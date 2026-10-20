"""Painting a region of the canvas onto any device: images, SVG, PDF pages, thumbnails."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from schemeup.domain.document import Document
from schemeup.domain.elements import render_bounds
from schemeup.domain.geometry import Rect
from schemeup.rendering.scene import SceneRenderer


def elements_in(document: Document, region: Rect, only: frozenset[str] | None = None) -> list:  # type: ignore[type-arg]
    return [
        e
        for e in document.ordered()
        if (only is None or e.id in only) and render_bounds(e).intersects(region)
    ]


def render_region(
    painter: QPainter,
    document: Document,
    region: Rect,
    renderer: SceneRenderer,
    target: QRectF,
    *,
    dark: bool = False,
    background: bool = True,
    only: frozenset[str] | None = None,
) -> float:
    """Draw `region` of the canvas scaled into `target`; returns the scale used."""
    scale = (
        min(target.width() / region.width, target.height() / region.height)
        if region.width and region.height
        else 1.0
    )
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if background:
        painter.fillRect(target, renderer.color(document.settings.background, dark))
    painter.setClipRect(target)
    dx = target.left() + (target.width() - region.width * scale) / 2
    dy = target.top() + (target.height() - region.height * scale) / 2
    painter.translate(dx, dy)
    painter.scale(scale, scale)
    painter.translate(-region.x, -region.y)
    renderer.paint(
        painter,
        document,
        elements_in(document, region, only),
        dark=dark,
        background=document.settings.background,
    )
    painter.restore()
    return scale


def render_image(
    document: Document,
    region: Rect,
    renderer: SceneRenderer,
    scale: float = 2.0,
    *,
    dark: bool = False,
    background: bool = True,
    only: frozenset[str] | None = None,
) -> QImage:
    width = max(1, round(region.width * scale))
    height = max(1, round(region.height * scale))
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0) if not background else Qt.GlobalColor.white)
    painter = QPainter(image)
    render_region(
        painter,
        document,
        region,
        renderer,
        QRectF(0, 0, width, height),
        dark=dark,
        background=background,
        only=only,
    )
    painter.end()
    return image


def export_region(
    document: Document, selection: frozenset[str], padding: float = 24.0
) -> Rect | None:
    """The area to export: the selection if there is one, otherwise all the content."""
    bounds = document.bounds_of(selection) if selection else document.content_bounds()
    if bounds is None:
        return None
    if selection:
        boxes = [render_bounds(e) for e in document.ordered() if e.id in selection]
    else:
        boxes = [render_bounds(e) for e in document.ordered()]
    tight = boxes[0]
    for box in boxes[1:]:
        tight = tight.union(box)
    # Render bounds include room for arrowheads and labels; trim back towards the
    # geometric bounds so exports don't carry a wide empty border.
    left = max(tight.left, bounds.left - 30)
    top = max(tight.top, bounds.top - 30)
    right = min(tight.right, bounds.right + 30)
    bottom = min(tight.bottom, bounds.bottom + 30)
    return Rect(left, top, right - left, bottom - top).inflated(padding)
