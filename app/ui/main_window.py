import subprocess

from PySide6.QtCore import QEvent, Qt, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import QAction, QPixmap, QPainter, QPainterPath, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QMenu,
    QSystemTrayIcon,
    QWidget,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QGridLayout,
    QSizePolicy,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
)

from dataclasses import replace

from app import backup, channel as channel_mod, config, links, osutil, settings
from app.backup import BackupInfo
from app import hotkeys
from app.launch import LaunchController
from app.overlay_host import OverlayHost
from app.starstrings_controller import StarStringsController
from app.theme import PALETTE
from app.ui.title_bar import TitleBar

ICON_SIZE = QSize(20, 20)


def _icon(name: str) -> QIcon:
    return QIcon(str(config.ICONS_DIR / f"{name}.png"))

CORNER_RADIUS = 14


def _divider() -> QFrame:
    d = QFrame()
    d.setObjectName("Divider")
    d.setFrameShape(QFrame.HLine)
    return d


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionLabel")
    return lbl


class _Switch(QAbstractButton):
    """An on/off slider switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 20)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        track = QColor(PALETTE["accent"] if on else "#3a3f45")
        if self.underMouse():
            track = track.lighter(115)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - 3 - d if on else r.left() + 3
        p.setBrush(QColor("#15181c" if on else PALETTE["text_secondary"]))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class _ToolTile(QFrame):
    """A large clickable card for one of SC-Toolkit's own tools: icon, title,
    a line of explanation and an optional credit (with links)."""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, text: str, credit: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ToolTile")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(16)
        icon = QLabel()
        icon.setPixmap(_icon(icon_name).pixmap(48, 48))
        icon.setAlignment(Qt.AlignTop)
        row.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(QLabel(title, objectName="TileTitle"))
        self.body = body = QLabel(text, objectName="TileText")
        body.setWordWrap(True)
        col.addWidget(body)
        if credit:
            note = QLabel(credit, objectName="TileCredit")
            note.setWordWrap(True)
            note.setOpenExternalLinks(True)
            col.addWidget(note)
        col.addStretch(1)
        row.addLayout(col, stretch=1)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton and self.isEnabled()
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class RootFrame(QWidget):
    """Paints the Polaris background art (cropped to fill, darkened with a
    gradient for legibility) behind everything else, clipped to rounded
    window corners.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RootFrame")
        self._bg = QPixmap(str(config.BACKGROUND_IMAGE))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        radius = 0 if self.window().isMaximized() else CORNER_RADIUS
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        painter.setClipPath(path)

        painter.fillPath(path, QColor(PALETTE["bg_panel_solid"]))
        scaled = None
        bottom = self.height()
        if not self._bg.isNull():
            scaled = self._bg.scaled(
                self.width(), bottom, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            # Anchored to the watermark's corner so it's never cropped.
            x0 = self.width() - scaled.width() if config.BACKGROUND_ANCHOR_RIGHT else 0
            painter.drawPixmap(x0, bottom - scaled.height(), scaled)


        painter.setPen(QColor(255, 255, 255, 20))
        painter.drawPath(path)


class MainWindow(QMainWindow):
    WIDTH = 1240
    HEIGHT = 760

    def __init__(self, start_overlay: bool = True):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.WIDTH, self.HEIGHT)
        self.setMinimumSize(1100, 720)

        self.channel = channel_mod.pick_default_channel(settings.current().game_root)
        self._mode = "start"  # "start" | "close"
        self._combo_backups: list[BackupInfo] = []

        self.controller = LaunchController(self)
        self.controller.status_changed.connect(self._set_status)
        self.controller.session_started.connect(self._on_session_started)
        self.controller.game_started.connect(self._on_game_started)
        self.controller.game_exited.connect(self._on_game_exited)
        self.controller.backup_created.connect(self._on_backup_created)
        self.controller.backup_skipped.connect(self._on_backup_done)
        self.controller.backup_failed.connect(self._on_backup_failed)
        self.controller.session_finished.connect(self._on_session_finished)
        self.controller.launch_failed.connect(self._on_launch_failed)

        self.starstrings_controller = StarStringsController(self)
        self.starstrings_controller.status_changed.connect(self._set_status)
        self.starstrings_controller.succeeded.connect(self._on_starstrings_succeeded)
        self.starstrings_controller.version_mismatch.connect(self._on_starstrings_mismatch)
        self.starstrings_controller.failed.connect(self._on_starstrings_failed)

        root = RootFrame()
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = title_bar = TitleBar()
        title_bar.settings_requested.connect(self._show_settings)
        outer.addWidget(title_bar)

        # Main view and the joystick bindings view share the window; the
        # bindings view is built on first use.
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, stretch=1)

        # Footer band: CIG's notice (required by the Fankit Agreement wherever
        # their material is shown) on the left, and a clear area on the right
        # where the wallpaper's watermark shows. Its height follows the window
        # because the watermark scales with the wallpaper.
        self.footer = QWidget()
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(24, 0, 0, 6)
        notice = QLabel(config.CIG_NOTICE, objectName="CigNotice")
        notice.setWordWrap(True)
        notice.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        footer_layout.addWidget(notice, stretch=1)
        self._watermark_gap = footer_layout.addSpacing(0) or footer_layout.itemAt(1)
        outer.addWidget(self.footer)
        self.bindings_view = None
        self.salvage_view = None
        self.mining_view = None
        self.settings_view = None
        self.maps_view = None
        self._main_size = None

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 20, 20, 20)
        body_layout.setSpacing(16)
        self.stack.addWidget(body)

        body_layout.addWidget(self._build_launch_panel(), stretch=0)
        body_layout.addWidget(self._build_tools_panel(), stretch=1)
        body_layout.addWidget(self._build_link_panel(), stretch=0)
        self._apply_channel_state()

        # Nothing configured yet (first run on this machine): settings first.
        if settings.validate_live_dir(settings.current().live_dir) is not None:
            QTimer.singleShot(0, lambda: self._show_settings(first_run=True))

        self.overlay = OverlayHost(self)
        self._build_tray()
        app = QApplication.instance()
        app.aboutToQuit.connect(self._on_about_to_quit)
        self._start_overlay = start_overlay
        if start_overlay and settings.current().overlay_enabled:
            # Started right away (hidden), so the overlay hotkeys work in game.
            QTimer.singleShot(500, self.overlay.start)

    # -- tray, overlay, commands from other processes -------------------------
    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self.tray = QSystemTrayIcon(QIcon(str(config.APP_ICON)), self)
        self.tray.setToolTip(config.DISPLAY_NAME)
        menu = QMenu(self)
        menu.addAction("Show launcher", self.show_launcher)
        self._tray_overlay = menu.addAction("", lambda: self.handle_command("toggle-overlay"))
        self._tray_clickthrough = menu.addAction("", lambda: self.handle_command("toggle-clickthrough"))
        self._tray_enable = menu.addAction("", lambda: self.overlay_switch.toggle())
        menu.addSeparator()
        self._quit_action = QAction("Quit", self)
        self._quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(self._quit_action)
        menu.aboutToShow.connect(self._update_quit_action)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._tray_hint_shown = False

    def _update_quit_action(self) -> None:
        enabled = settings.current().overlay_enabled
        self._tray_overlay.setText(f"Overlay\t{hotkeys.label('toggle-overlay')}")
        self._tray_clickthrough.setText(f"Overlay click-through\t{hotkeys.label('toggle-clickthrough')}")
        self._tray_overlay.setVisible(enabled)
        self._tray_clickthrough.setVisible(enabled)
        self._tray_enable.setText("Switch the overlay off" if enabled else "Switch the overlay on")
        self._quit_action.setText(
            "Quit (skips the settings backup when the game exits)" if self.controller.busy else "Quit")

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_launcher()

    def show_launcher(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def minimize_to_tray(self) -> None:
        if self.tray is None:
            self.showMinimized()
            return
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage(
                config.DISPLAY_NAME,
                "Still running in the tray."
                + (f" Overlay: {hotkeys.label('toggle-overlay')}." if settings.current().overlay_enabled else ""),
                QSystemTrayIcon.Information, 4000,
            )

    def handle_command(self, command: str) -> None:
        """Commands from `sc-toolkit --show / --toggle-overlay / …` (app.main)."""
        if command == "show":
            self.show_launcher()
        elif command in ("toggle-overlay", "toggle-clickthrough"):
            if settings.current().overlay_enabled:
                self.overlay.send(command)

    def _set_overlay_enabled(self, on: bool) -> None:
        if on != settings.current().overlay_enabled:
            settings.apply(replace(settings.current(), overlay_enabled=on))
        self._update_overlay_hint()
        if not self._start_overlay:
            return
        if on:
            self.overlay.start()
        else:
            self.overlay.stop()

    def _update_overlay_hint(self) -> None:
        on = settings.current().overlay_enabled
        show, click = hotkeys.label("toggle-overlay"), hotkeys.label("toggle-clickthrough")
        self.overlay_hint.setText(f"{show} to show" if on else "off")
        if hasattr(self, "overlay_tile"):
            self.overlay_tile.body.setText(
                f"Maps, Mining and Salvage in a small window on top of the game (Borderless mode). "
                f"{show} shows or hides it, {click} lets clicks through to the game.")

    def _open_overlay(self) -> None:
        """The tile: switches the overlay on if needed and shows it."""
        if not settings.current().overlay_enabled:
            self.overlay_switch.setChecked(True)
        if self._start_overlay:
            self.overlay.send("show")

    def closeEvent(self, event):
        # While a game session runs, closing would skip the backup on game
        # exit: keep running in the tray instead.
        if self.controller.busy and self.tray is not None:
            event.ignore()
            self.minimize_to_tray()
            return
        super().closeEvent(event)
        QApplication.instance().quit()

    def _on_about_to_quit(self) -> None:
        self.overlay.stop()
        if self.tray is not None:
            self.tray.hide()

    # -- maximise -----------------------------------------------------------------
    def resize(self, *args):
        # Each tool view picks its own window size; not while maximised.
        if self.isMaximized():
            return
        super().resize(*args)

    def _normal_size(self):
        """The size to come back to (the un-maximised one while maximised)."""
        return self.normalGeometry().size() if self.isMaximized() else self.size()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.sync_maximized(self.isMaximized())
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the footer as tall as the wallpaper's watermark and reserve its
        # width on the right, so no panel ever covers it.
        fx, fy, fw, fh = config.BACKGROUND_WATERMARK
        img_h = self.height()
        img_w = max(self.width(), img_h * 16 / 9)
        self.footer.setFixedHeight(max(44, int(img_h * (1 - fy)) + 4))
        self._watermark_gap.changeSize(int(img_w * (1 - fx)) + 8, 0)
        self.footer.layout().invalidate()

    # -- left panel: Start + config selector --------------------------------
    def _build_launch_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SidePanel")
        panel.setFixedWidth(260)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 24, 18, 24)
        layout.setSpacing(10)

        self.start_btn = QPushButton("START")
        self.start_btn.setObjectName("StartButton")
        self.start_btn.setFixedHeight(72)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self.start_btn)

        self.busy_bar = QProgressBar()
        self.busy_bar.setObjectName("BusyBar")
        self.busy_bar.setRange(0, 0)  # indeterminate / marquee
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(6)
        self.busy_bar.setVisible(False)
        layout.addWidget(self.busy_bar)

        layout.addSpacing(8)
        self.config_label = QLabel("LAUNCH WITH", objectName="ConfigLabel")
        layout.addWidget(self.config_label)

        self.config_combo = QComboBox()
        self.config_combo.setObjectName("ConfigCombo")
        layout.addWidget(self.config_combo)

        # Plain-language explanation of the current choice (updates with it).
        self.config_help = QLabel("", objectName="ConfigHelp")
        self.config_help.setWordWrap(True)
        layout.addWidget(self.config_help)
        self.config_combo.currentIndexChanged.connect(self._update_config_help)
        self._refresh_config_combo()

        layout.addSpacing(10)
        self.status_label = QLabel("")
        self.status_label.setObjectName("SectionLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        return panel

    def _apply_channel_state(self) -> None:
        """Enables/labels everything that depends on the configured install."""
        s = settings.current()
        has_game = self.channel is not None
        self.config_label.setText("LAUNCH WITH" + (f" ({self.channel})" if has_game else ""))
        self.start_btn.setEnabled(has_game and self._mode == "start")
        if not has_game:
            self.start_btn.setToolTip("Set your Star Citizen LIVE folder in Settings (gear icon)")
            self._set_status("No Star Citizen installation set — open Settings")
        elif s.launch is None or not s.launch.is_file():
            self.start_btn.setToolTip("Set the launch script in Settings (gear icon)")
            self._set_status("Launch script not set — open Settings")
        else:
            self.start_btn.setToolTip("")
            self._set_status("Idle")
        for btn in (self.bindings_btn, self.salvage_btn, self.mining_btn, self.starstrings_btn):
            btn.setEnabled(has_game)
        glass = s.gameglass
        self.gameglass_btn.setEnabled(glass is not None)
        self.gameglass_btn.setToolTip("" if glass else "Set the GameGlass path in Settings to enable")

    def _refresh_config_combo(self) -> None:
        combo = self.config_combo
        combo.clear()
        combo.addItem("Current game setup")

        self._combo_backups = []
        if self.channel is None:
            return
        profiles = backup.list_profiles(settings.current().backup_root, self.channel)
        backups = backup.list_backups(settings.current().backup_root, self.channel)
        for info in profiles:
            combo.addItem(f"★ {info.display_name}", info)
            combo.setItemData(
                combo.count() - 1, "Load this saved profile, then launch", Qt.ToolTipRole
            )
        if profiles and backups:
            combo.insertSeparator(combo.count())
        for info in backups:
            combo.addItem(info.display_name, info)
            combo.setItemData(
                combo.count() - 1, "Restore this backup, then launch", Qt.ToolTipRole
            )
        self._combo_backups = profiles + backups
        self._update_config_help()

    def _update_config_help(self, _index: int = 0) -> None:
        info = self._selected_backup()
        if info is None:
            self.config_help.setProperty("warn", False)
            self.config_help.setText(
                "Starts the game with your keybinds and settings exactly as they are now. "
                "Nothing is changed."
            )
        else:
            kind = "profile" if info.is_profile else "backup"
            self.config_help.setProperty("warn", True)
            self.config_help.setText(
                f"⚠ Overwrites your current in-game keybinds and game settings with this "
                f"{kind} before launching. Changes made while the game was started without "
                f"SC-Toolkit (not yet backed up) will be lost."
            )
        self.config_help.style().unpolish(self.config_help)
        self.config_help.style().polish(self.config_help)

    def _selected_backup(self) -> BackupInfo | None:
        data = self.config_combo.currentData()
        return data if isinstance(data, BackupInfo) else None

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_start_enabled(self, enabled: bool) -> None:
        self.start_btn.setEnabled(enabled and self.channel is not None)

    def _set_button_mode(self, mode: str) -> None:
        """'start' | 'close' (closes the RSI Launcher) | 'ingame' (disabled:
        closing the launcher would also kill the game)."""
        self._mode = mode
        self.start_btn.setText({"close": "CLOSE", "ingame": "IN GAME"}.get(mode, "START"))
        self.start_btn.setToolTip(
            "Quit Star Citizen first. Closing the RSI Launcher now would close the game too."
            if mode == "ingame" else ""
        )
        self.start_btn.setProperty("mode", mode)
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)

    def _on_start_clicked(self) -> None:
        if self._mode == "close":
            self.start_btn.setEnabled(False)
            self.controller.close_session()
            return

        if self.controller.busy:
            return
        self.config_combo.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.busy_bar.setVisible(True)
        self.controller.start(self.channel, self._selected_backup())

    def _on_session_started(self) -> None:
        self.busy_bar.setVisible(False)
        self._set_button_mode("close")
        self.start_btn.setEnabled(True)

    def _on_game_started(self) -> None:
        self._set_button_mode("ingame")
        self.start_btn.setEnabled(False)

    def _on_game_exited(self) -> None:
        self.busy_bar.setVisible(True)   # backup in progress

    def _on_backup_created(self, _display_name: str) -> None:
        self.config_combo.blockSignals(True)
        self._refresh_config_combo()
        self.config_combo.blockSignals(False)
        self._update_config_help()
        self._on_backup_done()

    def _on_backup_done(self) -> None:
        # Back to "launcher open": CLOSE works again, the game can be restarted.
        self.busy_bar.setVisible(False)
        if self.controller.busy:
            self._set_button_mode("close")
            self.start_btn.setEnabled(True)

    def _on_backup_failed(self, message: str) -> None:
        self._on_backup_done()
        QMessageBox.warning(self, config.DISPLAY_NAME, message)

    def _on_session_finished(self) -> None:
        self.busy_bar.setVisible(False)
        self.config_combo.setEnabled(True)
        self._set_button_mode("start")
        self._set_start_enabled(True)

    def _on_launch_failed(self, message: str) -> None:
        self.busy_bar.setVisible(False)
        self.config_combo.setEnabled(True)
        self._set_button_mode("start")
        self._set_start_enabled(True)
        self._set_status("Error — see dialog")
        QMessageBox.warning(self, config.DISPLAY_NAME, message)

    # -- middle: SC-Toolkit's own tools ---------------------------------------
    def _build_overlay_switch(self) -> QWidget:
        box = QFrame(objectName="OverlaySwitchBox")
        box.setToolTip(
            "Maps, Mining and Salvage in a small window on top of the game "
            "(run Star Citizen in Borderless mode). Hotkeys are set in Settings.")
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 3, 8, 3)
        row.setSpacing(10)
        row.addWidget(QLabel("IN-GAME OVERLAY", objectName="OverlaySwitchLabel"))
        self.overlay_hint = QLabel("", objectName="OverlaySwitchHint")
        row.addWidget(self.overlay_hint)
        self.overlay_switch = _Switch()
        self.overlay_switch.setChecked(settings.current().overlay_enabled)
        self.overlay_switch.toggled.connect(self._set_overlay_enabled)
        row.addWidget(self.overlay_switch)
        self._update_overlay_hint()
        return box

    def _build_tools_panel(self) -> QWidget:
        # No panel behind this column: each tile carries its own glass, so the
        # wallpaper shows through around and below them.
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        heading_row = QHBoxLayout()
        heading_row.setSpacing(12)
        heading_row.addWidget(QLabel("SC-TOOLKIT TOOLS", objectName="ToolsHeading"))
        heading_row.addStretch(1)
        heading_row.addWidget(self._build_overlay_switch())
        layout.addLayout(heading_row)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.bindings_btn = _ToolTile(
            "joystick", "Joystick Bindings",
            "See what every button on your stick does, rebind by pressing it, "
            "and save the result as a launch profile.",
        )
        self.bindings_btn.clicked.connect(self._show_bindings)
        self.salvage_btn = _ToolTile(
            "salvage", "Salvage Claims",
            "Ships in Adagio salvage claims by difficulty: their components, sell vs "
            "dismantle prices, and cargo aboard.",
        )
        self.salvage_btn.clicked.connect(self._show_salvage)
        self.mining_btn = _ToolTile(
            "mining", "Mining Finder",
            "Where each ore spawns, how likely each rock is, radar signatures and "
            "quality odds, straight from the game files.",
        )
        self.mining_btn.clicked.connect(self._show_mining)
        maps_tile = _ToolTile(
            "scmaps", "SC Maps",
            "One-page guides and maps for events, locations and missions.",
            credit=(
                "Community made by <a style='color:" + PALETTE["info"] + "' "
                "href='https://mrkraken.space/one-page-guides/'>Mr Kraken</a>, "
                "all credit to the author."
            ),
        )
        maps_tile.clicked.connect(self._show_maps)
        self.overlay_tile = _ToolTile("overlay", "In-game Overlay", "")
        self.overlay_tile.clicked.connect(self._open_overlay)
        for i, tile in enumerate((self.bindings_btn, self.salvage_btn, self.mining_btn, maps_tile)):
            grid.addWidget(tile, i // 2, i % 2)
        grid.addWidget(self.overlay_tile, 2, 0, 1, 2)
        self._update_overlay_hint()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        return panel

    # -- right panel: external tools + link library ---------------------------------
    def _build_link_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SidePanel")
        panel.setFixedWidth(260)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(6)

        layout.addWidget(_section_label("TOOLS"))
        self.gameglass_btn = self._tool_button("GameGlass", "gameglass", self._launch_gameglass)
        layout.addWidget(self.gameglass_btn)
        self.starstrings_btn = self._tool_button(
            "Update Star Strings", "starstrings", self._on_update_starstrings_clicked)
        layout.addWidget(self.starstrings_btn)

        layout.addSpacing(6)
        layout.addWidget(_divider())
        layout.addSpacing(6)

        layout.addWidget(_section_label("LINKS · OFFICIAL"))
        for label, url, icon_name in links.OFFICIAL_LINKS:
            layout.addWidget(self._link_button(label, icon_name, url))
        layout.addSpacing(8)
        layout.addWidget(_section_label("LINKS · COMMUNITY"))
        for label, url, icon_name in links.COMMUNITY_LINKS:
            layout.addWidget(self._link_button(label, icon_name, url))

        layout.addStretch(1)
        return panel

    @staticmethod
    def _tool_button(label: str, icon_name: str, slot) -> QPushButton:
        btn = QPushButton(label, objectName="ToolButton")
        btn.setIcon(_icon(icon_name))
        btn.setIconSize(ICON_SIZE)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _link_button(label: str, icon_name: str, url: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName("LinkButton")
        btn.setIcon(_icon(icon_name))
        btn.setIconSize(ICON_SIZE)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: MainWindow._open_url(url))
        return btn

    @staticmethod
    def _open_url(url: str) -> None:
        osutil.open_url(url)

    def _launch_gameglass(self) -> None:
        path = settings.current().gameglass
        if path is None or not path.is_file():
            QMessageBox.warning(
                self, "GameGlass", f"GameGlass not found:\n{path}\n\nCheck the path in Settings."
            )
            return
        osutil.make_executable(path)
        try:
            subprocess.Popen(
                [str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            QMessageBox.warning(self, "GameGlass", f"Failed to launch GameGlass:\n{exc}")

    # -- joystick bindings view ----------------------------------------------
    def _show_bindings(self) -> None:
        if self.bindings_view is None:
            from app.ui.bindings_view import BindingsView

            self.bindings_view = BindingsView(self.channel)
            self.bindings_view.back_requested.connect(self._show_main)
            self.bindings_view.profiles_changed.connect(self._refresh_config_combo)
            self.stack.addWidget(self.bindings_view)
        # The diagram wants more room than the launcher's compact size.
        self._main_size = self._normal_size()
        screen = self.screen().availableGeometry()
        self.resize(min(1640, int(screen.width() * 0.94)), min(980, int(screen.height() * 0.92)))
        self.stack.setCurrentWidget(self.bindings_view)
        self.bindings_view.activate()

    # -- salvage claims view ---------------------------------------------------
    def _show_salvage(self) -> None:
        if self.salvage_view is None:
            from app.ui.salvage_view import SalvageView

            self.salvage_view = SalvageView(self.channel)
            self.salvage_view.back_requested.connect(self._show_main)
            self.stack.addWidget(self.salvage_view)
        self._main_size = self._normal_size()
        screen = self.screen().availableGeometry()
        self.resize(min(1320, int(screen.width() * 0.9)), min(900, int(screen.height() * 0.9)))
        self.stack.setCurrentWidget(self.salvage_view)
        self.salvage_view.activate()

    # -- SC Maps viewer ---------------------------------------------------------
    def _show_maps(self) -> None:
        if self.maps_view is None:
            from app.ui.maps_view import MapsView

            self.maps_view = MapsView()
            self.maps_view.back_requested.connect(self._show_main)
            self.stack.addWidget(self.maps_view)
        self._main_size = self._normal_size()
        screen = self.screen().availableGeometry()
        self.resize(min(1400, int(screen.width() * 0.92)), min(960, int(screen.height() * 0.92)))
        self.stack.setCurrentWidget(self.maps_view)
        self.maps_view.activate()

    # -- mining finder view ------------------------------------------------------
    def _show_mining(self) -> None:
        if self.mining_view is None:
            from app.ui.mining_view import MiningView

            self.mining_view = MiningView(self.channel)
            self.mining_view.back_requested.connect(self._show_main)
            self.stack.addWidget(self.mining_view)
        self._main_size = self._normal_size()
        screen = self.screen().availableGeometry()
        self.resize(min(1400, int(screen.width() * 0.92)), min(920, int(screen.height() * 0.9)))
        self.stack.setCurrentWidget(self.mining_view)
        self.mining_view.activate()

    # -- settings view ---------------------------------------------------------
    def _show_settings(self, first_run: bool = False) -> None:
        if self.stack.currentWidget() is self.settings_view:
            return
        if self.settings_view is None:
            from app.ui.settings_view import SettingsView

            self.settings_view = SettingsView()
            self.settings_view.back_requested.connect(self._show_main)
            self.settings_view.saved.connect(self._on_settings_saved)
            self.stack.addWidget(self.settings_view)
        current = self.stack.currentWidget()
        if current in (self.bindings_view, self.salvage_view, self.mining_view, self.maps_view):
            current.deactivate()
            if self._main_size is not None:
                self.resize(self._main_size)
        self.stack.setCurrentWidget(self.settings_view)
        self.settings_view.activate(first_run)

    def _on_settings_saved(self) -> None:
        # Tools built against the old install are rebuilt on next use.
        for attr in ("bindings_view", "salvage_view", "mining_view"):
            view = getattr(self, attr)
            if view is not None:
                self.stack.removeWidget(view)
                view.deleteLater()
                setattr(self, attr, None)
        self.channel = channel_mod.pick_default_channel(settings.current().game_root)
        self._refresh_config_combo()
        self._apply_channel_state()
        self._update_overlay_hint()
        if self._start_overlay and settings.current().overlay_enabled:
            # New hotkeys / game folder: the overlay reads them at start.
            self.overlay.stop()
            self.overlay.start()
        self._show_main()

    def _show_main(self) -> None:
        current = self.stack.currentWidget()
        if current in (self.bindings_view, self.salvage_view, self.mining_view, self.maps_view):
            current.deactivate()
        self.stack.setCurrentIndex(0)
        if self._main_size is not None:
            self.resize(self._main_size)

    def _on_update_starstrings_clicked(self) -> None:
        if self.channel is None or self.starstrings_controller.busy:
            return
        self.starstrings_btn.setEnabled(False)
        self.starstrings_controller.run(self.channel)

    def _on_starstrings_succeeded(self, release_name: str) -> None:
        self.starstrings_btn.setEnabled(True)
        QMessageBox.information(
            self, "StarStrings", f"Translation installed:\n{release_name}"
        )

    def _on_starstrings_mismatch(self, installed: str, required: str) -> None:
        self.starstrings_btn.setEnabled(True)
        QMessageBox.warning(
            self,
            "StarStrings — Game version mismatch",
            "StarStrings targets a different game build than what's installed.\n\n"
            f"Installed build: {installed}\n"
            f"StarStrings build: {required}\n\n"
            "No changes were made.",
        )

    def _on_starstrings_failed(self, message: str) -> None:
        self.starstrings_btn.setEnabled(True)
        QMessageBox.warning(self, "StarStrings", message)
