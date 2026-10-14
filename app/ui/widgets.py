"""Small widgets shared by several views."""

import threading
import urllib.request

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractButton, QLabel

from app.theme import PALETTE


class Switch(QAbstractButton):
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
        track = QColor(PALETTE["info"] if on else "#3a3f45")
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


class Elided(QLabel):
    """One line that ends in "…" when it doesn't fit (full text in the tooltip)."""

    def __init__(self, text: str, name: str, tip: str = ""):
        super().__init__(text, objectName=name)
        self.setToolTip(tip or text)
        self.setMinimumWidth(40)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(40)
        return hint

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        p.drawText(self.rect(), int(self.alignment() | Qt.AlignVCenter), text)


class AvatarLoader(QObject):
    """Downloads an avatar picture off the UI thread."""
    loaded = Signal(str, bytes)  # url, image data

    def fetch(self, url: str) -> None:
        from app import config

        def work():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.loaded.emit(url, resp.read(512 * 1024))
            except OSError:
                pass  # no avatar then; the initial stays
        threading.Thread(target=work, daemon=True).start()


def round_pixmap(data: bytes, size: int) -> QPixmap | None:
    source = QPixmap()
    if not source.loadFromData(data):
        return None
    source = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return out


def initial_pixmap(name: str, size: int) -> QPixmap:
    """A steel circle with the name's first letter (until the avatar loads)."""
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(PALETTE["info_dim"]))
    p.drawEllipse(QRectF(0, 0, size, size))
    font = QFont(p.font())
    font.setPixelSize(int(size * 0.55))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor(PALETTE["text_primary"]))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, (name[:1] or "?").upper())
    p.end()
    return out


def person_pixmap(size: int, colour: str | None = None) -> QPixmap:
    """A simple head-and-shoulders glyph (the Sign in button)."""
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colour or PALETTE["text_secondary"]))
    p.drawEllipse(QRectF(size * 0.32, size * 0.08, size * 0.36, size * 0.36))
    body = QPainterPath()
    body.addRoundedRect(QRectF(size * 0.14, size * 0.52, size * 0.72, size * 0.44), size * 0.3, size * 0.3)
    p.drawPath(body)
    p.end()
    return out


def dimmed(pixmap: QPixmap, opacity: float = 0.4) -> QPixmap:
    out = QPixmap(pixmap.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setOpacity(opacity)
    p.drawPixmap(0, 0, pixmap)
    p.end()
    return out
