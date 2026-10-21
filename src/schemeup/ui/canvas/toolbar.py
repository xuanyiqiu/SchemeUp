"""The floating tool bar at the top of the canvas."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QToolButton, QWidget

from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.theme import Island, Theme, icon

TOOLS: tuple[tuple[ToolKind, str, str, str], ...] = (
    (ToolKind.HAND, "hand-stop", "Hand", "H"),
    (ToolKind.SELECT, "pointer", "Selection", "1"),
    (ToolKind.RECTANGLE, "square", "Rectangle", "2"),
    (ToolKind.DIAMOND, "square-rotated", "Diamond", "3"),
    (ToolKind.ELLIPSE, "circle", "Ellipse", "4"),
    (ToolKind.ARROW, "arrow-narrow-right", "Arrow", "5"),
    (ToolKind.LINE, "line", "Line", "6"),
    (ToolKind.DRAW, "pencil", "Draw", "7"),
    (ToolKind.TEXT, "letter-t", "Text", "8"),
    (ToolKind.IMAGE, "photo", "Insert image", "9"),
    (ToolKind.ERASER, "eraser", "Eraser", "0"),
    (ToolKind.FRAME, "frame", "Frame", "F"),
)

LETTERS = {
    ToolKind.SELECT: "V",
    ToolKind.RECTANGLE: "R",
    ToolKind.DIAMOND: "D",
    ToolKind.ELLIPSE: "O",
    ToolKind.ARROW: "A",
    ToolKind.LINE: "L",
    ToolKind.DRAW: "P",
    ToolKind.TEXT: "T",
    ToolKind.ERASER: "E",
}


class BadgeButton(QToolButton):
    """A tool button with its keyboard shortcut in the corner."""

    def __init__(self, badge: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._badge = badge
        self._color = QColor("#888")

    def set_badge_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._badge:
            return
        painter = QPainter(self)
        font = QFont(self.font())
        font.setPixelSize(9)
        painter.setFont(font)
        painter.setPen(self._color)
        r = QRectF(self.rect()).adjusted(0, 0, -3, -1)
        painter.drawText(
            r, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom), self._badge
        )
        painter.end()


class Toolbar(Island):
    tool_chosen = Signal(object)  # ToolKind
    lock_toggled = Signal(bool)
    structures_requested = Signal()

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent, radius=10)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._lock = BadgeButton("Q")
        self._lock.setCheckable(True)
        self._lock.setToolTip(self.tr("Keep the selected tool active after drawing") + " — Q")
        self._lock.toggled.connect(self.lock_toggled.emit)
        layout.addWidget(self._lock)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFixedWidth(1)
        self._separator = separator
        layout.addWidget(separator)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[ToolKind, BadgeButton] = {}
        for kind, _icon_name, label, badge in TOOLS:
            button = BadgeButton(badge if kind != ToolKind.HAND else "")
            button.setCheckable(kind != ToolKind.IMAGE)
            letter = LETTERS.get(kind)
            shortcut = f"{letter} or {badge}" if letter else badge
            button.setToolTip(f"{self.tr(label)} — {shortcut}")
            button.setIconSize(QSize(20, 20))
            button.setFixedSize(QSize(36, 36))
            button.clicked.connect(lambda _checked=False, k=kind: self.tool_chosen.emit(k))
            if kind != ToolKind.IMAGE:
                self._group.addButton(button)
            self._buttons[kind] = button
            layout.addWidget(button)
        self._lock.setFixedSize(QSize(36, 36))
        self._lock.setIconSize(QSize(18, 18))
        self._second_separator = QFrame()
        self._second_separator.setFrameShape(QFrame.Shape.VLine)
        self._second_separator.setFixedWidth(1)
        layout.addWidget(self._second_separator)
        self.structures_button = BadgeButton("")
        self.structures_button.setToolTip(self.tr("Draw a data structure") + " — Ctrl+Shift+D")
        self.structures_button.setIconSize(QSize(20, 20))
        self.structures_button.setFixedSize(QSize(36, 36))
        self.structures_button.clicked.connect(self.structures_requested.emit)
        layout.addWidget(self.structures_button)
        self.set_theme(theme)
        self.set_current(ToolKind.SELECT)

    def set_theme(self, theme: Theme) -> None:
        super().set_theme(theme)
        for kind, icon_name, _, _ in TOOLS:
            button = self._buttons[kind]
            button.setIcon(icon(icon_name, theme.text))
            button.set_badge_color(theme.muted)
        self._lock.setIcon(icon("lock" if self._lock.isChecked() else "lock-open", theme.text))
        self._lock.set_badge_color(theme.muted)
        self._separator.setStyleSheet(f"background: {theme.border}; border: none;")
        self._second_separator.setStyleSheet(f"background: {theme.border}; border: none;")
        self.structures_button.setIcon(icon("binary-tree", theme.text))

    def set_current(self, kind: ToolKind) -> None:
        button = self._buttons.get(kind)
        if button is not None and button.isCheckable():
            button.setChecked(True)

    def set_locked(self, locked: bool) -> None:
        self._lock.blockSignals(True)
        self._lock.setChecked(locked)
        self._lock.blockSignals(False)
        self._lock.setIcon(icon("lock" if locked else "lock-open", self._theme.text))
