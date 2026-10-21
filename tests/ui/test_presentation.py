from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from schemeup.domain import commands
from schemeup.domain.commands import ShapeKind
from schemeup.domain.elements import Frame
from schemeup.domain.geometry import Rect, Size
from schemeup.domain.style import Style
from schemeup.ui.editor_page import Chrome
from schemeup.ui.main_window import MainWindow
from tests.ui.conftest import Mouse, press


def slide(name: str, x: float) -> Frame:
    element = commands.make_shape(ShapeKind.FRAME, Rect(x, 0, 480, 270), Style())
    assert isinstance(element, Frame)
    return replace(element, name=name)


@pytest.fixture
def deck(window: MainWindow) -> MainWindow:
    window.new_note(None, "blank")
    session = window.editor.canvas.session
    session.add([slide("Intro", 0), slide("Design", 600), slide("Demo", 1200)], select=False)
    session.select([session.document.ordered()[0].id])  # the show starts from the selected frame
    return window


def test_a_note_without_frames_explains_what_to_do(window: MainWindow) -> None:
    window.new_note(None, "blank")
    window.start_presentation()
    assert not window.presentation.active
    assert window.toast.isVisible()


def test_presenting_hides_the_interface_and_goes_fullscreen(deck: MainWindow) -> None:
    deck.start_presentation()
    assert deck.presentation.active
    assert deck.isFullScreen()
    assert not deck.sidebar.isVisible()
    assert not deck.editor.title_bar.isVisible()
    assert deck.editor.chrome.value == Chrome.NONE.value

    deck.presentation.stop()
    assert not deck.isFullScreen()
    assert deck.sidebar.isVisible()
    assert deck.editor.title_bar.isVisible()


def test_the_show_starts_from_the_selected_frame(deck: MainWindow) -> None:
    session = deck.editor.canvas.session
    session.select([session.document.ordered()[2].id])
    deck.start_presentation()
    assert deck.presentation.index == 2
    assert not session.selection  # nothing stays selected on stage


def test_keys_walk_through_the_slides(deck: MainWindow) -> None:
    deck.start_presentation()
    canvas = deck.editor.canvas
    assert deck.presentation.index == 0
    press(canvas, Qt.Key.Key_Right)
    press(canvas, Qt.Key.Key_Space)
    assert deck.presentation.index == 2
    press(canvas, Qt.Key.Key_Right)  # nothing after the last slide
    assert deck.presentation.index == 2
    press(canvas, Qt.Key.Key_Left)
    assert deck.presentation.index == 1
    press(canvas, Qt.Key.Key_Home)
    assert deck.presentation.index == 0
    press(canvas, Qt.Key.Key_Left)  # nor before the first
    assert deck.presentation.index == 0
    press(canvas, Qt.Key.Key_End)
    assert deck.presentation.index == 2


def test_clicking_advances_and_escape_leaves(deck: MainWindow) -> None:
    deck.start_presentation()
    canvas = deck.editor.canvas
    Mouse(canvas).press(300, 300)
    assert deck.presentation.index == 1
    press(canvas, Qt.Key.Key_Escape)
    assert not deck.presentation.active
    assert not canvas.presenting


def test_the_camera_lands_on_the_slide(deck: MainWindow) -> None:
    deck.start_presentation()
    canvas = deck.editor.canvas
    deck.presentation.jump(1)  # reduced motion in the tests: the camera jumps
    visible = canvas.camera.visible_rect(Size(canvas.width(), canvas.height()))
    assert visible.contains_rect(Rect(600, 0, 480, 270))
    assert not visible.contains_rect(Rect(0, 0, 480, 270))


def test_slides_cannot_be_edited_while_presenting(deck: MainWindow) -> None:
    deck.start_presentation()
    canvas = deck.editor.canvas
    before = canvas.session.document
    press(canvas, Qt.Key.Key_Delete)
    press(canvas, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    press(canvas, Qt.Key.Key_Delete)
    assert canvas.session.document is before


def test_the_area_around_the_slide_is_dimmed(deck: MainWindow) -> None:
    deck.start_presentation()
    canvas = deck.editor.canvas
    deck.presentation.jump(0)
    image = canvas.grab().toImage()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    corner = image.pixelColor(2, 2)
    assert QColor(corner).lightness() < QColor(center).lightness() - 40


def test_focus_mode_keeps_the_tools_and_hides_the_rest(deck: MainWindow) -> None:
    deck.toggle_focus_mode()
    assert deck.isFullScreen()
    assert not deck.sidebar.isVisible()
    assert not deck.editor.title_bar.isVisible()
    assert deck.editor.toolbar.isVisible()
    assert not deck.editor.menu_island.isVisible()

    deck.toggle_focus_mode()
    assert deck.sidebar.isVisible()
    assert deck.editor.menu_island.isVisible()


def test_leaving_a_presentation_returns_to_focus_mode(deck: MainWindow) -> None:
    deck.toggle_focus_mode()
    deck.start_presentation()
    assert deck.editor.chrome.value == Chrome.NONE.value
    deck.presentation.stop()
    assert deck.editor.chrome.value == Chrome.FOCUS.value
    assert deck.isFullScreen()


def test_opening_another_note_ends_the_presentation(deck: MainWindow) -> None:
    deck.start_presentation()
    deck.new_note(None, "blank")
    assert not deck.presentation.active
