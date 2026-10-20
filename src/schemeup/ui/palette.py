"""The command palette (Ctrl+K): run any command or jump to any note by typing."""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.library import LibraryService
from schemeup.ui.theme import Theme, icon

ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True, slots=True)
class PaletteCommand:
    title: str
    action: Callable[[], None]
    shortcut: str = ""
    icon: str = "bolt"
    keywords: str = ""


def matches(query: str, text: str) -> bool:
    """Every character of `query` appears in `text` in order (case-insensitive)."""
    remaining = iter(text.lower())
    return all(ch in remaining for ch in query.lower() if not ch.isspace())


class _Input(QLineEdit):
    def __init__(self, palette: CommandPalette) -> None:
        super().__init__()
        self._palette = palette

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self._palette.step(1 if key == Qt.Key.Key_Down else -1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._palette.activate()
            return
        if key == Qt.Key.Key_Escape:
            self._palette.hide()
            return
        super().keyPressEvent(event)


class CommandPalette(QFrame):
    def __init__(
        self,
        theme: Theme,
        library: LibraryService,
        commands: Callable[[], list[PaletteCommand]],
        open_note: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("palette")
        self._library = library
        self._commands = commands
        self._open_note = open_note
        self._theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self.input = _Input(self)
        self.input.setPlaceholderText(self.tr("Type a command or search your notes…"))
        self.input.textChanged.connect(self._refresh)
        layout.addWidget(self.input)
        self.list = QListWidget()
        self.list.setIconSize(QSize(16, 16))
        self.list.itemActivated.connect(lambda _i: self.activate())
        self.list.itemClicked.connect(lambda _i: self.activate())
        layout.addWidget(self.list)
        self.hint = QLabel(self.tr("↑↓ to move  ·  Enter to run  ·  Esc to close"))
        self.hint.setObjectName("muted")
        layout.addWidget(self.hint)
        self.setFixedWidth(600)
        self.set_theme(theme)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            f"#palette {{ background: {theme.panel}; border: 1px solid {theme.border};"
            " border-radius: 12px; }"
        )

    def open_over(self, window: QWidget) -> None:
        self.input.clear()
        self._refresh()
        top_left = window.mapToGlobal(
            QPoint((window.width() - self.width()) // 2, int(window.height() * 0.12))
        )
        self.setFixedHeight(420)
        self.move(top_left)
        self.show()
        self.input.setFocus()

    def _section(self, title: str) -> None:
        item = QListWidgetItem(title.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setPixelSize(10)
        font.setBold(True)
        item.setFont(font)
        self.list.addItem(item)

    def _refresh(self) -> None:
        query = self.input.text().strip()
        self.list.clear()
        commands = [
            c for c in self._commands() if not query or matches(query, c.title + " " + c.keywords)
        ]
        if commands:
            self._section(self.tr("Commands"))
            for command in commands[:12]:
                text = command.title + (f"      {command.shortcut}" if command.shortcut else "")
                item = QListWidgetItem(icon(command.icon, self._theme.text), text)
                item.setData(ROLE, ("command", command))
                self.list.addItem(item)
        notes = []
        if query:
            notes = [h.note for h in self._library.search(query, limit=8)]
            titles = {n.id for n in notes}
            notes += [
                n for n in self._library.notes() if n.id not in titles and matches(query, n.title)
            ][:5]
        else:
            notes = self._library.notes()[:6]
        if notes:
            self._section(self.tr("Notes") if query else self.tr("Recent notes"))
            for note in notes:
                item = QListWidgetItem(
                    icon("file-text", self._theme.muted), html.unescape(note.title)
                )
                item.setData(ROLE, ("note", note.id))
                self.list.addItem(item)
        self.step(1, from_start=True)

    def step(self, delta: int, from_start: bool = False) -> None:
        count = self.list.count()
        if not count:
            return
        row = -1 if from_start else self.list.currentRow()
        for _ in range(count):
            row = (row + delta) % count
            if self.list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.list.setCurrentRow(row)
                return

    def activate(self) -> None:
        if self.list.currentRow() < 0:
            return
        data = self.list.currentItem().data(ROLE)
        if not data:
            return
        self.hide()
        kind, payload = data
        if kind == "command":
            payload.action()
        else:
            self._open_note(int(payload))
