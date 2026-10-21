"""Which frames are the slides of a note, and in what order."""

from __future__ import annotations

from collections.abc import Sequence

from schemeup.domain.document import Document
from schemeup.domain.elements import Frame
from schemeup.domain.geometry import Point


def slides(document: Document) -> list[Frame]:
    """Frames in reading order: rows from top to bottom, left to right within a row.

    A frame joins the row above when its top edge is within half the height of
    that row's first frame, so slides laid out side by side stay in one row even
    when they were not dragged to exactly the same height."""
    rows: list[list[Frame]] = []
    for frame in sorted(document.frames(), key=lambda f: (f.y, f.x)):
        if rows and frame.y < rows[-1][0].y + rows[-1][0].height / 2:
            rows[-1].append(frame)
        else:
            rows.append([frame])
    return [frame for row in rows for frame in sorted(row, key=lambda f: f.x)]


def slide_near(order: Sequence[Frame], point: Point) -> int:
    """Index of the slide containing `point`, or else the one whose center is closest."""
    if not order:
        raise ValueError("there are no slides")
    for i, frame in enumerate(order):
        if frame.local_rect.contains(point):
            return i

    def distance(i: int) -> float:
        c = order[i].center
        return (c.x - point.x) ** 2 + (c.y - point.y) ** 2

    return min(range(len(order)), key=distance)
