from schemeup.domain.geometry import Point
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
