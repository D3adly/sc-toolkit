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
import socket
import struct
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
LAYER_SHELL_LIB = "libLayerShellQtInterface.so.6"
_layer_shell: str | None = None       # "bundled", "system" or "" (X11); set on first check


def _app_site_packages() -> list[str]:
    import site

    return [p for p in site.getsitepackages() if Path(p).is_dir()]


def bundled_layer_shell() -> Path | None:
    """Our own LayerShellQt build (packaging/build_layershellqt.sh), made for
    the Qt inside our PySide6, laid out as lib/ + plugins/. The frozen Linux
    build ships it inside PySide6/Qt; a source checkout uses
    build/layershellqt once that script has been run."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) / "PySide6" / "Qt"
    else:
        base = Path(__file__).resolve().parent.parent / "build" / "layershellqt"
    plugin = base / "plugins" / "wayland-shell-integration" / "liblayer-shell.so"
    return base if (base / "lib" / LAYER_SHELL_LIB).is_file() and plugin.is_file() else None


def wayland_globals() -> set[str]:
    """Interface names the Wayland compositor advertises (wl_registry
    globals), read with the bare wire protocol: get_registry, then a sync
    whose done event marks the end of the list."""
    name = os.environ.get("WAYLAND_DISPLAY", "")
    path = name if name.startswith("/") else os.path.join(os.environ.get("XDG_RUNTIME_DIR", ""), name)
    found: set[str] = set()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(path)
        # wl_display (id 1): get_registry -> id 2 (opcode 1), sync -> callback id 3 (opcode 0).
        sock.sendall(struct.pack("<III", 1, 12 << 16 | 1, 2) + struct.pack("<III", 1, 12 << 16 | 0, 3))
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                raise OSError("Wayland compositor closed the connection")
            data += chunk
            while len(data) >= 8:
                obj, size_op = struct.unpack_from("<II", data)
                size, opcode = size_op >> 16, size_op & 0xFFFF
                if size < 8 or len(data) < size:
                    break
                if obj == 2 and opcode == 0:          # wl_registry.global(name, interface, version)
                    length = struct.unpack_from("<I", data, 12)[0]
                    found.add(data[16:16 + length - 1].decode(errors="replace"))
                elif obj == 3:                         # wl_callback.done: the list is complete
                    return found
                data = data[size:]


def _layer_shell_mode() -> str:
    """Which layer-shell overlay (app.ui.layer_overlay) this system can run:
    "bundled" (our own LayerShellQt, see bundled_layer_shell), "system" (a
    source checkout without it: the system Python + the system's PySide6
    and LayerShellQt, since a distro's LayerShellQt only loads into the
    distro's Qt; it borrows our other libraries, so the Python versions must
    match) or "" for the X11 overlay. Needs a Wayland session whose
    compositor offers wlr-layer-shell (KDE Plasma does, GNOME doesn't).
    Checked once; SCT_OVERLAY_BACKEND=x11 forces the X11 overlay. Why the
    X11 overlay isn't enough on KDE Wayland: ~/.ai/plans/sc-toolkit-overlay-attempts.md."""
    global _layer_shell
    if _layer_shell is None:
        _layer_shell = ""
        if not (sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY")):
            return _layer_shell
        if os.environ.get("SCT_OVERLAY_BACKEND", "").lower() == "x11":
            _note("layer-shell overlay off (SCT_OVERLAY_BACKEND=x11), using X11")
            return _layer_shell
        try:
            if "zwlr_layer_shell_v1" not in wayland_globals():
                _note("the compositor has no wlr-layer-shell, using the X11 overlay")
                return _layer_shell
        except (OSError, struct.error) as exc:
            _note(f"couldn't query the Wayland compositor, using the X11 overlay: {exc}")
            return _layer_shell
        if bundled_layer_shell():
            _layer_shell = "bundled"
        elif getattr(sys, "frozen", False):
            _note("this build has no bundled LayerShellQt, using the X11 overlay")
        elif SYSTEM_PYTHON.is_file():
            check = (
                "import ctypes, os, sys\n"
                f"assert sys.version_info[:2] == {tuple(sys.version_info[:2])}\n"
                "sys.path.extend(os.environ['SCT_EXTRA_SITE'].split(os.pathsep))\n"
                "import PySide6.QtCore, shiboken6, psutil, platformdirs\n"
                f"ctypes.CDLL('{LAYER_SHELL_LIB}')\n"
            )
            env = dict(os.environ, SCT_EXTRA_SITE=os.pathsep.join(_app_site_packages()))
            try:
                result = subprocess.run([str(SYSTEM_PYTHON), "-c", check], env=env, capture_output=True,
                                        text=True, timeout=20)
                if result.returncode == 0:
                    _layer_shell = "system"
                else:
                    _note("no bundled LayerShellQt (packaging/build_layershellqt.sh) and the system one "
                          f"doesn't fit, using X11: {result.stderr.strip()[-300:]}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                _note(f"layer-shell overlay check failed, using X11: {exc}")
        if _layer_shell:
            _note(f"layer-shell overlay ({_layer_shell} LayerShellQt)")
    return _layer_shell


def layer_shell_available() -> bool:
    return bool(_layer_shell_mode())


def _note(text: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as log:
            log.write(f"launcher: {text}\n")
    except OSError:
        pass


def overlay_command() -> list[str]:
    args = ["--overlay", "--parent-pid", str(os.getpid())]
    mode = _layer_shell_mode()
    if mode:
        args.append("--layer-shell")
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    python = str(SYSTEM_PYTHON) if mode == "system" else sys.executable
    return [python, "-m", "app.main", *args]


def overlay_environment() -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    mode = _layer_shell_mode()
    if mode:
        if mode == "bundled":
            base = bundled_layer_shell()
            env.insert("SCT_LAYER_SHELL_LIB", str(base / "lib" / LAYER_SHELL_LIB))
            env.insert("QT_PLUGIN_PATH", str(base / "plugins"))
        else:
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
