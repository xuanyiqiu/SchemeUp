"""A uniform grid hash for finding elements near a point or inside an area.

The world is cut into square cells and every element is registered in each
cell its bounds touch. Very large elements go into a separate list that
every query checks, so they don't fill hundreds of cells.
"""

from __future__ import annotations

import math
from collections import defaultdict

from schemeup.domain.document import Document
from schemeup.domain.elements import Element, render_bounds
from schemeup.domain.geometry import Rect

MAX_CELLS = 64


class SpatialHash:
    def __init__(self, cell_size: float = 512.0) -> None:
        self._cell = cell_size
        self._cells: defaultdict[tuple[int, int], set[str]] = defaultdict(set)
        self._where: dict[str, list[tuple[int, int]]] = {}
        self._oversized: set[str] = set()
        self._elements: dict[str, Element] = {}

    def __len__(self) -> int:
        return len(self._elements)

    def _cells_for(self, rect: Rect) -> list[tuple[int, int]]:
        x0, x1 = math.floor(rect.left / self._cell), math.floor(rect.right / self._cell)
        y0, y1 = math.floor(rect.top / self._cell), math.floor(rect.bottom / self._cell)
        return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    def insert(self, element: Element) -> None:
        self.remove(element.id)
        self._elements[element.id] = element
        bounds = render_bounds(element)
        cols = math.floor(bounds.right / self._cell) - math.floor(bounds.left / self._cell) + 1
        rows = math.floor(bounds.bottom / self._cell) - math.floor(bounds.top / self._cell) + 1
        if cols * rows > MAX_CELLS:
            self._oversized.add(element.id)
            return
        cells = self._cells_for(bounds)
        for cell in cells:
            self._cells[cell].add(element.id)
        self._where[element.id] = cells

    def remove(self, element_id: str) -> None:
        self._elements.pop(element_id, None)
        self._oversized.discard(element_id)
        for cell in self._where.pop(element_id, []):
            bucket = self._cells.get(cell)
            if bucket is not None:
                bucket.discard(element_id)
                if not bucket:
                    del self._cells[cell]

    def query(self, rect: Rect) -> set[str]:
        """Ids of elements whose render bounds may intersect `rect`."""
        found = set(self._oversized)
        for cell in self._cells_for(rect):
            bucket = self._cells.get(cell)
            if bucket:
                found |= bucket
        return found

    def sync(self, document: Document) -> None:
        """Bring the index in line with `document`, touching only what changed."""
        current = document.elements
        for element_id in list(self._elements):
            if element_id not in current:
                self.remove(element_id)
        for element_id, element in current.items():
            if self._elements.get(element_id) is not element:
                self.insert(element)
