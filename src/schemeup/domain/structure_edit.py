"""Changing a drawn data structure: add and remove cells, nodes, rows and columns.

A structure is read back from the canvas, so a value typed into a cell by hand counts. The
edit is made on that model and the structure is redrawn in the same place, in the same
group, as one change that can be undone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from schemeup.domain.document import Document
from schemeup.domain.elements import Arrow, Element, Ellipse, Rectangle, translated
from schemeup.domain.geometry import Point
from schemeup.domain.structures import (
    MAX_ITEMS,
    Edge,
    GraphModel,
    Model,
    StructureKind,
    TreeNode,
    build_model,
    union_bounds,
)
from schemeup.domain.style import Arrowhead, Style


class StructureOp(StrEnum):
    INSERT_AFTER = "insert-after"  # arrays, lists, stacks, queues
    INSERT_BEFORE = "insert-before"
    DELETE = "delete"  # a cell, a tree node and its subtree, a graph node and its edges
    ADD_LEFT = "add-left"  # tree children
    ADD_RIGHT = "add-right"
    ADD_NEIGHBOUR = "add-neighbour"  # graph: a new node linked to this one
    ADD_ROW = "add-row"  # matrices
    DELETE_ROW = "delete-row"
    ADD_COLUMN = "add-column"
    DELETE_COLUMN = "delete-column"


@dataclass(frozen=True, slots=True)
class Control:
    """A button to show on a node. `where` is its center as a fraction of the node's box:
    (1, 0) is the top right corner, (0, 1) the bottom left, and values outside 0..1 sit
    beside the node."""

    node_id: str
    op: StructureOp
    where: Point


@dataclass(slots=True)
class Reading:
    """A structure as it is on the canvas right now."""

    kind: StructureKind
    model: Model
    locators: dict[str, Any]  # value shape id -> its key in the model (index, (row, col), node)
    members: list[Element]  # everything in the structure's group
    group_ids: tuple[str, ...]
    frame_id: str | None
    base: Style


@dataclass(frozen=True, slots=True)
class StructureEdit:
    remove: tuple[str, ...]
    add: tuple[Element, ...]
    focus: str | None  # the new value shape, so its text can be typed straight away


KINDS = {kind.value: kind for kind in StructureKind}
LIST_KINDS = (
    StructureKind.ARRAY,
    StructureKind.LINKED_LIST,
    StructureKind.DOUBLY_LINKED_LIST,
    StructureKind.STACK,
    StructureKind.QUEUE,
)


# Reading


def read(document: Document, node_id: str) -> Reading | None:
    """The structure that value shape `node_id` belongs to, or None if what is on the canvas
    no longer makes a whole structure (a link was deleted, a cell moved away...)."""
    node = document.get(node_id)
    if node is None or node.structure not in KINDS or not node.group_ids:
        return None
    kind = KINDS[node.structure]
    group = node.group_ids[0]
    members = [e for e in document.ordered() if group in e.group_ids]
    nodes = [e for e in members if e.structure == kind.value and isinstance(e, Rectangle | Ellipse)]
    reading = _read_model(kind, nodes, members)
    if reading is None:
        return None
    model, locators = reading
    return Reading(kind, model, locators, members, node.group_ids, node.frame_id, node.style)


def _read_model(
    kind: StructureKind, nodes: list[Rectangle | Ellipse], members: list[Element]
) -> tuple[Model, dict[str, Any]] | None:
    if not nodes:
        return None
    match kind:
        case StructureKind.MATRIX:
            return _read_matrix(nodes)
        case StructureKind.TREE:
            return _read_tree(nodes, members)
        case StructureKind.GRAPH:
            return _read_graph(nodes, members)
        case _:
            if kind is StructureKind.STACK:  # the first value is at the bottom
                ordered = sorted(nodes, key=lambda n: -n.center.y)
            else:
                ordered = sorted(nodes, key=lambda n: n.center.x)
            return [n.label for n in ordered], {n.id: i for i, n in enumerate(ordered)}


def _clusters(values: list[float]) -> list[float]:
    """The distinct positions in `values`, merging those within a pixel of each other."""
    result: list[float] = []
    for value in sorted(values):
        if not result or value - result[-1] > 1.0:
            result.append(value)
    return result


def _nearest(positions: list[float], value: float) -> int:
    return min(range(len(positions)), key=lambda i: abs(positions[i] - value))


def _read_matrix(nodes: list[Rectangle | Ellipse]) -> tuple[Model, dict[str, Any]] | None:
    tops = _clusters([n.y for n in nodes])
    lefts = _clusters([n.x for n in nodes])
    if len(tops) * len(lefts) != len(nodes):
        return None
    rows = [["" for _ in lefts] for _ in tops]
    locators: dict[str, Any] = {}
    filled: set[tuple[int, int]] = set()
    for n in nodes:
        cell = (_nearest(tops, n.y), _nearest(lefts, n.x))
        if cell in filled:
            return None
        filled.add(cell)
        rows[cell[0]][cell[1]] = n.label
        locators[n.id] = cell
    return rows, locators


def _read_tree(
    nodes: list[Rectangle | Ellipse], members: list[Element]
) -> tuple[Model, dict[str, Any]] | None:
    by_id = {n.id: TreeNode(n.label) for n in nodes}
    shapes = {n.id: n for n in nodes}
    children: dict[str, list[str]] = {n.id: [] for n in nodes}
    has_parent: set[str] = set()
    for e in members:
        if not isinstance(e, Arrow) or e.start_binding is None or e.end_binding is None:
            continue
        parent, child = e.start_binding.element_id, e.end_binding.element_id
        if parent in by_id and child in by_id:
            children[parent].append(child)
            has_parent.add(child)
    roots = [n.id for n in nodes if n.id not in has_parent]
    if len(roots) != 1:
        return None
    seen: set[str] = set()
    stack = [roots[0]]
    while stack:
        current = stack.pop()
        if current in seen:
            return None  # a cycle
        seen.add(current)
        kids = sorted(children[current], key=lambda i: shapes[i].center.x)
        if len(kids) > 2:
            return None
        node = by_id[current]
        if len(kids) == 2:
            node.left, node.right = by_id[kids[0]], by_id[kids[1]]
        elif len(kids) == 1:
            only = shapes[kids[0]]
            if only.center.x < shapes[current].center.x:
                node.left = by_id[kids[0]]
            else:
                node.right = by_id[kids[0]]
        stack.extend(kids)
    if len(seen) != len(nodes):
        return None
    return by_id[roots[0]], dict(by_id)


def _read_graph(
    nodes: list[Rectangle | Ellipse], members: list[Element]
) -> tuple[Model, dict[str, Any]] | None:
    index = {n.id: i for i, n in enumerate(nodes)}
    edges: list[Edge] = []
    for e in members:
        if not isinstance(e, Arrow) or e.start_binding is None or e.end_binding is None:
            continue
        a, b = index.get(e.start_binding.element_id), index.get(e.end_binding.element_id)
        if a is not None and b is not None:
            edges.append(Edge(a, b, e.style.end_head != Arrowhead.NONE, e.label))
    return GraphModel([n.label for n in nodes], edges), dict(index)


# Buttons


def controls(reading: Reading) -> list[Control]:
    """The buttons that make sense on each node of `reading` right now."""
    result: list[Control] = []
    kind, model = reading.kind, reading.model
    if kind in LIST_KINDS:
        values = cast(list[str], model)
        room = len(values) < MAX_ITEMS
        for node_id, i in reading.locators.items():
            if room:
                result.append(Control(node_id, StructureOp.INSERT_AFTER, Point(1.0, 0.0)))
                if i == 0 and kind in (
                    StructureKind.ARRAY,
                    StructureKind.LINKED_LIST,
                    StructureKind.DOUBLY_LINKED_LIST,
                ):
                    result.append(Control(node_id, StructureOp.INSERT_BEFORE, Point(0.0, 0.0)))
            if len(values) > 1:
                result.append(Control(node_id, StructureOp.DELETE, Point(0.0, 1.0)))
    elif kind is StructureKind.MATRIX:
        rows = cast(list[list[str]], model)
        count_rows, count_columns = len(rows), len(rows[0])
        room = count_rows * count_columns < MAX_ITEMS
        for node_id, (r, c) in reading.locators.items():
            if r == count_rows - 1:  # column buttons sit under the last row
                if room:
                    result.append(Control(node_id, StructureOp.ADD_COLUMN, Point(0.72, 1.3)))
                if count_columns > 1:
                    result.append(Control(node_id, StructureOp.DELETE_COLUMN, Point(0.28, 1.3)))
            if c == count_columns - 1:  # row buttons sit beside the last column
                if room:
                    result.append(Control(node_id, StructureOp.ADD_ROW, Point(1.3, 0.72)))
                if count_rows > 1:
                    result.append(Control(node_id, StructureOp.DELETE_ROW, Point(1.3, 0.28)))
    elif kind is StructureKind.TREE:
        root = cast(TreeNode, model)
        size = len(_tree_nodes(root))
        for node_id, node in reading.locators.items():
            if size < MAX_ITEMS:
                if node.left is None:
                    result.append(Control(node_id, StructureOp.ADD_LEFT, Point(0.15, 0.85)))
                if node.right is None:
                    result.append(Control(node_id, StructureOp.ADD_RIGHT, Point(0.85, 0.85)))
            if node is not root:
                result.append(Control(node_id, StructureOp.DELETE, Point(0.85, 0.15)))
    elif kind is StructureKind.GRAPH:
        graph = cast(GraphModel, model)
        for node_id in reading.locators:
            if len(graph.labels) < MAX_ITEMS:
                result.append(Control(node_id, StructureOp.ADD_NEIGHBOUR, Point(0.85, 0.15)))
            if len(graph.labels) > 1:
                result.append(Control(node_id, StructureOp.DELETE, Point(0.15, 0.85)))
    return result


# Editing


def _tree_nodes(root: TreeNode) -> list[TreeNode]:
    found = [root]
    for node in found:
        found += [c for c in (node.left, node.right) if c is not None]
    return found


def _next_label(labels: list[str]) -> str:
    """A name for a new graph node that goes with the others: the next number, or letter."""
    if all(label.isdigit() for label in labels):
        return str(max((int(label) for label in labels), default=0) + 1)
    if all(len(label) == 1 and label.isalpha() for label in labels):
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if letter not in labels:
                return letter
    number = len(labels) + 1
    while str(number) in labels:
        number += 1
    return str(number)


def _apply(reading: Reading, node_id: str, op: StructureOp) -> Any:
    """Change `reading.model` in place; returns the key of the new value, if there is one."""
    model, place = reading.model, reading.locators[node_id]
    if reading.kind in LIST_KINDS:
        values = cast(list[str], model)
        if op is StructureOp.INSERT_AFTER:
            values.insert(place + 1, "")
            return place + 1
        if op is StructureOp.INSERT_BEFORE:
            values.insert(place, "")
            return place
        del values[place]
        return None
    if reading.kind is StructureKind.MATRIX:
        rows = cast(list[list[str]], model)
        r, c = place
        if op is StructureOp.ADD_ROW:
            rows.insert(r + 1, ["" for _ in rows[0]])
            return (r + 1, 0)
        if op is StructureOp.ADD_COLUMN:
            for row in rows:
                row.insert(c + 1, "")
            return (0, c + 1)
        if op is StructureOp.DELETE_ROW:
            del rows[r]
        else:
            for row in rows:
                del row[c]
        return None
    if reading.kind is StructureKind.TREE:
        node: TreeNode = place
        if op in (StructureOp.ADD_LEFT, StructureOp.ADD_RIGHT):
            child = TreeNode("")
            if op is StructureOp.ADD_LEFT:
                node.left = child
            else:
                node.right = child
            return child
        for parent in _tree_nodes(cast(TreeNode, model)):  # delete the node with its subtree
            if parent.left is node:
                parent.left = None
            if parent.right is node:
                parent.right = None
        return None
    graph = cast(GraphModel, model)
    if op is StructureOp.ADD_NEIGHBOUR:
        graph.labels.append(_next_label(graph.labels))
        new = len(graph.labels) - 1
        directed = bool(graph.edges) and all(e.directed for e in graph.edges)
        graph.edges.append(Edge(place, new, directed))
        return new
    del graph.labels[place]
    graph.edges[:] = [
        Edge(e.a - (e.a > place), e.b - (e.b > place), e.directed, e.weight)
        for e in graph.edges
        if place not in (e.a, e.b)
    ]
    return None


def edit(document: Document, node_id: str, op: StructureOp) -> StructureEdit | None:
    """`op` applied to the structure `node_id` belongs to, as the elements to swap.

    Returns None when the op is not one the node offers right now (see `controls`)."""
    reading = read(document, node_id)
    if reading is None or not any(c.node_id == node_id and c.op is op for c in controls(reading)):
        return None
    old = union_bounds(reading.members)
    focus_key = _apply(reading, node_id, op)
    built = build_model(
        reading.kind,
        reading.model,
        reading.base,
        group_ids=reading.group_ids,
        frame_id=reading.frame_id,
    )
    new = union_bounds(built.elements)
    # Keep the structure where it was: a stack grows upwards from its base, trees and
    # graphs around their middle, everything else from its top left corner.
    if reading.kind is StructureKind.STACK:
        dx, dy = old.left - new.left, old.bottom - new.bottom
    elif reading.kind in (StructureKind.TREE, StructureKind.GRAPH):
        dx, dy = old.center.x - new.center.x, old.center.y - new.center.y
    else:
        dx, dy = old.left - new.left, old.top - new.top
    placed = tuple(translated(e, dx, dy) for e in built.elements)
    focus = built.nodes[focus_key].id if focus_key is not None else None
    return StructureEdit(tuple(m.id for m in reading.members), placed, focus)
