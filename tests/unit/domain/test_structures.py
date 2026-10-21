import pytest

from schemeup.domain.binding import bound_endpoint
from schemeup.domain.document import Document
from schemeup.domain.elements import (
    Arrow,
    Element,
    Ellipse,
    Rectangle,
    Text,
    element_bounds,
    world_points,
)
from schemeup.domain.geometry import Point
from schemeup.domain.structures import (
    MAX_ITEMS,
    StructureError,
    StructureKind,
    build,
    recentered,
)
from schemeup.domain.style import Arrowhead, Style

BASE = Style()


def made(kind: StructureKind, text: str) -> list[Element]:
    return build(kind, text, BASE)


def labelled(elements: list[Element]) -> dict[str, Rectangle | Ellipse]:
    return {e.label: e for e in elements if isinstance(e, Rectangle | Ellipse) and e.label}


def arrows(elements: list[Element]) -> list[Arrow]:
    return [e for e in elements if isinstance(e, Arrow)]


def captions(elements: list[Element]) -> list[str]:
    return [e.text for e in elements if isinstance(e, Text)]


def test_everything_in_a_structure_moves_together() -> None:
    elements = made(StructureKind.LINKED_LIST, "1, 2, 3")
    groups = {e.group_ids for e in elements}
    assert len(groups) == 1 and len(next(iter(groups))) == 1


def test_an_array_is_a_row_of_cells_with_their_indices() -> None:
    elements = made(StructureKind.ARRAY, "3, 1, 4")
    cells = [e for e in elements if isinstance(e, Rectangle)]
    assert [c.label for c in cells] == ["3", "1", "4"]
    assert cells[1].x == pytest.approx(cells[0].x + cells[0].width)  # cells touch
    assert len({c.y for c in cells}) == 1
    assert captions(elements) == ["0", "1", "2"]


def test_wide_values_widen_every_cell_equally() -> None:
    narrow = [e for e in made(StructureKind.ARRAY, "1, 2") if isinstance(e, Rectangle)]
    wide = [e for e in made(StructureKind.ARRAY, "1, hello") if isinstance(e, Rectangle)]
    assert wide[0].width > narrow[0].width
    assert wide[0].width == wide[1].width


def test_a_matrix_has_rows_columns_and_pads_short_rows() -> None:
    elements = made(StructureKind.MATRIX, "1 2 3; 4 5")
    cells = [e for e in elements if isinstance(e, Rectangle)]
    assert len(cells) == 6
    assert sorted(c.label for c in cells) == ["", "1", "2", "3", "4", "5"]
    assert captions(elements) == ["0", "1", "0", "1", "2"]  # the rows, then the columns


def test_a_linked_list_chains_its_nodes_to_null() -> None:
    elements = made(StructureKind.LINKED_LIST, "1 -> 2 -> 3")
    nodes = labelled(elements)
    assert set(nodes) == {"1", "2", "3", "null"}
    ends = [
        (a.start_binding.element_id, a.end_binding.element_id)
        for a in arrows(elements)
        if a.start_binding and a.end_binding
    ]
    assert ends == [
        (nodes["1"].id, nodes["2"].id),
        (nodes["2"].id, nodes["3"].id),
        (nodes["3"].id, nodes["null"].id),
    ]
    assert "head" in captions(elements)


def test_a_doubly_linked_list_points_both_ways_and_ends_in_null_twice() -> None:
    elements = made(StructureKind.DOUBLY_LINKED_LIST, "1, 2")
    links = arrows(elements)
    assert len(links) == 3
    assert all(
        a.style.start_head == Arrowhead.ARROW and a.style.end_head == Arrowhead.ARROW for a in links
    )
    nulls = [e for e in elements if isinstance(e, Rectangle) and e.label == "null"]
    assert len(nulls) == 2


def test_arrows_start_and_end_on_the_shapes_they_are_bound_to() -> None:
    elements = made(StructureKind.LINKED_LIST, "a, b")
    document = Document.of(elements)
    for arrow in arrows(elements):
        assert arrow.start_binding is not None and arrow.end_binding is not None
        source = document.get(arrow.start_binding.element_id)
        target = document.get(arrow.end_binding.element_id)
        assert source is not None and target is not None
        start, end = world_points(arrow)[0], world_points(arrow)[-1]
        expected_start = bound_endpoint(source, arrow.start_binding, target.center)
        expected_end = bound_endpoint(target, arrow.end_binding, source.center)
        assert start.distance_to(expected_start) < 1e-6
        assert end.distance_to(expected_end) < 1e-6


