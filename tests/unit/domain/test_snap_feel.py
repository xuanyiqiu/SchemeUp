"""How snapping feels: a limited-radius magnet that holds, instead of a quantizer."""

import pytest

from schemeup.domain.geometry import Point
from schemeup.domain.sheets import MM, GridSheet
from schemeup.domain.snapping import SheetSnap, SnapHold, snap_point

CELL = 5 * MM  # a 5 mm cell, about 18.9 canvas units


def test_the_grid_only_catches_near_a_line() -> None:
    sheet = SheetSnap(GridSheet(5.0), zoom=1.0)
    near = snap_point(Point(CELL + 3, 0.5), None, sheet, threshold=5)
    far = snap_point(Point(CELL + CELL / 2, 0.5), None, sheet, threshold=5)
    assert near.offset.x == pytest.approx(-3)
    assert far.offset.x == 0.0  # mid-cell: nothing pulls the shape


def test_the_reach_is_capped_at_a_quarter_of_a_cell() -> None:
    sheet = SheetSnap(GridSheet(5.0), zoom=1.0)
    # A huge threshold (the view zoomed far out) must not turn the grid into a quantizer.
    result = snap_point(Point(CELL + CELL / 3, 0.0), None, sheet, threshold=100)
    assert result.offset.x == 0.0


def test_a_held_snap_survives_small_wobbles_and_lets_go_when_far() -> None:
    hold = SnapHold()
    release = 8.0
    # The pointer reaches x = 98 and snapping would add 2 to land on the line at 100.
    assert hold.apply(Point(98, 0), Point(2, 0), release).x == 100
    # Wobbling around the line keeps it there, even where snapping alone would not catch.
    assert hold.apply(Point(104, 0), Point(0, 0), release).x == 100
    assert hold.apply(Point(94, 0), Point(0, 0), release).x == 100
    # Past the release distance the shape follows the pointer again.
    assert hold.apply(Point(110, 0), Point(0, 0), release).x == 110
    assert hold.apply(Point(111, 0), Point(0, 0), release).x == 111


def test_axes_are_held_independently() -> None:
    hold = SnapHold()
    first = hold.apply(Point(98, 40), Point(2, 0), release=8)
    assert (first.x, first.y) == (100, 40)
    second = hold.apply(Point(105, 52), Point(0, 0), release=8)
    assert (second.x, second.y) == (100, 52)


def test_reset_forgets_the_hold() -> None:
    hold = SnapHold()
    hold.apply(Point(98, 0), Point(2, 0), release=8)
    hold.reset()
    assert hold.apply(Point(104, 0), Point(0, 0), release=8).x == 104
