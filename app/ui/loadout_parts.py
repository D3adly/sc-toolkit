"""The loadout editor's painted pieces (the website's HudStat, PowerRing,
BusNode, PartCard and KindTag): drawn in paintEvent so they match the design
without stylesheet tricks. Nothing moves on hover or select: only border
colours change, and a preview never changes a layout (owner, 2026-10-24).

The numbers come from app.loadoutmodel; these widgets only draw them and say
what was clicked.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from app import loadoutmodel as model
from app.theme import NUM_FAMILY, PALETTE
from app.ui import kit

BG_DEEP = "#0b0d10"
NODE_BG = QColor(21, 24, 28, 230)
EDGE = QColor(218, 197, 164, 36)          # rgba(218,197,164,.14)
EDGE_HOVER = QColor(218, 197, 164, 115)
TRACK = QColor(255, 255, 255, 20)


def qc(name: str, alpha: float | None = None) -> QColor:
    """A palette colour (or any CSS colour) as a QColor, optionally with alpha 0–1."""
    value = str(PALETTE.get(name, name))
    c = _rgba(value) if value.startswith("rgba") else QColor(value)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def _rgba(text: str) -> QColor:
    r, g, b, a = (float(x) for x in text[text.index("(") + 1:text.index(")")].split(","))
    c = QColor(int(r), int(g), int(b))
    c.setAlphaF(a)
    return c


def ui_font(px: int, weight: QFont.Weight = QFont.Normal, spacing: float = 0.0, caps: bool = False) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    if caps:
        f.setCapitalization(QFont.AllUppercase)
    return f


def num_font(px: int, weight: QFont.Weight = QFont.Bold) -> QFont:
    """Rajdhani for display numbers, with tabular figures so they don't jiggle while previewing."""
    f = QFont(NUM_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setFeature(QFont.Tag("tnum"), 1)
    return f


def set_font(w: QWidget, font: QFont, css: str = "") -> None:
    """A widget's font, also as its own stylesheet: the app's "QWidget { font-size }" rule beats setFont."""
    w.setFont(font)
    rules = [f"font-size: {font.pixelSize()}px", f"font-weight: {font.weight().value}"]
    if font.family() == NUM_FAMILY:
        rules.append(f"font-family: '{NUM_FAMILY}'")
    if font.letterSpacing():
        rules.append(f"letter-spacing: {font.letterSpacing():g}px")
    w.setStyleSheet("; ".join(rules) + ";" + (" " + css if css else ""))


def add_css(w: QWidget, css: str) -> None:
    w.setStyleSheet(f"{w.styleSheet()} {css}")


def big_number(v: float) -> str:
    """A node's number: a million and up shortened (torpedo damage), so it keeps to one line."""
    if v >= 1e6:
        return f"{v / 1e6:,.2f}".rstrip("0").rstrip(".") + "M"
    if v < 10 and not float(v).is_integer():
        return f"{v:,.1f}"
    return f"{model.loadoutcalc.rnd(v, 0):,.0f}"


# -- kind tags (BUY / CRAFT / STOCK / FITTED / OBSOLETE / UNOBTAINABLE) ------------------------

TAG_LABEL = {"buy": "BUY", "craft": "CRAFT", "stock": "STOCK", "fitted": "FITTED", "obsolete": "OBSOLETE",
             "unobtainable": "UNOBTAINABLE", "shared": "SHARED"}
TAG_FONT = None


def _tag_font() -> QFont:
    global TAG_FONT
    if TAG_FONT is None:
        TAG_FONT = ui_font(10, QFont.ExtraBold, 1.0)
    return TAG_FONT


def tag_width(kind: str) -> int:
    return QFontMetrics(_tag_font()).horizontalAdvance(TAG_LABEL.get(kind, kind.upper())) + 12


def draw_tag(p: QPainter, x: float, y: float, kind: str) -> float:
    """Draws a tag with its top-left at (x, y); returns its width."""
    text = TAG_LABEL.get(kind, kind.upper())
    w, h = tag_width(kind), 18
    r = QRectF(x, y, w, h)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    fg = qc("text_primary")
    if kind == "buy":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(141, 180, 207, 46))
    elif kind == "craft":
        p.setPen(QPen(QColor(243, 237, 226, 77), 1))
        p.setBrush(QColor(243, 237, 226, 26))
    elif kind == "fitted":
        p.setPen(Qt.NoPen)
        p.setBrush(qc("text_primary"))
        fg = QColor(BG_DEEP)
    elif kind == "obsolete":
        p.setPen(QPen(QColor(224, 149, 79, 153), 1))
        p.setBrush(Qt.NoBrush)
        fg = qc("warning")
    elif kind == "unobtainable":
        pen = QPen(QColor(243, 237, 226, 102), 1, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        fg = qc("text_secondary")
    elif kind == "shared":
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.NoBrush)
        fg = qc("info")
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        fg = qc("text_secondary")
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
    p.setFont(_tag_font())
    p.setPen(fg)
    p.drawText(r, Qt.AlignCenter, text)
    p.restore()
    return w


