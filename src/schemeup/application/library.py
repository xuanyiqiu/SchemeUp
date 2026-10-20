"""Use cases for the note library: folders, notes, tags, boards, search, calendar.

The service validates input, builds documents from templates, stamps times
from the clock and publishes an event after every change, so the explorer,
the boards and the calendar can refresh from the single source of truth.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from schemeup.domain.document import Document
from schemeup.domain.elements import SHAPES, Element, Text
from schemeup.domain.errors import ConflictError
from schemeup.domain.library import (
    INBOX,
    Activity,
    Board,
    Card,
    Column,
    Folder,
    NoteInfo,
    SearchHit,
    Tag,
    to_millis,
)
from schemeup.domain.templates import TEMPLATES_BY_ID, quick_note
from schemeup.domain.text import TextMeasurer, fit_label, fit_text

TRASH_DAYS = 30


class LibraryRepository(Protocol):
    def root_folder(self) -> Folder: ...
    def folders(self, include_trashed: bool = False) -> list[Folder]: ...
    def folder(self, folder_id: int) -> Folder: ...
    def find_folder(self, parent_id: int, name: str) -> Folder | None: ...
    def create_folder(self, parent_id: int, name: str, at: int) -> Folder: ...
    def rename_folder(self, folder_id: int, name: str) -> None: ...
    def move_folder(self, folder_id: int, parent_id: int) -> None: ...
    def trash_folder(self, folder_id: int, at: int) -> None: ...
    def restore_folder(self, folder_id: int) -> None: ...
    def delete_folder_forever(self, folder_id: int) -> None: ...
    def notes(self, folder_id: int | None = None) -> list[NoteInfo]: ...
    def note(self, note_id: int) -> NoteInfo: ...
    def create_note(self, folder_id: int, title: str, document: Document, at: int) -> NoteInfo: ...
    def load_document(self, note_id: int) -> Document: ...
    def save_document(self, note_id: int, document: Document, at: int) -> None: ...
    def rename_note(self, note_id: int, title: str, at: int) -> None: ...
    def move_note(self, note_id: int, folder_id: int) -> None: ...
    def trash_note(self, note_id: int, at: int) -> None: ...
    def restore_note(self, note_id: int) -> None: ...
    def delete_note_forever(self, note_id: int) -> None: ...
    def trashed_notes(self) -> list[NoteInfo]: ...
    def trashed_folders(self) -> list[Folder]: ...
    def empty_trash(self, older_than: int | None = None) -> int: ...
    def search(self, text: str, limit: int = 50) -> list[SearchHit]: ...
    def tags(self) -> list[Tag]: ...
    def set_note_tags(self, note_id: int, names: Iterable[str]) -> None: ...
    def notes_with_tag(self, name: str) -> list[NoteInfo]: ...
    def boards(self) -> list[Board]: ...
    def board(self, board_id: int) -> Board: ...
    def create_board(self, name: str, columns: Iterable[str], at: int) -> Board: ...
    def rename_board(self, board_id: int, name: str) -> None: ...
    def delete_board(self, board_id: int) -> None: ...
    def columns(self, board_id: int) -> list[Column]: ...
    def add_column(self, board_id: int, name: str) -> Column: ...
    def rename_column(self, column_id: int, name: str) -> None: ...
    def delete_column(self, column_id: int) -> None: ...
    def move_column(self, board_id: int, column_id: int, index: int) -> None: ...
    def cards(self, board_id: int) -> list[Card]: ...
    def move_card(
        self, board_id: int, note_id: int, column_id: int, index: int | None = None
    ) -> None: ...
    def remove_card(self, board_id: int, note_id: int) -> None: ...
    def boards_for_note(self, note_id: int) -> list[Board]: ...
    def notes_created_between(self, start: int, end: int) -> list[NoteInfo]: ...
    def activity_between(self, first_day: str, last_day: str) -> list[Activity]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


class EventKind(StrEnum):
    NOTES = "notes"  # notes created, renamed, moved, trashed, restored
    FOLDERS = "folders"
    CONTENT = "content"  # a note's document was saved
    TAGS = "tags"
    BOARDS = "boards"


@dataclass(frozen=True, slots=True)
class LibraryEvent:
    kind: EventKind
    note_id: int | None = None


class EventBus:
    """A synchronous publish/subscribe list. Handlers run in subscription order."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[LibraryEvent], None]] = []

    def subscribe(self, handler: Callable[[LibraryEvent], None]) -> None:
        self._handlers.append(handler)

    def publish(self, event: LibraryEvent) -> None:
        for handler in list(self._handlers):
            handler(event)


