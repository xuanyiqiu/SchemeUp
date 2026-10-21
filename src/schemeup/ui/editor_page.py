"""The editor page: the canvas with its floating tool bar, panels and title bar."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFont, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from schemeup.application.editor import Change, EditorSession
from schemeup.application.ports import AssetStore
from schemeup.ui.canvas.canvas_menu import CanvasMenu
from schemeup.ui.canvas.properties import PropertiesPanel
from schemeup.ui.canvas.toolbar import Toolbar
from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.canvas.view import CanvasView
from schemeup.ui.theme import Island, Theme, icon

MARGIN = 12


class Chrome(Enum):
    """How much of the editor's interface is showing around the canvas."""

    FULL = "full"
    FOCUS = "focus"  # title bar, canvas menu and properties hidden; tools and undo stay
    NONE = "none"  # the canvas alone, for presenting


class Stage(QWidget):
    """Holds the canvas and positions the floating islands over it."""

    def __init__(self, page: EditorPage) -> None:
        super().__init__(page)
        self._page = page

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._page.place_islands()


class EditorPage(QWidget):
    title_changed = Signal(str)
    export_requested = Signal()
    present_requested = Signal()

    def __init__(
        self,
        session: EditorSession,
        theme: Theme,
        *,
        assets: AssetStore | None = None,
        reduce_motion: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self._session = session
        self._theme = theme
        self._chrome = Chrome.FULL

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = QWidget()
        self.title_bar.setObjectName("titleBar")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(16, 8, 12, 8)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("noteTitle")
        self.title_edit.setPlaceholderText(self.tr("Untitled note"))
        font = QFont(self.title_edit.font())
        font.setPixelSize(17)
        font.setWeight(QFont.Weight.DemiBold)
        self.title_edit.setFont(font)
        self.title_edit.editingFinished.connect(
            lambda: self.title_changed.emit(self.title_edit.text().strip())
        )
        self.meta_label = QLabel()
        self.meta_label.setObjectName("muted")
        self.export_button = QToolButton()
        self.export_button.setToolTip(self.tr("Export") + " — Ctrl+Shift+E")
        self.export_button.setIconSize(QSize(18, 18))
        self.export_button.clicked.connect(self.export_requested.emit)
        self.present_button = QToolButton()
        self.present_button.setToolTip(self.tr("Present the frames as slides") + " — F5")
        self.present_button.setIconSize(QSize(18, 18))
        self.present_button.clicked.connect(self.present_requested.emit)
        title_layout.addWidget(self.title_edit, 1)
        # Room for extra widgets (the tag chips) between the title and the details.
        self.title_extras = QHBoxLayout()
        self.title_extras.setSpacing(6)
        title_layout.addLayout(self.title_extras)
        title_layout.addSpacing(10)
        title_layout.addWidget(self.meta_label)
        title_layout.addSpacing(8)
        title_layout.addWidget(self.present_button)
        title_layout.addWidget(self.export_button)
        layout.addWidget(self.title_bar)

        self.stage = Stage(self)
        layout.addWidget(self.stage, 1)
        self.canvas = CanvasView(
            session, assets=assets, theme=theme, reduce_motion=reduce_motion, parent=self.stage
        )

        self.toolbar = Toolbar(theme, self.stage)
        self.toolbar.tool_chosen.connect(self.canvas.set_tool)
        self.toolbar.lock_toggled.connect(self._set_tool_lock)
        self.canvas.tool_changed.connect(self._on_tool_changed)

        self.properties = PropertiesPanel(session, theme, self.stage)
        self.properties.resized.connect(self.place_islands)

        self.menu_island = Island(theme, self.stage)
        menu_layout = QHBoxLayout(self.menu_island)
        menu_layout.setContentsMargins(4, 4, 4, 4)
        self.menu_button = QToolButton()
        self.menu_button.setToolTip(self.tr("Canvas: background, sheet, page and snapping"))
        self.menu_button.setFixedSize(QSize(36, 36))
        self.menu_button.setIconSize(QSize(20, 20))
        self.menu_button.clicked.connect(self._open_canvas_menu)
        menu_layout.addWidget(self.menu_button)
        self.canvas_menu = CanvasMenu(session, theme, self)
        self.canvas_menu.snapping_toggled.connect(lambda o, g: self.canvas.set_snapping(o, g))

        self.history_island = Island(theme, self.stage)
        history_layout = QHBoxLayout(self.history_island)
        history_layout.setContentsMargins(4, 4, 4, 4)
        history_layout.setSpacing(2)
        self.undo_button = QToolButton()
        self.undo_button.setToolTip(self.tr("Undo") + " — Ctrl+Z")
        self.undo_button.clicked.connect(session.undo)
        self.redo_button = QToolButton()
        self.redo_button.setToolTip(self.tr("Redo") + " — Ctrl+Shift+Z")
        self.redo_button.clicked.connect(session.redo)
        for button in (self.undo_button, self.redo_button):
            button.setFixedSize(QSize(32, 32))
            button.setIconSize(QSize(18, 18))
            history_layout.addWidget(button)

        session.subscribe(self._on_session_change)
        self.canvas.camera_changed.connect(lambda _c: self.place_islands())
        self.set_theme(theme)
        self._update_history()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.title_bar.setStyleSheet(
            f"#titleBar {{ background: {theme.panel}; border-bottom: 1px solid {theme.border}; }}"
            f"#noteTitle {{ background: transparent; border: none; padding: 2px 0; }}"
        )
        self.canvas.set_theme(theme)
        self.toolbar.set_theme(theme)
        self.properties.set_theme(theme)
        self.menu_island.set_theme(theme)
        self.history_island.set_theme(theme)
        self.canvas_menu.set_theme(theme)
        self.menu_button.setIcon(icon("menu-2", theme.text))
        self.undo_button.setIcon(icon("arrow-back-up", theme.text))
        self.redo_button.setIcon(icon("arrow-forward-up", theme.text))
        self.export_button.setIcon(icon("download", theme.text))
        self.present_button.setIcon(icon("presentation", theme.text))

    @property
    def chrome(self) -> Chrome:
        return self._chrome

    def set_chrome(self, chrome: Chrome) -> None:
        self._chrome = chrome
        self.title_bar.setVisible(chrome is Chrome.FULL)
        self.properties.set_suppressed(chrome is not Chrome.FULL)
        self.place_islands()

    def place_islands(self) -> None:
        w, h = self.stage.width(), self.stage.height()
        self.canvas.setGeometry(0, 0, w, h)
        self.toolbar.setVisible(self._chrome is not Chrome.NONE)
        self.history_island.setVisible(self._chrome is not Chrome.NONE)
        self.menu_island.setVisible(self._chrome is Chrome.FULL)
        self.toolbar.adjustSize()
        left = self.menu_island.width() + MARGIN if self._chrome is Chrome.FULL else MARGIN
        tx = max((w - self.toolbar.width()) // 2, left)
        self.toolbar.move(tx, MARGIN - 4)
        self.menu_island.adjustSize()
        self.menu_island.move(MARGIN - 6, MARGIN - 4)
        top = self.menu_island.y() + self.menu_island.height() + 2
        self.properties.move(MARGIN - 6, top)
        if self.properties.height() > h - top - 70:
            self.properties.setFixedHeight(max(h - top - 70, 160))
        self.history_island.adjustSize()
        zoom = self.canvas.zoom_button
        self.history_island.move(
            zoom.x() + zoom.width() + 4,
            h - self.history_island.height() + Island.SHADOW - 12,
        )
        for widget in (self.toolbar, self.menu_island, self.properties, self.history_island):
            widget.raise_()

    def _open_canvas_menu(self) -> None:
        anchor = self.menu_island.mapToGlobal(QPoint(Island.SHADOW, self.menu_island.height()))
        self.canvas_menu.open_at(anchor, self.canvas.snap_objects, self.canvas.snap_grid)

    def _set_tool_lock(self, locked: bool) -> None:
        self.canvas.tool_locked = locked
        self.toolbar.set_locked(locked)

    def _on_tool_changed(self, kind: object) -> None:
        if isinstance(kind, ToolKind):
            self.toolbar.set_current(kind)
            self.properties.set_tool(kind)
        self.toolbar.set_locked(self.canvas.tool_locked)
        self.place_islands()

    def _on_session_change(self, change: Change) -> None:
        if change in (Change.DOCUMENT, Change.SELECTION):
            self._update_history()
            self.place_islands()

    def _update_history(self) -> None:
        self.undo_button.setEnabled(self._session.can_undo)
        self.redo_button.setEnabled(self._session.can_redo)

    def focus_canvas(self) -> None:
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
