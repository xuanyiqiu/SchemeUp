import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from schemeup.domain.camera import MAX_ZOOM, Camera
from schemeup.domain.geometry import Point
from schemeup.domain.sheets import GridSheet
from schemeup.ui.canvas_view import ZOOM_PER_NOTCH, CanvasView


@pytest.fixture
def view(qtbot: QtBot) -> CanvasView:
    canvas = CanvasView(GridSheet())
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    return canvas


def send_wheel(view: CanvasView, pos: QPointF, angle_y: int, ctrl: bool) -> None:
    modifiers = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    event = QWheelEvent(
        pos,
        view.mapToGlobal(pos),
        QPoint(),
        QPoint(0, angle_y),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view, event)


def send_mouse(view: CanvasView, kind: QEvent.Type, pos: QPointF, buttons: Qt.MouseButton) -> None:
    button = Qt.MouseButton.MiddleButton
    event = QMouseEvent(
        kind, pos, view.mapToGlobal(pos), button, buttons, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(view, event)


def test_starts_centered_on_the_origin(view: CanvasView) -> None:
    origin = view.camera.to_screen(Point(0, 0))
    assert origin == Point(400, 300)
    assert view.camera.zoom == 1.0
    assert not view.recenter_button.isVisible()


def test_ctrl_wheel_zooms_around_the_cursor(qtbot: QtBot, view: CanvasView) -> None:
    anchor = Point(200, 150)
    world_before = view.camera.to_world(anchor)

    send_wheel(view, QPointF(anchor.x, anchor.y), 120, ctrl=True)
    qtbot.waitUntil(lambda: not view.is_animating)

    assert view.camera.zoom == pytest.approx(ZOOM_PER_NOTCH)
    world_after = view.camera.to_world(anchor)
    assert world_after.x == pytest.approx(world_before.x)
    assert world_after.y == pytest.approx(world_before.y)


def test_wheel_without_ctrl_pans(qtbot: QtBot, view: CanvasView) -> None:
    send_wheel(view, QPointF(400, 300), -120, ctrl=False)
    qtbot.waitUntil(lambda: not view.is_animating)
    assert view.camera.zoom == 1.0
    # Scrolling down moves the content up.
    assert view.camera.to_screen(Point(0, 0)).y < 300


def test_middle_drag_pans_by_the_drag_distance(qtbot: QtBot, view: CanvasView) -> None:
    middle = Qt.MouseButton.MiddleButton
    send_mouse(view, QEvent.Type.MouseButtonPress, QPointF(100, 100), middle)
    send_mouse(view, QEvent.Type.MouseMove, QPointF(150, 120), middle)
    qtbot.wait(150)  # let the velocity window expire so the release doesn't fling
    send_mouse(view, QEvent.Type.MouseButtonRelease, QPointF(150, 120), Qt.MouseButton.NoButton)

    assert view.camera.to_screen(Point(0, 0)) == Point(450, 320)
    assert not view.is_animating


def test_recenter_button_animates_back_to_the_origin(qtbot: QtBot, view: CanvasView) -> None:
    view.set_camera(Camera(5000, -3000, 2.5))
    assert view.recenter_button.isVisible()

    view.recenter_button.click()
    qtbot.waitUntil(lambda: not view.is_animating)

    origin = view.camera.to_screen(Point(0, 0))
    assert origin.x == pytest.approx(400)
    assert origin.y == pytest.approx(300)
    assert view.camera.zoom == pytest.approx(1.0)
    assert not view.recenter_button.isVisible()


def test_zoom_label_follows_the_camera(view: CanvasView) -> None:
    view.set_camera(Camera(0, 0, 2.0))
    assert view.zoom_button.text() == "200%"


def test_zoom_past_the_limit_stretches_then_springs_back(qtbot: QtBot, view: CanvasView) -> None:
    anchor = Point(300, 200)
    view.set_camera(Camera(0, 0, MAX_ZOOM))
    world = view.camera.to_world(anchor)

    for _ in range(3):
        send_wheel(view, QPointF(anchor.x, anchor.y), 120, ctrl=True)
    qtbot.waitUntil(lambda: view.camera.zoom > MAX_ZOOM * 1.01)
    qtbot.waitUntil(lambda: not view.is_animating)

    assert view.camera.zoom == pytest.approx(MAX_ZOOM)
    settled = view.camera.to_world(anchor)
    assert settled.x == pytest.approx(world.x)
    assert settled.y == pytest.approx(world.y)


def test_fast_drag_release_keeps_gliding(qtbot: QtBot, view: CanvasView) -> None:
    middle = Qt.MouseButton.MiddleButton
    send_mouse(view, QEvent.Type.MouseButtonPress, QPointF(100, 100), middle)
    send_mouse(view, QEvent.Type.MouseMove, QPointF(140, 100), middle)
    send_mouse(view, QEvent.Type.MouseButtonRelease, QPointF(140, 100), Qt.MouseButton.NoButton)
    released_at = view.camera.to_screen(Point(0, 0)).x

    assert view.is_animating
    qtbot.wait(100)
    assert view.camera.to_screen(Point(0, 0)).x > released_at + 10


def test_grabbing_the_canvas_stops_a_glide(qtbot: QtBot, view: CanvasView) -> None:
    middle = Qt.MouseButton.MiddleButton
    send_mouse(view, QEvent.Type.MouseButtonPress, QPointF(100, 100), middle)
    send_mouse(view, QEvent.Type.MouseMove, QPointF(140, 100), middle)
    send_mouse(view, QEvent.Type.MouseButtonRelease, QPointF(140, 100), Qt.MouseButton.NoButton)
    qtbot.wait(50)

    send_mouse(view, QEvent.Type.MouseButtonPress, QPointF(200, 200), middle)
    caught_at = view.camera
    qtbot.wait(50)
    assert view.camera == caught_at
    assert not view.is_animating


def test_recenter_can_be_interrupted_without_a_jump(qtbot: QtBot, view: CanvasView) -> None:
    view.set_camera(Camera(5000, -3000, 1.0))
    view.recenter()
    qtbot.wait(60)
    before = view.camera

    send_wheel(view, QPointF(400, 300), -120, ctrl=False)
    after = view.camera
    # Taking over starts from the camera on screen, not from where the spring was heading.
    assert after == before
    qtbot.waitUntil(lambda: not view.is_animating)


@pytest.fixture
def calm_view(qtbot: QtBot) -> CanvasView:
    canvas = CanvasView(GridSheet(), reduce_motion=True)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    return canvas


def test_reduced_motion_recenters_instantly(calm_view: CanvasView) -> None:
    calm_view.set_camera(Camera(5000, -3000, 2.5))
    calm_view.recenter()
    assert not calm_view.is_animating
    assert calm_view.camera.to_screen(Point(0, 0)) == Point(400, 300)
    assert calm_view.camera.zoom == 1.0


def test_reduced_motion_zooms_without_springs_or_rubber_band(calm_view: CanvasView) -> None:
    send_wheel(calm_view, QPointF(200, 150), 120, ctrl=True)
    assert not calm_view.is_animating
    assert calm_view.camera.zoom == pytest.approx(ZOOM_PER_NOTCH)

    calm_view.set_camera(Camera(0, 0, MAX_ZOOM))
    send_wheel(calm_view, QPointF(200, 150), 120, ctrl=True)
    assert calm_view.camera.zoom == MAX_ZOOM


def test_reduced_motion_does_not_glide(calm_view: CanvasView) -> None:
    middle = Qt.MouseButton.MiddleButton
    send_mouse(calm_view, QEvent.Type.MouseButtonPress, QPointF(100, 100), middle)
    send_mouse(calm_view, QEvent.Type.MouseMove, QPointF(140, 100), middle)
    send_mouse(
        calm_view, QEvent.Type.MouseButtonRelease, QPointF(140, 100), Qt.MouseButton.NoButton
    )
    assert not calm_view.is_animating
    assert calm_view.camera.to_screen(Point(0, 0)) == Point(440, 300)