# -- icons (the website's node icons, as SVG paths) --------------------------------------------

ICONS = {
    "gun": "M12 2v4M12 18v4M2 12h4M18 12h4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    "rack": "M5 19l4-4M14 4l6 6-9 9H5v-6z",
    "missile": "M5 19l4-4M14 4l6 6-9 9H5v-6z",
    "shield": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
    "power": "M13 2L4 14h7l-1 8 9-12h-7z",
    "cooler": "M12 2v20M4 6l16 12M20 6L4 18",
    "quantum": "M3 12h13M12 6l6 6-6 6M20 4v16",
    "radar": "M12 12l7-7M12 3a9 9 0 1 0 9 9M12 7a5 5 0 1 0 5 5",
    "other": "M4 4h16v16H4zM9 9h6v6H9z",
    "lock": "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
}
_icon_cache: dict[tuple[str, str, int], QPixmap] = {}


def icon_pixmap(kind: str, colour: str, size: int = 15, ratio: float = 1.0) -> QPixmap:
    key = (kind, colour, int(size * ratio))
    if key not in _icon_cache:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{colour}" '
               f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="{ICONS[kind]}"/></svg>')
        px = QPixmap(int(size * ratio), int(size * ratio))
        px.fill(Qt.transparent)
        painter = QPainter(px)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
        painter.end()
        px.setDevicePixelRatio(ratio)
        _icon_cache[key] = px
    return _icon_cache[key]


def elide_lines(fm: QFontMetrics, text: str, width: int, lines: int) -> list[str]:
    """Word-wraps text into at most `lines` lines, the last one elided."""
    words, out, cur = text.split(), [], ""
    for i, w in enumerate(words):
        trial = f"{cur} {w}".strip()
        if fm.horizontalAdvance(trial) <= width or not cur:
            cur = trial
            continue
        out.append(cur)
        cur = w
        if len(out) == lines - 1:
            cur = " ".join([w] + words[i + 1:])
            break
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
    if out:
        out[-1] = fm.elidedText(out[-1], Qt.ElideRight, width)
    return out


# -- one total over the banner -------------------------------------------------------------------

