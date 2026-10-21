from pytestqt.qtbot import QtBot

from schemeup.application.library import LibraryService
from schemeup.domain.elements import Rectangle
from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.main_window import MainWindow
from tests.ui.conftest import Mouse


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


def test_the_window_can_be_snapped_to_half_a_screen(window: MainWindow) -> None:
    # Windows' snap layouts honour the minimum size. 640 is half of a 1920 px
    # screen at 150 % scaling, the narrowest I want to support.
    for page in (window.welcome, window.editor, window.board_view, window.calendar_view):
        window.pages.setCurrentWidget(page)
        assert window.minimumSizeHint().width() <= 640, type(page).__name__
