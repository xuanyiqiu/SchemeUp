"""The canvas document: elements in z-order plus canvas settings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from schemeup.domain.elements import (
    LABELED,
    Arrow,
    Element,
    Frame,
    Text,
    element_bounds,
)
from schemeup.domain.geometry import Rect, union_all

PAGE_SIZES_MM = {"A4": (210.0, 297.0), "A5": (148.0, 210.0), "Letter": (215.9, 279.4)}


@dataclass(frozen=True, slots=True)
class CanvasSettings:
    background: str = "#ffffff"
    sheet: str = "grid-5"
    line_spacing_mm: float = 8.0  # used by the "lines" sheet
    page_size: str | None = None  # None for an infinite canvas, else a key of PAGE_SIZES_MM
    page_landscape: bool = False


@dataclass(frozen=True, slots=True)
class Document:
    elements: Mapping[str, Element] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    settings: CanvasSettings = CanvasSettings()
    # Bounds of everything, filled on first use. Documents never change after
    # creation, so the union over every element is computed once per version
    # instead of once per repaint.
    _bounds: list[Rect | None] = field(default_factory=list, init=False, repr=False, compare=False)

    @staticmethod
    def of(elements: Iterable[Element], settings: CanvasSettings | None = None) -> Document:
        items = list(elements)
        return Document(
            {e.id: e for e in items}, tuple(e.id for e in items), settings or CanvasSettings()
        )

    def __len__(self) -> int:
        return len(self.order)

    def get(self, element_id: str) -> Element | None:
        return self.elements.get(element_id)

    def ordered(self) -> list[Element]:
        return [self.elements[i] for i in self.order]

    def z_index(self) -> dict[str, int]:
        return {element_id: i for i, element_id in enumerate(self.order)}

    def in_z_order(self, ids: Iterable[str]) -> list[Element]:
        index = self.z_index()
        wanted = sorted((i for i in ids if i in index), key=index.__getitem__)
        return [self.elements[i] for i in wanted]

    def with_elements(
        self, changes: Mapping[str, Element | None], order: tuple[str, ...] | None = None
    ) -> Document:
        """A new document with elements added, replaced (Element) or removed (None).

        New elements go on top unless an explicit `order` is given."""
        elements = dict(self.elements)
        new_order = list(self.order) if order is None else list(order)
        removed: set[str] = set()
        for element_id, element in changes.items():
            if element is None:
                elements.pop(element_id, None)
                removed.add(element_id)
            else:
                if element_id not in elements and order is None:
                    new_order.append(element_id)
                elements[element_id] = element
        if removed and order is None:
            new_order = [i for i in new_order if i not in removed]
        return Document(elements, tuple(i for i in new_order if i in elements), self.settings)

    def with_settings(self, settings: CanvasSettings) -> Document:
        return replace(self, settings=settings)

    def content_bounds(self) -> Rect | None:
        if not self._bounds:
            self._bounds.append(union_all(element_bounds(e) for e in self.elements.values()))
        return self._bounds[0]

    def bounds_of(self, ids: Iterable[str]) -> Rect | None:
        return union_all(element_bounds(self.elements[i]) for i in ids if i in self.elements)

    def frames(self) -> list[Frame]:
        return [e for e in self.ordered() if isinstance(e, Frame)]

    def children_of(self, frame_id: str) -> list[Element]:
        return [e for e in self.ordered() if e.frame_id == frame_id]

    def arrows_bound_to(self, ids: Iterable[str]) -> list[Arrow]:
        targets = set(ids)
        result: list[Arrow] = []
        for e in self.elements.values():
            if not isinstance(e, Arrow):
                continue
            start, end = e.start_binding, e.end_binding
            if (start and start.element_id in targets) or (end and end.element_id in targets):
                result.append(e)
        return result

    def group_members(self, group_id: str) -> list[str]:
        return [e.id for e in self.ordered() if group_id in e.group_ids]

    def plain_text(self) -> str:
        """All text and labels in reading order (top to bottom, then left to right)."""
        pieces: list[tuple[float, float, str]] = []
        for e in self.elements.values():
            if isinstance(e, Text) and e.text.strip():
                pieces.append((e.y, e.x, e.text.strip()))
            elif isinstance(e, LABELED) and e.label.strip():
                box = element_bounds(e)
                pieces.append((box.top, box.left, e.label.strip()))
            elif isinstance(e, Frame) and e.name.strip():
                pieces.append((e.y, e.x, e.name.strip()))
        pieces.sort(key=lambda item: (round(item[0] / 24), item[1]))
        return "\n".join(text for _, _, text in pieces)