class HudStat(QWidget):
    """The value, how it compares with stock, a meter up to the best this ship can do (the stock
    mark on it) and a preview of the part being pointed at, on one fixed-height line."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.label = label
        self.value: float | None = None
        self.stock: float | None = None
        self.best = 0.0
        self.preview: float | None = None
        self.unit = ""
        self.digits = 0
        self.setMinimumWidth(170)
        self.setFixedHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value, stock, best, preview, unit: str, digits: int = 0) -> None:
        self.value, self.stock, self.best, self.preview, self.unit, self.digits = value, stock, best, preview, unit, digits
        self.setAccessibleName(f"{self.label}: {self._show(value)} {unit}")
        self.update()

    def _show(self, v) -> str:
        if v is None:
            return "—"
        return f"{model.loadoutcalc.rnd(v, self.digits):,.{self.digits}f}"

    def _close(self, a: float, b: float) -> bool:
        return abs(a - b) < 10 ** -self.digits / 2

    def _pct(self, v) -> float:
        return min(1.0, max(0.0, (v or 0) / self.best)) if self.best > 0 else 0.0

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        p.setPen(QPen(QColor(218, 197, 164, 46), 1))
        p.drawLine(0, 0, 0, self.height())
        x0, inner = 16, w - 32
        p.setFont(ui_font(11, QFont.Bold, 1.6, True))
        p.setPen(qc("text_muted"))
        p.drawText(QRectF(x0, 6, inner, 16), Qt.AlignLeft | Qt.AlignVCenter, self.label)
        p.setFont(num_font(30))
        p.setPen(qc("text_primary"))
        value_text = self._show(self.value)
        p.drawText(QRectF(x0, 20, inner, 34), Qt.AlignLeft | Qt.AlignVCenter, value_text)
        previewing = self.preview is not None and self.value is not None and not self._close(self.preview, self.value)
        if previewing:
            up = self.preview > self.value
            p.setFont(num_font(18))
            p.setPen(qc("success" if up else "warning"))
            p.drawText(QRectF(x0, 20, inner, 34), Qt.AlignRight | Qt.AlignVCenter,
                       f"{'▲' if up else '▼'} {self._show(self.preview)}")
        elif self.value is not None and self.stock is not None:
            d = self.value - self.stock
            if self._close(d, 0):
                text, colour = "stock", "text_muted"
            else:
                text = f"{'▲' if d > 0 else '▼'} {self._show(abs(d))} vs stock"
                colour = "success" if d > 0 else "warning"
            p.setFont(ui_font(12, QFont.Bold))
            p.setPen(qc(colour))
            p.drawText(QRectF(x0, 20, inner, 34), Qt.AlignRight | Qt.AlignVCenter, text)
        p.setFont(ui_font(12))
        p.setPen(qc("text_secondary"))
        p.drawText(QRectF(x0, 54, inner, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(ui_font(12)).elidedText(self.unit, Qt.ElideRight, inner))
        # The meter: filled to the value, a ghost to the preview, the stock mark.
        y = 78
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(QRectF(x0, y, inner, 4), 2, 2)
        fill = QLinearGradient(x0, 0, x0 + inner, 0)
        fill.setColorAt(0, qc("info_dim"))
        fill.setColorAt(1, qc("info"))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(x0, y, inner * self._pct(self.value), 4), 2, 2)
        if previewing:
            ghost = qc("success" if self.preview > self.value else "warning", 0.55)
            a, b = sorted((self._pct(self.value), self._pct(self.preview)))
            p.setBrush(ghost)
            p.drawRect(QRectF(x0 + inner * a, y, inner * (b - a), 4))
        if self.stock is not None:
            p.setBrush(qc("text_secondary"))
            p.drawRect(QRectF(x0 + inner * self._pct(self.stock) - 1, y - 4, 2, 12))
        p.end()


# -- the power ring --------------------------------------------------------------------------------

class PowerRing(QWidget):
    """The power plants' segments as a ring, filled by what each part draws (the selected part's
    share lit), and the segments a full load needs beyond them on a thin outer ring."""

    SIZE = 112
    R = 40
    GAP = 2.5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gen = self.pmin = self.pmax = 0.0
        self.draws: list[tuple[str, float]] = []
        self.base = 0.0
        self.selected = ""
        self.setFixedSize(132, 160)

    def set(self, gen: float, pmin: float, pmax: float, draws, base: float, selected: str) -> None:
        self.gen, self.pmin, self.pmax, self.draws, self.base, self.selected = gen, pmin, pmax, draws, base, selected
        made = round(gen)
        self.setAccessibleName(f"Power plants make {made} segments; parts need {round(pmin)} to {round(pmax)}")
        self.update()

    def ring_centre_y(self) -> int:
        return self.SIZE // 2

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.SIZE / 2
        made = round(self.gen)
        over = max(0, round(self.pmax) - made)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0f1215"))
        p.drawEllipse(QPointF(cx, cy), 47, 47)
        owners: list[str] = []
        for node_id, draw in self.draws:
            owners += [node_id] * int(draw)
        owners += [""] * round(self.base)
        n = max(1, made)
        step = 2 * math.pi / n

        def arc(i: int, r: float, width: float, colour: QColor) -> None:
            cut = min(self.GAP / 2 / r, step / 4)
            a0 = -math.pi / 2 + i * step + cut
            a1 = -math.pi / 2 + (i + 1) * step - cut
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            path = QPainterPath()
            path.arcMoveTo(rect, -math.degrees(a0))
            path.arcTo(rect, -math.degrees(a0), -math.degrees(a1 - a0))
            pen = QPen(colour, width)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        for i in range(made):
            owner = owners[i] if i < len(owners) else None
            colour = (QColor(255, 255, 255, 26) if owner is None
                      else qc("text_primary") if owner and owner == self.selected else qc("info"))
            arc(i, self.R, 12, colour)
        for j in range(min(over, made)):
            arc(j, self.R + 12, 3, qc("warning"))
        p.setPen(qc("text_primary"))
        p.setFont(num_font(26))
        p.drawText(QRectF(cx - 40, cy - 22, 80, 28), Qt.AlignCenter, str(made))
        p.setFont(ui_font(8, QFont.Bold, 0.8))
        p.setPen(qc("text_secondary"))
        p.drawText(QRectF(cx - 40, cy + 6, 80, 12), Qt.AlignCenter, "SEGMENTS")
        p.setFont(ui_font(13))
        y = self.SIZE + 8
        needs = f"{round(self.pmin)}–{round(self.pmax)}"
        fm, fb = QFontMetrics(ui_font(13)), QFontMetrics(num_font(17))
        total = fm.horizontalAdvance("needs ") + fb.horizontalAdvance(needs)
        x = cx - total / 2
        p.drawText(QPointF(x, y + 14), "needs ")
        p.setFont(num_font(17))
        p.setPen(qc("text_primary"))
        p.drawText(QPointF(x + fm.horizontalAdvance("needs "), y + 14), needs)
        p.setFont(ui_font(12, QFont.DemiBold))
        p.setPen(qc("warning" if over else "text_muted"))
        p.drawText(QRectF(0, y + 20, self.width(), 18), Qt.AlignCenter,
                   f"{over} over at full load" if over else "runs everything")
        p.end()


# -- one part on the bus ----------------------------------------------------------------------------

class BusNodeWidget(QWidget):
    """What's fitted, its number and the segments it draws (pips). A group has a button per slot
    to change just that one; the card itself picks them all."""

    picked = Signal(str, object)        # node id, slot path or None

    PAD = 12

    def __init__(self, node: model.BusNode, tag: str, parent=None):
        super().__init__(parent)
        self.node, self.tag = node, tag
        self.selected = False
        self.side: str | None = None
        self.up = False
        self._hover = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        count = len(node.paths)
        self.setAccessibleName(f"{node.label}: {node.name}{f', {count} of them' if count > 1 else ''}, "
                               f"{big_number(node.value)} "
                               f"{'missile damage' if node.kind == 'rack' else model.KIND_STAT[node.kind][0]}")
        self.slot_buttons: list[QPushButton] = []
        if count > 1:
            for path, name in model.slot_names(node.paths):
                b = QPushButton(name, self, objectName="BusSlot")
                b.setCursor(Qt.PointingHandCursor)
                b.setCheckable(True)
                b.setAccessibleName(f"{node.label}: {name} only")
                b.clicked.connect(lambda _c=False, path=path: self.picked.emit(self.node.id, path))
                b.setProperty("path", path)
                self.slot_buttons.append(b)

    def set_state(self, selected: bool, side: str | None) -> None:
        self.selected, self.side = selected, side
        for b in self.slot_buttons:
            b.setChecked(selected and side == b.property("path"))
        self.update()

    # layout --------------------------------------------------------------------------------------
    def _lines(self, width: int) -> tuple[list[str], list[str]]:
        n = self.node
        count = len(n.paths)
        label = f"{n.label} · {n.size}{f' ×{count}' if count > 1 else ''}"
        inner = width - 2 * self.PAD
        return (elide_lines(QFontMetrics(ui_font(11, QFont.DemiBold)), label, inner, 2),
                elide_lines(QFontMetrics(ui_font(13, QFont.Bold)), n.name, inner, 3))

    def height_for(self, width: int) -> int:
        label, name = self._lines(width)
        h = self.PAD + 18 + 6 + len(label) * 14 + 4 + max(2, len(name)) * 16 + 4
        if self.node.kind == "rack":
            h += 16
        h += 30                                         # the number
        if self.node.draw:
            rows = math.ceil(min(self.node.draw, 24) / 12)
            h += rows * 7 + 4
        if self.slot_buttons:
            rows = 1 if len(self.slot_buttons) <= 2 else math.ceil(len(self.slot_buttons) / 2)
            h += 6 + rows * 28 + (rows - 1) * 4
        return h + self.PAD

    def resizeEvent(self, e):
        if self.slot_buttons:
            inner = self.width() - 2 * self.PAD
            cols = 2 if len(self.slot_buttons) > 2 else len(self.slot_buttons)
            rows = math.ceil(len(self.slot_buttons) / cols)
            bw = (inner - (cols - 1) * 4) / cols
            top = self.height() - self.PAD - rows * 28 - (rows - 1) * 4
            for i, b in enumerate(self.slot_buttons):
                r, c = divmod(i, cols)
                b.setGeometry(int(self.PAD + c * (bw + 4)), int(top + r * 32), int(bw), 28)
        super().resizeEvent(e)

    def stub_x(self) -> int:
        return self.width() // 2

    # painting ------------------------------------------------------------------------------------
    def paintEvent(self, _e):
        n = self.node
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.selected:
            p.setBrush(qc("info_soft"))
            p.setPen(QPen(qc("info"), 1))
        else:
            p.setBrush(NODE_BG)
            p.setPen(QPen(EDGE_HOVER if self._hover or self.hasFocus() else EDGE, 1))
        p.drawRoundedRect(r, 12, 12)
        if self.hasFocus():
            p.setPen(QPen(qc("info"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-0, -0, 0, 0), 12, 12)
        x, y, inner = self.PAD, self.PAD, self.width() - 2 * self.PAD
        p.drawPixmap(x, y + 1, icon_pixmap(n.kind, PALETTE["info"], 15, self.devicePixelRatioF()))
        draw_tag(p, x + inner - tag_width(self.tag), y, self.tag)
        y += 24
        label, name = self._lines(self.width())
        p.setFont(ui_font(11, QFont.DemiBold))
        p.setPen(qc("text_secondary"))
        for line in label:
            p.drawText(QRectF(x, y, inner, 14), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 14
        y += 4
        p.setFont(ui_font(13, QFont.Bold))
        p.setPen(qc("text_primary"))
        for line in name:
            p.drawText(QRectF(x, y, inner, 16), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 16
        y += (max(2, len(name)) - len(name)) * 16 + 4
        if n.kind == "rack":
            sub = ", ".join(f"{c} × {m}" for m, c in n.missiles) or "No missiles"
            p.setFont(ui_font(11))
            p.setPen(qc("text_secondary"))
            p.drawText(QRectF(x, y - 2, inner, 14), Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetrics(ui_font(11)).elidedText(sub, Qt.ElideRight, inner))
            y += 16
        big = "—" if n.obsolete else big_number(n.value)
        p.setFont(num_font(24))
        p.setPen(qc("text_primary"))
        fm = QFontMetrics(num_font(24))
        p.drawText(QRectF(x, y, inner, 30), Qt.AlignLeft | Qt.AlignVCenter, big)
        count = len(n.paths)
        p.setFont(ui_font(11))
        p.setPen(qc("text_secondary"))
        p.drawText(QRectF(x + fm.horizontalAdvance(big) + 4, y + 4, inner, 26), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{n.unit}{f' ×{count}' if count > 1 else ''}")
        y += 30
        if n.draw:
            p.setPen(Qt.NoPen)
            p.setBrush(qc("info"))
            for i in range(min(int(n.draw), 24)):
                row, col = divmod(i, 12)
                p.drawRoundedRect(QRectF(x + col * 9, y + 2 + row * 7, 6, 4), 1, 1)
        p.end()

    # input ------------------------------------------------------------------------------------------
    def event(self, e):
        if e.type() in (e.Type.HoverEnter, e.Type.HoverLeave):
            self._hover = e.type() == e.Type.HoverEnter
            self.update()
        return super().event(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.picked.emit(self.node.id, None)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.picked.emit(self.node.id, None)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)


class BusView(QWidget):
    """The power bus: the ring on the left, centred on the bus line; weapons above the line while
    they fit on one row, else stacked in lanes (Guns, Missiles) whose rails join a trunk down the
    left; systems below, wrapping into more rows the same way."""

    picked = Signal(str, object)

    CARD = 132
    GAP = 10
    RAIL = 30                # from a rail (or the bus line) to the cards it feeds
    RING_COL = 140

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ring = PowerRing(self)
        self.nodes: list[BusNodeWidget] = []
        self._lines: list[tuple[QPointF, QPointF, bool]] = []     # (from, to, lit)
        self._dot = QPointF()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_nodes(self, nodes: list[model.BusNode], tags: dict[str, str]) -> None:
        for w in self.nodes:
            kit.drop(w)
        self.nodes = []
        for n in nodes:
            w = BusNodeWidget(n, tags.get(n.id, "stock"), self)
            w.picked.connect(self.picked)
            w.show()
            self.nodes.append(w)
        self._relayout()

    def set_selected(self, node_id: str | None, side: str | None) -> None:
        for w in self.nodes:
            w.set_state(w.node.id == node_id, side if w.node.id == node_id else None)
        self.update()

    def resizeEvent(self, e):
        self._relayout()
        super().resizeEvent(e)

    def _relayout(self) -> None:
        width = max(self.width(), 600)
        left = self.RING_COL
        avail = width - left
        cols = max(1, (avail + self.GAP) // (self.CARD + self.GAP))
        card_w = (avail - (cols - 1) * self.GAP) / cols
        weapons = [w for w in self.nodes if w.node.kind in model.WEAPON_KINDS]
        systems = [w for w in self.nodes if w.node.kind not in model.WEAPON_KINDS]
        stacked = len(weapons) > cols
        lines: list[tuple[QPointF, QPointF, bool]] = []
        rails: list[float] = []
        y = 0.0

        def place_row(row: list[BusNodeWidget], top: float) -> float:
            h = max(w.height_for(int(card_w)) for w in row)
            for i, w in enumerate(row):
                w.setGeometry(int(left + i * (card_w + self.GAP)), int(top), int(card_w), int(h))
            return h

        def rows_of(ws: list[BusNodeWidget]) -> list[list[BusNodeWidget]]:
            return [ws[i:i + cols] for i in range(0, len(ws), cols)]

        trunk_x = left - self.GAP
        if weapons and not stacked:
            h = place_row(weapons, 0)
            for w in weapons:
                w.up = True
            y = h + self.RAIL + 4
            bus_y = y
            for w in weapons:
                cx = w.x() + w.width() / 2
                lines.append((QPointF(cx, w.y() + w.height()), QPointF(cx, bus_y), w.selected))
        else:
            lanes = [[w for w in weapons if w.node.kind == "gun"], [w for w in weapons if w.node.kind != "gun"]]
            for lane in lanes:
                for row in rows_of(lane):
                    rail_y = y
                    top = rail_y + self.RAIL
                    h = place_row(row, top)
                    rails.append(rail_y)
                    last = row[-1]
                    lines.append((QPointF(trunk_x, rail_y), QPointF(last.x() + last.width(), rail_y), False))
                    for w in row:
                        cx = w.x() + w.width() / 2
                        lines.append((QPointF(cx, rail_y), QPointF(cx, w.y()), w.selected))
                    y = top + h + 18
            bus_y = y + (4 if weapons else self.ring.ring_centre_y())
        # The ring sits centred on the bus line, in the left column.
        ring_top = bus_y - self.ring.ring_centre_y()
        if ring_top < 0:                         # no weapons: everything moves down to fit the ring
            shift = -ring_top
            bus_y += shift
            ring_top = 0
        self.ring.move(int((left - self.ring.width()) / 2 - 6), int(ring_top))
        self._dot = QPointF(left - 6, bus_y)
        sys_rows = rows_of(systems)
        y = bus_y + self.RAIL
        right = left
        for i, row in enumerate(sys_rows):
            if i:
                rail_y = y
                y += self.RAIL
                rails.append(rail_y)
                lines.append((QPointF(trunk_x, rail_y),
                              QPointF(left + len(row) * (card_w + self.GAP) - self.GAP, rail_y), False))
            h = place_row(row, y)
            for w in row:
                w.up = False
                cx = w.x() + w.width() / 2
                lines.append((QPointF(cx, (rails[-1] if i else bus_y)), QPointF(cx, w.y()), w.selected))
            right = max(right, row[-1].x() + row[-1].width())
            y += h + 18
        for w in weapons:
            right = max(right, w.x() + w.width())
        lines.insert(0, (QPointF(left - 6, bus_y), QPointF(right, bus_y), False))
        if rails:
            top, bottom = min(rails + [bus_y]), max(rails + [bus_y])
            lines.append((QPointF(trunk_x, top), QPointF(trunk_x, bottom), False))
        self._lines = lines
        total = max(y, ring_top + self.ring.height())
        self.setFixedHeight(int(total))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for a, b, lit in self._lines:
            p.setPen(QPen(qc("text_primary") if lit else qc("info_dim"), 2))
            p.drawLine(a, b)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("info"))
        p.drawEllipse(self._dot, 5, 5)
        p.end()


# -- a part in the swap tray -------------------------------------------------------------------------

class PartCardWidget(QWidget):
    """Point at it to preview it on the totals, click to hold the preview. Buy or Craft puts it on,
    got that way; the stock part's Stock needs neither. On the fitted part the pressed button is how
    it's got now; the other switches it."""

    hovered = Signal(str)
    left = Signal(str)
    held = Signal(str)
    fit = Signal(str, str)              # item, source

    WIDTH = 212
    PAD = 14

    def __init__(self, card: model.Card, parent=None):
        super().__init__(parent)
        self.card = card
        self.previewing = False
        self._hover = False
        self.setFixedWidth(self.WIDTH)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f"{card.name}, {card.value} {card.unit}, {card.src}"
                               + (", fitted" if card.fitted else ". Press to preview it, then Buy or Craft."))
        self.buy = QPushButton("Stock" if card.stock else "Buy", self, objectName="PartGet")
        self.craft = QPushButton("Craft", self, objectName="PartGet")
        self.buy.setEnabled(card.stock or card.can_buy)
        self.craft.setEnabled(card.can_craft)
        self.buy.setProperty("pressed", card.fitted_as is not None and card.fitted_as != "craft")
        self.craft.setProperty("pressed", card.fitted_as == "craft")
        for b in (self.buy, self.craft):
            b.setCursor(Qt.PointingHandCursor)
        self.buy.setAccessibleName(f"{'Stock' if card.stock else 'Buy'} {card.name}")
        self.craft.setAccessibleName(f"Craft {card.name}")
        self.buy.clicked.connect(lambda: self.fit.emit(card.item, "stock" if card.stock else "buy"))
        self.craft.clicked.connect(lambda: self.fit.emit(card.item, "craft"))
        self.setFixedHeight(self._height())

    def _texts(self):
        inner = self.WIDTH - 2 * self.PAD
        name = elide_lines(QFontMetrics(ui_font(15, QFont.Bold)), self.card.name, inner, 2)
        sub = elide_lines(QFontMetrics(ui_font(12)), self.card.sub, inner, 3)
        src = elide_lines(QFontMetrics(ui_font(12)), self.card.src, inner, 2)
        return name, sub, src

    def _height(self) -> int:
        return 336

    def set_previewing(self, on: bool) -> None:
        self.previewing = on
        self.update()

    def resizeEvent(self, e):
        bw = (self.WIDTH - 2 * self.PAD - 6) / 2
        y = self.height() - self.PAD - 34
        self.buy.setGeometry(self.PAD, int(y), int(bw), 34)
        self.craft.setGeometry(int(self.PAD + bw + 6), int(y), int(bw), 34)
        super().resizeEvent(e)

    def paintEvent(self, _e):
        c = self.card
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QLinearGradient(0, 0, self.width() * 0.3, self.height())
        bg.setColorAt(0, QColor(28, 32, 37, 242))
        bg.setColorAt(1, QColor(15, 18, 21, 242))
        if c.fitted:
            edge = qc("text_primary")
        elif self.previewing or self._hover or self.hasFocus():
            edge = qc("info")
        else:
            edge = EDGE
        p.setBrush(bg)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(r, 14, 14)
        x, y, inner = self.PAD, self.PAD, self.WIDTH - 2 * self.PAD
        draw_tag(p, x, y, "fitted" if c.fitted else c.tag)
        if c.delta:
            p.setFont(ui_font(12, QFont.Bold))
            p.setPen(qc({"better": "success", "worse": "warning"}.get(c.tone, "text_muted")))
            p.drawText(QRectF(x, y, inner, 18), Qt.AlignRight | Qt.AlignVCenter, c.delta)
        y += 26
        name, sub, src = self._texts()
        p.setFont(ui_font(15, QFont.Bold))
        p.setPen(qc("text_primary"))
        for line in name:
            p.drawText(QRectF(x, y, inner, 20), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 20
        y += 6 + (2 - len(name)) * 20
        p.setFont(ui_font(12))
        p.setPen(qc("text_secondary"))
        for line in sub:
            p.drawText(QRectF(x, y, inner, 16), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 16
        y += 8 + (3 - len(sub)) * 16
        p.setFont(num_font(32))
        p.setPen(qc("text_primary"))
        p.drawText(QRectF(x, y, inner, 34), Qt.AlignLeft | Qt.AlignVCenter, c.value)
        vw = QFontMetrics(num_font(32)).horizontalAdvance(c.value)
        p.setFont(ui_font(12))
        p.setPen(qc("text_secondary"))
        p.drawText(QRectF(x + vw + 4, y + 6, inner, 30), Qt.AlignLeft | Qt.AlignVCenter, c.unit)
        y += 42
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(QRectF(x, y, inner, 4), 2, 2)
        p.setBrush(qc("info"))
        p.drawRoundedRect(QRectF(x, y, inner * c.bar, 4), 2, 2)
        y += 14
        p.setFont(ui_font(12))
        p.setPen(qc("text_secondary"))
        for line in src:
            p.drawText(QRectF(x, y, inner, 16), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 16
        p.end()

    def event(self, e):
        t = e.type()
        if t == e.Type.HoverEnter:
            self._hover = True
            self.hovered.emit(self.card.item)
            self.update()
        elif t == e.Type.HoverLeave:
            self._hover = False
            self.left.emit(self.card.item)
            self.update()
        return super().event(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.held.emit(self.card.item)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.held.emit(self.card.item)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.hovered.emit(self.card.item)
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.left.emit(self.card.item)
        self.update()
        super().focusOutEvent(e)


# -- a toast with Undo ---------------------------------------------------------------------------------

class Toast(QWidget):
    """A short message at the bottom of its parent, with an optional Undo. Hides after a while."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 10, 10)
        row.setSpacing(12)
        self.text = QLabel(objectName="ToastText")
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(620)
        row.addWidget(self.text, 1)
        self.undo = QPushButton("Undo", objectName="ToastUndo")
        self.undo.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.undo)
        self._undo_slot = None
        self.undo.clicked.connect(self._on_undo)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        self.hide()

    def show_message(self, text: str, undo=None, ms: int = 6000) -> None:
        self.text.setText(text)
        self._undo_slot = undo
        self.undo.setVisible(undo is not None)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start(ms + (3000 if undo else 0))

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 24)

    def _on_undo(self) -> None:
        slot, self._undo_slot = self._undo_slot, None
        self.hide()
        if slot is not None:
            slot()

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(min(hint.width(), 760), hint.height())
