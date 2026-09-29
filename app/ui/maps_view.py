"""SC Maps: Mr Kraken's community one-page guides, viewed inside the
launcher. Images are loaded from their original (online) location the
first time and cached locally, so reopening a guide is instant and works
offline.

The zoomable image widget (`ZoomView`) is meant to be reused by the
overlay's compact Maps panel.
"""

from __future__ import annotations

import hashlib
import threading
import urllib.request

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app import config, maps, osutil
from app.theme import PALETTE

CACHE = config.CACHE_DIR / "maps"
TIMEOUT = 30
ZOOM_STEP = 1.25
ZOOM_MIN, ZOOM_MAX = 0.05, 8.0


def _cache_path(url: str):
    return CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img")


class _ImageLoader(QObject):
    loaded = Signal(str, bytes)   # url, image data
    failed = Signal(str, str)     # url, message

    def load(self, url: str) -> None:
        def work():
            path = _cache_path(url)
            try:
                if path.is_file():
                    data = path.read_bytes()
                else:
                    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
                    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                        data = resp.read()
                    CACHE.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(path)
                self.loaded.emit(url, data)
            except Exception as exc:  # network/disk errors are shown in the view
                self.failed.emit(url, str(exc))
        threading.Thread(target=work, daemon=True).start()


class ZoomView(QGraphicsView):
    """An image you can zoom (wheel, around the cursor) and pan (drag).
    Double-click toggles between fit-to-window and 100 %."""

    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self._item)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent;")
        self._fitted = True

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._item.setPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.fit()

    def has_image(self) -> bool:
        return not self._item.pixmap().isNull()

    def zoom(self) -> float:
        return self.transform().m11()

    def fit(self) -> None:
        if not self.has_image():
            return
        self.resetTransform()
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        self._fitted = True
        self.zoom_changed.emit(self.zoom())

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def set_zoom(self, factor: float) -> None:
        factor = max(ZOOM_MIN, min(ZOOM_MAX, factor))
        self.scale(factor / self.zoom(), factor / self.zoom())
        self._fitted = False
        self.zoom_changed.emit(self.zoom())

    def zoom_by(self, step: float) -> None:
        self.set_zoom(self.zoom() * step)

    def wheelEvent(self, event):
        if not self.has_image():
            return
        self.zoom_by(ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP)

    def mouseDoubleClickEvent(self, event):
        if self._fitted:
            self.actual_size()
        else:
            self.fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fitted:
            self.fit()


class MapsView(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loader = _ImageLoader(self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._wanted_url: str | None = None
        self._build_ui()
        self._fill_guides()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 20)
        outer.setSpacing(10)

        bar_frame = QFrame(objectName="ToolBar")
        bar = QHBoxLayout(bar_frame)
        bar.setContentsMargins(10, 8, 10, 8)
        bar.setSpacing(8)
        back = QPushButton("←  Back", objectName="ToolButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        bar.addWidget(back)
        bar.addSpacing(6)
        bar.addWidget(QLabel("GUIDE", objectName="ConfigLabel"))
        self.guide_combo = QComboBox(objectName="ConfigCombo")
        self.guide_combo.setMinimumWidth(300)
        self.guide_combo.setMaxVisibleItems(20)
        self.guide_combo.currentIndexChanged.connect(self._on_guide_changed)
        bar.addWidget(self.guide_combo)
        self.page_label = QLabel("PAGE", objectName="ConfigLabel")
        bar.addWidget(self.page_label)
        self.page_combo = QComboBox(objectName="ConfigCombo")
        self.page_combo.setMinimumWidth(240)
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)
        bar.addWidget(self.page_combo)
        bar.addStretch(1)
        for text, tip, slot in (
            ("−", "Zoom out", lambda: self.viewer.zoom_by(1 / ZOOM_STEP)),
            ("Fit", "Fit to window (double-click the image)", lambda: self.viewer.fit()),
            ("+", "Zoom in", lambda: self.viewer.zoom_by(ZOOM_STEP)),
            ("100%", "Actual size", lambda: self.viewer.actual_size()),
        ):
            btn = QPushButton(text, objectName="MiniButton")
            btn.setToolTip(tip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        self.zoom_label = QLabel("", objectName="InspectorHint")
        self.zoom_label.setMinimumWidth(44)
        bar.addWidget(self.zoom_label)
        self.post_btn = QPushButton("Original post ↗", objectName="MiniButton")
        self.post_btn.setToolTip("Open the guide's post on the RSI Community Hub")
        self.post_btn.setCursor(Qt.PointingHandCursor)
        self.post_btn.clicked.connect(self._open_post)
        bar.addWidget(self.post_btn)
        outer.addWidget(bar_frame)

        credit = QLabel(
            "Community guides by <a style='color:" + PALETTE["info"] + "' "
            f"href='{maps.GUIDES_INDEX_URL}'>Mr Kraken</a>: all credit to the author. "
            "Scroll to zoom, drag to move, double-click to switch between fit and 100%.",
            objectName="AboutLabel",
        )
        credit.setOpenExternalLinks(True)
        outer.addWidget(credit, alignment=Qt.AlignLeft)

        # Solid backdrop: many guides have transparent backgrounds.
        frame = QFrame(objectName="MapFrame")
        stack = QStackedLayout(frame)
        stack.setStackingMode(QStackedLayout.StackAll)
        self.viewer = ZoomView()
        self.viewer.zoom_changed.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))
        self.message = QLabel("", objectName="InspectorHint")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        stack.addWidget(self.viewer)
        stack.addWidget(self.message)
        stack.setCurrentWidget(self.message)   # message floats above the image
        outer.addWidget(frame, stretch=1)

    # -- lifecycle ------------------------------------------------------------
    def activate(self) -> None:
        if not self.viewer.has_image() and self._wanted_url is None:
            self._on_guide_changed(self.guide_combo.currentIndex())

    def deactivate(self) -> None:
        pass

    # -- guide / page selection -------------------------------------------------
    def _fill_guides(self) -> None:
        self.guide_combo.blockSignals(True)
        for title, pages, source in maps.GUIDES:
            self.guide_combo.addItem(title, (pages, source))
        self.guide_combo.blockSignals(False)

    def _on_guide_changed(self, index: int) -> None:
        pages, _source = self.guide_combo.itemData(index) or ([], "")
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for label, url in pages:
            self.page_combo.addItem(label, url)
        self.page_combo.blockSignals(False)
        multi = len(pages) > 1
        self.page_label.setVisible(multi)
        self.page_combo.setVisible(multi)
        self._on_page_changed(0)

    def _on_page_changed(self, index: int) -> None:
        url = self.page_combo.itemData(index)
        if not url:
            return
        self._wanted_url = url
        cached = _cache_path(url).is_file()
        self._show_message("" if cached else "Loading guide…")
        self._loader.load(url)

    def _open_post(self) -> None:
        _pages, source = self.guide_combo.currentData() or ([], "")
        osutil.open_url(source or maps.GUIDES_INDEX_URL)

    # -- image loading ------------------------------------------------------------
    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _on_loaded(self, url: str, data: bytes) -> None:
        if url != self._wanted_url:
            return  # a newer selection is already loading
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._show_message("Couldn't read this image.")
            return
        self._show_message("")
        self.viewer.set_pixmap(pixmap)

    def _on_failed(self, url: str, message: str) -> None:
        if url == self._wanted_url:
            self._show_message(f"Couldn't load the guide:\n{message}\n\nCheck your internet connection.")
