"""A year of activity: one column per week, each day shaded by how many notes it touched."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, QEvent, QLocale, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QHelpEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from schemeup.domain.streaks import LEVELS, level
from schemeup.ui.theme import Theme

WEEKS = 53
CELL = 10
GAP = 3
LEFT = 30  # room for the weekday names
TOP = 18  # room for the month names
SHADES = (0.28, 0.5, 0.75, 1.0)  # how much accent each level mixes in


def first_day(today: date) -> date:
    """The Monday that starts the leftmost column, so the grid ends with this week."""
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(weeks=WEEKS - 1)


def mix(base: QColor, top: QColor, amount: float) -> QColor:
    return QColor.fromRgbF(
        base.redF() + (top.redF() - base.redF()) * amount,
        base.greenF() + (top.greenF() - base.greenF()) * amount,
        base.blueF() + (top.blueF() - base.blueF()) * amount,
    )


class ActivityHeatmap(QWidget):
    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._counts: dict[date, int] = {}
        self._today = date.today()
        self._start = first_day(self._today)
        self.setFixedSize(self.sizeHint())
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(LEFT + WEEKS * (CELL + GAP), TOP + 7 * (CELL + GAP))

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_data(self, counts: dict[date, int], today: date) -> None:
        self._counts = counts
        self._today = today
        self._start = first_day(today)
        self.update()

    @property
    def start(self) -> date:
        return self._start

    def cell_rect(self, day: date) -> QRectF | None:
        offset = (day - self._start).days
        if offset < 0 or day > self._today:
            return None
        column, row = divmod(offset, 7)
        return QRectF(LEFT + column * (CELL + GAP), TOP + row * (CELL + GAP), CELL, CELL)

    def day_at(self, pos: QPointF) -> date | None:
        column = int((pos.x() - LEFT) // (CELL + GAP))
        row = int((pos.y() - TOP) // (CELL + GAP))
        if pos.x() < LEFT or pos.y() < TOP or not 0 <= column < WEEKS or not 0 <= row < 7:
            return None
        day = self._start + timedelta(days=column * 7 + row)
        rect = self.cell_rect(day)
        return day if rect is not None and rect.adjusted(-1, -1, 1, 1).contains(pos) else None

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            day = self.day_at(QPointF(event.pos()))
            if day is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), self.describe(day), self)
            return True
        return super().event(event)

    def describe(self, day: date) -> str:
        count = self._counts.get(day, 0)
        when = QLocale().toString(
            QDate(day.year, day.month, day.day), QLocale.FormatType.LongFormat
        )
        if count == 0:
            return self.tr("Nothing on %1").replace("%1", when)
        if count == 1:
            return self.tr("1 note on %1").replace("%1", when)
        return self.tr("%1 notes on %2").replace("%1", str(count)).replace("%2", when)

    def level_color(self, lvl: int) -> QColor:
        t = self._theme
        empty = mix(QColor(t.panel), QColor(t.text), 0.07 if not t.dark else 0.1)
        if lvl <= 0:
            return empty
        return mix(empty, QColor(t.accent), SHADES[min(lvl, LEVELS) - 1])

    def paintEvent(self, event: QPaintEvent) -> None:
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(QColor(t.muted))
        locale = QLocale()

        for row in (0, 2, 4):  # Monday, Wednesday, Friday
            y = TOP + row * (CELL + GAP)
            name = locale.dayName(row + 1, QLocale.FormatType.ShortFormat)
            painter.drawText(
                QRectF(0, y - 2, LEFT - 6, CELL + 4),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                name,
            )

        previous_month = 0
        for column in range(WEEKS):
            monday = self._start + timedelta(weeks=column)
            if monday > self._today:
                break
            if monday.month != previous_month and (column == 0 or monday.day <= 7):
                previous_month = monday.month
                if column <= WEEKS - 3:  # a label this close to the edge would be cut off
                    name = locale.monthName(monday.month, QLocale.FormatType.ShortFormat)
                    painter.drawText(
                        QRectF(LEFT + column * (CELL + GAP), 0, 40, TOP - 4),
                        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                        name,
                    )

        peak = max(self._counts.values(), default=0)
        painter.setPen(Qt.PenStyle.NoPen)
        for offset in range((self._today - self._start).days + 1):
            day = self._start + timedelta(days=offset)
            rect = self.cell_rect(day)
            if rect is None:
                continue
            painter.setBrush(self.level_color(level(self._counts.get(day, 0), peak)))
            painter.drawRoundedRect(rect, 2.5, 2.5)

        today_rect = self.cell_rect(self._today)
        if today_rect is not None:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.accent), 1.5))
            painter.drawRoundedRect(today_rect.adjusted(-1.5, -1.5, 1.5, 1.5), 3.5, 3.5)
        painter.end()
