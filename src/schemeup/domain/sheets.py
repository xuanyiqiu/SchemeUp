"""Sheet types: the paper pattern drawn behind the canvas.

A sheet only describes its lines as data. `visible_lines` turns that into
the concrete lines inside the visible area, so the drawing cost depends on
the window size and never on how far the canvas extends. The same data
gives the snap positions, so snapping always matches what is drawn.
"""

import math
from collections.abc import Callable, Sequence
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
MAGNET_FRACTION = 4.0  # snapping reaches at most 1/4 of the spacing between lines
SINGLE_LINE = 1e9  # spacing for a family that is really one line (a margin)


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
    snaps: bool = True

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


@dataclass(frozen=True, slots=True)
class RuledSheet:
    """Horizontal lines, like a lined notebook, with configurable spacing."""

    spacing_mm: float = 8.0

    def __post_init__(self) -> None:
        if self.spacing_mm <= 0:
            raise ValueError(f"line spacing must be positive, got {self.spacing_mm} mm")

    def line_families(self) -> Sequence[LineFamily]:
        return (LineFamily(Orientation.HORIZONTAL, self.spacing_mm * MM),)


@dataclass(frozen=True, slots=True)
class PatternSheet:
    """Any combination of line families: Seyès, millimetre paper, school rulings."""

    families: tuple[LineFamily, ...]

    def line_families(self) -> Sequence[LineFamily]:
        return self.families


def _h(
    spacing_mm: float, weight: Weight = Weight.MINOR, offset_mm: float = 0.0, lod: int = 1
) -> LineFamily:
    return LineFamily(Orientation.HORIZONTAL, spacing_mm * MM, weight, offset_mm * MM, lod)


def _v(
    spacing_mm: float, weight: Weight = Weight.MINOR, offset_mm: float = 0.0, lod: int = 1
) -> LineFamily:
    return LineFamily(Orientation.VERTICAL, spacing_mm * MM, weight, offset_mm * MM, lod)


def seyes() -> PatternSheet:
    """French Seyès ruling: 8 mm squares with three thin lines every 2 mm and a margin."""
    return PatternSheet(
        (
            _h(2.0),
            _h(8.0, Weight.MAJOR, lod=5),
            _v(8.0, Weight.MAJOR, lod=5),
            LineFamily(Orientation.VERTICAL, SINGLE_LINE, Weight.ACCENT, -32 * MM, 1, snaps=False),
        )
    )


def millimetre() -> PatternSheet:
    return PatternSheet(
        (
            _h(1.0),
            _v(1.0),
            _h(5.0, Weight.MAJOR),
            _v(5.0, Weight.MAJOR),
            _h(10.0, Weight.MAJOR, lod=10),
            _v(10.0, Weight.MAJOR, lod=10),
        )
    )


def montessori(band_mm: float = 5.0) -> PatternSheet:
    """Four-line school ruling: ascender, x-height and descender bands, then a gap."""
    period = band_mm * 4
    return PatternSheet(
        (
            _h(period, offset_mm=0.0),
            _h(period, Weight.MAJOR, offset_mm=band_mm),
            _h(period, Weight.MAJOR, offset_mm=band_mm * 2),
            _h(period, offset_mm=band_mm * 3),
        )
    )


def double_line(gap_mm: float) -> PatternSheet:
    """Pairs of lines `gap_mm` apart (the x-height), with two gaps between pairs."""
    period = gap_mm * 3
    return PatternSheet((_h(period, Weight.MAJOR), _h(period, Weight.MAJOR, offset_mm=gap_mm)))


@dataclass(frozen=True, slots=True)
class SheetPreset:
    id: str
    name: str
    build: Callable[[float], Sheet]  # gets the configurable line spacing in mm


