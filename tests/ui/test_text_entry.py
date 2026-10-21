import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from schemeup.application.editor import EditorSession
from schemeup.domain import commands
from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.geometry import Point, Size
from schemeup.domain.style import FontFamily, Style, TextAlign
from schemeup.rendering.text import QtTextMeasurer, layout_text
from schemeup.ui.canvas.view import CanvasView
from schemeup.ui.main_window import MainWindow


def test_new_text_is_typed_at_the_selected_size(window: MainWindow) -> None:
    # The window carries the real application stylesheet, which sets a 13 px font
    # on every widget; the editor must still show the size picked in the panel.
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.session.set_style(font_size=36.0)
    canvas.create_text_at(Point(0, 0))

    editor = canvas.text_editor
    expected = round(36 * canvas.camera.zoom)
    assert editor.font().pixelSize() == expected
    assert editor.document().defaultFont().pixelSize() == expected
    assert editor.fontMetrics().height() > 13


def test_the_editor_size_follows_the_zoom(window: MainWindow) -> None:
    window.new_note(None, "blank")
    canvas = window.editor.canvas
    canvas.session.set_style(font_size=20.0)
    canvas.zoom_to(2.0)
    canvas.create_text_at(Point(0, 0))
    assert canvas.text_editor.font().pixelSize() == round(20 * canvas.camera.zoom)


def test_a_text_box_hugs_its_glyphs() -> None:
    one = layout_text("1", FontFamily.HAND, 40, None, TextAlign.LEFT)
    assert 0.7 * 40 < one.height < 1.1 * 40  # the font's own line is 1.34 times the size
    two = layout_text("1\n1", FontFamily.HAND, 40, None, TextAlign.LEFT)
    assert two.height - one.height == pytest.approx(one.line_height)


def ink_extent(image: QImage, region: QRect) -> tuple[int, int, int, int]:
    """First and last dark row and column inside `region`."""
    rows, cols = set(), set()
    for y in range(region.top(), region.bottom()):
        for x in range(region.left(), region.right()):
            if QColor(image.pixel(x, y)).lightness() < 120:
                rows.add(y)
                cols.add(x)
    return min(rows), max(rows), min(cols), max(cols)


@pytest.mark.parametrize("align", [TextAlign.LEFT, TextAlign.CENTER, TextAlign.RIGHT])
def test_typing_shows_the_text_where_it_will_be_drawn(
    qtbot: QtBot, qapp: QApplication, align: TextAlign
) -> None:
    session = EditorSession(Document(settings=CanvasSettings(sheet="plain")), QtTextMeasurer())
    view = CanvasView(session, reduce_motion=True)
    qtbot.addWidget(view)
    view.resize(600, 300)
    view.show()
    qtbot.waitExposed(view)
    view.set_camera(view.camera.centered_on(Point(150, 60), Size(600, 300), zoom=1.0))
    text = commands.make_text(Point(100, 40), "HEH", Style(font_size=48, text_align=align))
    session.add([text], select=False)

    origin = view.camera.to_screen(Point(100, 40))
    region = QRect(int(origin.x) - 20, 60, 160, 140)  # clear of the zoom label and the caret
    drawn = ink_extent(view.grab().toImage(), region)
    view.edit_text(text.id)
    view.text_editor.moveCursor(QTextCursor.MoveOperation.Start)  # keep the caret off the glyphs
    typed = ink_extent(view.grab().toImage(), region)
    assert abs(typed[0] - drawn[0]) <= 1  # top of the letters
    assert abs(typed[1] - drawn[1]) <= 1  # bottom
    assert abs(typed[2] - drawn[2]) <= 1  # left edge


def test_finishing_the_title_does_not_steal_focus_from_a_text_being_typed(
    window: MainWindow,
) -> None:
    window.new_note(None, "blank")  # leaves the cursor in the title
    canvas = window.editor.canvas
    canvas.create_text_at(Point(0, 0))
    assert canvas.text_editor.element_id is not None
