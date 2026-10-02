"""Notices Star Citizen game updates as they happen, from the RSI Launcher's
log (setting `rsi_log_path`, auto-detected when empty). No polling: the
file is watched with QFileSystemWatcher and only new lines are read.

The launcher logs, per update:
    [Pipeline] Installing Star Citizen LIVE 4.10.1-live.12660092 at C:\\…\\StarCitizen (type: update, …)
    …                                              (Data.p4k is being rewritten)
    [PatcherPhase] Delta update completed (SC LIVE 4.10.1-live.12660092) in C:\\…\\StarCitizen\\LIVE

While an update runs, app.datahub leaves that channel's game files alone and
the tools keep the previous version's cached data; when it completes, the
hub reads the new files in one pass. If the log can't be found or its format
changes, the hub's checks at SC-Toolkit and game start still catch updates.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from app import settings

_STARTED = re.compile(r"\[Pipeline\] Installing Star Citizen (?P<channel>\S+) (?P<version>\S+) at ")
_COMPLETED = re.compile(r"\[PatcherPhase\] Delta update completed \(SC (?P<channel>\S+) (?P<version>\S+)\)")
# An update that stops without "completed": cancelled, failed or paused.
_STOPPED = re.compile(r"\[Pipeline\].*\b(cancel(l)?ed|aborted|failed|paused)\b", re.I)
TAIL_BYTES = 512 * 1024             # read at start: is an update running right now?


def log_path() -> Path | None:
    s = settings.current()
    path = s.rsi_log_path or settings.find_rsi_log(s.live_dir, s.launch_path)
    return Path(path) if path and Path(path).is_file() else None


class PatchWatcher(QObject):
    started = Signal(str, str)          # channel (LIVE, PTU…), version
    completed = Signal(str, str)
    stopped = Signal(str)               # channel: the update ended without completing

    def __init__(self, parent=None):
        super().__init__(parent)
        self.updating: dict[str, str] = {}      # channel → version being installed
        self._path: Path | None = None
        self._offset = 0
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_changed)
        self._watcher.directoryChanged.connect(self._on_changed)   # log recreated / rotated
        # Bursts of writes arrive as many change events: read once they settle.
        self._debounce = QTimer(self, singleShot=True, interval=500)
        self._debounce.timeout.connect(self._read_new)

    def start(self) -> None:
        """(Re)starts watching the configured / detected log."""
        for watched in self._watcher.files() + self._watcher.directories():
            self._watcher.removePath(watched)
        self._path = log_path()
        self.updating.clear()
        if self._path is None:
            return
        self._watcher.addPath(str(self._path))
        self._watcher.addPath(str(self._path.parent))
        size = self._path.stat().st_size
        self._offset = max(0, size - TAIL_BYTES)
        self._read_new(initial=True)

    def _on_changed(self, _path: str) -> None:
        if self._path is not None and str(self._path) not in self._watcher.files() and self._path.is_file():
            self._watcher.addPath(str(self._path))      # recreated: watch the new file
        self._debounce.start()

    def _read_new(self, initial: bool = False) -> None:
        if self._path is None:
            return
        try:
            size = self._path.stat().st_size
            if size < self._offset:
                self._offset = 0                         # rotated / truncated
            with self._path.open("rb") as f:
                f.seek(self._offset)
                data = f.read()
        except OSError:
            return
        # Only whole lines; a half-written last line is read next time.
        end = data.rfind(b"\n") + 1
        if not end:
            return
        self._offset += end
        for line in data[:end].decode("utf-8", "replace").splitlines():
            self._line(line, initial)

    def _line(self, line: str, quiet: bool) -> None:
        m = _STARTED.search(line)
        if m:
            self.updating[m["channel"]] = m["version"]
            if not quiet:
                self.started.emit(m["channel"], m["version"])
            return
        m = _COMPLETED.search(line)
        if m:
            self.updating.pop(m["channel"], None)
            if not quiet:
                self.completed.emit(m["channel"], m["version"])
            return
        if self.updating and _STOPPED.search(line):
            for channel in list(self.updating):
                self.updating.pop(channel)
                if not quiet:
                    self.stopped.emit(channel)

    def game_started(self) -> None:
        """The game can't run while it's being updated: whatever the log
        said last, no update is in progress any more."""
        for channel in list(self.updating):
            self.updating.pop(channel)
            self.stopped.emit(channel)
