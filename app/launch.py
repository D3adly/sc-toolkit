"""Launches the game via the launch script chosen in settings — normally the
LUG Helper's sc-launch.sh (which owns the
Wine/DXVK/shader-cache environment setup — not something we reimplement)
and, once that process exits — i.e. once the RSI Launcher has been closed —
runs a backup in the background.

sc-launch.sh execs `wine "RSI Launcher.exe"` as its own last, foregrounded
step, so waiting for the sc-launch.sh child process to exit is exactly
waiting for the RSI Launcher to exit — and killing that same process group
is exactly "close the RSI Launcher".
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading

from PySide6.QtCore import QObject, Signal

from app import backup, channel, process, settings
from app.backup import BackupInfo


class LaunchController(QObject):
    status_changed = Signal(str)
    session_started = Signal()
    session_ended = Signal()
    backup_created = Signal(str)   # display name of the new backup
    backup_skipped = Signal()      # no changes since last backup
    launch_failed = Signal(str)    # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
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
        """Terminates the running RSI Launcher (and the sc-launch.sh shell
        wrapping it), which lets _run_session's proc.wait() return and
        continue on into the usual post-session backup flow.
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass

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
            # A shell script (LUG Helper's sc-launch.sh) runs through bash;
            # anything else is executed directly.
            argv = [str(real_launch_script)]
            if real_launch_script.suffix == ".sh":
                argv = ["/usr/bin/env", "bash", *argv]
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self._busy = False
            self.launch_failed.emit(f"Failed to start launch script:\n{exc}")
            return

        self._proc = proc
        self.session_started.emit()
        self.status_changed.emit("Playing — press Close to end the session")
        proc.wait()
        self._proc = None
        self.session_ended.emit()

        self.status_changed.emit("Saving backup…")
        try:
            info = backup.create_backup(
                settings.current().backup_root, ch, paths.mappings_dir, paths.profile_dir
            )
        except Exception as exc:
            self._busy = False
            self.launch_failed.emit(f"Backup failed:\n{exc}")
            return

        self._busy = False
        if info is None:
            self.backup_skipped.emit()
            self.status_changed.emit("No config changes since last backup")
        else:
            self.backup_created.emit(info.display_name)
            self.status_changed.emit(f"Backup saved: {info.display_name}")
