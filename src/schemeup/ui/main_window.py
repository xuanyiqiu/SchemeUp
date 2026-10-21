"""The main window: sidebar, editor and welcome pages, autosave, palette, tray and capture."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QElapsedTimer, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
)

from schemeup.application.editor import Change, EditorSession
from schemeup.application.export import Exporter, Importer
from schemeup.application.library import EventKind, LibraryEvent, LibraryService
from schemeup.application.ports import AssetStore
from schemeup.application.settings import Settings
from schemeup.domain.document import Document
from schemeup.domain.elements import Text
from schemeup.domain.errors import SchemeUpError
from schemeup.domain.geometry import Point
from schemeup.domain.library import NoteInfo
from schemeup.domain.presentation import slide_near, slides
from schemeup.domain.templates import TEMPLATES
from schemeup.ui.board_view import BoardView
from schemeup.ui.calendar_view import CalendarView
from schemeup.ui.canvas.tools import ToolKind
from schemeup.ui.capture import CaptureWindow
from schemeup.ui.editor_page import Chrome, EditorPage
from schemeup.ui.formatting import full_time, human_size
from schemeup.ui.palette import CommandPalette, PaletteCommand
from schemeup.ui.presenter import Presentation
from schemeup.ui.settings_dialog import SettingsDialog
from schemeup.ui.sidebar import Page, Sidebar
from schemeup.ui.tags import TagEditor
from schemeup.ui.theme import DARK, LIGHT, Theme, icon, stylesheet
from schemeup.ui.toast import Toast
from schemeup.ui.welcome import WelcomePage

AUTOSAVE_IDLE_MS = 800
AUTOSAVE_MAX_MS = 5000


class PageStack(QStackedWidget):
    """A stack that is only as demanding as the page showing.

    QStackedWidget reports the largest minimum size of all its pages, so the
    calendar's width would stop the window from being snapped to half a screen
    while the editor, which can be narrow, is what's on display."""

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()


@dataclass(frozen=True, slots=True)
class StageMemory:
    """What the window looked like before focus mode or a presentation took it over."""

    sidebar: bool
    maximized: bool
    fullscreen: bool


@dataclass(slots=True)
class Environment:
    """Things the window needs from the composition root."""

    settings: Settings
    save_settings: Callable[[Settings], None]
    library_path: Path
    backups_dir: Path
    backup_now: Callable[[], Path | None]
    register_hotkey: Callable[[str], str]  # returns an error message, empty when it worked
    hotkey_supported: bool
    reduce_motion: bool
    exporter: Exporter | None = None
    importer: Importer | None = None


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints.colorScheme() == Qt.ColorScheme.Dark


def theme_for(choice: str) -> Theme:
    if choice == "dark" or (choice == "system" and system_prefers_dark()):
        return DARK
    return LIGHT


