import math
from dataclasses import replace

import pytest

from schemeup.domain import commands
from schemeup.domain.binding import binding_for
from schemeup.domain.commands import AlignEdge, LayerMove, ShapeKind
from schemeup.domain.document import Document
from schemeup.domain.elements import Arrow, Rectangle, Text, element_bounds, world_points
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.style import Style


def rect(x: float, y: float, w: float = 100, h: float = 60) -> Rectangle:
    element = commands.make_shape(ShapeKind.RECTANGLE, Rect(x, y, w, h), Style())
    assert isinstance(element, Rectangle)
    return element


def connected() -> tuple[Document, Rectangle, Rectangle, Arrow]:
    a, b = rect(0, 0), rect(300, 0)
    arrow = commands.make_linear(True, [Point(100, 30), Point(300, 30)], Style())
    assert isinstance(arrow, Arrow)
    arrow = replace(
        arrow,
        start_binding=binding_for(a, Point(100, 30), 8),
        end_binding=binding_for(b, Point(300, 30), 8),
    )
    return Document.of([a, b, arrow]), a, b, arrow


def test_moving_a_shape_drags_its_arrows_along() -> None:
    document, _, b, arrow = connected()
    after = document.with_elements(commands.move(document, [b.id], 0, 100))
    moved_arrow = after.get(arrow.id)
    assert isinstance(moved_arrow, Arrow)
    end = world_points(moved_arrow)[-1]
    assert end.y > 100


def test_moving_an_arrow_alone_unbinds_it() -> None:
    document, _, _, arrow = connected()
    after = document.with_elements(commands.move(document, [arrow.id], 0, 50))
    moved = after.get(arrow.id)
    assert isinstance(moved, Arrow)
    assert moved.start_binding is None and moved.end_binding is None


def test_moving_everything_keeps_bindings() -> None:
    document, a, b, arrow = connected()
    after = document.with_elements(commands.move(document, [a.id, b.id, arrow.id], 10, 10))
    moved = after.get(arrow.id)
    assert isinstance(moved, Arrow)
    assert moved.start_binding is not None and moved.end_binding is not None


def test_deleting_a_target_unbinds_its_arrows() -> None:
    document, a, _, arrow = connected()
    changes = commands.delete(document, [a.id])
    assert changes[a.id] is None
    unbound = changes[arrow.id]
    assert isinstance(unbound, Arrow) and unbound.start_binding is None


def test_duplicate_gets_new_ids_and_keeps_internal_bindings() -> None:
    document, a, b, arrow = connected()
    changes, new_ids = commands.duplicate(document, [a.id, b.id, arrow.id])
    assert len(new_ids) == 3
    assert not set(new_ids) & {a.id, b.id, arrow.id}
    copied_arrow = next(e for e in changes.values() if isinstance(e, Arrow))
    assert copied_arrow.start_binding is not None
    assert copied_arrow.start_binding.element_id in new_ids


def test_duplicate_of_a_group_gets_a_new_group() -> None:
    a, b = rect(0, 0), rect(200, 0)
    document = Document.of([a, b])
    document = document.with_elements(commands.group(document, [a.id, b.id]))
    changes, new_ids = commands.duplicate(document, [a.id, b.id])
    old_group = document.get(a.id).group_ids[-1]  # type: ignore[union-attr]
    new_groups = {changes[i].group_ids[-1] for i in new_ids}  # type: ignore[union-attr]
    assert len(new_groups) == 1
    assert old_group not in new_groups


def test_reorder() -> None:
    a, b, c = rect(0, 0), rect(10, 0), rect(20, 0)
    document = Document.of([a, b, c])
    assert commands.reorder(document, [a.id], LayerMove.FRONT) == (b.id, c.id, a.id)
    assert commands.reorder(document, [c.id], LayerMove.BACK) == (c.id, a.id, b.id)
    assert commands.reorder(document, [a.id], LayerMove.FORWARD) == (b.id, a.id, c.id)
    assert commands.reorder(document, [c.id], LayerMove.BACKWARD) == (a.id, c.id, b.id)


