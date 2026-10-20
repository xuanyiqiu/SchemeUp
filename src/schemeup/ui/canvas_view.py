"""The infinite canvas widget.

For now it draws the sheet and owns the camera: zoom around the cursor,
pan with inertia, and a spring back to the content.

Every camera motion is a spring or an exponential glide that starts from
the current on-screen state, so any of them can be interrupted or redirected
at any moment without a jump.
"""

import math
from dataclasses import replace

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, Qt, QTimer, Signal
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

from schemeup.domain.camera import Camera, CameraSpring, clamp_zoom, soft_clamp_zoom
from schemeup.domain.geometry import Point, Size
from schemeup.domain.kinetics import Inertia, Spring, VelocityTracker
from schemeup.domain.sheets import Sheet
from schemeup.rendering.sheet_painter import LIGHT_SHEET_STYLE, paint_sheet

WHEEL_NOTCH = 120  # angleDelta units for one click of a normal mouse wheel
ZOOM_PER_NOTCH = 1.2
PAN_PER_NOTCH = 80.0  # screen pixels
WHEEL_RESPONSE = 0.15  # snappy springs that smooth out the steps of a mouse wheel
RECENTER_RESPONSE = 0.4  # Apple's response for moving something into place
BOUNCE_BACK_RESPONSE = 0.3  # a rubber-banded zoom returning to its limit
ZOOM_SETTLE_MS = 150  # quiet time after zoom input before an overshoot springs back
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
QToolButton:pressed { background: #e2deff; }
"""


def _point(p: QPointF) -> Point:
    return Point(p.x(), p.y())


def _wheel_spring(response: float = WHEEL_RESPONSE) -> Spring:
    # Pan offsets are in screen pixels: rest within 0.1 px and 1 px/s.
    return Spring(0.0, 0.0, response=response, rest_distance=0.1, rest_speed=1.0)


class CanvasView(QWidget):
    camera_changed = Signal(object)

    def __init__(self, sheet: Sheet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheet = sheet
        self._background = QColor("#ffffff")
        self._camera = Camera()
        self._has_viewport = False

        # Each kind of motion is its own channel, stepped by the frame timer.
        # They add up, so zooming doesn't kill a glide that is still running.
        self._zoom_spring: Spring | None = None  # in log zoom
        self._zoom_request: float | None = None  # log zoom asked for, before the soft clamp
        self._zoom_anchor = Point(0, 0)
        self._pan_springs: tuple[Spring, Spring] | None = None  # wheel pan offset in x and y
        self._inertia: Inertia | None = None
        self._camera_spring: CameraSpring | None = None

        self._panning = False
        self._pan_button = Qt.MouseButton.NoButton
        self._space_held = False
        self._last_pan_pos = Point(0, 0)
        self._velocity = VelocityTracker()

        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_frame = 0.0
        self._frame_timer = QTimer(self)
        self._frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_timer.timeout.connect(self._on_frame)

        self._zoom_settle = QTimer(self)
        self._zoom_settle.setSingleShot(True)
        self._zoom_settle.setInterval(ZOOM_SETTLE_MS)
        self._zoom_settle.timeout.connect(self._settle_zoom)

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
        return self._frame_timer.isActive() or self._zoom_settle.isActive()

    def set_camera(self, camera: Camera) -> None:
        if camera == self._camera:
            return
        self._camera = camera
        self._update_overlays()
        self.camera_changed.emit(camera)
        self.update()

    def recenter(self) -> None:
        """Spring back to the content. There is no content yet, so that's the origin."""
        velocity = self._inertia.velocity if self._inertia is not None else Point(0, 0)
        zoom_velocity = self._zoom_spring.velocity if self._zoom_spring is not None else 0.0
        self._stop_motion()
        self._camera_spring = CameraSpring.between(
            self._camera,
            self._home_camera(),
            self._viewport(),
            velocity=velocity,
            zoom_velocity=zoom_velocity,
            response=RECENTER_RESPONSE,
        )
        self._start_frames()

    def zoom_to(self, zoom: float, anchor: Point | None = None) -> None:
        """Smoothly zoom to `zoom`, keeping `anchor` (default: the viewport center) fixed."""
        self._request_zoom(math.log(clamp_zoom(zoom)), anchor, smooth=True)

    def zoom_by(self, factor: float, anchor: Point | None = None) -> None:
        self._request_zoom(self._zoom_base() + math.log(factor), anchor, smooth=True)

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
            log_factor = math.log(ZOOM_PER_NOTCH) * angle.y() / WHEEL_NOTCH
            self._request_zoom(self._zoom_base() + log_factor, anchor, smooth=notched)
        else:
            if pixel.isNull():
                dx = angle.x() / WHEEL_NOTCH * PAN_PER_NOTCH
                dy = angle.y() / WHEEL_NOTCH * PAN_PER_NOTCH
            else:
                dx, dy = float(pixel.x()), float(pixel.y())
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and dx == 0:
                dx, dy = dy, 0.0
            if notched:
                self._interrupt_camera_spring()
                sx, sy = self._pan_springs or (_wheel_spring(), _wheel_spring())
                self._pan_springs = (sx.retargeted(sx.target + dx), sy.retargeted(sy.target + dy))
                self._start_frames()
            else:
                # Fingers on the touchpad catch any glide, like touching a scrolling list.
                self._stop_pan_motion()
                self.set_camera(self._camera.panned_by(dx, dy))
        event.accept()

    def event(self, event: QEvent) -> bool:
        # macOS delivers touchpad pinch as a native gesture; Windows sends Ctrl+wheel.
        if (
            isinstance(event, QNativeGestureEvent)
            and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
        ):
            log_factor = math.log1p(event.value())
            self._request_zoom(
                self._zoom_base() + log_factor, _point(event.position()), smooth=False
            )
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
        # Grabbing the canvas catches it: any glide stops right where it is.
        self._stop_pan_motion()
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

    def _request_zoom(self, log_zoom: float, anchor: Point | None, smooth: bool) -> None:
        """Zoom towards `log_zoom`. Past the limits the zoom stretches a little and
        springs back once the input stops."""
        self._interrupt_camera_spring()
        self._zoom_request = log_zoom
        self._zoom_anchor = anchor if anchor is not None else self._viewport_center()
        target = math.log(soft_clamp_zoom(math.exp(log_zoom)))
        if smooth:
            spring = self._zoom_spring or Spring(
                math.log(self._camera.zoom),
                target,
                response=WHEEL_RESPONSE,
                rest_distance=1e-4,
                rest_speed=1e-3,
            )
            self._zoom_spring = spring.retargeted(target)
            self._start_frames()
        else:
            self._zoom_spring = None
            self.set_camera(self._camera.with_zoom_at(self._zoom_anchor, math.exp(target)))
        self._zoom_settle.start()

    def _zoom_base(self) -> float:
        """Log zoom that new relative zoom input builds on, so fast wheel clicks add up."""
        if self._zoom_request is not None:
            return self._zoom_request
        return math.log(self._camera.zoom)

    def _settle_zoom(self) -> None:
        self._zoom_request = None
        current = self._zoom_spring.target if self._zoom_spring else math.log(self._camera.zoom)
        limit = math.log(clamp_zoom(math.exp(current)))
        if math.isclose(current, limit):
            return
        spring = self._zoom_spring or Spring(
            math.log(self._camera.zoom), limit, rest_distance=1e-4, rest_speed=1e-3
        )
        self._zoom_spring = replace(spring, target=limit, response=BOUNCE_BACK_RESPONSE)
        self._start_frames()

    def _on_frame(self) -> None:
        now = self._now()
        # A stalled frame (window drag, breakpoint) shouldn't make the camera jump.
        dt = min(now - self._last_frame, 0.05)
        self._last_frame = now
        camera = self._camera

        if self._camera_spring is not None:
            glide = self._camera_spring.step(dt)
            self._camera_spring = None if glide.at_rest else glide
            camera = (glide.settled() if glide.at_rest else glide).camera(self._viewport())

        if self._zoom_spring is not None:
            zoom = self._zoom_spring.step(dt)
            self._zoom_spring = None if zoom.at_rest else zoom
            log_zoom = zoom.target if zoom.at_rest else zoom.value
            camera = camera.with_zoom_at(self._zoom_anchor, math.exp(log_zoom))

        if self._pan_springs is not None:
            old_x, old_y = self._pan_springs
            sx, sy = old_x.step(dt), old_y.step(dt)
            if sx.at_rest and sy.at_rest:
                sx, sy = sx.settled(), sy.settled()
                self._pan_springs = None
            else:
                self._pan_springs = (sx, sy)
            camera = camera.panned_by(sx.value - old_x.value, sy.value - old_y.value)

        if self._inertia is not None:
            delta, inertia = self._inertia.step(dt)
            camera = camera.panned_by(delta.x, delta.y)
            self._inertia = inertia if inertia.active else None

        self.set_camera(camera)
        if not self._has_motion():
            self._frame_timer.stop()

    def _has_motion(self) -> bool:
        return (
            self._camera_spring is not None
            or self._zoom_spring is not None
            or self._pan_springs is not None
            or self._inertia is not None
        )

    def _start_frames(self) -> None:
        if self._frame_timer.isActive():
            return
        # One tick per display refresh, so 120 and 144 Hz screens get every frame.
        refresh = max(self.screen().refreshRate(), 30.0)
        self._frame_timer.setInterval(max(1, round(1000 / refresh)))
        self._last_frame = self._now()
        self._frame_timer.start()

    def _interrupt_camera_spring(self) -> None:
        """New input takes over from a recenter in progress. Its speed becomes a
        glide, so the motion blends into the new input instead of stopping dead."""
        if self._camera_spring is None:
            return
        inertia = Inertia.launch(self._camera_spring.screen_velocity())
        self._inertia = inertia if inertia.active else None
        self._camera_spring = None

    def _stop_pan_motion(self) -> None:
        self._camera_spring = None
        self._pan_springs = None
        self._inertia = None

    def _stop_motion(self) -> None:
        self._stop_pan_motion()
        self._zoom_spring = None
        self._zoom_request = None
        self._zoom_settle.stop()

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
