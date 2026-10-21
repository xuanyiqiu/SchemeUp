"""The calendar page: which notes were created or edited each day.

The month grid shades each day by how many notes it touched, like a contribution
graph, and lists a few titles. Clicking a day shows all of them on the right.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.library import CalendarDay, EventKind, LibraryEvent, LibraryService
from schemeup.ui.theme import Theme, icon

ROLE = Qt.ItemDataRole.UserRole
NARROW_WIDTH = 760


def month_grid(year: int, month: int) -> list[date]:
    """The 42 days (6 weeks, Monday first) shown for a month."""
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    return [start + timedelta(days=i) for i in range(42)]


def week_days(day: date) -> list[date]:
    start = day - timedelta(days=day.weekday())
    return [start + timedelta(days=i) for i in range(7)]


class DayGrid(QWidget):
    """Draws the month (6 rows) or week (1 tall row) and reports clicks on days."""

    day_clicked = Signal(object)  # date

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.days: list[date] = []
        self.month = date.today().month
        self.data: dict[date, CalendarDay] = {}
        self.selected = date.today()
        self.week = False
        self.setMinimumSize(QSize(360, 300))
        self.setMouseTracking(True)
        self._hover: date | None = None

    def _cell(self, index: int) -> QRectF:
        rows = 1 if self.week else 6
        header = 28.0
        w = self.width() / 7
        h = (self.height() - header) / rows
        return QRectF((index % 7) * w, header + (index // 7) * h, w, h).adjusted(3, 3, -3, -3)

    def _day_at(self, pos: QPointF) -> date | None:
        for i, day in enumerate(self.days):
            if self._cell(i).contains(pos):
                return day
        return None

    def paintEvent(self, event: QPaintEvent) -> None:
        t = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(self.font())
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(QColor(t.muted))
        w = self.width() / 7
        for i, name in enumerate(calendar.day_abbr):
            painter.drawText(QRectF(i * w, 0, w, 24), int(Qt.AlignmentFlag.AlignCenter), name)
        peak = max((d.count for d in self.data.values()), default=0)
        today = date.today()
        for i, day in enumerate(self.days):
            rect = self._cell(i)
            info = self.data.get(day)
            count = info.count if info else 0
            in_month = self.week or day.month == self.month
            painter.setPen(
                QPen(
                    QColor(t.accent if day == self.selected else t.border),
                    1.5 if day == self.selected else 1,
                )
            )
            fill = QColor(t.panel if in_month else t.window)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 8, 8)
            if count and peak:
                # Density shading: more notes that day, stronger tint.
                tint = QColor(t.accent)
                tint.setAlpha(int(30 + 120 * count / peak))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tint)
                painter.drawRoundedRect(
                    QRectF(
                        rect.left() + 6,
                        rect.bottom() - 9,
                        (rect.width() - 12) * min(1.0, 0.25 + count / peak * 0.75),
                        4,
                    ),
                    2,
                    2,
                )
            number = QRectF(rect.left() + 8, rect.top() + 6, 26, 20)
            if day == today:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(t.accent))
                painter.drawEllipse(QRectF(number.left() - 4, number.top() - 1, 22, 22))
                painter.setPen(QColor("white"))
            else:
                painter.setPen(QColor(t.text if in_month else t.muted))
            bold = QFont(small)
            bold.setWeight(QFont.Weight.DemiBold)
            painter.setFont(bold)
            painter.drawText(
                QRectF(number.left() - 4, number.top() - 1, 22, 22),
                int(Qt.AlignmentFlag.AlignCenter),
                str(day.day),
            )
            painter.setFont(small)
            if info is None:
                continue
            titles = [n.title for n in info.created] + [f"✎ {n.title}" for n in info.edited]
            line_height = 16
            available = int((rect.height() - 40) // line_height)
            shown = (
                titles[: max(available, 0)]
                if len(titles) <= available
                else titles[: max(available - 1, 0)]
            )
            y = rect.top() + 30
            painter.setPen(QColor(t.text if in_month else t.muted))
            for title in shown:
                text = painter.fontMetrics().elidedText(
                    title, Qt.TextElideMode.ElideRight, int(rect.width() - 16)
                )
                painter.drawText(
                    QRectF(rect.left() + 8, y, rect.width() - 16, line_height),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    text,
                )
                y += line_height
            hidden = len(titles) - len(shown)
            if hidden > 0:
                painter.setPen(QColor(t.muted))
                painter.drawText(
                    QRectF(rect.left() + 8, y, rect.width() - 16, line_height),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    self.tr("+%1 more").replace("%1", str(hidden)),
                )
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        day = self._day_at(event.position())
        if day is not None:
            self.selected = day
            self.update()
            self.day_clicked.emit(day)


class CalendarView(QWidget):
    note_opened = Signal(int)

    def __init__(
        self, library: LibraryService, theme: Theme, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self._library = library
        self._theme = theme
        self._anchor = date.today()
        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        layout = self._layout
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(18)

        main = QVBoxLayout()
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("title")
        self.prev = QToolButton()
        self.prev.setToolTip(self.tr("Previous"))
        self.prev.clicked.connect(lambda: self._step(-1))
        self.next = QToolButton()
        self.next.setToolTip(self.tr("Next"))
        self.next.clicked.connect(lambda: self._step(1))
        today = QPushButton(self.tr("Today"))
        today.clicked.connect(self._today)
        self.month_button = QPushButton(self.tr("Month"))
        self.week_button = QPushButton(self.tr("Week"))
        group = QButtonGroup(self)
        for button in (self.month_button, self.week_button):
            button.setCheckable(True)
            group.addButton(button)
        self.month_button.setChecked(True)
        self.month_button.clicked.connect(lambda: self._set_week(False))
        self.week_button.clicked.connect(lambda: self._set_week(True))
        header.addWidget(self.title, 1)
        header.addWidget(self.prev)
        header.addWidget(today)
        header.addWidget(self.next)
        self._header = header
        self._main = main
        self._modes = QHBoxLayout()
        self._modes.addWidget(self.month_button)
        self._modes.addWidget(self.week_button)
        header.addSpacing(12)
        header.addLayout(self._modes)
        self._modes_below = False
        main.addLayout(header)
        self.grid = DayGrid(theme)
        self.grid.day_clicked.connect(self._show_day)
        main.addWidget(self.grid, 1)
        layout.addLayout(main, 1)

        side = QVBoxLayout()
        self.day_title = QLabel()
        self.day_title.setObjectName("dayTitle")
        side.addWidget(self.day_title)
        self.day_list = QListWidget()
        self.day_list.setMinimumWidth(190)
        self.day_list.setMaximumWidth(280)
        self.day_list.itemClicked.connect(self._open_item)
        side.addWidget(self.day_list, 1)
        layout.addLayout(side)

        library.events.subscribe(self._on_event)
        self.set_theme(theme)

    def minimumSizeHint(self) -> QSize:
        # What the stacked (narrow) arrangement needs; the side-by-side one only
        # applies when there is more room than this anyway.
        return QSize(420, 520)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        # In a narrow window (half a screen) the day's notes go under the grid, not beside it.
        narrow = self.width() < NARROW_WIDTH
        direction = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        if self._layout.direction() != direction:
            self._layout.setDirection(direction)
            self.day_list.setMaximumWidth(16777215 if narrow else 280)
            self.day_list.setMaximumHeight(170 if narrow else 16777215)
        self._place_modes(self.width() < NARROW_WIDTH + 140)

    def _place_modes(self, below: bool) -> None:
        """Month/Week buttons sit in the header, or on a row of their own when it is too tight."""
        if below == self._modes_below:
            return
        self._modes_below = below
        if below:
            self._header.removeItem(self._modes)
            self._main.insertLayout(1, self._modes)
        else:
            self._main.removeItem(self._modes)
            self._header.addLayout(self._modes)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.grid.theme = theme
        self.prev.setIcon(icon("chevron-left", theme.text))
        self.next.setIcon(icon("chevron-right", theme.text))
        self.setStyleSheet(
            f"QPushButton:checked {{ background: {theme.accent_soft};"
            f" border-color: {theme.accent}; }}"
            "#dayTitle { font-size: 15px; font-weight: 600; }"
        )
        self.refresh()

    def _on_event(self, event: LibraryEvent) -> None:
        if event.kind in (EventKind.NOTES, EventKind.CONTENT) and self.isVisible():
            self.refresh()

    def _set_week(self, week: bool) -> None:
        self.grid.week = week
        self.refresh()

    def _step(self, direction: int) -> None:
        if self.grid.week:
            self._anchor += timedelta(days=7 * direction)
        else:
            month = self._anchor.month - 1 + direction
            self._anchor = date(self._anchor.year + month // 12, month % 12 + 1, 1)
        self.refresh()

    def _today(self) -> None:
        self._anchor = date.today()
        self.grid.selected = date.today()
        self.refresh()
        self._show_day(date.today())

    def refresh(self) -> None:
        if self.grid.week:
            days = week_days(self._anchor)
            self.title.setText(
                self.tr("Week of %1").replace("%1", days[0].strftime("%d %b %Y").lstrip("0"))
            )
        else:
            days = month_grid(self._anchor.year, self._anchor.month)
            self.title.setText(date(self._anchor.year, self._anchor.month, 1).strftime("%B %Y"))
        self.grid.days = days
        self.grid.month = self._anchor.month
        self.grid.data = self._library.calendar(days[0], days[-1])
        self.grid.update()
        self._show_day(self.grid.selected)

    def _show_day(self, day: object) -> None:
        if not isinstance(day, date):
            return
        self.day_title.setText(day.strftime("%A %d %B").replace(" 0", " "))
        self.day_list.clear()
        info = self._library.calendar(day, day).get(day)
        if info is None or not info.count:
            item = QListWidgetItem(self.tr("Nothing written that day."))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.day_list.addItem(item)
            return
        for label, notes, name in (
            (self.tr("Created"), info.created, "file-text"),
            (self.tr("Edited"), info.edited, "clock"),
        ):
            if not notes:
                continue
            header = QListWidgetItem(label.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.day_list.addItem(header)
            for note in notes:
                item = QListWidgetItem(icon(name, self._theme.muted), note.title)
                item.setData(ROLE, note.id)
                self.day_list.addItem(item)

    def _open_item(self, item: QListWidgetItem) -> None:
        note_id = item.data(ROLE)
        if note_id is not None:
            self.note_opened.emit(int(note_id))
