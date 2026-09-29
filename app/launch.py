"""Launches the game via the launch script chosen in settings (normally the
LUG Helper's sc-launch.sh, or RSI Launcher.exe on Windows), then follows
the session:

- START restores the chosen profile/backup, then opens the RSI Launcher.
- Every time the game itself (StarCitizen.exe) exits, keybinds are backed
  up right away. The RSI Launcher may stay open, and a new game start is
  tracked again.
- The session ends once both the launcher and the game are gone.

CLOSE ends the launcher's process tree, so it's refused while the game runs
(the game is the launcher's child and would be killed with it).
"""

from __future__ import annotations

import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal

from app import backup, channel, osutil, process, settings
from app.backup import BackupInfo

POLL_SECONDS = 2.0


class LaunchController(QObject):
    status_changed = Signal(str)
    session_started = Signal()     # RSI Launcher is up
    game_started = Signal()        # StarCitizen.exe appeared
    game_exited = Signal()         # StarCitizen.exe went away (backup follows)
    backup_created = Signal(str)   # display name of the new backup
    backup_skipped = Signal()      # no changes since last backup
    backup_failed = Signal(str)    # error message; the session keeps going
    session_finished = Signal()    # launcher and game both gone
    launch_failed = Signal(str)    # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._in_game = False
        self._proc: subprocess.Popen | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self, ch: str, restore_info: BackupInfo | None) -> None:
        if self._busy:
            return

        real_launch_script = settings.current().launch
        if real_launch_script is None:
            self.launch_failed.emit("No launch script set — choose it in Settings (gear icon).")
            return
        if not real_launch_script.is_file():
            self.launch_failed.emit(f"Launch script not found:\n{real_launch_script}")
            return

        if process.is_game_running():
            self.launch_failed.emit(
                "Star Citizen or the RSI Launcher is already running.\n"
                "Close it before restoring or launching."
            )
            return

        self._busy = True
        thread = threading.Thread(
            target=self._run_session, args=(real_launch_script, ch, restore_info), daemon=True
        )
        thread.start()

    def close_session(self) -> None:
        """Closes the RSI Launcher (and the sc-launch.sh shell wrapping it).
        Refused while the game runs: it's a child of the launcher, so this
        would kill it too. The main window disables the button then.
        """
        proc = self._proc
        if proc is None or proc.poll() is not None or self._in_game:
            return
        osutil.terminate_tree(proc.pid)

    def _run_session(self, real_launch_script, ch: str, restore_info: BackupInfo | None) -> None:
        paths = channel.resolve_channel_paths(settings.current().game_root, ch)

        if restore_info is not None:
            kind = "profile" if restore_info.is_profile else "backup"
            self.status_changed.emit(f"Restoring {kind}: {restore_info.display_name}…")
            try:
                backup.restore_backup(restore_info, paths.mappings_dir, paths.profile_dir)
            except Exception as exc:
                self._busy = False
                self.launch_failed.emit(f"Restore failed:\n{exc}")
                return

        self.status_changed.emit(f"Launching ({ch})…")
        try:
            proc = osutil.spawn(real_launch_script)
        except OSError as exc:
            self._busy = False
            self.launch_failed.emit(f"Failed to start launch script:\n{exc}")
            return

        self._proc = proc
        self._in_game = False
        self.session_started.emit()
        self.status_changed.emit("RSI Launcher open. Start the game from there")

        # Follow the game itself, not just the launcher: keybinds only change
        # in game, so back up each time StarCitizen.exe exits. The launcher
        # counts as running while our process or any RSI Launcher process is
        # alive (it may restart/detach itself, especially on Windows).
        while True:
            time.sleep(POLL_SECONDS)
            running = osutil.running_game_processes()
            in_game = osutil.GAME_EXE in running
            if in_game and not self._in_game:
                self._in_game = True
                self.game_started.emit()
                self.status_changed.emit("In game. Keybinds are backed up when the game closes")
            elif self._in_game and not in_game:
                self._in_game = False
                self.game_exited.emit()
                self._backup(ch, paths)
            launcher_up = proc.poll() is None or osutil.LAUNCHER_EXE in running
            if not launcher_up and not in_game:
                break

        self._proc = None
        self._busy = False
        self.session_finished.emit()

    def _backup(self, ch: str, paths) -> None:
        self.status_changed.emit("Game closed. Saving backup…")
        try:
            info = backup.create_backup(
                settings.current().backup_root, ch, paths.mappings_dir, paths.profile_dir
            )
        except Exception as exc:
            self.backup_failed.emit(f"Backup failed:\n{exc}")
            self.status_changed.emit("Backup failed")
            return
        if info is None:
            self.backup_skipped.emit()
            self.status_changed.emit("Game closed. No keybind changes since the last backup")
        else:
            self.backup_created.emit(info.display_name)
            self.status_changed.emit(f"Game closed. Backup saved: {info.display_name}")
