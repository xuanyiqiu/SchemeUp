"""Data structures drawn from a line of text: arrays, linked lists, trees, graphs.

`build` turns something like "3, 1, 4, 1, 5" or "1,2,3,null,4" into shapes, arrows
bound to them and small captions, all in one group, so a diagram of a structure
costs a few seconds of typing instead of a few minutes of dragging boxes.

The drawing itself works from a model (values, rows, a tree, a graph), which is
also what `structure_edit` reads back from the canvas and changes when a cell or a
node is added or removed.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, cast

from schemeup.domain import commands
from schemeup.domain.binding import CENTER, DEFAULT_GAP, bound_endpoint
from schemeup.domain.commands import ShapeKind
from schemeup.domain.elements import (
    Arrow,
    Binding,
    Element,
    Ellipse,
    Rectangle,
    Text,
    element_bounds,
    new_id,
    translated,
)
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.style import (
    TRANSPARENT,
    Arrowhead,
    FillStyle,
    StrokeStyle,
    Style,
    TextAlign,
)
from schemeup.domain.text import LABEL_PADDING

MAX_ITEMS = 64
CELL_HEIGHT = 44.0
MIN_CELL_WIDTH = 52.0
NODE_GAP = 48.0  # between the nodes of a linked list
LEVEL_GAP = 40.0  # between the levels of a tree
NODE_FILL = "#a5d8ff"
NODE_STROKE = "#1971c2"
CAPTION_STROKE = "#868e96"
EMPTY_WORDS = frozenset({"null", "none", "nil", "#", "-", "~"})


class StructureKind(StrEnum):
    ARRAY = "array"
    MATRIX = "matrix"
    LINKED_LIST = "linked-list"
    DOUBLY_LINKED_LIST = "doubly-linked-list"
    STACK = "stack"
    QUEUE = "queue"
    TREE = "tree"
    GRAPH = "graph"


# A sample line for each kind: the picker's placeholder, and what it draws when you press Enter
# without typing anything.
EXAMPLES: dict[StructureKind, str] = {
    StructureKind.ARRAY: "3, 1, 4, 1, 5, 9",
    StructureKind.MATRIX: "1 2 3; 4 5 6; 7 8 9",
    StructureKind.LINKED_LIST: "1 -> 2 -> 3 -> 4",
    StructureKind.DOUBLY_LINKED_LIST: "1, 2, 3, 4",
    StructureKind.STACK: "1, 2, 3",
    StructureKind.QUEUE: "1, 2, 3",
    StructureKind.TREE: "1, 2, 3, null, 4, 5, 6",
    StructureKind.GRAPH: "A-B, B-C, C-A, A->D",
}


class StructureError(ValueError):
    """The text could not be turned into this kind of structure."""


# Models


@dataclass(slots=True, eq=False)
class TreeNode:
    value: str
    left: TreeNode | None = None
    right: TreeNode | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    a: int  # index into the graph's labels
    b: int
    directed: bool = False
    weight: str = ""


@dataclass(slots=True)
class GraphModel:
    labels: list[str]
    edges: list[Edge] = field(default_factory=list)


# What a structure of each kind is made of: a list of values (array, linked lists, stack,
# queue), a list of rows (matrix), the root of a tree, or a graph.
type Model = list[str] | list[list[str]] | TreeNode | GraphModel


@dataclass(slots=True)
class Built:
    """A drawn structure: its elements, and the shape of each value in its model.

    `nodes` is keyed by where the value sits in the model: an index (lists, graphs), a
    (row, column) pair (matrices) or the `TreeNode` itself."""

    elements: list[Element]
    nodes: dict[Any, Element]


# Parsing


def _words(text: str) -> list[str]:
    parts = re.split(r"\s*(?:<->|->|=>|→|,|;|\n)\s*|\s+", text.strip())
    return [p for p in parts if p]


def _check_size(count: int) -> None:
    if count == 0:
        raise StructureError("type some values first")
    if count > MAX_ITEMS:
        raise StructureError(f"that is {count} items; up to {MAX_ITEMS} fit on a diagram")


def _is_empty(word: str) -> bool:
    return word.lower() in EMPTY_WORDS


def _tree_from_level_order(words: list[str]) -> TreeNode:
    """The usual level-order list: children of each node in turn, `null` for a missing one."""
    if _is_empty(words[0]):
        raise StructureError("a tree needs a root value first")
    root = TreeNode(words[0])
    pending = iter(words[1:])
    queue = [root]
    for node in queue:
        for side in ("left", "right"):
            word = next(pending, None)
            if word is None:
                return root
            if not _is_empty(word):
                child = TreeNode(word)
                setattr(node, side, child)
                queue.append(child)
    return root


_EDGE = re.compile(r"^(?P<a>.+?)\s*(?P<arrow>->|--|-|=>|→)\s*(?P<b>.+?)(?::(?P<w>[^:]+))?$")


def _parse_graph(text: str) -> GraphModel:
    """Node names in order of appearance, and the edges written between them."""
    labels: list[str] = []
    edges: list[Edge] = []

    def index_of(name: str) -> int:
        if name not in labels:
            labels.append(name)
        return labels.index(name)

    for part in re.split(r"[,;\n]+", text):
        part = part.strip()
        if not part:
            continue
        match = _EDGE.match(part)
        if match is None:
            index_of(part)  # a lone name is a node without edges
            continue
        a, b = index_of(match["a"].strip()), index_of(match["b"].strip())
        directed = match["arrow"] in ("->", "=>", "→")
        edges.append(Edge(a, b, directed, (match["w"] or "").strip()))
    return GraphModel(labels, edges)


def parse(kind: StructureKind, text: str) -> Model:
    """The model a line of text describes; `StructureError` says what is wrong with it."""
    match kind:
        case StructureKind.MATRIX:
            rows = [_words(r) for r in re.split(r"[;\n/]", text) if r.strip()]
            _check_size(sum(len(r) for r in rows))
            return rows
        case StructureKind.GRAPH:
            graph = _parse_graph(text)
            _check_size(len(graph.labels))
            return graph
        case StructureKind.TREE:
            words = _words(text)
            _check_size(len(words))
            return _tree_from_level_order(words)
        case _:
            words = _words(text)
            _check_size(len(words))
            return words


# Styles


def _node_style(base: Style) -> Style:
    """The blue node look, unless the user already picked their own colors."""
    if base.fill_color == TRANSPARENT and base.stroke_color == Style().stroke_color:
        return replace(
            base, fill_color=NODE_FILL, fill_style=FillStyle.SOLID, stroke_color=NODE_STROKE
        )
    return base


def _link_style(base: Style, nodes: Style, heads: tuple[Arrowhead, Arrowhead]) -> Style:
    return replace(
        base,
        stroke_color=nodes.stroke_color,
        fill_color=TRANSPARENT,
        start_head=heads[0],
        end_head=heads[1],
    )


def _caption_style(base: Style) -> Style:
    return replace(
        base,
        font_size=max(12.0, round(base.font_size * 0.7)),
        stroke_color=CAPTION_STROKE,
        text_align=TextAlign.CENTER,
        fill_color=TRANSPARENT,
    )


# Pieces


def _cell_width(words: list[str], font_size: float) -> float:
    longest = max((len(w) for w in words), default=1)
    return max(MIN_CELL_WIDTH, math.ceil(longest * font_size * 0.62 + 26))


def _circle_size(words: list[str], font_size: float) -> float:
    """Diameter of a node circle that holds its label on one line, so the editor does not
    stretch it.

    An ellipse's label area is the square inscribed in it, so the circle has to be
    root two times as wide and as tall as the text plus its padding."""
    longest = max((len(w) for w in words), default=1)
    text_width = longest * font_size * 0.75  # the hand font is wide: "20" is 1.5 sizes across
    line = font_size * 1.1  # the tight line height of the canvas fonts, rounded up
    needed = max(text_width, line) + 2 * LABEL_PADDING
    return max(CELL_HEIGHT, math.ceil(needed * math.sqrt(2)))


def _shape(kind: ShapeKind, rect: Rect, label: str, style: Style) -> Rectangle | Ellipse:
    shape = commands.make_shape(kind, rect, style)
    assert isinstance(shape, Rectangle | Ellipse)
    return replace(shape, label=label)


def _node(
    structure: StructureKind, kind: ShapeKind, rect: Rect, label: str, style: Style
) -> Rectangle | Ellipse:
    """A shape that holds one value of a structure; the tag lets it be read back later."""
    return replace(_shape(kind, rect, label, style), structure=structure.value)


def _caption(text: str, rect: Rect, base: Style) -> Text:
    """A small centered label that sits in `rect` (its width, its top)."""
    element = commands.make_text(Point(rect.x, rect.y), text, _caption_style(base))
    return replace(element, width=rect.width, auto_width=False)


def _empty_marker(rect: Rect, base: Style, nodes: Style) -> Element:
    style = replace(
        nodes,
        fill_color=TRANSPARENT,
        stroke_color=CAPTION_STROKE,
        stroke_style=StrokeStyle.DASHED,
    )
    return _shape(ShapeKind.RECTANGLE, rect, "null", replace(style, font_size=base.font_size * 0.8))


def _link(
    source: Element,
    target: Element,
    style: Style,
    *,
    source_anchor: Point = CENTER,
    target_anchor: Point = CENTER,
    label: str = "",
) -> Element:
    start = Binding(element_id=source.id, anchor=source_anchor, gap=DEFAULT_GAP)
    end = Binding(element_id=target.id, anchor=target_anchor, gap=DEFAULT_GAP)
    points = [
        bound_endpoint(source, start, target.center),
        bound_endpoint(target, end, source.center),
    ]
    arrow = commands.make_linear(True, points, style)
    assert isinstance(arrow, Arrow)
    return replace(arrow, start_binding=start, end_binding=end, label=label)


RIGHT_SIDE = Point(1.0, 0.5)
LEFT_SIDE = Point(0.0, 0.5)


# Layouts. Each returns elements around the origin; `build_model` groups them.


def _array(words: list[str], base: Style) -> Built:
    nodes = _node_style(base)
    w = _cell_width(words, base.font_size)
    built = Built([], {})
    for i, word in enumerate(words):
        cell = _node(
            StructureKind.ARRAY, ShapeKind.RECTANGLE, Rect(i * w, 0, w, CELL_HEIGHT), word, nodes
        )
        built.nodes[i] = cell
        built.elements += [cell, _caption(str(i), Rect(i * w, CELL_HEIGHT + 4, w, 20), base)]
    return built


def _matrix(rows: list[list[str]], base: Style) -> Built:
    nodes = _node_style(base)
    columns = max(len(r) for r in rows)
    w = _cell_width([c for r in rows for c in r], base.font_size)
    cap = _caption_style(base).font_size * 1.4
    built = Built([], {})
    for i, row in enumerate(rows):
        for j in range(columns):
            word = row[j] if j < len(row) else ""
            rect = Rect(j * w, i * CELL_HEIGHT, w, CELL_HEIGHT)
            cell = _node(StructureKind.MATRIX, ShapeKind.RECTANGLE, rect, word, nodes)
            built.nodes[(i, j)] = cell
            built.elements.append(cell)
        built.elements.append(
            _caption(str(i), Rect(-34, i * CELL_HEIGHT + (CELL_HEIGHT - cap) / 2, 28, cap), base)
        )
    for j in range(columns):
        built.elements.append(_caption(str(j), Rect(j * w, -cap - 4, w, cap), base))
    return built


def _linked_list(words: list[str], base: Style, doubly: bool) -> Built:
    kind = StructureKind.DOUBLY_LINKED_LIST if doubly else StructureKind.LINKED_LIST
    nodes = _node_style(base)
    heads = (Arrowhead.ARROW if doubly else Arrowhead.NONE, Arrowhead.ARROW)
    links = _link_style(base, nodes, heads)
    w = _cell_width(words, base.font_size)
    step = w + NODE_GAP
    first = 0.0 if not doubly else NODE_GAP + MIN_CELL_WIDTH
    built = Built([], {})
    for i, word in enumerate(words):
        rect = Rect(first + i * step, 0, w, CELL_HEIGHT)
        built.nodes[i] = _node(kind, ShapeKind.RECTANGLE, rect, word, nodes)
    shapes = list(built.nodes.values())
    end = _empty_marker(
        Rect(first + len(words) * step, CELL_HEIGHT * 0.1, MIN_CELL_WIDTH, CELL_HEIGHT * 0.8),
        base,
        nodes,
    )
    chain: list[Element] = [*shapes, end]
    built.elements += chain
    if doubly:
        start = _empty_marker(
            Rect(0, CELL_HEIGHT * 0.1, MIN_CELL_WIDTH, CELL_HEIGHT * 0.8), base, nodes
        )
        chain.insert(0, start)
        built.elements.append(start)
    for a, b in itertools.pairwise(chain):
        built.elements.append(_link(a, b, links, source_anchor=RIGHT_SIDE, target_anchor=LEFT_SIDE))
    built.elements.append(_caption("head", Rect(shapes[0].x, -26, w, 20), base))
    return built


def _stack(words: list[str], base: Style) -> Built:
    nodes = _node_style(base)
    w = _cell_width(words, base.font_size)
    count = len(words)
    built = Built([], {})
    for i, word in enumerate(words):  # the first value is at the bottom
        y = (count - 1 - i) * CELL_HEIGHT
        cell = _node(
            StructureKind.STACK, ShapeKind.RECTANGLE, Rect(0, y, w, CELL_HEIGHT), word, nodes
        )
        built.nodes[i] = cell
        built.elements.append(cell)
    middle = CELL_HEIGHT / 2
    pointer = commands.make_linear(
        True,
        [Point(w + 46, middle), Point(w + 8, middle)],
        _link_style(base, nodes, (Arrowhead.NONE, Arrowhead.ARROW)),
    )
    built.elements += [pointer, _caption("top", Rect(w + 48, middle - 10, 40, 20), base)]
    return built


def _queue(words: list[str], base: Style) -> Built:
    nodes = _node_style(base)
    w = _cell_width(words, base.font_size)
    built = Built([], {})
    for i, word in enumerate(words):
        built.nodes[i] = _node(
            StructureKind.QUEUE, ShapeKind.RECTANGLE, Rect(i * w, 0, w, CELL_HEIGHT), word, nodes
        )
    built.elements += list(built.nodes.values())
    last = (len(words) - 1) * w
    below = CELL_HEIGHT + 4
    if len(words) == 1:
        built.elements.append(_caption("front / back", Rect(-10, below, w + 20, 20), base))
    else:
        built.elements.append(_caption("front", Rect(0, below, w, 20), base))
        built.elements.append(_caption("back", Rect(last, below, w, 20), base))
    return built


def _tree(root: TreeNode, base: Style) -> Built:
    nodes = _node_style(base)
    labels: list[str] = []

    def collect(node: TreeNode | None) -> None:
        if node is not None:
            labels.append(node.value)
            collect(node.left)
            collect(node.right)

    collect(root)
    size = _circle_size(labels, base.font_size)
    step_x, step_y = size + 14, size + LEVEL_GAP
    placed: list[tuple[TreeNode, int, int]] = []  # node, in-order column, depth

    def walk(node: TreeNode | None, depth: int) -> None:
        if node is None:
            return
        walk(node.left, depth + 1)
        placed.append((node, len(placed), depth))
        walk(node.right, depth + 1)

    walk(root, 0)
    built = Built([], {})
    for node, column, depth in placed:
        rect = Rect(column * step_x, depth * step_y, size, size)
        circle = _node(StructureKind.TREE, ShapeKind.ELLIPSE, rect, node.value, nodes)
        built.nodes[node] = circle
        built.elements.append(circle)
    links = _link_style(base, nodes, (Arrowhead.NONE, Arrowhead.NONE))
    for node, _column, _depth in placed:
        for child in (node.left, node.right):
            if child is not None:
                built.elements.append(_link(built.nodes[node], built.nodes[child], links))
    return built


def _graph(graph: GraphModel, base: Style) -> Built:
    nodes = _node_style(base)
    size = _circle_size(graph.labels, base.font_size)
    count = len(graph.labels)
    radius = 0.0 if count == 1 else max(90.0, count * (size + 16) / (2 * math.pi))
    built = Built([], {})
    for i, name in enumerate(graph.labels):
        angle = -math.pi / 2 + 2 * math.pi * i / count
        rect = Rect(
            radius * math.cos(angle) - size / 2, radius * math.sin(angle) - size / 2, size, size
        )
        built.nodes[i] = _node(StructureKind.GRAPH, ShapeKind.ELLIPSE, rect, name, nodes)
    built.elements += list(built.nodes.values())
    for edge in graph.edges:
        if edge.a == edge.b:
            continue  # a loop back to the same node has no sensible straight line
        heads = (Arrowhead.NONE, Arrowhead.ARROW if edge.directed else Arrowhead.NONE)
        link_style = _link_style(base, nodes, heads)
        built.elements.append(
            _link(built.nodes[edge.a], built.nodes[edge.b], link_style, label=edge.weight)
        )
    return built


# Entry points


def build_model(
    kind: StructureKind,
    model: Model,
    base: Style,
    *,
    group_ids: tuple[str, ...] | None = None,
    frame_id: str | None = None,
) -> Built:
    """Draw `model` around the origin, all of it in one group.

    `group_ids` and `frame_id` let a redrawn structure keep the groups and the frame
    the old one belonged to."""
    match kind:
        case StructureKind.MATRIX:
            built = _matrix(cast(list[list[str]], model), base)
        case StructureKind.GRAPH:
            assert isinstance(model, GraphModel)
            built = _graph(model, base)
        case StructureKind.TREE:
            assert isinstance(model, TreeNode)
            built = _tree(model, base)
        case StructureKind.LINKED_LIST | StructureKind.DOUBLY_LINKED_LIST:
            doubly = kind is StructureKind.DOUBLY_LINKED_LIST
            built = _linked_list(cast(list[str], model), base, doubly)
        case StructureKind.STACK:
            built = _stack(cast(list[str], model), base)
        case StructureKind.QUEUE:
            built = _queue(cast(list[str], model), base)
        case StructureKind.ARRAY:
            built = _array(cast(list[str], model), base)
    groups = (new_id(),) if group_ids is None else group_ids
    grouped = {e.id: replace(e, group_ids=groups, frame_id=frame_id) for e in built.elements}
    return Built(
        [grouped[e.id] for e in built.elements],
        {key: grouped[node.id] for key, node in built.nodes.items()},
    )


def build(kind: StructureKind, text: str, base: Style) -> list[Element]:
    """The elements of a structure written as `text`, in one group, around the origin.

    Raises `StructureError` with a message fit to show the user when the text does
    not describe this kind of structure."""
    return build_model(kind, parse(kind, text), base).elements


def union_bounds(elements: list[Element]) -> Rect:
    box = element_bounds(elements[0])
    for element in elements[1:]:
        box = box.union(element_bounds(element))
    return box


def recentered(elements: list[Element], center: Point) -> list[Element]:
    """`elements` moved so the middle of the whole structure sits at `center`."""
    box = union_bounds(elements)
    dx, dy = center.x - box.center.x, center.y - box.center.y
    return [translated(e, dx, dy) for e in elements]
