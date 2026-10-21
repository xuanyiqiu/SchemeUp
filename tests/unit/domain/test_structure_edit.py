import json
from dataclasses import replace
from typing import cast

import pytest

from schemeup.domain.commands import duplicate
from schemeup.domain.document import Document
from schemeup.domain.elements import Arrow, Element, Ellipse, Rectangle
from schemeup.domain.serialization import document_from_dict, document_to_dict
from schemeup.domain.structure_edit import (
    Control,
    StructureEdit,
    StructureOp,
    controls,
    edit,
    read,
)
from schemeup.domain.structures import (
    EXAMPLES,
    MAX_ITEMS,
    GraphModel,
    StructureKind,
    TreeNode,
    build,
    union_bounds,
)
from schemeup.domain.style import Arrowhead, Style

BASE = Style()


def drawn(kind: StructureKind, text: str) -> Document:
    return Document.of(build(kind, text, BASE))


def nodes(document: Document, kind: StructureKind) -> list[Rectangle | Ellipse]:
    found = [
        e
        for e in document.ordered()
        if e.structure == kind.value and isinstance(e, Rectangle | Ellipse)
    ]
    return sorted(found, key=lambda n: (n.y, n.x))


def by_label(document: Document, kind: StructureKind, label: str) -> Rectangle | Ellipse:
    return next(n for n in nodes(document, kind) if n.label == label)


def run(document: Document, node_id: str, op: StructureOp) -> tuple[Document, StructureEdit]:
    result = edit(document, node_id, op)
    assert result is not None, f"{op} is not offered on that node"
    changes: dict[str, Element | None] = {i: None for i in result.remove}
    changes.update({e.id: e for e in result.add})
    return document.with_elements(changes), result


def values(document: Document, kind: StructureKind) -> list[str]:
    """Labels of a structure's value shapes, in reading order."""
    shapes = nodes(document, kind)
    if kind is StructureKind.STACK:
        return [n.label for n in sorted(shapes, key=lambda n: -n.y)]
    return [n.label for n in sorted(shapes, key=lambda n: n.x)]


def offered(document: Document, node_id: str) -> set[StructureOp]:
    reading = read(document, node_id)
    assert reading is not None
    return {c.op for c in controls(reading) if c.node_id == node_id}


def level_order(root: TreeNode) -> list[str | None]:
    out: list[str | None] = []
    queue: list[TreeNode | None] = [root]
    for node in queue:
        out.append(None if node is None else node.value)
        if node is not None:
            queue += [node.left, node.right]
    while out and out[-1] is None:
        out.pop()
    return out


# Reading the canvas back


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        (StructureKind.ARRAY, "3, 1, 4", ["3", "1", "4"]),
        (StructureKind.LINKED_LIST, "a -> b -> c", ["a", "b", "c"]),
        (StructureKind.DOUBLY_LINKED_LIST, "1, 2", ["1", "2"]),
        (StructureKind.STACK, "1, 2, 3", ["1", "2", "3"]),
        (StructureKind.QUEUE, "x, y", ["x", "y"]),
    ],
)
def test_lists_are_read_back_in_order(kind: StructureKind, text: str, expected: list[str]) -> None:
    document = drawn(kind, text)
    reading = read(document, nodes(document, kind)[0].id)
    assert reading is not None and reading.model == expected


def test_a_matrix_is_read_back_as_rows() -> None:
    document = drawn(StructureKind.MATRIX, "1 2 3; 4 5 6")
    reading = read(document, nodes(document, StructureKind.MATRIX)[0].id)
    assert reading is not None and reading.model == [["1", "2", "3"], ["4", "5", "6"]]


def test_a_tree_is_read_back_from_its_links() -> None:
    document = drawn(StructureKind.TREE, "1, 2, 3, null, 4")
    reading = read(document, by_label(document, StructureKind.TREE, "1").id)
    assert reading is not None
    assert level_order(cast(TreeNode, reading.model)) == ["1", "2", "3", None, "4"]


def test_a_graph_is_read_back_with_directions_and_weights() -> None:
    document = drawn(StructureKind.GRAPH, "A-B:4, B->C")
    reading = read(document, by_label(document, StructureKind.GRAPH, "A").id)
    assert reading is not None
    graph = cast(GraphModel, reading.model)
    assert graph.labels == ["A", "B", "C"]
    assert [(e.a, e.b, e.directed, e.weight) for e in graph.edges] == [
        (0, 1, False, "4"),
        (1, 2, True, ""),
    ]


def test_a_value_typed_into_a_cell_is_part_of_what_is_read() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2, 3")
    middle = by_label(document, StructureKind.ARRAY, "2")
    typed = document.with_elements({middle.id: replace(middle, label="two")})
    edited, _ = run(typed, nodes(typed, StructureKind.ARRAY)[0].id, StructureOp.INSERT_AFTER)
    assert values(edited, StructureKind.ARRAY) == ["1", "", "two", "3"]


