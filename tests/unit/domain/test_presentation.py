from dataclasses import replace

import pytest

from schemeup.domain import commands
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import Frame
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.presentation import slide_near, slides
from schemeup.domain.style import Style


def frame(name: str, x: float, y: float, w: float = 400, h: float = 300) -> Frame:
    element = commands.make_shape(ShapeKind.FRAME, Rect(x, y, w, h), Style())
    assert isinstance(element, Frame)
    return replace(element, name=name)


def names(order: list[Frame]) -> list[str]:
    return [f.name for f in order]


def test_no_frames_means_no_slides() -> None:
    assert slides(Document()) == []


def test_slides_run_left_to_right_then_top_to_bottom() -> None:
    document = Document.of(
        [
            frame("d", 0, 500),
            frame("b", 500, 0),
            frame("c", 1000, 0),
            frame("a", 0, 0),
            frame("e", 500, 500),
        ]
    )
    assert names(slides(document)) == ["a", "b", "c", "d", "e"]


def test_frames_that_are_roughly_level_share_a_row() -> None:
    # "right" sits 40 units lower than "left" but is still the next slide, not a new row.
    document = Document.of([frame("right", 500, 40), frame("left", 0, 0), frame("below", 0, 400)])
    assert names(slides(document)) == ["left", "right", "below"]


def test_slide_near_prefers_the_frame_under_the_point() -> None:
    order = slides(Document.of([frame("a", 0, 0), frame("b", 600, 0)]))
    assert slide_near(order, Point(650, 100)) == 1
    assert slide_near(order, Point(10, 10)) == 0


def test_slide_near_falls_back_to_the_closest_center() -> None:
    order = slides(Document.of([frame("a", 0, 0), frame("b", 600, 0)]))
    assert slide_near(order, Point(560, 900)) == 1
    with pytest.raises(ValueError):
        slide_near([], Point(0, 0))
