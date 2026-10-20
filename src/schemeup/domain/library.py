"""The note library: folders, notes, tags, boards. Plain records, no behaviour.

Folders are the single place a note lives. Tags label notes and boards place
them in a workflow; both only reference notes, so nothing is ever duplicated.
Timestamps are milliseconds since the epoch, in UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

INBOX = "Inbox"


def to_millis(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def from_millis(millis: int) -> datetime:
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


@dataclass(frozen=True, slots=True)
class Folder:
    id: int
    uuid: str
    parent_id: int | None  # None only for the root folder
    name: str
    position: int
    created_at: int
    trashed_at: int | None = None

    @property
    def is_root(self) -> bool:
        return self.parent_id is None


@dataclass(frozen=True, slots=True)
class NoteInfo:
    id: int
    uuid: str
    folder_id: int
    title: str
    created_at: int
    updated_at: int
    size_bytes: int = 0
    trashed_at: int | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Tag:
    id: int
    name: str
    color: str | None = None
    count: int = 0


@dataclass(frozen=True, slots=True)
class Board:
    id: int
    name: str
    position: int
    created_at: int


@dataclass(frozen=True, slots=True)
class Column:
    id: int
    board_id: int
    name: str
    position: int


@dataclass(frozen=True, slots=True)
class Card:
    board_id: int
    note_id: int
    column_id: int
    position: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    note: NoteInfo
    snippet: str


@dataclass(frozen=True, slots=True)
class Activity:
    note_id: int
    day: str  # local date, YYYY-MM-DD
    edits: int
