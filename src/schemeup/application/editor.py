"""The editing session for one open note.

It owns the document, the selection, the style for new elements and the undo
history. Every edit goes through `commit`, which records a changeset and
notifies listeners (the canvas, the properties panel, autosave).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from enum import StrEnum
from typing import Any

from schemeup.domain import commands
from schemeup.domain.commands import AlignEdge, LayerMove
from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.elements import (
    LABELED,
    SHAPES,
    Element,
    ShapeBase,
    Text,
    outer_group,
    touched,
)
from schemeup.domain.export_layout import pages_of
from schemeup.domain.geometry import Point, Rect
from schemeup.domain.history import Changeset, History, Selection
from schemeup.domain.structure_edit import StructureOp, edit
from schemeup.domain.style import DEFAULT_STYLE, Style
from schemeup.domain.text import TextMeasurer, fit_label, fit_text


class Change(StrEnum):
    DOCUMENT = "document"
    SELECTION = "selection"
    STYLE = "style"


type Listener = Callable[[Change], None]


def expand_groups(document: Document, ids: Iterable[str]) -> frozenset[str]:
    """`ids` plus every element sharing their outermost group."""
    result = set(ids)
    for element_id in list(result):
        element = document.get(element_id)
        group = outer_group(element) if element is not None else None
        if group is not None:
            result.update(document.group_members(group))
    return frozenset(result)


class EditorSession:
    def __init__(
        self,
        document: Document,
        measurer: TextMeasurer,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._document = document
        self._measurer = measurer
        self._clock = clock
        self._selection: Selection = frozenset()
        self._style = DEFAULT_STYLE
        self._history = History()
        self._listeners: list[Listener] = []
        self.revision = 0  # goes up on every document change; autosave watches it

    # State

    @property
    def document(self) -> Document:
        return self._document

    @property
    def selection(self) -> Selection:
        return self._selection

    @property
    def style(self) -> Style:
        return self._style

    @property
    def measurer(self) -> TextMeasurer:
        return self._measurer

    @property
    def can_undo(self) -> bool:
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._history.can_redo

    def selected_elements(self) -> list[Element]:
        return self._document.in_z_order(self._selection)

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _notify(self, change: Change) -> None:
        for listener in list(self._listeners):
            listener(change)

    # Core operations

    def load(self, document: Document) -> None:
        self._document = document
        self._selection = frozenset()
        self._history.clear()
        self.revision += 1
        self._notify(Change.DOCUMENT)
        self._notify(Change.SELECTION)

    def commit(
        self,
        changes: Mapping[str, Element | None],
        label: str,
        *,
        order: tuple[str, ...] | None = None,
        settings: CanvasSettings | None = None,
        selection: Iterable[str] | None = None,
        merge_key: str | None = None,
    ) -> None:
        changeset = Changeset.between(label, self._document, changes, order, settings)
        before = self._selection
        document = changeset.apply(self._document)
        if selection is not None:
            after = frozenset(i for i in selection if i in document.elements)
        else:
            after = frozenset(i for i in before if i in document.elements)
        if not changeset.is_empty:
            self._history.record(changeset, before, after, merge_key, self._clock())
            self._document = document
            self.revision += 1
            self._notify(Change.DOCUMENT)
        if after != before:
            self._selection = after
            self._notify(Change.SELECTION)

    def select(self, ids: Iterable[str]) -> None:
        selection = frozenset(i for i in ids if i in self._document.elements)
        if selection != self._selection:
            self._selection = selection
            self._notify(Change.SELECTION)

    def select_all(self) -> None:
        self.select(e.id for e in self._document.ordered() if not e.locked)

    def undo(self) -> None:
        result = self._history.undo(self._document)
        if result is not None:
            self._apply_history(*result)

    def redo(self) -> None:
        result = self._history.redo(self._document)
        if result is not None:
            self._apply_history(*result)

    def _apply_history(self, document: Document, selection: Selection) -> None:
        self._document = document
        self._selection = frozenset(i for i in selection if i in document.elements)
        self.revision += 1
        self._notify(Change.DOCUMENT)
        self._notify(Change.SELECTION)

    # Style

    def set_style(self, **fields: Any) -> None:
        """Change the style for new elements and apply it to the selection."""
        self._style = replace(self._style, **fields)
        self._notify(Change.STYLE)
        if not self._selection:
            return
        changes = commands.set_style(self._document, self._selection, **fields)
        changes = self.refit(changes)
        key = "style:" + ",".join(sorted(fields))
        self.commit(commands.with_rebinding(self._document, changes), "Change style", merge_key=key)

    def adopt_style(self, style: Style) -> None:
        """Make `style` the style for new elements without touching the selection."""
        if style != self._style:
            self._style = style
            self._notify(Change.STYLE)

    def refit(self, changes: Mapping[str, Element | None]) -> dict[str, Element | None]:
        """Resize text elements and labelled shapes so their text still fits."""
        result: dict[str, Element | None] = {}
        for element_id, element in changes.items():
            if isinstance(element, Text):
                element = fit_text(element, self._measurer)
            elif isinstance(element, SHAPES):
                element = fit_label(element, self._measurer)
            result[element_id] = element
        return result

    # Element operations

    def add(self, elements: Iterable[Element], label: str = "Add", select: bool = True) -> None:
        items = list(elements)
        changes: dict[str, Element | None] = {e.id: e for e in items}
        changes = self.refit(changes)
        document = self._document.with_elements(changes)
        changes.update(commands.assign_frames(document, (e.id for e in items)))
        selection = [e.id for e in items] if select else None
        self.commit(changes, label, selection=selection)

    def set_text(self, element_id: str, text: str) -> None:
        """Commit edited text: the content of a text element or a shape's label."""
        element = self._document.get(element_id)
        if element is None:
            return
        if isinstance(element, Text):
            if not text.strip():
                self.commit(commands.delete(self._document, [element_id]), "Delete text")
                return
            if text == element.text:
                return
            updated: Element = fit_text(touched(element, text=text), self._measurer)
        elif isinstance(element, LABELED):
            if text == element.label:
                return
            updated = touched(element, label=text)
            if isinstance(updated, ShapeBase):
                updated = fit_label(updated, self._measurer)
        else:
            return
        changes = commands.with_rebinding(self._document, {element_id: updated})
        self.commit(changes, "Edit text")

    def delete_selection(self) -> None:
        if self._selection:
            self.commit(commands.delete(self._document, self._selection), "Delete", selection=())

    def duplicate_selection(self) -> None:
        if not self._selection:
            return
        changes, new_ids = commands.duplicate(self._document, self._selection)
        self.commit(changes, "Duplicate", selection=new_ids)

    def paste(self, elements: list[Element], center: Point | None) -> None:
        """Insert copies of `elements`, centered on `center` when given."""
        if not elements:
            return
        source = Document.of(elements)
        offset = Point(16.0, 16.0)
        bounds = source.content_bounds()
        if center is not None and bounds is not None:
            offset = center - bounds.center
        changes, new_ids = commands.duplicate(source, source.order, offset)
        changes = dict(changes)
        changes.update(commands.assign_frames(self._document.with_elements(changes), new_ids))
        self.commit(changes, "Paste", selection=new_ids)

    def move_selection(self, dx: float, dy: float, merge_key: str | None = "nudge") -> None:
        if self._selection:
            self.commit(
                commands.move(self._document, self._selection, dx, dy), "Move", merge_key=merge_key
            )

    def reorder_selection(self, how: LayerMove) -> None:
        if self._selection:
            self.commit({}, "Reorder", order=commands.reorder(self._document, self._selection, how))

    def group_selection(self) -> None:
        if len(self._selection) > 1:
            self.commit(commands.group(self._document, self._selection), "Group")

    def ungroup_selection(self) -> None:
        if self._selection:
            self.commit(commands.ungroup(self._document, self._selection), "Ungroup")

    def toggle_lock_selection(self) -> None:
        elements = self.selected_elements()
        if not elements:
            return
        lock = not all(e.locked for e in elements)
        self.commit(
            commands.set_locked(self._document, self._selection, lock),
            "Lock" if lock else "Unlock",
            selection=() if lock else None,
        )

    def unlock_all(self) -> None:
        locked = [e.id for e in self._document.ordered() if e.locked]
        if locked:
            self.commit(
                commands.set_locked(self._document, locked, False), "Unlock", selection=locked
            )

    def align_selection(self, edge: AlignEdge) -> None:
        if len(self._selection) > 1:
            self.commit(commands.align(self._document, self._selection, edge), "Align")

    def distribute_selection(self, horizontal: bool) -> None:
        if len(self._selection) > 2:
            self.commit(
                commands.distribute(self._document, self._selection, horizontal), "Distribute"
            )

    def edit_structure(self, node_id: str, op: StructureOp) -> str | None:
        """Add or remove a part of a data structure, redrawing it in place as one change.

        Returns the new value shape, so its text can be typed straight away, or None when
        nothing was added (or the structure could not be edited)."""
        result = edit(self._document, node_id, op)
        if result is None:
            return None
        changes = commands.delete(self._document, result.remove)
        changes.update({e.id: e for e in result.add})
        changes = self.refit(changes)
        self.commit(changes, "Edit structure", selection=[e.id for e in result.add])
        return result.focus

    def add_page(self) -> Rect | None:
        """Append an empty page to a paged note and return it (None for an infinite canvas)."""
        pages = pages_of(self._document)
        if not pages:
            return None
        settings = replace(self._document.settings, page_count=len(pages) + 1)
        self.commit({}, "Add page", settings=settings)
        return pages_of(self._document)[-1]

    def set_canvas_settings(self, settings: CanvasSettings) -> None:
        if settings != self._document.settings:
            self.commit({}, "Canvas settings", settings=settings, merge_key="canvas")
