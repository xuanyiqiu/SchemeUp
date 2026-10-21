"""The library repository on top of SQLite.

Every operation that changes more than one row runs in one transaction, so a
move, a save or a trash can't half-happen. The FTS index is updated in the
same transaction as the content it indexes.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime

from schemeup.domain.document import Document
from schemeup.domain.errors import ConflictError, NotFoundError, StorageError
from schemeup.domain.export_layout import searchable_text
from schemeup.domain.library import (
    Activity,
    Board,
    Card,
    Column,
    Folder,
    NoteInfo,
    SearchHit,
    Tag,
)
from schemeup.domain.serialization import CURRENT_VERSION, document_from_dict, document_to_dict
from schemeup.infrastructure.database import Database

ROOT_NAME = "Library"
HIT_START, HIT_END = "\u0001", "\u0002"


def local_day(millis: int) -> str:
    return datetime.fromtimestamp(millis / 1000).strftime("%Y-%m-%d")


def fts_query(text: str) -> str:
    """User input to an FTS5 query: every word must match, the last one as a prefix."""
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if not words:
        return ""
    quoted = [f'"{w}"' for w in words[:-1]] + [f'"{words[-1]}"*']
    return " ".join(quoted)


def _folder(row: sqlite3.Row) -> Folder:
    return Folder(
        id=row["id"],
        uuid=row["uuid"],
        parent_id=row["parent_id"],
        name=row["name"],
        position=row["position"],
        created_at=row["created_at"],
        trashed_at=row["trashed_at"],
    )


class SqliteLibrary:
    def __init__(self, db: Database, day_of: Callable[[int], str] = local_day) -> None:
        self._db = db
        self._day_of = day_of
        self._ensure_root()

    @property
    def database(self) -> Database:
        return self._db

    # Helpers

    def _ensure_root(self) -> None:
        if self._db.query_one("SELECT id FROM folders WHERE parent_id IS NULL") is None:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO folders (uuid, parent_id, name, position, created_at) VALUES (?, NULL, ?, 0, ?)",
                    (uuid.uuid4().hex, ROOT_NAME, int(time.time() * 1000)),
                )

    def _tags_by_note(self, note_ids: Iterable[int]) -> dict[int, tuple[str, ...]]:
        ids = list(note_ids)
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._db.query(
            f"SELECT nt.note_id, t.name FROM note_tags nt JOIN tags t ON t.id = nt.tag_id "
            f"WHERE nt.note_id IN ({marks}) ORDER BY t.name COLLATE NOCASE",
            ids,
        )
        result: dict[int, list[str]] = {}
        for row in rows:
            result.setdefault(row["note_id"], []).append(row["name"])
        return {k: tuple(v) for k, v in result.items()}

    def _notes(self, rows: list[sqlite3.Row]) -> list[NoteInfo]:
        tags = self._tags_by_note(r["id"] for r in rows)
        return [
            NoteInfo(
                id=r["id"],
                uuid=r["uuid"],
                folder_id=r["folder_id"],
                title=r["title"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                size_bytes=r["size_bytes"],
                trashed_at=r["trashed_at"],
                tags=tags.get(r["id"], ()),
            )
            for r in rows
        ]

    def _reindex(self, note_id: int) -> None:
        row = self._db.query_one(
            "SELECT n.title, d.plain_text FROM notes n JOIN note_documents d ON d.note_id = n.id WHERE n.id = ?",
            (note_id,),
        )
        if row is None:
            return
        tags = " ".join(self._tags_by_note([note_id]).get(note_id, ()))
        self._db.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        self._db.execute(
            "INSERT INTO notes_fts (rowid, title, body, tags) VALUES (?, ?, ?, ?)",
            (note_id, row["title"], row["plain_text"], tags),
        )

    def _touch_activity(self, note_id: int, at: int) -> None:
        self._db.execute(
            "INSERT INTO note_activity (note_id, day, edits) VALUES (?, ?, 1) "
            "ON CONFLICT (note_id, day) DO UPDATE SET edits = edits + 1",
            (note_id, self._day_of(at)),
        )

    def _subtree(self, folder_id: int) -> list[int]:
        rows = self._db.query(
            "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL "
            "SELECT f.id FROM folders f JOIN tree ON f.parent_id = tree.id) SELECT id FROM tree",
            (folder_id,),
        )
        return [r["id"] for r in rows]

    # Folders

    def root_folder(self) -> Folder:
        row = self._db.query_one("SELECT * FROM folders WHERE parent_id IS NULL")
        assert row is not None
        return _folder(row)

    def folders(self, include_trashed: bool = False) -> list[Folder]:
        where = "" if include_trashed else "WHERE trashed_at IS NULL"
        rows = self._db.query(
            f"SELECT * FROM folders {where} ORDER BY position, name COLLATE NOCASE"
        )
        return [_folder(r) for r in rows]

    def folder(self, folder_id: int) -> Folder:
        row = self._db.query_one("SELECT * FROM folders WHERE id = ?", (folder_id,))
        if row is None:
            raise NotFoundError(f"folder {folder_id} not found")
        return _folder(row)

    def find_folder(self, parent_id: int, name: str) -> Folder | None:
        row = self._db.query_one(
            "SELECT * FROM folders WHERE parent_id = ? AND name = ? COLLATE NOCASE AND trashed_at IS NULL",
            (parent_id, name),
        )
        return _folder(row) if row else None

    def create_folder(self, parent_id: int, name: str, at: int) -> Folder:
        try:
            with self._db.transaction():
                cursor = self._db.execute(
                    "INSERT INTO folders (uuid, parent_id, name, position, created_at) VALUES (?, ?, ?, 0, ?)",
                    (uuid.uuid4().hex, parent_id, name, at),
                )
        except sqlite3.IntegrityError as error:
            raise ConflictError(f"a folder called {name!r} already exists here") from error
        return self.folder(int(cursor.lastrowid or 0))

    def rename_folder(self, folder_id: int, name: str) -> None:
        try:
            with self._db.transaction():
                self._db.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id))
        except sqlite3.IntegrityError as error:
            raise ConflictError(f"a folder called {name!r} already exists here") from error

    def move_folder(self, folder_id: int, parent_id: int) -> None:
        if parent_id in self._subtree(folder_id):
            raise ConflictError("a folder can't move inside itself")
        try:
            with self._db.transaction():
                self._db.execute(
                    "UPDATE folders SET parent_id = ? WHERE id = ?", (parent_id, folder_id)
                )
        except sqlite3.IntegrityError as error:
            raise ConflictError("the destination already has a folder with that name") from error

    def trash_folder(self, folder_id: int, at: int) -> None:
        if self.folder(folder_id).is_root:
            raise ConflictError("the library root can't be deleted")
        ids = self._subtree(folder_id)
        marks = ",".join("?" * len(ids))
        with self._db.transaction():
            self._db.execute(
                f"UPDATE folders SET trashed_at = ? WHERE id IN ({marks}) AND trashed_at IS NULL",
                [at, *ids],
            )
            self._db.execute(
                f"UPDATE notes SET trashed_at = ? WHERE folder_id IN ({marks}) AND trashed_at IS NULL",
                [at, *ids],
            )

    def restore_folder(self, folder_id: int) -> None:
        folder = self.folder(folder_id)
        if folder.trashed_at is None:
            return
        batch = folder.trashed_at
        ids = self._subtree(folder_id)
        marks = ",".join("?" * len(ids))
        with self._db.transaction():
            parent = self.folder(folder.parent_id) if folder.parent_id is not None else None
            if parent is not None and parent.trashed_at is not None:
                self._db.execute(
                    "UPDATE folders SET parent_id = ? WHERE id = ?",
                    (self.root_folder().id, folder_id),
                )
            try:
                self._db.execute(
                    f"UPDATE folders SET trashed_at = NULL WHERE id IN ({marks}) AND trashed_at = ?",
                    [*ids, batch],
                )
            except sqlite3.IntegrityError:
                self._db.execute(
                    "UPDATE folders SET name = name || ' (restored)' WHERE id = ?", (folder_id,)
                )
                self._db.execute(
                    f"UPDATE folders SET trashed_at = NULL WHERE id IN ({marks}) AND trashed_at = ?",
                    [*ids, batch],
                )
            self._db.execute(
                f"UPDATE notes SET trashed_at = NULL WHERE folder_id IN ({marks}) AND trashed_at = ?",
                [*ids, batch],
            )

    def delete_folder_forever(self, folder_id: int) -> None:
        ids = self._subtree(folder_id)
        marks = ",".join("?" * len(ids))
        with self._db.transaction():
            notes = [
                r["id"]
                for r in self._db.query(f"SELECT id FROM notes WHERE folder_id IN ({marks})", ids)
            ]
            for note_id in notes:
                self._db.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
            self._db.execute(f"DELETE FROM notes WHERE folder_id IN ({marks})", ids)
            self._db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

    # Notes

    def notes(self, folder_id: int | None = None) -> list[NoteInfo]:
        if folder_id is None:
            rows = self._db.query(
                "SELECT * FROM notes WHERE trashed_at IS NULL ORDER BY updated_at DESC"
            )
        else:
            rows = self._db.query(
                "SELECT * FROM notes WHERE folder_id = ? AND trashed_at IS NULL ORDER BY updated_at DESC",
                (folder_id,),
            )
        return self._notes(rows)

    def note(self, note_id: int) -> NoteInfo:
        row = self._db.query_one("SELECT * FROM notes WHERE id = ?", (note_id,))
        if row is None:
            raise NotFoundError(f"note {note_id} not found")
        return self._notes([row])[0]

    def note_by_uuid(self, note_uuid: str) -> NoteInfo | None:
        row = self._db.query_one("SELECT * FROM notes WHERE uuid = ?", (note_uuid,))
        return self._notes([row])[0] if row else None

    def create_note(self, folder_id: int, title: str, document: Document, at: int) -> NoteInfo:
        body = json.dumps(document_to_dict(document), separators=(",", ":"), ensure_ascii=False)
        with self._db.transaction():
            cursor = self._db.execute(
                "INSERT INTO notes (uuid, folder_id, title, created_at, updated_at, size_bytes) VALUES (?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, folder_id, title, at, at, len(body.encode("utf-8"))),
            )
            note_id = int(cursor.lastrowid or 0)
            self._db.execute(
                "INSERT INTO note_documents (note_id, schema_version, body, plain_text) VALUES (?, ?, ?, ?)",
                (note_id, CURRENT_VERSION, body, searchable_text(document)),
            )
            self._reindex(note_id)
            self._touch_activity(note_id, at)
        return self.note(note_id)

    def load_document(self, note_id: int) -> Document:
        row = self._db.query_one("SELECT body FROM note_documents WHERE note_id = ?", (note_id,))
        if row is None:
            raise NotFoundError(f"note {note_id} has no content")
        try:
            return document_from_dict(json.loads(row["body"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise StorageError(f"note {note_id} is damaged: {error}") from error

    def save_document(self, note_id: int, document: Document, at: int) -> None:
        body = json.dumps(document_to_dict(document), separators=(",", ":"), ensure_ascii=False)
        with self._db.transaction():
            self._db.execute(
                "UPDATE note_documents SET schema_version = ?, body = ?, plain_text = ? WHERE note_id = ?",
                (CURRENT_VERSION, body, searchable_text(document), note_id),
            )
            self._db.execute(
                "UPDATE notes SET updated_at = ?, size_bytes = ? WHERE id = ?",
                (at, len(body.encode("utf-8")), note_id),
            )
            self._reindex(note_id)
            self._touch_activity(note_id, at)

    def rename_note(self, note_id: int, title: str, at: int) -> None:
        with self._db.transaction():
            self._db.execute(
                "UPDATE notes SET title = ?, updated_at = ? WHERE id = ?", (title, at, note_id)
            )
            self._reindex(note_id)

    def move_note(self, note_id: int, folder_id: int) -> None:
        with self._db.transaction():
            self._db.execute("UPDATE notes SET folder_id = ? WHERE id = ?", (folder_id, note_id))

    def trash_note(self, note_id: int, at: int) -> None:
        with self._db.transaction():
            self._db.execute("UPDATE notes SET trashed_at = ? WHERE id = ?", (at, note_id))

    def restore_note(self, note_id: int) -> None:
        note = self.note(note_id)
        with self._db.transaction():
            if self.folder(note.folder_id).trashed_at is not None:
                self._db.execute(
                    "UPDATE notes SET folder_id = ? WHERE id = ?", (self.root_folder().id, note_id)
                )
            self._db.execute("UPDATE notes SET trashed_at = NULL WHERE id = ?", (note_id,))

    def delete_note_forever(self, note_id: int) -> None:
        with self._db.transaction():
            self._db.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
            self._db.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def trashed_notes(self) -> list[NoteInfo]:
        return self._notes(
            self._db.query(
                "SELECT * FROM notes WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC"
            )
        )

    def trashed_folders(self) -> list[Folder]:
        rows = self._db.query(
            "SELECT f.* FROM folders f LEFT JOIN folders p ON p.id = f.parent_id "
            "WHERE f.trashed_at IS NOT NULL AND (p.trashed_at IS NULL OR p.trashed_at != f.trashed_at) "
            "ORDER BY f.trashed_at DESC"
        )
        return [_folder(r) for r in rows]

    def empty_trash(self, older_than: int | None = None) -> int:
        limit = older_than if older_than is not None else 2**62
        folders = [f for f in self.trashed_folders() if (f.trashed_at or 0) <= limit]
        notes = [n for n in self.trashed_notes() if (n.trashed_at or 0) <= limit]
        with self._db.transaction():
            for note in notes:
                self.delete_note_forever(note.id)
            for folder in folders:
                self.delete_folder_forever(folder.id)
        return len(notes) + len(folders)

    # Search

    def search(self, text: str, limit: int = 50) -> list[SearchHit]:
        query = fts_query(text)
        if not query:
            return []
        try:
            rows = self._db.query(
                "SELECT n.*, snippet(notes_fts, 1, ?, ?, '…', 10) AS snip FROM notes_fts "
                "JOIN notes n ON n.id = notes_fts.rowid "
                "WHERE notes_fts MATCH ? AND n.trashed_at IS NULL "
                "ORDER BY bm25(notes_fts, 10.0, 1.0, 4.0) LIMIT ?",
                (HIT_START, HIT_END, query, limit),
            )
        except StorageError:
            return []
        notes = self._notes(rows)
        return [SearchHit(note, row["snip"] or "") for note, row in zip(notes, rows, strict=True)]

    # Tags

    def tags(self) -> list[Tag]:
        rows = self._db.query(
            "SELECT t.id, t.name, t.color, COUNT(n.id) AS count FROM tags t "
            "LEFT JOIN note_tags nt ON nt.tag_id = t.id "
            "LEFT JOIN notes n ON n.id = nt.note_id AND n.trashed_at IS NULL "
            "GROUP BY t.id ORDER BY t.name COLLATE NOCASE"
        )
        return [Tag(r["id"], r["name"], r["color"], r["count"]) for r in rows]

    def set_note_tags(self, note_id: int, names: Iterable[str]) -> None:
        clean = sorted(
            {n.strip().lstrip("#") for n in names if n.strip().lstrip("#")}, key=str.lower
        )
        with self._db.transaction():
            self._db.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
            for name in clean:
                self._db.execute(
                    "INSERT INTO tags (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (name,)
                )
                row = self._db.query_one("SELECT id FROM tags WHERE name = ?", (name,))
                assert row is not None
                self._db.execute(
                    "INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)", (note_id, row["id"])
                )
            self._db.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM note_tags)")
            self._reindex(note_id)

    def notes_with_tag(self, name: str) -> list[NoteInfo]:
        rows = self._db.query(
            "SELECT n.* FROM notes n JOIN note_tags nt ON nt.note_id = n.id JOIN tags t ON t.id = nt.tag_id "
            "WHERE t.name = ? AND n.trashed_at IS NULL ORDER BY n.updated_at DESC",
            (name,),
        )
        return self._notes(rows)

    # Boards

    def boards(self) -> list[Board]:
        rows = self._db.query("SELECT * FROM boards ORDER BY position, id")
        return [Board(r["id"], r["name"], r["position"], r["created_at"]) for r in rows]

    def board(self, board_id: int) -> Board:
        row = self._db.query_one("SELECT * FROM boards WHERE id = ?", (board_id,))
        if row is None:
            raise NotFoundError(f"board {board_id} not found")
        return Board(row["id"], row["name"], row["position"], row["created_at"])

    def create_board(self, name: str, columns: Iterable[str], at: int) -> Board:
        with self._db.transaction():
            position = self._db.query_one("SELECT COALESCE(MAX(position) + 1, 0) AS p FROM boards")
            cursor = self._db.execute(
                "INSERT INTO boards (name, position, created_at) VALUES (?, ?, ?)",
                (name, position["p"] if position else 0, at),
            )
            board_id = int(cursor.lastrowid or 0)
            for i, column in enumerate(columns):
                self._db.execute(
                    "INSERT INTO board_columns (board_id, name, position) VALUES (?, ?, ?)",
                    (board_id, column, i),
                )
        return self.board(board_id)

    def rename_board(self, board_id: int, name: str) -> None:
        with self._db.transaction():
            self._db.execute("UPDATE boards SET name = ? WHERE id = ?", (name, board_id))

    def delete_board(self, board_id: int) -> None:
        with self._db.transaction():
            self._db.execute("DELETE FROM board_cards WHERE board_id = ?", (board_id,))
            self._db.execute("DELETE FROM boards WHERE id = ?", (board_id,))

    def columns(self, board_id: int) -> list[Column]:
        rows = self._db.query(
            "SELECT * FROM board_columns WHERE board_id = ? ORDER BY position, id", (board_id,)
        )
        return [Column(r["id"], r["board_id"], r["name"], r["position"]) for r in rows]

    def add_column(self, board_id: int, name: str) -> Column:
        with self._db.transaction():
            position = self._db.query_one(
                "SELECT COALESCE(MAX(position) + 1, 0) AS p FROM board_columns WHERE board_id = ?",
                (board_id,),
            )
            cursor = self._db.execute(
                "INSERT INTO board_columns (board_id, name, position) VALUES (?, ?, ?)",
                (board_id, name, position["p"] if position else 0),
            )
        column_id = int(cursor.lastrowid or 0)
        return next(c for c in self.columns(board_id) if c.id == column_id)

    def rename_column(self, column_id: int, name: str) -> None:
        with self._db.transaction():
            self._db.execute("UPDATE board_columns SET name = ? WHERE id = ?", (name, column_id))

    def delete_column(self, column_id: int) -> None:
        with self._db.transaction():
            self._db.execute("DELETE FROM board_columns WHERE id = ?", (column_id,))

    def move_column(self, board_id: int, column_id: int, index: int) -> None:
        ids = [c.id for c in self.columns(board_id) if c.id != column_id]
        ids.insert(max(0, min(index, len(ids))), column_id)
        with self._db.transaction():
            for position, cid in enumerate(ids):
                self._db.execute(
                    "UPDATE board_columns SET position = ? WHERE id = ?", (position, cid)
                )

    def cards(self, board_id: int) -> list[Card]:
        rows = self._db.query(
            "SELECT c.* FROM board_cards c JOIN notes n ON n.id = c.note_id "
            "WHERE c.board_id = ? AND n.trashed_at IS NULL ORDER BY c.column_id, c.position",
            (board_id,),
        )
        return [Card(r["board_id"], r["note_id"], r["column_id"], r["position"]) for r in rows]

    def move_card(
        self, board_id: int, note_id: int, column_id: int, index: int | None = None
    ) -> None:
        """Put a note's card in `column_id` at `index` (the end by default), adding it if needed."""
        with self._db.transaction():
            current = self._db.query_one(
                "SELECT column_id FROM board_cards WHERE board_id = ? AND note_id = ?",
                (board_id, note_id),
            )
            self._db.execute(
                "DELETE FROM board_cards WHERE board_id = ? AND note_id = ?", (board_id, note_id)
            )
            target = [
                r["note_id"]
                for r in self._db.query(
                    "SELECT note_id FROM board_cards WHERE column_id = ? ORDER BY position",
                    (column_id,),
                )
            ]
            target.insert(
                len(target) if index is None else max(0, min(index, len(target))), note_id
            )
            for position, nid in enumerate(target):
                if nid == note_id:
                    self._db.execute(
                        "INSERT INTO board_cards (board_id, note_id, column_id, position) VALUES (?, ?, ?, ?)",
                        (board_id, note_id, column_id, position),
                    )
                else:
                    self._db.execute(
                        "UPDATE board_cards SET position = ? WHERE board_id = ? AND note_id = ?",
                        (position, board_id, nid),
                    )
            if current is not None and current["column_id"] != column_id:
                rest = self._db.query(
                    "SELECT note_id FROM board_cards WHERE column_id = ? ORDER BY position",
                    (current["column_id"],),
                )
                for position, row in enumerate(rest):
                    self._db.execute(
                        "UPDATE board_cards SET position = ? WHERE board_id = ? AND note_id = ?",
                        (position, board_id, row["note_id"]),
                    )

    def remove_card(self, board_id: int, note_id: int) -> None:
        with self._db.transaction():
            self._db.execute(
                "DELETE FROM board_cards WHERE board_id = ? AND note_id = ?", (board_id, note_id)
            )

    def boards_for_note(self, note_id: int) -> list[Board]:
        rows = self._db.query(
            "SELECT b.* FROM boards b JOIN board_cards c ON c.board_id = b.id WHERE c.note_id = ? ORDER BY b.position",
            (note_id,),
        )
        return [Board(r["id"], r["name"], r["position"], r["created_at"]) for r in rows]

    # Calendar

    def notes_created_between(self, start: int, end: int) -> list[NoteInfo]:
        rows = self._db.query(
            "SELECT * FROM notes WHERE created_at >= ? AND created_at < ? AND trashed_at IS NULL ORDER BY created_at",
            (start, end),
        )
        return self._notes(rows)

    def activity_between(self, first_day: str, last_day: str) -> list[Activity]:
        rows = self._db.query(
            "SELECT a.* FROM note_activity a JOIN notes n ON n.id = a.note_id "
            "WHERE a.day >= ? AND a.day <= ? AND n.trashed_at IS NULL ORDER BY a.day",
            (first_day, last_day),
        )
        return [Activity(r["note_id"], r["day"], r["edits"]) for r in rows]


class SqliteAssetStore:
    """Images stored once in the library, keyed by the SHA-256 of their bytes."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, bytes] = {}

    def put(self, data: bytes, mime: str) -> str:
        import hashlib

        asset_id = hashlib.sha256(data).hexdigest()
        with self._db.transaction():
            self._db.execute(
                "INSERT INTO assets (sha256, mime, data, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (sha256) DO NOTHING",
                (asset_id, mime, data, int(time.time() * 1000)),
            )
        self._cache[asset_id] = data
        return asset_id

    def get(self, asset_id: str) -> bytes | None:
        if asset_id in self._cache:
            return self._cache[asset_id]
        row = self._db.query_one("SELECT data FROM assets WHERE sha256 = ?", (asset_id,))
        if row is None:
            return None
        data = bytes(row["data"])
        self._cache[asset_id] = data
        return data
