from collections.abc import Iterator
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from schemeup.application.editor import EditorSession
from schemeup.application.library import LibraryService
from schemeup.application.settings import MemorySettingsStore, Settings
from schemeup.domain.document import Document
from schemeup.domain.elements import Rectangle
from schemeup.infrastructure.database import Database
from schemeup.infrastructure.library_store import SqliteAssetStore, SqliteLibrary
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.main_window import Environment, MainWindow
from tests.ui.conftest import Mouse


@pytest.fixture
def library() -> LibraryService:
    return LibraryService(SqliteLibrary(Database(":memory:")), QtTextMeasurer())


@pytest.fixture
def window(qtbot: QtBot, library: LibraryService, tmp_path: Any) -> Iterator[MainWindow]:
    store = MemorySettingsStore(Settings(close_to_tray=False, theme="light"))
    env = Environment(
        settings=store.load(),
        save_settings=store.save,
        library_path=tmp_path / "library.sqlite3",
        backups_dir=tmp_path / "backups",
        backup_now=lambda: None,
        register_hotkey=lambda _text: "",
        hotkey_supported=False,
        reduce_motion=True,
    )
    session = EditorSession(Document(), QtTextMeasurer())
    db = Database(":memory:")
    win = MainWindow(library, session, assets=SqliteAssetStore(db), env=env)
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win._quitting = True


def test_starts_on_the_welcome_page(window: MainWindow) -> None:
    assert window.pages.currentWidget() is window.welcome
    assert window.current_note is None


def test_editing_a_note_autosaves(
    qtbot: QtBot, window: MainWindow, library: LibraryService
) -> None:
    window.new_note(None, "blank")
    note = window.current_note
    assert note is not None
    canvas = window.editor.canvas
    canvas.set_snapping(False, False)
    canvas.set_tool(ToolKind.RECTANGLE)
    Mouse(canvas).drag(200, 200, 400, 300)
    qtbot.waitUntil(lambda: len(library.open_document(note.id)) == 1, timeout=3000)
    assert isinstance(library.open_document(note.id).ordered()[0], Rectangle)


def test_switching_notes_saves_the_previous_one(
    window: MainWindow, library: LibraryService
) -> None:
    window.new_note(None, "blank")
    first = window.current_note
    assert first is not None
    canvas = window.editor.canvas
    canvas.set_snapping(False, False)
    canvas.set_tool(ToolKind.ELLIPSE)
    Mouse(canvas).drag(200, 200, 300, 260)
    window.new_note(None, "blank")  # flushes before switching
    assert len(library.open_document(first.id)) == 1


def test_renaming_from_the_title_bar(window: MainWindow, library: LibraryService) -> None:
    window.new_note(None, "blank")
    note = window.current_note
    assert note is not None
    window.editor.title_edit.setText("Graph algorithms")
    window.editor.title_edit.editingFinished.emit()
    assert library.note(note.id).title == "Graph algorithms"


def test_trashing_the_open_note_closes_it(window: MainWindow, library: LibraryService) -> None:
    window.new_note(None, "meeting")
    note = window.current_note
    assert note is not None
    library.trash_note(note.id)
    assert window.current_note is None
    assert window.pages.currentWidget() is window.welcome


def test_quick_capture_files_a_note(window: MainWindow, library: LibraryService) -> None:
    window.capture.open()
    window.capture.body.insertPlainText("buy milk")
    window.capture.body.finish.emit(False)
    assert any("milk" in library.open_document(n.id).plain_text() for n in library.notes())


def test_theme_toggle(window: MainWindow) -> None:
    assert not window._theme.dark
    window.toggle_theme()
    assert window._theme.dark
