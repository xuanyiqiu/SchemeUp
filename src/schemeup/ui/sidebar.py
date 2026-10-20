"""The left sidebar: navigation, search, the folder tree, boards and trash."""

from __future__ import annotations

import html
from collections.abc import Callable
from enum import StrEnum

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDropEvent, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.library import EventKind, LibraryEvent, LibraryService
from schemeup.domain.errors import SchemeUpError
from schemeup.domain.library import INBOX, Board, Folder, NoteInfo
from schemeup.domain.templates import TEMPLATES
from schemeup.ui.formatting import full_time, human_size, relative_time
from schemeup.ui.theme import Theme, icon

KIND = Qt.ItemDataRole.UserRole
ID = Qt.ItemDataRole.UserRole + 1
STAMP = Qt.ItemDataRole.UserRole + 2
HIT_START, HIT_END = "\u0001", "\u0002"


class Page(StrEnum):
    NOTES = "notes"
    CALENDAR = "calendar"
    BOARDS = "boards"
    TRASH = "trash"


class _DateDelegate(QStyledItemDelegate):
    """Draws a note's last-edited date, muted and right-aligned, after its title."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.muted = QColor("#888")

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        stamp = index.data(STAMP)
        if not stamp:
            super().paint(painter, option, index)
            return
        text = relative_time(int(stamp))
        font = QFont(option.font)
        font.setPixelSize(11)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 18
        narrowed = QStyleOptionViewItem(option)
        narrowed.rect = option.rect.adjusted(0, 0, -width, 0)
        super().paint(painter, narrowed, index)
        painter.save()
        painter.setFont(font)
        painter.setPen(self.muted)
        rect = option.rect.adjusted(0, 0, -8, 0)
        painter.drawText(
            rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), text
        )
        painter.restore()

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 28))


class NoteTree(QTreeWidget):
    """Folders and notes. Drag items onto a folder to move them."""

    dropped = Signal(list, object)  # [(kind, id)], target folder id or None for the root

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setAnimated(True)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(16, 16))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setExpandsOnDoubleClick(True)
        self.delegate = _DateDelegate(self)
        self.setItemDelegate(self.delegate)

    def dropEvent(self, event: QDropEvent) -> None:
        moved = [(i.data(0, KIND), i.data(0, ID)) for i in self.selectedItems()]
        target = self.itemAt(event.position().toPoint())
        folder_id = None
        if target is not None:
            if target.data(0, KIND) == "folder":
                folder_id = target.data(0, ID)
            else:
                parent = target.parent()
                folder_id = parent.data(0, ID) if parent is not None else None
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        # Let the library decide; the tree is rebuilt from it afterwards.
        self.dropped.emit(moved, folder_id)


def walk(tree: QTreeWidget) -> list[QTreeWidgetItem]:
    """Every item of the tree, depth first."""
    result: list[QTreeWidgetItem] = []
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        result.append(item)
        stack.extend(item.child(i) for i in range(item.childCount()))
    return result


class Sidebar(QWidget):
    note_activated = Signal(int)
    page_requested = Signal(object)  # Page
    board_activated = Signal(int)
    settings_requested = Signal()
    theme_toggled = Signal()
    new_note_requested = Signal(object, str)  # folder id or None, template id

    def __init__(
        self, library: LibraryService, theme: Theme, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._library = library
        self._theme = theme
        self._current_note: int | None = None
        self._expanded: set[int] = set()
        self._rebuilding = False
        self._page = Page.NOTES
        self.setMinimumWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setFixedSize(QSize(26, 26))
        title = QLabel("SchemeUp")
        title.setObjectName("brand")
        header.addWidget(self.logo)
        header.addWidget(title)
        header.addStretch(1)
        self.new_folder_button = QToolButton()
        self.new_folder_button.setToolTip(self.tr("New folder"))
        self.new_folder_button.clicked.connect(lambda: self._new_folder(self._selected_folder()))
        header.addWidget(self.new_folder_button)
        layout.addLayout(header)

        self.new_note_button = QPushButton(self.tr("New note"))
        self.new_note_button.setObjectName("primary")
        self.new_note_button.setToolTip(self.tr("New note") + " — Ctrl+N")
        self.new_note_button.clicked.connect(
            lambda: self.new_note_requested.emit(self._selected_folder(), "blank")
        )
        template_menu = QMenu(self)
        for template in TEMPLATES:
            action = template_menu.addAction(self.tr(template.name))
            action.triggered.connect(
                lambda _c=False, t=template.id: self.new_note_requested.emit(
                    self._selected_folder(), t
                )
            )
        self.template_button = QToolButton()
        self.template_button.setToolTip(self.tr("New note from a template"))
        self.template_button.setMenu(template_menu)
        self.template_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        new_row = QHBoxLayout()
        new_row.setSpacing(4)
        new_row.addWidget(self.new_note_button, 1)
        new_row.addWidget(self.template_button)
        layout.addLayout(new_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search notes…  (Ctrl+F)"))
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        layout.addWidget(self.search)

        nav = QHBoxLayout()
        nav.setSpacing(2)
        self._nav_group = QButtonGroup(self)
        self._nav: dict[Page, QToolButton] = {}
        for page, tip in (
            (Page.NOTES, self.tr("Notes")),
            (Page.CALENDAR, self.tr("Calendar")),
            (Page.BOARDS, self.tr("Boards")),
            (Page.TRASH, self.tr("Trash")),
        ):
            button = QToolButton()
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setFixedSize(QSize(36, 32))
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda _c=False, p=page: self.show_page(p, emit=True))
            self._nav_group.addButton(button)
            self._nav[page] = button
            nav.addWidget(button)
        nav.addStretch(1)
        layout.addLayout(nav)

        self.stack = QStackedWidget()
        self.tree = NoteTree()
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemChanged.connect(self._item_renamed)
        self.tree.itemExpanded.connect(lambda i: self._expanded.add(i.data(0, ID)))
        self.tree.itemCollapsed.connect(lambda i: self._expanded.discard(i.data(0, ID)))
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.dropped.connect(self._dropped)
        self.results = QListWidget()
        self.results.itemClicked.connect(lambda i: self.note_activated.emit(i.data(ID)))
        self.boards = QListWidget()
        self.boards.itemClicked.connect(lambda i: self.board_activated.emit(i.data(ID)))
        self.boards.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.boards.customContextMenuRequested.connect(self._board_menu)
        self.trash = QListWidget()
        self.trash.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.trash.customContextMenuRequested.connect(self._trash_menu)
        self.trash.itemDoubleClicked.connect(self._restore_item)
        boards_page = QWidget()
        boards_layout = QVBoxLayout(boards_page)
        boards_layout.setContentsMargins(0, 0, 0, 0)
        boards_layout.addWidget(self.boards, 1)
        new_board = QPushButton(self.tr("New board"))
        new_board.clicked.connect(self._new_board)
        boards_layout.addWidget(new_board)
        trash_page = QWidget()
        trash_layout = QVBoxLayout(trash_page)
        trash_layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(self.tr("Double-click to restore. Items older than 30 days are removed."))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        trash_layout.addWidget(hint)
        trash_layout.addWidget(self.trash, 1)
        empty = QPushButton(self.tr("Empty trash"))
        empty.clicked.connect(self._empty_trash)
        trash_layout.addWidget(empty)
        for widget in (self.tree, self.results, boards_page, trash_page):
            self.stack.addWidget(widget)
        layout.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.settings_button = QToolButton()
        self.settings_button.setToolTip(self.tr("Settings") + " — Ctrl+,")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.theme_button = QToolButton()
        self.theme_button.setToolTip(self.tr("Light or dark") + " — Alt+Shift+D")
        self.theme_button.clicked.connect(self.theme_toggled.emit)
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        footer.addWidget(self.settings_button)
        footer.addWidget(self.theme_button)
        footer.addStretch(1)
        footer.addWidget(self.count_label)
        layout.addLayout(footer)

        library.events.subscribe(self._on_library_event)
        self.set_theme(theme)
        self.show_page(Page.NOTES)
        self.refresh()

    # Appearance

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            f"#sidebar {{ background: {theme.panel}; border-right: 1px solid {theme.border}; }}"
            f"#brand {{ font-size: 16px; font-weight: 700; }}"
        )
        self.logo.setPixmap(icon("app", theme.accent).pixmap(QSize(26, 26)))
        self.new_folder_button.setIcon(icon("folder-plus", theme.text))
        self.template_button.setIcon(icon("template", theme.text))
        self.settings_button.setIcon(icon("settings", theme.text))
        self.theme_button.setIcon(icon("sun" if theme.dark else "moon", theme.text))
        for page, name in (
            (Page.NOTES, "files"),
            (Page.CALENDAR, "calendar"),
            (Page.BOARDS, "layout-kanban"),
            (Page.TRASH, "trash"),
        ):
            self._nav[page].setIcon(icon(name, theme.text))
        self.tree.delegate.muted = QColor(theme.muted)
        self.refresh()

    # Pages

    def show_page(self, page: Page, emit: bool = False) -> None:
        self._nav[page].setChecked(True)
        self._page = page
        if page == Page.BOARDS:
            self.stack.setCurrentIndex(2)
            self._refresh_boards()
        elif page == Page.TRASH:
            self.stack.setCurrentIndex(3)
            self._refresh_trash()
        else:
            self.stack.setCurrentIndex(1 if self.search.text().strip() else 0)
        if emit:
            self.page_requested.emit(page)

    def set_current_note(self, note_id: int | None) -> None:
        self._current_note = note_id
        self._select_note(note_id)

    def focus_search(self) -> None:
        self.show_page(Page.NOTES, emit=False)
        self.search.setFocus()
        self.search.selectAll()

    # Refreshing from the library

    def _on_library_event(self, event: LibraryEvent) -> None:
        if event.kind in (EventKind.NOTES, EventKind.FOLDERS, EventKind.TAGS, EventKind.CONTENT):
            self.refresh()
        if event.kind == EventKind.BOARDS:
            self._refresh_boards()

    def refresh(self) -> None:
        if self.tree.state() == QAbstractItemView.State.EditingState:
            return
        self._rebuild_tree()
        if self._page == Page.TRASH:
            self._refresh_trash()
        if self.search.text().strip():
            self._run_search()
        self._refresh_boards()

    def _rebuild_tree(self) -> None:
        self._rebuilding = True
        try:
            self.tree.clear()
            root = self._library.root()
            folders = self._library.folders()
            notes = self._library.notes()
            children: dict[int | None, list[Folder]] = {}
            for folder in folders:
                if not folder.is_root:
                    children.setdefault(folder.parent_id, []).append(folder)
            notes_by_folder: dict[int, list[NoteInfo]] = {}
            for note in notes:
                notes_by_folder.setdefault(note.folder_id, []).append(note)
            first_run = not self._expanded

            def add(parent: QTreeWidgetItem | None, folder_id: int) -> None:
                subfolders = sorted(
                    children.get(folder_id, []), key=lambda f: (f.name != INBOX, f.name.lower())
                )
                for folder in subfolders:
                    item = QTreeWidgetItem([folder.name])
                    item.setData(0, KIND, "folder")
                    item.setData(0, ID, folder.id)
                    item.setIcon(
                        0, icon("inbox" if folder.name == INBOX else "folder", self._theme.muted)
                    )
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    if parent is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    add(item, folder.id)
                    if folder.id in self._expanded or (first_run and folder.name == INBOX):
                        item.setExpanded(True)
                        self._expanded.add(folder.id)
                for note in notes_by_folder.get(folder_id, []):
                    item = QTreeWidgetItem([note.title])
                    item.setData(0, KIND, "note")
                    item.setData(0, ID, note.id)
                    item.setData(0, STAMP, note.updated_at)
                    item.setIcon(0, icon("file-text", self._theme.muted))
                    item.setFlags(
                        (item.flags() | Qt.ItemFlag.ItemIsEditable) & ~Qt.ItemFlag.ItemIsDropEnabled
                    )
                    tags = "  ".join(f"#{t}" for t in note.tags)
                    item.setToolTip(
                        0,
                        f"<b>{html.escape(note.title)}</b><br>"
                        + self.tr("Created")
                        + f" {full_time(note.created_at)}<br>"
                        + self.tr("Edited")
                        + f" {full_time(note.updated_at)}<br>{human_size(note.size_bytes)}"
                        + (f"<br>{html.escape(tags)}" if tags else ""),
                    )
                    if parent is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)

            add(None, root.id)
            count = len(notes)
            self.count_label.setText(
                self.tr("1 note") if count == 1 else self.tr("%1 notes").replace("%1", str(count))
            )
        finally:
            self._rebuilding = False
        self._select_note(self._current_note)

    def _select_note(self, note_id: int | None) -> None:
        if note_id is None:
            return
        for item in walk(self.tree):
            if item.data(0, KIND) == "note" and item.data(0, ID) == note_id:
                self.tree.setCurrentItem(item)
                return

    def _run_search(self) -> None:
        text = self.search.text().strip()
        if not text:
            if self._page in (Page.NOTES, Page.CALENDAR):
                self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self.results.clear()
        hits = self._library.search(text)
        if not hits:
            item = QListWidgetItem(self.tr("No notes match “%1”").replace("%1", text))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)
            return
        for hit in hits:
            snippet = html.escape(hit.snippet.replace("\n", " "))
            snippet = snippet.replace(HIT_START, f"<b style='color:{self._theme.accent}'>").replace(
                HIT_END, "</b>"
            )
            item = QListWidgetItem()
            item.setData(ID, hit.note.id)
            widget = QWidget()
            box = QVBoxLayout(widget)
            box.setContentsMargins(6, 4, 6, 4)
            box.setSpacing(1)
            title = QLabel(f"<b>{html.escape(hit.note.title)}</b>")
            body = QLabel(snippet or self.tr("(title match)"))
            body.setObjectName("muted")
            body.setWordWrap(True)
            box.addWidget(title)
            box.addWidget(body)
            item.setSizeHint(widget.sizeHint() + QSize(0, 4))
            self.results.addItem(item)
            self.results.setItemWidget(item, widget)

    def _refresh_boards(self) -> None:
        self.boards.clear()
        for board in self._library.boards():
            item = QListWidgetItem(icon("layout-kanban", self._theme.muted), board.name)
            item.setData(ID, board.id)
            self.boards.addItem(item)

    def _refresh_trash(self) -> None:
        self.trash.clear()
        folders, notes = self._library.trash()
        for folder in folders:
            item = QListWidgetItem(icon("folder", self._theme.muted), folder.name)
            item.setData(KIND, "folder")
            item.setData(ID, folder.id)
            self.trash.addItem(item)
        for note in notes:
            item = QListWidgetItem(icon("file-text", self._theme.muted), note.title)
            item.setData(KIND, "note")
            item.setData(ID, note.id)
            item.setToolTip(self.tr("Deleted") + f" {full_time(note.trashed_at or 0)}")
            self.trash.addItem(item)
        if not folders and not notes:
            item = QListWidgetItem(self.tr("The trash is empty"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.trash.addItem(item)

    # Tree interaction

    def _selected_folder(self) -> int | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        if item.data(0, KIND) == "folder":
            return int(item.data(0, ID))
        parent = item.parent()
        return int(parent.data(0, ID)) if parent is not None else None

    def _item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, KIND) == "note":
            self.note_activated.emit(int(item.data(0, ID)))

    def _item_renamed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._rebuilding:
            return
        name = item.text(0).strip()
        try:
            if item.data(0, KIND) == "folder":
                self._library.rename_folder(int(item.data(0, ID)), name)
            else:
                self._library.rename_note(int(item.data(0, ID)), name)
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Can't rename"), str(error))
        QTimer.singleShot(0, self.refresh)

    def _dropped(self, moved: list[tuple[str, int]], folder_id: int | None) -> None:
        target = folder_id if folder_id is not None else self._library.root().id
        try:
            for kind, item_id in moved:
                if kind == "note":
                    self._library.move_note(item_id, target)
                else:
                    self._library.move_folder(item_id, target)
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Can't move"), str(error))
        self.refresh()

    def _new_folder(self, parent_id: int | None) -> None:
        try:
            folder = self._library.create_folder(parent_id, self.tr("New folder"))
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Can't create the folder"), str(error))
            return
        if parent_id is not None:
            self._expanded.add(parent_id)
        self.refresh()
        self._edit_item("folder", folder.id)

    def _edit_item(self, kind: str, item_id: int) -> None:
        for item in walk(self.tree):
            if item.data(0, KIND) == kind and item.data(0, ID) == item_id:
                self.tree.setCurrentItem(item)
                self.tree.editItem(item, 0)
                return

    def _tree_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is None or item.data(0, KIND) == "folder":
            target = int(item.data(0, ID)) if item is not None else None
            new_menu = menu.addMenu(self.tr("New note"))
            for template in TEMPLATES:
                action = new_menu.addAction(self.tr(template.name))
                action.triggered.connect(
                    lambda _c=False, t=template.id: self.new_note_requested.emit(target, t)
                )
            menu.addAction(self.tr("New folder"), lambda: self._new_folder(target))
            if item is not None:
                menu.addSeparator()
                menu.addAction(self.tr("Rename"), lambda: self.tree.editItem(item, 0))
                menu.addAction(
                    self.tr("Move to trash"), lambda: self._trash_folder(int(item.data(0, ID)))
                )
        else:
            note_id = int(item.data(0, ID))
            library = self._library

            def move_to(folder: int) -> Callable[[], None]:
                return lambda: library.move_note(note_id, folder)

            def add_to(board: int, column: int) -> Callable[[], None]:
                return lambda: library.place_card(board, note_id, column)

            menu.addAction(self.tr("Open"), lambda: self.note_activated.emit(note_id))
            menu.addAction(self.tr("Rename"), lambda: self.tree.editItem(item, 0))
            menu.addAction(self.tr("Duplicate"), lambda: self._duplicate(note_id))
            move_menu = menu.addMenu(self.tr("Move to"))
            move_menu.addAction(self.tr("Library (top level)"), move_to(library.root().id))
            for folder in library.folders():
                if not folder.is_root:
                    move_menu.addAction(folder.name, move_to(folder.id))
            boards: list[Board] = library.boards()
            if boards:
                board_menu = menu.addMenu(self.tr("Add to board"))
                for board in boards:
                    columns = library.columns(board.id)
                    if columns:
                        board_menu.addAction(board.name, add_to(board.id, columns[0].id))
            menu.addSeparator()
            menu.addAction(self.tr("Move to trash"), lambda: library.trash_note(note_id))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _duplicate(self, note_id: int) -> None:
        self._library.duplicate_note(note_id)

    def _trash_folder(self, folder_id: int) -> None:
        try:
            self._library.trash_folder(folder_id)
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Can't delete"), str(error))

    def _restore_item(self, item: QListWidgetItem) -> None:
        kind, item_id = item.data(KIND), item.data(ID)
        if kind == "note":
            self._library.restore_note(int(item_id))
        elif kind == "folder":
            self._library.restore_folder(int(item_id))
        self._refresh_trash()

    def _trash_menu(self, pos: QPoint) -> None:
        item = self.trash.itemAt(pos)
        if item is None or item.data(KIND) is None:
            return
        kind, item_id = item.data(KIND), int(item.data(ID))
        menu = QMenu(self)
        menu.addAction(self.tr("Restore"), lambda: self._restore_item(item))

        def delete_forever() -> None:
            if kind == "note":
                self._library.delete_note_forever(item_id)
            else:
                self._library.delete_folder_forever(item_id)
            self._refresh_trash()

        menu.addAction(self.tr("Delete forever"), delete_forever)
        menu.exec(self.trash.viewport().mapToGlobal(pos))

    def _empty_trash(self) -> None:
        answer = QMessageBox.question(
            self, self.tr("Empty trash"), self.tr("Delete everything in the trash for good?")
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._library.empty_trash()
            self._refresh_trash()

    # Boards

    def _new_board(self) -> None:
        board = self._library.create_board(self.tr("New board"))
        self._refresh_boards()
        self.board_activated.emit(board.id)

    def _board_menu(self, pos: QPoint) -> None:
        item = self.boards.itemAt(pos)
        if item is None:
            return
        board_id = int(item.data(ID))
        menu = QMenu(self)
        menu.addAction(self.tr("Open"), lambda: self.board_activated.emit(board_id))

        def delete() -> None:
            answer = QMessageBox.question(
                self,
                self.tr("Delete board"),
                self.tr("Delete this board? The notes stay in their folders."),
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._library.delete_board(board_id)

        menu.addAction(self.tr("Delete board"), delete)
        menu.exec(self.boards.viewport().mapToGlobal(pos))