def test_something_that_is_not_a_structure_is_not_read() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2")
    cell = nodes(document, StructureKind.ARRAY)[0]
    assert read(document, "nothing") is None
    assert read(document.with_elements({cell.id: replace(cell, group_ids=())}), cell.id) is None
    assert read(document.with_elements({cell.id: replace(cell, structure="")}), cell.id) is None


# Lists


def test_inserting_after_a_cell_adds_an_empty_cell_to_type_into() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2, 3")
    after, result = run(
        document, by_label(document, StructureKind.ARRAY, "1").id, StructureOp.INSERT_AFTER
    )
    assert values(after, StructureKind.ARRAY) == ["1", "", "2", "3"]
    focus = after.get(result.focus or "")
    assert isinstance(focus, Rectangle) and focus.label == ""


def test_inserting_before_is_only_offered_on_the_first_cell() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2, 3")
    first = by_label(document, StructureKind.ARRAY, "1")
    assert StructureOp.INSERT_BEFORE in offered(document, first.id)
    assert StructureOp.INSERT_BEFORE not in offered(
        document, by_label(document, StructureKind.ARRAY, "2").id
    )
    after, _ = run(document, first.id, StructureOp.INSERT_BEFORE)
    assert values(after, StructureKind.ARRAY) == ["", "1", "2", "3"]


def test_deleting_a_cell_removes_just_that_one() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2, 3")
    after, result = run(
        document, by_label(document, StructureKind.ARRAY, "2").id, StructureOp.DELETE
    )
    assert values(after, StructureKind.ARRAY) == ["1", "3"]
    assert result.focus is None


def test_the_last_cell_cannot_be_deleted() -> None:
    document = drawn(StructureKind.ARRAY, "1")
    only = nodes(document, StructureKind.ARRAY)[0]
    assert StructureOp.DELETE not in offered(document, only.id)
    assert edit(document, only.id, StructureOp.DELETE) is None


def test_a_linked_list_keeps_its_links_after_an_insert() -> None:
    document = drawn(StructureKind.LINKED_LIST, "1, 2")
    after, _ = run(
        document, by_label(document, StructureKind.LINKED_LIST, "1").id, StructureOp.INSERT_AFTER
    )
    arrows = [e for e in after.ordered() if isinstance(e, Arrow)]
    assert len(arrows) == 3  # 1-new, new-2, 2-null
    ids = set(after.elements)
    assert all(
        a.start_binding
        and a.end_binding
        and {a.start_binding.element_id, a.end_binding.element_id} <= ids
        for a in arrows
    )


def test_pushing_onto_a_stack_adds_above_the_top_and_keeps_the_base_still() -> None:
    document = drawn(StructureKind.STACK, "1, 2")
    base_before = by_label(document, StructureKind.STACK, "1")
    top = by_label(document, StructureKind.STACK, "2")
    after, _ = run(document, top.id, StructureOp.INSERT_AFTER)
    assert values(after, StructureKind.STACK) == ["1", "2", ""]
    base_after = by_label(after, StructureKind.STACK, "1")
    assert base_after.y + base_after.height == pytest.approx(base_before.y + base_before.height)
    assert base_after.x == pytest.approx(base_before.x)


def test_an_array_keeps_its_top_left_corner_when_it_grows() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2")
    first = by_label(document, StructureKind.ARRAY, "1")
    after, _ = run(document, first.id, StructureOp.INSERT_AFTER)
    again = by_label(after, StructureKind.ARRAY, "1")
    assert (again.x, again.y) == pytest.approx((first.x, first.y))


def test_the_buttons_stop_offering_inserts_at_the_size_limit() -> None:
    text = ", ".join(str(i) for i in range(MAX_ITEMS))
    document = drawn(StructureKind.ARRAY, text)
    cell = nodes(document, StructureKind.ARRAY)[0]
    assert StructureOp.INSERT_AFTER not in offered(document, cell.id)
    assert StructureOp.DELETE in offered(document, cell.id)


# Keeping it in place


def test_a_redrawn_structure_keeps_its_groups_and_frame() -> None:
    elements = [
        replace(e, group_ids=(*e.group_ids, "outer"), frame_id="frame")
        for e in build(StructureKind.ARRAY, "1, 2", BASE)
    ]
    document = Document.of(elements)
    after, result = run(
        document, by_label(document, StructureKind.ARRAY, "1").id, StructureOp.INSERT_AFTER
    )
    assert {e.group_ids for e in result.add} == {elements[0].group_ids}
    assert {e.frame_id for e in result.add} == {"frame"}
    assert not set(result.remove) & {e.id for e in result.add}
    assert len(after) == len(result.add)


