"""Rough rendering, freehand strokes, hit testing, the spatial index and binding."""

from dataclasses import replace

import pytest

from schemeup.domain import commands
from schemeup.domain.binding import CENTER, binding_for, bound_endpoint, find_target, outline_point
from schemeup.domain.commands import ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import Rectangle
from schemeup.domain.freehand import stroke_outline
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.hit import hit_test, ids_in_rect, is_inside, outline_distance, topmost_at
from schemeup.domain.rough import Random, RoughGenerator, hachure_lines
from schemeup.domain.shapes import PartKind, element_parts
from schemeup.domain.spatial import SpatialHash
from schemeup.domain.style import FillStyle, Style


def shape(kind: ShapeKind, rect: Rect, **style: object) -> Rectangle:
    return commands.make_shape(kind, rect, Style(**style))  # type: ignore[arg-type,return-value]


def test_random_matches_rough_js_sequence() -> None:
    # First values of rough.js' Random(1): ((2**31 - 1) & imul(48271, seed)) / 2**31
    r = Random(1)
    assert r.next() == pytest.approx(48271 / 2**31)
    assert r.next() == pytest.approx(((48271 * 48271) & 0x7FFFFFFF) / 2**31)


def test_same_seed_gives_identical_geometry() -> None:
    a = shape(ShapeKind.RECTANGLE, Rect(0, 0, 200, 100), fill_color="#a5d8ff")
    assert element_parts(a) == element_parts(replace(a, x=500))
    assert element_parts(a) != element_parts(replace(a, seed=a.seed + 1))


def test_clean_mode_draws_exact_lines() -> None:
    gen = RoughGenerator(seed=7, roughness=0)
    ops = gen.line(Point(0, 0), Point(100, 0))
    assert len(ops) == 2  # one stroke, no second pass
    assert ops[-1].y == 0


def test_fill_styles_produce_the_right_parts() -> None:
    rect = Rect(0, 0, 200, 100)
    hachure = element_parts(shape(ShapeKind.RECTANGLE, rect, fill_color="#ffc9c9"))
    solid = element_parts(
        shape(ShapeKind.ELLIPSE, rect, fill_color="#ffc9c9", fill_style=FillStyle.SOLID)
    )
    empty = element_parts(shape(ShapeKind.DIAMOND, rect))
    assert [p.kind for p in hachure] == [PartKind.FILL_LINES, PartKind.STROKE]
    assert [p.kind for p in solid] == [PartKind.FILL_AREA, PartKind.STROKE]
    assert [p.kind for p in empty] == [PartKind.STROKE]


def test_hachure_lines_stay_inside_the_polygon() -> None:
    square = [Point(0, 0), Point(100, 0), Point(100, 100), Point(0, 100)]
    lines = hachure_lines(square, 10, -41)
    assert len(lines) > 5
    for a, b in lines:
        for p in (a, b):
            assert -1e-6 <= p.x <= 100 + 1e-6 and -1e-6 <= p.y <= 100 + 1e-6


def test_freehand_outline_surrounds_the_stroke() -> None:
    points = [Point(x, 0) for x in range(0, 200, 5)]
    outline = stroke_outline(points)
    assert len(outline) > 10
    ys = [p.y for p in outline]
    assert min(ys) < 0 < max(ys)
    assert stroke_outline([Point(5, 5)])  # a single click still makes a dot


def test_hit_testing() -> None:
    empty = shape(ShapeKind.RECTANGLE, Rect(0, 0, 100, 100))
    filled = shape(ShapeKind.ELLIPSE, Rect(0, 0, 100, 100), fill_color="#b2f2bb")
    assert hit_test(empty, Point(2, 50), 4)
    assert not hit_test(empty, Point(50, 50), 4)
    assert hit_test(filled, Point(50, 50), 4)
    assert is_inside(filled, Point(50, 50)) and not is_inside(filled, Point(2, 2))
    assert outline_distance(empty, Point(150, 50)) == pytest.approx(50)


def test_topmost_and_rubber_band_selection() -> None:
    low = shape(ShapeKind.RECTANGLE, Rect(0, 0, 100, 100), fill_color="#fff")
    high = shape(ShapeKind.RECTANGLE, Rect(50, 50, 100, 100), fill_color="#fff")
    document = Document.of([low, high])
    assert topmost_at(document, Point(75, 75), 2) == high
    assert ids_in_rect(document, Rect(-10, -10, 130, 130)) == [low.id]


def test_spatial_hash_finds_and_forgets() -> None:
    index = SpatialHash(cell_size=100)
    near = shape(ShapeKind.RECTANGLE, Rect(0, 0, 50, 50))
    far = shape(ShapeKind.RECTANGLE, Rect(5000, 5000, 50, 50))
    huge = shape(ShapeKind.RECTANGLE, Rect(-50000, -50000, 100000, 100000))
    document = Document.of([near, far, huge])
    index.sync(document)
    found = index.query(Rect(0, 0, 10, 10))
    assert near.id in found and huge.id in found and far.id not in found
    index.sync(document.with_elements({near.id: None}))
    assert near.id not in index.query(Rect(0, 0, 10, 10))


def test_binding_anchors_and_endpoints() -> None:
    target = shape(ShapeKind.RECTANGLE, Rect(0, 0, 100, 100))
    side = binding_for(target, Point(101, 50), 8)
    assert side.anchor == Point(1.0, 0.5)
    deep = binding_for(target, Point(40, 40), 8)
    assert deep.anchor == CENTER
    end = bound_endpoint(target, deep, Point(300, 50))
    assert end.x == pytest.approx(100 + deep.gap)
    assert outline_point(target, Point(50, -500)) == Point(50, 0)
    document = Document.of([target])
    assert find_target(document, Point(104, 50), 8) == target
    assert find_target(document, Point(150, 50), 8) is None
