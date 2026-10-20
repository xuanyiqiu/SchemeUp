import itertools
import math

import pytest

from schemeup.domain.camera import MAX_ZOOM, MIN_ZOOM
from schemeup.domain.geometry import Rect
from schemeup.domain.sheets import (
    MIN_SPACING_PX,
    MM,
    GridSheet,
    LineFamily,
    Orientation,
    PlainSheet,
    Weight,
    fade_opacity,
    visible_lines,
)

VISIBLE = Rect(-123.4, 56.7, 800, 600)


def lines_by_orientation(sheet: GridSheet, zoom: float) -> dict[Orientation, list[float]]:
    visible = Rect(VISIBLE.x, VISIBLE.y, VISIBLE.width / zoom, VISIBLE.height / zoom)
    result: dict[Orientation, list[float]] = {o: [] for o in Orientation}
    for group in visible_lines(sheet, visible, zoom):
        result[group.family.orientation].extend(group.positions)
    return result


def test_plain_sheet_has_no_lines() -> None:
    assert visible_lines(PlainSheet(), VISIBLE, 1.0) == []


def test_grid_cell_is_measured_in_millimetres() -> None:
    families = GridSheet(cell_mm=5).line_families()
    assert all(f.spacing == pytest.approx(5 * MM) for f in families)


def test_grid_lines_stay_inside_the_visible_area_and_are_evenly_spaced() -> None:
    groups = visible_lines(GridSheet(cell_mm=5), VISIBLE, 1.0)
    assert len(groups) == 2
    for group in groups:
        low, high = (
            (VISIBLE.left, VISIBLE.right)
            if group.family.orientation is Orientation.VERTICAL
            else (VISIBLE.top, VISIBLE.bottom)
        )
        assert all(low <= p <= high for p in group.positions)
        gaps = {round(b - a, 6) for a, b in itertools.pairwise(group.positions)}
        assert gaps == {round(5 * MM, 6)}
        assert group.opacity == 1.0


def test_lines_are_anchored_to_the_world_origin() -> None:
    for group in visible_lines(GridSheet(cell_mm=4), VISIBLE, 1.0):
        for p in group.positions:
            assert p / (4 * MM) == pytest.approx(round(p / (4 * MM)))


@pytest.mark.parametrize("zoom", [MIN_ZOOM, 0.15, 0.2, 0.3, 0.5, 1.0])
def test_lines_never_get_denser_than_the_minimum_spacing(zoom: float) -> None:
    for positions in lines_by_orientation(GridSheet(cell_mm=5), zoom).values():
        ordered = sorted(positions)
        gaps = [b - a for a, b in itertools.pairwise(ordered)]
        assert min(gaps) * zoom >= MIN_SPACING_PX - 1e-9


@pytest.mark.parametrize("zoom", [MIN_ZOOM, MAX_ZOOM])
def test_line_count_is_bounded_at_extreme_zoom(zoom: float) -> None:
    for orientation, positions in lines_by_orientation(GridSheet(cell_mm=5), zoom).items():
        extent = VISIBLE.width if orientation is Orientation.VERTICAL else VISIBLE.height
        assert len(positions) <= math.ceil(extent / MIN_SPACING_PX) + 1


def test_zooming_out_keeps_a_coarser_grid_visible() -> None:
    groups = visible_lines(GridSheet(cell_mm=5), Rect(0, 0, 8000, 6000), 0.1)
    assert groups
    assert max(g.opacity for g in groups) == 1.0


def test_fading_level_keeps_shared_lines_solid() -> None:
    # 5 mm at 45% zoom is about 8.5 px on screen: inside the fade band.
    groups = visible_lines(GridSheet(cell_mm=5), Rect(0, 0, 2000, 2000), 0.45)
    vertical = [g for g in groups if g.family.orientation is Orientation.VERTICAL]
    assert sorted(g.opacity for g in vertical)[-1] == 1.0
    assert 0.0 < sorted(g.opacity for g in vertical)[0] < 1.0


def test_fade_is_monotonic() -> None:
    samples = [fade_opacity(px / 10) for px in range(0, 200)]
    assert samples == sorted(samples)
    assert samples[0] == 0.0 and samples[-1] == 1.0


def test_major_lines_are_an_extra_family() -> None:
    weights = [f.weight for f in GridSheet(cell_mm=5, major_every=5).line_families()]
    assert weights.count(Weight.MAJOR) == 2


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        GridSheet(cell_mm=0)
    with pytest.raises(ValueError):
        LineFamily(Orientation.VERTICAL, spacing=-1)
    with pytest.raises(ValueError):
        visible_lines(GridSheet(), VISIBLE, 0)