def test_the_style_of_the_cells_is_kept() -> None:
    chosen = Style(stroke_color="#c92a2a", font_size=28.0)
    document = Document.of(build(StructureKind.ARRAY, "1, 2", chosen))
    after, _ = run(document, nodes(document, StructureKind.ARRAY)[0].id, StructureOp.INSERT_AFTER)
    assert {n.style.stroke_color for n in nodes(after, StructureKind.ARRAY)} == {"#c92a2a"}
    assert {n.style.font_size for n in nodes(after, StructureKind.ARRAY)} == {28.0}


# Matrices


def test_matrix_rows_and_columns_can_be_added_and_removed() -> None:
    document = drawn(StructureKind.MATRIX, "1 2; 3 4")
    one = by_label(document, StructureKind.MATRIX, "1").id
    four = by_label(document, StructureKind.MATRIX, "4").id

    wider, _ = run(document, four, StructureOp.ADD_COLUMN)
    assert len(nodes(wider, StructureKind.MATRIX)) == 6
    taller, _ = run(document, four, StructureOp.ADD_ROW)
    assert len(nodes(taller, StructureKind.MATRIX)) == 6

    narrower, _ = run(document, four, StructureOp.DELETE_COLUMN)
    assert sorted(n.label for n in nodes(narrower, StructureKind.MATRIX)) == ["1", "3"]
    shorter, _ = run(document, four, StructureOp.DELETE_ROW)
    assert sorted(n.label for n in nodes(shorter, StructureKind.MATRIX)) == ["1", "2"]
    assert one in document.elements


def test_matrix_buttons_sit_under_the_last_row_and_beside_the_last_column() -> None:
    document = drawn(StructureKind.MATRIX, "1 2; 3 4")
    reading = read(document, by_label(document, StructureKind.MATRIX, "1").id)
    assert reading is not None
    ops = {(c.node_id, c.op) for c in controls(reading)}
    top_left = by_label(document, StructureKind.MATRIX, "1").id
    bottom_right = by_label(document, StructureKind.MATRIX, "4").id
    assert (top_left, StructureOp.ADD_COLUMN) not in ops
    assert (bottom_right, StructureOp.ADD_COLUMN) in ops
    assert (bottom_right, StructureOp.ADD_ROW) in ops


def test_the_last_row_and_column_of_a_matrix_cannot_be_removed() -> None:
    document = drawn(StructureKind.MATRIX, "7")
    cell = nodes(document, StructureKind.MATRIX)[0].id
    assert {StructureOp.DELETE_ROW, StructureOp.DELETE_COLUMN}.isdisjoint(offered(document, cell))


# Trees


def test_children_can_be_added_only_where_there_is_room() -> None:
    document = drawn(StructureKind.TREE, "1, 2, 3, null, 4")
    assert offered(document, by_label(document, StructureKind.TREE, "1").id) == set()
    assert offered(document, by_label(document, StructureKind.TREE, "3").id) == {
        StructureOp.ADD_LEFT,
        StructureOp.ADD_RIGHT,
        StructureOp.DELETE,
    }
    two = offered(document, by_label(document, StructureKind.TREE, "2").id)
    assert StructureOp.ADD_LEFT in two and StructureOp.ADD_RIGHT not in two


def test_adding_a_child_puts_it_on_the_chosen_side_and_ready_to_type() -> None:
    document = drawn(StructureKind.TREE, "1, 2")
    after, result = run(
        document, by_label(document, StructureKind.TREE, "1").id, StructureOp.ADD_RIGHT
    )
    reading = read(after, by_label(after, StructureKind.TREE, "1").id)
    assert reading is not None
    assert level_order(cast(TreeNode, reading.model)) == ["1", "2", ""]
    focus = after.get(result.focus or "")
    assert isinstance(focus, Ellipse) and focus.label == ""


def test_deleting_a_node_takes_its_subtree_with_it() -> None:
    document = drawn(StructureKind.TREE, "1, 2, 3, 4, 5")
    after, _ = run(document, by_label(document, StructureKind.TREE, "2").id, StructureOp.DELETE)
    assert sorted(n.label for n in nodes(after, StructureKind.TREE)) == ["1", "3"]
    assert len([e for e in after.ordered() if isinstance(e, Arrow)]) == 1


def test_the_root_of_a_tree_has_no_delete_button() -> None:
    document = drawn(StructureKind.TREE, "1, 2")
    assert StructureOp.DELETE not in offered(
        document, by_label(document, StructureKind.TREE, "1").id
    )


def test_a_tree_stays_centered_on_the_same_point() -> None:
    document = drawn(StructureKind.TREE, "1, 2, 3")
    before = union_bounds(document.ordered()).center
    after, _ = run(document, by_label(document, StructureKind.TREE, "2").id, StructureOp.ADD_LEFT)
    now = union_bounds(after.ordered()).center
    assert now.x == pytest.approx(before.x)
    assert now.y == pytest.approx(before.y)


