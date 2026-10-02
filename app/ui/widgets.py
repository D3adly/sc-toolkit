"""Small widgets shared by several views."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
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
