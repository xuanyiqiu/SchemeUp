"""Smooth pressure-sensitive strokes, ported from perfect-freehand (MIT, Steve Ruiz).

`stroke_outline` turns the raw input points of a freehand stroke into the
outline of a variable-width shape that the renderer fills.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from schemeup.domain.geometry import Point

RATE_OF_PRESSURE_CHANGE = 0.275
FIXED_PI = math.pi + 0.0001


@dataclass(frozen=True, slots=True)
class StrokeOptions:
    size: float = 8.0
    thinning: float = 0.6
    smoothing: float = 0.5
    streamline: float = 0.5
    simulate_pressure: bool = True
    last: bool = True  # the stroke is finished


@dataclass(slots=True)
class _StrokePoint:
    point: Point
    pressure: float
    vector: Point
    distance: float
    running_length: float


def _lerp(a: Point, b: Point, t: float) -> Point:
    return a + (b - a) * t


def _perpendicular(v: Point) -> Point:
    return Point(v.y, -v.x)


def _dot(a: Point, b: Point) -> float:
    return a.x * b.x + a.y * b.y


def _rotate_around(p: Point, center: Point, r: float) -> Point:
    s, c = math.sin(r), math.cos(r)
    px, py = p.x - center.x, p.y - center.y
    return Point(px * c - py * s + center.x, px * s + py * c + center.y)


def _easing(t: float) -> float:
    return math.sin(t * math.pi / 2)


def _stroke_radius(
    size: float, thinning: float, pressure: float, easing: Callable[[float], float]
) -> float:
    return size * easing(0.5 - thinning * (0.5 - pressure))


def _stroke_points(
    points: Sequence[Point], pressures: Sequence[float], options: StrokeOptions
) -> list[_StrokePoint]:
    if not points:
        return []
    t = 0.15 + (1 - options.streamline) * 0.85
    pts = [(p, pressures[i] if i < len(pressures) else 0.5) for i, p in enumerate(points)]
    if len(pts) == 2:
        last = pts[1]
        pts = pts[:1]
        for i in range(1, 5):
            pts.append((_lerp(pts[0][0], last[0], i / 4), last[1]))
    if len(pts) == 1:
        pts.append((pts[0][0] + Point(1, 1), pts[0][1]))

    result = [_StrokePoint(pts[0][0], pts[0][1], Point(1, 1), 0.0, 0.0)]
    has_min_length = False
    running = 0.0
    prev = result[0]
    last_index = len(pts) - 1
    for i in range(1, len(pts)):
        target, pressure = pts[i]
        point = target if options.last and i == last_index else _lerp(prev.point, target, t)
        if point == prev.point:
            continue
        distance = point.distance_to(prev.point)
        running += distance
        if i < last_index and not has_min_length:
            if running < options.size:
                continue
            has_min_length = True
        prev = _StrokePoint(point, pressure, (prev.point - point).normalized(), distance, running)
        result.append(prev)
    result[0].vector = result[1].vector if len(result) > 1 else Point(0, 0)
    return result


def stroke_outline(
    points: Sequence[Point], pressures: Sequence[float] = (), options: StrokeOptions | None = None
) -> list[Point]:
    """Outline polygon of a freehand stroke drawn through `points`."""
    options = options or StrokeOptions()
    stroke = _stroke_points(points, pressures, options)
    size = options.size
    if not stroke or size <= 0:
        return []
    total = stroke[-1].running_length
    min_distance = (size * options.smoothing) ** 2
    left: list[Point] = []
    right: list[Point] = []

    prev_pressure = stroke[0].pressure
    for sp in stroke[:10]:
        pressure = sp.pressure
        if options.simulate_pressure:
            speed = min(1.0, sp.distance / size)
            rest = min(1.0, 1 - speed)
            pressure = min(
                1.0, prev_pressure + (rest - prev_pressure) * (speed * RATE_OF_PRESSURE_CHANGE)
            )
        prev_pressure = (prev_pressure + pressure) / 2

    radius = _stroke_radius(size, options.thinning, stroke[-1].pressure, _easing)
    first_radius: float | None = None
    prev_vector = stroke[0].vector
    pl = pr = stroke[0].point
    tl = tr = pl
    prev_sharp = False

    for i, sp in enumerate(stroke):
        pressure = sp.pressure
        if i < len(stroke) - 1 and total - sp.running_length < 3:
            continue
        if options.thinning:
            if options.simulate_pressure:
                speed = min(1.0, sp.distance / size)
                rest = min(1.0, 1 - speed)
                pressure = min(
                    1.0, prev_pressure + (rest - prev_pressure) * (speed * RATE_OF_PRESSURE_CHANGE)
                )
            radius = _stroke_radius(size, options.thinning, pressure, _easing)
        else:
            radius = size / 2
        if first_radius is None:
            first_radius = radius
        radius = max(0.01, radius)

        next_vector = (stroke[i + 1] if i < len(stroke) - 1 else sp).vector
        next_dpr = _dot(sp.vector, next_vector) if i < len(stroke) - 1 else 1.0
        prev_dpr = _dot(sp.vector, prev_vector)
        sharp = prev_dpr < 0 and not prev_sharp
        next_sharp = next_dpr < 0

        if sharp or next_sharp:
            offset = _perpendicular(prev_vector) * radius
            steps = 13
            for k in range(steps + 1):
                t = k / steps
                tl = _rotate_around(sp.point - offset, sp.point, FIXED_PI * t)
                left.append(tl)
                tr = _rotate_around(sp.point + offset, sp.point, FIXED_PI * -t)
                right.append(tr)
            pl, pr = tl, tr
            if next_sharp:
                prev_sharp = True
            continue
        prev_sharp = False

        if i == len(stroke) - 1:
            offset = _perpendicular(sp.vector) * radius
            left.append(sp.point - offset)
            right.append(sp.point + offset)
            continue

        offset = _perpendicular(_lerp(next_vector, sp.vector, next_dpr)) * radius
        tl = sp.point - offset
        if i <= 1 or (pl.x - tl.x) ** 2 + (pl.y - tl.y) ** 2 > min_distance:
            left.append(tl)
            pl = tl
        tr = sp.point + offset
        if i <= 1 or (pr.x - tr.x) ** 2 + (pr.y - tr.y) ** 2 > min_distance:
            right.append(tr)
            pr = tr
        prev_pressure = pressure
        prev_vector = sp.vector

    first = stroke[0].point
    last = stroke[-1].point if len(stroke) > 1 else stroke[0].point + Point(1, 1)
    if len(stroke) == 1 or not left or not right:
        r = first_radius or radius
        start = first + _perpendicular((first - last).normalized()) * -r
        return [_rotate_around(start, first, FIXED_PI * 2 * k / 13) for k in range(1, 14)]

    start_cap = [_rotate_around(right[0], first, FIXED_PI * k / 13) for k in range(1, 14)]
    direction = _perpendicular(-stroke[-1].vector)
    cap_start = last + direction * radius
    end_cap = [_rotate_around(cap_start, last, FIXED_PI * 3 * k / 29) for k in range(1, 29)]
    return left + end_cap + right[::-1] + start_cap
