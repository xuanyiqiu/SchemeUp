"""Small immutable 2D types and helpers used across the domain."""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, k: float) -> Point:
        return Point(self.x * k, self.y * k)

    def __neg__(self) -> Point:
        return Point(-self.x, -self.y)

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def normalized(self) -> Point:
        length = self.length()
        return Point(0.0, 0.0) if length == 0 else Point(self.x / length, self.y / length)

    def rotated(self, center: Point, angle: float) -> Point:
        """This point rotated by `angle` radians (clockwise on screen, y points down)."""
        if angle == 0:
            return self
        c, s = math.cos(angle), math.sin(angle)
        dx, dy = self.x - center.x, self.y - center.y
        return Point(center.x + dx * c - dy * s, center.y + dx * s + dy * c)


@dataclass(frozen=True, slots=True)
class Size:
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @staticmethod
    def from_corners(a: Point, b: Point) -> Rect:
        return Rect(min(a.x, b.x), min(a.y, b.y), abs(b.x - a.x), abs(b.y - a.y))

    @staticmethod
    def from_points(points: Iterable[Point]) -> Rect:
        xs: list[float] = []
        ys: list[float] = []
        for p in points:
            xs.append(p.x)
            ys.append(p.y)
        if not xs:
            raise ValueError("cannot build a rect from no points")
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def corners(self) -> tuple[Point, Point, Point, Point]:
        return (
            Point(self.left, self.top),
            Point(self.right, self.top),
            Point(self.right, self.bottom),
            Point(self.left, self.bottom),
        )

    def contains(self, p: Point) -> bool:
        return self.left <= p.x <= self.right and self.top <= p.y <= self.bottom

    def contains_rect(self, other: Rect) -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def intersects(self, other: Rect) -> bool:
        return not (
            other.left > self.right
            or other.right < self.left
            or other.top > self.bottom
            or other.bottom < self.top
        )

    def union(self, other: Rect) -> Rect:
        left, top = min(self.left, other.left), min(self.top, other.top)
        right, bottom = max(self.right, other.right), max(self.bottom, other.bottom)
        return Rect(left, top, right - left, bottom - top)

    def inflated(self, dx: float, dy: float | None = None) -> Rect:
        dy = dx if dy is None else dy
        return Rect(self.x - dx, self.y - dy, self.width + 2 * dx, self.height + 2 * dy)

    def translated(self, dx: float, dy: float) -> Rect:
        return Rect(self.x + dx, self.y + dy, self.width, self.height)


def union_all(rects: Iterable[Rect]) -> Rect | None:
    result: Rect | None = None
    for rect in rects:
        result = rect if result is None else result.union(rect)
    return result


def distance_to_segment(p: Point, a: Point, b: Point) -> float:
    ab = b - a
    length_sq = ab.x * ab.x + ab.y * ab.y
    if length_sq == 0:
        return p.distance_to(a)
    t = ((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / length_sq
    t = min(max(t, 0.0), 1.0)
    return p.distance_to(a + ab * t)


def distance_to_polyline(p: Point, points: Iterable[Point]) -> float:
    best = math.inf
    previous: Point | None = None
    for point in points:
        if previous is not None:
            best = min(best, distance_to_segment(p, previous, point))
        previous = point
    if previous is not None and best == math.inf:
        best = p.distance_to(previous)
    return best


def polyline_length(points: list[Point]) -> float:
    return sum(a.distance_to(b) for a, b in itertools.pairwise(points))


def point_along(points: list[Point], fraction: float) -> Point:
    """The point at `fraction` (0..1) of the total length of a polyline."""
    if not points:
        raise ValueError("empty polyline")
    total = polyline_length(points)
    if total == 0:
        return points[0]
    remaining = total * min(max(fraction, 0.0), 1.0)
    for a, b in itertools.pairwise(points):
        segment = a.distance_to(b)
        if remaining <= segment and segment > 0:
            return a + (b - a) * (remaining / segment)
        remaining -= segment
    return points[-1]
