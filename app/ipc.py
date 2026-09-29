"""Tiny local IPC between SC-Toolkit processes, over QLocalServer/Socket
(a named pipe on Windows, a Unix socket on Linux; per user).

- The **main** app listens on `MAIN`: a second launch, or a command such as
  `sc-toolkit --toggle-overlay` (bound to a desktop shortcut), is forwarded
  to the running instance instead of starting another one.
- The **overlay** process listens on `OVERLAY`, so the main app (tray menu,
  forwarded commands) can drive it.

Messages are single lines of text: "show", "toggle-overlay", "quit", …
"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_USER = "".join(c for c in getpass.getuser() if c.isalnum()) or "user"
MAIN = f"sc-toolkit-main-{_USER}"
OVERLAY = f"sc-toolkit-overlay-{_USER}"
TIMEOUT_MS = 500


def send(server: str, command: str) -> bool:
    """Sends one command; False if nobody is listening."""
    sock = QLocalSocket()
    sock.connectToServer(server)
    if not sock.waitForConnected(TIMEOUT_MS):
        return False
    sock.write((command + "\n").encode())
    # flush() often writes everything at once; waitForBytesWritten() then
    # has nothing left to wait for and reports False.
    ok = sock.flush() or sock.bytesToWrite() == 0 or sock.waitForBytesWritten(TIMEOUT_MS)
    ok = ok and sock.bytesToWrite() == 0
    sock.disconnectFromServer()
    return ok


class CommandServer(QObject):
    """Receives commands for this process; emits `command(str)` per line."""

    command = Signal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        self.name = name

    def listen(self) -> bool:
        """False if another process already serves this name."""
        # Ask first: with UserAccessOption, Qt creates the socket under a
        # temporary name and renames it into place, which would silently
        # replace a live server's socket (leaving that process unreachable).
        probe = QLocalSocket()
        probe.connectToServer(self.name)
        if probe.waitForConnected(TIMEOUT_MS):
            probe.disconnectFromServer()
            return False
        if probe.error() not in (QLocalSocket.ConnectionRefusedError, QLocalSocket.ServerNotFoundError):
            return False   # there, just slow to answer (e.g. still starting)
        if self._server.listen(self.name):
            return True
        # Refused: a stale socket from a crashed run (Unix) blocks the name.
        QLocalServer.removeServer(self.name)
        return self._server.listen(self.name)

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock: QLocalSocket) -> None:
        while sock.canReadLine():
            line = bytes(sock.readLine()).decode(errors="replace").strip()
            if line:
                self.command.emit(line)
