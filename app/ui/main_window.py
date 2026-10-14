import subprocess
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QRectF, QSize, QTimer, Signal
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
    QMessageBox,
    QProgressBar,
    QStackedWidget,
)

from dataclasses import replace

from app import (
    __version__, backup, channel as channel_mod, config, datahub, gamelog, ipc, links, maps, osutil, settings,
    updater,
)
from app.backup import BackupInfo
from app import hotkeys
from app import process
from app.launch import LaunchController
from app.overlay_host import OverlayHost
from app.patchwatch import PatchWatcher
from app.starstrings_controller import StarStringsController
from app.update_controller import UpdateController
from app.theme import PALETTE
from app.ui.kit import ToolRail
from app.ui.title_bar import TitleBar, _shadow
from app.ui.widgets import Switch

ICON_SIZE = QSize(20, 20)


def _icon(name: str) -> QIcon:
    return QIcon(str(config.ICONS_DIR / f"{name}.png"))

CORNER_RADIUS = 14

# The tool rail: (key, icon, caption). Tools in NEEDS_GAME read the game files.
RAIL_ITEMS = [
    ("launch", "launch", "Launch"),
    ("missions", "missions", "Missions"),
    ("mining", "mining", "Mining"),
    ("salvage", "salvage", "Salvage"),
    ("stats", "stats", "My Stats"),
    ("hangar", "hangar", "My Ships"),
    ("maps", "scmaps", "Maps"),
    ("bindings", "joystick", "Bindings"),
]
NEEDS_GAME = {"missions", "mining", "salvage", "bindings"}


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
    """A tool on the launch screen: icon, name, one line on what it's for,
    and a live line (what's in it right now)."""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolTile")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        grid = QGridLayout(self)
        grid.setContentsMargins(14, 12, 14, 11)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        icon = QLabel()
        pix = (QIcon(str(config.APP_ICON)) if icon_name == "app" else _icon(icon_name)).pixmap(36, 36)
        icon.setPixmap(pix)
        icon.setFixedSize(36, 36)
        grid.addWidget(icon, 0, 0, 2, 1, Qt.AlignTop)
        grid.addWidget(QLabel(title, objectName="TileTitle"), 0, 1)
        self.body = body = QLabel(text, objectName="TileText")
        body.setWordWrap(True)
        grid.addWidget(body, 1, 1)
        self.live = QLabel("", objectName="TileLive")
        self.live.setTextFormat(Qt.RichText)
        self.live.setOpenExternalLinks(True)
        grid.addWidget(self.live, 2, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)

    def set_live(self, html: str) -> None:
        self.live.setText(html)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton and self.isEnabled()
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _HomeLoader(QObject):
    """What the launch screen shows about your data: the last play session
    (read from its own log only) and a few counts. Off the UI thread."""

    loaded = Signal(dict)

    def run(self) -> None:
        def work():
            out: dict = {}
            root = settings.current().game_root
            try:
                from app import stats

                sessions = [s for s in gamelog.all_sessions(root) if s.started]
                if sessions:
                    latest = sessions[-1]
                    events = [e for e in gamelog.read_history(root, stats.KINDS, gamelog.OUTPUT_EVENTS,
                                                              since=latest.started)
                              if e.session == latest.id]
                    tiles = {name: value for sec in stats._scope(events, [latest], None)
                             for name, value, _hint in sec["tiles"]}
                    end = latest.ended()
                    out["last"] = {
                        "when": "{} {} {}".format(
                            ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[latest.started.astimezone().weekday()],
                            latest.started.astimezone().day, kit_months()[latest.started.astimezone().month - 1]),
                        "played": tiles.get("Time played", "—"),
                        "missions": tiles.get("Completed", "0"),
                        "blueprints": tiles.get("Received", "0"),
                        "deaths": tiles.get("Deaths", "0"),
                        "ended": end,
                    }
            except Exception:
                import traceback

                traceback.print_exc()
            try:
                channel = channel_mod.pick_default_channel(root)
                croot = channel_mod.resolve_channel_paths(root, channel).channel_root if channel else None
                mining_data = datahub.read_game("mining", croot)
                if mining_data:
                    out["locations"] = len(mining_data["locations"])
                contracts = datahub.read_game("contracts", croot)
                if contracts is not None:
                    out["missions"] = len(contracts)
                    out["channel"] = channel
            except Exception:
                pass
            self.loaded.emit(out)
        threading.Thread(target=work, daemon=True).start()


