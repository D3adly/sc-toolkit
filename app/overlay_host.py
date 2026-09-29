"""The main app's side of the overlay: starts the overlay process
(`sc-toolkit --overlay`, see app.ui.overlay) and sends it commands.

The overlay is started with the launcher so its global hotkeys work right
away, and it is told to quit when the launcher quits (it also watches the
launcher's PID, in case the launcher crashes). If it exits unexpectedly it
is restarted (a few times at most); its output goes to overlay.log in the
cache folder.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer

from app import config, hotkeys, ipc

LOG_FILE = config.CACHE_DIR / "overlay.log"
MAX_RESTARTS = 3            # within RESTART_WINDOW seconds
RESTART_WINDOW = 60


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
        self._wanted = False            # False while stopping on purpose
        self._restarts: list[float] = []

    def running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self) -> None:
        if self.running():
            return
        self._wanted = True
        cmd = overlay_command()
        proc = QProcess(self)
        proc.setProcessEnvironment(overlay_environment())
        proc.setProcessChannelMode(QProcess.MergedChannels)
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            if LOG_FILE.is_file() and LOG_FILE.stat().st_size > 512 * 1024:
                LOG_FILE.unlink()
            with LOG_FILE.open("a") as log:
                log.write(f"--- overlay start {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            proc.setStandardOutputFile(str(LOG_FILE), QProcess.Append)
        except OSError:
            proc.setProcessChannelMode(QProcess.ForwardedChannels)
        if not getattr(sys, "frozen", False):
            proc.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        proc.finished.connect(self._on_finished)
        proc.start(cmd[0], cmd[1:])
        self._proc = proc

    def _on_finished(self, code: int, status) -> None:
        # Whatever happened, don't leave KWin holding the overlay's keys.
        hotkeys.release()
        if not self._wanted:
            return
        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < RESTART_WINDOW] + [now]
        if len(self._restarts) <= MAX_RESTARTS:
            QTimer.singleShot(1000, self.start)

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
        self._wanted = False
        ipc.send(ipc.OVERLAY, "quit")
        if self._proc is not None and self.running() and not self._proc.waitForFinished(1500):
            self._proc.kill()
            self._proc.waitForFinished(500)
