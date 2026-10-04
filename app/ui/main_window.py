import subprocess

from PySide6.QtCore import QEvent, Qt, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import QAction, QPixmap, QPainter, QPainterPath, QColor, QIcon
from PySide6.QtWidgets import (
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

from app import (
    __version__, backup, channel as channel_mod, config, datahub, gamelog, ipc, links, osutil, settings, updater,
)
from app.backup import BackupInfo
from app import hotkeys
from app.launch import LaunchController
from app.overlay_host import OverlayHost
from app.patchwatch import PatchWatcher
from app.starstrings_controller import StarStringsController
from app.update_controller import UpdateController
from app.theme import PALETTE
from app.ui.title_bar import TitleBar
from app.ui.widgets import Switch

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
        self.gamelog = gamelog.LiveReader(lambda: settings.current().game_root, self)
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
        title_bar.whats_new_requested.connect(self._show_whats_new)
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
        self.stats_view = None
        self.whats_new_view = None
        self.hangar_view = None
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
        # Game.log: live reader (switch next to the overlay's) and history
        # reads. Features hook in with self.gamelog.add_listener().
        self.gamelog.state_changed.connect(self._update_gamelog_hint)
        self._history_jobs: set[gamelog.HistoryJob] = set()
        if start_overlay and settings.current().gamelog_live_enabled:
            self.gamelog.start()
        self._setup_updates(live=start_overlay)
        self._setup_data(live=start_overlay)
        # The online account (optional): the title bar mirrors it; a sign-in kept in the keyring is
        # picked up at startup.
        from app.account_controller import controller as account_controller
        account = account_controller()
        account.changed.connect(lambda st: self.title_bar.set_account(
            st.status, st.profile.display_name if st.profile else "", st.offline))
        title_bar.account_requested.connect(self._on_account_clicked)
        if start_overlay:
            account.restore()

    # -- game files and web data (app.datahub) -----------------------------------
    def _setup_data(self, live: bool) -> None:
        hub = datahub.hub()
        hub.status.connect(self._on_data_status)
        hub.failed.connect(lambda name, msg: self._on_data_status(
            f"Couldn't update the {datahub.label(name)}: {msg.splitlines()[0] if msg else 'error'}", sticky=True))
        self._overlay_notify = QTimer(self, singleShot=True, interval=2000)
        self._overlay_notify.timeout.connect(lambda: ipc.send(ipc.OVERLAY, "game-data-updated"))
        hub.updated.connect(lambda name: name in datahub.GAME_SOURCES and self._overlay_notify.start())
        # Game updates, from the RSI Launcher's log (no polling).
        self.patches = PatchWatcher(self)
        self.patches.started.connect(self._on_game_update_started)
        self.patches.completed.connect(self._on_game_update_completed)
        self.patches.stopped.connect(self._on_game_update_stopped)
        self.controller.game_started.connect(self._on_game_started_data)
        if live:
            self.patches.start()
            for channel, version in self.patches.updating.items():   # one already running
                self._on_game_update_started(channel, version)
            # Shortly after start: catch up after a game patch and refresh web
            # data that's older than its limit; everything else reads caches.
            QTimer.singleShot(1500, self._refresh_data)

    def _channel_root(self, channel: str | None):
        root = settings.current().game_root
        return channel_mod.resolve_channel_paths(root, channel).channel_root if channel and root else None

    def _refresh_data(self) -> None:
        datahub.hub().startup(self._channel_root(self.channel))

    def _on_game_update_started(self, channel: str, version: str) -> None:
        datahub.hub().set_updating(channel, version)
        self._on_data_status(f"Star Citizen {channel} {version.split('-')[0]} is being installed: the tools use the "
                             "previous version's data until it's done.", sticky=True)

    def _on_game_update_completed(self, channel: str, version: str) -> None:
        datahub.hub().set_updating(channel, None)
        self._data_sticky = False
        datahub.hub().startup(self._channel_root(channel))     # reads the new files in one pass

    def _on_game_update_stopped(self, channel: str) -> None:
        # Cancelled or paused: the files may be half updated, so keep the
        # previous data; the next start of SC-Toolkit or the game checks again.
        datahub.hub().set_updating(channel, None)
        self._on_data_status(f"The {channel} update stopped: the tools keep the previous version's data.",
                             sticky=True)

    def _on_game_started_data(self) -> None:
        """Safety net for updates the log didn't show: one look at Data.p4k's
        size and date, and a rebuild only if the game version changed."""
        self.patches.game_started()
        self._refresh_data()

    def _on_data_status(self, text: str, sticky: bool = False) -> None:
        if not text and getattr(self, "_data_sticky", False):
            return                      # keep an error or update notice visible until the next run
        self._data_sticky = sticky
        self.data_status.setText(text)
        self.data_status.setVisible(bool(text))

    # -- updates and What's new -------------------------------------------------
    def _setup_updates(self, live: bool) -> None:
        """live: a real run (not the smoke test), which checks for updates
        and remembers the What's new state."""
        self.updates = UpdateController(self)
        self.updates.checked.connect(self._on_update_checked)
        self.updates.check_failed.connect(self._on_update_check_failed)
        self.updates.progress.connect(self._on_update_progress)
        self.updates.install_failed.connect(self._on_update_install_failed)
        self.updates.installed.connect(self._on_update_installed)
        if not live:
            return
        # A quiet hint on the version after an update; nothing on a first run.
        seen = settings.current().changelog_seen
        if not seen:
            settings.apply(replace(settings.current(), changelog_seen=__version__))
        elif seen != __version__:
            self.title_bar.set_changelog_unseen(True)
        # At startup, then every few hours while it runs (the tray keeps it
        # alive for days); app.updater asks GitHub at most once a day.
        QTimer.singleShot(5000, self._auto_check_updates)
        self._update_timer = QTimer(self, interval=6 * 3600 * 1000)
        self._update_timer.timeout.connect(self._auto_check_updates)
        self._update_timer.start()

    def _auto_check_updates(self) -> None:
        if settings.current().update_check:
            self.updates.check()

    def _on_update_checked(self, release) -> None:
        self.title_bar.set_update(release.version if release else None)
        if self.whats_new_view is not None:
            self.whats_new_view.show_release(release)
            self.whats_new_view.show_check_result(
                "" if release else f"v{__version__} is the latest version")

    def _on_update_check_failed(self, message: str) -> None:
        if self.whats_new_view is not None:
            self.whats_new_view.show_check_result(message)

    def _show_whats_new(self) -> None:
        if self.whats_new_view is None:
            from app.ui.whats_new_view import WhatsNewView

            self.whats_new_view = WhatsNewView()
            self.whats_new_view.back_requested.connect(self._show_main)
            self.whats_new_view.check_requested.connect(lambda: self.updates.check(force=True))
            self.whats_new_view.install_requested.connect(self._install_update)
            self.stack.addWidget(self.whats_new_view)
        current = self.stack.currentWidget()
        if current in (self.bindings_view, self.salvage_view, self.mining_view, self.maps_view,
                       self.hangar_view):
            current.deactivate()
            if self._main_size is not None:
                self.resize(self._main_size)
        if not self.updates.installing:
            self.whats_new_view.show_release(self.updates.release)
        self.stack.setCurrentWidget(self.whats_new_view)
        if settings.current().changelog_seen != __version__:
            settings.apply(replace(settings.current(), changelog_seen=__version__))
        self.title_bar.set_changelog_unseen(False)

    def _install_update(self) -> None:
        view = self.whats_new_view
        if self.controller.busy:
            view.set_install_state("Finish the game session first: SC-Toolkit backs up your keybinds "
                                   "when the game closes.", False)
            return
        if osutil.is_game_running():
            view.set_install_state("Close Star Citizen and the RSI Launcher first.", False)
            return
        view.set_install_state("Downloading…", True)
        self.updates.install()

    def _on_update_progress(self, done: int, total: int) -> None:
        if self.whats_new_view is not None:
            self.whats_new_view.set_progress(done, total)

    def _on_update_install_failed(self, message: str) -> None:
        if self.whats_new_view is not None:
            self.whats_new_view.set_install_state(message, False)

    def _on_update_installed(self, target) -> None:
        try:
            updater.restart(target)
        except OSError as exc:
            self.whats_new_view.set_install_state(
                f"Installed. Couldn't restart it ({exc}): close SC-Toolkit and start it again.", False)
            return
        self.whats_new_view.set_install_state("Installed. Restarting…", True)
        QTimer.singleShot(300, QApplication.instance().quit)

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
        elif command == "live-log-on":         # the overlay's "Turn on live log"
            self.gamelog_switch.setChecked(True)

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
        self.overlay_hint.setText(f"{show} shows it, {click} click-through" if on else "off")

    def _set_gamelog_enabled(self, on: bool) -> None:
        if on != settings.current().gamelog_live_enabled:
            settings.apply(replace(settings.current(), gamelog_live_enabled=on))
        if not self._start_overlay:
            return
        # The overlay's live tabs run their own reader behind the same switch.
        ipc.send(ipc.OVERLAY, "live-log-on" if on else "live-log-off")
        if on:
            self.gamelog.start()
        else:
            self.gamelog.stop()

    def _update_gamelog_hint(self, state: str | None = None) -> None:
        state = state or self.gamelog.state
        self.gamelog_hint.setText({"waiting": "waiting for game", "reading": "reading"}.get(state, "off"))

    def read_log_history(self, kinds, output: str = gamelog.OUTPUT_EVENTS, on_done=None,
                         on_failed=None, **options) -> gamelog.HistoryJob:
        """Reads every Game.log on disk in the background for the given
        event kinds (see gamelog.EVENT_TYPES). `on_done` gets a list of
        gamelog.Event (output "events") or per-kind totals ("aggregate");
        options go to gamelog.read_history (channels, since, until).
        """
        job = gamelog.HistoryJob(settings.current().game_root, kinds, output, self, **options)
        self._history_jobs.add(job)

        def finish(*_):
            self._history_jobs.discard(job)
            job.deleteLater()
        if on_done is not None:
            job.finished.connect(on_done)
        if on_failed is not None:
            job.failed.connect(on_failed)
        job.finished.connect(finish)
        job.failed.connect(finish)
        job.start()
        return job

    def _open_overlay(self) -> None:
        """Settings' "Open the overlay": switches it on if needed and shows it."""
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
        self.gamelog.stop()
        for job in list(self._history_jobs):
            job.cancel()
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

        layout.addSpacing(14)
        layout.addWidget(_section_label("IN GAME"))
        layout.addWidget(self._build_overlay_switch())
        layout.addWidget(self._build_gamelog_switch())

        layout.addSpacing(10)
        self.status_label = QLabel("")
        self.status_label.setObjectName("SectionLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        # What app.datahub is fetching or reading (after a patch, once a day…).
        self.data_status = QLabel("", objectName="InspectorHint")
        self.data_status.setWordWrap(True)
        self.data_status.hide()
        layout.addWidget(self.data_status)
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

    # -- left panel: in-game switches ------------------------------------------
    def _switch_box(self, title: str, tip: str, checked: bool, on_toggle) -> tuple[QFrame, QLabel, Switch]:
        """A labelled on/off switch with a status line under the label."""
        box = QFrame(objectName="OverlaySwitchBox")
        box.setToolTip(tip)
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 6, 10, 6)
        row.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(QLabel(title, objectName="OverlaySwitchLabel"))
        hint = QLabel("", objectName="OverlaySwitchHint")
        text.addWidget(hint)
        row.addLayout(text, stretch=1)
        switch = Switch()
        switch.setChecked(checked)
        switch.toggled.connect(on_toggle)
        row.addWidget(switch, alignment=Qt.AlignVCenter)
        return box, hint, switch

    def _build_overlay_switch(self) -> QWidget:
        box, self.overlay_hint, self.overlay_switch = self._switch_box(
            "IN-GAME OVERLAY",
            "Missions, session status, Maps, Mining and Salvage in a small window on top of the game "
            "(run Star Citizen in Borderless mode). Hotkeys and more in Settings.",
            settings.current().overlay_enabled, self._set_overlay_enabled)
        self._update_overlay_hint()
        return box

    def _build_gamelog_switch(self) -> QWidget:
        box, self.gamelog_hint, self.gamelog_switch = self._switch_box(
            "LIVE LOG",
            "Follows Star Citizen's Game.log while you play (from the start of the "
            "current game session) so tools can react to contracts, payouts and more.",
            settings.current().gamelog_live_enabled, self._set_gamelog_enabled)
        self._update_gamelog_hint()
        return box

    # -- middle: SC-Toolkit's own tools ---------------------------------------
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
        self.stats_tile = _ToolTile(
            "stats", "My Stats",
            "Your missions, blueprints, money, travel, ships and losses from the game's "
            "logs: all time and your last session.",
        )
        self.stats_tile.clicked.connect(self._show_stats)
        hangar_tile = _ToolTile(
            "hangar", "My Ships",
            "Your hangar: the ships you pledged or bought in game, ships in concept with their "
            "loaners, and a link to each on Erkul.",
        )
        hangar_tile.clicked.connect(self._show_hangar)
        for i, tile in enumerate((self.bindings_btn, self.salvage_btn, self.mining_btn, maps_tile,
                                  self.stats_tile, hangar_tile)):
            grid.addWidget(tile, i // 2, i % 2)
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

    # -- My Stats ----------------------------------------------------------------
    def _show_stats(self) -> None:
        if self.stats_view is None:
            from app.ui.stats_view import StatsView

            self.stats_view = StatsView()
            self.stats_view.back_requested.connect(self._show_main)
            self.stack.addWidget(self.stats_view)
        self._main_size = self._normal_size()
        screen = self.screen().availableGeometry()
        self.resize(min(1320, int(screen.width() * 0.9)), min(900, int(screen.height() * 0.9)))
        self.stack.setCurrentWidget(self.stats_view)
        self.stats_view.activate()

    # -- My Ships -------------------------------------------------------------------
    def _show_hangar(self) -> None:
        if self.hangar_view is None:
            from app.ui.hangar_view import HangarView

            self.hangar_view = HangarView()
            self.hangar_view.back_requested.connect(self._show_main)
            self.stack.addWidget(self.hangar_view)
        self._main_size = self._normal_size()
        screen = self.screen().availableGeometry()
        self.resize(min(1400, int(screen.width() * 0.92)), min(920, int(screen.height() * 0.9)))
        self.stack.setCurrentWidget(self.hangar_view)
        self.hangar_view.activate()

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
    def _on_account_clicked(self) -> None:
        """Title bar account button: signed out, it starts the browser sign-in straight away (and
        shows its progress in Settings); otherwise it opens the account panel."""
        from app.account_controller import controller as account_controller

        account = account_controller()
        if account.state.status == "signed_out":
            account.sign_in()
        self._show_settings()
        self.settings_view.show_account_panel()

    def _show_settings(self, first_run: bool = False) -> None:
        if self.stack.currentWidget() is self.settings_view:
            return
        if self.settings_view is None:
            from app.ui.settings_view import SettingsView

            self.settings_view = SettingsView()
            self.settings_view.back_requested.connect(self._show_main)
            self.settings_view.saved.connect(self._on_settings_saved)
            self.settings_view.open_overlay_requested.connect(self._open_overlay)
            self.stack.addWidget(self.settings_view)
        current = self.stack.currentWidget()
        if current in (self.bindings_view, self.salvage_view, self.mining_view, self.maps_view,
                       self.hangar_view):
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
        if self._start_overlay:
            self.patches.start()        # the RSI Launcher log setting may have changed
            self._refresh_data()        # a new game folder may need its game data read
        self._refresh_config_combo()
        self._apply_channel_state()
        self._update_overlay_hint()
        if not settings.current().update_check:
            self.title_bar.set_update(None)
        elif self._start_overlay:
            self.updates.check()        # asks GitHub again only if "beta versions" changed
        if self._start_overlay and settings.current().overlay_enabled:
            # New hotkeys / game folder: the overlay reads them at start.
            self.overlay.stop()
            self.overlay.start()
        self._show_main()

    def _show_main(self) -> None:
        current = self.stack.currentWidget()
        if current in (self.bindings_view, self.salvage_view, self.mining_view, self.maps_view,
                       self.hangar_view):
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
