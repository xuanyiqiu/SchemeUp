"""Snapping rules, text fitting and the documented palette contrast."""

from dataclasses import replace

import pytest

from schemeup.domain import commands
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import Ellipse, Rectangle, Text
from schemeup.domain.geometry import Point, Rect, Size
from schemeup.domain.palette import (
    FILL_SWATCHES,
    STROKE_SWATCHES,
    contrast_ratio,
    dark_variant,
)
from schemeup.domain.sheets import MM, GridSheet, RuledSheet, sheet_for
from schemeup.domain.snapping import SheetSnap, SnapTargets, snap_point, snap_rect
from schemeup.domain.style import TRANSPARENT, Style, TextAlign, VerticalAlign
from schemeup.domain.text import fit_label, fit_text, label_area, place_block
from tests.unit.domain.conftest import FakeMeasurer


def test_aligns_with_a_nearby_edge_and_draws_a_guide() -> None:
    targets = SnapTargets([Rect(0, 0, 100, 100)])
    result = snap_rect(Rect(204, 0, 50, 50), targets, None, threshold=8)
    assert result.offset.x == 0  # nothing within reach on x
    result = snap_rect(Rect(103, 300, 50, 50), targets, None, threshold=8)
    assert result.offset.x == pytest.approx(-3)  # left edge onto the right edge
    assert result.guides


def test_object_snap_wins_over_the_grid() -> None:
    sheet = SheetSnap(GridSheet(5.0), zoom=1.0)
    targets = SnapTargets([Rect(0, 0, 103, 100)])
    result = snap_rect(Rect(107, 300, 40, 40), targets, sheet, threshold=8)
    assert result.offset.x == pytest.approx(-4)  # to the shape edge at 103, not a grid line


def test_grid_applies_when_no_object_is_near() -> None:
    sheet = SheetSnap(GridSheet(5.0), zoom=1.0)
    result = snap_point(Point(5 * MM + 2, 7), None, sheet, threshold=8)
    assert result.offset.x == pytest.approx(-2)
    assert not result.guides


def test_lined_paper_only_snaps_vertically() -> None:
    sheet = SheetSnap(RuledSheet(8.0), zoom=1.0)
    result = snap_point(Point(13, 8 * MM + 3), None, sheet, threshold=8)
    assert result.offset.x == 0.0
    assert result.offset.y == pytest.approx(-3)


def test_equal_spacing_between_neighbours() -> None:
    targets = SnapTargets([Rect(0, 0, 100, 100), Rect(300, 0, 100, 100)])
    # A 100-wide box fits exactly in the middle at x=150.
    result = snap_rect(Rect(146, 20, 100, 60), targets, None, threshold=8)
    assert result.offset.x == pytest.approx(4)
    assert any(g.spacing for g in result.guides)


def test_every_sheet_preset_builds() -> None:
    for preset in ("plain", "grid-5", "lines", "seyes", "millimetre", "montessori-5", "double-3"):
        sheet_for(preset, 8.0).line_families()
    assert sheet_for("does-not-exist").line_families() == GridSheet(5.0).line_families()


def test_fit_text_grows_with_content(measurer: FakeMeasurer) -> None:
    text = Text(id="t", x=0, y=0, text="hello", style=Style())
    fitted = fit_text(text, measurer)
    assert (fitted.width, fitted.height) == (50, 20)
    wrapped = fit_text(
        Text(id="w", x=0, y=0, width=30, auto_width=False, text="abcdefgh", style=Style()), measurer
    )
    assert wrapped.height == 60


def test_shapes_grow_to_fit_their_label(measurer: FakeMeasurer) -> None:
    box = commands.make_shape(ShapeKind.RECTANGLE, Rect(0, 0, 120, 40), Style())
    assert isinstance(box, Rectangle)
    labelled = fit_label(replace(box, label="a very long label indeed"), measurer)
    assert labelled.height > 40


def test_label_position_follows_the_text_position() -> None:
    shape = Ellipse(id="e", x=0, y=0, width=200, height=200)
    area = label_area(shape)
    assert area.width < 200  # inscribed box of the ellipse
    top_left = place_block(
        area, Size(20, 10), Style(text_align=TextAlign.LEFT, vertical_align=VerticalAlign.TOP)
    )
    assert (top_left.x, top_left.y) == (area.x, area.y)
    centered = place_block(area, Size(20, 10), Style())
    assert centered.center == area.center


def test_documented_stroke_contrast_on_both_canvases() -> None:
    white, dark = "#ffffff", dark_variant("#ffffff")
    assert dark == "#121212"
    for swatch in STROKE_SWATCHES:
        assert contrast_ratio(swatch.color, white) >= 3.0
        assert contrast_ratio(dark_variant(swatch.color), dark) >= 3.0


def test_pastels_are_too_faint_for_strokes() -> None:
    pastels = [s.color for s in FILL_SWATCHES if s.color != TRANSPARENT]
    assert all(contrast_ratio(c, "#ffffff") < 2.0 for c in pastels)
    assert all(contrast_ratio("#1e1e1e", c) > 10 for c in pastels)


def test_plain_text_reads_top_to_bottom() -> None:
    a = commands.make_text(Point(0, 100), "second", Style())
    b = commands.make_text(Point(0, 0), "first", Style())
    assert Document.of([a, b]).plain_text() == "first\nsecond"
