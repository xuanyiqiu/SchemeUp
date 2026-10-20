"""Editing operations as pure functions.

Each function looks at a document and returns the element changes for one
edit (new element, replacement, or None to delete). The editor session turns
them into undoable changesets.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import replace
from enum import StrEnum
from typing import Any

from schemeup.domain.binding import rebound, unbound_from
from schemeup.domain.document import Document
from schemeup.domain.elements import (
    WITH_POINTS,
    Arrow,
    Diamond,
    Element,
    Ellipse,
    Frame,
    Freedraw,
    Image,
    Line,
    Rectangle,
    Text,
    element_bounds,
    new_id,
    new_seed,
    touched,
    translated,
    with_world_points,
    world_points,
)
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.style import MAX_FONT_SIZE, MIN_FONT_SIZE, Style

type Changes = dict[str, Element | None]


class ShapeKind(StrEnum):
    RECTANGLE = "rectangle"
    DIAMOND = "diamond"
    ELLIPSE = "ellipse"
    FRAME = "frame"


class LayerMove(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"
    FRONT = "front"
    BACK = "back"


class AlignEdge(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


# Creation


def make_shape(kind: ShapeKind, rect: Rect, style: Style) -> Element:
    common: dict[str, Any] = {
        "id": new_id(),
        "x": rect.x,
        "y": rect.y,
        "width": rect.width,
        "height": rect.height,
        "style": style,
        "seed": new_seed(),
    }
    match kind:
        case ShapeKind.RECTANGLE:
            return Rectangle(**common)
        case ShapeKind.DIAMOND:
            return Diamond(**common)
        case ShapeKind.ELLIPSE:
            return Ellipse(**common)
        case ShapeKind.FRAME:
            return Frame(**common)


def make_linear(arrow: bool, points: Sequence[Point], style: Style) -> Line | Arrow:
    base: Line | Arrow = (
        Arrow(id=new_id(), x=0, y=0, style=style, seed=new_seed())
        if arrow
        else Line(id=new_id(), x=0, y=0, style=style, seed=new_seed())
    )
    return replace(with_world_points(base, points), version=1)


def make_freedraw(
    points: Sequence[Point], pressures: Sequence[float], style: Style, simulate: bool
) -> Freedraw:
    base = Freedraw(
        id=new_id(),
        x=0,
        y=0,
        style=style,
        seed=new_seed(),
        pressures=tuple(pressures),
        simulate_pressure=simulate,
    )
    return replace(with_world_points(base, points), version=1)


def make_text(at: Point, text: str, style: Style) -> Text:
    return Text(id=new_id(), x=at.x, y=at.y, text=text, style=style, seed=new_seed())


def make_image(rect: Rect, asset_id: str, style: Style) -> Image:
    return Image(
        id=new_id(),
        x=rect.x,
        y=rect.y,
        width=rect.width,
        height=rect.height,
        asset_id=asset_id,
        style=style,
        seed=new_seed(),
    )


# Helpers


def with_frame_children(document: Document, ids: Iterable[str]) -> set[str]:
    """`ids` plus the children of any frame among them."""
    result = set(ids)
    for element_id in list(result):
        if isinstance(document.get(element_id), Frame):
            result.update(e.id for e in document.children_of(element_id))
    return result


def rebind_dependents(document: Document, changed: set[str]) -> Changes:
    """Arrows bound to `changed` elements, moved to follow them."""
    result: Changes = {}
    for arrow in document.arrows_bound_to(changed):
        if arrow.id in changed:
            continue
        updated = rebound(document, arrow)
        if updated is not arrow:
            result[arrow.id] = updated
    return result


def with_rebinding(document: Document, changes: Changes) -> Changes:
    changed = {i for i, e in changes.items() if e is not None}
    result = dict(changes)
    result.update(rebind_dependents(document.with_elements(changes), changed))
    return result


def assign_frames(document: Document, ids: Iterable[str]) -> Changes:
    """Put elements into the frame under their center (or take them out of one)."""
    frames = document.frames()
    result: Changes = {}
    for element_id in ids:
        element = document.get(element_id)
        if element is None or isinstance(element, Frame):
            continue
        center = element_bounds(element).center
        owner = next(
            (f.id for f in reversed(frames) if f.local_rect.contains(center)),
            None,
        )
        if owner != element.frame_id:
            result[element_id] = touched(element, frame_id=owner)
    return result


# Edits


def move(document: Document, ids: Iterable[str], dx: float, dy: float) -> Changes:
    targets = with_frame_children(document, ids)
    changes: Changes = {}
    for element_id in targets:
        element = document.get(element_id)
        if element is None:
            continue
        moved = translated(element, dx, dy)
        if isinstance(moved, Arrow):
            # An arrow dragged away from its targets lets go of them.
            outside = {
                b.element_id
                for b in (moved.start_binding, moved.end_binding)
                if b is not None and b.element_id not in targets
            }
            moved = unbound_from(moved, outside)
        changes[element_id] = moved
    return with_rebinding(document, changes)


def delete(document: Document, ids: Iterable[str]) -> Changes:
    targets = with_frame_children(document, ids)
    changes: Changes = {
        element_id: None for element_id in targets if element_id in document.elements
    }
    for arrow in document.arrows_bound_to(targets):
        if arrow.id not in targets:
            changes[arrow.id] = unbound_from(arrow, targets)
    return changes


def duplicate(
    document: Document, ids: Iterable[str], offset: Point | None = None
) -> tuple[Changes, list[str]]:
    offset = offset if offset is not None else Point(16.0, 16.0)
    targets = with_frame_children(document, ids)
    originals = document.in_z_order(targets)
    id_map = {e.id: new_id() for e in originals}
    group_map: dict[str, str] = {}
    changes: Changes = {}
    for element in originals:
        groups = tuple(group_map.setdefault(g, new_id()) for g in element.group_ids)
        frame_id = id_map.get(element.frame_id, element.frame_id) if element.frame_id else None
        copy = replace(
            element,
            id=id_map[element.id],
            seed=new_seed(),
            version=1,
            x=element.x + offset.x,
            y=element.y + offset.y,
            group_ids=groups,
            frame_id=frame_id,
            locked=False,
        )
        if isinstance(copy, Arrow):
            start, end = copy.start_binding, copy.end_binding
            copy = replace(
                copy,
                start_binding=replace(start, element_id=id_map[start.element_id])
                if start and start.element_id in id_map
                else None,
                end_binding=replace(end, element_id=id_map[end.element_id])
                if end and end.element_id in id_map
                else None,
            )
        changes[copy.id] = copy
    return changes, [id_map[e.id] for e in originals]


def set_style(document: Document, ids: Iterable[str], **fields: Any) -> Changes:
    changes: Changes = {}
    for element_id in ids:
        element = document.get(element_id)
        if element is None:
            continue
        style = replace(element.style, **fields)
        if style != element.style:
            changes[element_id] = touched(element, style=style)
    return changes


def reorder(document: Document, ids: Iterable[str], how: LayerMove) -> tuple[str, ...]:
    selected = set(ids)
    order = list(document.order)
    match how:
        case LayerMove.FRONT:
            order = [i for i in order if i not in selected] + [i for i in order if i in selected]
        case LayerMove.BACK:
            order = [i for i in order if i in selected] + [i for i in order if i not in selected]
        case LayerMove.FORWARD:
            for i in range(len(order) - 2, -1, -1):
                if order[i] in selected and order[i + 1] not in selected:
                    order[i], order[i + 1] = order[i + 1], order[i]
        case LayerMove.BACKWARD:
            for i in range(1, len(order)):
                if order[i] in selected and order[i - 1] not in selected:
                    order[i], order[i - 1] = order[i - 1], order[i]
    return tuple(order)


def group(document: Document, ids: Iterable[str]) -> Changes:
    group_id = new_id()
    changes: Changes = {}
    for element_id in ids:
        element = document.get(element_id)
        if element is not None:
            changes[element_id] = touched(element, group_ids=(*element.group_ids, group_id))
    return changes


def ungroup(document: Document, ids: Iterable[str]) -> Changes:
    changes: Changes = {}
    for element_id in ids:
        element = document.get(element_id)
        if element is not None and element.group_ids:
            changes[element_id] = touched(element, group_ids=element.group_ids[:-1])
    return changes


def set_locked(document: Document, ids: Iterable[str], locked: bool) -> Changes:
    changes: Changes = {}
    for element_id in ids:
        element = document.get(element_id)
        if element is not None and element.locked != locked:
            changes[element_id] = touched(element, locked=locked)
    return changes


def align(document: Document, ids: Iterable[str], edge: AlignEdge) -> Changes:
    elements = [e for e in (document.get(i) for i in ids) if e is not None]
    target = document.bounds_of(e.id for e in elements)
    if target is None or len(elements) < 2:
        return {}
    changes: Changes = {}
    for element in elements:
        b = element_bounds(element)
        match edge:
            case AlignEdge.LEFT:
                dx, dy = target.left - b.left, 0.0
            case AlignEdge.CENTER:
                dx, dy = target.center.x - b.center.x, 0.0
            case AlignEdge.RIGHT:
                dx, dy = target.right - b.right, 0.0
            case AlignEdge.TOP:
                dx, dy = 0.0, target.top - b.top
            case AlignEdge.MIDDLE:
                dx, dy = 0.0, target.center.y - b.center.y
            case AlignEdge.BOTTOM:
                dx, dy = 0.0, target.bottom - b.bottom
        if dx or dy:
            changes[element.id] = translated(element, dx, dy)
    return with_rebinding(document, changes)


def distribute(document: Document, ids: Iterable[str], horizontal: bool) -> Changes:
    elements = [e for e in (document.get(i) for i in ids) if e is not None]
    if len(elements) < 3:
        return {}
    boxes = sorted(
        ((element_bounds(e), e) for e in elements),
        key=lambda item: item[0].left if horizontal else item[0].top,
    )
    first, last = boxes[0][0], boxes[-1][0]
    if horizontal:
        total = last.right - first.left
        used = sum(b.width for b, _ in boxes)
    else:
        total = last.bottom - first.top
        used = sum(b.height for b, _ in boxes)
    gap = (total - used) / (len(boxes) - 1)
    cursor = first.left if horizontal else first.top
    changes: Changes = {}
    for box, element in boxes:
        if horizontal:
            dx, dy = cursor - box.left, 0.0
            cursor += box.width + gap
        else:
            dx, dy = 0.0, cursor - box.top
            cursor += box.height + gap
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            changes[element.id] = translated(element, dx, dy)
    return with_rebinding(document, changes)


def rotate(document: Document, ids: Iterable[str], center: Point, delta: float) -> Changes:
    changes: Changes = {}
    for element_id in ids:
        element = document.get(element_id)
        if element is None:
            continue
        if isinstance(element, WITH_POINTS):
            # Lines and strokes bake rotation into their points.
            points = [p.rotated(center, delta) for p in world_points(element)]
            changes[element_id] = with_world_points(element, points)
        else:
            new_center = element.center.rotated(center, delta)
            changes[element_id] = touched(
                element,
                x=new_center.x - element.width / 2,
                y=new_center.y - element.height / 2,
                angle=(element.angle + delta) % (2 * math.pi),
            )
    return with_rebinding(document, changes)


def scale(
    document: Document, ids: Iterable[str], source: Rect, target: Rect, *, scale_text: bool = True
) -> Changes:
    """Map elements from the `source` box onto the `target` box (resize)."""
    sx = target.width / source.width if source.width else 1.0
    sy = target.height / source.height if source.height else 1.0

    def map_point(p: Point) -> Point:
        return Point(target.x + (p.x - source.x) * sx, target.y + (p.y - source.y) * sy)

    changes: Changes = {}
    for element_id in ids:
        element = document.get(element_id)
        if element is None:
            continue
        if isinstance(element, WITH_POINTS):
            changes[element_id] = with_world_points(
                element, [map_point(p) for p in world_points(element)]
            )
            continue
        center = map_point(element.center)
        width = max(abs(element.width * sx), 1.0)
        height = max(abs(element.height * sy), 1.0)
        updated = touched(
            element, x=center.x - width / 2, y=center.y - height / 2, width=width, height=height
        )
        if isinstance(updated, Text):
            if scale_text:
                factor = min(abs(sx), abs(sy)) if abs(sx - sy) > 1e-6 else abs(sy)
                size = min(max(element.style.font_size * factor, MIN_FONT_SIZE), MAX_FONT_SIZE)
                updated = touched(updated, style=replace(updated.style, font_size=round(size, 1)))
            else:
                updated = touched(updated, auto_width=False)
        changes[element_id] = updated
    return with_rebinding(document, changes)
