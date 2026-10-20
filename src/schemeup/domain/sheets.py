"""Sheet types: the paper pattern drawn behind the canvas.

A sheet only describes its lines as data. `visible_lines` turns that into
the concrete lines inside the visible area, so the drawing cost depends on
the window size and never on how far the canvas extends.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from schemeup.domain.geometry import Rect

# Canvas units per millimetre. A unit is a CSS reference pixel (1/96 inch),
# so a 210 mm wide page prints exactly as A4.
MM = 96 / 25.4

# Below MIN_SPACING_PX on screen a level of lines is not drawn; it fades in
# until FULL_SPACING_PX, where it becomes fully opaque.
MIN_SPACING_PX = 6.0
FULL_SPACING_PX = 12.0


class Orientation(Enum):
    VERTICAL = "vertical"  # lines at constant x
    HORIZONTAL = "horizontal"  # lines at constant y


class Weight(Enum):
    MINOR = "minor"
    MAJOR = "major"
    ACCENT = "accent"


@dataclass(frozen=True, slots=True)
class LineFamily:
    """Evenly spaced parallel lines.

    When the lines get too dense on screen, only every `lod_factor`-th line is
    kept (repeatedly if needed). Zoomed far out, a 5 mm grid turns into a 25 mm
    grid instead of a grey blur. With `lod_factor` 1 the family just disappears.
    """

    orientation: Orientation
    spacing: float  # canvas units
    weight: Weight = Weight.MINOR
    offset: float = 0.0
    lod_factor: int = 5

    def __post_init__(self) -> None:
        if self.spacing <= 0:
            raise ValueError(f"line spacing must be positive, got {self.spacing}")
        if self.lod_factor < 1:
            raise ValueError(f"lod_factor must be at least 1, got {self.lod_factor}")


@dataclass(frozen=True, slots=True)
class LineGroup:
    """Lines of one family that share the same opacity."""

    family: LineFamily
    positions: tuple[float, ...]  # x for vertical lines, y for horizontal ones
    opacity: float


class Sheet(Protocol):
    def line_families(self) -> Sequence[LineFamily]: ...


@dataclass(frozen=True, slots=True)
class PlainSheet:
    def line_families(self) -> Sequence[LineFamily]:
        return ()


@dataclass(frozen=True, slots=True)
class GridSheet:
    """Square grid paper, like a 5 mm squared notebook."""

    cell_mm: float = 5.0
    major_every: int = 0  # 0 means no heavier lines

    def __post_init__(self) -> None:
        if self.cell_mm <= 0:
            raise ValueError(f"cell size must be positive, got {self.cell_mm} mm")

    def line_families(self) -> Sequence[LineFamily]:
        spacing = self.cell_mm * MM
        families = [
            LineFamily(Orientation.VERTICAL, spacing),
            LineFamily(Orientation.HORIZONTAL, spacing),
        ]
        if self.major_every > 1:
            major = spacing * self.major_every
            families += [
                LineFamily(Orientation.VERTICAL, major, Weight.MAJOR),
                LineFamily(Orientation.HORIZONTAL, major, Weight.MAJOR),
            ]
        return tuple(families)


def fade_opacity(spacing_px: float) -> float:
    """0 at MIN_SPACING_PX, 1 from FULL_SPACING_PX on, linear in between."""
    t = (spacing_px - MIN_SPACING_PX) / (FULL_SPACING_PX - MIN_SPACING_PX)
    return min(max(t, 0.0), 1.0)


def visible_lines(sheet: Sheet, visible: Rect, zoom: float) -> list[LineGroup]:
    if zoom <= 0:
        raise ValueError(f"zoom must be positive, got {zoom}")
    groups: list[LineGroup] = []
    for family in sheet.line_families():
        groups.extend(_family_lines(family, visible, zoom))
    return groups


def _family_lines(family: LineFamily, visible: Rect, zoom: float) -> list[LineGroup]:
    spacing = family.spacing
    if family.lod_factor > 1:
        while spacing * zoom < MIN_SPACING_PX:
            spacing *= family.lod_factor
    elif spacing * zoom < MIN_SPACING_PX:
        return []

    if family.orientation is Orientation.VERTICAL:
        low, high = visible.left, visible.right
    else:
        low, high = visible.top, visible.bottom
    indices = range(
        math.ceil((low - family.offset) / spacing),
        math.floor((high - family.offset) / spacing) + 1,
    )

    opacity = fade_opacity(spacing * zoom)
    if opacity >= 1.0 or family.lod_factor == 1:
        positions = tuple(family.offset + i * spacing for i in indices)
        return [LineGroup(family, positions, opacity)]

    # While a level fades in, the lines it shares with the next coarser level
    # stay solid. That way no line ever pops in or out while zooming.
    k = family.lod_factor
    fading = tuple(family.offset + i * spacing for i in indices if i % k != 0)
    solid = tuple(family.offset + i * spacing for i in indices if i % k == 0)
    return [LineGroup(family, fading, opacity), LineGroup(family, solid, 1.0)]
