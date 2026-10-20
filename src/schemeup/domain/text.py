"""Text layout rules that don't depend on Qt.

Measuring text needs real fonts, so it goes through the `TextMeasurer` port;
the Qt implementation lives in `rendering`. Tests use a fake measurer.
"""

from __future__ import annotations

import math
from typing import Protocol

from schemeup.domain.elements import (
    Diamond,
    Ellipse,
    LinearBase,
    ShapeBase,
    Text,
    touched,
    world_points,
)
from schemeup.domain.geometry import Point, Rect, Size, point_along
from schemeup.domain.style import FontFamily, Style, TextAlign, VerticalAlign

LABEL_PADDING = 10.0
ARROW_LABEL_MAX_WIDTH = 260.0


class TextMeasurer(Protocol):
    def measure(self, text: str, family: FontFamily, size: float, max_width: float | None) -> Size:
        """Size of `text` laid out with wrapping at `max_width` (None means no wrapping)."""
        ...


def label_area(shape: ShapeBase) -> Rect:
    """Box available for a shape's label, in local (unrotated) coordinates."""
    rect = shape.local_rect
    if isinstance(shape, Ellipse):
        w, h = rect.width / math.sqrt(2), rect.height / math.sqrt(2)
    elif isinstance(shape, Diamond):
        w, h = rect.width / 2, rect.height / 2
    else:
        w, h = rect.width, rect.height
    w = max(w - 2 * LABEL_PADDING, 1.0)
    h = max(h - 2 * LABEL_PADDING, 1.0)
    c = rect.center
    return Rect(c.x - w / 2, c.y - h / 2, w, h)


def place_block(area: Rect, size: Size, style: Style) -> Rect:
    """Where a text block of `size` sits inside `area`, following the text position."""
    match style.text_align:
        case TextAlign.LEFT:
            x = area.left
        case TextAlign.RIGHT:
            x = area.right - size.width
        case _:
            x = area.center.x - size.width / 2
    match style.vertical_align:
        case VerticalAlign.TOP:
            y = area.top
        case VerticalAlign.BOTTOM:
            y = area.bottom - size.height
        case _:
            y = area.center.y - size.height / 2
    return Rect(x, y, size.width, size.height)


def fit_text(text: Text, measurer: TextMeasurer) -> Text:
    """`text` resized to its content: width follows the text unless it wraps."""
    style = text.style
    content = text.text or " "
    if text.auto_width:
        size = measurer.measure(content, style.font_family, style.font_size, None)
        width = max(size.width, 1.0)
    else:
        width = max(text.width, style.font_size)
        size = measurer.measure(content, style.font_family, style.font_size, width)
    if abs(width - text.width) < 1e-6 and abs(size.height - text.height) < 1e-6:
        return text
    return touched(text, width=width, height=size.height)


def needed_shape_height(shape: ShapeBase, measurer: TextMeasurer) -> float:
    """Height the shape needs so its label fits, keeping its width."""
    if not shape.label:
        return shape.height
    area = label_area(shape)
    size = measurer.measure(shape.label, shape.style.font_family, shape.style.font_size, area.width)
    inner = size.height + 2 * LABEL_PADDING
    if isinstance(shape, Ellipse):
        return inner * math.sqrt(2)
    if isinstance(shape, Diamond):
        return inner * 2
    return inner


def fit_label[S: ShapeBase](shape: S, measurer: TextMeasurer) -> S:
    """`shape` grown vertically if its label doesn't fit (it never shrinks)."""
    needed = needed_shape_height(shape, measurer)
    if needed <= shape.height + 1e-6:
        return shape
    return touched(shape, height=needed)


def arrow_label_center(element: LinearBase) -> Point:
    return point_along(world_points(element), 0.5)
