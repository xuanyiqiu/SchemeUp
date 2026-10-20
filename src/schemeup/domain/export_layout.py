"""Where pages fall when an infinite canvas goes to a paged format (PDF, Word).

Frames are the natural unit: one frame, one page. Without frames the content
can be fitted onto one page or tiled at true size, and paged notes already
have their pages.
"""

from __future__ import annotations

import math
from enum import StrEnum

from schemeup.domain.document import PAGE_SIZES_MM, Document
from schemeup.domain.geometry import Rect, Size
from schemeup.domain.sheets import MM

PAGE_GAP = 40.0  # canvas units between the pages of a paged note
MARGIN_MM = 10.0


class PageLayout(StrEnum):
    FIT = "fit"  # all content scaled onto one page
    FRAMES = "frames"  # one page per frame
    TILES = "tiles"  # content at true size, cut into as many pages as needed
    PAGES = "pages"  # the pages of a paged note


def page_size(name: str, landscape: bool) -> Size:
    """Paper size in canvas units."""
    w_mm, h_mm = PAGE_SIZES_MM.get(name, PAGE_SIZES_MM["A4"])
    if landscape:
        w_mm, h_mm = h_mm, w_mm
    return Size(w_mm * MM, h_mm * MM)


def printable_size(name: str, landscape: bool) -> Size:
    paper = page_size(name, landscape)
    margin = MARGIN_MM * MM
    return Size(paper.width - 2 * margin, paper.height - 2 * margin)


def page_rects(page: str | None, landscape: bool, content_bottom: float) -> list[Rect]:
    """Pages of a paged note, stacked downwards until they cover the content.

    The first page starts one margin up and left of the origin, so content
    placed at the origin (templates, quick notes) sits inside the margins."""
    if page is None or page not in PAGE_SIZES_MM:
        return []
    size = page_size(page, landscape)
    margin = MARGIN_MM * MM
    pages = [Rect(-margin, -margin, size.width, size.height)]
    while pages[-1].bottom < content_bottom:
        pages.append(Rect(0, pages[-1].bottom + PAGE_GAP, size.width, size.height))
    return pages


def fit_scale(region: Rect, target: Size) -> float:
    """Scale that fits `region` into `target` without distortion."""
    if region.width <= 0 or region.height <= 0:
        return 1.0
    return min(target.width / region.width, target.height / region.height)


def tiles(region: Rect, tile: Size) -> list[Rect]:
    """`region` cut into tiles of `tile`, row by row."""
    columns = max(1, math.ceil(region.width / tile.width))
    rows = max(1, math.ceil(region.height / tile.height))
    return [
        Rect(region.x + c * tile.width, region.y + r * tile.height, tile.width, tile.height)
        for r in range(rows)
        for c in range(columns)
    ]


def export_regions(
    document: Document,
    layout: PageLayout,
    region: Rect | None,
    page: str,
    landscape: bool,
) -> list[Rect]:
    """The canvas areas that become pages, in order."""
    if layout == PageLayout.PAGES:
        content = document.content_bounds()
        settings = document.settings
        return page_rects(
            settings.page_size, settings.page_landscape, content.bottom if content else 0.0
        )
    if layout == PageLayout.FRAMES:
        return [f.local_rect for f in document.frames()]
    if region is None:
        return []
    if layout == PageLayout.TILES:
        return tiles(region, printable_size(page, landscape))
    return [region]


def is_infinite(document: Document) -> bool:
    """A note without pages or frames: a paged export needs the user to choose how."""
    return document.settings.page_size is None and not document.frames()
