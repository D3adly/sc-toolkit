from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from app import channel as channel_mod, process, settings, starstrings


class StarStringsController(QObject):
    status_changed = Signal(str)
    succeeded = Signal(str)              # release name
    version_mismatch = Signal(str, str)  # installed build id, required build id
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, ch: str) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._run, args=(ch,), daemon=True).start()

    def _run(self, ch: str) -> None:
        try:
            if process.is_game_running():
                raise starstrings.StarStringsError(
                    "Star Citizen is currently running.\n"
                    "Close it before installing a translation update."
                )

            paths = channel_mod.resolve_channel_paths(settings.current().game_root, ch)

            self.status_changed.emit("Checking installed game version…")
            installed_id = starstrings.get_installed_build_id(paths.channel_root)

            self.status_changed.emit("Checking StarStrings compatibility…")
            target_id = starstrings.get_repo_target_build_id()

            if installed_id != target_id:
                self._busy = False
                self.version_mismatch.emit(installed_id, target_id)
                self.status_changed.emit("StarStrings update skipped — version mismatch")
                return

            self.status_changed.emit("Fetching latest release info…")
            asset = starstrings.get_latest_release_asset()

            self.status_changed.emit(f"Downloading {asset.name}…")
            starstrings.download_and_install(asset, paths.channel_root)

            self._busy = False
            self.succeeded.emit(asset.release_name)
            self.status_changed.emit(f"StarStrings installed: {asset.release_name}")
        except starstrings.StarStringsError as exc:
            self._busy = False
            self.failed.emit(str(exc))
        except Exception as exc:  # network/zip/etc. surprises
            self._busy = False
            self.failed.emit(f"Unexpected error:\n{exc}")
