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
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer

from app import config, hotkeys, ipc

LOG_FILE = config.CACHE_DIR / "overlay.log"
MAX_RESTARTS = 3            # within RESTART_WINDOW seconds
RESTART_WINDOW = 60


SYSTEM_PYTHON = Path("/usr/bin/python3")
_layer_shell_ok: bool | None = None


def _app_site_packages() -> list[str]:
    import site

    return [p for p in site.getsitepackages() if Path(p).is_dir()]


def layer_shell_available() -> bool:
    """KDE Wayland overlay (app.ui.layer_overlay): needs a Wayland session,
    the system's LayerShellQt, and a system Python with the system's
    PySide6 (LayerShellQt's Qt plugin only loads into the Qt it was built
    for, not the Qt bundled with our PySide6), the same Python version as
    ours (it borrows our other libraries). Checked once; SCT_OVERLAY_BACKEND=x11
    forces the X11 overlay."""
    global _layer_shell_ok
    if _layer_shell_ok is None:
        _layer_shell_ok = False
        if (sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY")
                and os.environ.get("SCT_OVERLAY_BACKEND", "").lower() != "x11"
                and not getattr(sys, "frozen", False) and SYSTEM_PYTHON.is_file()):
            check = (
                "import ctypes, os, sys\n"
                f"assert sys.version_info[:2] == {tuple(sys.version_info[:2])}\n"
                "sys.path.extend(os.environ['SCT_EXTRA_SITE'].split(os.pathsep))\n"
                "import PySide6.QtCore, shiboken6, psutil, platformdirs\n"
                "ctypes.CDLL('libLayerShellQtInterface.so.6')\n"
            )
            env = dict(os.environ, SCT_EXTRA_SITE=os.pathsep.join(_app_site_packages()))
            try:
                result = subprocess.run([str(SYSTEM_PYTHON), "-c", check], env=env, capture_output=True,
                                        text=True, timeout=20)
                _layer_shell_ok = result.returncode == 0
                if not _layer_shell_ok:
                    _note(f"layer-shell overlay unavailable, using X11: {result.stderr.strip()[-300:]}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                _note(f"layer-shell overlay check failed, using X11: {exc}")
    return _layer_shell_ok


def _note(text: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as log:
            log.write(f"launcher: {text}\n")
    except OSError:
        pass


def overlay_command() -> list[str]:
    args = ["--overlay", "--parent-pid", str(os.getpid())]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    if layer_shell_available():
        return [str(SYSTEM_PYTHON), "-m", "app.main", *args, "--layer-shell"]
    return [sys.executable, "-m", "app.main", *args]


def overlay_environment() -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    if layer_shell_available():
        env.insert("SCT_EXTRA_SITE", os.pathsep.join(_app_site_packages()))
        env.insert("QT_QPA_PLATFORM", "wayland")
        env.insert("QT_WAYLAND_SHELL_INTEGRATION", "layer-shell")
    elif sys.platform.startswith("linux") and env.contains("DISPLAY"):
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