def kit_months():
    from app.ui.kit import MONTHS

    return MONTHS


class RootFrame(QWidget):
    """Paints the Polaris background art (cropped to fill, darkened with a
    gradient for legibility) behind everything else, clipped to rounded
    window corners.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RootFrame")
        self._bg = QPixmap(str(config.BACKGROUND_IMAGE))
        self.scrim = 0          # 0–255: darkens the wallpaper behind the tools

    def set_scrim(self, alpha: int) -> None:
        if alpha != self.scrim:
            self.scrim = alpha
            self.update()

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
            if self.scrim:
                # Dimmed behind the tools, but never the STAR CITIZEN watermark
                # (the Fankit terms want it visible).
                fx, fy, fw, fh = config.BACKGROUND_WATERMARK
                mark = QRectF(x0 + scaled.width() * fx, bottom - scaled.height() + scaled.height() * fy,
                              scaled.width() * fw, scaled.height() * fh).adjusted(-6, -6, 6, 6)
                shade = QPainterPath()
                shade.addRect(QRectF(self.rect()))
                hole = QPainterPath()
                hole.addRoundedRect(mark, 8, 8)
                painter.fillPath(shade.subtracted(hole), QColor(9, 11, 13, self.scrim))

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

        self.sync = None                     # app.sync.SyncController (live runs only)
        self.channel = channel_mod.pick_default_channel(settings.current().game_root)
        self._mode = "start"  # "start" | "close"
        self._combo_backups: list[BackupInfo] = []

        self.controller = LaunchController(self)
        self.game_watcher = process.GameWatcher(self)
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
        title_bar.whats_new_requested.connect(self._show_whats_new)
        outer.addWidget(title_bar)

        # The tool rail on the left; the launch screen and every tool share the
        # rest of the window. Tool views are built on first use.
        middle = QHBoxLayout()
        middle.setContentsMargins(14, 6, 0, 10)
        middle.setSpacing(12)
        self.rail = ToolRail(RAIL_ITEMS, [("settings", "settings", "Settings")])
        self.rail.selected.connect(self.show_tool)
        middle.addWidget(self.rail)
        self.stack = QStackedWidget()
        middle.addWidget(self.stack, stretch=1)
        outer.addLayout(middle, stretch=1)
        self._views: dict[str, QWidget] = {}
        self._current = "launch"

        # Footer band: CIG's notice (required by the Fankit Agreement wherever
        # their material is shown) on the left, and a clear area on the right
        # where the wallpaper's watermark shows. Its height follows the window
        # because the watermark scales with the wallpaper.
        self.footer = QWidget()
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(100, 0, 0, 4)
        notice = QLabel(config.CIG_NOTICE, objectName="CigNotice")
        notice.setWordWrap(True)
        _shadow(notice)
        notice.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        footer_layout.addWidget(notice, stretch=1)
        self._watermark_gap = footer_layout.addSpacing(0) or footer_layout.itemAt(1)
        outer.addWidget(self.footer)
        self.settings_view = None
        self.whats_new_view = None

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 18, 0)
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
        self.game_watcher.changed.connect(self._update_game_state)
        self.game_watcher.start()
        self._setup_data(live=start_overlay)
        # The online account (optional): the title bar mirrors it; a sign-in kept in the keyring is
        # picked up at startup.
        from app.account_controller import controller as account_controller
        account = account_controller()
        account.changed.connect(lambda st: self.title_bar.set_account(
            st.status, st.profile.display_name if st.profile else "", st.offline,
            st.profile.avatar_url if st.profile else None))
        title_bar.account_requested.connect(self._on_account_clicked)
        account.changed.connect(self._on_account_for_sync)
        if start_overlay:
            from app.sync import SyncController

            self.sync = SyncController(self.gamelog, self)
            self.sync.status.connect(self._on_sync_status)
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
        # previous data; the next start of SC-Toolbox or the game checks again.
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
        if not self.updates.installing:
            self.whats_new_view.show_release(self.updates.release)
        self._switch_to("whatsnew", self.whats_new_view)
        if settings.current().changelog_seen != __version__:
            settings.apply(replace(settings.current(), changelog_seen=__version__))
        self.title_bar.set_changelog_unseen(False)

    def _install_update(self) -> None:
        view = self.whats_new_view
        if self.controller.busy:
            view.set_install_state("Finish the game session first: SC-Toolbox backs up your keybinds "
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
                f"Installed. Couldn't restart it ({exc}): close SC-Toolbox and start it again.", False)
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
        elif command == "settings":            # the overlay's ⋯ → Overlay settings
            self.show_launcher()
            self._show_settings()
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
        self.overlay_hint.setText(f"{show} show · {click} click-through" if on else "Off")

    def _set_gamelog_enabled(self, on: bool) -> None:
        if on != settings.current().gamelog_live_enabled:
            settings.apply(replace(settings.current(), gamelog_live_enabled=on))
        if not on and self.sync_switch.isChecked():
            self.sync_switch.setChecked(False)       # sync follows the live log
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
        self.gamelog_hint.setText({"waiting": "Waiting for the game", "reading": "Reading Game.log"}.get(state, "Off"))

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
        layout.addWidget(self._build_sync_switch())

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
        self.config_label.setText("LAUNCH WITH" + (f" · {self.channel}" if has_game else ""))
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
        for btn in (self.bindings_btn, self.salvage_btn, self.mining_btn, self.starstrings_btn,
                    self.tiles["missions"]):
            btn.setEnabled(has_game)
        for key in NEEDS_GAME:
            self.rail.set_enabled(key, has_game, "" if has_game else "Set your Star Citizen folder in Settings")
        self._update_game_state()
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
                f"SC-Toolbox (not yet backed up) will be lost."
            )
        self.config_help.style().unpolish(self.config_help)
        self.config_help.style().polish(self.config_help)

    def _selected_backup(self) -> BackupInfo | None:
        data = self.config_combo.currentData()
        return data if isinstance(data, BackupInfo) else None

    def _set_status(self, text: str) -> None:
        # Nothing to say while idle; otherwise what the launcher is doing.
        self.status_label.setText("" if text == "Idle" else text)
        self.status_label.setVisible(text != "Idle" and bool(text))

    def _update_game_state(self, *_args) -> None:
        """The light at the bottom of the rail, from the running processes
        (app.process.GameWatcher): Ready, Launcher (the RSI Launcher runs) or
        Game (Star Citizen runs), whoever started them."""
        state = getattr(self, "game_watcher", None) and self.game_watcher.state
        if self.channel is None:
            self.rail.set_game_state("SET UP", "warning")
        elif state == process.GAME:
            self.rail.set_game_state("IN GAME", "info")
        elif state == process.LAUNCHER:
            self.rail.set_game_state("LAUNCHER", "info")
        elif self.controller.busy:
            self.rail.set_game_state("STARTING", "info")
        else:
            self.rail.set_game_state("READY", "success")
        self._sync_start_button(state)

    def _sync_start_button(self, state: str | None) -> None:
        """Game or RSI Launcher started outside SC-Toolbox (or before it):
        START can't launch now, and says why."""
        if self.controller.busy or self._mode != "start":
            return
        running = state in (process.GAME, process.LAUNCHER)
        self.start_btn.setEnabled(not running and self.channel is not None)
        self.start_btn.setText({process.GAME: "IN GAME", process.LAUNCHER: "LAUNCHER OPEN"}.get(state, "START"))
        self.start_btn.setToolTip("Star Citizen is running" if state == process.GAME else
                                  "The RSI Launcher is open: start the game from it, or close it to "
                                  "launch with SC-Toolbox" if state == process.LAUNCHER else "")

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
        self._update_game_state()

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
        self._update_game_state()

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
            "Overlay",
            "Missions, session status, Maps, Mining and Salvage in a small window on top of the game "
            "(run Star Citizen in Borderless mode). Hotkeys and more in Settings.",
            settings.current().overlay_enabled, self._set_overlay_enabled)
        self._update_overlay_hint()
        return box

    def _build_sync_switch(self) -> QWidget:
        """Sync online: shown while signed in. Needs the live log, so it turns it on
        (and turning the live log off turns sync off)."""
        box, self.sync_hint, self.sync_switch = self._switch_box(
            "Sync online",
            "Keeps sc-toolbox.com up to date: your stats and blueprints from your game logs, and My "
            "Ships both ways. Online keeps everything, also when this PC has less.",
            settings.current().sync_enabled, self._set_sync_enabled)
        self.sync_box = box
        self.sync_hint.setTextFormat(Qt.RichText)
        self.sync_hint.linkActivated.connect(lambda _l: self._sign_in_again())
        box.setVisible(False)
        return box

    def _set_sync_enabled(self, on: bool) -> None:
        if on and not self.gamelog_switch.isChecked():
            self.gamelog_switch.setChecked(True)     # sync reads the live log
        if self.sync is not None:
            self.sync.set_enabled(on)
        elif on != settings.current().sync_enabled:
            settings.apply(replace(settings.current(), sync_enabled=on))

    def _on_sync_status(self, text: str, tone: str) -> None:
        colour = {"success": PALETTE["success"], "warning": PALETTE["warning"], "danger": PALETTE["danger"],
                  "info": PALETTE["info"]}.get(tone, PALETTE["text_muted"])
        if text.startswith("Sign in again"):
            # The sign-in predates the sync permissions (or expired): one click to renew it.
            self.sync_hint.setText(f"<a href='signin' style='color:{colour}'>{text}</a>")
        else:
            self.sync_hint.setText(f"<span style='color:{colour}'>{text}</span>")

    def _sign_in_again(self) -> None:
        from app.account_controller import controller as account_controller

        account_controller().sign_in()

    def _on_account_for_sync(self, state) -> None:
        self.sync_box.setVisible(state.status == "signed_in")

    def _build_gamelog_switch(self) -> QWidget:
        box, self.gamelog_hint, self.gamelog_switch = self._switch_box(
            "Live log",
            "Follows Star Citizen's Game.log while you play (from the start of the "
            "current game session) so tools can react to contracts, payouts and more.",
            settings.current().gamelog_live_enabled, self._set_gamelog_enabled)
        self._update_gamelog_hint()
        return box

    # -- middle: SC-Toolbox's own tools ---------------------------------------
    def _build_tools_panel(self) -> QWidget:
        # No panel behind this column: each tile carries its own glass, so the
        # wallpaper shows through around and below them.
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(10)
        tiles = [
            ("missions", "missions", "Mission Database", "Every mission, its rewards and blueprints"),
            ("mining", "mining", "Mining Finder", "Where each ore spawns and how to spot it"),
            ("salvage", "salvage", "Salvage Claims", "Which claim ship pays the most"),
            ("stats", "stats", "My Stats", "Your play time, missions and earnings"),
            ("hangar", "hangar", "My Ships", "Your pledged and in-game ships"),
            ("maps", "scmaps", "SC Maps", "One-page guides by Mr Kraken"),
            ("bindings", "joystick", "Joystick Bindings", "See and rebind every button"),
            ("web", "app", "sc-toolbox.com", "Blueprints and the Ship Database, online"),
        ]
        self.tiles: dict[str, _ToolTile] = {}
        for i, (key, icon_name, title, text) in enumerate(tiles):
            tile = _ToolTile(icon_name, title, text)
            if key == "web":
                tile.clicked.connect(lambda: osutil.open_url("https://sc-toolbox.com"))
                tile.set_live("Opens in your browser ↗")
            else:
                tile.clicked.connect(lambda k=key: self.show_tool(k))
            self.tiles[key] = tile
            grid.addWidget(tile, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        self.bindings_btn, self.salvage_btn = self.tiles["bindings"], self.tiles["salvage"]
        self.mining_btn, self.stats_tile = self.tiles["mining"], self.tiles["stats"]
        self.tiles["maps"].set_live(f"{len(maps.GUIDES)} guides")
        self._home_loader = _HomeLoader(self)
        self._home_loader.loaded.connect(self._on_home_data)
        QTimer.singleShot(300, self._refresh_home)
        return panel

    def _refresh_home(self) -> None:
        from app import hangar, salvage

        entries = hangar.load()
        self.tiles["hangar"].set_live(f"<b>{len(entries)}</b> ship{'s' if len(entries) != 1 else ''}"
                                      if entries else "Add the ships you own")
        uex = salvage.load_uex()
        from app.ui.kit import short_date

        self.tiles["salvage"].set_live(f"Prices from <b>{short_date(uex[0] if uex else None)}</b>")
        profiles = backup.list_profiles(settings.current().backup_root, self.channel) if self.channel else []
        self.tiles["bindings"].set_live(f"<b>{len(profiles)}</b> saved profile{'s' if len(profiles) != 1 else ''}"
                                        if profiles else "Save a layout as a launch profile")
        self._home_loader.run()

    def _on_home_data(self, data: dict) -> None:
        if "missions" in data:
            self.tiles["missions"].set_live(f"<b>{data['missions']:,}</b> missions · {data.get('channel', '')}")
        if "locations" in data:
            self.tiles["mining"].set_live(f"<b>{data['locations']}</b> locations")
        last = data.get("last")
        if not last:
            self.last_session.hide()
            self.tiles["stats"].set_live("From your game logs")
            return
        self.tiles["stats"].set_live(f"Last session <b>{last['played']}</b>")
        self.last_title.setText(f"LAST SESSION · {last['when'].upper()}")
        for key, stat in self.last_stats.items():
            stat.value.setText(last[key])
        blueprints = last["blueprints"] not in ("0", "—")
        self.last_stats["blueprints"].value.setProperty("tone", "success" if blueprints else "")
        from app.ui.kit import repolish

        repolish(self.last_stats["blueprints"].value)
        self.last_session.show()

    # -- right panel: last session, external tools, links ------------------------------
    def _build_link_panel(self) -> QWidget:
        from app.ui import kit

        column = QWidget()
        column.setFixedWidth(250)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        self.last_session = kit.panel()
        lv = QVBoxLayout(self.last_session)
        lv.setContentsMargins(14, 12, 14, 12)
        lv.setSpacing(8)
        self.last_title = kit.caps("Last session")
        lv.addWidget(self.last_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.last_stats = {}
        for i, (key, caption) in enumerate((("played", "played"), ("missions", "missions done"),
                                           ("blueprints", "blueprints"), ("deaths", "deaths"))):
            stat = kit.Stat("—", caption, size="md")
            self.last_stats[key] = stat
            grid.addWidget(stat, i // 2, i % 2)
        lv.addLayout(grid)
        more = kit.button("All your stats →", "ghost", lambda: self.show_tool("stats"))
        lv.addWidget(more, alignment=Qt.AlignLeft)
        self.last_session.hide()
        col.addWidget(self.last_session)

        tools = kit.panel()
        tv = QVBoxLayout(tools)
        tv.setContentsMargins(14, 12, 14, 12)
        tv.setSpacing(6)
        tv.addWidget(kit.caps("Also"))
        self.gameglass_btn = self._tool_button("GameGlass", "gameglass", self._launch_gameglass)
        tv.addWidget(self.gameglass_btn)
        self.starstrings_btn = self._tool_button(
            "Update Star Strings", "starstrings", self._on_update_starstrings_clicked)
        tv.addWidget(self.starstrings_btn)
        col.addWidget(tools)

        for title, items in (("Official", links.OFFICIAL_LINKS), ("Community", links.COMMUNITY_LINKS)):
            box = kit.panel()
            bv = QVBoxLayout(box)
            bv.setContentsMargins(14, 12, 14, 12)
            bv.setSpacing(6)
            bv.addWidget(kit.caps(title))
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, (label, url, icon_name) in enumerate(items):
                text = {"Server Status": "Servers"}.get(label, label.split(" (")[0])
                last_alone = i == len(items) - 1 and i % 2 == 0
                grid.addWidget(self._link_button(text, icon_name, url), i // 2, i % 2, 1, 2 if last_alone else 1)
            bv.addLayout(grid)
            col.addWidget(box)
        col.addStretch(1)
        return column

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
        btn.setObjectName("LinkChip")
        btn.setIcon(_icon(icon_name))
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(url)
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

    # -- tools: the rail and the views ---------------------------------------------
    def show_tool(self, key: str) -> None:
        """Shows the launch screen ("launch") or a tool view, building it on
        first use; the rail follows."""
        if key == "settings":
            self._show_settings()
            return
        if key == "whatsnew":
            self._show_whats_new()
            return
        if key != "launch" and key in NEEDS_GAME and self.channel is None:
            key = "launch"
        view = self.stack.widget(0) if key == "launch" else self._view(key)
        self._switch_to(key, view)

    def _switch_to(self, key: str, view: QWidget) -> None:
        previous = self.stack.currentWidget()
        if previous is not view and hasattr(previous, "can_leave") and not previous.can_leave():
            self.rail.set_current(self._current)
            return
        if previous is not view and hasattr(previous, "deactivate"):
            previous.deactivate()
        self._current = key
        self.rail.set_current(key)
        self.centralWidget().set_scrim(0 if key == "launch" else 150)
        self.stack.setCurrentWidget(view)
        if hasattr(view, "activate") and key != "settings":
            view.activate()

    def _view(self, key: str) -> QWidget:
        view = self._views.get(key)
        if view is not None:
            return view
        if key == "bindings":
            from app.ui.bindings_view import BindingsView

            view = BindingsView(self.channel)
            view.profiles_changed.connect(self._refresh_config_combo)
        elif key == "salvage":
            from app.ui.salvage_view import SalvageView

            view = SalvageView(self.channel)
        elif key == "mining":
            from app.ui.mining_view import MiningView

            view = MiningView(self.channel)
        elif key == "missions":
            from app.ui.missions_view import MissionsView

            view = MissionsView(self.channel)
        elif key == "stats":
            from app.ui.stats_view import StatsView

            view = StatsView()
        elif key == "hangar":
            from app.ui.hangar_view import HangarView

            view = HangarView()
            if self.sync is not None:
                view.attach_sync(self.sync)
        elif key == "maps":
            from app.ui.maps_view import MapsView

            view = MapsView()
        else:
            raise KeyError(key)
        view.back_requested.connect(self._show_main)
        if hasattr(view, "open_tool"):
            view.open_tool.connect(self.open_tool)
        self._views[key] = view
        self.stack.addWidget(view)
        return view

    def open_tool(self, key: str, target: object = None) -> None:
        """Links between tools: opens `key` and, if it can, points it at `target`."""
        self.show_tool(key)
        view = self._views.get(key)
        if view is not None and target is not None and hasattr(view, "focus_on"):
            view.focus_on(target)

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
        if self.settings_view is None:
            from app.ui.settings_view import SettingsView

            self.settings_view = SettingsView()
            self.settings_view.back_requested.connect(self._show_main)
            self.settings_view.saved.connect(self._on_settings_saved)
            self.settings_view.open_overlay_requested.connect(self._open_overlay)
            self.settings_view.sync_toggled.connect(self.sync_switch.setChecked)
            self.sync_switch.toggled.connect(self.settings_view.set_sync)
            self.stack.addWidget(self.settings_view)
        if self.stack.currentWidget() is not self.settings_view:
            self._switch_to("settings", self.settings_view)
            self.settings_view.activate(first_run)

    def _on_settings_saved(self) -> None:
        # Tools built against the old install are rebuilt on next use.
        for key in ("bindings", "salvage", "mining", "missions"):
            view = self._views.pop(key, None)
            if view is not None:
                self.stack.removeWidget(view)
                view.deleteLater()
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
        self.show_tool("launch")

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
