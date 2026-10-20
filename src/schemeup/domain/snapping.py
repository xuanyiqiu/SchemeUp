"""Smart snapping: alignment with other elements, equal spacing and the sheet.

Each axis is resolved on its own. Object snaps (edges, centers, equal gaps)
win over the sheet whenever one is within the threshold: on a grid there is
always a line in reach, so letting the grid win would hide every alignment.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field

from schemeup.domain.geometry import Point, Rect
from schemeup.domain.sheets import Orientation, Sheet, snap_to_sheet

SNAP_DISTANCE_PX = 8.0


@dataclass(frozen=True, slots=True)
class Guide:
    start: Point
    end: Point
    marks: tuple[Point, ...] = ()
    spacing: bool = False  # an equal-gap guide rather than an alignment line


@dataclass(frozen=True, slots=True)
class SnapResult:
    offset: Point
    guides: tuple[Guide, ...] = ()


@dataclass(frozen=True, slots=True)
class SheetSnap:
    sheet: Sheet
    zoom: float


@dataclass(slots=True)
class _Candidate:
    offset: float
    guides: list[Guide] = field(default_factory=list)


class SnapTargets:
    """Edges and centers of the elements one can snap to, sorted for binary search.

    Built once when a gesture starts, then queried on every mouse move."""

    def __init__(self, rects: Sequence[Rect]) -> None:
        self.rects = list(rects)
        xs: list[tuple[float, int]] = []
        ys: list[tuple[float, int]] = []
        for i, r in enumerate(self.rects):
            xs += [(r.left, i), (r.center.x, i), (r.right, i)]
            ys += [(r.top, i), (r.center.y, i), (r.bottom, i)]
        xs.sort()
        ys.sort()
        self._xs = xs
        self._ys = ys
        self._x_values = [v for v, _ in xs]
        self._y_values = [v for v, _ in ys]

    def near(self, value: float, threshold: float, horizontal: bool) -> list[tuple[float, int]]:
        values = self._x_values if horizontal else self._y_values
        items = self._xs if horizontal else self._ys
        lo = bisect.bisect_left(values, value - threshold)
        hi = bisect.bisect_right(values, value + threshold)
        return items[lo:hi]


def _probes(rect: Rect, horizontal: bool) -> list[float]:
    if horizontal:
        return [rect.left, rect.center.x, rect.right]
    return [rect.top, rect.center.y, rect.bottom]


def _align_candidates(
    rect: Rect, probes: list[float], targets: SnapTargets, threshold: float, horizontal: bool
) -> list[_Candidate]:
    result: list[_Candidate] = []
    for probe in probes:
        for value, index in targets.near(probe, threshold, horizontal):
            other = targets.rects[index]
            offset = value - probe
            if horizontal:
                top = min(rect.top, other.top)
                bottom = max(rect.bottom, other.bottom)
                guide = Guide(
                    Point(value, top), Point(value, bottom), (Point(value, other.center.y),)
                )
            else:
                left = min(rect.left, other.left)
                right = max(rect.right, other.right)
                guide = Guide(
                    Point(left, value), Point(right, value), (Point(other.center.x, value),)
                )
            result.append(_Candidate(offset, [guide]))
    return result


def _spacing_candidates(
    rect: Rect, targets: SnapTargets, threshold: float, horizontal: bool
) -> list[_Candidate]:
    """Equal-gap candidates with the neighbours on the same row (or column)."""

    def overlaps(r: Rect) -> bool:
        if horizontal:
            return r.bottom > rect.top and r.top < rect.bottom
        return r.right > rect.left and r.left < rect.right

    def lo(r: Rect) -> float:
        return r.left if horizontal else r.top

    def hi(r: Rect) -> float:
        return r.right if horizontal else r.bottom

    size = rect.width if horizontal else rect.height
    row = [r for r in targets.rects if overlaps(r)]
    before = sorted((r for r in row if hi(r) <= lo(rect) + threshold), key=hi, reverse=True)
    after = sorted((r for r in row if lo(r) >= hi(rect) - threshold), key=lo)
    result: list[_Candidate] = []

    def gap_guide(a: float, b: float, cross: float) -> Guide:
        if horizontal:
            return Guide(Point(a, cross), Point(b, cross), spacing=True)
        return Guide(Point(cross, a), Point(cross, b), spacing=True)

    def cross_of(*rs: Rect) -> float:
        if horizontal:
            return (max(r.top for r in rs) + min(r.bottom for r in rs)) / 2
        return (max(r.left for r in rs) + min(r.right for r in rs)) / 2

    if before and after:
        a, b = before[0], after[0]
        free = lo(b) - hi(a)
        if free >= size:
            start = hi(a) + (free - size) / 2
            offset = start - lo(rect)
            cross = cross_of(a, b, rect)
            result.append(
                _Candidate(
                    offset,
                    [gap_guide(hi(a), start, cross), gap_guide(start + size, lo(b), cross)],
                )
            )
    if len(before) >= 2:
        a, a2 = before[0], before[1]
        gap = lo(a) - hi(a2)
        if gap > 0:
            start = hi(a) + gap
            cross = cross_of(a, a2, rect)
            result.append(
                _Candidate(
                    start - lo(rect),
                    [gap_guide(hi(a2), lo(a), cross), gap_guide(hi(a), start, cross)],
                )
            )
    if len(after) >= 2:
        b, b2 = after[0], after[1]
        gap = lo(b2) - hi(b)
        if gap > 0:
            start = lo(b) - gap - size
            cross = cross_of(b, b2, rect)
            result.append(
                _Candidate(
                    start - lo(rect),
                    [gap_guide(hi(b), lo(b2), cross), gap_guide(start + size, lo(b), cross)],
                )
            )
    return [c for c in result if abs(c.offset) <= threshold]


def _resolve(candidates: list[_Candidate], threshold: float) -> tuple[float | None, list[Guide]]:
    within = [c for c in candidates if abs(c.offset) <= threshold]
    if not within:
        return None, []
    best = min(within, key=lambda c: abs(c.offset))
    guides = [g for c in within if abs(c.offset - best.offset) < 1e-6 for g in c.guides]
    return best.offset, guides


def snap_rect(
    rect: Rect,
    targets: SnapTargets | None,
    sheet: SheetSnap | None,
    threshold: float,
    *,
    spacing: bool = True,
) -> SnapResult:
    """Offset that snaps a moving rect, plus the guides to show."""
    offsets: list[float] = []
    guides: list[Guide] = []
    for horizontal in (True, False):
        offset: float | None = None
        axis_guides: list[Guide] = []
        if targets is not None:
            candidates = _align_candidates(
                rect, _probes(rect, horizontal), targets, threshold, horizontal
            )
            if spacing:
                candidates += _spacing_candidates(rect, targets, threshold, horizontal)
            offset, axis_guides = _resolve(candidates, threshold)
        if offset is None and sheet is not None:
            edge = rect.left if horizontal else rect.top
            orientation = Orientation.VERTICAL if horizontal else Orientation.HORIZONTAL
            line = snap_to_sheet(sheet.sheet, edge, orientation, sheet.zoom)
            if line is not None:
                offset = line - edge
        offsets.append(offset or 0.0)
        guides += axis_guides
    return SnapResult(Point(offsets[0], offsets[1]), tuple(guides))


def snap_point(
    p: Point,
    targets: SnapTargets | None,
    sheet: SheetSnap | None,
    threshold: float,
) -> SnapResult:
    """Snap a single point (drawing a shape, dragging a resize handle)."""
    return snap_rect(Rect(p.x, p.y, 0, 0), targets, sheet, threshold, spacing=False)
