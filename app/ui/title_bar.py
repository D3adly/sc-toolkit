from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSpacerItem, QSizePolicy


class TitleBar(QWidget):
    """Frameless-window title bar: app label + drag-to-move + settings /
    minimize / close.
    """

    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(4)

        title = QLabel("SC-TOOLKIT")
        layout.addWidget(title)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("TitleBarButton")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

        self.minimize_btn = QPushButton("–")
        self.minimize_btn.setObjectName("TitleBarButton")
        self.minimize_btn.setFixedSize(28, 28)
        self.minimize_btn.clicked.connect(self._minimize)
        layout.addWidget(self.minimize_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("TitleBarButton")
        self.close_btn.setProperty("kind", "close")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self._close)
        layout.addWidget(self.close_btn)

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
