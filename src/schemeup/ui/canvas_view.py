"""The infinite canvas widget.

For now it draws the sheet and owns the camera: zoom around the cursor,
pan with inertia, and an animated jump back to the content.
"""

import math

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QPointF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFocusEvent,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QToolButton, QWidget

from schemeup.domain.camera import Camera, clamp_zoom
from schemeup.domain.geometry import Point, Size
from schemeup.domain.kinetics import Inertia, VelocityTracker
from schemeup.domain.sheets import Sheet
from schemeup.rendering.sheet_painter import LIGHT_SHEET_STYLE, paint_sheet

WHEEL_NOTCH = 120  # angleDelta units for one click of a normal mouse wheel
ZOOM_PER_NOTCH = 1.2
PAN_PER_NOTCH = 80.0  # screen pixels
SMOOTHING_TIME = 0.06  # seconds for wheel zoom/pan to cover ~63% of the way to the target
FRAME_INTERVAL_MS = 16
RECENTER_DURATION_MS = 320
OVERLAY_MARGIN = 16

OVERLAY_STYLE = """
QToolButton {
    background: #ffffff;
    color: #1e1e1e;
    border: 1px solid #e0e0e6;
    border-radius: 8px;
    padding: 6px 12px;
}
QToolButton:hover { background: #f1f0ff; }
"""


def _point(p: QPointF) -> Point:
    return Point(p.x(), p.y())


