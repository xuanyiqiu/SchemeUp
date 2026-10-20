from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from schemeup.application.library import EventKind, LibraryEvent, LibraryService
from schemeup.application.settings import Settings
from schemeup.domain import commands
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import Rectangle
from schemeup.domain.errors import ConflictError, StorageError
from schemeup.domain.geometry import Rect
from schemeup.domain.library import INBOX
from schemeup.domain.style import Style
from schemeup.infrastructure.backup import Backups
from schemeup.infrastructure.database import SCHEMA_VERSION, Database
from schemeup.infrastructure.library_store import SqliteAssetStore, SqliteLibrary, fts_query
from schemeup.infrastructure.settings_store import JsonSettingsStore
from tests.unit.domain.conftest import FakeMeasurer

TZ = timezone(timedelta(hours=2))


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 10, 20, 9, 30, tzinfo=TZ))


@pytest.fixture
def repo() -> SqliteLibrary:
    return SqliteLibrary(
        Database(":memory:"),
        day_of=lambda ms: datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d"),
    )


@pytest.fixture
def library(repo: SqliteLibrary, clock: FixedClock) -> LibraryService:
    return LibraryService(repo, FakeMeasurer(), clock)


def test_schema_is_created_and_versioned() -> None:
    db = Database(":memory:")
    assert db.version == SCHEMA_VERSION
    assert db.quick_check()


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite3"
    db = Database(path)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    db.close()
    with pytest.raises(StorageError):
        Database(path)


def test_notes_live_in_the_inbox_by_default(library: LibraryService) -> None:
    note = library.create_note()
    assert library.folder(note.folder_id).name == INBOX
    assert note.title == "Note 2026-10-20 09:30"


def test_templates_produce_sized_documents(library: LibraryService) -> None:
    note = library.create_note(template_id="leetcode")
    document = library.open_document(note.id)
    assert len(document) > 3
    assert all(e.width > 0 for e in document.ordered())


def test_saving_round_trips_the_document(library: LibraryService, clock: FixedClock) -> None:
    note = library.create_note()
    shape = commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 0, 100, 50), Style())
    clock.advance(minutes=5)
    library.save_document(note.id, Document.of([shape]))
    assert library.open_document(note.id).ordered() == [shape]
    saved = library.note(note.id)
    assert saved.updated_at > saved.created_at
    assert saved.size_bytes > 0


def test_events_are_published(library: LibraryService) -> None:
    seen: list[LibraryEvent] = []
    library.events.subscribe(seen.append)
    note = library.create_note()
    library.rename_note(note.id, "Renamed")
    assert [e.kind for e in seen if e.note_id == note.id] == [EventKind.NOTES, EventKind.NOTES]


def test_folders_tree_moves_and_conflicts(library: LibraryService) -> None:
    work = library.create_folder(None, "Work")
    meetings = library.create_folder(work.id, "Meetings")
    same_name = library.create_folder(work.id, "Meetings")
    assert same_name.name == "Meetings 2"
    with pytest.raises(ConflictError):
        library.move_folder(work.id, meetings.id)  # a folder can't go inside itself
    with pytest.raises(ConflictError):
        library.rename_folder(same_name.id, "Meetings")


def test_trash_and_restore_a_folder_with_its_notes(library: LibraryService) -> None:
    folder = library.create_folder(None, "Old")
    note = library.create_note(folder.id)
    library.trash_folder(folder.id)
    assert note.id not in {n.id for n in library.notes()}
    folders, notes = library.trash()
    assert [f.id for f in folders] == [folder.id]
    assert [n.id for n in notes] == [note.id]
    library.restore_folder(folder.id)
    assert note.id in {n.id for n in library.notes(folder.id)}


def test_restoring_a_note_whose_folder_is_gone_puts_it_at_the_top(library: LibraryService) -> None:
    folder = library.create_folder(None, "Temp")
    note = library.create_note(folder.id)
    library.trash_note(note.id)
    library.trash_folder(folder.id)
    library.restore_note(note.id)
    assert library.note(note.id).folder_id == library.root().id


def test_old_trash_is_purged(library: LibraryService, clock: FixedClock) -> None:
    note = library.create_note()
    library.trash_note(note.id)
    clock.advance(days=31)
    assert library.purge_old_trash() == 1
    assert library.trash() == ([], [])


def test_search_finds_text_inside_drawings(library: LibraryService) -> None:
    note = library.create_note(title="Graph problems")
    shape = commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 0, 100, 50), Style())
    assert isinstance(shape, Rectangle)
    labelled = replace(shape, label="Dijkstra con montículo")
    library.save_document(note.id, Document.of([labelled]))
    assert [h.note.id for h in library.search("dijk")] == [note.id]  # prefix match
    assert [h.note.id for h in library.search("monticulo")] == [note.id]  # accents ignored
    assert library.search("graph")[0].note.id == note.id  # title match
    assert library.search("nothing here") == []


def test_search_ignores_trashed_notes(library: LibraryService) -> None:
    note = library.create_note(title="Secret plan")
    library.trash_note(note.id)
    assert library.search("secret") == []


