"""Settings view: where the user points the launcher at their own machine
— the game's LIVE folder, the launch script, GameGlass and the backup
folder — plus the in-game overlay's hotkeys. Each value is checked as it's
edited, so problems show up here rather than when pressing START.
"""

from __future__ import annotations

import sys
from dataclasses import fields, replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QKeySequenceEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import __version__, channel as channel_mod, datahub, hotkeys, settings
from app.settings import Settings
from app.theme import PALETTE
from app.ui.widgets import Switch

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


class _HotkeyRow:
    """Label, a field that records a key combination, Default button and a
    validation line."""

    def __init__(self, grid: QGridLayout, row: int, title: str, default: str, on_change):
        self.default = default
        grid.addWidget(QLabel(title, objectName="SlotTitle"), row, 0, Qt.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(4)
        line = QHBoxLayout()
        line.setSpacing(6)
        self.edit = QKeySequenceEdit()
        self.edit.setMaximumSequenceLength(1)
        self.edit.setClearButtonEnabled(True)
        self.edit.setFixedWidth(220)
        inner = self.edit.findChild(QLineEdit)
        if inner is not None:
            inner.setObjectName("SearchField")
            inner.setPlaceholderText("Click, then press the keys")
        self.edit.keySequenceChanged.connect(lambda _s: on_change())
        line.addWidget(self.edit)
        reset = QPushButton("Default", objectName="MiniButton")
        reset.setToolTip(f"Back to {default}")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(lambda: self.set_value(default))
        line.addWidget(reset)
        line.addStretch(1)
        box.addLayout(line)
        self.status = QLabel("", objectName="InspectorHint")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        grid.addLayout(box, row, 1)

    @property
    def value(self) -> str:
        return self.edit.keySequence().toString(QKeySequence.PortableText)

    def set_value(self, text: str) -> None:
        self.edit.setKeySequence(QKeySequence.fromString(text, QKeySequence.PortableText))

    set_status = _PathRow.set_status


class SettingsView(QWidget):
    saved = Signal()
    back_requested = Signal()
    open_overlay_requested = Signal()

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

        # Scrolls when the window is too short for every section.
        scroll = QScrollArea(objectName="InspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget(objectName="Inspector")
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(10)
        scroll.setWidget(content)

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
        self.rsi_log = _PathRow(
            grid, 4, "RSI Launcher log (optional)",
            "The RSI Launcher's logs\\log.log (in %APPDATA%\\rsilauncher on Windows, in the Wine prefix's "
            "user folder on Linux). SC-Toolkit watches it to notice game updates: while one runs, the "
            "tools keep the previous version's data; when it's done, they switch to the new one."
            if WINDOWS else
            "The RSI Launcher's logs/log.log, in the Wine prefix: drive_c/users/<you>/AppData/Roaming/"
            "rsilauncher. SC-Toolkit watches it to notice game updates: while one runs, the tools keep the "
            "previous version's data; when it's done, they switch to the new one.",
            folder=False, file_filter="Log (*.log);;All files (*)", on_change=self._validate,
        )
        sections.addWidget(panel)

        overlay_panel = QFrame(objectName="SidePanel")
        ogrid = QGridLayout(overlay_panel)
        ogrid.setContentsMargins(20, 18, 20, 18)
        ogrid.setHorizontalSpacing(18)
        ogrid.setVerticalSpacing(12)
        ogrid.setColumnMinimumWidth(0, 190)
        ogrid.setColumnStretch(1, 1)
        ogrid.addWidget(QLabel("IN-GAME OVERLAY", objectName="SectionLabel"), 0, 0, 1, 2)
        about = QLabel(
            "Missions, session status, Maps, Mining and Salvage in a small window on top of the game "
            "(run Star Citizen in Borderless mode). It never touches the game itself. Switch it on "
            "with IN-GAME OVERLAY in the launcher's left panel.",
            objectName="InspectorText",
        )
        about.setWordWrap(True)
        ogrid.addWidget(about, 1, 0, 1, 2)
        open_btn = QPushButton("Open the overlay", objectName="MiniButton")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setToolTip("Switches the overlay on if it's off, and shows it")
        open_btn.clicked.connect(self.open_overlay_requested.emit)
        ogrid.addWidget(open_btn, 2, 0, 1, 2, Qt.AlignLeft)
        note = QLabel(
            "Hotkeys: they work while Star Citizen has focus, as long as the overlay is switched on. "
            "Click a field and press the new key: an "
            "F-key, Insert, Home, End, Page Up/Down, Pause or Scroll Lock on its own, or a letter "
            "or digit with Ctrl, Alt or Meta. Modifier keys still reach the game when pressed, so "
            "a single key the game doesn't use (like F7) works best.",
            objectName="InspectorHint",
        )
        note.setWordWrap(True)
        ogrid.addWidget(note, 3, 0, 1, 2)
        defaults = {f.name: f.default for f in fields(Settings)}
        self.hotkey_rows: dict[str, _HotkeyRow] = {}
        for i, (action, (field, title)) in enumerate(hotkeys.ACTIONS.items()):
            self.hotkey_rows[field] = _HotkeyRow(ogrid, 4 + i, title, defaults[field], self._validate)
        sections.addWidget(overlay_panel)

        updates_panel = QFrame(objectName="SidePanel")
        ugrid = QGridLayout(updates_panel)
        ugrid.setContentsMargins(20, 18, 20, 18)
        ugrid.setHorizontalSpacing(18)
        ugrid.setVerticalSpacing(12)
        ugrid.setColumnMinimumWidth(0, 190)
        ugrid.setColumnStretch(2, 1)
        ugrid.addWidget(QLabel("UPDATES", objectName="SectionLabel"), 0, 0, 1, 3)
        self.update_check = Switch()
        self.update_prereleases = Switch()
        for row, (title, switch, hint) in enumerate((
            ("Check for updates", self.update_check,
             "Once a day, SC-Toolkit asks GitHub whether there's a new version. When there is, an "
             "Update button shows next to the version at the top; nothing is installed until you click it."),
            ("Include beta versions", self.update_prereleases,
             "Also offer test versions (pre-releases), which get new features first but may have bugs."),
        ), start=1):
            ugrid.addWidget(QLabel(title, objectName="InspectorText"), row, 0)
            ugrid.addWidget(switch, row, 1, Qt.AlignVCenter)
            label = QLabel(hint, objectName="InspectorHint")
            label.setWordWrap(True)
            ugrid.addWidget(label, row, 2)
        sections.addWidget(updates_panel)

        data_panel = QFrame(objectName="SidePanel")
        dv = QVBoxLayout(data_panel)
        dv.setContentsMargins(20, 18, 20, 18)
        dv.setSpacing(8)
        dv.addWidget(QLabel("GAME & WEB DATA", objectName="SectionLabel"))
        data_note = QLabel(
            "SC-Toolkit reads the game files once per game version and keeps what the tools need; "
            "it downloads the ship list weekly and the salvage spreadsheet and UEX prices at most "
            "once a day. All of this happens by itself. If something looks wrong or failed, "
            "Refresh data reads the game files again now and downloads whatever is due.",
            objectName="InspectorHint",
        )
        data_note.setWordWrap(True)
        dv.addWidget(data_note)
        data_row = QHBoxLayout()
        self.refresh_data_btn = QPushButton("Refresh data", objectName="MiniButton")
        self.refresh_data_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_data_btn.clicked.connect(self._refresh_data)
        data_row.addWidget(self.refresh_data_btn)
        self.data_result = QLabel("", objectName="InspectorNote")
        self.data_result.setWordWrap(True)
        data_row.addWidget(self.data_result, stretch=1)
        dv.addLayout(data_row)
        sections.addWidget(data_panel)
        hub = datahub.hub()
        hub.status.connect(self._on_data_status)
        hub.refreshed.connect(self._on_data_refreshed)
        sections.addStretch(1)
        outer.addWidget(scroll, stretch=1)

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
                           (self.gameglass, s.gameglass_path), (self.backups, s.backup_dir),
                           (self.rsi_log, s.rsi_log_path)):
            row.set_value(value)
        for field, row in self.hotkey_rows.items():
            row.set_value(getattr(s, field))
        self.update_check.setChecked(s.update_check)
        self.update_prereleases.setChecked(s.update_prereleases)
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
        # The log is found from the game / launch script paths, also when they
        # were filled in by hand.
        log = settings.find_rsi_log(self.live.value, self.launch.value)
        if log and not self.rsi_log.value:
            self.rsi_log.set_value(log)
        if not (found.live_dir or found.launch_path or found.gameglass_path):
            self.intro.setVisible(True)
            self.intro.setText("Nothing found in the usual places — use Browse to pick the folders.")

    def _refresh_data(self) -> None:
        root = settings.current().game_root
        channel = channel_mod.pick_default_channel(root)
        self._refreshing = True
        self.refresh_data_btn.setEnabled(False)
        self.data_result.setText("Refreshing…")
        datahub.hub().refresh_all(channel_mod.resolve_channel_paths(root, channel).channel_root if channel else None)

    def _on_data_status(self, text: str) -> None:
        if getattr(self, "_refreshing", False) and text:
            self.data_result.setText(text)

    def _on_data_refreshed(self, summary: str) -> None:
        self._refreshing = False
        self.refresh_data_btn.setEnabled(True)
        self.data_result.setText(summary)

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

        if not self.rsi_log.value:
            # Empty = auto-detect at runtime (app.patchwatch): say what that finds.
            found = settings.find_rsi_log(self.live.value, self.launch.value)
            self.rsi_log.edit.setPlaceholderText(found)
            self.rsi_log.set_status(True if found else None,
                                    "Found automatically (leave empty to keep detecting it)" if found else
                                    "Not found: game updates are noticed when SC-Toolkit or the game starts")
        else:
            err = settings.validate_file(self.rsi_log.value)
            self.rsi_log.set_status(False if err else True, err or "Found: game updates are noticed as they happen")

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

        hotkeys_ok = True
        seen: dict[str, str] = {}
        for field, row in self.hotkey_rows.items():
            try:
                combo = hotkeys.format_combo(*hotkeys.parse(row.value))
            except ValueError as exc:
                row.set_status(False, str(exc))
                hotkeys_ok = False
                continue
            if combo in seen:
                row.set_status(False, "Already used for the other hotkey")
                hotkeys_ok = False
            else:
                row.set_status(True, "OK")
            seen[combo] = field

        # The game folder is the one thing nothing works without.
        self.save_btn.setEnabled(live_err is None and hotkeys_ok and not (
            Path(self.backups.value).is_file() if self.backups.value else False))

    def _save(self) -> None:
        settings.apply(replace(
            settings.current(),
            live_dir=self.live.value,
            launch_path=self.launch.value,
            gameglass_path=self.gameglass.value,
            backup_dir=self.backups.value,
            rsi_log_path=self.rsi_log.value,
            update_check=self.update_check.isChecked(),
            update_prereleases=self.update_prereleases.isChecked(),
            **{field: hotkeys.format_combo(*hotkeys.parse(row.value))
               for field, row in self.hotkey_rows.items()},
        ))
        self.saved.emit()