SHEET_PRESETS: tuple[SheetPreset, ...] = (
    SheetPreset("plain", "Plain", lambda _: PlainSheet()),
    SheetPreset("grid-4", "Grid 4 mm", lambda _: GridSheet(4.0)),
    SheetPreset("grid-5", "Grid 5 mm", lambda _: GridSheet(5.0)),
    SheetPreset("grid-6", "Grid 6 mm", lambda _: GridSheet(6.0)),
    SheetPreset("grid-8", "Grid 8 mm", lambda _: GridSheet(8.0)),
    SheetPreset("grid-3", "Grid 3 mm", lambda _: GridSheet(3.0, major_every=4)),
    SheetPreset("lines", "Lines", lambda spacing: RuledSheet(spacing)),
    SheetPreset("seyes", "Seyès", lambda _: seyes()),
    SheetPreset("millimetre", "Millimetre", lambda _: millimetre()),
    SheetPreset("montessori-5", "Montessori 5 mm", lambda _: montessori(5.0)),
    SheetPreset("double-2.5", "Double line 2.5 mm", lambda _: double_line(2.5)),
    SheetPreset("double-3", "Double line 3 mm", lambda _: double_line(3.0)),
    SheetPreset("double-3.5", "Double line 3.5 mm", lambda _: double_line(3.5)),
)
PRESETS_BY_ID = {p.id: p for p in SHEET_PRESETS}


def sheet_for(preset_id: str, line_spacing_mm: float = 8.0) -> Sheet:
    preset = PRESETS_BY_ID.get(preset_id, PRESETS_BY_ID["grid-5"])
    return preset.build(line_spacing_mm)


def fade_opacity(spacing_px: float) -> float:
    """0 at MIN_SPACING_PX, 1 from FULL_SPACING_PX on, linear in between."""
    t = (spacing_px - MIN_SPACING_PX) / (FULL_SPACING_PX - MIN_SPACING_PX)
    return min(max(t, 0.0), 1.0)


def _level_spacing(family: LineFamily, zoom: float) -> float | None:
    """Spacing of the level drawn at `zoom`, or None if the family is hidden."""
    spacing = family.spacing
    if family.lod_factor > 1:
        while spacing * zoom < MIN_SPACING_PX:
            spacing *= family.lod_factor
        return spacing
    return spacing if spacing * zoom >= MIN_SPACING_PX else None


def visible_lines(sheet: Sheet, visible: Rect, zoom: float) -> list[LineGroup]:
    if zoom <= 0:
        raise ValueError(f"zoom must be positive, got {zoom}")
    groups: list[LineGroup] = []
    for family in sheet.line_families():
        groups.extend(_family_lines(family, visible, zoom))
    return groups


def _family_lines(family: LineFamily, visible: Rect, zoom: float) -> list[LineGroup]:
    spacing = _level_spacing(family, zoom)
    if spacing is None:
        return []
    if family.orientation is Orientation.VERTICAL:
        low, high = visible.left, visible.right
    else:
        low, high = visible.top, visible.bottom
    indices = range(
        math.ceil((low - family.offset) / spacing),
        math.floor((high - family.offset) / spacing) + 1,
    )

    opacity = 1.0 if spacing >= SINGLE_LINE else fade_opacity(spacing * zoom)
    if opacity >= 1.0 or family.lod_factor == 1:
        positions = tuple(family.offset + i * spacing for i in indices)
        return [LineGroup(family, positions, opacity)]

    # While a level fades in, the lines it shares with the next coarser level
    # stay solid. That way no line ever pops in or out while zooming.
    k = family.lod_factor
    fading = tuple(family.offset + i * spacing for i in indices if i % k != 0)
    solid = tuple(family.offset + i * spacing for i in indices if i % k == 0)
    return [LineGroup(family, fading, opacity), LineGroup(family, solid, 1.0)]


def snap_to_sheet(
    sheet: Sheet,
    value: float,
    orientation: Orientation,
    zoom: float,
    max_distance: float = math.inf,
) -> float | None:
    """Nearest visible line of `sheet` across `orientation` (x for vertical lines).

    Only lines within `max_distance` count, and never farther than a quarter of the
    line spacing: a magnet that holds near a line, not a quantizer that moves
    everything in whole cells."""
    best: float | None = None
    for family in sheet.line_families():
        if family.orientation is not orientation or not family.snaps:
            continue
        spacing = _level_spacing(family, zoom)
        if spacing is None or spacing >= SINGLE_LINE:
            continue
        candidate = family.offset + round((value - family.offset) / spacing) * spacing
        if abs(candidate - value) > min(max_distance, spacing / MAGNET_FRACTION):
            continue
        if best is None or abs(candidate - value) < abs(best - value):
            best = candidate
    return best