def test_a_tree_with_a_missing_link_is_left_alone() -> None:
    document = drawn(StructureKind.TREE, "1, 2, 3")
    arrow = next(e for e in document.ordered() if isinstance(e, Arrow))
    broken = document.with_elements({arrow.id: None})
    assert read(broken, by_label(broken, StructureKind.TREE, "1").id) is None
    assert edit(broken, by_label(broken, StructureKind.TREE, "1").id, StructureOp.ADD_LEFT) is None


# Graphs


def test_a_new_graph_node_continues_the_naming_and_links_to_its_neighbour() -> None:
    document = drawn(StructureKind.GRAPH, "A-B")
    after, result = run(
        document, by_label(document, StructureKind.GRAPH, "B").id, StructureOp.ADD_NEIGHBOUR
    )
    assert sorted(n.label for n in nodes(after, StructureKind.GRAPH)) == ["A", "B", "C"]
    assert len([e for e in after.ordered() if isinstance(e, Arrow)]) == 2
    new = after.get(result.focus or "")
    assert isinstance(new, Ellipse) and new.label == "C"


def test_numbered_graphs_get_the_next_number() -> None:
    document = drawn(StructureKind.GRAPH, "1-2, 2-3")
    after, _ = run(
        document, by_label(document, StructureKind.GRAPH, "3").id, StructureOp.ADD_NEIGHBOUR
    )
    assert "4" in {n.label for n in nodes(after, StructureKind.GRAPH)}


def test_a_new_node_in_a_directed_graph_gets_a_directed_edge() -> None:
    document = drawn(StructureKind.GRAPH, "A->B, B->C")
    after, _ = run(
        document, by_label(document, StructureKind.GRAPH, "C").id, StructureOp.ADD_NEIGHBOUR
    )
    arrows = [e for e in after.ordered() if isinstance(e, Arrow)]
    assert all(a.style.end_head == Arrowhead.ARROW for a in arrows)


def test_deleting_a_graph_node_removes_its_edges_and_keeps_the_rest() -> None:
    document = drawn(StructureKind.GRAPH, "A-B:1, B-C:2, C-D:3")
    after, _ = run(document, by_label(document, StructureKind.GRAPH, "B").id, StructureOp.DELETE)
    assert sorted(n.label for n in nodes(after, StructureKind.GRAPH)) == ["A", "C", "D"]
    remaining = [e for e in after.ordered() if isinstance(e, Arrow)]
    assert [a.label for a in remaining] == ["3"]


def test_the_last_graph_node_cannot_be_deleted() -> None:
    document = drawn(StructureKind.GRAPH, "A")
    only = nodes(document, StructureKind.GRAPH)[0]
    assert offered(document, only.id) == {StructureOp.ADD_NEIGHBOUR}


# Buttons


def test_every_button_is_on_a_node_of_its_own_structure() -> None:
    for kind in StructureKind:
        document = drawn(kind, EXAMPLES[kind])
        node = nodes(document, kind)[0]
        reading = read(document, node.id)
        assert reading is not None
        found = controls(reading)
        assert found, kind
        assert all(isinstance(c, Control) and c.node_id in document.elements for c in found)


def test_an_op_the_node_does_not_offer_is_refused() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2")
    cell = nodes(document, StructureKind.ARRAY)[0]
    assert edit(document, cell.id, StructureOp.ADD_LEFT) is None
    assert edit(document, "missing", StructureOp.DELETE) is None


def test_a_structure_is_still_editable_after_saving_and_loading() -> None:
    document = drawn(StructureKind.TREE, "1, 2, 3")
    restored = document_from_dict(json.loads(json.dumps(document_to_dict(document))))
    root = by_label(restored, StructureKind.TREE, "1")
    after, _ = run(restored, by_label(restored, StructureKind.TREE, "3").id, StructureOp.ADD_LEFT)
    assert root.structure == "tree"
    assert len(nodes(after, StructureKind.TREE)) == 4


def test_a_duplicated_structure_is_edited_on_its_own() -> None:
    document = drawn(StructureKind.ARRAY, "1, 2")
    changes, new_ids = duplicate(document, [e.id for e in document.ordered()])
    both = document.with_elements(changes)
    copies = [both.elements[i] for i in new_ids if both.elements[i].structure]
    original_count = len(nodes(document, StructureKind.ARRAY))
    after, _ = run(both, copies[0].id, StructureOp.INSERT_AFTER)
    assert len(nodes(after, StructureKind.ARRAY)) == original_count * 2 + 1
    untouched = {e.id for e in document.ordered()}
    assert untouched <= set(after.elements)
