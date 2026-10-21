"""Where pages fall when an infinite canvas goes to a paged format (PDF, Word).

Frames are the natural unit: one frame, one page. Without frames the content
can be fitted onto one page or tiled at true size, and paged notes already
have their pages.
"""

from __future__ import annotations

import math
from enum import StrEnum

from schemeup.domain.document import PAGE_SIZES_MM, Document
from schemeup.domain.elements import Element, element_bounds
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


def page_rects(
    page: str | None, landscape: bool, content_bottom: float, minimum: int = 1
) -> list[Rect]:
    """Pages of a paged note, stacked downwards until they cover the content.

    There are always at least `minimum` pages. The first page starts one margin up
    and left of the origin, so content placed at the origin (templates, quick
    notes) sits inside the margins."""
    if page is None or page not in PAGE_SIZES_MM:
        return []
    size = page_size(page, landscape)
    margin = MARGIN_MM * MM
    pages = [Rect(-margin, -margin, size.width, size.height)]
    while len(pages) < minimum or pages[-1].bottom < content_bottom:
        pages.append(Rect(-margin, pages[-1].bottom + PAGE_GAP, size.width, size.height))
    return pages


def pages_of(document: Document, extra_bottom: float | None = None) -> list[Rect]:
    """The pages of a paged note (none for an infinite canvas).

    A new page appears when content passes the bottom of the last one, like in a
    word processor. Only content in the page column counts, so something dragged
    far to the side does not add pages. `extra_bottom` is for content not yet in the
    document, such as the text being typed."""
    settings = document.settings
    if settings.page_size is None:
        return []

    def compute() -> list[Rect]:
        column = page_rects(settings.page_size, settings.page_landscape, 0.0)[0]
        bottom = 0.0
        for element in document.elements.values():
            box = element_bounds(element)
            if box.right > column.left and box.left < column.right:
                bottom = max(bottom, box.bottom)
        return page_rects(settings.page_size, settings.page_landscape, bottom, settings.page_count)

    pages = document.cached("pages", compute)
    if extra_bottom is not None and extra_bottom > pages[-1].bottom:
        return page_rects(
            settings.page_size, settings.page_landscape, extra_bottom, settings.page_count
        )
    return pages


def touches_pages(element: Element, pages: list[Rect]) -> bool:
    box = element_bounds(element)
    return any(box.intersects(page) for page in pages)


def off_page_ids(document: Document) -> frozenset[str]:
    """Elements that touch no page of a paged note. They stay in the note but are not
    part of its pages: not exported and not searched. Empty for an infinite canvas."""

    def compute() -> frozenset[str]:
        pages = pages_of(document)
        if not pages:
            return frozenset()
        return frozenset(e.id for e in document.elements.values() if not touches_pages(e, pages))

    return document.cached("off_page", compute)


def searchable_text(document: Document) -> str:
    """The text that counts: everything on an infinite canvas, only the pages' otherwise."""
    off = off_page_ids(document)
    return document.plain_text(only=set(document.elements) - off if off else None)


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
        return pages_of(document)
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
