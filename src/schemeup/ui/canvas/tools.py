"""Canvas tools. Each tool turns pointer input into previews and committed edits.

A tool never touches the canvas widget directly; it talks to it through the
small `ToolHost` protocol, which keeps the tools testable and the widget lean.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum, StrEnum
from typing import Protocol

from PySide6.QtCore import Qt

from schemeup.application.editor import EditorSession, expand_groups
from schemeup.domain import commands
from schemeup.domain.binding import binding_for, find_target, rebound
from schemeup.domain.camera import Camera
from schemeup.domain.commands import Changes, ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import (
    LABELED,
    Arrow,
    Element,
    Freedraw,
    Line,
    Text,
    touched,
    with_world_points,
    world_points,
)
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.hit import hit_test, ids_in_rect
from schemeup.domain.snapping import (
    Guide,
    SheetSnap,
    SnapHold,
    SnapTargets,
    snap_point,
    snap_rect,
)
from schemeup.domain.style import MAX_FONT_SIZE, MIN_FONT_SIZE
from schemeup.domain.text import fit_text
from schemeup.ui.canvas.overlays import Handle, SelectionFrame, selection_frame

DRAG_THRESHOLD_PX = 3.0
ANGLE_STEP = math.radians(15)


class ToolKind(StrEnum):
    SELECT = "select"
    HAND = "hand"
    RECTANGLE = "rectangle"
    DIAMOND = "diamond"
    ELLIPSE = "ellipse"
    ARROW = "arrow"
    LINE = "line"
    DRAW = "draw"
    TEXT = "text"
    IMAGE = "image"
    ERASER = "eraser"
    FRAME = "frame"


@dataclass(frozen=True, slots=True)
class Pointer:
    world: Point
    screen: Point
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    pressure: float = 0.5
    tablet: bool = False
    speed: float = 0.0  # how fast the pointer is moving, in screen pixels per second


class ToolHost(Protocol):
    @property
    def session(self) -> EditorSession: ...
    @property
    def camera(self) -> Camera: ...
    def tolerance(self) -> float: ...
    def snap_threshold(self) -> float: ...
    def snap_release(self) -> float: ...
    def snapping(self, pointer: Pointer) -> bool: ...
    def snap_targets(self, exclude: set[str]) -> SnapTargets | None: ...
    def sheet_snap(self) -> SheetSnap | None: ...
    def hit(self, p: Point) -> Element | None: ...
    def container_at(self, p: Point) -> Element | None: ...
    def candidates(self, rect: Rect) -> set[str]: ...
    def set_preview(self, document: Document | None, changed: Iterable[str] = ()) -> None: ...
    def set_guides(self, guides: tuple[Guide, ...]) -> None: ...
    def set_highlight(self, element: Element | None) -> None: ...
    def set_rubber_band(self, rect: Rect | None) -> None: ...
    def set_faded(self, ids: frozenset[str]) -> None: ...
    def handle_at(self, screen: Point) -> Handle | int | None: ...
    def edit_text(self, element_id: str) -> None: ...
    def create_text_at(self, world: Point) -> None: ...
    def finish_creation(self) -> None: ...
    def start_drag_pan(self, screen: Point) -> None: ...
    def drag_pan(self, screen: Point) -> None: ...
    def end_drag_pan(self) -> None: ...
    def set_cursor(self, shape: Qt.CursorShape) -> None: ...


def constrain_angle(origin: Point, p: Point) -> Point:
    """`p` moved so the segment from `origin` sits on a 15 degree step."""
    d = p - origin
    if d.length() == 0:
        return p
    angle = round(math.atan2(d.y, d.x) / ANGLE_STEP) * ANGLE_STEP
    return origin + Point(math.cos(angle), math.sin(angle)) * d.length()


class Tool:
    kind = ToolKind.SELECT
    cursor = Qt.CursorShape.ArrowCursor

    def __init__(self, host: ToolHost) -> None:
        self.host = host

    @property
    def session(self) -> EditorSession:
        return self.host.session

    def activate(self) -> None:
        self.host.set_cursor(self.cursor)

    def deactivate(self) -> None:
        self.cancel()

    def press(self, p: Pointer) -> None:
        pass

    def move(self, p: Pointer) -> None:
        pass

    def hover(self, p: Pointer) -> None:
        pass

    def release(self, p: Pointer) -> None:
        pass

    def double_click(self, p: Pointer) -> None:
        pass

    def key(self, key: int) -> bool:
        """Handle a key press; return True when consumed."""
        return False

    def cancel(self) -> None:
        self.host.set_preview(None)
        self.host.set_guides(())
        self.host.set_highlight(None)

    def snapped(self, p: Pointer, exclude: set[str] | None = None) -> Point:
        if not self.host.snapping(p):
            self.host.set_guides(())
            return p.world
        result = snap_point(
            p.world,
            self.host.snap_targets(exclude or set()),
            self.host.sheet_snap(),
            self.host.snap_threshold(),
        )
        self.host.set_guides(result.guides)
        return p.world + result.offset


class _Mode(Enum):
    IDLE = 0
    PENDING = 1
    MOVE = 2
    RESIZE = 3
    ROTATE = 4
    RUBBER = 5
    POINT = 6


class SelectionTool(Tool):
    kind = ToolKind.SELECT

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self._mode = _Mode.IDLE
        self._start = Pointer(Point(0, 0), Point(0, 0))
        self._origin = Document()
        self._ids: frozenset[str] = frozenset()
        self._changes: Changes = {}
        self._targets: SnapTargets | None = None
        self._frame: SelectionFrame | None = None
        self._handle: Handle = Handle.SE
        self._point_index = 0
        self._start_angle = 0.0
        self._base_selection: frozenset[str] = frozenset()
        self._clicked: frozenset[str] = frozenset()
        self._dup: Changes = {}
        self._start_bounds: Rect | None = None
        self._hold = SnapHold()
        # Offset between where the pointer grabbed a handle and the edge or point it
        # controls, so the shape doesn't jump to the pointer on the first move.
        self._grab = Point(0.0, 0.0)

    def press(self, p: Pointer) -> None:
        session = self.session
        document = session.document
        self._start = p
        self._origin = document
        self._changes = {}
        handle = self.host.handle_at(p.screen) if session.selection else None
        if isinstance(handle, int):
            self._mode = _Mode.POINT
            self._point_index = handle
            self._ids = session.selection
            element = document.get(next(iter(self._ids)))
            if isinstance(element, Line | Arrow):
                self._grab = world_points(element)[handle] - p.world
            return
        if isinstance(handle, Handle):
            self._ids = session.selection
            self._frame = selection_frame(document, self._ids)
            self._handle = handle
            if handle == Handle.ROTATE and self._frame is not None:
                d = p.world - self._frame.center
                self._start_angle = math.atan2(d.y, d.x)
                self._mode = _Mode.ROTATE
            elif self._frame is not None:
                self._mode = _Mode.RESIZE
                self._targets = self.host.snap_targets(set(self._ids))
                local = self._frame.to_local(p.world)
                r = self._frame.rect
                gx = (r.left if "w" in handle.value else r.right) - local.x
                gy = (r.top if handle.value.startswith("n") else r.bottom) - local.y
                self._grab = Point(
                    gx if handle.value[-1] in "we" else 0.0,
                    gy if handle.value[0] in "ns" else 0.0,
                )
            return

        hit = self.host.hit(p.world)
        if hit is not None:
            clicked = frozenset({hit.id}) if p.ctrl else expand_groups(document, [hit.id])
            self._clicked = clicked
            selection = session.selection
            if p.shift:
                selection = selection - clicked if clicked <= selection else selection | clicked
            elif not clicked <= selection:
                selection = clicked
            session.select(selection)
            self._mode = _Mode.PENDING if clicked <= session.selection else _Mode.IDLE
            return

        frame = selection_frame(document, session.selection)
        if frame is not None and len(session.selection) > 1 and frame.rect.contains(p.world):
            self._clicked = frozenset()
            self._mode = _Mode.PENDING
            return

        if not p.shift:
            session.select(())
        self._base_selection = session.selection
        self._mode = _Mode.RUBBER

    def move(self, p: Pointer) -> None:
        if self._mode == _Mode.PENDING:
            if (p.screen - self._start.screen).length() < DRAG_THRESHOLD_PX:
                return
            self._begin_move(p)
        match self._mode:
            case _Mode.MOVE:
                self._drag_move(p)
            case _Mode.RESIZE:
                self._drag_resize(p)
            case _Mode.ROTATE:
                self._drag_rotate(p)
            case _Mode.RUBBER:
                rect = Rect.from_corners(self._start.world, p.world)
                self.host.set_rubber_band(rect)
                inside = ids_in_rect(self._origin, rect, self.host.candidates(rect))
                self.session.select(self._base_selection | expand_groups(self._origin, inside))
            case _Mode.POINT:
                self._drag_point(p)
            case _:
                pass

    def _begin_move(self, p: Pointer) -> None:
        document = self.session.document
        ids = self.session.selection
        self._dup = {}
        if p.alt:
            # Alt-drag leaves the original behind and moves a copy.
            self._dup, new_ids = commands.duplicate(document, ids, Point(0.0, 0.0))
            document = document.with_elements(self._dup)
            ids = frozenset(new_ids)
        self._origin = document
        self._ids = frozenset(commands.with_frame_children(document, ids))
        self._start_bounds = document.bounds_of(self._ids)
        exclude = set(self._ids)
        exclude.update(a.id for a in document.arrows_bound_to(self._ids))
        self._targets = self.host.snap_targets(exclude)
        self._hold.reset()
        self._mode = _Mode.MOVE

    def _drag_move(self, p: Pointer) -> None:
        delta = p.world - self._start.world
        if p.shift:
            delta = Point(delta.x, 0.0) if abs(delta.x) >= abs(delta.y) else Point(0.0, delta.y)
        guides: tuple[Guide, ...] = ()
        if self._start_bounds is not None and self.host.snapping(p):
            sheet, threshold = self.host.sheet_snap(), self.host.snap_threshold()
            raw = self._start_bounds.translated(delta.x, delta.y)
            result = snap_rect(raw, self._targets, sheet, threshold)
            delta = self._hold.apply(delta, result.offset, self.host.snap_release())
            # Guides belong to where the shape ended up, which a held snap keeps off the raw spot.
            held = self._start_bounds.translated(delta.x, delta.y)
            guides = snap_rect(held, self._targets, sheet, threshold).guides
        else:
            self._hold.reset()
        self.host.set_guides(guides)
        changes = commands.move(self._origin, self._ids, delta.x, delta.y)
        self._changes = changes
        self.host.set_preview(self._origin.with_elements(changes), changes.keys())

    def _drag_rotate(self, p: Pointer) -> None:
        if self._frame is None:
            return
        center = self._frame.center
        d = p.world - center
        delta = math.atan2(d.y, d.x) - self._start_angle
        if p.shift:
            base = self._frame.angle
            delta = round((base + delta) / ANGLE_STEP) * ANGLE_STEP - base
        changes = commands.rotate(self._origin, self._ids, center, delta)
        self._changes = changes
        self.host.set_preview(self._origin.with_elements(changes), changes.keys())

    def _drag_resize(self, p: Pointer) -> None:
        frame = self._frame
        if frame is None:
            return
        handle = self._handle
        rect = frame.rect
        pointer = frame.to_world(frame.to_local(p.world) + self._grab)
        if frame.angle == 0 and self.host.snapping(p):
            result = snap_point(
                pointer, self._targets, self.host.sheet_snap(), self.host.snap_threshold()
            )
            offset = result.offset
            if handle in (Handle.N, Handle.S):
                offset = Point(0.0, offset.y)
            elif handle in (Handle.E, Handle.W):
                offset = Point(offset.x, 0.0)
            pointer = pointer + offset
            self.host.set_guides(result.guides)
        local = frame.to_local(pointer)
        x0, y0, x1, y1 = rect.left, rect.top, rect.right, rect.bottom
        if "w" in handle.value:
            x0 = local.x
        if "e" in handle.value:
            x1 = local.x
        if handle.value.startswith("n"):
            y0 = local.y
        if handle.value.startswith("s"):
            y1 = local.y
        corner = handle in (Handle.NW, Handle.NE, Handle.SE, Handle.SW)
        if p.shift and corner and rect.width > 0 and rect.height > 0:
            sx, sy = (x1 - x0) / rect.width, (y1 - y0) / rect.height
            factor = max(abs(sx), abs(sy))
            sx, sy = math.copysign(factor, sx), math.copysign(factor, sy)
            if "w" in handle.value:
                x0 = x1 - rect.width * sx
            else:
                x1 = x0 + rect.width * sx
            if handle.value.startswith("n"):
                y0 = y1 - rect.height * sy
            else:
                y1 = y0 + rect.height * sy
        if p.alt:
            c = rect.center
            if "w" in handle.value or "e" in handle.value:
                half = abs((x1 if "e" in handle.value else x0) - c.x)
                x0, x1 = c.x - half, c.x + half
            if handle.value[0] in "ns":
                half = abs((y0 if handle.value.startswith("n") else y1) - c.y)
                y0, y1 = c.y - half, c.y + half
        new_rect = Rect.from_corners(Point(x0, y0), Point(x1, y1))
        new_rect = Rect(new_rect.x, new_rect.y, max(new_rect.width, 1.0), max(new_rect.height, 1.0))
        changes = self._resized(new_rect, corner)
        self._changes = changes
        self.host.set_preview(self._origin.with_elements(changes), changes.keys())

    def _resized(self, new_rect: Rect, corner: bool) -> Changes:
        frame = self._frame
        assert frame is not None
        document = self._origin
        elements = document.in_z_order(self._ids)
        if len(elements) == 1 and not isinstance(elements[0], Line | Arrow | Freedraw):
            element = elements[0]
            center = new_rect.center.rotated(frame.center, frame.angle)
            w, h = new_rect.width, new_rect.height
            updated: Element = touched(
                element, x=center.x - w / 2, y=center.y - h / 2, width=w, height=h
            )
            if isinstance(updated, Text):
                if corner and frame.rect.height > 0:
                    factor = h / frame.rect.height
                    size = min(max(element.style.font_size * factor, MIN_FONT_SIZE), MAX_FONT_SIZE)
                    updated = touched(
                        updated, style=replace(updated.style, font_size=round(size, 1))
                    )
                    updated = fit_text(updated, self.session.measurer)
                else:
                    updated = fit_text(touched(updated, auto_width=False), self.session.measurer)
            changes = self.session.refit({element.id: updated})
            return commands.with_rebinding(document, changes)
        changes = commands.scale(document, self._ids, frame.rect, new_rect, scale_text=corner)
        return self.session.refit(changes)

    def _drag_point(self, p: Pointer) -> None:
        document = self._origin
        element = document.get(next(iter(self._ids))) if self._ids else None
        if not isinstance(element, Line | Arrow):
            return
        points = world_points(element)
        i = self._point_index
        if not 0 <= i < len(points):
            return
        target = p.world + self._grab
        neighbor = points[i - 1] if i > 0 else points[1] if len(points) > 1 else None
        endpoint = i in (0, len(points) - 1)
        highlight = None
        if isinstance(element, Arrow) and endpoint:
            highlight = find_target(
                document, target, self.host.tolerance(), frozenset({element.id})
            )
        if highlight is None:
            if p.shift and neighbor is not None:
                target = constrain_angle(neighbor, target)
            else:
                target = self.snapped(replace(p, world=target), {element.id})
        self.host.set_highlight(highlight)
        points[i] = target
        updated = with_world_points(element, points)
        if isinstance(updated, Arrow) and endpoint:
            binding = binding_for(highlight, target, self.host.tolerance()) if highlight else None
            if i == 0:
                updated = replace(updated, start_binding=binding)
            else:
                updated = replace(updated, end_binding=binding)
            updated = rebound(document, updated)
        self._changes = {element.id: updated}
        self.host.set_preview(document.with_elements(self._changes), [element.id])

    def release(self, p: Pointer) -> None:
        mode = self._mode
        self._mode = _Mode.IDLE
        self.host.set_rubber_band(None)
        self.host.set_guides(())
        self.host.set_highlight(None)
        if mode == _Mode.PENDING:
            if self._clicked and not p.shift and len(self.session.selection) > len(self._clicked):
                self.session.select(self._clicked)
            return
        if mode in (_Mode.MOVE, _Mode.RESIZE, _Mode.ROTATE, _Mode.POINT) and self._changes:
            changes: Changes = dict(self._dup) if mode == _Mode.MOVE else {}
            changes.update(self._changes)
            preview = self._origin.with_elements(self._changes)
            changes.update(commands.assign_frames(preview, self._ids))
            label = {
                _Mode.MOVE: "Duplicate" if self._dup else "Move",
                _Mode.RESIZE: "Resize",
                _Mode.ROTATE: "Rotate",
                _Mode.POINT: "Edit points",
            }[mode]
            self.session.commit(changes, label, selection=self._ids)
        self._dup = {}
        self._changes = {}
        self.host.set_preview(None)

    def hover(self, p: Pointer) -> None:
        handle = self.host.handle_at(p.screen) if self.session.selection else None
        if isinstance(handle, int):
            self.host.set_cursor(Qt.CursorShape.PointingHandCursor)
            return
        if isinstance(handle, Handle):
            from schemeup.ui.canvas.overlays import cursor_for

            frame = selection_frame(self.session.document, self.session.selection)
            self.host.set_cursor(cursor_for(handle, frame.angle if frame else 0.0))
            return
        hit = self.host.hit(p.world)
        self.host.set_cursor(
            Qt.CursorShape.SizeAllCursor if hit is not None else Qt.CursorShape.ArrowCursor
        )

    def double_click(self, p: Pointer) -> None:
        hit = self.host.hit(p.world)
        if hit is None or not isinstance(hit, (Text, *LABELED)):
            # Inside a shape counts too, even without a fill (as in Excalidraw).
            hit = self.host.container_at(p.world) or hit
        if hit is not None and isinstance(hit, (Text, *LABELED)):
            self.session.select([hit.id])
            self.host.edit_text(hit.id)
        elif hit is None:
            self.host.create_text_at(p.world)

    def cancel(self) -> None:
        super().cancel()
        self._mode = _Mode.IDLE
        self.host.set_rubber_band(None)


class ShapeTool(Tool):
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, host: ToolHost, kind: ToolKind, shape: ShapeKind) -> None:
        super().__init__(host)
        self.kind = kind
        self._shape = shape
        self._element: Element | None = None
        self._start = Point(0, 0)
        self._start_screen = Point(0, 0)

    def press(self, p: Pointer) -> None:
        self._start = self.snapped(p)
        self._start_screen = p.screen
        style = self.session.style
        self._element = commands.make_shape(
            self._shape, Rect(self._start.x, self._start.y, 1, 1), style
        )
        if self._shape == ShapeKind.FRAME:
            count = len(self.session.document.frames()) + 1
            self._element = touched(self._element, name=f"Frame {count}")

    def move(self, p: Pointer) -> None:
        if self._element is None:
            return
        current = self.snapped(p, {self._element.id})
        dx, dy = current.x - self._start.x, current.y - self._start.y
        if p.shift:
            side = max(abs(dx), abs(dy))
            dx, dy = math.copysign(side, dx or 1), math.copysign(side, dy or 1)
        if p.alt:
            rect = Rect(self._start.x - abs(dx), self._start.y - abs(dy), 2 * abs(dx), 2 * abs(dy))
        else:
            rect = Rect.from_corners(self._start, self._start + Point(dx, dy))
        self._element = touched(
            self._element, x=rect.x, y=rect.y, width=rect.width, height=rect.height
        )
        document = self.session.document
        self.host.set_preview(
            document.with_elements({self._element.id: self._element}), [self._element.id]
        )

    def release(self, p: Pointer) -> None:
        element = self._element
        self._element = None
        self.host.set_preview(None)
        self.host.set_guides(())
        if element is None:
            return
        if (p.screen - self._start_screen).length() < DRAG_THRESHOLD_PX * 2:
            w, h = (400.0, 280.0) if self._shape == ShapeKind.FRAME else (120.0, 80.0)
            element = touched(
                element, x=self._start.x - w / 2, y=self._start.y - h / 2, width=w, height=h
            )
        self.session.add([element], "Add shape")
        self.host.finish_creation()


class LinearTool(Tool):
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, host: ToolHost, arrow: bool) -> None:
        super().__init__(host)
        self.kind = ToolKind.ARROW if arrow else ToolKind.LINE
        self._arrow = arrow
        self._points: list[Point] = []
        self._dragging = False
        self._multi = False
        self._press_screen = Point(0, 0)
        self._start_target: Element | None = None
        self._end_target: Element | None = None
        self._element: Line | Arrow | None = None

    def _bind_target(self, p: Point) -> Element | None:
        if not self._arrow:
            return None
        # Arrows bind from a bit further away than clicks hit, so they connect easily.
        return find_target(self.session.document, p, self.host.tolerance() * 2)

    def press(self, p: Pointer) -> None:
        if self._multi:
            last = self._points[-2] if len(self._points) > 1 else None
            if last is not None and (self.host.camera.to_screen(last) - p.screen).length() < 8:
                self._finish()
                return
            self._points.append(self._points[-1])
            return
        self._start_target = self._bind_target(p.world)
        start = p.world if self._start_target is not None else self.snapped(p)
        self._points = [start, start]
        self._dragging = True
        self._press_screen = p.screen
        self._update_preview()

    def move(self, p: Pointer) -> None:
        if self._points:
            self._track(p)

    def hover(self, p: Pointer) -> None:
        if self._multi and self._points:
            self._track(p)
        else:
            self.host.set_highlight(self._bind_target(p.world))

    def _track(self, p: Pointer) -> None:
        anchor = self._points[-2]
        self._end_target = self._bind_target(p.world)
        if self._end_target is not None and self._end_target is not self._start_target:
            point = p.world
            self.host.set_guides(())
        elif p.shift:
            self._end_target = None
            point = constrain_angle(anchor, p.world)
        else:
            self._end_target = None
            exclude = {self._element.id} if self._element else set()
            point = self.snapped(p, exclude)
        self.host.set_highlight(self._end_target)
        self._points[-1] = point
        self._update_preview()

    def release(self, p: Pointer) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if (p.screen - self._press_screen).length() > DRAG_THRESHOLD_PX * 2:
            self._finish()
        else:
            # A click without dragging starts a multi-point line: click to add points,
            # double-click, Enter or Escape to finish.
            self._multi = True

    def double_click(self, p: Pointer) -> None:
        if self._multi:
            if len(self._points) > 2:
                self._points.pop()
            self._finish()

    def key(self, key: int) -> bool:
        if self._multi and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            if len(self._points) > 2:
                self._points.pop()
            self._finish()
            return True
        return False

    def _build(self) -> Line | Arrow | None:
        points = list(self._points)
        while len(points) > 2 and points[-1] == points[-2]:
            points.pop()
        if len(points) < 2:
            return None
        style = self.session.style
        if self._element is None:
            self._element = commands.make_linear(self._arrow, points, style)
        element = with_world_points(self._element, points)
        if isinstance(element, Arrow):
            tolerance = self.host.tolerance()
            start = (
                binding_for(self._start_target, points[0], tolerance)
                if self._start_target
                else None
            )
            end = (
                binding_for(self._end_target, points[-1], tolerance)
                if self._end_target is not None and self._end_target is not self._start_target
                else None
            )
            element = replace(element, start_binding=start, end_binding=end)
            element = rebound(self.session.document, element)
        return element

    def _update_preview(self) -> None:
        element = self._build()
        if element is None:
            return
        self.host.set_preview(
            self.session.document.with_elements({element.id: element}), [element.id]
        )

    def _finish(self) -> None:
        element = self._build()
        self._reset()
        if element is None:
            return
        length = sum(
            a.distance_to(b)
            for a, b in zip(world_points(element), world_points(element)[1:], strict=False)
        )
        if length * self.host.camera.zoom < 4:
            return
        self.session.add([element], "Add arrow" if self._arrow else "Add line")
        self.host.finish_creation()

    def _reset(self) -> None:
        self._points = []
        self._dragging = False
        self._multi = False
        self._element = None
        self._start_target = None
        self._end_target = None
        super().cancel()

    def cancel(self) -> None:
        if self._multi and len(self._points) > 2:
            self._points.pop()
            self._finish()
            return
        self._reset()


class FreedrawTool(Tool):
    kind = ToolKind.DRAW
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self._points: list[Point] = []
        self._pressures: list[float] = []
        self._element: Freedraw | None = None
        self._tablet = False

    def press(self, p: Pointer) -> None:
        self._points = [p.world]
        self._pressures = [p.pressure]
        self._tablet = p.tablet
        self._element = commands.make_freedraw(
            self._points, self._pressures, self.session.style, not p.tablet
        )
        self._show()

    def move(self, p: Pointer) -> None:
        if self._element is None:
            return
        # Skip samples closer than half a screen pixel; they add nothing visible.
        if (p.world - self._points[-1]).length() * self.host.camera.zoom < 0.5:
            return
        self._points.append(p.world)
        self._pressures.append(p.pressure)
        self._show()

    def _show(self) -> None:
        if self._element is None:
            return
        element = with_world_points(self._element, self._points)
        self._element = replace(element, pressures=tuple(self._pressures) if self._tablet else ())
        self.host.set_preview(
            self.session.document.with_elements({self._element.id: self._element}),
            [self._element.id],
        )

    def release(self, p: Pointer) -> None:
        element = self._element
        self._element = None
        self.host.set_preview(None)
        if element is not None:
            self.session.add([replace(element, version=1)], "Draw", select=False)


class TextTool(Tool):
    kind = ToolKind.TEXT
    cursor = Qt.CursorShape.IBeamCursor

    def press(self, p: Pointer) -> None:
        hit = self.host.hit(p.world)
        if hit is None or not isinstance(hit, (Text, *LABELED)):
            hit = self.host.container_at(p.world) or hit
        if hit is not None and isinstance(hit, (Text, *LABELED)):
            self.session.select([hit.id])
            self.host.edit_text(hit.id)
        else:
            self.host.create_text_at(p.world)


class EraserTool(Tool):
    kind = ToolKind.ERASER
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self._erased: set[str] = set()
        self._active = False

    def press(self, p: Pointer) -> None:
        self._active = True
        self._erased = set()
        self._erase_at(p)

    def move(self, p: Pointer) -> None:
        if self._active:
            self._erase_at(p)

    def _erase_at(self, p: Pointer) -> None:
        document = self.session.document
        tolerance = self.host.tolerance()
        area = Rect(p.world.x, p.world.y, 0, 0).inflated(tolerance)
        for element_id in self.host.candidates(area):
            element = document.get(element_id)
            if element is not None and not element.locked and hit_test(element, p.world, tolerance):
                self._erased.add(element_id)
        self.host.set_faded(frozenset(self._erased))

    def release(self, p: Pointer) -> None:
        self._active = False
        erased = self._erased
        self._erased = set()
        self.host.set_faded(frozenset())
        if erased:
            self.session.commit(commands.delete(self.session.document, erased), "Erase")

    def cancel(self) -> None:
        super().cancel()
        self._active = False
        self._erased = set()
        self.host.set_faded(frozenset())


class HandTool(Tool):
    kind = ToolKind.HAND
    cursor = Qt.CursorShape.OpenHandCursor

    def press(self, p: Pointer) -> None:
        self.host.set_cursor(Qt.CursorShape.ClosedHandCursor)
        self.host.start_drag_pan(p.screen)

    def move(self, p: Pointer) -> None:
        self.host.drag_pan(p.screen)

    def release(self, p: Pointer) -> None:
        self.host.end_drag_pan()
        self.host.set_cursor(self.cursor)


__all__ = [
    "EraserTool",
    "FreedrawTool",
    "HandTool",
    "LinearTool",
    "Pointer",
    "SelectionTool",
    "ShapeTool",
    "TextTool",
    "Tool",
    "ToolHost",
    "ToolKind",
    "constrain_angle",
]
