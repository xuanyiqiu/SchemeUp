"""In-place text editing over the canvas.

A frameless, transparent QTextEdit is placed over the text being edited, so
typing gets everything Qt's editor offers: IME, clipboard, selection, word
jumps and undo while typing. Excalidraw does the same with an HTML textarea.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFocusEvent, QFont, QKeyEvent, QPalette, QTextCursor, QTextOption
from PySide6.QtWidgets import QFrame, QTextEdit, QWidget


class TextEditor(QTextEdit):
    finished = Signal(str, str)  # element id, final text

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("canvasTextEditor")
        self.setStyleSheet(
            "#canvasTextEditor { background: transparent; border: none; padding: 0; }"
        )
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setAcceptRichText(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)
        self.setTabChangesFocus(False)
        self._element_id: str | None = None
        self._layout: Callable[[str], QRectF] | None = None
        self.textChanged.connect(self._relayout)
        self.hide()

    @property
    def element_id(self) -> str | None:
        return self._element_id

    def begin(
        self,
        element_id: str,
        text: str,
        font: QFont,
        color: QColor,
        alignment: Qt.AlignmentFlag,
        layout: Callable[[str], QRectF],
    ) -> None:
        self._element_id = element_id
        self._layout = layout
        # The app-wide stylesheet sets a font size on every QWidget, and style sheets win
        # over setFont(). Putting the size in this widget's own sheet, which is more
        # specific, keeps what you type the same size as what the canvas will draw.
        self.setStyleSheet(
            "#canvasTextEditor { background: transparent; border: none; padding: 0;"
            f" font-family: '{font.family()}'; font-size: {font.pixelSize()}px; }}"
        )
        self.setFont(font)
        self.document().setDefaultFont(font)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Text, color)
        self.setPalette(palette)
        option = QTextOption(alignment)
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(option)
        self.blockSignals(True)
        self.setPlainText(text)
        self.blockSignals(False)
        self.moveCursor(QTextCursor.MoveOperation.End)
        self._relayout()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh(self) -> None:
        """Re-place the editor, for example after the camera moved."""
        if self._element_id is not None:
            self._relayout()

    def _relayout(self) -> None:
        if self._layout is None:
            return
        rect = self._layout(self.toPlainText())
        self.setGeometry(rect.toAlignedRect())

    def commit(self) -> None:
        if self._element_id is None:
            return
        element_id, text = self._element_id, self.toPlainText()
        self._element_id = None
        self._layout = None
        self.hide()
        self.finished.emit(element_id, text)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.commit()
            return
        if (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.commit()
            return
        if key == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.commit()
