"""The board page: columns of cards, where every card is a note.

A card only references a note; the note itself stays in its folder. Moving a
card changes its column on this board and nothing else.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.library import EventKind, LibraryEvent, LibraryService
from schemeup.domain.library import Column, NoteInfo
from schemeup.ui.formatting import relative_time
from schemeup.ui.theme import Theme, icon

CARD_MIME = "application/x-schemeup-card"
NOTE = Qt.ItemDataRole.UserRole
COLUMN_WIDTH = 290


class CardDelegate(QStyledItemDelegate):
    def __init__(self, theme: Theme, parent: QWidget) -> None:
        super().__init__(parent)
        self.theme = theme

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        note: NoteInfo | None = index.data(NOTE)
        if note is None:
            return
        t = self.theme
        rect = QRectF(option.rect).adjusted(2, 3, -2, -3)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(t.accent if hovered else t.border), 1))
        painter.setBrush(QColor(t.panel))
        painter.drawRoundedRect(rect, 9, 9)
        inner = rect.adjusted(12, 9, -12, -9)
        title_font = QFont(option.font)
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(t.text))
        title = painter.fontMetrics().elidedText(
            note.title, Qt.TextElideMode.ElideRight, int(inner.width())
        )
        painter.drawText(inner, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), title)
        small = QFont(option.font)
        small.setPixelSize(11)
        painter.setFont(small)
        y = inner.top() + 24
        if note.tags:
            x = inner.left()
            for tag in note.tags[:4]:
                text = f"#{tag}"
                width = painter.fontMetrics().horizontalAdvance(text) + 12
                chip = QRectF(x, y, width, 18)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(t.accent_soft))
                painter.drawRoundedRect(chip, 9, 9)
                painter.setPen(QColor(t.text))
                painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)
                x += width + 4
            y += 24
        painter.setPen(QColor(t.muted))
        painter.drawText(
            QRectF(inner.left(), y, inner.width(), 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            relative_time(note.updated_at),
        )
        painter.restore()

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        note: NoteInfo | None = index.data(NOTE)
        return QSize(COLUMN_WIDTH - 24, 78 if note is not None and note.tags else 56)


class CardList(QListWidget):
    """Cards of one column. Dropping a card here moves it to this column."""

    card_dropped = Signal(int, int, int)  # note id, column id, index

    def __init__(self, column_id: int, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.column_id = column_id
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.delegate = CardDelegate(theme, self)
        self.setItemDelegate(self.delegate)
        self.setStyleSheet(
            "QListWidget::item:selected, QListWidget::item:hover { background: transparent; }"
        )

    def mimeTypes(self) -> list[str]:
        return [CARD_MIME]

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:
        mime = QMimeData()
        if items:
            note: NoteInfo = items[0].data(NOTE)
            mime.setData(CARD_MIME, QByteArray(str(note.id).encode("ascii")))
        return mime

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(CARD_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(CARD_MIME):
            event.acceptProposedAction()
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        data = event.mimeData()
        if not data.hasFormat(CARD_MIME):
            return
        note_id = int(bytes(data.data(CARD_MIME).data()).decode("ascii"))
        item = self.itemAt(event.position().toPoint())
        index = self.row(item) if item is not None else self.count()
        if item is not None and event.position().y() > self.visualItemRect(item).center().y():
            index += 1
        # Copy, not move: the library is the source of truth and the board is rebuilt from it.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.card_dropped.emit(note_id, self.column_id, index)


class ColumnWidget(QFrame):
    def __init__(self, board: BoardView, column: Column, notes: list[NoteInfo]) -> None:
        super().__init__()
        self.setObjectName("boardColumn")
        self.setFixedWidth(COLUMN_WIDTH)
        self._board = board
        self.column = column
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.name = QLineEdit(column.name)
        self.name.setObjectName("columnName")
        self.name.editingFinished.connect(
            lambda: board.library.rename_column(column.id, self.name.text())
        )
        count = QLabel(str(len(notes)))
        count.setObjectName("muted")
        menu_button = QToolButton()
        menu_button.setObjectName("bare")
        menu_button.setIcon(icon("dots", board.theme.muted))
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        menu.addAction(self.tr("Rename"), self._start_rename)
        menu.addAction(self.tr("Move left"), lambda: board.move_column(column, -1))
        menu.addAction(self.tr("Move right"), lambda: board.move_column(column, 1))
        menu.addSeparator()
        menu.addAction(self.tr("Delete column"), lambda: board.delete_column(column))
        menu_button.setMenu(menu)
        header.addWidget(self.name, 1)
        header.addWidget(count)
        header.addWidget(menu_button)
        layout.addLayout(header)
        self.cards = CardList(column.id, board.theme)
        for note in notes:
            item = QListWidgetItem()
            item.setData(NOTE, note)
            item.setToolTip(note.title)
            self.cards.addItem(item)
        self.cards.card_dropped.connect(board.card_dropped)
        self.cards.itemClicked.connect(lambda item: board.note_opened.emit(item.data(NOTE).id))
        self.cards.customContextMenuRequested.connect(self._card_menu)
        layout.addWidget(self.cards, 1)
        add = QPushButton(self.tr("+ Add a note"))
        add.setObjectName("addCard")
        add.clicked.connect(lambda: board.add_note_menu(column, add))
        layout.addWidget(add)

    def _start_rename(self) -> None:
        self.name.setFocus()
        self.name.selectAll()

    def _card_menu(self, pos: QPoint) -> None:
        item = self.cards.itemAt(pos)
        if item is None:
            return
        note: NoteInfo = item.data(NOTE)
        board = self._board
        menu = QMenu(self)
        menu.addAction(self.tr("Open"), lambda: board.note_opened.emit(note.id))
        move = menu.addMenu(self.tr("Move to"))
        for column in board.columns:
            if column.id != self.column.id:
                move.addAction(column.name, board.mover(note.id, column.id))
        menu.addSeparator()
        menu.addAction(self.tr("Remove from board"), lambda: board.remove_card(note.id))
        menu.exec(self.cards.viewport().mapToGlobal(pos))


class BoardView(QWidget):
    note_opened = Signal(int)

    def __init__(
        self, library: LibraryService, theme: Theme, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.library = library
        self.theme = theme
        self.board_id: int | None = None
        self.columns: list[Column] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setObjectName("boardTitle")
        self.title.editingFinished.connect(self._rename)
        self.add_column = QPushButton(self.tr("+ Column"))
        self.add_column.clicked.connect(self._add_column)
        header.addWidget(self.title, 1)
        header.addWidget(self.add_column)
        layout.addLayout(header)
        self.hint = QLabel(
            self.tr(
                "Drag cards between columns. A card is a link to a note;"
                " the note stays in its folder."
            )
        )
        self.hint.setObjectName("muted")
        layout.addWidget(self.hint)
        self.columns_area = QScrollArea()
        self.columns_area.setWidgetResizable(True)
        self.columns_area.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.columns_area, 1)
        self.empty = QLabel(self.tr("No board yet. Create one from the sidebar."))
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)
        library.events.subscribe(self._on_event)
        self.set_theme(theme)

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.setStyleSheet(
            "#boardTitle { background: transparent; border: none; font-size: 22px;"
            " font-weight: 700; }"
            f"#boardColumn {{ background: {theme.input}; border: 1px solid {theme.border};"
            " border-radius: 12px; }"
            f"#columnName {{ background: transparent; border: none; font-weight: 600; }}"
            f"QPushButton#addCard {{ background: transparent; border: 1px dashed {theme.border};"
            f" color: {theme.muted}; }}"
            "QScrollArea { background: transparent; }"
            " QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self.refresh()

    def show_board(self, board_id: int | None) -> None:
        self.board_id = board_id
        self.refresh()

    def _on_event(self, event: LibraryEvent) -> None:
        if event.kind in (EventKind.BOARDS, EventKind.NOTES, EventKind.TAGS) and self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        boards = self.library.boards()
        if self.board_id is not None and all(b.id != self.board_id for b in boards):
            self.board_id = None
        if self.board_id is None and boards:
            self.board_id = boards[0].id
        has_board = self.board_id is not None
        self.empty.setVisible(not has_board)
        for widget in (self.title, self.add_column, self.hint, self.columns_area):
            widget.setVisible(has_board)
        if self.board_id is None:
            return
        board = self.library.boards()[[b.id for b in boards].index(self.board_id)]
        self.title.setText(board.name)
        self.columns = self.library.columns(board.id)
        notes = {n.id: n for n in self.library.notes()}
        by_column: dict[int, list[NoteInfo]] = {c.id: [] for c in self.columns}
        for card in self.library.cards(board.id):
            note = notes.get(card.note_id)
            if note is not None and card.column_id in by_column:
                by_column[card.column_id].append(note)
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for column in self.columns:
            row.addWidget(ColumnWidget(self, column, by_column[column.id]))
        row.addStretch(1)
        position = self.columns_area.horizontalScrollBar().value()
        self.columns_area.setWidget(container)
        self.columns_area.horizontalScrollBar().setValue(position)

    # Actions used by the columns

    def card_dropped(self, note_id: int, column_id: int, index: int) -> None:
        if self.board_id is not None:
            self.library.place_card(self.board_id, note_id, column_id, index)

    def mover(self, note_id: int, column_id: int) -> Callable[[], None]:
        return lambda: self.card_dropped(note_id, column_id, 10**6)

    def remove_card(self, note_id: int) -> None:
        if self.board_id is not None:
            self.library.remove_card(self.board_id, note_id)

    def move_column(self, column: Column, delta: int) -> None:
        if self.board_id is not None:
            index = [c.id for c in self.columns].index(column.id)
            self.library.move_column(self.board_id, column.id, max(index + delta, 0))

    def delete_column(self, column: Column) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Delete column"),
            self.tr("Delete “%1”? Its cards leave the board; the notes stay.").replace(
                "%1", column.name
            ),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.library.delete_column(column.id)

    def add_note_menu(self, column: Column, anchor: QWidget) -> None:
        if self.board_id is None:
            return
        on_board = {c.note_id for c in self.library.cards(self.board_id)}
        menu = QMenu(self)
        board_id = self.board_id
        menu.addAction(self.tr("New note in this column"), lambda: self._new_note_card(column))
        menu.addSeparator()
        for note in [n for n in self.library.notes() if n.id not in on_board][:15]:
            menu.addAction(note.title, self._placer(board_id, note.id, column.id))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _placer(self, board_id: int, note_id: int, column_id: int) -> Callable[[], None]:
        return lambda: self.library.place_card(board_id, note_id, column_id)

    def _new_note_card(self, column: Column) -> None:
        if self.board_id is None:
            return
        title, ok = QInputDialog.getText(self, self.tr("New note"), self.tr("Title"))
        if ok and title.strip():
            note = self.library.create_note(None, "blank", title.strip())
            self.library.place_card(self.board_id, note.id, column.id)

    def _rename(self) -> None:
        if self.board_id is not None:
            self.library.rename_board(self.board_id, self.title.text())

    def _add_column(self) -> None:
        if self.board_id is not None:
            self.library.add_column(self.board_id, self.tr("New column"))
