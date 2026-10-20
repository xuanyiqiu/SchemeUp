"""The page shown when no note is open: templates, recent notes and a few tips."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.library import LibraryService
from schemeup.domain.templates import TEMPLATES
from schemeup.ui.formatting import relative_time
from schemeup.ui.theme import Theme, icon

CARD_LABELS = {
    "blank": "Blank",
    "quick": "Quick note",
    "meeting": "Meeting",
    "leetcode": "LeetCode",
    "architecture": "Architecture",
}

TEMPLATE_ICONS = {
    "blank": "file-text",
    "quick": "bolt",
    "meeting": "clock",
    "leetcode": "grid-dots",
    "architecture": "box-multiple",
}

TIPS = (
    ("Ctrl+N", "New note"),
    ("Ctrl+Alt+N", "Quick note from anywhere, even with SchemeUp in the background"),
    ("Ctrl+K", "Command palette: every command and every note"),
    ("Ctrl+F", "Search all notes, including text inside drawings"),
)


class WelcomePage(QWidget):
    template_chosen = Signal(str)
    note_chosen = Signal(int)

    def __init__(
        self, library: LibraryService, theme: Theme, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self._library = library
        self._theme = theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        center = QHBoxLayout()
        center.addStretch(1)
        column = QVBoxLayout()
        column.setSpacing(14)
        self.title = QLabel(self.tr("Good to see you"))
        self.title.setObjectName("title")
        subtitle = QLabel(self.tr("Sketch, take notes, and find everything later."))
        subtitle.setObjectName("muted")
        column.addWidget(self.title)
        column.addWidget(subtitle)

        start = QLabel(self.tr("Start something new").upper())
        start.setObjectName("section")
        column.addSpacing(10)
        column.addWidget(start)
        grid = QGridLayout()
        grid.setSpacing(10)
        self._cards: list[tuple[QToolButton, str]] = []
        for i, template in enumerate(TEMPLATES):
            card = QToolButton()
            card.setObjectName("card")
            card.setText(self.tr(CARD_LABELS.get(template.id, template.name)))
            card.setToolTip(self.tr(template.name))
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.setIconSize(QSize(26, 26))
            card.setFixedSize(QSize(132, 96))
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.clicked.connect(lambda _c=False, t=template.id: self.template_chosen.emit(t))
            self._cards.append((card, TEMPLATE_ICONS.get(template.id, "file-text")))
            grid.addWidget(card, 0, i)
        column.addLayout(grid)

        recent = QLabel(self.tr("Recent notes").upper())
        recent.setObjectName("section")
        column.addSpacing(10)
        column.addWidget(recent)
        self.recent = QListWidget()
        self.recent.setFixedHeight(200)
        self.recent.itemClicked.connect(
            lambda item: self.note_chosen.emit(int(item.data(Qt.ItemDataRole.UserRole)))
        )
        column.addWidget(self.recent)

        tips = QLabel(self.tr("Shortcuts").upper())
        tips.setObjectName("section")
        column.addSpacing(6)
        column.addWidget(tips)
        for keys, text in TIPS:
            row = QHBoxLayout()
            key = QLabel(keys)
            key.setObjectName("kbd")
            key.setFixedWidth(96)
            label = QLabel(self.tr(text))
            label.setObjectName("muted")
            row.addWidget(key)
            row.addWidget(label, 1)
            column.addLayout(row)

        holder = QWidget()
        holder.setLayout(column)
        holder.setFixedWidth(720)
        center.addWidget(holder)
        center.addStretch(1)
        outer.addLayout(center)
        outer.addStretch(2)
        self.set_theme(theme)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            f"QToolButton#card {{ background: {theme.panel}; border: 1px solid {theme.border};"
            f" border-radius: 12px; padding: 10px; font-weight: 600; }}"
            f"QToolButton#card:hover {{ border: 1px solid {theme.accent};"
            f" background: {theme.hover}; }}"
            f"QLabel#kbd {{ background: {theme.input}; border: 1px solid {theme.border};"
            " border-radius: 5px;"
            " padding: 2px 6px; font-family: 'JetBrains Mono'; font-size: 11px; }"
            f"QLabel#title {{ font-size: 26px; font-weight: 700; }}"
        )
        for card, name in self._cards:
            card.setIcon(icon(name, theme.accent))
        self.refresh()

    def refresh(self) -> None:
        self.recent.clear()
        notes = self._library.notes()[:8]
        if not notes:
            item = QListWidgetItem(self.tr("No notes yet. Pick a template above, or press Ctrl+N."))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(item)
        for note in notes:
            item = QListWidgetItem(
                icon("file-text", self._theme.muted),
                f"{note.title}    ·    {relative_time(note.updated_at)}",
            )
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.recent.addItem(item)
