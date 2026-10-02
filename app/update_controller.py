"""Runs app.updater's network work off the UI thread and reports back
through signals (same pattern as StarStringsController)."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app import settings, updater


class UpdateController(QObject):
    checked = Signal(object)        # updater.Release or None (up to date)
    check_failed = Signal(str)
    progress = Signal(int, int)     # bytes done, total (0 if unknown)
    installed = Signal(object)      # the replaced file (Path): restart from it
    install_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.release: updater.Release | None = None     # newest known update
        self._checking = False
        self._installing = False
        self._cancel = False

    @property
    def installing(self) -> bool:
        return self._installing

    def check(self, force: bool = False) -> None:
        if self._checking:
            return
        self._checking = True
        prereleases = settings.current().update_prereleases
        threading.Thread(target=self._check, args=(prereleases, force), daemon=True).start()

    def _check(self, prereleases: bool, force: bool) -> None:
        try:
            self.release = updater.check(prereleases, force=force)
        except updater.UpdateError as exc:
            self._checking = False
            self.check_failed.emit(str(exc))
            return
        self._checking = False
        self.checked.emit(self.release)

    def install(self) -> None:
        release, target = self.release, updater.install_target()
        if self._installing or release is None or target is None:
            return
        self._installing = True
        self._cancel = False
        threading.Thread(target=self._install, args=(release, target), daemon=True).start()

    def cancel(self) -> None:
        self._cancel = True

    def _install(self, release: updater.Release, target: Path) -> None:
        try:
            downloaded = updater.download(release, target, progress=self.progress.emit,
                                          cancelled=lambda: self._cancel)
            updater.install(downloaded, target)
        except updater.UpdateError as exc:
            self._installing = False
            self.install_failed.emit(str(exc))
            return
        self.installed.emit(target)