def test_align_left_and_distribute() -> None:
    a, b, c = rect(0, 0), rect(50, 100), rect(400, 200)
    document = Document.of([a, b, c])
    aligned = document.with_elements(commands.align(document, [a.id, b.id, c.id], AlignEdge.LEFT))
    assert {element_bounds(e).left for e in aligned.ordered()} == {0}

    spread = document.with_elements(commands.distribute(document, [a.id, b.id, c.id], True))
    boxes = sorted((element_bounds(e) for e in spread.ordered()), key=lambda r: r.left)
    gaps = [boxes[i + 1].left - boxes[i].right for i in range(2)]
    assert gaps[0] == pytest.approx(gaps[1])


def test_rotate_shapes_and_bake_rotation_into_lines() -> None:
    shape = rect(0, 0, 100, 100)
    line = commands.make_linear(False, [Point(0, 0), Point(100, 0)], Style())
    document = Document.of([shape, line])
    after = document.with_elements(
        commands.rotate(document, [shape.id, line.id], Point(50, 50), math.pi / 2)
    )
    assert after.get(shape.id).angle == pytest.approx(math.pi / 2)  # type: ignore[union-attr]
    rotated_line = after.get(line.id)
    assert rotated_line.angle == 0  # type: ignore[union-attr]
    points = world_points(rotated_line)  # type: ignore[arg-type]
    assert points[0].x == pytest.approx(100) and points[1].y == pytest.approx(100)


def test_scale_maps_elements_into_the_new_box() -> None:
    a = rect(0, 0, 100, 100)
    document = Document.of([a])
    after = document.with_elements(
        commands.scale(document, [a.id], Rect(0, 0, 100, 100), Rect(0, 0, 200, 50))
    )
    assert element_bounds(after.get(a.id)) == Rect(0, 0, 200, 50)  # type: ignore[arg-type]


def test_scaling_text_from_a_corner_scales_the_font() -> None:
    text = Text(id="t", x=0, y=0, width=100, height=20, text="hi", style=Style(font_size=20))
    document = Document.of([text])
    after = document.with_elements(
        commands.scale(document, ["t"], Rect(0, 0, 100, 20), Rect(0, 0, 200, 40))
    )
    assert after.get("t").style.font_size == pytest.approx(40)  # type: ignore[union-attr]


def test_assign_frames_uses_the_center() -> None:
    frame = commands.make_shape(ShapeKind.FRAME, Rect(0, 0, 400, 400), Style())
    inside, outside = rect(50, 50), rect(500, 500)
    document = Document.of([frame, inside, outside])
    changes = commands.assign_frames(document, [inside.id, outside.id])
    assert changes[inside.id].frame_id == frame.id  # type: ignore[union-attr]
    assert outside.id not in changes


def test_moving_a_frame_moves_its_children() -> None:
    frame = commands.make_shape(ShapeKind.FRAME, Rect(0, 0, 400, 400), Style())
    child = rect(50, 50)
    document = Document.of([frame, child])
    document = document.with_elements(commands.assign_frames(document, [child.id]))
    after = document.with_elements(commands.move(document, [frame.id], 100, 0))
    assert after.get(child.id).x == 150  # type: ignore[union-attr]


def test_set_style_and_lock() -> None:
    a = rect(0, 0)
    document = Document.of([a])
    styled = commands.set_style(document, [a.id], stroke_color="#c92a2a")
    assert styled[a.id].style.stroke_color == "#c92a2a"  # type: ignore[union-attr]
    assert commands.set_style(document, [a.id], stroke_color=a.style.stroke_color) == {}
    locked = commands.set_locked(document, [a.id], True)
    assert locked[a.id].locked  # type: ignore[union-attr]
