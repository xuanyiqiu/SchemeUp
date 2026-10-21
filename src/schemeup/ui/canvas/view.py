"""The infinite canvas widget.

It owns the camera and its motion (springs, glide, rubber-banded zoom), draws
the sheet and the document through the shared scene renderer, and routes
pointer input to the active tool. Every camera motion starts from the current
on-screen state, so any of them can be interrupted without a jump.
"""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Callable, Iterable
from dataclasses import replace

from PySide6.QtCore import (
    QByteArray,
    QElapsedTimer,
    QEvent,
    QMimeData,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDropEvent,
    QFocusEvent,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QResizeEvent,
    QTabletEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QFileDialog, QMenu, QToolButton, QWidget

from schemeup.application.editor import Change, EditorSession
from schemeup.application.ports import AssetStore
from schemeup.domain import commands
from schemeup.domain.camera import Camera, CameraSpring, clamp_zoom, soft_clamp_zoom
from schemeup.domain.commands import LayerMove, ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import (
    LABELED,
    LINEAR,
    SHAPES,
    Element,
    Frame,
    LinearBase,
    ShapeBase,
    Text,
    element_bounds,
    world_points,
)
from schemeup.domain.export_layout import page_rects
from schemeup.domain.geometry import Point, Rect, Size
from schemeup.domain.hit import is_inside, topmost_at
from schemeup.domain.kinetics import Inertia, Spring, VelocityTracker
from schemeup.domain.serialization import element_from_dict, element_to_dict
from schemeup.domain.sheets import Sheet, sheet_for
from schemeup.domain.snapping import Guide, SheetSnap, SnapTargets
from schemeup.domain.spatial import SpatialHash
from schemeup.domain.style import FontFamily, TextAlign
from schemeup.domain.text import ARROW_LABEL_MAX_WIDTH, arrow_label_center, label_area, place_block
from schemeup.rendering.fonts import canvas_font
from schemeup.rendering.images import AssetImages
from schemeup.rendering.scene import SceneRenderer, fitted_block
from schemeup.rendering.sheet_painter import DARK_SHEET_STYLE, LIGHT_SHEET_STYLE, paint_sheet
from schemeup.rendering.text import layout_text
from schemeup.ui.canvas.overlays import (
    HANDLE_SIZE,
    Handle,
    handle_points,
    paint_guides,
    paint_highlight,
    paint_rubber_band,
    paint_selection,
    selection_frame,
    single_linear,
)
from schemeup.ui.canvas.text_editor import TextEditor
from schemeup.ui.canvas.tools import (
    EraserTool,
    FreedrawTool,
    HandTool,
    LinearTool,
    Pointer,
    SelectionTool,
    ShapeTool,
    TextTool,
    Tool,
    ToolKind,
)
from schemeup.ui.theme import LIGHT, Theme

WHEEL_NOTCH = 120  # angleDelta units for one click of a normal mouse wheel
ZOOM_PER_NOTCH = 1.2
PAN_PER_NOTCH = 80.0  # screen pixels
WHEEL_RESPONSE = 0.15  # snappy springs that smooth out the steps of a mouse wheel
RECENTER_RESPONSE = 0.4  # Apple's response for moving something into place
BOUNCE_BACK_RESPONSE = 0.3  # a rubber-banded zoom returning to its limit
ZOOM_SETTLE_MS = 150  # quiet time after zoom input before an overshoot springs back
OVERLAY_MARGIN = 16
HIT_TOLERANCE_PX = 8.0
SNAP_DISTANCE_PX = 5.0  # how close a shape must come to a line for it to catch
SNAP_RELEASE_FACTOR = 1.6  # a caught line lets go this much farther out
SNAP_MAX_SPEED = 600.0  # screen px/s; moving faster than this skips snapping
CURTAIN_ALPHA = 190  # how far the area around the current slide is dimmed
SLIDE_WHEEL_GAP = 0.35  # seconds between slide changes from a wheel or touchpad
NEXT_SLIDE_KEYS = (
    Qt.Key.Key_Right,
    Qt.Key.Key_Down,
    Qt.Key.Key_PageDown,
    Qt.Key.Key_Space,
    Qt.Key.Key_Return,
    Qt.Key.Key_Enter,
    Qt.Key.Key_N,
)
PREVIOUS_SLIDE_KEYS = (
    Qt.Key.Key_Left,
    Qt.Key.Key_Up,
    Qt.Key.Key_PageUp,
    Qt.Key.Key_Backspace,
    Qt.Key.Key_P,
)
CLIPBOARD_MIME = "application/x-schemeup-elements"


def _point(p: QPointF) -> Point:
    return Point(p.x(), p.y())


def _wheel_spring(response: float = WHEEL_RESPONSE) -> Spring:
    # Pan offsets are in screen pixels: rest within 0.1 px and 1 px/s.
    return Spring(0.0, 0.0, response=response, rest_distance=0.1, rest_speed=1.0)


class CanvasView(QWidget):
    camera_changed = Signal(object)
    tool_changed = Signal(object)
    snapping_changed = Signal()
    copy_png_requested = Signal()
    slide_step = Signal(int)  # +1 or -1, while presenting
    slide_jump = Signal(int)  # an absolute slide index, -1 for the last
    presentation_exited = Signal()
    presentation_activity = Signal()

    def __init__(
        self,
        session: EditorSession,
        *,
        assets: AssetStore | None = None,
        theme: Theme = LIGHT,
        reduce_motion: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._assets = assets
        self._theme = theme
        # With reduced motion the camera jumps straight to where it's going:
        # no springs, no glide, no rubber band.
        self._reduce_motion = reduce_motion
        self._camera = Camera()
        self._has_viewport = False
        self._images = AssetImages(assets)
        self._renderer = SceneRenderer(self._images)
        self._index = SpatialHash()
        self._indexed: Document | None = None

        # Display state set by tools.
        self._preview: Document | None = None
        self._preview_ids: frozenset[str] = frozenset()
        self._guides: tuple[Guide, ...] = ()
        self._highlight: Element | None = None
        self._rubber: Rect | None = None
        self._faded: frozenset[str] = frozenset()

        self.snap_objects = False
        self.snap_grid = False
        self.tool_locked = False

        # Presenting: input turns into slide navigation and everything but the
        # current slide is dimmed.
        self._presenting = False
        self._spotlight: Rect | None = None
        self._last_slide_wheel = 0.0
        self._stage_cursor = Qt.CursorShape.ArrowCursor

        # Camera motion channels, stepped together by the frame timer.
        self._zoom_spring: Spring | None = None
        self._zoom_request: float | None = None
        self._zoom_anchor = Point(0, 0)
        self._pan_springs: tuple[Spring, Spring] | None = None
        self._inertia: Inertia | None = None
        self._camera_spring: CameraSpring | None = None

        self._panning = False
        self._pan_button = Qt.MouseButton.NoButton
        self._space_held = False
        self._last_pan_pos = Point(0, 0)
        self._velocity = VelocityTracker()
        self._pointer_velocity = VelocityTracker(window=0.06)
        self._pointer_down = False
        self._pressure = 0.5
        self._tablet = False
        self._last_mouse = Point(0, 0)

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
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        # paintEvent covers every pixel, so Qt can skip clearing the background.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(320, 240)

        self.text_editor = TextEditor(self)
        self.text_editor.finished.connect(self._text_finished)
        self._new_text: Text | None = None

        self.recenter_button = QToolButton(self)
        self.recenter_button.setText(self.tr("Back to content"))
        self.recenter_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recenter_button.clicked.connect(self.recenter)
        self.recenter_button.hide()
        self.zoom_button = QToolButton(self)
        self.zoom_button.setToolTip(self.tr("Reset zoom (Ctrl+0)"))
        self.zoom_button.clicked.connect(self.reset_zoom)
        self._style_overlays()

        self._tools: dict[ToolKind, Tool] = {
            ToolKind.SELECT: SelectionTool(self),
            ToolKind.HAND: HandTool(self),
            ToolKind.RECTANGLE: ShapeTool(self, ToolKind.RECTANGLE, ShapeKind.RECTANGLE),
            ToolKind.DIAMOND: ShapeTool(self, ToolKind.DIAMOND, ShapeKind.DIAMOND),
            ToolKind.ELLIPSE: ShapeTool(self, ToolKind.ELLIPSE, ShapeKind.ELLIPSE),
            ToolKind.FRAME: ShapeTool(self, ToolKind.FRAME, ShapeKind.FRAME),
            ToolKind.ARROW: LinearTool(self, arrow=True),
            ToolKind.LINE: LinearTool(self, arrow=False),
            ToolKind.DRAW: FreedrawTool(self),
            ToolKind.TEXT: TextTool(self),
            ToolKind.ERASER: EraserTool(self),
        }
        self._tool: Tool = self._tools[ToolKind.SELECT]
        self._add_shortcuts()
        session.subscribe(self._on_session_change)
        self._update_overlays()

    # Public state

    @property
    def session(self) -> EditorSession:
        return self._session

    @property
    def camera(self) -> Camera:
        return self._camera

    @property
    def tool(self) -> ToolKind:
        return self._tool.kind

    @property
    def is_animating(self) -> bool:
        return self._frame_timer.isActive() or self._zoom_settle.isActive()

    @property
    def renderer(self) -> SceneRenderer:
        return self._renderer

    @property
    def dark(self) -> bool:
        return self._theme.dark

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._style_overlays()
        self.update()

    def set_assets(self, assets: AssetStore | None) -> None:
        self._assets = assets
        self._images = AssetImages(assets)
        self._renderer.set_images(self._images)
        self.update()

    def set_camera(self, camera: Camera) -> None:
        if camera == self._camera:
            return
        self._camera = camera
        self._update_overlays()
        self.text_editor.refresh()
        self.camera_changed.emit(camera)
        self.update()

    def display_document(self) -> Document:
        return self._preview if self._preview is not None else self._session.document

    def set_tool(self, kind: ToolKind) -> None:
        if kind == ToolKind.IMAGE:
            self.insert_image()
            return
        if self.text_editor.element_id is not None:
            self.text_editor.commit()
        if kind == self._tool.kind:
            return
        self._tool.deactivate()
        self._tool = self._tools[kind]
        self._tool.activate()
        if kind not in (ToolKind.SELECT, ToolKind.HAND):
            self._session.select(())
        self.tool_changed.emit(kind)
        self.update()

    @property
    def presenting(self) -> bool:
        return self._presenting

    def set_presenting(self, presenting: bool) -> None:
        """Turn the canvas into a read-only stage (or back into an editor)."""
        if presenting == self._presenting:
            return
        if presenting:
            if self.text_editor.element_id is not None:
                self.text_editor.commit()
            self._tool.cancel()
            self.set_tool(ToolKind.SELECT)
            self._session.select(())
        self._presenting = presenting
        self._spotlight = None
        # The editing shortcuts (Delete, arrows, tool letters) must not act on a slide show.
        for action in self.actions():
            action.setEnabled(not presenting)
        self._update_cursor()
        self._update_overlays()
        self.update()

    def present(self, frame: Rect, animate: bool = True) -> None:
        """Light up `frame` and fly the camera so it fills the view."""
        self._spotlight = frame
        self.fit_to(frame, max_zoom=4.0, padding=48, animate=animate)
        self.update()

    def set_snapping(self, objects: bool | None = None, grid: bool | None = None) -> None:
        if objects is not None:
            self.snap_objects = objects
        if grid is not None:
            self.snap_grid = grid
        self.snapping_changed.emit()

    # ToolHost

    def tolerance(self) -> float:
        return HIT_TOLERANCE_PX / self._camera.zoom

    def snap_threshold(self) -> float:
        return SNAP_DISTANCE_PX / self._camera.zoom

    def snap_release(self) -> float:
        return self.snap_threshold() * SNAP_RELEASE_FACTOR

    def snapping(self, pointer: Pointer) -> bool:
        # Sweeping across the canvas shouldn't be pulled around by every line it passes;
        # snapping engages again as the pointer slows down to land.
        if pointer.speed > SNAP_MAX_SPEED:
            return False
        return (self.snap_objects or self.snap_grid) and not pointer.ctrl

    def snap_targets(self, exclude: set[str]) -> SnapTargets | None:
        if not self.snap_objects:
            return None
        document = self._session.document
        area = self._camera.visible_rect(self._viewport()).inflated(200 / self._camera.zoom)
        rects = []
        for element_id in self.candidates(area):
            element = document.get(element_id)
            if element is None or element_id in exclude or isinstance(element, LINEAR):
                continue
            rects.append(element_bounds(element))
        return SnapTargets(rects)

    def sheet_snap(self) -> SheetSnap | None:
        if not self.snap_grid:
            return None
        return SheetSnap(self._sheet(), self._camera.zoom)

    def hit(self, p: Point) -> Element | None:
        area = Rect(p.x, p.y, 0, 0).inflated(self.tolerance())
        return topmost_at(self._session.document, p, self.tolerance(), self.candidates(area))

    def container_at(self, p: Point) -> Element | None:
        """Topmost shape whose inside contains `p`, filled or not."""
        document = self._session.document
        area = Rect(p.x, p.y, 0, 0)
        for element in reversed(document.in_z_order(self.candidates(area))):
            if isinstance(element, SHAPES) and not element.locked and is_inside(element, p):
                return element
        return None

    def candidates(self, rect: Rect) -> set[str]:
        self._sync_index()
        return self._index.query(rect)

    def set_preview(self, document: Document | None, changed: Iterable[str] = ()) -> None:
        self._preview = document
        self._preview_ids = frozenset(changed) if document is not None else frozenset()
        self.update()

    def set_guides(self, guides: tuple[Guide, ...]) -> None:
        if guides != self._guides:
            self._guides = guides
            self.update()

    def set_highlight(self, element: Element | None) -> None:
        if element is not self._highlight:
            self._highlight = element
            self.update()

    def set_rubber_band(self, rect: Rect | None) -> None:
        self._rubber = rect
        self.update()

    def set_faded(self, ids: frozenset[str]) -> None:
        if ids != self._faded:
            self._faded = ids
            self.update()

    def handle_at(self, screen: Point) -> Handle | int | None:
        document = self._session.document
        selection = self._session.selection
        linear = single_linear(document, selection)
        if linear is not None and isinstance(linear, LinearBase):
            for i, p in enumerate(world_points(linear)):
                if (self._camera.to_screen(p) - screen).length() <= 8:
                    return i
            return None
        if any(e.locked for e in document.in_z_order(selection)):
            return None
        frame = selection_frame(document, selection)
        if frame is None:
            return None
        for handle, p in handle_points(frame, self._camera).items():
            if (p - screen).length() <= HANDLE_SIZE:
                return handle
        return None

    def finish_creation(self) -> None:
        if not self.tool_locked:
            self.set_tool(ToolKind.SELECT)

    def set_cursor(self, shape: Qt.CursorShape) -> None:
        if not self._panning and not self._space_held:
            self.setCursor(shape)

    def start_drag_pan(self, screen: Point) -> None:
        self._stop_pan_motion()
        self._panning = True
        self._last_pan_pos = screen
        self._velocity.reset()
        self._velocity.add(self._now(), screen)

    def drag_pan(self, screen: Point) -> None:
        if not self._panning:
            return
        delta = screen - self._last_pan_pos
        self._last_pan_pos = screen
        self._velocity.add(self._now(), screen)
        self.set_camera(self._camera.panned_by(delta.x, delta.y))

    def end_drag_pan(self) -> None:
        if not self._panning:
            return
        self._panning = False
        inertia = Inertia.launch(self._velocity.velocity(self._now()))
        if inertia.active and not self._reduce_motion:
            self._inertia = inertia
            self._start_frames()

    # Text editing

    def edit_text(self, element_id: str) -> None:
        element = self._session.document.get(element_id)
        if element is None:
            return
        if isinstance(element, Text):
            self._begin_text(element, element.text)
        elif isinstance(element, LABELED):
            self._begin_text(element, element.label)

    def create_text_at(self, world: Point) -> None:
        style = self._session.style
        line = layout_text(
            " ", style.font_family, style.font_size, None, TextAlign.LEFT
        ).line_height
        text = commands.make_text(
            Point(world.x, world.y - line / 2), "", replace(style, text_align=TextAlign.LEFT)
        )
        self._new_text = text
        self._begin_text(text, "")

    def _begin_text(self, element: Element, text: str) -> None:
        style = element.style
        zoom = self._camera.zoom
        font = canvas_font(style.font_family, style.font_size * zoom)
        color = self._renderer.color(style.stroke_color, self.dark)
        alignment = {
            TextAlign.LEFT: Qt.AlignmentFlag.AlignLeft,
            TextAlign.CENTER: Qt.AlignmentFlag.AlignHCenter,
            TextAlign.RIGHT: Qt.AlignmentFlag.AlignRight,
        }[style.text_align]
        self.text_editor.begin(
            element.id, text, font, color, alignment, lambda t: self._text_rect(element.id, t)
        )
        self.update()

    def _text_rect(self, element_id: str, text: str) -> QRectF:
        """Screen rect for the editor while typing `text` into `element_id`."""
        element = self._session.document.get(element_id)
        if element is None and self._new_text is not None and self._new_text.id == element_id:
            element = self._new_text
        if element is None:
            return QRectF()
        style = element.style
        zoom = self._camera.zoom
        slack = 12.0
        if isinstance(element, Text):
            width = None if element.auto_width else element.width
            block = layout_text(
                text or " ", style.font_family, style.font_size, width, style.text_align
            )
            top_left = self._camera.to_screen(Point(element.x, element.y))
            w = (block.width if width is None else width) * zoom + slack
            raise_by = block.inset * zoom
            # Split the caret slack so aligned text sits where it will be drawn.
            shift = {TextAlign.LEFT: 0.0, TextAlign.CENTER: slack / 2, TextAlign.RIGHT: slack}[
                style.text_align
            ]
            return QRectF(
                top_left.x - shift, top_left.y - raise_by, w, block.height * zoom + 2 + raise_by
            )
        if isinstance(element, SHAPES):
            area = label_area(element)
            block = fitted_block(text or " ", style, area.width)
            box = place_block(area, Size(block.width, block.height), style)
            center = box.center.rotated(element.center, element.angle)
            s = self._camera.to_screen(center)
            w, h = block.width * zoom + slack, block.height * zoom + 2
            raise_by = block.inset * zoom
            return QRectF(s.x - w / 2, s.y - h / 2 - raise_by, w, h + raise_by)
        if isinstance(element, LINEAR):
            block = fitted_block(text or " ", style, ARROW_LABEL_MAX_WIDTH)
            s = self._camera.to_screen(arrow_label_center(element))
            w, h = block.width * zoom + slack, block.height * zoom + 2
            raise_by = block.inset * zoom
            return QRectF(s.x - w / 2, s.y - h / 2 - raise_by, w, h + raise_by)
        return QRectF()

    def _text_finished(self, element_id: str, text: str) -> None:
        new_text = self._new_text
        self._new_text = None
        if new_text is not None and new_text.id == element_id:
            if text.strip():
                self._session.add([replace(new_text, text=text)], "Add text")
        else:
            self._session.set_text(element_id, text)
        self.setFocus()
        if self._tool.kind == ToolKind.TEXT:
            self.finish_creation()
        self.update()

    # Images and clipboard

    def insert_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Insert image"),
            "",
            self.tr("Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg)"),
        )
        if path:
            try:
                with open(path, "rb") as f:
                    self.add_image_bytes(f.read(), None)
            except OSError:
                pass

    def add_image_bytes(self, data: bytes, at: Point | None) -> bool:
        image = QImage.fromData(data)
        if image.isNull() or self._assets is None:
            return False
        asset_id = self._assets.put(data, "image/png")
        w, h = float(image.width()), float(image.height())
        limit = 640.0 / self._camera.zoom
        if w > limit:
            h, w = h * limit / w, limit
        center = at or self._camera.to_world(Point(self.width() / 2, self.height() / 2))
        element = commands.make_image(
            Rect(center.x - w / 2, center.y - h / 2, w, h), asset_id, self._session.style
        )
        self._session.add([element], "Add image")
        self.set_tool(ToolKind.SELECT)
        return True

    def copy(self) -> None:
        document = self._session.document
        ids = commands.with_frame_children(document, self._session.selection)
        elements = document.in_z_order(ids)
        if not elements:
            return
        files: dict[str, str] = {}
        for e in elements:
            asset_id = getattr(e, "asset_id", "")
            if asset_id and self._assets is not None:
                data = self._assets.get(asset_id)
                if data:
                    files[asset_id] = base64.b64encode(data).decode("ascii")
        payload = {
            "type": "schemeup/clipboard",
            "elements": [element_to_dict(e) for e in elements],
            "files": files,
        }
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, QByteArray(json.dumps(payload).encode("utf-8")))
        texts = [e.text if isinstance(e, Text) else getattr(e, "label", "") for e in elements]
        mime.setText("\n".join(t for t in texts if t))
        QGuiApplication.clipboard().setMimeData(mime)

    def cut(self) -> None:
        self.copy()
        self._session.delete_selection()

    def paste(self) -> None:
        mime = QGuiApplication.clipboard().mimeData()
        inside = QRectF(self.rect()).contains(QPointF(self._last_mouse.x, self._last_mouse.y))
        at = self._camera.to_world(self._last_mouse) if inside else None
        if mime.hasFormat(CLIPBOARD_MIME):
            try:
                payload = json.loads(bytes(mime.data(CLIPBOARD_MIME).data()).decode("utf-8"))
                for asset_id, encoded in payload.get("files", {}).items():
                    if self._assets is not None and self._assets.get(asset_id) is None:
                        self._assets.put(base64.b64decode(encoded), "image/png")
                elements = [element_from_dict(d) for d in payload.get("elements", [])]
            except (ValueError, KeyError, TypeError):
                return
            self._session.paste(elements, at)
            return
        if mime.hasImage():
            image = mime.imageData()
            if isinstance(image, QImage) and not image.isNull():
                from PySide6.QtCore import QBuffer, QIODevice
                from PySide6.QtGui import QImageWriter

                data = QByteArray()
                buffer = QBuffer(data)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                QImageWriter(buffer, b"PNG").write(image)
                self.add_image_bytes(bytes(data.data()), at)
                return
        if mime.hasText() and mime.text().strip():
            point = at or self._camera.to_world(Point(self.width() / 2, self.height() / 2))
            text = commands.make_text(
                point, mime.text(), replace(self._session.style, text_align=TextAlign.LEFT)
            )
            self._session.add([text], "Paste text")

    # Navigation

    def content_bounds(self) -> Rect | None:
        return self._session.document.content_bounds()

    def recenter(self) -> None:
        """Spring back to the content (or the origin of an empty canvas)."""
        velocity = self._inertia.velocity if self._inertia is not None else Point(0, 0)
        zoom_velocity = self._zoom_spring.velocity if self._zoom_spring is not None else 0.0
        self._stop_motion()
        target = self._home_camera()
        if self._reduce_motion:
            self.set_camera(target)
            return
        self._camera_spring = CameraSpring.between(
            self._camera,
            target,
            self._viewport(),
            velocity=velocity,
            zoom_velocity=zoom_velocity,
            response=RECENTER_RESPONSE,
        )
        self._start_frames()

    def fit_to(
        self,
        rect: Rect | None,
        max_zoom: float = 1.0,
        padding: float = 60.0,
        animate: bool = True,
    ) -> None:
        if rect is None:
            self.recenter()
            return
        target = self._camera.fitted_to(rect, self._viewport(), padding=padding, max_zoom=max_zoom)
        self._stop_motion()
        if self._reduce_motion or not animate:
            self.set_camera(target)
            return
        self._camera_spring = CameraSpring.between(
            self._camera, target, self._viewport(), response=RECENTER_RESPONSE
        )
        self._start_frames()

    def fit_content(self) -> None:
        self.fit_to(self.content_bounds(), max_zoom=2.0)

    def fit_selection(self) -> None:
        self.fit_to(self._session.document.bounds_of(self._session.selection), max_zoom=4.0)

    def zoom_to(self, zoom: float, anchor: Point | None = None) -> None:
        """Smoothly zoom to `zoom`, keeping `anchor` (default: the viewport center) fixed."""
        self._request_zoom(math.log(clamp_zoom(zoom)), anchor, smooth=True)

    def zoom_by(self, factor: float, anchor: Point | None = None) -> None:
        self._request_zoom(self._zoom_base() + math.log(factor), anchor, smooth=True)

    def reset_zoom(self) -> None:
        self.zoom_to(1.0)

    def show_document(self) -> None:
        """Called after a different note was loaded: frame its content."""
        self._stop_motion()
        self._preview = None
        self._sync_index()
        bounds = self.content_bounds()
        if not self._has_viewport:
            return
        if bounds is None:
            self.set_camera(self._camera.centered_on(Point(0, 0), self._viewport(), zoom=1.0))
        else:
            camera = Camera().fitted_to(bounds, self._viewport(), padding=80, max_zoom=1.0)
            if bounds.width * 1.0 < self.width() - 160 and bounds.height < self.height() - 160:
                camera = Camera(bounds.left - 80, bounds.top - 80, 1.0)
            self.set_camera(camera)

    # Qt event handlers

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        document = self.display_document()
        settings = document.settings
        dark = self.dark
        background = self._renderer.color(settings.background, dark)
        painter.fillRect(self.rect(), background)

        viewport = self._viewport()
        sheet_style = DARK_SHEET_STYLE if dark else LIGHT_SHEET_STYLE
        content = document.content_bounds() if settings.page_size else None
        pages = page_rects(
            settings.page_size, settings.page_landscape, content.bottom if content else 0.0
        )
        if pages:
            painter.fillRect(self.rect(), QColor("#2b2b31" if dark else "#e9e9ee"))
            for page in pages:
                a = self._camera.to_screen(Point(page.left, page.top))
                b = self._camera.to_screen(Point(page.right, page.bottom))
                screen_rect = QRectF(a.x, a.y, b.x - a.x, b.y - a.y)
                painter.fillRect(screen_rect.translated(0, 3), QColor(0, 0, 0, 40))
                painter.fillRect(screen_rect, background)
                painter.save()
                painter.setClipRect(screen_rect)
                paint_sheet(painter, self._sheet(), self._camera, viewport, sheet_style, background)
                painter.restore()
        else:
            paint_sheet(painter, self._sheet(), self._camera, viewport, sheet_style, background)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.save()
        zoom = self._camera.zoom
        painter.setTransform(
            QTransform(zoom, 0, 0, zoom, -self._camera.x * zoom, -self._camera.y * zoom)
        )
        visible = self._camera.visible_rect(viewport)
        ids = self.candidates(visible) | self._preview_ids
        elements = document.in_z_order(ids)
        editing = self.text_editor.element_id
        self._renderer.paint(
            painter,
            document,
            elements,
            dark=dark,
            background=settings.background,
            faded=self._faded,
            editing_text=editing,
            frame_chrome=not self._presenting,
        )
        painter.restore()

        if self._presenting:
            self._paint_curtain(painter)
            painter.end()
            return

        if self._highlight is not None:
            paint_highlight(painter, self._highlight, self._camera, self._theme.selection)
        selection = self._session.selection
        if selection:
            show_handles = self._tool.kind == ToolKind.SELECT and editing is None
            paint_selection(
                painter,
                document,
                selection,
                self._camera,
                self._theme.selection,
                self._theme.panel,
                show_handles,
            )
        paint_guides(painter, self._guides, self._camera)
        if self._rubber is not None:
            paint_rubber_band(painter, self._rubber, self._camera, self._theme.selection)
        if not document.order and editing is None:
            self._paint_empty_hint(painter)
        painter.end()

    def _paint_curtain(self, painter: QPainter) -> None:
        """Dim everything outside the slide, so its neighbours show only as a hint."""
        if self._spotlight is None:
            return
        a = self._camera.to_screen(Point(self._spotlight.left, self._spotlight.top))
        b = self._camera.to_screen(Point(self._spotlight.right, self._spotlight.bottom))
        curtain = QPainterPath()
        curtain.addRect(QRectF(self.rect()))
        curtain.addRect(QRectF(a.x, a.y, b.x - a.x, b.y - a.y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 8, 12, CURTAIN_ALPHA))
        painter.drawPath(curtain)  # odd-even fill leaves the slide itself clear

    def _paint_empty_hint(self, painter: QPainter) -> None:
        muted = QColor(self._theme.muted)
        painter.setPen(muted)
        title = canvas_font(FontFamily.HAND, 26)
        painter.setFont(title)
        center = QRectF(0, self.height() / 2 - 60, self.width(), 40)
        painter.drawText(
            center, int(Qt.AlignmentFlag.AlignCenter), self.tr("Pick a tool and start drawing")
        )
        small = canvas_font(FontFamily.NORMAL, 13)
        painter.setFont(small)
        below = QRectF(0, self.height() / 2 - 18, self.width(), 24)
        painter.drawText(
            below,
            int(Qt.AlignmentFlag.AlignCenter),
            self.tr("Double-click anywhere to type. Wheel to pan, Ctrl+wheel to zoom."),
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._has_viewport:
            self._has_viewport = True
            self._camera = self._home_camera()
            if self._session.document.order:
                self.show_document()
        if self._presenting and self._spotlight is not None:
            self.fit_to(self._spotlight, max_zoom=4.0, padding=48, animate=False)
        self._place_overlays()
        self._update_overlays()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._presenting:
            now = self._now()
            if event.angleDelta().y() and now - self._last_slide_wheel > SLIDE_WHEEL_GAP:
                self._last_slide_wheel = now
                self.slide_step.emit(-1 if event.angleDelta().y() > 0 else 1)
            event.accept()
            return
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
            if notched and not self._reduce_motion:
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

    def tabletEvent(self, event: QTabletEvent) -> None:
        # Remember the pen pressure and let Qt turn the event into mouse events.
        self._pressure = event.pressure()
        self._tablet = True
        event.ignore()

    def _pointer(self, event: QMouseEvent) -> Pointer:
        screen = _point(event.position())
        mods = event.modifiers()
        tablet = self._tablet and event.source() != Qt.MouseEventSource.MouseEventNotSynthesized
        return Pointer(
            world=self._camera.to_world(screen),
            screen=screen,
            shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
            ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
            alt=bool(mods & Qt.KeyboardModifier.AltModifier),
            pressure=self._pressure if tablet else 0.5,
            tablet=tablet,
            speed=self._pointer_speed(),
        )

    def _pointer_speed(self) -> float:
        v = self._pointer_velocity.velocity(self._now())
        return math.hypot(v.x, v.y)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        self._pointer_velocity.reset()
        if self._presenting:
            button = event.button()
            if button == Qt.MouseButton.LeftButton:
                self.slide_step.emit(1)
            elif button in (Qt.MouseButton.RightButton, Qt.MouseButton.BackButton):
                self.slide_step.emit(-1)
            event.accept()
            return
        button = event.button()
        if button == Qt.MouseButton.MiddleButton or (
            button == Qt.MouseButton.LeftButton and self._space_held
        ):
            if self._panning:
                return
            # Grabbing the canvas catches it: any glide stops right where it is.
            self._pan_button = button
            self.start_drag_pan(_point(event.position()))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton:
            if self.text_editor.element_id is not None:
                self.text_editor.commit()
                if self._tool.kind != ToolKind.SELECT:
                    return
            self._pointer_down = True
            self._tool.press(self._pointer(event))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._last_mouse = _point(event.position())
        self._pointer_velocity.add(self._now(), self._last_mouse)
        if self._presenting:
            self.presentation_activity.emit()
            event.accept()
            return
        if self._panning:
            self.drag_pan(_point(event.position()))
            event.accept()
            return
        pointer = self._pointer(event)
        if self._pointer_down:
            self._tool.move(pointer)
        else:
            self._tool.hover(pointer)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning and event.button() == self._pan_button:
            self._pan_button = Qt.MouseButton.NoButton
            self.end_drag_pan()
            self._update_cursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pointer_down:
            self._pointer_down = False
            self._tool.release(self._pointer(event))
            self._tablet = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._presenting:
            self.mousePressEvent(event)  # two quick clicks are two steps, not a text edit
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._tool.double_click(self._pointer(event))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._presenting:
            self._present_key(event)
            return
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self._tool.key(event.key()):
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._tool.kind != ToolKind.SELECT:
                self._tool.cancel()
                self.set_tool(ToolKind.SELECT)
            else:
                self._session.select(())
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

    def _present_key(self, event: QKeyEvent) -> None:
        key = event.key()
        self.presentation_activity.emit()
        if key in NEXT_SLIDE_KEYS:
            self.slide_step.emit(1)
        elif key in PREVIOUS_SLIDE_KEYS:
            self.slide_step.emit(-1)
        elif key == Qt.Key.Key_Home:
            self.slide_jump.emit(0)
        elif key == Qt.Key.Key_End:
            self.slide_jump.emit(-1)
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.presentation_exited.emit()
        else:
            event.ignore()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self._presenting:
            return
        world = self._camera.to_world(_point(QPointF(event.pos())))
        hit = self.hit(world)
        if hit is not None and hit.id not in self._session.selection:
            from schemeup.application.editor import expand_groups

            self._session.select(expand_groups(self._session.document, [hit.id]))
        menu = QMenu(self)
        has_selection = bool(self._session.selection)
        entries: list[tuple[str, str, Callable[[], None], bool]] = [
            (self.tr("Cut"), "Ctrl+X", self.cut, has_selection),
            (self.tr("Copy"), "Ctrl+C", self.copy, has_selection),
            (self.tr("Paste"), "Ctrl+V", self.paste, True),
            ("", "", lambda: None, False),
            (self.tr("Duplicate"), "Ctrl+D", self._session.duplicate_selection, has_selection),
            (self.tr("Delete"), "Del", self._session.delete_selection, has_selection),
            ("", "", lambda: None, False),
            (
                self.tr("Bring to front"),
                "Ctrl+Shift+]",
                lambda: self._session.reorder_selection(LayerMove.FRONT),
                has_selection,
            ),
            (
                self.tr("Bring forward"),
                "Ctrl+]",
                lambda: self._session.reorder_selection(LayerMove.FORWARD),
                has_selection,
            ),
            (
                self.tr("Send backward"),
                "Ctrl+[",
                lambda: self._session.reorder_selection(LayerMove.BACKWARD),
                has_selection,
            ),
            (
                self.tr("Send to back"),
                "Ctrl+Shift+[",
                lambda: self._session.reorder_selection(LayerMove.BACK),
                has_selection,
            ),
            ("", "", lambda: None, False),
            (
                self.tr("Group"),
                "Ctrl+G",
                self._session.group_selection,
                len(self._session.selection) > 1,
            ),
            (self.tr("Ungroup"), "Ctrl+Shift+G", self._session.ungroup_selection, has_selection),
            (
                self.tr("Lock / unlock"),
                "Ctrl+Shift+L",
                self._session.toggle_lock_selection,
                has_selection,
            ),
            ("", "", lambda: None, False),
            (self.tr("Copy as PNG"), "Shift+Alt+C", self.copy_png_requested.emit, True),
            (self.tr("Select all"), "Ctrl+A", self._session.select_all, True),
            (
                self.tr("Unlock all"),
                "",
                self._session.unlock_all,
                any(e.locked for e in self._session.document.ordered()),
            ),
        ]
        for text, shortcut, slot, enabled in entries:
            if not text:
                menu.addSeparator()
                continue
            action = menu.addAction(text)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setEnabled(enabled)
            action.triggered.connect(slot)
        menu.exec(event.globalPos())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        at = self._camera.to_world(_point(event.position()))
        for url in event.mimeData().urls():
            if url.isLocalFile():
                try:
                    with open(url.toLocalFile(), "rb") as f:
                        if self.add_image_bytes(f.read(), at):
                            at = at + Point(24, 24)
                except OSError:
                    continue
        event.acceptProposedAction()

    # Internals

    def _sheet(self) -> Sheet:
        settings = self._session.document.settings
        return sheet_for(settings.sheet, settings.line_spacing_mm)

    def _sync_index(self) -> None:
        document = self._session.document
        if self._indexed is not document:
            self._index.sync(document)
            self._indexed = document

    def _on_session_change(self, change: Change) -> None:
        if change == Change.DOCUMENT:
            self._sync_index()
            self._renderer.prune(self._session.document)
            self._update_overlays()
        self.update()

    def _request_zoom(self, log_zoom: float, anchor: Point | None, smooth: bool) -> None:
        """Zoom towards `log_zoom`. Past the limits the zoom stretches a little and
        springs back once the input stops."""
        self._interrupt_camera_spring()
        anchor = anchor if anchor is not None else self._viewport_center()
        if self._reduce_motion:
            self.set_camera(self._camera.with_zoom_at(anchor, clamp_zoom(math.exp(log_zoom))))
            return
        self._zoom_request = log_zoom
        self._zoom_anchor = anchor
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
        bounds = self.content_bounds()
        viewport = self._viewport()
        if bounds is None:
            return self._camera.centered_on(Point(0, 0), viewport, zoom=1.0)
        visible = self._camera.visible_rect(viewport)
        if bounds.width <= visible.width * 0.9 and bounds.height <= visible.height * 0.9:
            return self._camera.centered_on(bounds.center, viewport)
        return self._camera.fitted_to(bounds, viewport, padding=60, max_zoom=1.0)

    def _viewport(self) -> Size:
        return Size(self.width(), self.height())

    def _viewport_center(self) -> Point:
        return Point(self.width() / 2, self.height() / 2)

    def _now(self) -> float:
        return self._clock.nsecsElapsed() / 1e9

    def show_stage_cursor(self, visible: bool) -> None:
        """While presenting, the pointer hides itself when it has not moved for a while."""
        self._stage_cursor = Qt.CursorShape.ArrowCursor if visible else Qt.CursorShape.BlankCursor
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._presenting:
            self.setCursor(self._stage_cursor)
        elif self._panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._space_held:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(self._tool.cursor)

    def _content_visible(self) -> bool:
        visible = self._camera.visible_rect(self._viewport())
        bounds = self.content_bounds()
        if bounds is None:
            return visible.contains(Point(0, 0))
        return visible.intersects(bounds)

    def _update_overlays(self) -> None:
        self.zoom_button.setVisible(not self._presenting)
        self.recenter_button.setVisible(
            self._has_viewport and not self._presenting and not self._content_visible()
        )
        self.zoom_button.setText(f"{round(self._camera.zoom * 100)}%")
        self.zoom_button.adjustSize()
        self._place_overlays()

    def _style_overlays(self) -> None:
        t = self._theme
        style = f"""
        QToolButton {{
            background: {t.panel}; color: {t.text}; border: 1px solid {t.border};
            border-radius: 8px; padding: 6px 12px;
        }}
        QToolButton:hover {{ background: {t.hover}; }}
        QToolButton:pressed {{ background: {t.accent_soft}; }}
        """
        self.recenter_button.setStyleSheet(style)
        self.zoom_button.setStyleSheet(style)

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
        s = self._session
        tool_keys: list[tuple[ToolKind, tuple[str, ...]]] = [
            (ToolKind.SELECT, ("V", "1")),
            (ToolKind.HAND, ("H",)),
            (ToolKind.RECTANGLE, ("R", "2")),
            (ToolKind.DIAMOND, ("D", "3")),
            (ToolKind.ELLIPSE, ("O", "4")),
            (ToolKind.ARROW, ("A", "5")),
            (ToolKind.LINE, ("L", "6")),
            (ToolKind.DRAW, ("P", "7")),
            (ToolKind.TEXT, ("T", "8")),
            (ToolKind.IMAGE, ("9",)),
            (ToolKind.ERASER, ("E", "0")),
            (ToolKind.FRAME, ("F",)),
        ]

        def choose(kind: ToolKind) -> Callable[[], None]:
            return lambda: self.set_tool(kind)

        bindings: list[tuple[tuple[str, ...], Callable[[], None]]] = [
            (keys, choose(kind)) for kind, keys in tool_keys
        ]
        bindings += [
            (("Q",), self._toggle_tool_lock),
            (("Ctrl+Z",), s.undo),
            (("Ctrl+Shift+Z", "Ctrl+Y"), s.redo),
            (("Delete", "Backspace"), s.delete_selection),
            (("Ctrl+D",), s.duplicate_selection),
            (("Ctrl+A",), s.select_all),
            (("Ctrl+C",), self.copy),
            (("Ctrl+X",), self.cut),
            (("Ctrl+V",), self.paste),
            (("Ctrl+G",), s.group_selection),
            (("Ctrl+Shift+G",), s.ungroup_selection),
            (("Ctrl+Shift+L",), s.toggle_lock_selection),
            (("Ctrl+]",), lambda: s.reorder_selection(LayerMove.FORWARD)),
            (("Ctrl+[",), lambda: s.reorder_selection(LayerMove.BACKWARD)),
            (("Ctrl+Shift+]", "Ctrl+}"), lambda: s.reorder_selection(LayerMove.FRONT)),
            (("Ctrl+Shift+[", "Ctrl+{"), lambda: s.reorder_selection(LayerMove.BACK)),
            (("Alt+S",), lambda: self.set_snapping(objects=not self.snap_objects)),
            (("Ctrl+'",), lambda: self.set_snapping(grid=not self.snap_grid)),
            (("Shift+1", "!"), self.fit_content),
            (("Shift+2", "@", '"'), self.fit_selection),
            (("Ctrl+=", "Ctrl++"), lambda: self.zoom_by(ZOOM_PER_NOTCH)),
            (("Ctrl+-",), lambda: self.zoom_by(1 / ZOOM_PER_NOTCH)),
            (("Ctrl+0",), self.reset_zoom),
            (("Return", "Enter"), self._edit_selected_text),
            (("Shift+Alt+C",), self.copy_png_requested.emit),
            (("Left",), lambda: s.move_selection(-1, 0)),
            (("Right",), lambda: s.move_selection(1, 0)),
            (("Up",), lambda: s.move_selection(0, -1)),
            (("Down",), lambda: s.move_selection(0, 1)),
            (("Shift+Left",), lambda: s.move_selection(-10, 0)),
            (("Shift+Right",), lambda: s.move_selection(10, 0)),
            (("Shift+Up",), lambda: s.move_selection(0, -10)),
            (("Shift+Down",), lambda: s.move_selection(0, 10)),
        ]
        for keys, handler in bindings:
            action = QAction(self)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            action.triggered.connect(handler)
            self.addAction(action)

    def _toggle_tool_lock(self) -> None:
        self.tool_locked = not self.tool_locked
        self.tool_changed.emit(self._tool.kind)

    def _edit_selected_text(self) -> None:
        selection = self._session.selection
        if len(selection) == 1:
            element = self._session.document.get(next(iter(selection)))
            if isinstance(element, Text | ShapeBase | LinearBase):
                self.edit_text(element.id)

    def frames(self) -> list[Frame]:
        return self._session.document.frames()