def test_fts_query_quotes_words() -> None:
    assert fts_query('two "pointers" AND') == '"two" "pointers" "AND"*'
    assert fts_query("  ") == ""


def test_tags(library: LibraryService) -> None:
    a = library.create_note(title="A")
    b = library.create_note(title="B")
    library.set_tags(a.id, ["graphs", "#bfs", "graphs"])
    library.set_tags(b.id, ["graphs"])
    assert library.note(a.id).tags == ("bfs", "graphs")
    assert {t.name: t.count for t in library.tags()} == {"bfs": 1, "graphs": 2}
    library.set_tags(a.id, [])
    assert [t.name for t in library.tags()] == ["graphs"]  # unused tags disappear
    assert [n.id for n in library.notes_with_tag("graphs")] == [b.id]
    assert library.search("graphs")[0].note.id == b.id


def test_board_cards_reference_notes_without_copying(library: LibraryService) -> None:
    board = library.create_board("Interview prep")
    todo, doing, done = library.columns(board.id)
    a = library.create_note(title="A")
    b = library.create_note(title="B")
    library.place_card(board.id, a.id, todo.id)
    library.place_card(board.id, b.id, todo.id)
    library.place_card(board.id, b.id, todo.id, 0)  # reorder: B first
    assert [c.note_id for c in library.cards(board.id) if c.column_id == todo.id] == [b.id, a.id]
    library.place_card(board.id, a.id, done.id)  # move across columns
    cards = library.cards(board.id)
    assert {c.note_id: c.column_id for c in cards} == {b.id: todo.id, a.id: done.id}
    assert len(cards) == 2  # still one card per note per board
    assert [x.id for x in library.boards_for_note(a.id)] == [board.id]
    library.trash_note(a.id)
    assert [c.note_id for c in library.cards(board.id)] == [b.id]
    del doing


def test_deleting_a_column_removes_its_cards(library: LibraryService) -> None:
    board = library.create_board("B", ["One", "Two"])
    one, _ = library.columns(board.id)
    note = library.create_note()
    library.place_card(board.id, note.id, one.id)
    library.delete_column(one.id)
    assert library.cards(board.id) == []


def test_calendar_groups_created_and_edited_notes(
    library: LibraryService, clock: FixedClock
) -> None:
    first = library.create_note(title="Monday")
    clock.advance(days=1)
    library.create_note(title="Tuesday")
    library.save_document(first.id, Document())
    days = library.calendar(datetime(2026, 10, 19).date(), datetime(2026, 10, 25).date())
    monday, tuesday = days[datetime(2026, 10, 20).date()], days[datetime(2026, 10, 21).date()]
    assert [n.title for n in monday.created] == ["Monday"]
    assert [n.title for n in tuesday.created] == ["Tuesday"]
    assert [n.title for n in tuesday.edited] == ["Monday"]
    assert tuesday.count == 2


def test_capture_files_text_in_the_inbox(library: LibraryService) -> None:
    note = library.capture("call the dentist")
    assert note is not None
    assert library.folder(note.folder_id).name == INBOX
    assert "dentist" in library.open_document(note.id).plain_text()
    assert library.capture("   ") is None


def test_duplicate_keeps_content_and_tags(library: LibraryService) -> None:
    note = library.create_note(template_id="meeting", title="Standup")
    library.set_tags(note.id, ["work"])
    copy = library.duplicate_note(note.id)
    assert copy.title == "Standup (copy)"
    assert copy.tags == ("work",)
    assert len(library.open_document(copy.id)) == len(library.open_document(note.id))


def test_assets_are_stored_once(repo: SqliteLibrary) -> None:
    store = SqliteAssetStore(repo.database)
    first = store.put(b"png bytes", "image/png")
    assert store.put(b"png bytes", "image/png") == first
    assert SqliteAssetStore(repo.database).get(first) == b"png bytes"
    assert store.get("missing") is None


def test_settings_survive_a_round_trip_and_bad_files(tmp_path: Path) -> None:
    store = JsonSettingsStore(tmp_path / "settings.json")
    assert store.load() == Settings()
    store.save(Settings(theme="dark", last_note_id=7, hotkey="Ctrl+Shift+Space"))
    loaded = store.load()
    assert (loaded.theme, loaded.last_note_id, loaded.hotkey) == ("dark", 7, "Ctrl+Shift+Space")
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert store.load() == Settings()


def test_backups_run_daily_and_keep_a_few(tmp_path: Path) -> None:
    db = Database(tmp_path / "library.sqlite3")
    SqliteLibrary(db)
    backups = Backups(db, tmp_path / "backups", keep=2)
    now = datetime(2026, 10, 20, 10, 0)
    assert backups.run_if_due(now) is not None
    assert backups.run_if_due(now + timedelta(hours=1)) is None
    for i in range(3):
        backups.run(now + timedelta(days=i + 1))
    files = backups.existing()
    assert len(files) == 2
    restored = Database(files[-1])
    assert restored.quick_check()
