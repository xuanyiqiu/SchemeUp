"""Tag chips for the open note: click a chip to remove it, "+ Tag" to add one."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLineEdit, QPushButton, QWidget

from schemeup.ui.theme import Theme


class TagEditor(QWidget):
    changed = Signal(list)  # list[str]

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._tags: list[str] = []
        self._known: list[str] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._input = QLineEdit()
        self._input.setPlaceholderText(self.tr("tag name"))
        self._input.setFixedWidth(120)
        self._input.hide()
        self._input.returnPressed.connect(self._add_from_input)
        self._input.editingFinished.connect(self._input.hide)
        self._add = QPushButton(self.tr("+ Tag"))
        self._add.setObjectName("chipAdd")
        self._add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add.clicked.connect(self._start_adding)
        self.set_theme(theme)
        self._rebuild()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            f"QPushButton#chip {{ background: {theme.accent_soft}; color: {theme.text};"
            " border: none; border-radius: 10px; padding: 2px 10px; font-size: 12px; }"
            f"QPushButton#chip:hover {{ background: {theme.hover};"
            " text-decoration: line-through; }"
            f"QPushButton#chipAdd {{ background: transparent; color: {theme.muted};"
            f" border: 1px dashed {theme.border}; border-radius: 10px; padding: 2px 10px;"
            " font-size: 12px; }"
        )

    def set_tags(self, tags: list[str], known: list[str]) -> None:
        self._tags = list(tags)
        self._known = known
        completer = QCompleter(known, self._input)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._input.setCompleter(completer)
        self._rebuild()

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None and widget not in (self._input, self._add):
                widget.deleteLater()
        for tag in self._tags:
            chip = QPushButton(f"#{tag}")
            chip.setObjectName("chip")
            chip.setToolTip(self.tr("Remove tag"))
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(22)
            chip.clicked.connect(lambda _c=False, t=tag: self._remove(t))
            self._layout.addWidget(chip)
        self._add.setFixedHeight(22)
        self._layout.addWidget(self._input)
        self._layout.addWidget(self._add)

    def _start_adding(self) -> None:
        self._input.clear()
        self._input.show()
        self._input.setFocus()

    def _add_from_input(self) -> None:
        name = self._input.text().strip().lstrip("#")
        self._input.hide()
        if name and name.lower() not in (t.lower() for t in self._tags):
            self._tags.append(name)
            self._rebuild()
            self.changed.emit(list(self._tags))

    def _remove(self, tag: str) -> None:
        self._tags = [t for t in self._tags if t != tag]
        self._rebuild()
        self.changed.emit(list(self._tags))

    def sizeHint(self) -> QSize:
        return super().sizeHint()