def test_the_first_value_is_at_the_bottom_of_a_stack() -> None:
    elements = made(StructureKind.STACK, "1, 2, 3")
    cells = labelled(elements)
    assert cells["1"].y > cells["2"].y > cells["3"].y
    assert len({c.x for c in cells.values()}) == 1
    assert "top" in captions(elements)


def test_a_queue_names_its_front_and_back() -> None:
    assert captions(made(StructureKind.QUEUE, "1, 2, 3")) == ["front", "back"]
    assert captions(made(StructureKind.QUEUE, "7")) == ["front / back"]


def test_a_tree_follows_the_level_order_list() -> None:
    elements = made(StructureKind.TREE, "1, 2, 3, null, 4")
    nodes = labelled(elements)
    assert set(nodes) == {"1", "2", "3", "4"}
    assert len(arrows(elements)) == 3  # 1-2, 1-3, 2-4
    assert nodes["1"].y < nodes["2"].y < nodes["4"].y
    assert nodes["2"].y == nodes["3"].y
    assert nodes["2"].x < nodes["1"].x < nodes["3"].x  # left child, parent, right child
    assert nodes["2"].x < nodes["4"].x < nodes["1"].x  # 4 is the right child of 2


def test_tree_links_are_plain_lines_between_circles() -> None:
    elements = made(StructureKind.TREE, "1, 2")
    assert all(isinstance(e, Ellipse | Arrow) for e in elements)
    link = arrows(elements)[0]
    assert link.style.start_head == Arrowhead.NONE
    assert link.style.end_head == Arrowhead.NONE


def test_a_tree_needs_a_root() -> None:
    with pytest.raises(StructureError, match="root"):
        made(StructureKind.TREE, "null, 1, 2")


def test_an_undirected_graph_has_headless_edges() -> None:
    elements = made(StructureKind.GRAPH, "A-B, B-C, C-A")
    assert set(labelled(elements)) == {"A", "B", "C"}
    links = arrows(elements)
    assert len(links) == 3
    assert all(a.style.end_head == Arrowhead.NONE for a in links)


def test_directed_and_weighted_edges() -> None:
    directed, weighted = arrows(made(StructureKind.GRAPH, "A->B, B-C:5"))
    assert directed.style.end_head == Arrowhead.ARROW
    assert weighted.label == "5"
    assert weighted.style.end_head == Arrowhead.NONE


def test_a_lone_name_is_a_node_without_edges() -> None:
    elements = made(StructureKind.GRAPH, "A-B, Z")
    assert set(labelled(elements)) == {"A", "B", "Z"}
    assert len(arrows(elements)) == 1


def test_graph_nodes_do_not_overlap() -> None:
    elements = made(StructureKind.GRAPH, "1-2, 2-3, 3-4, 4-5, 5-6, 6-1")
    boxes = [element_bounds(n) for n in labelled(elements).values()]
    assert not any(a.intersects(b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])


@pytest.mark.parametrize("kind", list(StructureKind))
def test_empty_input_explains_itself(kind: StructureKind) -> None:
    with pytest.raises(StructureError, match="type some values"):
        made(kind, "   ")


def test_too_many_items_are_refused_with_a_number() -> None:
    values = ", ".join(str(i) for i in range(MAX_ITEMS + 1))
    with pytest.raises(StructureError, match=str(MAX_ITEMS + 1)):
        made(StructureKind.ARRAY, values)


def test_a_structure_is_centered_where_it_is_asked_to_be() -> None:
    elements = recentered(made(StructureKind.ARRAY, "1, 2, 3, 4"), Point(500, 300))
    box = element_bounds(elements[0])
    for element in elements[1:]:
        box = box.union(element_bounds(element))
    assert box.center.x == pytest.approx(500)
    assert box.center.y == pytest.approx(300)


def test_the_users_colors_are_kept_when_they_chose_some() -> None:
    chosen = Style(stroke_color="#c92a2a")
    cells = [e for e in build(StructureKind.ARRAY, "1", chosen) if isinstance(e, Rectangle)]
    assert cells[0].style.stroke_color == "#c92a2a"
    default = [e for e in made(StructureKind.ARRAY, "1") if isinstance(e, Rectangle)]
    assert default[0].style.stroke_color != Style().stroke_color  # the app's blue pair
