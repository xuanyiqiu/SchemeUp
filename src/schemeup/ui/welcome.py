"""The page shown when no note is open: templates, recent notes and a few tips."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.library import LibraryService
from schemeup.domain.streaks import streaks
from schemeup.domain.templates import TEMPLATES
from schemeup.ui.formatting import relative_time
from schemeup.ui.heatmap import ActivityHeatmap, first_day
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

CARD_MIN = 92

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
        # The page scrolls and shrinks with the window, so it never keeps the
        # window from being snapped to half a screen.
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        page_layout.addWidget(scroll)
        content = QWidget()
        content.setObjectName("page")
        scroll.setWidget(content)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 0, 24, 0)
        outer.addStretch(1)
        center = QHBoxLayout()
        center.addStretch(1)
        column = QVBoxLayout()
        column.setSpacing(14)
        column.setContentsMargins(0, 0, 0, 0)
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
        self._card_grid = QGridLayout()
        grid = self._card_grid
        grid.setSpacing(10)
        self._cards: list[tuple[QToolButton, str]] = []
        for i, template in enumerate(TEMPLATES):
            card = QToolButton()
            card.setObjectName("card")
            card.setText(self.tr(CARD_LABELS.get(template.id, template.name)))
            card.setToolTip(self.tr(template.name))
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.setIconSize(QSize(26, 26))
            card.setMinimumSize(QSize(CARD_MIN, 96))
            card.setMaximumWidth(150)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.clicked.connect(lambda _c=False, t=template.id: self.template_chosen.emit(t))
            self._cards.append((card, TEMPLATE_ICONS.get(template.id, "file-text")))
            grid.addWidget(card, 0, i)
        self._card_columns = len(self._cards)
        column.addLayout(grid)

        recent = QLabel(self.tr("Recent notes").upper())
        recent.setObjectName("section")
        column.addSpacing(10)
        column.addWidget(recent)
        self.recent = QListWidget()
        self.recent.setFixedHeight(168)
        self.recent.itemClicked.connect(
            lambda item: self.note_chosen.emit(int(item.data(Qt.ItemDataRole.UserRole)))
        )
        column.addWidget(self.recent)

        year = QLabel(self.tr("Your year in notes").upper())
        year.setObjectName("section")
        column.addSpacing(6)
        column.addWidget(year)
        self.heatmap = ActivityHeatmap(theme)
        column.addWidget(self.heatmap)
        summary = QHBoxLayout()
        self.year_label = QLabel()
        self.year_label.setObjectName("muted")
        self.year_label.setWordWrap(True)
        self.streak_label = QLabel()
        self.streak_label.setObjectName("muted")
        summary.addWidget(self.year_label, 1)
        summary.addWidget(self.streak_label)
        column.addLayout(summary)

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
            label.setWordWrap(True)
            row.addWidget(key)
            row.addWidget(label, 1)
            column.addLayout(row)

        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(720)
        center.addWidget(holder, 100)
        center.addStretch(1)
        outer.addLayout(center)
        outer.addStretch(2)
        self.set_theme(theme)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        # As many cards per row as fit, so a half-width window wraps them instead of clipping.
        columns = max(2, min(len(self._cards), (self.width() - 48 + 10) // (CARD_MIN + 10)))
        if columns == self._card_columns:
            return
        self._card_columns = columns
        for i, (card, _name) in enumerate(self._cards):
            self._card_grid.addWidget(card, i // columns, i % columns)

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
        self.heatmap.set_theme(theme)
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
        self._refresh_year()

    def _refresh_year(self) -> None:
        today = date.today()
        days = self._library.calendar(first_day(today), today)
        counts = {day: entry.count for day, entry in days.items() if entry.count}
        self.heatmap.set_data(counts, today)
        total = sum(counts.values())
        if total == 0:
            self.year_label.setText(
                self.tr("Nothing yet. Your first note lights up today's square.")
            )
            self.streak_label.clear()
            return
        word = (
            self.tr("1 note touched in the last year")
            if total == 1
            else self.tr("%1 notes touched in the last year").replace("%1", str(total))
        )
        self.year_label.setText(word)
        run = streaks(counts, today)
        self.streak_label.setText(
            self.tr("Current streak %1, longest %2")
            .replace("%1", self._days(run.current))
            .replace("%2", self._days(run.longest))
        )

    def _days(self, count: int) -> str:
        if count == 1:
            return self.tr("1 day")
        return self.tr("%1 days").replace("%1", str(count))