class CanvasView(QWidget):
    camera_changed = Signal(object)

    def __init__(self, sheet: Sheet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheet = sheet
        self._background = QColor("#ffffff")
        self._camera = Camera()
        self._has_viewport = False

        # Wheel input only moves a target; the frame timer eases the camera towards
        # it. That turns the 120-unit jumps of a mouse wheel into smooth motion.
        self._zoom_target: float | None = None
        self._zoom_anchor = Point(0, 0)
        self._pending_pan = Point(0, 0)

        self._panning = False
        self._pan_button = Qt.MouseButton.NoButton
        self._space_held = False
        self._last_pan_pos = Point(0, 0)
        self._velocity = VelocityTracker()
        self._inertia: Inertia | None = None

        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_frame = 0.0
        self._frame_timer = QTimer(self)
        self._frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_timer.setInterval(FRAME_INTERVAL_MS)
        self._frame_timer.timeout.connect(self._on_frame)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(RECENTER_DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._on_animation_step)
        self._animation_from = self._camera
        self._animation_to = self._camera

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # paintEvent covers every pixel, so Qt can skip clearing the background.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(320, 240)

        self.recenter_button = QToolButton(self)
        self.recenter_button.setText(self.tr("Back to content"))
        self.recenter_button.setStyleSheet(OVERLAY_STYLE)
        self.recenter_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recenter_button.clicked.connect(self.recenter)
        self.recenter_button.hide()

        self.zoom_button = QToolButton(self)
        self.zoom_button.setToolTip(self.tr("Reset zoom"))
        self.zoom_button.setStyleSheet(OVERLAY_STYLE)
        self.zoom_button.clicked.connect(self.reset_zoom)

        self._add_shortcuts()
        self._update_overlays()

    @property
    def camera(self) -> Camera:
        return self._camera

    @property
    def is_animating(self) -> bool:
        return (
            self._frame_timer.isActive()
            or self._animation.state() == QVariantAnimation.State.Running
        )

    def set_camera(self, camera: Camera) -> None:
        if camera == self._camera:
            return
        self._camera = camera
        self._update_overlays()
        self.camera_changed.emit(camera)
        self.update()

    def recenter(self) -> None:
        """Animate back to the content. There is no content yet, so that's the origin."""
        self._stop_motion()
        self._animation_from = self._camera
        self._animation_to = self._home_camera()
        self._animation.start()

    def zoom_to(self, zoom: float, anchor: Point | None = None) -> None:
        """Smoothly zoom to `zoom`, keeping `anchor` (default: the viewport center) fixed."""
        self._animation.stop()
        self._inertia = None
        self._zoom_anchor = anchor if anchor is not None else self._viewport_center()
        self._zoom_target = clamp_zoom(zoom)
        self._start_frames()

    def zoom_by(self, factor: float, anchor: Point | None = None) -> None:
        base = self._zoom_target if self._zoom_target is not None else self._camera.zoom
        self.zoom_to(base * factor, anchor)

    def reset_zoom(self) -> None:
        self.zoom_to(1.0)

    # Qt event handlers

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background)
        paint_sheet(painter, self._sheet, self._camera, self._viewport(), LIGHT_SHEET_STYLE)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._has_viewport:
            self._has_viewport = True
            self._camera = self._home_camera()
        self._place_overlays()
        self._update_overlays()

    def wheelEvent(self, event: QWheelEvent) -> None:
        anchor = _point(event.position())
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        # Mouse wheels send whole notches and no pixel delta; touchpads send small
        # steps. Notches get smoothed, touchpad input is applied directly.
        notched = (
            pixel.isNull()
            and not angle.isNull()
            and angle.x() % WHEEL_NOTCH == 0
            and angle.y() % WHEEL_NOTCH == 0
        )

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = ZOOM_PER_NOTCH ** (angle.y() / WHEEL_NOTCH)
            if notched:
                self.zoom_by(factor, anchor)
            else:
                self._stop_motion()
                self.set_camera(self._camera.zoomed_at(anchor, factor))
        else:
            if pixel.isNull():
                dx = angle.x() / WHEEL_NOTCH * PAN_PER_NOTCH
                dy = angle.y() / WHEEL_NOTCH * PAN_PER_NOTCH
            else:
                dx, dy = float(pixel.x()), float(pixel.y())
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and dx == 0:
                dx, dy = dy, 0.0
            if notched:
                self._animation.stop()
                self._pending_pan = self._pending_pan + Point(dx, dy)
                self._start_frames()
            else:
                self._stop_motion()
                self.set_camera(self._camera.panned_by(dx, dy))
        event.accept()

    def event(self, event: QEvent) -> bool:
        # macOS delivers touchpad pinch as a native gesture; Windows sends Ctrl+wheel.
        if (
            isinstance(event, QNativeGestureEvent)
            and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
        ):
            self._stop_motion()
            self.set_camera(self._camera.zoomed_at(_point(event.position()), 1.0 + event.value()))
            return True
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        button = event.button()
        starts_pan = button == Qt.MouseButton.MiddleButton or (
            button == Qt.MouseButton.LeftButton and self._space_held
        )
        if not starts_pan or self._panning:
            super().mousePressEvent(event)
            return
        self._stop_motion()
        self._panning = True
        self._pan_button = button
        self._last_pan_pos = _point(event.position())
        self._velocity.reset()
        self._velocity.add(self._now(), self._last_pan_pos)
        self._update_cursor()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._panning:
            super().mouseMoveEvent(event)
            return
        pos = _point(event.position())
        delta = pos - self._last_pan_pos
        self._last_pan_pos = pos
        self._velocity.add(self._now(), pos)
        self.set_camera(self._camera.panned_by(delta.x, delta.y))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._panning or event.button() != self._pan_button:
            super().mouseReleaseEvent(event)
            return
        self._panning = False
        self._pan_button = Qt.MouseButton.NoButton
        inertia = Inertia.launch(self._velocity.velocity(self._now()))
        if inertia.active:
            self._inertia = inertia
            self._start_frames()
        self._update_cursor()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self._update_cursor()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self._update_cursor()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        # The key release never arrives if the window loses focus while Space is down.
        self._space_held = False
        self._update_cursor()
        super().focusOutEvent(event)

    # Internals

    def _on_frame(self) -> None:
        now = self._now()
        # A stalled frame (window drag, breakpoint) shouldn't make the camera jump.
        dt = min(now - self._last_frame, 0.05)
        self._last_frame = now
        camera = self._camera
        catch_up = 1.0 - math.exp(-dt / SMOOTHING_TIME)

        if self._zoom_target is not None:
            ratio = self._zoom_target / camera.zoom
            if abs(math.log(ratio)) < 1e-3:
                camera = camera.zoomed_at(self._zoom_anchor, ratio)
                self._zoom_target = None
            else:
                camera = camera.zoomed_at(self._zoom_anchor, ratio**catch_up)

        pending = self._pending_pan
        if pending.length() > 0:
            step = pending if pending.length() < 0.5 else pending * catch_up
            camera = camera.panned_by(step.x, step.y)
            self._pending_pan = pending - step

        if self._inertia is not None:
            delta, inertia = self._inertia.step(dt)
            camera = camera.panned_by(delta.x, delta.y)
            self._inertia = inertia if inertia.active else None

        self.set_camera(camera)
        if self._zoom_target is None and self._pending_pan.length() == 0 and self._inertia is None:
            self._frame_timer.stop()

    def _on_animation_step(self, value: object) -> None:
        t = float(value) if isinstance(value, (int, float)) else 1.0
        self.set_camera(self._animation_from.interpolate(self._animation_to, t, self._viewport()))

    def _start_frames(self) -> None:
        if not self._frame_timer.isActive():
            self._last_frame = self._now()
            self._frame_timer.start()

    def _stop_motion(self) -> None:
        self._animation.stop()
        self._frame_timer.stop()
        self._zoom_target = None
        self._pending_pan = Point(0, 0)
        self._inertia = None

    def _home_camera(self) -> Camera:
        return self._camera.centered_on(Point(0, 0), self._viewport(), zoom=1.0)

    def _viewport(self) -> Size:
        return Size(self.width(), self.height())

    def _viewport_center(self) -> Point:
        return Point(self.width() / 2, self.height() / 2)

    def _now(self) -> float:
        return self._clock.nsecsElapsed() / 1e9

    def _update_cursor(self) -> None:
        if self._panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._space_held:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def _update_overlays(self) -> None:
        origin_visible = self._camera.visible_rect(self._viewport()).contains(Point(0, 0))
        self.recenter_button.setVisible(self._has_viewport and not origin_visible)
        self.zoom_button.setText(f"{round(self._camera.zoom * 100)}%")
        self.zoom_button.adjustSize()

    def _place_overlays(self) -> None:
        self.recenter_button.adjustSize()
        self.recenter_button.move(
            self.width() - self.recenter_button.width() - OVERLAY_MARGIN,
            self.height() - self.recenter_button.height() - OVERLAY_MARGIN,
        )
        self.zoom_button.move(
            OVERLAY_MARGIN, self.height() - self.zoom_button.height() - OVERLAY_MARGIN
        )

    def _add_shortcuts(self) -> None:
        bindings = [
            (("Ctrl+=", "Ctrl++"), lambda: self.zoom_by(ZOOM_PER_NOTCH)),
            (("Ctrl+-",), lambda: self.zoom_by(1 / ZOOM_PER_NOTCH)),
            (("Ctrl+0",), self.reset_zoom),
        ]
        for keys, handler in bindings:
            action = QAction(self)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(handler)
            self.addAction(action)
