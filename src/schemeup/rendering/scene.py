"""Draws canvas elements with QPainter.

The same renderer paints the screen, PNG/SVG/PDF exports and thumbnails.
Geometry for each element is generated once and cached; it is only rebuilt
when something that changes its shape (size, style, seed, points) changes,
so moving an element never regenerates its rough paths.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Protocol

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from schemeup.domain.document import Document
from schemeup.domain.elements import (
    LINEAR,
    SHAPES,
    Element,
    Frame,
    Image,
    LinearBase,
    ShapeBase,
    Text,
)
from schemeup.domain.geometry import Size
from schemeup.domain.palette import dark_variant
from schemeup.domain.rough import CurveTo, LineTo, MoveTo, Op
from schemeup.domain.shapes import PartKind, PathPart, element_parts
from schemeup.domain.style import TRANSPARENT, FontFamily, StrokeStyle, Style, TextAlign
from schemeup.domain.text import ARROW_LABEL_MAX_WIDTH, arrow_label_center, label_area, place_block
from schemeup.rendering.text import TextBlock, draw_block, layout_text

FRAME_COLOR = "#868e96"


class ImageProvider(Protocol):
    def image(self, asset_id: str) -> QImage | None: ...


def ops_to_path(ops: Iterable[Op]) -> QPainterPath:
    path = QPainterPath()
    for op in ops:
        match op:
            case MoveTo(x, y):
                path.moveTo(x, y)
            case LineTo(x, y):
                path.lineTo(x, y)
            case CurveTo(c1x, c1y, c2x, c2y, x, y):
                path.cubicTo(c1x, c1y, c2x, c2y, x, y)
    return path


def smooth_closed_path(points: list[tuple[float, float]]) -> QPainterPath:
    """A closed curve through the midpoints of a polygon, with its vertices as control points."""
    path = QPainterPath()
    n = len(points)
    if n < 3:
        return path

    def mid(a: tuple[float, float], b: tuple[float, float]) -> QPointF:
        return QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    path.moveTo(mid(points[0], points[1]))
    for i in range(1, n + 1):
        a, b = points[i % n], points[(i + 1) % n]
        path.quadTo(QPointF(*a), mid(a, b))
    path.closeSubpath()
    path.setFillRule(Qt.FillRule.WindingFill)
    return path


def _part_path(part: PathPart) -> QPainterPath:
    if part.smooth:
        points = [(op.x, op.y) for op in part.ops if isinstance(op, MoveTo | LineTo)]
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        return smooth_closed_path(points)
    path = ops_to_path(part.ops)
    path.setFillRule(Qt.FillRule.WindingFill)
    return path


def fitted_block(text: str, style: Style, max_width: float) -> TextBlock:
    """Layout that keeps short text on its natural width and wraps long text at `max_width`."""
    natural = layout_text(text, style.font_family, style.font_size, None, style.text_align)
    if natural.width <= max_width:
        return natural
    return layout_text(text, style.font_family, style.font_size, max_width, style.text_align)


def _geometry_key(element: Element) -> tuple[Any, ...]:
    points = getattr(element, "points", None)
    pressures = getattr(element, "pressures", None)
    return (
        type(element),
        element.width,
        element.height,
        element.style,
        element.seed,
        points,
        pressures,
    )


class SceneRenderer:
    def __init__(self, images: ImageProvider | None = None) -> None:
        self._images = images
        self._parts: dict[
            str, tuple[Element, tuple[Any, ...], list[tuple[PartKind, QPainterPath]]]
        ] = {}
        self._colors: dict[tuple[str, bool], QColor] = {}

    def set_images(self, images: ImageProvider | None) -> None:
        self._images = images

    def color(self, value: str, dark: bool) -> QColor:
        key = (value, dark)
        cached = self._colors.get(key)
        if cached is None:
            if value == TRANSPARENT:
                cached = QColor(0, 0, 0, 0)
            else:
                cached = QColor(dark_variant(value) if dark else value)
            self._colors[key] = cached
        return cached

    def prune(self, document: Document) -> None:
        """Drop cached geometry for elements that no longer exist."""
        for element_id in [i for i in self._parts if i not in document.elements]:
            del self._parts[element_id]

    def parts(self, element: Element) -> list[tuple[PartKind, QPainterPath]]:
        cached = self._parts.get(element.id)
        if cached is not None:
            if cached[0] is element:
                return cached[2]
            key = _geometry_key(element)
            if cached[1] == key:
                self._parts[element.id] = (element, key, cached[2])
                return cached[2]
        else:
            key = _geometry_key(element)
        paths = [(part.kind, _part_path(part)) for part in element_parts(element)]
        self._parts[element.id] = (element, key, paths)
        return paths

    def paint(
        self,
        painter: QPainter,
        document: Document,
        elements: Iterable[Element],
        *,
        dark: bool = False,
        background: str = "#ffffff",
        hidden: frozenset[str] = frozenset(),
        faded: frozenset[str] = frozenset(),
        editing_text: str | None = None,
    ) -> None:
        frames = {f.id: f for f in document.frames()}
        for element in elements:
            if element.id in hidden:
                continue
            frame = frames.get(element.frame_id) if element.frame_id else None
            if frame is not None:
                painter.save()
                painter.setClipRect(
                    QRectF(frame.x, frame.y, frame.width, frame.height),
                    Qt.ClipOperation.IntersectClip,
                )
            self.paint_element(
                painter,
                element,
                dark=dark,
                background=background,
                faded=element.id in faded,
                hide_text=element.id == editing_text,
            )
            if frame is not None:
                painter.restore()

    def paint_element(
        self,
        painter: QPainter,
        element: Element,
        *,
        dark: bool = False,
        background: str = "#ffffff",
        faded: bool = False,
        hide_text: bool = False,
    ) -> None:
        style = element.style
        painter.save()
        painter.setOpacity(painter.opacity() * (style.opacity / 100) * (0.3 if faded else 1.0))
        painter.translate(element.x, element.y)
        if element.angle:
            painter.translate(element.width / 2, element.height / 2)
            painter.rotate(math.degrees(element.angle))
            painter.translate(-element.width / 2, -element.height / 2)

        if isinstance(element, Text):
            if not hide_text:
                block = layout_text(
                    element.text,
                    style.font_family,
                    style.font_size,
                    None if element.auto_width else element.width,
                    style.text_align,
                )
                draw_block(painter, block, 0.0, 0.0, self.color(style.stroke_color, dark))
        elif isinstance(element, Image):
            self._paint_image(painter, element)
        elif isinstance(element, Frame):
            self._paint_frame(painter, element, dark)
        else:
            self._paint_parts(painter, element, dark)
            if isinstance(element, SHAPES) and element.label and not hide_text:
                self._paint_shape_label(painter, element, dark)
            elif isinstance(element, LINEAR) and element.label and not hide_text:
                self._paint_linear_label(painter, element, dark, background)
        painter.restore()

    def _stroke_pen(self, element: Element, dark: bool) -> QPen:
        style = element.style
        width = style.stroke_width + (0.5 if style.stroke_style != StrokeStyle.SOLID else 0.0)
        pen = QPen(self.color(style.stroke_color, dark), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if style.stroke_style == StrokeStyle.DASHED:
            pen.setDashPattern([8 / width, (8 + width) / width])
        elif style.stroke_style == StrokeStyle.DOTTED:
            pen.setDashPattern([0.01, (6 + width) / width])
        return pen

    def _paint_parts(self, painter: QPainter, element: Element, dark: bool) -> None:
        style = element.style
        for kind, path in self.parts(element):
            if kind == PartKind.STROKE:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(self._stroke_pen(element, dark))
                painter.drawPath(path)
            elif kind == PartKind.FILL_LINES:
                pen = QPen(self.color(style.fill_color, dark), max(style.stroke_width / 2, 0.5))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(pen)
                painter.drawPath(path)
            elif kind == PartKind.FILL_AREA:
                painter.fillPath(path, self.color(style.fill_color, dark))
            elif kind == PartKind.STROKE_AREA:
                painter.fillPath(path, self.color(style.stroke_color, dark))

    def _paint_shape_label(self, painter: QPainter, shape: ShapeBase, dark: bool) -> None:
        style = shape.style
        area = label_area(shape).translated(-shape.x, -shape.y)
        block = fitted_block(shape.label, style, area.width)
        box = place_block(area, Size(block.width, block.height), style)
        draw_block(painter, block, box.x, box.y, self.color(style.stroke_color, dark))

    def _paint_linear_label(
        self, painter: QPainter, element: LinearBase, dark: bool, background: str
    ) -> None:
        style = element.style
        center = arrow_label_center(element)
        local = QPointF(center.x - element.x, center.y - element.y)
        block = fitted_block(element.label, style, ARROW_LABEL_MAX_WIDTH)
        x, y = local.x() - block.width / 2, local.y() - block.height / 2
        pad = 4.0
        painter.save()
        painter.setOpacity(1.0)
        painter.fillRect(
            QRectF(x - pad, y - pad / 2, block.width + 2 * pad, block.height + pad),
            self.color(background, dark),
        )
        painter.restore()
        draw_block(painter, block, x, y, self.color(style.stroke_color, dark))

    def _paint_image(self, painter: QPainter, element: Image) -> None:
        target = QRectF(0, 0, element.width, element.height)
        image = self._images.image(element.asset_id) if self._images else None
        if image is None or image.isNull():
            painter.fillRect(target, QColor(233, 236, 239))
            pen = QPen(QColor(173, 181, 189), 1.5)
            painter.setPen(pen)
            painter.drawRect(target)
            painter.drawLine(target.topLeft(), target.bottomRight())
            painter.drawLine(target.topRight(), target.bottomLeft())
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, image)

    def _paint_frame(self, painter: QPainter, frame: Frame, dark: bool) -> None:
        for _, path in self.parts(frame):
            pen = QPen(self.color(FRAME_COLOR, dark), 1.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            painter.drawPath(path)
        block = layout_text(frame.name or " ", FontFamily.NORMAL, 14, None, TextAlign.LEFT)
        draw_block(painter, block, 0.0, -block.height - 4, self.color(FRAME_COLOR, dark))
