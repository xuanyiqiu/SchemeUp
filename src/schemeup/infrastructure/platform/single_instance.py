"""Keeps one running instance and lets later launches pass it a command.

A second `schemeup` (or `schemeup --capture`) connects to the first one over
a local socket, sends its command and exits. That is also how macOS and Linux
users get quick capture from an OS keyboard shortcut.
"""

from __future__ import annotations

import getpass
from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name() -> str:
    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = "user"
    return f"schemeup-{user}"


def send_to_running(command: str, timeout_ms: int = 300) -> bool:
    """Send `command` to an instance that is already running. False if there is none."""
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(command.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


class InstanceServer(QObject):
    def __init__(self, on_command: Callable[[str], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_command = on_command
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept)

    def listen(self) -> bool:
        name = server_name()
        if not self._server.listen(name):
            # A stale socket from a crashed instance blocks the name on Unix.
            QLocalServer.removeServer(name)
            return self._server.listen(name)
        return True

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))

    def _read(self, socket: QLocalSocket) -> None:
        command = bytes(socket.readAll().data()).decode("utf-8", errors="ignore").strip()
        socket.disconnectFromServer()
        if command:
            self._on_command(command)
