from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpacerItem, QWidget,
)

from app import __version__


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
    and version + drag-to-move + settings / minimize / close.
    """

    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        # Plain QWidget subclasses only paint their stylesheet background with this.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(4)

        layout.addWidget(_shadow(QLabel("SC-TOOLKIT")))
        layout.addSpacing(6)
        layout.addWidget(_shadow(QLabel(f"v{__version__}", objectName="TitleVersion")))
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("TitleBarButton")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(_shadow(self.settings_btn))

        self.minimize_btn = QPushButton("–")
        self.minimize_btn.setObjectName("TitleBarButton")
        self.minimize_btn.setFixedSize(28, 28)
        self.minimize_btn.clicked.connect(self._minimize)
        layout.addWidget(_shadow(self.minimize_btn))

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("TitleBarButton")
        self.close_btn.setProperty("kind", "close")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self._close)
        layout.addWidget(_shadow(self.close_btn))

    def _minimize(self):
        self.window().showMinimized()

    def _close(self):
        self.window().close()

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
