"""Selection frames, handles and guides, drawn in screen space over the canvas."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from schemeup.domain.camera import Camera
from schemeup.domain.document import Document
from schemeup.domain.elements import LINEAR, Element, element_bounds, world_points
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.snapping import Guide

HANDLE_SIZE = 8.0
ROTATE_OFFSET = 26.0
GUIDE_COLOR = "#f03e3e"


class Handle(StrEnum):
    NW = "nw"
    N = "n"
    NE = "ne"
    E = "e"
    SE = "se"
    S = "s"
    SW = "sw"
    W = "w"
    ROTATE = "rotate"


@dataclass(frozen=True, slots=True)
class SelectionFrame:
    """The box handles attach to: an element's own (possibly rotated) box, or the
    axis-aligned bounds of a multi-selection."""

    rect: Rect  # unrotated, in world coordinates
    angle: float

    @property
    def center(self) -> Point:
        return self.rect.center

    def to_world(self, p: Point) -> Point:
        return p.rotated(self.center, self.angle)

    def to_local(self, p: Point) -> Point:
        return p.rotated(self.center, -self.angle)


def selection_frame(document: Document, ids: frozenset[str]) -> SelectionFrame | None:
    elements = document.in_z_order(ids)
    if not elements:
        return None
    if len(elements) == 1:
        e = elements[0]
        if isinstance(e, LINEAR):
            return SelectionFrame(element_bounds(e), 0.0)
        return SelectionFrame(e.local_rect, e.angle)
    bounds = document.bounds_of(ids)
    return SelectionFrame(bounds, 0.0) if bounds is not None else None


def single_linear(document: Document, ids: frozenset[str]) -> Element | None:
    if len(ids) != 1:
        return None
    element = document.get(next(iter(ids)))
    if isinstance(element, LINEAR) and len(element.points) >= 2:
        return element
    return None


def handle_points(frame: SelectionFrame, camera: Camera) -> dict[Handle, Point]:
    """Screen positions of the resize and rotate handles."""
    pad = 4 / camera.zoom
    r = frame.rect.inflated(pad)
    local = {
        Handle.NW: Point(r.left, r.top),
        Handle.N: Point(r.center.x, r.top),
        Handle.NE: Point(r.right, r.top),
        Handle.E: Point(r.right, r.center.y),
        Handle.SE: Point(r.right, r.bottom),
        Handle.S: Point(r.center.x, r.bottom),
        Handle.SW: Point(r.left, r.bottom),
        Handle.W: Point(r.left, r.center.y),
        Handle.ROTATE: Point(r.center.x, r.top - ROTATE_OFFSET / camera.zoom),
    }
    points = {h: camera.to_screen(frame.to_world(p)) for h, p in local.items()}
    # Edge handles on a thin selection would sit on top of the corners.
    screen_w, screen_h = r.width * camera.zoom, r.height * camera.zoom
    if screen_w < 3 * HANDLE_SIZE:
        points.pop(Handle.N)
        points.pop(Handle.S)
    if screen_h < 3 * HANDLE_SIZE:
        points.pop(Handle.E)
        points.pop(Handle.W)
    return points


def cursor_for(handle: Handle, angle: float) -> Qt.CursorShape:
    if handle == Handle.ROTATE:
        return Qt.CursorShape.CrossCursor
    base = {
        Handle.E: 0,
        Handle.SE: 45,
        Handle.S: 90,
        Handle.SW: 135,
        Handle.W: 180,
        Handle.NW: 225,
        Handle.N: 270,
        Handle.NE: 315,
    }[handle]
    direction = (base + math.degrees(angle)) % 180
    if direction < 22.5 or direction >= 157.5:
        return Qt.CursorShape.SizeHorCursor
    if direction < 67.5:
        return Qt.CursorShape.SizeFDiagCursor
    if direction < 112.5:
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.SizeBDiagCursor


def _frame_polygon(frame: SelectionFrame, camera: Camera, pad_px: float) -> QPolygonF:
    r = frame.rect.inflated(pad_px / camera.zoom)
    return QPolygonF([QPointF(*_xy(camera.to_screen(frame.to_world(c)))) for c in r.corners()])


def _xy(p: Point) -> tuple[float, float]:
    return (p.x, p.y)


def paint_selection(
    painter: QPainter,
    document: Document,
    ids: frozenset[str],
    camera: Camera,
    color: str,
    background: str,
    show_handles: bool = True,
) -> None:
    elements = document.in_z_order(ids)
    if not elements:
        return
    accent = QColor(color)
    thin = QPen(accent, 1)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    linear = single_linear(document, ids)
    if linear is not None and isinstance(linear, LINEAR):
        painter.setPen(thin)
        for p in world_points(linear):
            s = camera.to_screen(p)
            painter.setBrush(QColor(background))
            painter.drawEllipse(QPointF(s.x, s.y), 5, 5)
        painter.restore()
        return

    if len(elements) > 1:
        dashed = QPen(accent, 1, Qt.PenStyle.DashLine)
        painter.setPen(dashed)
        for e in elements:
            box = (
                SelectionFrame(element_bounds(e), 0.0)
                if isinstance(e, LINEAR)
                else SelectionFrame(e.local_rect, e.angle)
            )
            painter.drawPolygon(_frame_polygon(box, camera, 2))

    frame = selection_frame(document, ids)
    if frame is None:
        painter.restore()
        return
    painter.setPen(thin)
    painter.drawPolygon(_frame_polygon(frame, camera, 4))
    if show_handles and not any(e.locked for e in elements):
        points = handle_points(frame, camera)
        top = points.get(Handle.N) or camera.to_screen(
            frame.to_world(Point(frame.rect.center.x, frame.rect.top))
        )
        rotate = points[Handle.ROTATE]
        painter.drawLine(QPointF(top.x, top.y), QPointF(rotate.x, rotate.y))
        painter.setBrush(QColor(background))
        half = HANDLE_SIZE / 2
        for handle, p in points.items():
            if handle == Handle.ROTATE:
                painter.drawEllipse(QPointF(p.x, p.y), half + 1, half + 1)
            else:
                painter.save()
                painter.translate(p.x, p.y)
                painter.rotate(math.degrees(frame.angle))
                painter.drawRoundedRect(QRectF(-half, -half, HANDLE_SIZE, HANDLE_SIZE), 2, 2)
                painter.restore()
    painter.restore()


def paint_guides(painter: QPainter, guides: tuple[Guide, ...], camera: Camera) -> None:
    if not guides:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(GUIDE_COLOR), 1)
    painter.setPen(pen)
    for guide in guides:
        a, b = camera.to_screen(guide.start), camera.to_screen(guide.end)
        painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
        if guide.spacing:
            # Small caps at both ends of a gap.
            dx, dy = b.x - a.x, b.y - a.y
            length = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / length * 4, dx / length * 4
            for p in (a, b):
                painter.drawLine(QPointF(p.x - nx, p.y - ny), QPointF(p.x + nx, p.y + ny))
        for mark in guide.marks:
            s = camera.to_screen(mark)
            painter.drawLine(QPointF(s.x - 3, s.y - 3), QPointF(s.x + 3, s.y + 3))
            painter.drawLine(QPointF(s.x - 3, s.y + 3), QPointF(s.x + 3, s.y - 3))
    painter.restore()


def paint_highlight(painter: QPainter, element: Element, camera: Camera, color: str) -> None:
    """Outline of a shape an arrow is about to bind to."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    c.setAlpha(120)
    painter.setPen(QPen(c, 4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    frame = SelectionFrame(element.local_rect, element.angle)
    painter.drawPolygon(_frame_polygon(frame, camera, 6))
    painter.restore()


def paint_rubber_band(painter: QPainter, rect: Rect, camera: Camera, color: str) -> None:
    a = camera.to_screen(Point(rect.left, rect.top))
    b = camera.to_screen(Point(rect.right, rect.bottom))
    fill = QColor(color)
    fill.setAlpha(28)
    painter.save()
    painter.setPen(QPen(QColor(color), 1))
    painter.setBrush(fill)
    painter.drawRect(QRectF(QPointF(a.x, a.y), QPointF(b.x, b.y)))
    painter.restore()
