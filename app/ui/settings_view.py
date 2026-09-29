"""Settings view: where the user points the launcher at their own machine
— the game's LIVE folder, the launch script, GameGlass and the backup
folder. Each path is checked as it's edited, so problems show up here
rather than when pressing START.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import __version__, channel as channel_mod, settings
from app.settings import Settings
from app.theme import PALETTE

WINDOWS = sys.platform.startswith("win")


class _PathRow:
    """Label, path field, Browse button and a live validation line."""

    def __init__(self, grid: QGridLayout, row: int, title: str, hint: str, *, folder: bool,
                 file_filter: str = "", placeholder: str = "", on_change=None):
        self.folder = folder
        self.file_filter = file_filter
        grid.addWidget(QLabel(title, objectName="SlotTitle"), row, 0, Qt.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(4)
        line = QHBoxLayout()
        line.setSpacing(6)
        self.edit = QLineEdit(objectName="SearchField")
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(lambda _t: on_change and on_change())
        line.addWidget(self.edit, stretch=1)
        browse = QPushButton("Browse…", objectName="MiniButton")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        line.addWidget(browse)
        box.addLayout(line)
        hint_lbl = QLabel(hint, objectName="InspectorHint")
        hint_lbl.setWordWrap(True)
        box.addWidget(hint_lbl)
        self.status = QLabel("", objectName="InspectorHint")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        grid.addLayout(box, row, 1)

    @property
    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, text: str) -> None:
        self.edit.setText(text)

    def set_status(self, ok: bool | None, text: str) -> None:
        """ok=True green check, False red cross, None neutral."""
        mark = {True: "✓ ", False: "✗ ", None: ""}[ok]
        self.status.setObjectName({True: "SettingsOk", False: "SettingsBad", None: "InspectorHint"}[ok])
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(mark + text)

    def _browse(self) -> None:
        start = self.value or str(Path.home())
        if self.folder:
            chosen = QFileDialog.getExistingDirectory(self.edit, "Choose folder", start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self.edit, "Choose file", start, self.file_filter)
        if chosen:
            self.set_value(chosen)


class SettingsView(QWidget):
    saved = Signal()
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 20)
        outer.setSpacing(10)

        bar_frame = QFrame(objectName="ToolBar")
        bar = QHBoxLayout(bar_frame)
        bar.setContentsMargins(10, 8, 10, 8)
        bar.setSpacing(8)
        self.back_btn = QPushButton("←  Back", objectName="ToolButton")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.back_requested.emit)
        bar.addWidget(self.back_btn)
        bar.addSpacing(8)
        bar.addWidget(QLabel("SETTINGS", objectName="ConfigLabel"))
        bar.addStretch(1)
        detect = QPushButton("Auto-detect", objectName="MiniButton")
        detect.setToolTip("Look for Star Citizen and GameGlass in their usual install locations")
        detect.setCursor(Qt.PointingHandCursor)
        detect.clicked.connect(self._autodetect)
        bar.addWidget(detect)
        self.save_btn = QPushButton("Save", objectName="StartButtonSmall")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._save)
        bar.addWidget(self.save_btn)
        outer.addWidget(bar_frame)

        self.intro = QLabel("", objectName="InspectorNote")
        self.intro.setWordWrap(True)
        outer.addWidget(self.intro)

        panel = QFrame(objectName="SidePanel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(20, 18, 20, 18)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(16)
        grid.setColumnMinimumWidth(0, 190)
        grid.setColumnStretch(1, 1)

        launch_hint = (
            "RSI Launcher.exe, usually in Roberts Space Industries\\RSI Launcher."
            if WINDOWS else
            "The script that starts the RSI Launcher — for a LUG Helper install that's "
            "sc-launch.sh in your Wine prefix. The launcher waits for it to exit, then backs up "
            "your keybinds."
        )
        self.live = _PathRow(
            grid, 0, "Star Citizen LIVE folder",
            "The LIVE folder inside StarCitizen (it contains Data.p4k). PTU / EPTU / TECH-PREVIEW "
            "next to it are picked up automatically.",
            folder=True, on_change=self._validate,
        )
        self.launch = _PathRow(
            grid, 1, "Launch script", launch_hint, folder=False,
            file_filter="RSI Launcher (*.exe)" if WINDOWS else "Scripts and programs (*.sh *.AppImage *);;All files (*)",
            on_change=self._validate,
        )
        self.gameglass = _PathRow(
            grid, 2, "GameGlass (optional)",
            "GameGlass.exe" if WINDOWS else "The GameGlass AppImage. Leave empty if you don't use it (the GameGlass button is then disabled).",
            folder=False,
            file_filter="GameGlass (*.exe)" if WINDOWS else "AppImage (*.AppImage);;All files (*)",
            on_change=self._validate,
        )
        self.backups = _PathRow(
            grid, 3, "Backup folder (optional)",
            "Where keybind backups and saved binding profiles are kept. Leave empty for the default.",
            folder=True, placeholder=str(settings.DEFAULT_BACKUP_DIR), on_change=self._validate,
        )
        outer.addWidget(panel)
        outer.addStretch(1)

        about = QLabel(
            f"SC-Toolkit v{__version__} · GPL-3.0 · "
            f"<a style='color:{PALETTE['info']}' href='https://github.com/D3adly/sc-toolkit'>"
            "github.com/D3adly/sc-toolkit</a>",
            objectName="AboutLabel",
        )
        about.setOpenExternalLinks(True)
        outer.addWidget(about, alignment=Qt.AlignRight)

    # -- lifecycle ------------------------------------------------------------
    def activate(self, first_run: bool = False) -> None:
        s = settings.current()
        for row, value in ((self.live, s.live_dir), (self.launch, s.launch_path),
                           (self.gameglass, s.gameglass_path), (self.backups, s.backup_dir)):
            row.set_value(value)
        self.back_btn.setVisible(not first_run)
        self.intro.setVisible(first_run)
        self.intro.setText(
            "Welcome! Point the launcher at your Star Citizen install to get started. "
            "Try Auto-detect first — it checks the usual install locations."
        )
        self._validate()

    def deactivate(self) -> None:
        pass

    # -- actions ------------------------------------------------------------------
    def _autodetect(self) -> None:
        found = settings.autodetect()
        for row, value in ((self.live, found.live_dir), (self.launch, found.launch_path),
                           (self.gameglass, found.gameglass_path)):
            if value and not row.value:
                row.set_value(value)
        if not (found.live_dir or found.launch_path or found.gameglass_path):
            self.intro.setVisible(True)
            self.intro.setText("Nothing found in the usual places — use Browse to pick the folders.")

    def _validate(self) -> None:
        live_err = settings.validate_live_dir(self.live.value)
        if live_err:
            self.live.set_status(False, live_err)
        else:
            channels = channel_mod.detect_channels(Path(self.live.value).parent)
            self.live.set_status(True, "Channels found: " + ", ".join(channels))

        launch_err = settings.validate_file(self.launch.value)
        self.launch.set_status(False if launch_err else True,
                               launch_err or "Found — START will use it")

        if not self.gameglass.value:
            self.gameglass.set_status(None, "Not set — GameGlass button disabled")
        else:
            err = settings.validate_file(self.gameglass.value)
            self.gameglass.set_status(False if err else True, err or "Found")

        if not self.backups.value:
            self.backups.set_status(None, f"Using the default: {settings.DEFAULT_BACKUP_DIR}")
        else:
            p = Path(self.backups.value)
            if p.is_dir():
                self.backups.set_status(True, "Folder exists")
            elif p.exists():
                self.backups.set_status(False, "That's a file, not a folder")
            else:
                self.backups.set_status(None, "Will be created on first backup")

        # The game folder is the one thing nothing works without.
        self.save_btn.setEnabled(live_err is None and not (Path(self.backups.value).is_file()
                                                           if self.backups.value else False))

    def _save(self) -> None:
        settings.apply(Settings(
            live_dir=self.live.value,
            launch_path=self.launch.value,
            gameglass_path=self.gameglass.value,
            backup_dir=self.backups.value,
        ))
        self.saved.emit()
