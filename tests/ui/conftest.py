from collections.abc import Iterator
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from schemeup.application.editor import EditorSession
from schemeup.application.library import LibraryService
from schemeup.application.ports import MemoryAssetStore
from schemeup.application.settings import MemorySettingsStore, Settings
from schemeup.domain.document import Document
from schemeup.infrastructure.database import Database
from schemeup.infrastructure.library_store import SqliteAssetStore, SqliteLibrary
from schemeup.rendering.fonts import register_fonts
from schemeup.rendering.text import QtTextMeasurer
from schemeup.ui.canvas.view import CanvasView
from schemeup.ui.main_window import Environment, MainWindow

NO_MODS = Qt.KeyboardModifier.NoModifier


@pytest.fixture(autouse=True)
def _fonts(qapp: QApplication) -> None:
    register_fonts()


def press(widget: QWidget, key: Qt.Key, mods: Qt.KeyboardModifier = NO_MODS) -> None:
    """Type one key into a widget."""
    QTest.keyClick(widget, key, mods)


class Mouse:
    """Sends real mouse events to a widget, in its own coordinates."""

    def __init__(self, widget: QWidget) -> None:
        self.widget = widget

    def _send(
        self,
        kind: QEvent.Type,
        x: float,
        y: float,
        buttons: Qt.MouseButton,
        mods: Qt.KeyboardModifier,
    ) -> None:
        pos = QPointF(x, y)
        event = QMouseEvent(
            kind, pos, self.widget.mapToGlobal(pos), Qt.MouseButton.LeftButton, buttons, mods
        )
        QApplication.sendEvent(self.widget, event)

    def press(self, x: float, y: float, mods: Qt.KeyboardModifier = NO_MODS) -> None:
        self._send(QEvent.Type.MouseButtonPress, x, y, Qt.MouseButton.LeftButton, mods)

    def move(self, x: float, y: float, mods: Qt.KeyboardModifier = NO_MODS) -> None:
        self._send(QEvent.Type.MouseMove, x, y, Qt.MouseButton.LeftButton, mods)

    def release(self, x: float, y: float, mods: Qt.KeyboardModifier = NO_MODS) -> None:
        self._send(QEvent.Type.MouseButtonRelease, x, y, Qt.MouseButton.NoButton, mods)

    def drag(
        self, x0: float, y0: float, x1: float, y1: float, mods: Qt.KeyboardModifier = NO_MODS
    ) -> None:
        self.press(x0, y0, mods)
        for i in range(1, 9):
            self.move(x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8, mods)
        self.release(x1, y1, mods)

    def click(self, x: float, y: float) -> None:
        self.press(x, y)
        self.release(x, y)

    def double_click(self, x: float, y: float) -> None:
        self.click(x, y)
        self._send(QEvent.Type.MouseButtonDblClick, x, y, Qt.MouseButton.LeftButton, NO_MODS)
        self.release(x, y)


@pytest.fixture
def session() -> EditorSession:
    return EditorSession(Document(), QtTextMeasurer())


@pytest.fixture
def canvas(qtbot: QtBot, session: EditorSession) -> Iterator[CanvasView]:
    view = CanvasView(session, assets=MemoryAssetStore(), reduce_motion=True)
    qtbot.addWidget(view)
    view.resize(1000, 700)
    view.show()
    qtbot.waitExposed(view)
    # Snapping is tested in the domain; here it would only make positions harder to predict.
    view.set_snapping(objects=False, grid=False)
    yield view


@pytest.fixture
def mouse(canvas: CanvasView) -> Mouse:
    return Mouse(canvas)


@pytest.fixture
def library() -> LibraryService:
    return LibraryService(SqliteLibrary(Database(":memory:")), QtTextMeasurer())


@pytest.fixture
def window(qtbot: QtBot, library: LibraryService, tmp_path: Any) -> Iterator[MainWindow]:
    store = MemorySettingsStore(Settings(close_to_tray=False, theme="light"))
    env = Environment(
        settings=store.load(),
        save_settings=store.save,
        library_path=tmp_path / "library.sqlite3",
        backups_dir=tmp_path / "backups",
        backup_now=lambda: None,
        register_hotkey=lambda _text: "",
        hotkey_supported=False,
        reduce_motion=True,
    )
    session = EditorSession(Document(), QtTextMeasurer())
    db = Database(":memory:")
    win = MainWindow(library, session, assets=SqliteAssetStore(db), env=env)
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win._quitting = True
