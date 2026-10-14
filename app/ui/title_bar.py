from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpacerItem, QWidget,
)

from app import __version__
from app.ui.widgets import AvatarLoader, initial_pixmap, round_pixmap

AVATAR = 20

def _shadow(widget: QWidget) -> QWidget:
    """Soft dark halo so text stays legible straight on the wallpaper."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(10)
    effect.setOffset(0, 1)
    effect.setColor(QColor(0, 0, 0, 230))
    widget.setGraphicsEffect(effect)
    return widget


class TitleBar(QWidget):
    """Frameless-window title bar (transparent over the wallpaper): app name
    and version + drag-to-move + account / minimize / maximize / close
    (Settings is in the tool rail). The version opens What's new; an Update button appears next to it
    when a new version is out. The account button shows the online sign-in
    (hidden while no service is configured).
    """

    whats_new_requested = Signal()
    account_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        # Plain QWidget subclasses only paint their stylesheet background with this.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(4)

        layout.addWidget(_shadow(QLabel("SC-TOOLBOX")))
        layout.addSpacing(6)
        self.version_btn = QPushButton(objectName="TitleVersion")
        self.version_btn.setCursor(Qt.PointingHandCursor)
        self.version_btn.clicked.connect(self.whats_new_requested.emit)
        layout.addWidget(_shadow(self.version_btn))
        self.update_btn = QPushButton(objectName="TitleUpdate")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self.whats_new_requested.emit)
        self.update_btn.hide()
        layout.addWidget(_shadow(self.update_btn))
        self.set_changelog_unseen(False)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self._avatars: dict[str, QPixmap] = {}
        self._avatar_wanted: set[str] = set()
        self._avatar_loader = AvatarLoader(self)
        self._avatar_loader.loaded.connect(self._on_avatar)
        self.account_btn = QPushButton(objectName="TitleAccount")
        self.account_btn.setCursor(Qt.PointingHandCursor)
        self.account_btn.clicked.connect(self.account_requested.emit)
        self.account_btn.hide()
        layout.addWidget(_shadow(self.account_btn))
        layout.addSpacing(4)

        self.minimize_btn = QPushButton("–")
        self.minimize_btn.setObjectName("TitleBarButton")
        self.minimize_btn.setToolTip("Minimise to tray")
        self.minimize_btn.setFixedSize(28, 28)
        self.minimize_btn.clicked.connect(self._minimize)
        layout.addWidget(_shadow(self.minimize_btn))

        self.maximize_btn = QPushButton()
        self.maximize_btn.setObjectName("TitleBarButton")
        self.maximize_btn.setFixedSize(28, 28)
        self.maximize_btn.clicked.connect(self.toggle_maximized)
        layout.addWidget(_shadow(self.maximize_btn))
        self.sync_maximized(False)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("TitleBarButton")
        self.close_btn.setProperty("kind", "close")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self._close)
        layout.addWidget(_shadow(self.close_btn))

    def set_changelog_unseen(self, unseen: bool) -> None:
        """After an update: a quiet hint until What's new has been opened."""
        self.version_btn.setText(f"v{__version__} · what's new" if unseen else f"v{__version__}")
        self.version_btn.setProperty("unseen", unseen)
        self.version_btn.style().polish(self.version_btn)
        self.version_btn.setToolTip("What's new in SC-Toolbox")

    def set_account(self, status: str, name: str = "", offline: bool = False, avatar_url: str | None = None) -> None:
        """Mirrors the online account: hidden when off, "Sign in" when signed out, else your
        avatar and name (with "offline" when the service can't be reached)."""
        self.account_btn.setVisible(status != "off")
        if status == "signed_in":
            self.account_btn.setText(f"{name}" + ("  · offline" if offline else ""))
            self.account_btn.setIcon(QIcon(self._avatar(name, avatar_url)))
            self.account_btn.setIconSize(QSize(AVATAR, AVATAR))
            self.account_btn.setToolTip("Signed in to SC-Toolbox online. Click for your account.")
        elif status == "signing_in":
            self.account_btn.setText("Signing in…")
            self.account_btn.setToolTip("Finish signing in in your browser. Click to see the sign-in in Settings.")
        else:
            self.account_btn.setIcon(QIcon())
            self.account_btn.setText("Sign in")
            self.account_btn.setToolTip("Sign in to SC-Toolbox online with Discord (opens your browser)")
        self.account_btn.setProperty("signedIn", status == "signed_in")
        self.account_btn.setProperty("offline", offline)
        self.account_btn.style().unpolish(self.account_btn)
        self.account_btn.style().polish(self.account_btn)

    def _avatar(self, name: str, url: str | None) -> QPixmap:
        """The round avatar: the downloaded picture once it's here, else the initial."""
        if url and url in self._avatars:
            return self._avatars[url]
        if url and url not in self._avatar_wanted:
            self._avatar_wanted.add(url)
            self._avatar_loader.fetch(url)
        self._pending_avatar = (name, url)
        return initial_pixmap(name, AVATAR * 2)

    def _on_avatar(self, url: str, data: bytes) -> None:
        pix = round_pixmap(data, AVATAR * 2)
        if pix is None:
            return
        self._avatars[url] = pix
        pending = getattr(self, "_pending_avatar", None)
        if pending and pending[1] == url and self.account_btn.property("signedIn"):
            self.account_btn.setIcon(QIcon(pix))

    def set_update(self, version: str | None) -> None:
        self.update_btn.setVisible(version is not None)
        if version:
            self.update_btn.setText(f"Update to v{version}")
            self.update_btn.setToolTip(f"SC-Toolbox {version} is available: see what's new and install it")

    def _minimize(self):
        window = self.window()
        if hasattr(window, "minimize_to_tray"):
            window.minimize_to_tray()
        else:
            window.showMinimized()

    def _close(self):
        self.window().close()

    def toggle_maximized(self):
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()

    def sync_maximized(self, maximized: bool) -> None:
        """Called by the window when its state changes."""
        self.maximize_btn.setText("❐" if maximized else "□")
        self.maximize_btn.setToolTip("Restore" if maximized else "Maximise")

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()

    # --- window dragging -----------------------------------------------
    # Wayland compositors don't let clients set their own absolute window
    # position (unlike X11), so manually tracking mouse delta and calling
    # move() silently does nothing there. startSystemMove() instead asks
    # the compositor itself to perform the drag, which works on both.
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
            event.accept()
