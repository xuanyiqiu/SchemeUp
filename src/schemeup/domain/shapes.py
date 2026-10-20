"""Turns elements into drawable path parts in their local coordinates.

The renderer converts the parts into QPainterPaths once per element version
and caches them, so this code only runs when an element changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from schemeup.domain.elements import (
    Arrow,
    Diamond,
    Element,
    Ellipse,
    Frame,
    Freedraw,
    Line,
    Rectangle,
)
from schemeup.domain.freehand import StrokeOptions, stroke_outline
from schemeup.domain.geometry import Point
from schemeup.domain.rough import LineTo, MoveTo, Op, RoughGenerator
from schemeup.domain.style import Arrowhead, FillStyle, Roundness, StrokeStyle, Style


class PartKind(StrEnum):
    STROKE = "stroke"  # outline, drawn with the stroke pen
    FILL_LINES = "fill-lines"  # hachure lines, drawn with a thinner pen in the fill color
    FILL_AREA = "fill-area"  # solid area in the fill color
    STROKE_AREA = "stroke-area"  # solid area in the stroke color (freehand, filled arrowheads)


@dataclass(frozen=True, slots=True)
class PathPart:
    kind: PartKind
    ops: tuple[Op, ...]
    smooth: bool = False  # ops form a closed polygon to draw as a smooth curve


def adjusted_roughness(style: Style, width: float, height: float) -> float:
    """Small shapes get less roughness, or they turn into scribbles (as Excalidraw does)."""
    roughness = float(style.roughness)
    big, small = max(abs(width), abs(height)), min(abs(width), abs(height))
    if small >= 20 and big >= 50:
        return roughness
    return min(roughness / (3 if big < 10 else 2), 2.5)


def _generator(element: Element, width: float, height: float) -> RoughGenerator:
    style = element.style
    return RoughGenerator(
        element.seed,
        adjusted_roughness(style, width, height),
        multi_stroke=style.stroke_style == StrokeStyle.SOLID,
        preserve_vertices=style.roughness < 2,
    )


def corner_radius(width: float, height: float) -> float:
    side = min(abs(width), abs(height))
    return 32.0 if side >= 128 else side * 0.25


def _polygon_ops(points: list[Point]) -> tuple[Op, ...]:
    ops: list[Op] = [MoveTo(points[0].x, points[0].y)]
    ops += [LineTo(p.x, p.y) for p in points[1:]]
    ops.append(LineTo(points[0].x, points[0].y))
    return tuple(ops)


def _rounded_outline(points: list[Point], radius: float, segments: int = 6) -> list[Point]:
    """Polygon approximation of a rounded polygon, for fills and hit areas."""
    if radius <= 0:
        return points
    n = len(points)
    result: list[Point] = []
    for i in range(n):
        prev, vertex, nxt = points[i - 1], points[i], points[(i + 1) % n]
        to_prev, to_next = prev - vertex, nxt - vertex
        r = min(radius, to_prev.length() / 2, to_next.length() / 2)
        start = vertex + to_prev.normalized() * r
        end = vertex + to_next.normalized() * r
        for k in range(segments + 1):
            t = k / segments
            a = start + (vertex - start) * t
            b = vertex + (end - vertex) * t
            result.append(a + (b - a) * t)
    return result


def _fill_parts(gen: RoughGenerator, style: Style, polygon: list[Point]) -> list[PathPart]:
    if not style.has_fill or len(polygon) < 3:
        return []
    if style.fill_style == FillStyle.SOLID:
        return [PathPart(PartKind.FILL_AREA, _polygon_ops(polygon))]
    gap = max(style.stroke_width * 4, 4.0)
    ops = gen.hachure(polygon, gap, -41.0)
    if style.fill_style == FillStyle.CROSS_HATCH:
        ops += gen.hachure(polygon, gap, -41.0 + 90)
    return [PathPart(PartKind.FILL_LINES, tuple(ops))]


def _closed_shape(element: Element, vertices: list[Point], round_corners: bool) -> list[PathPart]:
    gen = _generator(element, element.width, element.height)
    radius = corner_radius(element.width, element.height) if round_corners else 0.0
    outline = gen.rounded_polygon(vertices, radius) if radius else gen.polygon(vertices)
    parts = [PathPart(PartKind.STROKE, tuple(outline))]
    fills = _fill_parts(gen, element.style, _rounded_outline(vertices, radius))
    return fills + parts


def ellipse_polygon(width: float, height: float, segments: int = 48) -> list[Point]:
    cx, cy = width / 2, height / 2
    return [
        Point(
            cx + cx * math.cos(2 * math.pi * k / segments),
            cy + cy * math.sin(2 * math.pi * k / segments),
        )
        for k in range(segments)
    ]


def element_parts(element: Element) -> tuple[PathPart, ...]:
    """Drawable parts of an element, in coordinates relative to (element.x, element.y)."""
    w, h = element.width, element.height
    round_corners = element.style.roundness == Roundness.ROUND
    match element:
        case Rectangle():
            vertices = [Point(0, 0), Point(w, 0), Point(w, h), Point(0, h)]
            return tuple(_closed_shape(element, vertices, round_corners))
        case Diamond():
            vertices = [Point(w / 2, 0), Point(w, h / 2), Point(w / 2, h), Point(0, h / 2)]
            return tuple(_closed_shape(element, vertices, round_corners))
        case Ellipse():
            gen = _generator(element, w, h)
            outline, _ = gen.ellipse(w / 2, h / 2, w, h)
            fills = _fill_parts(gen, element.style, ellipse_polygon(w, h))
            return (*fills, PathPart(PartKind.STROKE, tuple(outline)))
        case Line() | Arrow():
            return tuple(_linear_parts(element))
        case Freedraw():
            options = StrokeOptions(
                size=element.style.stroke_width * 4.25,
                simulate_pressure=element.simulate_pressure,
            )
            outline_points = stroke_outline(element.points, element.pressures, options)
            if len(outline_points) < 3:
                return ()
            return (PathPart(PartKind.STROKE_AREA, _polygon_ops(outline_points), smooth=True),)
        case Frame():
            gen = RoughGenerator(element.seed, 0)
            vertices = [Point(0, 0), Point(w, 0), Point(w, h), Point(0, h)]
            return (PathPart(PartKind.STROKE, tuple(gen.rounded_polygon(vertices, 8))),)
        case _:
            return ()


def _linear_parts(element: Line | Arrow) -> list[PathPart]:
    points = list(element.points)
    if len(points) < 2:
        return []
    box_w, box_h = element.width, element.height
    gen = _generator(element, max(box_w, 50), max(box_h, 50))
    curved = element.style.roundness == Roundness.ROUND and len(points) > 2
    body = gen.curve(points) if curved else gen.linear_path(points, close=False)
    parts = [PathPart(PartKind.STROKE, tuple(body))]
    if isinstance(element, Arrow):
        style = element.style
        parts += _arrowhead(gen, style, style.end_head, points[-1], points[-2])
        parts += _arrowhead(gen, style, style.start_head, points[0], points[1])
    return parts


def arrowhead_size(style: Style, segment_length: float) -> float:
    return min(20.0 + 2.0 * style.stroke_width, max(segment_length * 0.4, 6.0))


def _arrowhead(
    gen: RoughGenerator, style: Style, head: Arrowhead, tip: Point, before: Point
) -> list[PathPart]:
    if head == Arrowhead.NONE:
        return []
    direction = (tip - before).normalized()
    if direction.length() == 0:
        return []
    size = arrowhead_size(style, tip.distance_to(before))
    back = tip - direction * size
    if head == Arrowhead.ARROW:
        wing_a = back.rotated(tip, math.radians(25))
        wing_b = back.rotated(tip, math.radians(-25))
        return [PathPart(PartKind.STROKE, tuple(gen.line(wing_a, tip) + gen.line(wing_b, tip)))]
    if head == Arrowhead.TRIANGLE:
        wing_a = back.rotated(tip, math.radians(25))
        wing_b = back.rotated(tip, math.radians(-25))
        triangle = [tip, wing_a, wing_b]
        return [
            PathPart(PartKind.STROKE_AREA, _polygon_ops(triangle)),
            PathPart(PartKind.STROKE, tuple(gen.polygon(triangle))),
        ]
    if head == Arrowhead.DOT:
        radius = size * 0.3
        center = tip - direction * radius
        circle = [
            Point(center.x + radius * math.cos(a), center.y + radius * math.sin(a))
            for a in (2 * math.pi * k / 20 for k in range(20))
        ]
        return [PathPart(PartKind.STROKE_AREA, _polygon_ops(circle), smooth=True)]
    # Bar: a short line across the tip.
    normal = Point(-direction.y, direction.x) * (size * 0.45)
    return [PathPart(PartKind.STROKE, tuple(gen.line(tip + normal, tip - normal)))]
