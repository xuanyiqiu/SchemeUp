"""Hand-drawn geometry, ported from the core of rough.js (MIT, Preet Shihn).

The generator turns lines, polygons, ellipses and curves into drawing
operations with small random offsets. The randomness comes from the same
Park-Miller generator rough.js uses, seeded per element, so a shape looks
identical every time it is drawn.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from schemeup.domain.geometry import Point


@dataclass(frozen=True, slots=True)
class MoveTo:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class LineTo:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class CurveTo:
    c1x: float
    c1y: float
    c2x: float
    c2y: float
    x: float
    y: float


type Op = MoveTo | LineTo | CurveTo


class Random:
    def __init__(self, seed: int) -> None:
        self._seed = seed

    def next(self) -> float:
        # Math.imul(48271, seed) in JavaScript: a 32-bit signed multiplication.
        value = (48271 * self._seed) & 0xFFFFFFFF
        self._seed = value - 0x100000000 if value >= 0x80000000 else value
        return (self._seed & 0x7FFFFFFF) / 2**31


class RoughGenerator:
    def __init__(
        self,
        seed: int,
        roughness: float,
        *,
        bowing: float = 1.0,
        max_offset: float = 2.0,
        multi_stroke: bool = True,
        preserve_vertices: bool = False,
    ) -> None:
        self.random = Random(seed)
        self.roughness = roughness
        self.bowing = bowing
        self.max_offset = max_offset
        self.multi_stroke = multi_stroke and roughness > 0
        self.preserve_vertices = preserve_vertices
        self.curve_fitting = 0.95
        self.curve_tightness = 0.0
        self.curve_step_count = 9.0

    # Randomness

    def _offset(self, low: float, high: float, gain: float = 1.0) -> float:
        return self.roughness * gain * (self.random.next() * (high - low) + low)

    def _offset_opt(self, x: float, gain: float = 1.0) -> float:
        return self._offset(-x, x, gain)

    # Lines

    def line(self, a: Point, b: Point, filling: bool = False) -> list[Op]:
        return self._double_line(a.x, a.y, b.x, b.y, filling)

    def _double_line(self, x1: float, y1: float, x2: float, y2: float, filling: bool) -> list[Op]:
        first = self._line(x1, y1, x2, y2, move=True, overlay=False)
        if not self.multi_stroke:
            return first
        return first + self._line(x1, y1, x2, y2, move=True, overlay=True)

    def _line(
        self, x1: float, y1: float, x2: float, y2: float, *, move: bool, overlay: bool
    ) -> list[Op]:
        length_sq = (x1 - x2) ** 2 + (y1 - y2) ** 2
        length = math.sqrt(length_sq)
        if length < 200:
            gain = 1.0
        elif length > 500:
            gain = 0.4
        else:
            gain = -0.0016668 * length + 1.233334
        offset = self.max_offset
        if offset * offset * 100 > length_sq:
            offset = length / 10
        half = offset / 2
        diverge = 0.2 + self.random.next() * 0.2
        mid_x = self.bowing * self.max_offset * (y2 - y1) / 200
        mid_y = self.bowing * self.max_offset * (x1 - x2) / 200
        mid_x = self._offset_opt(mid_x, gain)
        mid_y = self._offset_opt(mid_y, gain)
        spread = half if overlay else offset
        keep = self.preserve_vertices

        def jitter() -> float:
            return self._offset_opt(spread, gain)

        ops: list[Op] = []
        if move:
            ops.append(MoveTo(x1 + (0 if keep else jitter()), y1 + (0 if keep else jitter())))
        ops.append(
            CurveTo(
                mid_x + x1 + (x2 - x1) * diverge + jitter(),
                mid_y + y1 + (y2 - y1) * diverge + jitter(),
                mid_x + x1 + 2 * (x2 - x1) * diverge + jitter(),
                mid_y + y1 + 2 * (y2 - y1) * diverge + jitter(),
                x2 + (0 if keep else jitter()),
                y2 + (0 if keep else jitter()),
            )
        )
        return ops

    def linear_path(self, points: Sequence[Point], close: bool) -> list[Op]:
        if len(points) < 2:
            return []
        ops: list[Op] = []
        for a, b in itertools.pairwise(points):
            ops += self._double_line(a.x, a.y, b.x, b.y, False)
        if close and len(points) > 2:
            a, b = points[-1], points[0]
            ops += self._double_line(a.x, a.y, b.x, b.y, False)
        return ops

    def polygon(self, points: Sequence[Point]) -> list[Op]:
        return self.linear_path(points, close=True)

    def rounded_polygon(self, points: Sequence[Point], radius: float) -> list[Op]:
        """A closed polygon with its corners rounded off by `radius`."""
        n = len(points)
        if n < 3 or radius <= 0:
            return self.polygon(points)
        ops: list[Op] = []
        corners = [_corner(points[i - 1], points[i], points[(i + 1) % n], radius) for i in range(n)]
        for i in range(n):
            _, start_out = corners[i][0], corners[i][1]
            end_in = corners[(i + 1) % n][0]
            ops += self._double_line(start_out.x, start_out.y, end_in.x, end_in.y, False)
            nxt = corners[(i + 1) % n]
            vertex = points[(i + 1) % n]
            ops += self.bezier(nxt[0], vertex, vertex, nxt[1])
        return ops

    def bezier(self, start: Point, c1: Point, c2: Point, end: Point) -> list[Op]:
        """A cubic Bézier with the rough.js double-stroke jitter (_bezierTo)."""
        ros = (self.max_offset or 1.0, (self.max_offset or 1.0) + 0.3)
        iterations = 2 if self.multi_stroke else 1
        ops: list[Op] = []
        for i in range(iterations):
            if i == 0:
                ops.append(MoveTo(start.x, start.y))
            else:
                ops.append(
                    MoveTo(start.x + self._offset_opt(ros[0]), start.y + self._offset_opt(ros[0]))
                )
            end_x = end.x + (0 if self.preserve_vertices else self._offset_opt(ros[i]))
            end_y = end.y + (0 if self.preserve_vertices else self._offset_opt(ros[i]))
            ops.append(
                CurveTo(
                    c1.x + self._offset_opt(ros[i]),
                    c1.y + self._offset_opt(ros[i]),
                    c2.x + self._offset_opt(ros[i]),
                    c2.y + self._offset_opt(ros[i]),
                    end_x,
                    end_y,
                )
            )
        return ops

    # Ellipses and curves

    def ellipse(
        self, cx: float, cy: float, width: float, height: float
    ) -> tuple[list[Op], list[Point]]:
        """Outline operations plus the estimated outline points (used for fills)."""
        psq = math.sqrt(math.pi * 2 * math.sqrt(((width / 2) ** 2 + (height / 2) ** 2) / 2))
        steps = math.ceil(
            max(self.curve_step_count, (self.curve_step_count / math.sqrt(200)) * psq)
        )
        increment = math.pi * 2 / steps
        rx, ry = abs(width / 2), abs(height / 2)
        fit = 1 - self.curve_fitting
        rx += self._offset_opt(rx * fit)
        ry += self._offset_opt(ry * fit)
        overlap = increment * self._offset(0.1, self._offset(0.4, 1))
        points, core = self._ellipse_points(increment, cx, cy, rx, ry, 1, overlap)
        ops = self._curve(points)
        if self.multi_stroke:
            second, _ = self._ellipse_points(increment, cx, cy, rx, ry, 1.5, 0)
            ops += self._curve(second)
        return ops, core

    def _ellipse_points(
        self,
        increment: float,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        offset: float,
        overlap: float,
    ) -> tuple[list[Point], list[Point]]:
        core: list[Point] = []
        points: list[Point] = []
        if self.roughness == 0:
            increment /= 4
            points.append(Point(cx + rx * math.cos(-increment), cy + ry * math.sin(-increment)))
            angle = 0.0
            while angle <= math.pi * 2:
                p = Point(cx + rx * math.cos(angle), cy + ry * math.sin(angle))
                core.append(p)
                points.append(p)
                angle += increment
            points.append(Point(cx + rx, cy))
            points.append(Point(cx + rx * math.cos(increment), cy + ry * math.sin(increment)))
            return points, core

        rad_offset = self._offset_opt(0.5) - math.pi / 2

        def jittered(scale: float, angle: float) -> Point:
            return Point(
                self._offset_opt(offset) + cx + scale * rx * math.cos(angle),
                self._offset_opt(offset) + cy + scale * ry * math.sin(angle),
            )

        points.append(jittered(0.9, rad_offset - increment))
        end_angle = math.pi * 2 + rad_offset - 0.01
        angle = rad_offset
        while angle < end_angle:
            p = jittered(1.0, angle)
            core.append(p)
            points.append(p)
            angle += increment
        points.append(jittered(1.0, rad_offset + math.pi * 2 + overlap * 0.5))
        points.append(jittered(0.98, rad_offset + overlap))
        points.append(jittered(0.9, rad_offset + overlap * 0.5))
        return points, core

    def curve(self, points: Sequence[Point]) -> list[Op]:
        """A smooth hand-drawn curve through `points` (for curved lines and arrows)."""
        if not points:
            return []
        ops = self._curve_with_offset(points, 1 * (1 + self.roughness * 0.2))
        if self.multi_stroke:
            ops += self._curve_with_offset(points, 1.5 * (1 + self.roughness * 0.22))
        return ops

    def _curve_with_offset(self, points: Sequence[Point], offset: float) -> list[Op]:
        def jitter(p: Point) -> Point:
            return Point(p.x + self._offset_opt(offset), p.y + self._offset_opt(offset))

        ps = [jitter(points[0]), jitter(points[0])]
        for i in range(1, len(points)):
            ps.append(jitter(points[i]))
            if i == len(points) - 1:
                ps.append(jitter(points[i]))
        return self._curve(ps)

    def _curve(self, points: Sequence[Point]) -> list[Op]:
        n = len(points)
        ops: list[Op] = []
        if n > 3:
            s = 1 - self.curve_tightness
            ops.append(MoveTo(points[1].x, points[1].y))
            for i in range(1, n - 2):
                p_prev, p, p_next, p_next2 = points[i - 1], points[i], points[i + 1], points[i + 2]
                ops.append(
                    CurveTo(
                        p.x + (s * p_next.x - s * p_prev.x) / 6,
                        p.y + (s * p_next.y - s * p_prev.y) / 6,
                        p_next.x + (s * p.x - s * p_next2.x) / 6,
                        p_next.y + (s * p.y - s * p_next2.y) / 6,
                        p_next.x,
                        p_next.y,
                    )
                )
        elif n == 3:
            ops.append(MoveTo(points[1].x, points[1].y))
            ops.append(
                CurveTo(
                    points[1].x, points[1].y, points[2].x, points[2].y, points[2].x, points[2].y
                )
            )
        elif n == 2:
            ops += self._line(
                points[0].x, points[0].y, points[1].x, points[1].y, move=True, overlay=True
            )
        return ops

    # Fills

    def hachure(self, polygon: Sequence[Point], gap: float, angle_deg: float = -41.0) -> list[Op]:
        ops: list[Op] = []
        for a, b in hachure_lines(polygon, gap, angle_deg):
            ops += self._double_line(a.x, a.y, b.x, b.y, True)
        return ops


def _corner(previous: Point, vertex: Point, following: Point, radius: float) -> tuple[Point, Point]:
    """Points on the two edges of a corner where the rounding starts and ends."""
    to_prev, to_next = previous - vertex, following - vertex
    r = min(radius, to_prev.length() / 2, to_next.length() / 2)
    return vertex + to_prev.normalized() * r, vertex + to_next.normalized() * r


def hachure_lines(
    polygon: Sequence[Point], gap: float, angle_deg: float
) -> list[tuple[Point, Point]]:
    """Parallel fill lines clipped to a polygon (scan-line intersection)."""
    if len(polygon) < 3 or gap <= 0:
        return []
    angle = math.radians(angle_deg)
    origin = Point(0.0, 0.0)
    rotated = [p.rotated(origin, -angle) for p in polygon]
    top = min(p.y for p in rotated)
    bottom = max(p.y for p in rotated)
    edges = list(zip(rotated, rotated[1:] + rotated[:1], strict=False))
    lines: list[tuple[Point, Point]] = []
    y = top + gap / 2
    while y < bottom:
        xs: list[float] = []
        for a, b in edges:
            if (a.y <= y < b.y) or (b.y <= y < a.y):
                xs.append(a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            start = Point(xs[i], y).rotated(origin, angle)
            end = Point(xs[i + 1], y).rotated(origin, angle)
            lines.append((start, end))
        y += gap
    return lines
