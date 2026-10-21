"""Presenting a note: its frames become slides and the camera flies between them."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from schemeup.domain.elements import Frame
from schemeup.domain.style import FontFamily
from schemeup.rendering.fonts import canvas_font
from schemeup.ui.canvas.view import CanvasView
from schemeup.ui.theme import Theme

IDLE_MS = 2200  # without input, the ribbon fades and the pointer hides
FADE_MS = 380
SEGMENT_WIDTH = 24
SEGMENT_GAP = 5
MAX_SEGMENTS_WIDTH = 520


class ProgressRibbon(QWidget):
    """A slim pill at the bottom of the stage: the slide's name and one segment per slide."""

    HEIGHT = 36

    def __init__(self, theme: Theme, reduce_motion: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self._stage = parent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._accent = QColor(theme.accent)
        self._reduce_motion = reduce_motion
        self._count = 0
        self._index = 0
        self._name = ""
        self._opacity = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._set_opacity)
        parent.installEventFilter(self)
        self.hide()

    def set_theme(self, theme: Theme) -> None:
        self._accent = QColor(theme.accent)
        self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._stage and event.type() == QEvent.Type.Resize:
            self._resize()
        return False

    def set_state(self, count: int, index: int, name: str) -> None:
        self._count, self._index, self._name = count, index, name
        self._resize()
        self.update()

    def appear(self) -> None:
        self._fade_to(1.0, 140)

    def disappear(self) -> None:
        self._fade_to(0.0, FADE_MS)

    def _fade_to(self, target: float, ms: int) -> None:
        self._fade.stop()
        if self._reduce_motion:
            self._set_opacity(target)
            return
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(target)
        self._fade.setDuration(ms)
        self._fade.start()

    def _set_opacity(self, value: object) -> None:
        self._opacity = float(value) if isinstance(value, int | float) else 0.0
        self.setVisible(self._opacity > 0.01 and self._count > 0)
        self.update()

    def _segments_width(self) -> int:
        wanted = self._count * SEGMENT_WIDTH + (self._count - 1) * SEGMENT_GAP
        return min(wanted, MAX_SEGMENTS_WIDTH)

    def _label(self) -> str:
        return f"{self._index + 1} / {self._count}"

    def _resize(self) -> None:
        metrics = QFontMetrics(canvas_font(FontFamily.NORMAL, 13))
        text = metrics.horizontalAdvance(self._name) if self._name else 0
        label = metrics.horizontalAdvance(self._label())
        gaps = 3 * 18 if self._name else 2 * 18
        width = 18 + text + label + self._segments_width() + gaps
        self.resize(min(width, max(self._stage.width() - 48, 200)), self.HEIGHT)
        self.move(
            (self._stage.width() - self.width()) // 2, self._stage.height() - self.height() - 26
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._count == 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        body = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QColor(255, 255, 255, 36))
        painter.setBrush(QColor(18, 18, 24, 214))
        painter.drawRoundedRect(body, body.height() / 2, body.height() / 2)

        font = canvas_font(FontFamily.NORMAL, 13)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        x = 24.0
        middle = self.height() / 2
        if self._name:
            painter.setPen(QColor(255, 255, 255, 235))
            painter.drawText(
                QRectF(x, 0, self.width() - x, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self._name,
            )
            x += metrics.horizontalAdvance(self._name) + 18

        width = self._segments_width()
        step = width / self._count
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(self._count):
            if i == self._index:
                painter.setBrush(self._accent)
            elif i < self._index:
                painter.setBrush(QColor(255, 255, 255, 170))
            else:
                painter.setBrush(QColor(255, 255, 255, 56))
            gap = min(SEGMENT_GAP, step / 3)
            painter.drawRoundedRect(QRectF(x + i * step, middle - 2.5, step - gap, 5), 2.5, 2.5)
        x += width + 18

        painter.setPen(QColor(255, 255, 255, 140))
        painter.drawText(
            QRectF(x, 0, self.width() - x, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._label(),
        )
        painter.end()


class Presentation(QObject):
    """Runs a slide show over a canvas: step, jump, fly, and get out of the way."""

    finished = Signal()

    def __init__(
        self,
        canvas: CanvasView,
        theme: Theme,
        *,
        reduce_motion: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._slides: list[Frame] = []
        self._index = 0
        self.ribbon = ProgressRibbon(theme, reduce_motion, canvas)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_MS)
        self._idle.timeout.connect(self._rest)
        canvas.slide_step.connect(self.step)
        canvas.slide_jump.connect(self.jump)
        canvas.presentation_exited.connect(self.stop)
        canvas.presentation_activity.connect(self._wake)

    @property
    def active(self) -> bool:
        return self._canvas.presenting

    @property
    def index(self) -> int:
        return self._index

    @property
    def count(self) -> int:
        return len(self._slides)

    def set_theme(self, theme: Theme) -> None:
        self.ribbon.set_theme(theme)

    def start(self, slides: list[Frame], index: int = 0) -> None:
        if not slides:
            return
        self._slides = slides
        self._canvas.set_presenting(True)
        self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        self._show(min(max(index, 0), len(slides) - 1))

    def stop(self) -> None:
        if not self.active:
            return
        self._idle.stop()
        self.ribbon.disappear()
        self._canvas.show_stage_cursor(True)
        self._canvas.set_presenting(False)
        self._slides = []
        self.finished.emit()

    def step(self, delta: int) -> None:
        self._go(self._index + delta)

    def jump(self, index: int) -> None:
        """Go to slide `index`; -1 means the last slide."""
        self._go(len(self._slides) - 1 if index == -1 else index)

    def _go(self, index: int) -> None:
        if not self.active or not self._slides:
            return
        self._show(min(max(index, 0), len(self._slides) - 1))

    def _show(self, index: int) -> None:
        self._index = index
        frame = self._slides[index]
        self.ribbon.set_state(len(self._slides), index, frame.name.strip())
        self._canvas.present(frame.local_rect)
        self._wake()

    def _wake(self) -> None:
        self._canvas.show_stage_cursor(True)
        self.ribbon.appear()
        self._idle.start()

    def _rest(self) -> None:
        self._canvas.show_stage_cursor(False)
        self.ribbon.disappear()
