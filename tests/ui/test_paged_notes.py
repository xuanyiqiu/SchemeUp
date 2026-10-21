from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from schemeup.domain.document import CanvasSettings
from schemeup.domain.export_layout import pages_of
from schemeup.domain.geometry import Point, Size
from schemeup.ui.main_window import MainWindow


def shortcut_action(widget: QWidget, keys: str) -> QAction:
    return next(a for a in widget.actions() if QKeySequence(keys) in a.shortcuts())


def paged_note(window: MainWindow) -> MainWindow:
    window.new_note(None, "blank")
    window.editor.canvas.session.set_canvas_settings(CanvasSettings(page_size="A4"))
    return window


def test_ctrl_enter_adds_a_page_and_shows_it(window: MainWindow) -> None:
    canvas = paged_note(window).editor.canvas
    assert len(pages_of(canvas.session.document)) == 1
    shortcut_action(canvas, "Ctrl+Return").trigger()
    pages = pages_of(canvas.session.document)
    assert len(pages) == 2
    viewport = Size(canvas.width(), canvas.height())
    assert canvas.camera.visible_rect(viewport).intersects(pages[-1])


def test_ctrl_enter_does_nothing_on_an_infinite_canvas(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    shortcut_action(canvas, "Ctrl+Return").trigger()
    assert pages_of(canvas.session.document) == []


def test_typing_past_the_bottom_of_the_page_brings_a_new_page(window: MainWindow) -> None:
    canvas = paged_note(window).editor.canvas
    first = pages_of(canvas.session.document)[0]
    canvas.create_text_at(Point(0, first.bottom - 60))
    for _ in range(8):
        canvas.text_editor.insertPlainText("line\n")
    assert len(pages_of(canvas.session.document, canvas._editing_bottom())) == 2
    canvas.text_editor.commit()
    assert len(pages_of(canvas.session.document)) == 2


def test_the_palette_offers_to_add_a_page_only_on_paged_notes(window: MainWindow) -> None:
    window.new_note(None, "blank")
    assert "Add a page" not in [c.title for c in window._commands()]
    window.editor.canvas.session.set_canvas_settings(CanvasSettings(page_size="A5"))
    assert "Add a page" in [c.title for c in window._commands()]
