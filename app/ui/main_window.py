import subprocess

from PySide6.QtCore import Qt, QRectF, QSize, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QSizePolicy,
    QMessageBox,
    QProgressBar,
    QMenu,
    QStackedWidget,
)

from app import backup, channel as channel_mod, config, links, maps, osutil, settings
from app.backup import BackupInfo
from app.launch import LaunchController
from app.starstrings_controller import StarStringsController
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
        path.addRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)
        painter.setClipPath(path)

        painter.fillPath(path, QColor("#0d0f12"))
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
    WIDTH = 1080
    HEIGHT = 840

    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.WIDTH, self.HEIGHT)
        self.setMinimumSize(900, 820)

        self.channel = channel_mod.pick_default_channel(settings.current().game_root)
        self._mode = "start"  # "start" | "close"
        self._combo_backups: list[BackupInfo] = []

        self.controller = LaunchController(self)
        self.controller.status_changed.connect(self._set_status)
        self.controller.session_started.connect(self._on_session_started)
        self.controller.session_ended.connect(self._on_session_ended)
        self.controller.backup_created.connect(self._on_backup_created)
        self.controller.backup_skipped.connect(self._on_session_finished)
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

        title_bar = TitleBar()
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
        self._main_size = None

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 20, 20, 20)
        body_layout.setSpacing(16)
        self.stack.addWidget(body)

        body_layout.addWidget(self._build_launch_panel(), stretch=0)
        body_layout.addStretch(1)
        body_layout.addWidget(self._build_link_panel(), stretch=0)
        self._apply_channel_state()

        # Nothing configured yet (first run on this machine): settings first.
        if settings.validate_live_dir(settings.current().live_dir) is not None:
            QTimer.singleShot(0, lambda: self._show_settings(first_run=True))

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
        self.config_label = QLabel("CONFIG", objectName="ConfigLabel")
        layout.addWidget(self.config_label)

        self.config_combo = QComboBox()
        self.config_combo.setObjectName("ConfigCombo")
        layout.addWidget(self.config_combo)
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
        self.config_label.setText("CONFIG" + (f" ({self.channel})" if has_game else ""))
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
        combo.addItem("Unchanged")
        combo.setItemData(0, "Loads whatever is already in the game", Qt.ToolTipRole)

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

    def _selected_backup(self) -> BackupInfo | None:
        data = self.config_combo.currentData()
        return data if isinstance(data, BackupInfo) else None

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_start_enabled(self, enabled: bool) -> None:
        self.start_btn.setEnabled(enabled and self.channel is not None)

    def _set_button_mode(self, mode: str) -> None:
        self._mode = mode
        self.start_btn.setText("CLOSE" if mode == "close" else "START")
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

    def _on_session_ended(self) -> None:
        self.busy_bar.setVisible(True)
        self.start_btn.setEnabled(False)

    def _on_backup_created(self, _display_name: str) -> None:
        self._refresh_config_combo()
        self._on_session_finished()

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

    # -- right panel: link library -------------------------------------------
    def _build_link_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SidePanel")
        panel.setFixedWidth(300)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 20, 18, 20)
        layout.setSpacing(6)

        layout.addWidget(_section_label("OFFICIAL"))
        for label, url, icon_name in links.OFFICIAL_LINKS:
            layout.addWidget(self._link_button(label, icon_name, url))

        layout.addSpacing(6)
        layout.addWidget(_divider())
        layout.addSpacing(6)

        layout.addWidget(_section_label("COMMUNITY TOOLS"))
        for label, url, icon_name in links.COMMUNITY_LINKS:
            layout.addWidget(self._link_button(label, icon_name, url))

        layout.addSpacing(6)
        layout.addWidget(_divider())
        layout.addSpacing(6)

        layout.addWidget(_section_label("TOOLS"))

        self.bindings_btn = bindings_btn = QPushButton("Joystick Bindings")
        bindings_btn.setObjectName("ToolButton")
        bindings_btn.setIcon(_icon("joystick"))
        bindings_btn.setIconSize(ICON_SIZE)
        bindings_btn.setCursor(Qt.PointingHandCursor)
        bindings_btn.setEnabled(self.channel is not None)
        bindings_btn.clicked.connect(self._show_bindings)
        layout.addWidget(bindings_btn)

        self.salvage_btn = salvage_btn = QPushButton("Salvage Claims")
        salvage_btn.setObjectName("ToolButton")
        salvage_btn.setIcon(_icon("salvage"))
        salvage_btn.setIconSize(ICON_SIZE)
        salvage_btn.setCursor(Qt.PointingHandCursor)
        salvage_btn.setEnabled(self.channel is not None)
        salvage_btn.clicked.connect(self._show_salvage)
        layout.addWidget(salvage_btn)

        self.mining_btn = mining_btn = QPushButton("Mining Finder")
        mining_btn.setObjectName("ToolButton")
        mining_btn.setIcon(_icon("mining"))
        mining_btn.setIconSize(ICON_SIZE)
        mining_btn.setCursor(Qt.PointingHandCursor)
        mining_btn.setEnabled(self.channel is not None)
        mining_btn.clicked.connect(self._show_mining)
        layout.addWidget(mining_btn)

        self.gameglass_btn = gameglass_btn = QPushButton("GameGlass")
        gameglass_btn.setObjectName("ToolButton")
        gameglass_btn.setIcon(_icon("gameglass"))
        gameglass_btn.setIconSize(ICON_SIZE)
        gameglass_btn.setCursor(Qt.PointingHandCursor)
        gameglass_btn.clicked.connect(self._launch_gameglass)
        layout.addWidget(gameglass_btn)

        scmaps_btn = QPushButton("SC Maps")
        scmaps_btn.setObjectName("ToolButton")
        scmaps_btn.setIcon(_icon("scmaps"))
        scmaps_btn.setIconSize(ICON_SIZE)
        scmaps_btn.setCursor(Qt.PointingHandCursor)
        scmaps_btn.clicked.connect(lambda: self._show_maps_menu(scmaps_btn))
        layout.addWidget(scmaps_btn)

        self.starstrings_btn = QPushButton("Update Star Strings")
        self.starstrings_btn.setObjectName("ToolButton")
        self.starstrings_btn.setIcon(_icon("starstrings"))
        self.starstrings_btn.setIconSize(ICON_SIZE)
        self.starstrings_btn.setCursor(Qt.PointingHandCursor)
        self.starstrings_btn.setEnabled(self.channel is not None)
        self.starstrings_btn.clicked.connect(self._on_update_starstrings_clicked)
        layout.addWidget(self.starstrings_btn)

        layout.addStretch(1)
        return panel

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

    def _show_maps_menu(self, anchor: QPushButton) -> None:
        menu = QMenu(self)
        menu.addSection("Mr Kraken's Guides")
        for title, pages, _source_url in maps.GUIDES:
            if len(pages) == 1:
                action = menu.addAction(title)
                action.triggered.connect(lambda checked=False, u=pages[0][1]: self._open_url(u))
            else:
                submenu = menu.addMenu(title)
                for label, url in pages:
                    action = submenu.addAction(label)
                    action.triggered.connect(lambda checked=False, u=url: self._open_url(u))
        menu.addSeparator()
        more_action = menu.addAction("More guides (mrkraken.space)")
        more_action.triggered.connect(lambda: self._open_url(maps.GUIDES_INDEX_URL))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

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
        self._main_size = self.size()
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
        self._main_size = self.size()
        screen = self.screen().availableGeometry()
        self.resize(min(1320, int(screen.width() * 0.9)), min(900, int(screen.height() * 0.9)))
        self.stack.setCurrentWidget(self.salvage_view)
        self.salvage_view.activate()

    # -- mining finder view ------------------------------------------------------
    def _show_mining(self) -> None:
        if self.mining_view is None:
            from app.ui.mining_view import MiningView

            self.mining_view = MiningView(self.channel)
            self.mining_view.back_requested.connect(self._show_main)
            self.stack.addWidget(self.mining_view)
        self._main_size = self.size()
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
        if current in (self.bindings_view, self.salvage_view, self.mining_view):
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
        self._show_main()

    def _show_main(self) -> None:
        current = self.stack.currentWidget()
        if current in (self.bindings_view, self.salvage_view, self.mining_view):
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
