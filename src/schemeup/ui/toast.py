"""A short message at the bottom of the window that goes away on its own."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from schemeup.ui.theme import Island, Theme


class Toast(Island):
    def __init__(self, theme: Theme, parent: QWidget) -> None:
        super().__init__(theme, parent, radius=10)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        self._label = QLabel()
        layout.addWidget(self._label)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, seconds: float = 4.0) -> None:
        self._label.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)
        self.show()
        self.raise_()
        self._timer.start(int(seconds * 1000))
