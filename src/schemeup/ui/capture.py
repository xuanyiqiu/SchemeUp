"""The quick capture window: a small always-on-top notepad that files its text as a note.

It is created once at startup and only shown and hidden afterwards, so the
global shortcut brings it up instantly.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from schemeup.domain.style import FontFamily
from schemeup.rendering.fonts import canvas_font
from schemeup.ui.theme import Theme, icon


class _Body(QPlainTextEdit):
    finish = Signal(bool)  # open in the editor afterwards

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.finish.emit(False)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.finish.emit(True)
            return
        super().keyPressEvent(event)


class CaptureWindow(QWidget):
    captured = Signal(str, str, bool)  # title, text, open in editor

    SHADOW = 14

    def __init__(self, theme: Theme) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._theme = theme
        self._closing = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("SchemeUp quick note")
        self.resize(560 + 2 * self.SHADOW, 340 + 2 * self.SHADOW)
        layout = QVBoxLayout(self)
        s = self.SHADOW
        layout.setContentsMargins(s + 16, s + 12, s + 16, s + 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self._icon = QLabel()
        self.title = QLineEdit()
        self.title.setObjectName("captureTitle")
        header.addWidget(self._icon)
        header.addWidget(self.title, 1)
        layout.addLayout(header)
        self.body = _Body()
        self.body.setObjectName("captureBody")
        self.body.setFont(canvas_font(FontFamily.HAND, 18))
        self.body.setPlaceholderText(self.tr("Start typing…"))
        self.body.finish.connect(self._finish)
        layout.addWidget(self.body, 1)
        self.hint = QLabel(self.tr("Esc saves and closes  ·  Ctrl+Enter saves and opens the note"))
        self.hint.setObjectName("muted")
        layout.addWidget(self.hint)
        self.set_theme(theme)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._icon.setPixmap(icon("bolt", theme.accent).pixmap(20, 20))
        self.setStyleSheet(
            "#captureTitle { background: transparent; border: none; font-size: 15px;"
            f" font-weight: 600; color: {theme.text}; }}"
            f"#captureBody {{ background: transparent; border: none; color: {theme.text}; }}"
            f"QLabel#muted {{ color: {theme.muted}; font-size: 11px; }}"
        )
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SHADOW
        body = QRectF(self.rect()).adjusted(s, s, -s, -s)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(s, 0, -2):
            alpha = int(self._theme.shadow * 1.4 * (1 - i / (s + 1)) / 3)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(body.adjusted(-i, -i + 3, i, i + 3), 14 + i, 14 + i)
        painter.setBrush(QColor(self._theme.panel))
        painter.setPen(QPen(QColor(self._theme.border), 1))
        painter.drawRoundedRect(body, 14, 14)
        painter.end()

    def open(self) -> None:
        if self.isVisible():
            self.activateWindow()
            self.body.setFocus()
            return
        self.title.setText(datetime.now().strftime("Quick note %Y-%m-%d %H:%M"))
        self.body.clear()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.top() + area.height() // 4)
        self._closing = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.body.setFocus()

    def _finish(self, open_in_editor: bool) -> None:
        if self._closing:
            return
        self._closing = True
        title, text = self.title.text(), self.body.toPlainText()
        self.hide()
        self.captured.emit(title, text, open_in_editor)

    def changeEvent(self, event: QEvent) -> None:
        # Clicking somewhere else files the note too; nothing typed is ever lost.
        if (
            event.type() == QEvent.Type.ActivationChange
            and self.isVisible()
            and not self.isActiveWindow()
        ):
            self._finish(False)
        super().changeEvent(event)