def fit_document(document: Document, measurer: TextMeasurer) -> Document:
    """Size every text element and labelled shape to its text (templates come unsized)."""
    changes: dict[str, Element | None] = {}
    for element in document.ordered():
        if isinstance(element, Text):
            changes[element.id] = fit_text(element, measurer)
        elif isinstance(element, SHAPES) and element.label:
            changes[element.id] = fit_label(element, measurer)
    return document.with_elements(changes) if changes else document


@dataclass(frozen=True, slots=True)
class CalendarDay:
    day: date
    created: tuple[NoteInfo, ...]
    edited: tuple[NoteInfo, ...]  # edited that day but created earlier

    @property
    def count(self) -> int:
        return len(self.created) + len(self.edited)


class LibraryService:
    def __init__(
        self,
        repository: LibraryRepository,
        measurer: TextMeasurer,
        clock: Clock | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repository
        self._measurer = measurer
        self._clock = clock or SystemClock()
        self.events = events or EventBus()

    def _now(self) -> int:
        return to_millis(self._clock.now())

    def _publish(self, kind: EventKind, note_id: int | None = None) -> None:
        self.events.publish(LibraryEvent(kind, note_id))

    # Folders

    def root(self) -> Folder:
        return self._repo.root_folder()

    def folders(self) -> list[Folder]:
        return self._repo.folders()

    def folder(self, folder_id: int) -> Folder:
        return self._repo.folder(folder_id)

    def inbox(self) -> Folder:
        root = self._repo.root_folder()
        existing = self._repo.find_folder(root.id, INBOX)
        if existing is not None:
            return existing
        folder = self._repo.create_folder(root.id, INBOX, self._now())
        self._publish(EventKind.FOLDERS)
        return folder

    def create_folder(self, parent_id: int | None, name: str) -> Folder:
        name = name.strip()
        if not name:
            raise ConflictError("folders need a name")
        parent = parent_id if parent_id is not None else self._repo.root_folder().id
        folder = self._repo.create_folder(
            parent, self._unique_folder_name(parent, name), self._now()
        )
        self._publish(EventKind.FOLDERS)
        return folder

    def _unique_folder_name(self, parent_id: int, name: str) -> str:
        candidate, n = name, 2
        while self._repo.find_folder(parent_id, candidate) is not None:
            candidate = f"{name} {n}"
            n += 1
        return candidate

    def rename_folder(self, folder_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ConflictError("folders need a name")
        self._repo.rename_folder(folder_id, name)
        self._publish(EventKind.FOLDERS)

    def move_folder(self, folder_id: int, parent_id: int) -> None:
        if folder_id == parent_id:
            return
        self._repo.move_folder(folder_id, parent_id)
        self._publish(EventKind.FOLDERS)

    def trash_folder(self, folder_id: int) -> None:
        self._repo.trash_folder(folder_id, self._now())
        self._publish(EventKind.FOLDERS)
        self._publish(EventKind.NOTES)

    # Notes

    def notes(self, folder_id: int | None = None) -> list[NoteInfo]:
        return self._repo.notes(folder_id)

    def note(self, note_id: int) -> NoteInfo:
        return self._repo.note(note_id)

    def create_note(
        self, folder_id: int | None = None, template_id: str = "blank", title: str | None = None
    ) -> NoteInfo:
        now = self._clock.now()
        template = TEMPLATES_BY_ID.get(template_id, TEMPLATES_BY_ID["blank"])
        document = fit_document(template.build(now), self._measurer)
        folder = folder_id if folder_id is not None else self.inbox().id
        note = self._repo.create_note(
            folder, (title or now.strftime(template.title)).strip(), document, to_millis(now)
        )
        self._publish(EventKind.NOTES, note.id)
        return note

    def capture(self, text: str, title: str | None = None) -> NoteInfo | None:
        """Quick capture: a note in the Inbox holding `text`. Empty text creates nothing."""
        if not text.strip():
            return None
        now = self._clock.now()
        document = fit_document(quick_note(text.rstrip()), self._measurer)
        name = (title or "").strip() or now.strftime("Quick note %Y-%m-%d %H:%M")
        note = self._repo.create_note(self.inbox().id, name, document, to_millis(now))
        self._publish(EventKind.NOTES, note.id)
        return note

    def import_document(
        self, title: str, document: Document, folder_id: int | None = None
    ) -> NoteInfo:
        """Store an existing document as a new note (welcome note, imported files)."""
        folder = folder_id if folder_id is not None else self.inbox().id
        fitted = fit_document(document, self._measurer)
        note = self._repo.create_note(folder, title.strip() or "Imported note", fitted, self._now())
        self._publish(EventKind.NOTES, note.id)
        return note

    def open_document(self, note_id: int) -> Document:
        return self._repo.load_document(note_id)

    def save_document(self, note_id: int, document: Document) -> None:
        self._repo.save_document(note_id, document, self._now())
        self._publish(EventKind.CONTENT, note_id)

    def rename_note(self, note_id: int, title: str) -> None:
        title = title.strip()
        if not title or title == self._repo.note(note_id).title:
            return
        self._repo.rename_note(note_id, title, self._now())
        self._publish(EventKind.NOTES, note_id)

    def move_note(self, note_id: int, folder_id: int) -> None:
        if self._repo.note(note_id).folder_id != folder_id:
            self._repo.move_note(note_id, folder_id)
            self._publish(EventKind.NOTES, note_id)

    def duplicate_note(self, note_id: int) -> NoteInfo:
        original = self._repo.note(note_id)
        document = self._repo.load_document(note_id)
        copy = self._repo.create_note(
            original.folder_id, f"{original.title} (copy)", document, self._now()
        )
        if original.tags:
            self._repo.set_note_tags(copy.id, original.tags)
        self._publish(EventKind.NOTES, copy.id)
        return self._repo.note(copy.id)

    def trash_note(self, note_id: int) -> None:
        self._repo.trash_note(note_id, self._now())
        self._publish(EventKind.NOTES, note_id)

    def restore_note(self, note_id: int) -> None:
        self._repo.restore_note(note_id)
        self._publish(EventKind.NOTES, note_id)

    def restore_folder(self, folder_id: int) -> None:
        self._repo.restore_folder(folder_id)
        self._publish(EventKind.FOLDERS)
        self._publish(EventKind.NOTES)

    def delete_note_forever(self, note_id: int) -> None:
        self._repo.delete_note_forever(note_id)
        self._publish(EventKind.NOTES, note_id)

    def delete_folder_forever(self, folder_id: int) -> None:
        self._repo.delete_folder_forever(folder_id)
        self._publish(EventKind.FOLDERS)
        self._publish(EventKind.NOTES)

    def trash(self) -> tuple[list[Folder], list[NoteInfo]]:
        return self._repo.trashed_folders(), self._repo.trashed_notes()

    def empty_trash(self) -> int:
        removed = self._repo.empty_trash()
        self._publish(EventKind.FOLDERS)
        self._publish(EventKind.NOTES)
        return removed

    def purge_old_trash(self) -> int:
        cutoff = self._clock.now() - timedelta(days=TRASH_DAYS)
        removed = self._repo.empty_trash(to_millis(cutoff))
        if removed:
            self._publish(EventKind.NOTES)
        return removed

    def search(self, text: str, limit: int = 50) -> list[SearchHit]:
        return self._repo.search(text, limit)

    # Tags

    def tags(self) -> list[Tag]:
        return self._repo.tags()

    def set_tags(self, note_id: int, names: Iterable[str]) -> None:
        self._repo.set_note_tags(note_id, names)
        self._publish(EventKind.TAGS, note_id)

    def notes_with_tag(self, name: str) -> list[NoteInfo]:
        return self._repo.notes_with_tag(name)

    # Boards

    def boards(self) -> list[Board]:
        return self._repo.boards()

    def create_board(self, name: str, columns: Iterable[str] = ("To do", "Doing", "Done")) -> Board:
        board = self._repo.create_board(name.strip() or "Board", columns, self._now())
        self._publish(EventKind.BOARDS)
        return board

    def rename_board(self, board_id: int, name: str) -> None:
        if name.strip():
            self._repo.rename_board(board_id, name.strip())
            self._publish(EventKind.BOARDS)

    def delete_board(self, board_id: int) -> None:
        self._repo.delete_board(board_id)
        self._publish(EventKind.BOARDS)

    def columns(self, board_id: int) -> list[Column]:
        return self._repo.columns(board_id)

    def add_column(self, board_id: int, name: str) -> Column:
        column = self._repo.add_column(board_id, name.strip() or "Column")
        self._publish(EventKind.BOARDS)
        return column

    def rename_column(self, column_id: int, name: str) -> None:
        if name.strip():
            self._repo.rename_column(column_id, name.strip())
            self._publish(EventKind.BOARDS)

    def delete_column(self, column_id: int) -> None:
        self._repo.delete_column(column_id)
        self._publish(EventKind.BOARDS)

    def move_column(self, board_id: int, column_id: int, index: int) -> None:
        self._repo.move_column(board_id, column_id, index)
        self._publish(EventKind.BOARDS)

    def cards(self, board_id: int) -> list[Card]:
        return self._repo.cards(board_id)

    def place_card(
        self, board_id: int, note_id: int, column_id: int, index: int | None = None
    ) -> None:
        self._repo.move_card(board_id, note_id, column_id, index)
        self._publish(EventKind.BOARDS, note_id)

    def remove_card(self, board_id: int, note_id: int) -> None:
        self._repo.remove_card(board_id, note_id)
        self._publish(EventKind.BOARDS, note_id)

    def boards_for_note(self, note_id: int) -> list[Board]:
        return self._repo.boards_for_note(note_id)

    # Calendar

    def calendar(self, first: date, last: date) -> dict[date, CalendarDay]:
        """Notes created or edited on each day from `first` to `last` (inclusive)."""
        tz = self._clock.now().tzinfo
        start = to_millis(datetime.combine(first, datetime.min.time(), tzinfo=tz))
        end = to_millis(datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=tz))
        created = self._repo.notes_created_between(start, end)
        notes_by_id = {n.id: n for n in self._repo.notes()}
        days: dict[date, tuple[list[NoteInfo], list[NoteInfo]]] = {}
        for note in created:
            day = datetime.fromtimestamp(note.created_at / 1000, tz=tz).date()
            days.setdefault(day, ([], []))[0].append(note)
        for activity in self._repo.activity_between(first.isoformat(), last.isoformat()):
            day = date.fromisoformat(activity.day)
            touched_note = notes_by_id.get(activity.note_id)
            if touched_note is None:
                continue
            created_today, edited = days.setdefault(day, ([], []))
            known = {n.id for n in created_today} | {n.id for n in edited}
            if touched_note.id not in known:
                edited.append(touched_note)
        return {day: CalendarDay(day, tuple(c), tuple(e)) for day, (c, e) in sorted(days.items())}


__all__ = [
    "CalendarDay",
    "Clock",
    "EventBus",
    "EventKind",
    "LibraryEvent",
    "LibraryRepository",
    "LibraryService",
    "SystemClock",
    "fit_document",
]
