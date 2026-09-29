"""The main app's side of the overlay: starts the overlay process
(`sc-toolkit --overlay`, see app.ui.overlay) and sends it commands.

The overlay is started with the launcher so its global hotkeys work right
away, and it is told to quit when the launcher quits (it also watches the
launcher's PID, in case the launcher crashes).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment

from app import ipc


def overlay_command() -> list[str]:
    args = ["--overlay", "--parent-pid", str(os.getpid())]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "app.main", *args]


def overlay_environment() -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    if sys.platform.startswith("linux") and env.contains("DISPLAY"):
        # XWayland: an X11 window can keep itself above the (also XWayland)
        # game and grab the global hotkeys; a Wayland one can do neither.
        env.insert("QT_QPA_PLATFORM", "xcb")
    return env


class OverlayHost(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None

    def running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self) -> None:
        if self.running():
            return
        cmd = overlay_command()
        proc = QProcess(self)
        proc.setProcessEnvironment(overlay_environment())
        proc.setProcessChannelMode(QProcess.ForwardedChannels)
        if not getattr(sys, "frozen", False):
            proc.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        proc.start(cmd[0], cmd[1:])
        self._proc = proc

    def send(self, command: str) -> None:
        """Delivers a command, starting the overlay first if it isn't running."""
        if ipc.send(ipc.OVERLAY, command):
            return
        self.start()
        if self._proc is not None and self._proc.waitForStarted(3000):
            # Give it a moment to build its window and start listening.
            for _ in range(20):
                if ipc.send(ipc.OVERLAY, command):
                    return
                self._proc.waitForFinished(150)

    def stop(self) -> None:
        ipc.send(ipc.OVERLAY, "quit")
        if self._proc is not None and self.running() and not self._proc.waitForFinished(1500):
            self._proc.kill()
            self._proc.waitForFinished(500)
