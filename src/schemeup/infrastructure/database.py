"""The SQLite library file: connection, pragmas, migrations and transactions."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from schemeup.domain.errors import StorageError

SCHEMA_V1 = """
CREATE TABLE folders (
    id          INTEGER PRIMARY KEY,
    uuid        TEXT NOT NULL UNIQUE,
    parent_id   INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    trashed_at  INTEGER
);
CREATE UNIQUE INDEX folders_sibling_name
    ON folders(parent_id, name COLLATE NOCASE) WHERE trashed_at IS NULL;

CREATE TABLE notes (
    id          INTEGER PRIMARY KEY,
    uuid        TEXT NOT NULL UNIQUE,
    folder_id   INTEGER NOT NULL REFERENCES folders(id),
    title       TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    trashed_at  INTEGER,
    size_bytes  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX notes_folder ON notes(folder_id) WHERE trashed_at IS NULL;
CREATE INDEX notes_created ON notes(created_at);
CREATE INDEX notes_updated ON notes(updated_at);

CREATE TABLE note_documents (
    note_id         INTEGER PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    schema_version  INTEGER NOT NULL,
    body            TEXT NOT NULL,
    plain_text      TEXT NOT NULL
);

CREATE TABLE tags (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color  TEXT
);

CREATE TABLE note_tags (
    note_id  INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
) WITHOUT ROWID;

CREATE TABLE boards (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);

CREATE TABLE board_columns (
    id        INTEGER PRIMARY KEY,
    board_id  INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    position  INTEGER NOT NULL,
    UNIQUE (id, board_id)
);

CREATE TABLE board_cards (
    board_id   INTEGER NOT NULL,
    note_id    INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    column_id  INTEGER NOT NULL,
    position   INTEGER NOT NULL,
    PRIMARY KEY (board_id, note_id),
    FOREIGN KEY (column_id, board_id)
        REFERENCES board_columns(id, board_id) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE assets (
    sha256      TEXT PRIMARY KEY,
    mime        TEXT NOT NULL,
    data        BLOB NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE TABLE note_activity (
    note_id  INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    day      TEXT NOT NULL,
    edits    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (note_id, day)
) WITHOUT ROWID;
CREATE INDEX note_activity_day ON note_activity(day);

CREATE VIRTUAL TABLE notes_fts USING fts5(
    title, body, tags,
    tokenize = 'unicode61 remove_diacritics 2',
    prefix = '2 3'
);
"""

# Index i holds the script that upgrades the database from version i to i + 1.
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1,)
SCHEMA_VERSION = len(MIGRATIONS)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = path
        self._depth = 0
        try:
            self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        except sqlite3.Error as error:
            raise StorageError(f"cannot open the library at {path}: {error}") from error
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            # With WAL, NORMAL never corrupts the file; a power cut can only lose
            # the last transaction or two.
            self._conn.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    @property
    def version(self) -> int:
        return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def _migrate(self) -> None:
        current = self.version
        if current > SCHEMA_VERSION:
            raise StorageError(
                f"this library was created by a newer version of SchemeUp (schema {current})"
            )
        if current == SCHEMA_VERSION:
            return
        if current > 0 and str(self.path) != ":memory:":
            # Keep a copy of the old file in case a migration goes wrong.
            shutil.copy2(self.path, f"{self.path}.before-v{SCHEMA_VERSION}")
        for version in range(current, SCHEMA_VERSION):
            with self.transaction():
                self._run_script(MIGRATIONS[version])
                self._conn.execute(f"PRAGMA user_version = {version + 1}")

    def _run_script(self, script: str) -> None:
        # executescript() would commit our transaction, so statements run one by one.
        for statement in (s.strip() for s in script.split(";\n")):
            if statement:
                self._conn.execute(statement)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A write transaction; nested calls join the outer one."""
        if self._depth:
            self._depth += 1
            try:
                yield self._conn
            finally:
                self._depth -= 1
            return
        self._conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
        finally:
            self._depth = 0

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        try:
            return list(self._conn.execute(sql, params))
        except sqlite3.Error as error:
            raise StorageError(str(error)) from error

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        try:
            return self._conn.execute(sql, params)
        except sqlite3.IntegrityError:
            raise
        except sqlite3.Error as error:
            raise StorageError(str(error)) from error

    def quick_check(self) -> bool:
        row = self._conn.execute("PRAGMA quick_check").fetchone()
        return row is not None and row[0] == "ok"

    def backup_to(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(str(target))
        try:
            self._conn.backup(destination)
        finally:
            destination.close()

    def close(self) -> None:
        self._conn.close()
