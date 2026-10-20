"""Canvas elements.

Elements are immutable. Every change produces a new instance with a higher
`version`, which is what the render caches key on. Linear elements (lines,
arrows, freehand strokes) store their points relative to (x, y); the first
point is always (0, 0).
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from schemeup.domain.geometry import Point, Rect
from schemeup.domain.style import DEFAULT_STYLE, Style


@dataclass(frozen=True, slots=True, kw_only=True)
class ElementBase:
    id: str
    x: float
    y: float
    width: float = 0.0
    height: float = 0.0
    angle: float = 0.0  # radians, clockwise around the center
    style: Style = DEFAULT_STYLE
    seed: int = 1
    version: int = 1
    locked: bool = False
    group_ids: tuple[str, ...] = ()  # innermost group first
    frame_id: str | None = None

    @property
    def local_rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)


@dataclass(frozen=True, slots=True, kw_only=True)
class ShapeBase(ElementBase):
    label: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Rectangle(ShapeBase):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Diamond(ShapeBase):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Ellipse(ShapeBase):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Binding:
    element_id: str
    anchor: Point  # (u, v) in the target's normalized box; (0.5, 0.5) aims at the center
    gap: float = 6.0

    @property
    def aims_at_center(self) -> bool:
        return abs(self.anchor.x - 0.5) < 1e-6 and abs(self.anchor.y - 0.5) < 1e-6


@dataclass(frozen=True, slots=True, kw_only=True)
class LinearBase(ElementBase):
    points: tuple[Point, ...] = (Point(0.0, 0.0),)
    label: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Line(LinearBase):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Arrow(LinearBase):
    start_binding: Binding | None = None
    end_binding: Binding | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Freedraw(ElementBase):
    points: tuple[Point, ...] = (Point(0.0, 0.0),)
    pressures: tuple[float, ...] = ()
    simulate_pressure: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class Text(ElementBase):
    text: str = ""
    auto_width: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class Image(ElementBase):
    asset_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Frame(ElementBase):
    name: str = "Frame"


type Element = Rectangle | Diamond | Ellipse | Line | Arrow | Freedraw | Text | Image | Frame
type PointsElement = LinearBase | Freedraw

SHAPES = (Rectangle, Diamond, Ellipse)
LINEAR = (Line, Arrow)
WITH_POINTS = (Line, Arrow, Freedraw)
LABELED = (Rectangle, Diamond, Ellipse, Line, Arrow)
BINDABLE = (Rectangle, Diamond, Ellipse, Text, Image)


def new_id() -> str:
    return secrets.token_hex(6)


def new_seed() -> int:
    return secrets.randbits(31) or 1


def touched[E: ElementBase](element: E, **changes: Any) -> E:
    """A copy with `changes` applied and the version bumped."""
    return replace(element, version=element.version + 1, **changes)


def translated[E: ElementBase](element: E, dx: float, dy: float) -> E:
    return touched(element, x=element.x + dx, y=element.y + dy)


def world_points(element: PointsElement) -> list[Point]:
    return [Point(element.x + p.x, element.y + p.y) for p in element.points]


def with_world_points[P: LinearBase | Freedraw](element: P, points: Sequence[Point]) -> P:
    """A copy whose points are `points` (world coordinates), normalized so the
    first point sits at (x, y)."""
    if not points:
        raise ValueError("a linear element needs at least one point")
    origin = points[0]
    relative = tuple(Point(p.x - origin.x, p.y - origin.y) for p in points)
    box = Rect.from_points(relative)
    return touched(
        element,
        x=origin.x,
        y=origin.y,
        points=relative,
        width=box.width,
        height=box.height,
    )


def to_local(element: ElementBase, p: Point) -> Point:
    """`p` in the element's unrotated frame (still world units)."""
    return p.rotated(element.center, -element.angle) if element.angle else p


def to_world(element: ElementBase, p: Point) -> Point:
    return p.rotated(element.center, element.angle) if element.angle else p


def element_bounds(element: Element) -> Rect:
    """Tight axis-aligned bounds in world coordinates, rotation included."""
    if isinstance(element, WITH_POINTS):
        return Rect.from_points(world_points(element))
    rect = element.local_rect
    if element.angle:
        return Rect.from_points(c.rotated(rect.center, element.angle) for c in rect.corners())
    return rect


def render_bounds(element: Element) -> Rect:
    """Bounds including stroke width, arrowheads and labels, for culling and repaint."""
    bounds = element_bounds(element)
    margin = element.style.stroke_width * 2 + 2
    if isinstance(element, LINEAR):
        margin += 30 + (element.style.font_size * 2 if element.label else 0)
    elif isinstance(element, Freedraw):
        margin += element.style.stroke_width * 4
    elif isinstance(element, Frame):
        margin += 30
    return bounds.inflated(margin)


def outer_group(element: ElementBase) -> str | None:
    return element.group_ids[-1] if element.group_ids else None


def label_of(element: Element) -> str:
    return element.label if isinstance(element, LABELED) else ""
