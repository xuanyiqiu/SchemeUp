"""Hit testing on the ideal geometry of elements (not the wobbly rough paths)."""

from __future__ import annotations

import math
from collections.abc import Iterable

from schemeup.domain.document import Document
from schemeup.domain.elements import (
    LINEAR,
    Diamond,
    Element,
    Ellipse,
    Frame,
    Freedraw,
    Image,
    Text,
    element_bounds,
    to_local,
    world_points,
)
from schemeup.domain.geometry import Point, Rect, distance_to_polyline, distance_to_segment

FRAME_TITLE_HEIGHT = 24.0


def _diamond_corners(r: Rect) -> list[Point]:
    c = r.center
    return [Point(c.x, r.top), Point(r.right, c.y), Point(c.x, r.bottom), Point(r.left, c.y)]


def is_inside(element: Element, p: Point) -> bool:
    """Whether `p` lies inside the element's area (shapes, text, images, frames)."""
    local = to_local(element, p)
    rect = element.local_rect
    match element:
        case Ellipse():
            hw, hh = rect.width / 2, rect.height / 2
            if hw <= 0 or hh <= 0:
                return False
            c = rect.center
            return ((local.x - c.x) / hw) ** 2 + ((local.y - c.y) / hh) ** 2 <= 1
        case Diamond():
            hw, hh = rect.width / 2, rect.height / 2
            if hw <= 0 or hh <= 0:
                return False
            c = rect.center
            return abs(local.x - c.x) / hw + abs(local.y - c.y) / hh <= 1
        case _ if isinstance(element, (LINEAR, Freedraw)):
            return False
        case _:
            return rect.contains(local)


def outline_distance(element: Element, p: Point) -> float:
    """Distance from `p` to the element's outline (shapes, text, images, frames)."""
    local = to_local(element, p)
    rect = element.local_rect
    match element:
        case Ellipse():
            c = rect.center
            hw, hh = rect.width / 2, rect.height / 2
            d = local - c
            if hw <= 0 or hh <= 0:
                return d.length()
            r = math.sqrt((d.x / hw) ** 2 + (d.y / hh) ** 2)
            if r == 0:
                return min(hw, hh)
            return d.length() * abs(1 - 1 / r)
        case Diamond():
            corners = _diamond_corners(rect)
            return min(
                distance_to_segment(local, corners[i], corners[(i + 1) % 4]) for i in range(4)
            )
        case _:
            if rect.contains(local):
                return min(
                    local.x - rect.left,
                    rect.right - local.x,
                    local.y - rect.top,
                    rect.bottom - local.y,
                )
            dx = max(rect.left - local.x, 0.0, local.x - rect.right)
            dy = max(rect.top - local.y, 0.0, local.y - rect.bottom)
            return math.hypot(dx, dy)


def frame_title_rect(frame: Frame) -> Rect:
    return Rect(frame.x, frame.y - FRAME_TITLE_HEIGHT, max(frame.width, 60.0), FRAME_TITLE_HEIGHT)


def hit_test(element: Element, p: Point, tolerance: float) -> bool:
    half_stroke = element.style.stroke_width / 2
    if isinstance(element, LINEAR):
        return distance_to_polyline(p, world_points(element)) <= tolerance + half_stroke
    if isinstance(element, Freedraw):
        return (
            distance_to_polyline(p, world_points(element))
            <= tolerance + element.style.stroke_width * 2
        )
    if isinstance(element, Text | Image):
        return element.local_rect.inflated(tolerance).contains(to_local(element, p))
    if isinstance(element, Frame):
        return outline_distance(element, p) <= tolerance or frame_title_rect(element).contains(p)
    # Only rectangles, diamonds and ellipses are left.
    if (element.style.has_fill or element.label) and is_inside(element, p):
        return True
    return outline_distance(element, p) <= tolerance + half_stroke


def topmost_at(
    document: Document,
    p: Point,
    tolerance: float,
    candidates: Iterable[str] | None = None,
    *,
    include_locked: bool = False,
) -> Element | None:
    ids = document.order if candidates is None else candidates
    for element in reversed(document.in_z_order(ids)):
        if element.locked and not include_locked:
            continue
        if hit_test(element, p, tolerance):
            return element
    return None


def ids_in_rect(
    document: Document, rect: Rect, candidates: Iterable[str] | None = None
) -> list[str]:
    """Unlocked elements whose bounds sit completely inside `rect`."""
    ids = document.order if candidates is None else candidates
    return [
        e.id
        for e in document.in_z_order(ids)
        if not e.locked and rect.contains_rect(element_bounds(e))
    ]
