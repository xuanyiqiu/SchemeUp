"""Data structures drawn from a line of text: arrays, linked lists, trees, graphs.

`build` turns something like "3, 1, 4, 1, 5" or "1,2,3,null,4" into shapes, arrows
bound to them and small captions, all in one group, so a diagram of a structure
costs a few seconds of typing instead of a few minutes of dragging boxes.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, replace
from enum import StrEnum

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


# What the input line looks like for each kind, shown as the placeholder in the picker.
EXAMPLES: dict[StructureKind, str] = {
    StructureKind.ARRAY: "3, 1, 4, 1, 5, 9",
    StructureKind.MATRIX: "1 2 3; 4 5 6; 7 8 9",
    StructureKind.LINKED_LIST: "1 -> 2 -> 3 -> 4",
    StructureKind.DOUBLY_LINKED_LIST: "1, 2, 3, 4",
    StructureKind.STACK: "1, 2, 3  (the last one is the top)",
    StructureKind.QUEUE: "1, 2, 3  (the first one is the front)",
    StructureKind.TREE: "1, 2, 3, null, 4, 5, 6",
    StructureKind.GRAPH: "A-B, B-C, C-A, A->D   (a-b:5 adds a weight)",
}


class StructureError(ValueError):
    """The text could not be turned into this kind of structure."""


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


@dataclass(slots=True)
class _TreeNode:
    value: str
    left: _TreeNode | None = None
    right: _TreeNode | None = None


def _tree_from_level_order(words: list[str]) -> _TreeNode:
    """The usual level-order list: children of each node in turn, `null` for a missing one."""
    if _is_empty(words[0]):
        raise StructureError("a tree needs a root value first")
    root = _TreeNode(words[0])
    pending = iter(words[1:])
    queue = [root]
    for node in queue:
        for side in ("left", "right"):
            word = next(pending, None)
            if word is None:
                return root
            if not _is_empty(word):
                child = _TreeNode(word)
                setattr(node, side, child)
                queue.append(child)
    return root


_EDGE = re.compile(r"^(?P<a>.+?)\s*(?P<arrow>->|--|-|=>|→)\s*(?P<b>.+?)(?::(?P<w>[^:]+))?$")


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


def _shape(kind: ShapeKind, rect: Rect, label: str, style: Style) -> Rectangle | Ellipse:
    shape = commands.make_shape(kind, rect, style)
    assert isinstance(shape, Rectangle | Ellipse)
    return replace(shape, label=label)


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


# Layouts. Each returns elements around the origin; `build` groups and centers them.


def _array(words: list[str], base: Style) -> list[Element]:
    nodes = _node_style(base)
    w = _cell_width(words, base.font_size)
    elements: list[Element] = []
    for i, word in enumerate(words):
        elements.append(_shape(ShapeKind.RECTANGLE, Rect(i * w, 0, w, CELL_HEIGHT), word, nodes))
        elements.append(_caption(str(i), Rect(i * w, CELL_HEIGHT + 4, w, 20), base))
    return elements


def _matrix(rows: list[list[str]], base: Style) -> list[Element]:
    nodes = _node_style(base)
    columns = max(len(r) for r in rows)
    w = _cell_width([c for r in rows for c in r], base.font_size)
    cap = _caption_style(base).font_size * 1.4
    elements: list[Element] = []
    for i, row in enumerate(rows):
        for j in range(columns):
            word = row[j] if j < len(row) else ""
            rect = Rect(j * w, i * CELL_HEIGHT, w, CELL_HEIGHT)
            elements.append(_shape(ShapeKind.RECTANGLE, rect, word, nodes))
        elements.append(
            _caption(str(i), Rect(-34, i * CELL_HEIGHT + (CELL_HEIGHT - cap) / 2, 28, cap), base)
        )
    for j in range(columns):
        elements.append(_caption(str(j), Rect(j * w, -cap - 4, w, cap), base))
    return elements


def _linked_list(words: list[str], base: Style, doubly: bool) -> list[Element]:
    nodes = _node_style(base)
    heads = (Arrowhead.ARROW if doubly else Arrowhead.NONE, Arrowhead.ARROW)
    links = _link_style(base, nodes, heads)
    w = _cell_width(words, base.font_size)
    step = w + NODE_GAP
    first = 0.0 if not doubly else NODE_GAP + MIN_CELL_WIDTH
    shapes = [
        _shape(ShapeKind.RECTANGLE, Rect(first + i * step, 0, w, CELL_HEIGHT), word, nodes)
        for i, word in enumerate(words)
    ]
    end = _empty_marker(
        Rect(first + len(words) * step, CELL_HEIGHT * 0.1, MIN_CELL_WIDTH, CELL_HEIGHT * 0.8),
        base,
        nodes,
    )
    chain: list[Element] = [*shapes, end]
    elements: list[Element] = list(chain)
    if doubly:
        start = _empty_marker(
            Rect(0, CELL_HEIGHT * 0.1, MIN_CELL_WIDTH, CELL_HEIGHT * 0.8), base, nodes
        )
        chain.insert(0, start)
        elements.append(start)
    for a, b in itertools.pairwise(chain):
        elements.append(_link(a, b, links, source_anchor=RIGHT_SIDE, target_anchor=LEFT_SIDE))
    elements.append(_caption("head", Rect(shapes[0].x, -26, w, 20), base))
    return elements


def _stack(words: list[str], base: Style) -> list[Element]:
    nodes = _node_style(base)
    w = _cell_width(words, base.font_size)
    count = len(words)
    elements: list[Element] = []
    for i, word in enumerate(words):  # the first value is at the bottom
        y = (count - 1 - i) * CELL_HEIGHT
        elements.append(_shape(ShapeKind.RECTANGLE, Rect(0, y, w, CELL_HEIGHT), word, nodes))
    middle = CELL_HEIGHT / 2
    pointer = commands.make_linear(
        True,
        [Point(w + 46, middle), Point(w + 8, middle)],
        _link_style(base, nodes, (Arrowhead.NONE, Arrowhead.ARROW)),
    )
    elements += [pointer, _caption("top", Rect(w + 48, middle - 10, 40, 20), base)]
    return elements


def _queue(words: list[str], base: Style) -> list[Element]:
    nodes = _node_style(base)
    w = _cell_width(words, base.font_size)
    elements: list[Element] = [
        _shape(ShapeKind.RECTANGLE, Rect(i * w, 0, w, CELL_HEIGHT), word, nodes)
        for i, word in enumerate(words)
    ]
    last = (len(words) - 1) * w
    below = CELL_HEIGHT + 4
    if len(words) == 1:
        elements.append(_caption("front / back", Rect(-10, below, w + 20, 20), base))
    else:
        elements.append(_caption("front", Rect(0, below, w, 20), base))
        elements.append(_caption("back", Rect(last, below, w, 20), base))
    return elements


def _tree(root: _TreeNode, base: Style) -> list[Element]:
    nodes = _node_style(base)
    labels: list[str] = []

    def collect(node: _TreeNode | None) -> None:
        if node is not None:
            labels.append(node.value)
            collect(node.left)
            collect(node.right)

    collect(root)
    size = max(CELL_HEIGHT, _cell_width(labels, base.font_size) - 8)
    step_x, step_y = size + 14, size + LEVEL_GAP
    placed: list[tuple[_TreeNode, int, int]] = []  # node, in-order column, depth

    def walk(node: _TreeNode | None, depth: int) -> None:
        if node is None:
            return
        walk(node.left, depth + 1)
        placed.append((node, len(placed), depth))
        walk(node.right, depth + 1)

    walk(root, 0)
    shape_of: dict[int, Element] = {}
    elements: list[Element] = []
    for node, column, depth in placed:
        circle = _shape(
            ShapeKind.ELLIPSE, Rect(column * step_x, depth * step_y, size, size), node.value, nodes
        )
        shape_of[id(node)] = circle
        elements.append(circle)
    links = _link_style(base, nodes, (Arrowhead.NONE, Arrowhead.NONE))
    for node, _column, _depth in placed:
        for child in (node.left, node.right):
            if child is not None:
                elements.append(_link(shape_of[id(node)], shape_of[id(child)], links))
    return elements


def _parse_edges(text: str) -> tuple[list[str], list[tuple[str, str, bool, str]]]:
    """Node names in order of appearance, and the edges as (from, to, directed, weight)."""
    order: list[str] = []
    edges: list[tuple[str, str, bool, str]] = []

    def see(name: str) -> None:
        if name not in order:
            order.append(name)

    for part in re.split(r"[,;\n]+", text):
        part = part.strip()
        if not part:
            continue
        match = _EDGE.match(part)
        if match is None:
            see(part)  # a lone name is a node without edges
            continue
        a, b = match["a"].strip(), match["b"].strip()
        see(a)
        see(b)
        directed = match["arrow"] in ("->", "=>", "\u2192")
        edges.append((a, b, directed, (match["w"] or "").strip()))
    return order, edges


def _graph(order: list[str], edges: list[tuple[str, str, bool, str]], base: Style) -> list[Element]:
    nodes = _node_style(base)
    size = max(CELL_HEIGHT, _cell_width(order, base.font_size) - 8)
    count = len(order)
    radius = 0.0 if count == 1 else max(90.0, count * (size + 16) / (2 * math.pi))
    shapes: dict[str, Element] = {}
    for i, name in enumerate(order):
        angle = -math.pi / 2 + 2 * math.pi * i / count
        x = radius * math.cos(angle) - size / 2
        y = radius * math.sin(angle) - size / 2
        shapes[name] = _shape(ShapeKind.ELLIPSE, Rect(x, y, size, size), name, nodes)
    elements: list[Element] = list(shapes.values())
    for a, b, directed, weight in edges:
        if a == b:
            continue  # a loop back to the same node has no sensible straight line
        heads = (Arrowhead.NONE, Arrowhead.ARROW if directed else Arrowhead.NONE)
        elements.append(_link(shapes[a], shapes[b], _link_style(base, nodes, heads), label=weight))
    return elements


# Entry points


def build(kind: StructureKind, text: str, base: Style) -> list[Element]:
    """The elements of a structure written as `text`, in one group, around the origin.

    Raises `StructureError` with a message fit to show the user when the text does
    not describe this kind of structure."""
    match kind:
        case StructureKind.MATRIX:
            rows = [_words(r) for r in re.split(r"[;\n/]", text) if r.strip()]
            _check_size(sum(len(r) for r in rows))
            elements = _matrix(rows, base)
        case StructureKind.GRAPH:
            order, edges = _parse_edges(text)
            _check_size(len(order))
            elements = _graph(order, edges, base)
        case StructureKind.TREE:
            words = _words(text)
            _check_size(len(words))
            elements = _tree(_tree_from_level_order(words), base)
        case _:
            words = _words(text)
            _check_size(len(words))
            elements = {
                StructureKind.ARRAY: lambda: _array(words, base),
                StructureKind.LINKED_LIST: lambda: _linked_list(words, base, doubly=False),
                StructureKind.DOUBLY_LINKED_LIST: lambda: _linked_list(words, base, doubly=True),
                StructureKind.STACK: lambda: _stack(words, base),
                StructureKind.QUEUE: lambda: _queue(words, base),
            }[kind]()
    group = new_id()
    return [replace(e, group_ids=(group,)) for e in elements]


def recentered(elements: list[Element], center: Point) -> list[Element]:
    """`elements` moved so the middle of the whole structure sits at `center`."""
    box = element_bounds(elements[0])
    for element in elements[1:]:
        box = box.union(element_bounds(element))
    dx, dy = center.x - box.center.x, center.y - box.center.y
    return [translated(e, dx, dy) for e in elements]
