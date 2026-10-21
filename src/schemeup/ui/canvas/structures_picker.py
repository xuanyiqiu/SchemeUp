"""The data structure picker: choose a kind, type its values, see it, press Enter."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.domain.document import Document
from schemeup.domain.elements import element_bounds
from schemeup.domain.structures import EXAMPLES, StructureError, StructureKind, build
from schemeup.domain.style import Style
from schemeup.rendering.export_render import render_image
from schemeup.rendering.scene import SceneRenderer
from schemeup.ui.theme import Theme

PREVIEW = QSize(440, 190)
PREVIEW_PADDING = 18.0


class StructurePicker(QFrame):
    # The kind and the text to draw; the text is never empty (an empty field means the example).
    insert_requested = Signal(object, str)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self._theme = theme
        self._style = Style()
        self._renderer = SceneRenderer()
        self._kind = StructureKind.ARRAY
        self.setObjectName("structurePicker")

        # Names and explanations are listed here, not in the domain, so they can be translated.
        self._names = {
            StructureKind.ARRAY: self.tr("Array"),
            StructureKind.MATRIX: self.tr("Matrix"),
            StructureKind.LINKED_LIST: self.tr("Linked list"),
            StructureKind.DOUBLY_LINKED_LIST: self.tr("Doubly linked"),
            StructureKind.STACK: self.tr("Stack"),
            StructureKind.QUEUE: self.tr("Queue"),
            StructureKind.TREE: self.tr("Binary tree"),
            StructureKind.GRAPH: self.tr("Graph"),
        }
        self._hints = {
            StructureKind.ARRAY: self.tr("Values separated by commas. Indices are added."),
            StructureKind.MATRIX: self.tr("Rows separated by semicolons, values by spaces."),
            StructureKind.LINKED_LIST: self.tr("Values in order. Arrows and the end are added."),
            StructureKind.DOUBLY_LINKED_LIST: self.tr("Values in order, linked both ways."),
            StructureKind.STACK: self.tr("The first value is the bottom, the last is the top."),
            StructureKind.QUEUE: self.tr("The first value is the front, the last is the back."),
            StructureKind.TREE: self.tr("Level order, as in LeetCode. Use null for a gap."),
            StructureKind.GRAPH: self.tr(
                "Edges like A-B, or A->B for a direction, A-B:5 for a weight."
            ),
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)
        title = QLabel(self.tr("Draw a data structure").upper())
        title.setObjectName("section")
        layout.addWidget(title)

        chips = QGridLayout()
        chips.setSpacing(4)
        self._group = QButtonGroup(self)
        self._chips: dict[StructureKind, QToolButton] = {}
        for i, kind in enumerate(StructureKind):
            chip = QToolButton()
            chip.setObjectName("chip")
            chip.setText(self._names[kind])
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.clicked.connect(lambda _c=False, k=kind: self.choose(k))
            self._group.addButton(chip)
            self._chips[kind] = chip
            chips.addWidget(chip, i // 4, i % 4)
        layout.addLayout(chips)

        self._field = QLineEdit()
        self._field.textChanged.connect(self._refresh)
        self._field.returnPressed.connect(self._insert)
        self._field.installEventFilter(self)
        layout.addWidget(self._field)
        self._hint = QLabel()
        self._hint.setObjectName("muted")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._preview = QLabel()
        self._preview.setObjectName("preview")
        self._preview.setFixedSize(PREVIEW)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)

        row = QHBoxLayout()
        self._status = QLabel()
        self._status.setObjectName("muted")
        self._insert_button = QPushButton(self.tr("Insert"))
        self._insert_button.setObjectName("primary")
        self._insert_button.clicked.connect(self._insert)
        row.addWidget(self._status, 1)
        row.addWidget(self._insert_button)
        layout.addLayout(row)

        self.set_theme(theme)
        self.choose(StructureKind.ARRAY)

    @property
    def kind(self) -> StructureKind:
        return self._kind

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            f"#structurePicker {{ background: {theme.panel}; border: 1px solid {theme.border};"
            " border-radius: 12px; }"
            f"#preview {{ background: {theme.input}; border: 1px solid {theme.border};"
            " border-radius: 8px; }"
            f"QToolButton#chip {{ border: 1px solid {theme.border}; border-radius: 7px;"
            " padding: 6px 4px; }"
            f"QToolButton#chip:checked {{ background: {theme.accent_soft};"
            f" border-color: {theme.accent}; }}"
        )
        self._refresh()

    def set_style(self, style: Style) -> None:
        """The style new elements get, so the preview matches what will be drawn."""
        self._style = style
        self._refresh()

    def choose(self, kind: StructureKind) -> None:
        self._kind = kind
        self._chips[kind].setChecked(True)
        self._field.setPlaceholderText(EXAMPLES[kind])
        self._hint.setText(self._hints[kind])
        self._refresh()

    def open_at(self, anchor: QPoint, kind: StructureKind | None = None) -> None:
        if kind is not None:
            self.choose(kind)
        self.adjustSize()
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            anchor = QPoint(
                max(area.left() + 8, min(anchor.x(), area.right() - self.width() - 8)),
                max(area.top() + 8, min(anchor.y(), area.bottom() - self.height() - 8)),
            )
        self.move(anchor)
        self.show()
        self._field.setFocus(Qt.FocusReason.PopupFocusReason)
        self._field.selectAll()

    def text(self) -> str:
        """What will be drawn: the typed values, or the example when the field is empty."""
        return self._field.text().strip() or EXAMPLES[self._kind]

    def name(self, kind: StructureKind) -> str:
        return self._names[kind]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Tab walks through the kinds without the hands leaving the keyboard.
        if (
            watched is self._field
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
        ):
            kinds = list(StructureKind)
            step = -1 if event.key() == Qt.Key.Key_Backtab else 1
            self.choose(kinds[(kinds.index(self._kind) + step) % len(kinds)])
            return True
        return super().eventFilter(watched, event)

    def _refresh(self) -> None:
        try:
            elements = build(self._kind, self.text(), self._style)
        except StructureError as error:
            self._preview.clear()
            self._preview.setText(str(error).capitalize() + ".")
            self._status.setText("")
            self._insert_button.setEnabled(False)
            return
        self._insert_button.setEnabled(True)
        self._preview.setText("")
        self._preview.setPixmap(self._render(elements))
        shown = self._field.text().strip()
        self._status.setText(
            self.tr("Enter inserts it in the middle of the view")
            if shown
            else self.tr("Example shown. Type your own values.")
        )

    def _render(self, elements: list) -> QPixmap:  # type: ignore[type-arg]
        document = Document.of(elements)
        box = element_bounds(elements[0])
        for element in elements[1:]:
            box = box.union(element_bounds(element))
        region = box.inflated(PREVIEW_PADDING)
        ratio = self.devicePixelRatioF()
        scale = min(PREVIEW.width() / region.width, PREVIEW.height() / region.height, 1.0)
        image = render_image(
            document, region, self._renderer, scale * ratio, dark=self._theme.dark, background=False
        )
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        return pixmap

    def _insert(self) -> None:
        if not self._insert_button.isEnabled():
            return
        self.hide()
        self.insert_requested.emit(self._kind, self.text())
