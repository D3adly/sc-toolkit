"""Process presence: the check that refuses to restore/launch into an
already-running game, and GameWatcher, which follows whether the RSI
Launcher and the game are running (for the launcher's state light),
whoever started them and whenever SC-Toolbox itself was started.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from app.osutil import GAME_EXE, LAUNCHER_EXE, is_game_running, running_game_processes

__all__ = ["is_game_running", "GameWatcher", "READY", "LAUNCHER", "GAME"]

READY, LAUNCHER, GAME = "ready", "launcher", "game"
POLL_MS = 3000


def state_of(found: set[str]) -> str:
    if GAME_EXE in found:
        return GAME
    if LAUNCHER_EXE in found:
        return LAUNCHER
    return READY


class GameWatcher(QObject):
    """Emits `changed(state)` — ready (neither runs), launcher (the RSI
    Launcher runs), game (Star Citizen runs) — at start and whenever it
    changes. The process scan runs off the UI thread every few seconds."""

    changed = Signal(str)
    _scanned = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state: str | None = None
        self._busy = False
        self._scanned.connect(self._on_scanned)
        self._timer = QTimer(self, interval=POLL_MS, timeout=self.poll)

    def start(self) -> None:
        self.poll()
        self._timer.start()

    def poll(self) -> None:
        if self._busy:
            return
        self._busy = True

        def work():
            try:
                state = state_of(running_game_processes())
            except Exception:
                state = self.state or READY
            self._scanned.emit(state)
        threading.Thread(target=work, daemon=True).start()

    def _on_scanned(self, state: str) -> None:
        self._busy = False
        if state != self.state:
            self.state = state
            self.changed.emit(state)
