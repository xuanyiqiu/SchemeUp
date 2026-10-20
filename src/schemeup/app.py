"""Composition root: the one place that wires the layers together."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from schemeup import __version__
from schemeup.application.editor import EditorSession
from schemeup.application.library import LibraryService
from schemeup.domain.document import Document
from schemeup.domain.errors import SchemeUpError, StorageError
from schemeup.domain.templates import welcome
from schemeup.infrastructure.backup import Backups
from schemeup.infrastructure.database import Database
from schemeup.infrastructure.library_store import SqliteAssetStore, SqliteLibrary
from schemeup.infrastructure.platform.hotkey import GlobalHotkey
from schemeup.infrastructure.platform.motion import wants_reduced_motion
from schemeup.infrastructure.platform.single_instance import InstanceServer, send_to_running
from schemeup.infrastructure.settings_store import JsonSettingsStore
from schemeup.rendering.fonts import register_fonts
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.main_window import Environment, MainWindow


def data_directory() -> Path:
    override = os.environ.get("SCHEMEUP_DATA_DIR")
    if override:
        return Path(override)
    return Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv
    wants_capture = "--capture" in args
    app = QApplication(args)
    app.setApplicationName("SchemeUp")
    app.setApplicationVersion(__version__)
    # Closing the window keeps SchemeUp in the tray; quitting is explicit.
    app.setQuitOnLastWindowClosed(False)

    if send_to_running("capture" if wants_capture else "show"):
        return 0

    register_fonts()
    data_dir = data_directory()
    data_dir.mkdir(parents=True, exist_ok=True)
    store = JsonSettingsStore(data_dir / "settings.json")
    settings = store.load()
    crashed = not settings.clean_exit
    settings.clean_exit = False
    store.save(settings)

    library_path = data_dir / "library.sqlite3"
    try:
        db = Database(library_path)
    except StorageError as error:
        QMessageBox.critical(None, "SchemeUp", f"The library could not be opened.\n\n{error}")
        return 1
    measurer = QtTextMeasurer()
    library = LibraryService(SqliteLibrary(db), measurer)
    assets = SqliteAssetStore(db)
    library.purge_old_trash()

    backups_dir = Path(settings.backups_dir) if settings.backups_dir else data_dir / "backups"
    backups = Backups(db, backups_dir)
    with contextlib.suppress(OSError, SchemeUpError):
        backups.run_if_due(datetime.now())

    def backup_now() -> Path | None:
        try:
            return backups.run(datetime.now())
        except (OSError, SchemeUpError):
            return None

    configured = None if settings.motion == "system" else settings.motion
    motion = os.environ.get("SCHEMEUP_MOTION") or configured
    session = EditorSession(Document(), measurer)
    window: MainWindow | None = None
    hotkey = GlobalHotkey(lambda: window.quick_capture() if window else None)

    def register_hotkey(text: str) -> str:
        return "" if hotkey.register(text) else hotkey.error

    env = Environment(
        settings=settings,
        save_settings=store.save,
        library_path=library_path,
        backups_dir=backups_dir,
        backup_now=backup_now,
        register_hotkey=register_hotkey,
        hotkey_supported=hotkey.supported,
        reduce_motion=wants_reduced_motion(motion),
    )
    window = MainWindow(library, session, assets=assets, env=env)
    hotkey_error = register_hotkey(settings.hotkey) if hotkey.supported else ""

    def on_command(command: str) -> None:
        assert window is not None
        if command == "capture":
            window.quick_capture()
        else:
            window.show_and_raise()

    server = InstanceServer(on_command)
    server.listen()

    if not settings.welcome_seen:
        with contextlib.suppress(SchemeUpError):
            note = library.import_document("Welcome to SchemeUp", welcome(datetime.now()))
            settings.last_note_id = note.id
        settings.welcome_seen = True
        store.save(settings)

    window.show()
    if settings.last_note_id is not None:
        try:
            note_info = library.note(settings.last_note_id)
            if note_info.trashed_at is None:
                window.open_note(note_info.id)
        except SchemeUpError:
            settings.last_note_id = None
    if wants_capture:
        QTimer.singleShot(0, window.quick_capture)
    if crashed:
        window.toast.show_message(
            window.tr("SchemeUp didn't close properly last time. Your notes are safe."), 6
        )
    elif hotkey_error:
        window.toast.show_message(hotkey_error, 6)

    code = app.exec()
    hotkey.unregister()
    db.close()
    return code