class MainWindow(QMainWindow):
    def __init__(
        self,
        library: LibraryService,
        session: EditorSession,
        *,
        assets: AssetStore | None,
        env: Environment,
    ) -> None:
        super().__init__()
        self._library = library
        self._session = session
        self._env = env
        self._settings = env.settings
        self._theme = theme_for(self._settings.theme)
        self._note: NoteInfo | None = None
        self._saved_revision = session.revision
        self._quitting = False
        self._focus_mode = False
        self._stage: StageMemory | None = None
        self.setWindowTitle("SchemeUp")
        self.setWindowIcon(icon("app", self._theme.accent))
        self.resize(1400, 880)

        self.sidebar = Sidebar(library, self._theme)
        self.editor = EditorPage(
            session, self._theme, assets=assets, reduce_motion=env.reduce_motion
        )
        self.editor.export_requested.connect(self.export_note)
        self.editor.present_requested.connect(self.start_presentation)
        self.presentation = Presentation(
            self.editor.canvas, self._theme, reduce_motion=env.reduce_motion, parent=self
        )
        self.presentation.finished.connect(self._sync_stage)
        self.editor.canvas.copy_png_requested.connect(self.copy_png)
        self._assets = assets
        self.editor.title_changed.connect(self._rename_current)
        self.tags = TagEditor(self._theme)
        self.tags.changed.connect(self._set_tags)
        self.editor.title_extras.addWidget(self.tags)
        self.editor.canvas.set_snapping(self._settings.snap_objects, self._settings.snap_grid)
        self.editor.canvas.snapping_changed.connect(self._remember_snapping)
        self.welcome = WelcomePage(library, self._theme)
        self.welcome.template_chosen.connect(lambda t: self.new_note(None, t))
        self.welcome.note_chosen.connect(self.open_note)

        self.board_view = BoardView(library, self._theme)
        self.board_view.note_opened.connect(self.open_note)
        self.calendar_view = CalendarView(library, self._theme)
        self.calendar_view.note_opened.connect(self.open_note)

        self.pages = PageStack()
        self.pages.addWidget(self.welcome)
        self.pages.addWidget(self.editor)
        self.pages.addWidget(self.board_view)
        self.pages.addWidget(self.calendar_view)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.pages)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([270, 1130])
        self.splitter.setHandleWidth(1)
        self.setCentralWidget(self.splitter)
        self.sidebar.setVisible(self._settings.sidebar_visible)

        self.sidebar.note_activated.connect(self.open_note)
        self.sidebar.new_note_requested.connect(self.new_note)
        self.sidebar.settings_requested.connect(self.open_settings)
        self.sidebar.theme_toggled.connect(self.toggle_theme)
        self.sidebar.page_requested.connect(self._show_page)
        self.sidebar.board_activated.connect(self.show_board)
        self.sidebar.import_requested.connect(self.import_note)

        self.toast = Toast(self._theme, self.pages)
        self.command_palette = CommandPalette(
            self._theme, library, self._commands, self.open_note, self
        )
        self.capture = CaptureWindow(self._theme)
        self.capture.captured.connect(self._captured)

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(AUTOSAVE_IDLE_MS)
        self._idle.timeout.connect(self.flush)
        self._dirty_since = QElapsedTimer()
        session.subscribe(self._on_session_change)
        library.events.subscribe(self._on_library_event)

        self._add_shortcuts()
        self._create_tray()
        self.apply_theme(self._theme)
        if self._settings.window_geometry:
            self.restoreGeometry(
                QByteArray.fromBase64(self._settings.window_geometry.encode("ascii"))
            )

    # Notes

    @property
    def current_note(self) -> NoteInfo | None:
        return self._note

    def open_note(self, note_id: int) -> None:
        self.presentation.stop()
        if self._note is not None and self._note.id == note_id:
            self._show_editor()
            return
        self.flush()
        try:
            note = self._library.note(note_id)
            document = self._library.open_document(note_id)
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Can't open the note"), str(error))
            return
        self._note = note
        self._session.load(document)
        self._saved_revision = self._session.revision
        self._show_editor()
        self._refresh_header()
        self.editor.canvas.show_document()
        self.sidebar.set_current_note(note_id)
        self._settings.last_note_id = note_id
        self.editor.focus_canvas()

    def new_note(self, folder_id: int | None, template_id: str = "blank") -> None:
        try:
            note = self._library.create_note(folder_id, template_id)
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Can't create the note"), str(error))
            return
        self.open_note(note.id)
        if template_id == "quick":
            texts = [e for e in self._session.document.ordered() if isinstance(e, Text)]
            if texts:
                self.editor.canvas.edit_text(texts[0].id)
        elif template_id == "blank":
            self.editor.title_edit.setFocus()
            self.editor.title_edit.selectAll()

    def close_note(self) -> None:
        self.presentation.stop()
        self.flush()
        self._note = None
        self._session.load(Document())
        self.welcome.refresh()
        self.pages.setCurrentWidget(self.welcome)
        self.sidebar.set_current_note(None)
        self.setWindowTitle("SchemeUp")

    def flush(self) -> None:
        """Save the open note now if it changed."""
        self._idle.stop()
        self._dirty_since.invalidate()
        if self._note is None or self._session.revision == self._saved_revision:
            return
        try:
            self._library.save_document(self._note.id, self._session.document)
        except SchemeUpError as error:
            self.toast.show_message(self.tr("Couldn't save: %1").replace("%1", str(error)), 6)
            return
        self._saved_revision = self._session.revision

    def _on_session_change(self, change: Change) -> None:
        if change != Change.DOCUMENT or self._note is None:
            return
        if self._session.revision == self._saved_revision:
            return
        # Save after a short pause, but never let unsaved work pile up longer than a few seconds.
        if not self._dirty_since.isValid():
            self._dirty_since.start()
        if self._dirty_since.elapsed() >= AUTOSAVE_MAX_MS:
            self.flush()
        else:
            self._idle.start()

    def _on_library_event(self, event: LibraryEvent) -> None:
        if self._note is None:
            if (
                event.kind in (EventKind.NOTES, EventKind.CONTENT)
                and self.pages.currentWidget() is self.welcome
            ):
                self.welcome.refresh()
            return
        if event.kind in (EventKind.NOTES, EventKind.TAGS) and event.note_id in (
            None,
            self._note.id,
        ):
            try:
                note = self._library.note(self._note.id)
            except SchemeUpError:
                self._note = None
                self.close_note()
                return
            if note.trashed_at is not None:
                self._note = None
                self.close_note()
                return
            self._note = note
            self._refresh_header()
        elif event.kind == EventKind.CONTENT and event.note_id == self._note.id:
            self._note = self._library.note(self._note.id)
            self._refresh_meta()

    def _refresh_header(self) -> None:
        if self._note is None:
            return
        self.editor.title_edit.setText(self._note.title)
        self.setWindowTitle(f"{self._note.title} — SchemeUp")
        self.tags.set_tags(list(self._note.tags), [t.name for t in self._library.tags()])
        self._refresh_meta()

    def _refresh_meta(self) -> None:
        if self._note is None:
            return
        note = self._note
        self.editor.meta_label.setText(
            self.tr("Edited") + f" {full_time(note.updated_at)}  ·  {human_size(note.size_bytes)}"
        )
        self.editor.meta_label.setToolTip(
            self.tr("Created")
            + f" {full_time(note.created_at)}\n"
            + self.tr("Edited")
            + f" {full_time(note.updated_at)}"
        )

    def _rename_current(self, title: str) -> None:
        if self._note is None:
            return
        if not title:
            self.editor.title_edit.setText(self._note.title)
            return
        self._library.rename_note(self._note.id, title)
        # editingFinished also fires when focus moves somewhere on purpose (a text being
        # typed on the canvas, say); only Enter, which leaves focus here, hands it back.
        if self.editor.title_edit.hasFocus():
            self.editor.focus_canvas()

    def _set_tags(self, names: list[str]) -> None:
        if self._note is not None:
            self._library.set_tags(self._note.id, names)

    def _show_editor(self) -> None:
        self.pages.setCurrentWidget(self.editor)
        self.sidebar.show_page(Page.NOTES)

    def _show_page(self, page: object) -> None:
        self.presentation.stop()
        if page == Page.NOTES:
            if self._note is not None:
                self._show_editor()
            else:
                self.pages.setCurrentWidget(self.welcome)
        elif page == Page.CALENDAR:
            self.flush()
            self.calendar_view.refresh()
            self.pages.setCurrentWidget(self.calendar_view)
        elif page == Page.BOARDS:
            self.flush()
            self.board_view.refresh()
            self.pages.setCurrentWidget(self.board_view)

    def show_board(self, board_id: int) -> None:
        self.flush()
        self.sidebar.show_page(Page.BOARDS)
        self.board_view.show_board(board_id)
        self.pages.setCurrentWidget(self.board_view)

    def show_calendar(self) -> None:
        self.sidebar.show_page(Page.CALENDAR)
        self._show_page(Page.CALENDAR)

    def show_boards(self) -> None:
        self.sidebar.show_page(Page.BOARDS)
        self._show_page(Page.BOARDS)

    def new_board(self) -> None:
        self.show_board(self._library.create_board(self.tr("New board")).id)

    def _remember_snapping(self) -> None:
        self._settings.snap_objects = self.editor.canvas.snap_objects
        self._settings.snap_grid = self.editor.canvas.snap_grid

    # Quick capture and tray

    def quick_capture(self) -> None:
        self.capture.open()

    def _captured(self, title: str, text: str, open_in_editor: bool) -> None:
        note = self._library.capture(text, title)
        if note is None:
            return
        if open_in_editor:
            self.show_and_raise()
            self.open_note(note.id)
        elif self.isVisible():
            self.toast.show_message(self.tr("Saved to Inbox: %1").replace("%1", note.title))

    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _create_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(icon("app", self._theme.accent), self)
        tray.setToolTip("SchemeUp")
        menu = QMenu()
        menu.addAction(self.tr("Quick note") + f"\t{self._settings.hotkey}", self.quick_capture)
        menu.addAction(self.tr("Open SchemeUp"), self.show_and_raise)
        menu.addSeparator()
        menu.addAction(self.tr("Quit"), self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: (
                self.show_and_raise()
                if reason == QSystemTrayIcon.ActivationReason.Trigger
                else None
            )
        )
        tray.show()
        self._tray_menu = menu
        self.tray = tray

    # Theme and settings

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(stylesheet(theme))
        self.sidebar.set_theme(theme)
        self.editor.set_theme(theme)
        self.presentation.set_theme(theme)
        self.welcome.set_theme(theme)
        self.board_view.set_theme(theme)
        self.calendar_view.set_theme(theme)
        self.tags.set_theme(theme)
        self.toast.set_theme(theme)
        self.command_palette.set_theme(theme)
        self.capture.set_theme(theme)
        self.splitter.setStyleSheet(f"QSplitter::handle {{ background: {theme.border}; }}")

    def toggle_theme(self) -> None:
        self._settings.theme = "light" if self._theme.dark else "dark"
        self.apply_theme(theme_for(self._settings.theme))
        self._env.save_settings(self._settings)

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self._settings,
            self._env.library_path,
            self._env.backups_dir,
            self._env.backup_now,
            self._env.hotkey_supported,
            self,
        )
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        updated = dialog.result_settings()
        hotkey_changed = updated.hotkey != self._settings.hotkey
        language_changed = updated.language != self._settings.language
        motion_changed = updated.motion != self._settings.motion
        self._settings = updated
        self._env.settings = updated
        self.apply_theme(theme_for(updated.theme))
        if hotkey_changed:
            error = self._env.register_hotkey(updated.hotkey)
            if error:
                QMessageBox.warning(self, self.tr("Quick capture shortcut"), error)
        self._env.save_settings(updated)
        if language_changed or motion_changed:
            self.toast.show_message(
                self.tr("Restart SchemeUp to apply the new language or motion setting."), 6
            )

    def toggle_sidebar(self) -> None:
        if self._stage is not None:
            return  # focus mode and presentations keep it hidden
        self.sidebar.setVisible(not self.sidebar.isVisible())
        self._settings.sidebar_visible = self.sidebar.isVisible()

    # Presenting and focus mode

    def start_presentation(self) -> None:
        """Present the note's frames as slides, starting from the one in view."""
        if self.presentation.active or self._note is None:
            return
        if self.pages.currentWidget() is not self.editor:
            return
        order = slides(self._session.document)
        if not order:
            self.toast.show_message(
                self.tr("Add frames to present. Each frame becomes one slide."), 5
            )
            return
        canvas = self.editor.canvas
        selected = self._session.document.bounds_of(self._session.selection)
        view_center = canvas.camera.to_world(Point(canvas.width() / 2, canvas.height() / 2))
        self.flush()
        self.presentation.start(
            order, slide_near(order, selected.center if selected else view_center)
        )
        self._sync_stage()

    def toggle_focus_mode(self) -> None:
        """Hide the sidebar, title bar and panels and go fullscreen, or bring them back."""
        if self.presentation.active:
            return
        self._focus_mode = not self._focus_mode
        self._sync_stage()
        if self._focus_mode:
            self.toast.show_message(self.tr("Focus mode. Press F11 to bring the panels back."), 4)

    def _sync_stage(self) -> None:
        """Make the window match the current mode: presenting, focus or normal."""
        if self.presentation.active:
            chrome = Chrome.NONE
        elif self._focus_mode:
            chrome = Chrome.FOCUS
        else:
            chrome = Chrome.FULL
        if chrome is Chrome.FULL:
            stage, self._stage = self._stage, None
            self.editor.set_chrome(chrome)
            if stage is not None:
                self.sidebar.setVisible(stage.sidebar)
                if not stage.fullscreen:
                    self.showMaximized() if stage.maximized else self.showNormal()
            self.editor.focus_canvas()
            return
        if self._stage is None:
            self._stage = StageMemory(
                self.sidebar.isVisible(), self.isMaximized(), self.isFullScreen()
            )
        self.sidebar.setVisible(False)
        self.editor.set_chrome(chrome)
        if not self.isFullScreen():
            self.showFullScreen()
        self.editor.focus_canvas()

    # Commands

    def _commands(self) -> list[PaletteCommand]:
        canvas = self.editor.canvas
        tr = self.tr
        commands = [
            PaletteCommand(
                tr("New note"),
                lambda: self.new_note(None, "blank"),
                "Ctrl+N",
                "file-text",
                "create",
            ),
            PaletteCommand(
                tr("Quick note"), self.quick_capture, self._settings.hotkey, "bolt", "capture inbox"
            ),
            PaletteCommand(
                tr("Search notes"), self.sidebar.focus_search, "Ctrl+F", "search", "find"
            ),
            PaletteCommand(
                tr("Toggle sidebar"), self.toggle_sidebar, "Ctrl+\\", "layout-sidebar-left-collapse"
            ),
            PaletteCommand(
                tr("Toggle dark mode"), self.toggle_theme, "Alt+Shift+D", "moon", "theme light"
            ),
            PaletteCommand(
                tr("Focus mode"),
                self.toggle_focus_mode,
                "F11",
                "arrows-maximize",
                "zen distraction fullscreen",
            ),
            PaletteCommand(tr("Settings"), self.open_settings, "Ctrl+,", "settings", "preferences"),
            PaletteCommand(
                tr("Trash"),
                lambda: self.sidebar.show_page(Page.TRASH, emit=True),
                "",
                "trash",
                "deleted",
            ),
            PaletteCommand(tr("Open calendar"), self.show_calendar, "", "calendar", "dates days"),
            PaletteCommand(tr("Open boards"), self.show_boards, "", "layout-kanban", "kanban"),
            PaletteCommand(tr("New board"), self.new_board, "", "layout-kanban", "kanban trello"),
            PaletteCommand(tr("Import a file…"), self.import_note, "", "upload", "excalidraw open"),
        ]
        for template in TEMPLATES[2:]:
            commands.append(
                PaletteCommand(
                    tr("New note from template: %1").replace("%1", tr(template.name)),
                    self._new_from(template.id),
                    "",
                    "template",
                )
            )
        if self._note is not None:
            note_id = self._note.id
            commands += [
                PaletteCommand(tr("Zoom to fit"), canvas.fit_content, "Shift+1", "focus-centered"),
                PaletteCommand(tr("Reset zoom"), canvas.reset_zoom, "Ctrl+0", "zoom-in"),
                PaletteCommand(tr("Back to content"), canvas.recenter, "", "focus-centered"),
                PaletteCommand(
                    tr("Toggle snapping to shapes"),
                    lambda: canvas.set_snapping(objects=not canvas.snap_objects),
                    "Alt+S",
                    "ruler-2",
                ),
                PaletteCommand(
                    tr("Toggle snapping to the sheet"),
                    lambda: canvas.set_snapping(grid=not canvas.snap_grid),
                    "Ctrl+'",
                    "grid-dots",
                ),
                PaletteCommand(
                    tr("Present frames as slides"),
                    self.start_presentation,
                    "F5",
                    "presentation",
                    "slideshow talk",
                ),
                PaletteCommand(
                    tr("Export…"), self.export_note, "Ctrl+Shift+E", "download", "pdf png svg word"
                ),
                PaletteCommand(
                    tr("Copy as PNG"), self.copy_png, "Shift+Alt+C", "copy", "clipboard image"
                ),
                PaletteCommand(tr("Rename note"), self._focus_title, "F2", "file-text"),
                PaletteCommand(tr("Duplicate note"), self._duplicate_current, "", "copy"),
                PaletteCommand(
                    tr("Move note to trash"), lambda: self._library.trash_note(note_id), "", "trash"
                ),
                PaletteCommand(tr("Close note"), self.close_note, "Ctrl+W", "x"),
                PaletteCommand(tr("Undo"), self._session.undo, "Ctrl+Z", "arrow-back-up"),
                PaletteCommand(tr("Redo"), self._session.redo, "Ctrl+Shift+Z", "arrow-forward-up"),
            ]
            for kind, name in (
                (ToolKind.RECTANGLE, tr("Rectangle")),
                (ToolKind.DIAMOND, tr("Diamond")),
                (ToolKind.ELLIPSE, tr("Ellipse")),
                (ToolKind.ARROW, tr("Arrow")),
                (ToolKind.LINE, tr("Line")),
                (ToolKind.DRAW, tr("Draw")),
                (ToolKind.TEXT, tr("Text")),
                (ToolKind.FRAME, tr("Frame")),
                (ToolKind.IMAGE, tr("Insert image")),
            ):
                commands.append(
                    PaletteCommand(
                        tr("Tool: %1").replace("%1", name),
                        self._use_tool(kind),
                        "",
                        "pointer",
                    )
                )
        commands.append(PaletteCommand(tr("Quit"), self.quit, "Ctrl+Q", "x", "exit close"))
        return commands

    def _new_from(self, template_id: str) -> Callable[[], None]:
        return lambda: self.new_note(None, template_id)

    def _use_tool(self, kind: ToolKind) -> Callable[[], None]:
        return lambda: self.editor.canvas.set_tool(kind)

    def _duplicate_current(self) -> None:
        if self._note is not None:
            self.open_note(self._library.duplicate_note(self._note.id).id)

    def export_note(self) -> None:
        if self._note is None or self._env.exporter is None:
            return
        from schemeup.ui.export_dialog import ExportDialog

        self.flush()
        dialog = ExportDialog(
            self._session.document,
            self._session.selection,
            self._note.title,
            self._note.tags,
            self.editor.canvas.renderer,
            self._env.exporter,
            self._theme,
            self,
        )
        if dialog.exec() == ExportDialog.DialogCode.Accepted and dialog.exported_path is not None:
            self.toast.show_message(self.tr("Exported %1").replace("%1", dialog.exported_path.name))

    def copy_png(self) -> None:
        from schemeup.rendering.export_render import export_region, render_image

        document = self._session.document
        selection = self._session.selection
        region = export_region(document, selection)
        if region is None:
            return
        image = render_image(
            document,
            region,
            self.editor.canvas.renderer,
            2.0,
            dark=self._theme.dark,
            only=selection or None,
        )
        QGuiApplication.clipboard().setImage(image)
        self.toast.show_message(self.tr("Copied as PNG"))

    def import_note(self) -> None:
        if self._env.importer is None:
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import"),
            "",
            self.tr("Excalidraw or SchemeUp files (*.excalidraw *.schemeup *.json)"),
        )
        if not path:
            return
        try:
            imported = self._env.importer.read(Path(path))
            if self._assets is not None:
                for content in imported.files.values():
                    self._assets.put(content, "image/png")
            note = self._library.import_document(imported.title, imported.document)
            if imported.tags:
                self._library.set_tags(note.id, imported.tags)
        except SchemeUpError as error:
            QMessageBox.warning(self, self.tr("Import failed"), str(error))
            return
        self.open_note(note.id)
        self.toast.show_message(self.tr("Imported %1").replace("%1", note.title))

    def _focus_title(self) -> None:
        self.editor.title_edit.setFocus()
        self.editor.title_edit.selectAll()

    def _add_shortcuts(self) -> None:
        bindings: list[tuple[tuple[str, ...], Callable[[], None]]] = [
            (("Ctrl+N",), lambda: self.new_note(None, "blank")),
            (("Ctrl+K",), lambda: self.command_palette.open_over(self)),
            (("Ctrl+F",), self.sidebar.focus_search),
            (("Ctrl+\\",), self.toggle_sidebar),
            (("Alt+Shift+D",), self.toggle_theme),
            (("Ctrl+,",), self.open_settings),
            (("Ctrl+W",), self.close_note),
            (("Ctrl+Shift+E",), self.export_note),
            (("Ctrl+S",), self.flush),
            (("F2",), self._focus_title),
            (("F5",), self.start_presentation),
            (("F11",), self.toggle_focus_mode),
            (("Ctrl+Q",), self.quit),
        ]
        for keys, handler in bindings:
            action = QAction(self)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(handler)
            self.addAction(action)

    # Lifecycle

    def save_state(self) -> None:
        self._focus_mode = False
        self.presentation.stop()
        self._sync_stage()  # so the saved geometry is the window's, not a fullscreen stage
        self.flush()
        self._settings.window_geometry = bytes(self.saveGeometry().toBase64().data()).decode(
            "ascii"
        )
        self._env.save_settings(self._settings)

    def quit(self) -> None:
        self._quitting = True
        self.save_state()
        self._settings.clean_exit = True
        self._env.save_settings(self._settings)
        if self.tray is not None:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_state()
        if not self._quitting and self._settings.close_to_tray and self.tray is not None:
            # Stay resident in the tray so quick capture opens instantly.
            event.ignore()
            self.hide()
            return
        self.quit()
        event.accept()

    def sizeHint(self) -> QSize:
        return QSize(1400, 880)
