"""Undo and redo.

Every edit becomes a `Changeset` holding the before and after state of the
elements it touched. Undo applies `before`, redo applies `after`, so there is
no hand-written inverse per command that could go out of sync.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from schemeup.domain.document import CanvasSettings, Document
from schemeup.domain.elements import Element

type Selection = frozenset[str]


@dataclass(frozen=True, slots=True)
class Changeset:
    label: str
    before: Mapping[str, Element | None]
    after: Mapping[str, Element | None]
    order_before: tuple[str, ...] | None = None
    order_after: tuple[str, ...] | None = None
    settings_before: CanvasSettings | None = None
    settings_after: CanvasSettings | None = None

    @staticmethod
    def between(
        label: str,
        document: Document,
        changes: Mapping[str, Element | None],
        order: tuple[str, ...] | None = None,
        settings: CanvasSettings | None = None,
    ) -> Changeset:
        return Changeset(
            label=label,
            before={i: document.get(i) for i in changes},
            after=dict(changes),
            order_before=document.order if order is not None else None,
            order_after=order,
            settings_before=document.settings if settings is not None else None,
            settings_after=settings,
        )

    @property
    def is_empty(self) -> bool:
        same_elements = all(self.before.get(i) is e for i, e in self.after.items())
        return (
            same_elements
            and self.order_before == self.order_after
            and self.settings_before == self.settings_after
        )

    def apply(self, document: Document) -> Document:
        return _transition(document, self.after, self.order_after, self.settings_after)

    def revert(self, document: Document) -> Document:
        return _transition(document, self.before, self.order_before, self.settings_before)

    def merged_with(self, later: Changeset) -> Changeset:
        before = dict(later.before)
        before.update(self.before)
        after = dict(self.after)
        after.update(later.after)
        return Changeset(
            label=self.label,
            before=before,
            after=after,
            order_before=self.order_before if self.order_before is not None else later.order_before,
            order_after=later.order_after if later.order_after is not None else self.order_after,
            settings_before=(
                self.settings_before if self.settings_before is not None else later.settings_before
            ),
            settings_after=(
                later.settings_after if later.settings_after is not None else self.settings_after
            ),
        )


def _transition(
    document: Document,
    elements: Mapping[str, Element | None],
    order: tuple[str, ...] | None,
    settings: CanvasSettings | None,
) -> Document:
    result = document.with_elements(elements, order)
    return result.with_settings(settings) if settings is not None else result


@dataclass(slots=True)
class _Entry:
    changeset: Changeset
    selection_before: Selection
    selection_after: Selection
    merge_key: str | None
    time: float


@dataclass(slots=True)
class History:
    merge_window: float = 1.0  # seconds within which edits with the same key merge
    _undo: list[_Entry] = field(default_factory=list)
    _redo: list[_Entry] = field(default_factory=list)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def record(
        self,
        changeset: Changeset,
        selection_before: Selection,
        selection_after: Selection,
        merge_key: str | None = None,
        now: float = 0.0,
    ) -> None:
        if changeset.is_empty:
            return
        self._redo.clear()
        last = self._undo[-1] if self._undo else None
        if (
            last is not None
            and merge_key is not None
            and last.merge_key == merge_key
            and now - last.time <= self.merge_window
        ):
            last.changeset = last.changeset.merged_with(changeset)
            last.selection_after = selection_after
            last.time = now
            return
        self._undo.append(_Entry(changeset, selection_before, selection_after, merge_key, now))

    def undo(self, document: Document) -> tuple[Document, Selection] | None:
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(entry)
        return entry.changeset.revert(document), entry.selection_before

    def redo(self, document: Document) -> tuple[Document, Selection] | None:
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(entry)
        return entry.changeset.apply(document), entry.selection_after

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
