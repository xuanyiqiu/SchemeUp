"""Arrow binding geometry: where a bound arrow end sits on its target."""

from __future__ import annotations

import math

from schemeup.domain.document import Document
from schemeup.domain.elements import (
    BINDABLE,
    Arrow,
    Binding,
    Diamond,
    Element,
    Ellipse,
    to_local,
    to_world,
    touched,
    with_world_points,
    world_points,
)
from schemeup.domain.geometry import Point
from schemeup.domain.hit import is_inside, outline_distance

CENTER = Point(0.5, 0.5)
NAMED_ANCHORS = (Point(0.5, 0.0), Point(1.0, 0.5), Point(0.5, 1.0), Point(0.0, 0.5))
DEFAULT_GAP = 6.0


def outline_point(target: Element, toward: Point) -> Point:
    """Where the ray from the target's center towards `toward` crosses its outline."""
    center = target.center
    local = to_local(target, toward)
    d = local - center
    hw, hh = target.width / 2, target.height / 2
    if d.length() == 0 or hw <= 0 or hh <= 0:
        return center
    if isinstance(target, Ellipse):
        t = 1 / math.sqrt((d.x / hw) ** 2 + (d.y / hh) ** 2)
    elif isinstance(target, Diamond):
        t = 1 / (abs(d.x) / hw + abs(d.y) / hh)
    else:
        tx = hw / abs(d.x) if d.x else math.inf
        ty = hh / abs(d.y) if d.y else math.inf
        t = min(tx, ty)
    return to_world(target, center + d * t)


def anchor_point(target: Element, anchor: Point) -> Point:
    local = Point(target.x + anchor.x * target.width, target.y + anchor.y * target.height)
    return to_world(target, local)


def bound_endpoint(target: Element, binding: Binding, toward: Point) -> Point:
    """World position of an arrow end bound to `target`."""
    center = target.center
    if binding.aims_at_center:
        edge = outline_point(target, toward)
    else:
        edge = anchor_point(target, binding.anchor)
    direction = (edge - center).normalized()
    return edge + direction * binding.gap


def find_target(
    document: Document, p: Point, tolerance: float, exclude: frozenset[str] = frozenset()
) -> Element | None:
    """Topmost element an arrow end at `p` would bind to."""
    for element in reversed(document.ordered()):
        if element.id in exclude or not isinstance(element, BINDABLE):
            continue
        if is_inside(element, p) or outline_distance(element, p) <= tolerance:
            return element
    return None


def binding_for(target: Element, p: Point, tolerance: float) -> Binding:
    """The binding an arrow end dropped at `p` gets.

    Near a side midpoint it snaps there. Deep inside the shape it aims at the
    center, so the arrow keeps pointing at the shape as things move. Otherwise
    it sticks to the closest point of the outline."""
    for anchor in NAMED_ANCHORS:
        if anchor_point(target, anchor).distance_to(p) <= tolerance * 1.5:
            return Binding(element_id=target.id, anchor=anchor, gap=DEFAULT_GAP)
    if is_inside(target, p) and outline_distance(target, p) > tolerance:
        return Binding(element_id=target.id, anchor=CENTER, gap=DEFAULT_GAP)
    edge = to_local(target, outline_point(target, p))
    w, h = max(target.width, 1e-9), max(target.height, 1e-9)
    anchor = Point((edge.x - target.x) / w, (edge.y - target.y) / h)
    return Binding(element_id=target.id, anchor=anchor, gap=DEFAULT_GAP)


def rebound(document: Document, arrow: Arrow) -> Arrow:
    """`arrow` with its bound ends moved onto their targets' current geometry."""
    points = world_points(arrow)
    if len(points) < 2:
        return arrow
    start_target = document.get(arrow.start_binding.element_id) if arrow.start_binding else None
    end_target = document.get(arrow.end_binding.element_id) if arrow.end_binding else None
    changed = False
    if arrow.start_binding and start_target is not None:
        toward = end_target.center if end_target is not None and len(points) == 2 else points[1]
        points[0] = bound_endpoint(start_target, arrow.start_binding, toward)
        changed = True
    if arrow.end_binding and end_target is not None:
        toward = (
            start_target.center if start_target is not None and len(points) == 2 else points[-2]
        )
        points[-1] = bound_endpoint(end_target, arrow.end_binding, toward)
        changed = True
    if not changed:
        return arrow
    return with_world_points(arrow, points)


def unbound_from(arrow: Arrow, removed: set[str]) -> Arrow:
    start = arrow.start_binding
    end = arrow.end_binding
    new_start = None if start and start.element_id in removed else start
    new_end = None if end and end.element_id in removed else end
    if new_start is start and new_end is end:
        return arrow
    return touched(arrow, start_binding=new_start, end_binding=new_end)
