"""The color picker used everywhere: five swatches, the last color used and a full picker.

Stroke pickers offer deep tones and fill pickers pastels of the same four
hues, so strokes stay readable while fills stay light (see the palette).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.domain.palette import SWATCHES, PickerKind, is_valid_hex
from schemeup.domain.style import TRANSPARENT
from schemeup.ui.theme import Theme


class RecentColors:
    """The last color picked in this session, per kind of picker."""

    def __init__(self) -> None:
        self._last: dict[PickerKind, str] = {}

    def get(self, kind: PickerKind) -> str | None:
        return self._last.get(kind)

    def remember(self, kind: PickerKind, color: str) -> None:
        if color != TRANSPARENT:
            self._last[kind] = color


def paint_swatch(
    painter: QPainter, rect: QRectF, color: str, border: QColor, radius: float = 5.0
) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if color == TRANSPARENT:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, radius, radius)
        # A checkerboard says "nothing here" better than white.
        painter.save()
        clip = QRectF(rect)
        painter.setClipRect(clip)
        cell = rect.width() / 4
        painter.setBrush(QColor("#d0d0d6"))
        for i in range(4):
            for j in range(4):
                if (i + j) % 2:
                    painter.drawRect(QRectF(rect.x() + i * cell, rect.y() + j * cell, cell, cell))
        painter.restore()
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(rect, radius, radius)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(border, 1))
    painter.drawRoundedRect(rect, radius, radius)


class SwatchButton(QToolButton):
    def __init__(self, color: str, size: int = 22, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.selected = False
        self.ring = QColor("#6d5dfc")
        self.border = QColor(0, 0, 0, 40)
        self.setFixedSize(QSize(size + 6, size + 6))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_color(self, color: str) -> None:
        self.color = color
        self.setToolTip(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inner = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.selected:
            painter.setPen(QPen(self.ring, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        elif self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 18))
            painter.drawRoundedRect(QRectF(self.rect()), 7, 7)
        paint_swatch(painter, inner, self.color, self.border)
        painter.end()


class SaturationValueArea(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hue = 0.0
        self.saturation = 1.0
        self.value = 1.0
        self.setFixedSize(QSize(200, 140))
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        base = QColor.fromHsvF(self.hue, 1.0, 1.0)
        horizontal = QLinearGradient(r.topLeft(), r.topRight())
        horizontal.setColorAt(0, QColor("white"))
        horizontal.setColorAt(1, base)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(horizontal))
        painter.drawRoundedRect(r, 6, 6)
        vertical = QLinearGradient(r.topLeft(), r.bottomLeft())
        vertical.setColorAt(0, QColor(0, 0, 0, 0))
        vertical.setColorAt(1, QColor(0, 0, 0, 255))
        painter.setBrush(QBrush(vertical))
        painter.drawRoundedRect(r, 6, 6)
        x = self.saturation * r.width()
        y = (1 - self.value) * r.height()
        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(x, y), 6, 6)
        painter.setPen(QPen(QColor(0, 0, 0, 120), 1))
        painter.drawEllipse(QPointF(x, y), 7.5, 7.5)
        painter.end()

    def _pick(self, pos: QPointF) -> None:
        self.saturation = min(max(pos.x() / self.width(), 0.0), 1.0)
        self.value = 1 - min(max(pos.y() / self.height(), 0.0), 1.0)
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pick(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())


class HueStrip(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hue = 0.0
        self.setFixedSize(QSize(200, 14))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        gradient = QLinearGradient(r.topLeft(), r.topRight())
        for i in range(7):
            gradient.setColorAt(i / 6, QColor.fromHsvF(min(i / 6, 0.999), 1, 1))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(r, 7, 7)
        x = self.hue * r.width()
        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(QColor.fromHsvF(min(self.hue, 0.999), 1, 1))
        painter.drawEllipse(QPointF(min(max(x, 7), r.width() - 7), r.height() / 2), 6, 6)
        painter.end()

    def _pick(self, pos: QPointF) -> None:
        self.hue = min(max(pos.x() / self.width(), 0.0), 0.999)
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pick(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())


class ColorPopover(QFrame):
    """A small popup with a saturation/value square, a hue strip and a hex field."""

    color_chosen = Signal(str)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("colorPopover")
        self.setStyleSheet(
            f"#colorPopover {{ background: {theme.panel}; border: 1px solid {theme.border};"
            " border-radius: 10px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self._area = SaturationValueArea()
        self._hue = HueStrip()
        layout.addWidget(self._area)
        layout.addWidget(self._hue)
        row = QHBoxLayout()
        self._hex = QLineEdit()
        self._hex.setPlaceholderText("#rrggbb")
        self._hex.setMaxLength(7)
        more = QPushButton(self.tr("More…"))
        more.clicked.connect(self._open_dialog)
        row.addWidget(self._hex, 1)
        row.addWidget(more)
        layout.addLayout(row)
        self._area.changed.connect(self._from_area)
        self._hue.changed.connect(self._from_hue)
        self._hex.editingFinished.connect(self._from_hex)

    def open_at(self, color: str, anchor: QPoint) -> None:
        if color != "transparent" and is_valid_hex(color):
            c = QColor(color)
            hue = max(c.hsvHueF(), 0.0)
            self._hue.hue = hue
            self._area.hue = hue
            self._area.saturation = c.hsvSaturationF()
            self._area.value = c.valueF()
            self._hex.setText(c.name())
        self.adjustSize()
        self.move(anchor)
        self.show()

    def _current(self) -> str:
        return QColor.fromHsvF(self._area.hue, self._area.saturation, self._area.value).name()

    def _from_area(self) -> None:
        color = self._current()
        self._hex.setText(color)
        self.color_chosen.emit(color)

    def _from_hue(self) -> None:
        self._area.hue = self._hue.hue
        self._area.update()
        self._from_area()

    def _from_hex(self) -> None:
        text = self._hex.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        if is_valid_hex(text):
            c = QColor(text)
            hue = max(c.hsvHueF(), 0.0)
            self._hue.hue = self._area.hue = hue
            self._area.saturation, self._area.value = c.hsvSaturationF(), c.valueF()
            self._area.update()
            self._hue.update()
            self.color_chosen.emit(c.name())

    def _open_dialog(self) -> None:
        self.hide()
        chosen = QColorDialog.getColor(
            QColor(self._current()), self.parentWidget(), self.tr("Pick a color")
        )
        if chosen.isValid():
            self.color_chosen.emit(chosen.name())


class ColorRow(QWidget):
    """Five palette swatches, the last color used, and a large swatch for any color."""

    color_chosen = Signal(str)

    def __init__(
        self, kind: PickerKind, recent: RecentColors, theme: Theme, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._recent = recent
        self._theme = theme
        self._current = SWATCHES[kind][0].color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self._swatches: list[SwatchButton] = []
        for swatch in SWATCHES[kind]:
            button = SwatchButton(swatch.color, 20)
            button.setToolTip(self.tr(swatch.name))
            button.clicked.connect(lambda _c=False, color=swatch.color: self._choose(color))
            self._swatches.append(button)
            layout.addWidget(button)
        self._divider = QFrame()
        self._divider.setFrameShape(QFrame.Shape.VLine)
        self._divider.setFixedSize(QSize(1, 18))
        layout.addSpacing(4)
        layout.addWidget(self._divider)
        layout.addSpacing(4)
        self._last = SwatchButton(TRANSPARENT, 20)
        self._last.setToolTip(self.tr("Last color used"))
        self._last.clicked.connect(lambda: self._choose(self._last.color))
        layout.addWidget(self._last)
        self._big = SwatchButton(self._current, 26)
        self._big.setToolTip(self.tr("Pick any color"))
        self._big.clicked.connect(self._open_popover)
        layout.addWidget(self._big)
        layout.addStretch(1)
        self._popover: ColorPopover | None = None
        self.set_theme(theme)
        self.refresh()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        ring = QColor(theme.accent)
        border = QColor(255, 255, 255, 50) if theme.dark else QColor(0, 0, 0, 40)
        for button in [*self._swatches, self._last, self._big]:
            button.ring = ring
            button.border = border
            button.update()
        self._divider.setStyleSheet(f"background: {theme.border}; border: none;")
        self._popover = None

    def set_color(self, color: str) -> None:
        self._current = color
        self.refresh()

    def refresh(self) -> None:
        for button in self._swatches:
            button.selected = button.color.lower() == self._current.lower()
            button.update()
        last = self._recent.get(self._kind)
        self._last.setVisible(last is not None)
        if last is not None:
            self._last.set_color(last)
            self._last.selected = last.lower() == self._current.lower() and not any(
                b.selected for b in self._swatches
            )
        self._big.set_color(self._current)

    def _choose(self, color: str) -> None:
        self._current = color
        self._recent.remember(self._kind, color)
        self.refresh()
        self.color_chosen.emit(color)

    def _open_popover(self) -> None:
        if self._popover is None:
            self._popover = ColorPopover(self._theme, self)
            self._popover.color_chosen.connect(self._choose)
        anchor = self._big.mapToGlobal(QPoint(self._big.width() + 8, -10))
        self._popover.open_at(self._current, anchor)
