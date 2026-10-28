"""The loadout editor's other views (designs: Loadouts canvas, "V-Compare",
"V-Craft", "V-Shopping", "V-LauncherRemove"), ports of the website's:

- CompareView: everything that fits the slots the tray had open, searchable,
  sorted by any of its numbers, filtered by kind; pin up to three to compare
  row by row; Buy or Craft puts one on.
- CraftDialog: one quality step per recipe slot, with how often finds reach
  it, and what the picks make of the part's numbers.
- ShoppingView: the buy run as stops (fewest stops or lowest price, a shop of
  your own per part) and the craft list (materials, quality odds, ore SCU).
  Saving the list freezes the buy run and turns on the ticks; both sync with
  the website.
- RemoveShipDialog: removing a ship that has loadouts asks first.

No price freshness tags or "N days ago" anywhere (owner, 2026-10-25).
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from app import loadoutcalc, loadoutmodel as model, uexparts
from app.loadoutcalc import STAT_PROPS, best_qualities, modifier_value, part_stats
from app.loadoutmodel import KIND_LABEL, KIND_STAT, money, show_stat
from app.theme import PALETTE
from app.ui import kit
from app.ui.loadout_parts import EDGE, add_css, draw_tag, elide_lines, num_font, qc, set_font, ui_font


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    lab = QLabel(text, objectName=name)
    lab.setWordWrap(wrap)
    return lab


def _caps(text: str, colour: str = "text_muted") -> QLabel:
    lab = QLabel(text.upper())
    set_font(lab, ui_font(11, QFont.Bold, 1.6))
    add_css(lab, f"color: {PALETTE[colour]};")
    return lab


def _num(text: str, px: int) -> QLabel:
    lab = QLabel(text)
    set_font(lab, num_font(px))
    return lab


def _num_unit(text: str, px: int, unit: str) -> QLabel:
    """A big number with its unit after it on the same line."""
    lab = _num(f"{text} <span style=\"font-family:'Inter'; font-size:13px; font-weight:500; "
               f"color:{PALETTE['text_muted']}\">{unit}</span>" if unit else text, px)
    return lab


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _ago(iso: str) -> str:
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "a while ago"
    mins = int((datetime.now(timezone.utc) - then).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} days ago"


def _pct_text(f: float) -> str:
    p = round((f - 1) * 1000) / 10
    return f"{'+' if p > 0 else '−' if p < 0 else '±'}{abs(p):.1f}%"


class _Chip(QPushButton):
    def __init__(self, text: str, on: bool = False, parent=None):
        super().__init__(text, parent, objectName="LoChipBtn")
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.PointingHandCursor)


class _Panel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent, objectName="LoPanel")


# == compare =============================================================================================

class _Metric:
    def __init__(self, key: str, label: str, unit: str, of, lower: bool = False):
        self.key, self.label, self.unit, self.of, self.lower = key, label, unit, of, lower


class _CompareCard(QWidget):
    """A part in the compare grid: click to select it (the ship's change shows in the dock), + to
    pin it; the selected one gets Buy / Craft."""

    selected = Signal(str)
    pinned = Signal(str)
    fit = Signal(str, str)

    HEIGHT = 238

    def __init__(self, c: dict, sel: bool, pin: bool, gets: list[dict], parent=None):
        super().__init__(parent)
        self.c, self.sel = c, sel
        self.setMinimumHeight(self.HEIGHT + (46 if sel else 0))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(c["aria"])
        self._hover = False
        self.setAttribute(Qt.WA_Hover)
        self.pin = QPushButton("✓" if pin else "+", self, objectName="LoPin")
        self.pin.setCheckable(True)
        self.pin.setChecked(pin)
        self.pin.setCursor(Qt.PointingHandCursor)
        self.pin.setAccessibleName(f"{'Unpin' if pin else 'Pin'} {c['name']} to compare")
        self.pin.clicked.connect(lambda: self.pinned.emit(c["item"]))
        self.gets: list[QPushButton] = []
        if sel:
            for g in gets:
                b = QPushButton(g["label"], self, objectName="PartGet")
                b.setEnabled(g["can"])
                b.setProperty("pressed", g["on"])
                b.setCursor(Qt.PointingHandCursor)
                b.setAccessibleName(f"{g['label']} {c['name']}")
                b.clicked.connect(lambda _c=False, s=g["source"]: self.fit.emit(c["item"], s))
                self.gets.append(b)

    def resizeEvent(self, e):
        self.pin.setGeometry(self.width() - 40, 10, 30, 30)
        if self.gets:
            bw = (self.width() - 28 - 6) / 2
            for i, b in enumerate(self.gets):
                b.setGeometry(int(14 + i * (bw + 6)), self.height() - 14 - 34, int(bw), 34)
        super().resizeEvent(e)

    def paintEvent(self, _e):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QLinearGradient(0, 0, self.width() * 0.3, self.height())
        bg.setColorAt(0, QColor(28, 32, 37, 242))
        bg.setColorAt(1, QColor(15, 18, 21, 242))
        p.setBrush(bg)
        edge = qc("info") if self.sel or self._hover or self.hasFocus() else (
            qc("text_primary") if c["fitted"] else EDGE)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(r, 14, 14)
        x, y, inner = 14, 14, self.width() - 28
        tx = x
        tx += draw_tag(p, tx, y, c["tag"]) + 6
        if c["fitted"]:
            tx += draw_tag(p, tx, y, "fitted") + 6
        if c["stock"] and c["tag"] != "stock":
            draw_tag(p, tx, y, "stock")
        y += 28
        p.setFont(ui_font(16, QFont.ExtraBold))
        p.setPen(qc("text_primary"))
        for line in elide_lines(QFontMetrics(ui_font(16, QFont.ExtraBold)), c["name"], inner - 30, 2):
            p.drawText(QRectF(x, y, inner, 20), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 20
        y += 4
        p.setFont(ui_font(12))
        p.setPen(qc("text_muted"))
        sub = elide_lines(QFontMetrics(ui_font(12)), c["sub"], inner, 2)
        for line in sub:
            p.drawText(QRectF(x, y, inner, 16), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 16
        y = 14 + 28 + 44 + 4 + 36
        p.setFont(num_font(32))
        p.setPen(qc("text_primary"))
        p.drawText(QRectF(x, y, inner, 34), Qt.AlignLeft | Qt.AlignVCenter, c["value"])
        vw = QFontMetrics(num_font(32)).horizontalAdvance(c["value"])
        p.setFont(ui_font(12))
        p.setPen(qc("text_muted"))
        p.drawText(QRectF(x + vw + 4, y + 6, inner, 30), Qt.AlignLeft | Qt.AlignVCenter, c["unit"])
        if c["delta"]:
            p.setFont(ui_font(12, QFont.Bold))
            p.setPen(qc({"better": "success", "worse": "warning"}.get(c["tone"], "text_muted")))
            p.drawText(QRectF(x, y, inner, 34), Qt.AlignRight | Qt.AlignVCenter, c["delta"])
        y += 42
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(x, y, inner, 4), 2, 2)
        p.setBrush(qc("info"))
        p.drawRoundedRect(QRectF(x, y, inner * c["bar"], 4), 2, 2)
        y += 14
        p.setFont(ui_font(12))
        p.setPen(qc("text_secondary"))
        p.drawText(QRectF(x, y, inner, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(ui_font(12)).elidedText(c["side"], Qt.ElideRight, int(inner * 0.6)))
        p.setFont(num_font(15))
        p.setPen(qc("text_primary"))
        p.drawText(QRectF(x, y, inner, 18), Qt.AlignRight | Qt.AlignVCenter, c["price"])
        p.end()

    def event(self, e):
        if e.type() in (e.Type.HoverEnter, e.Type.HoverLeave):
            self._hover = e.type() == e.Type.HoverEnter
            self.update()
        return super().event(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.selected.emit(self.c["item"])
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.selected.emit(self.c["item"])
            return
        super().keyPressEvent(e)


class _Bar(QWidget):
    """A compare cell's bar."""

    def __init__(self, share: float, best: bool, parent=None):
        super().__init__(parent)
        self.share, self.best = share, best
        self.setFixedHeight(4)
        self.setMinimumWidth(40)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(self.rect()), 2, 2)
        p.setBrush(qc("text_primary" if self.best else "info"))
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.share, 4), 2, 2)
        p.end()


class CompareView(QWidget):
    """Everything that fits the editor's open slots."""

    COLUMNS = 4

    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.ctx = editor.ctx
        self.kind = editor.tray_kind()
        self.targets = editor.targets()
        row = editor.fitted_row() or {}
        self.fitted_item = row.get("item") or ""
        self.fitted_source = row.get("source") or "stock"
        self.fitted_qualities = row.get("qualities")
        self.stock_item = editor.stock_item(self.targets[0]) if self.targets else ""
        self.choices = editor.choices()
        n = editor.selected()
        size = (model.slot_of(editor._view["rows"], self.targets[0]) or {}).get("max", 0) if self.targets else 0
        count = f" · ×{len(self.targets)}" if len(self.targets) > 1 else ""
        self.port = f"{'Missiles · ' if self.kind == 'missile' else ''}{n.label} · size {size}{count}"
        self.fit_to = ("" if len(self.targets) == 1 else " for both" if len(self.targets) == 2
                       else f" for all {len(self.targets)}")
        self.now = editor._view["totals"]
        self.metrics = self._metrics()
        self.max_of = {m.key: max([1e-9] + [m.of(i) or 0 for i in self.choices]) for m in self.metrics}
        self.query = ""
        self.sort = "main"
        self.group = ""
        best = self._sorted([i for i in self.choices if i != self.fitted_item], self.metrics[0])
        self.pins = ([self.fitted_item] if self.fitted_item in self.ctx.items else []) + best
        self.pins = self.pins[:3]
        self.sel = self.fitted_item if self.fitted_item in self.ctx.items else (self.choices[0] if self.choices else "")
        self._build()
        self._render()

    # -- the numbers -------------------------------------------------------------------------------------
    def _part(self, item: str) -> dict:
        return self.ctx.items.get(item) or {}

    def _stats(self, item: str) -> dict:
        return part_stats(self._part(item))

    def _price(self, item: str):
        a = model.availability(self.ctx, item)
        return a.cheapest["price"] if a.cheapest else None

    def _metrics(self) -> list[_Metric]:
        kind, ctx = self.kind, self.ctx
        short, unit = KIND_STAT[kind][1], KIND_STAT[kind][0]

        def main(item: str):
            if item == self.fitted_item:
                return model.stat_of(kind, ctx, item, self.fitted_source, self.fitted_qualities)
            return model.stat_of(kind, ctx, item)

        draw = _Metric("draw", "Power draw", "draw", lambda i: self._stats(i).get("pmax", 0), True)
        extra = {
            "gun": [_Metric("alpha", "Alpha", "alpha", lambda i: sum((self._stats(i).get("alpha") or {}).values())),
                    _Metric("range", "Range", "m", lambda i: (self._part(i).get("gun") or {}).get("range") or 0)],
            "missile": [_Metric("lock", "Lock time", "s", lambda i: (self._part(i).get("missile") or {}).get("lockTime"),
                                True),
                        _Metric("speed", "Speed", "m/s", lambda i: (self._part(i).get("missile") or {}).get("speed") or 0)],
            "rack": [_Metric("size", "Missile size", "S",
                             lambda i: max([0] + [s["max"] for s in self._part(i).get("slots") or []]))],
            "shield": [_Metric("regen", "Regen", "HP/s", lambda i: self._stats(i).get("regen", 0))],
            "power": [], "cooler": [draw],
            "quantum": [_Metric("cool", "Cooldown", "s", lambda i: self._stats(i).get("qcooldown"), True), draw],
            "radar": [_Metric("ping", "Ping cooldown", "s", lambda i: (self._part(i).get("radar") or {}).get("ping"),
                              True), draw],
            "other": [],
        }[kind]
        return ([_Metric("main", "DPS" if short == "DPS" else _cap(unit), short, main, model.lower_is_better(kind))]
                + extra + [_Metric("price", "Price", "aUEC", self._price, True)])

    def _group_of(self, item: str) -> str:
        p = self._part(item)
        if self.kind == "gun":
            tags = p.get("tags") if isinstance(p.get("tags"), list) else str(p.get("tags") or "").split()
            import re
            for t in tags:
                m = re.search(r"(Cannon|Repeater|Gatling|Scattergun|MassDriver)$", t)
                if m:
                    return "Mass drivers" if m.group(1) == "MassDriver" else f"{m.group(1)}s"
            return ""
        if self.kind == "missile":
            s = (p.get("missile") or {}).get("signal") or ""
            return {"IR": "Heat (IR)", "EM": "EM", "CrossSection": "Cross-section", "CS": "Cross-section"}.get(s, s)
        return p.get("class") or ""

    def _sorted(self, items: list[str], m: _Metric) -> list[str]:
        def key(i):
            v = m.of(i)
            return (v is None, 0 if v is None else (v if m.lower else -v), self._part(i).get("name") or i)
        return sorted(items, key=key)

    def _up_to(self, item: str) -> str:
        recipe = self.ctx.recipes.get(item)
        if not recipe:
            return ""
        own = model.stat_of(self.kind, self.ctx, item)
        best = model.stat_of(self.kind, self.ctx, item, "craft", best_qualities(recipe))
        return f" · up to {show_stat(best)} crafted" if best > own + 1e-6 else ""

    def _tag(self, item: str) -> str:
        if item == self.stock_item:
            return "stock"
        a = model.availability(self.ctx, item)
        return "buy" if a.can_buy else "craft" if a.can_craft else "unobtainable"

    def _how(self, item: str) -> str:
        a = model.availability(self.ctx, item)
        if a.cheapest:
            shops = f"{a.shops} {'shop' if a.shops == 1 else 'shops'}"
            return f"{shops} · or craft" if a.can_craft else shops
        if a.can_craft:
            return "Craft only"
        return "Comes with the ship" if item == self.stock_item else "No known seller · not craftable"

    def _gets(self, item: str) -> list[dict]:
        """The two ways to put a part on (Stock for the ship's own); off when no shop sells it or no
        blueprint makes it; on for how the fitted part is got now."""
        a = model.availability(self.ctx, item)
        stock = item == self.stock_item
        fitted = item == self.fitted_item
        crafted = fitted and self.fitted_source == "craft"
        return [{"source": "stock" if stock else "buy", "label": "Stock" if stock else "Buy",
                 "can": stock or a.can_buy, "on": fitted and not crafted},
                {"source": "craft", "label": "Craft", "can": a.can_craft, "on": crafted}]

    # -- layout --------------------------------------------------------------------------------------------
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(12)
        back = QPushButton(f"←  Back to {self.ed.entry.name or self.ed.entry.ship_name} · "
                           f"{(self.ed.current().name if self.ed.current() else 'Stock')}", objectName="LoBack")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.ed.close_subview)
        v.addWidget(back, alignment=Qt.AlignLeft)
        head = QHBoxLayout()
        head.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_caps(self.port, "info"))
        title = QLabel(f"Everything that fits <span style='color:{PALETTE['text_muted']}'>· {len(self.choices)}</span>")
        set_font(title, ui_font(28, QFont.ExtraBold))
        titles.addWidget(title)
        head.addLayout(titles)
        head.addStretch(1)
        self.search = QLineEdit(objectName="SearchField")
        self.search.setPlaceholderText(f"Search {KIND_LABEL[self.kind][1].lower()} or makers")
        self.search.setFixedWidth(240)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        head.addWidget(self.search, alignment=Qt.AlignBottom)
        sorts = QHBoxLayout()
        sorts.setSpacing(6)
        sorts.addWidget(_label("Sort", "LoHint"))
        self.sort_chips = []
        for m in self.metrics:
            chip = _Chip(m.label, m.key == self.sort)
            chip.clicked.connect(lambda _c=False, k=m.key: self._set("sort", k))
            sorts.addWidget(chip)
            self.sort_chips.append((m.key, chip))
        head.addLayout(sorts)
        v.addLayout(head)
        filters = QHBoxLayout()
        filters.setSpacing(6)
        groups = sorted({g for g in (self._group_of(i) for i in self.choices) if g})
        self.group_chips = []
        if len(groups) > 1:
            for key, text in [("", "All kinds")] + [(g, g) for g in groups]:
                chip = _Chip(text, key == self.group)
                chip.clicked.connect(lambda _c=False, k=key: self._set("group", k))
                filters.addWidget(chip)
                self.group_chips.append((key, chip))
        filters.addStretch(1)
        filters.addWidget(_label("Click to preview on the ship · Buy or Craft to put it on · + to compare (up to 3)",
                                 "LoHint"))
        v.addLayout(filters)
        self.grid_scroll = QScrollArea(objectName="LoScroll")
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self.grid_scroll.setWidget(self.grid_host)
        v.addWidget(self.grid_scroll, 1)
        self.dock = QFrame(objectName="LoDock")
        self.dock.setMinimumHeight(200)
        dh = QHBoxLayout(self.dock)
        dh.setContentsMargins(20, 14, 20, 16)
        dh.setSpacing(20)
        self.table_host = QWidget()
        self.table = QGridLayout(self.table_host)
        self.table.setContentsMargins(0, 0, 0, 0)
        self.table.setHorizontalSpacing(16)
        self.table.setVerticalSpacing(6)
        dh.addWidget(self.table_host, 1)
        self.picked_host = QWidget()
        self.picked_host.setFixedWidth(320)
        self.picked = QVBoxLayout(self.picked_host)
        self.picked.setContentsMargins(20, 0, 0, 0)
        self.picked.setSpacing(6)
        dh.addWidget(self.picked_host)
        v.addWidget(self.dock)

    def _on_search(self, text: str) -> None:
        self.query = text.strip().lower()
        self._render_cards()

    def _set(self, what: str, value: str) -> None:
        setattr(self, what, value)
        for key, chip in (self.sort_chips if what == "sort" else self.group_chips):
            chip.setChecked(key == value)
        self._render_cards()

    def _render(self) -> None:
        self._render_cards()
        self._render_dock()

    def _cards(self) -> list[dict]:
        m = next((x for x in self.metrics if x.key == self.sort), self.metrics[0])
        shown_m = self.metrics[0] if m.key == "price" else m
        mx = self.max_of.get(shown_m.key, 1)
        fitted_v = (shown_m.of(self.fitted_item) or 0) if self.fitted_item in self.ctx.items else 0
        out = []
        for item in self._sorted(self._shown(), m):
            p = self._part(item)
            v = shown_m.of(item)
            fitted = item == self.fitted_item
            diff = (v or 0) - fitted_v
            better = diff < 0 if shown_m.lower else diff > 0
            cost = self._price(item)
            unit = KIND_STAT[self.kind][1] if shown_m.key == "main" else shown_m.unit
            same = abs(diff) < 1e-6
            out.append({
                "item": item, "name": p.get("name") or item, "sub": model.describe(p) + self._up_to(item),
                "tag": self._tag(item), "fitted": fitted, "stock": item == self.stock_item,
                "value": "—" if v is None else show_stat(v), "unit": unit,
                "bar": min(1.0, (v or 0) / mx) if mx else 0.0,
                "delta": "" if fitted or v is None else f"±0 {unit}" if same
                else f"{'▲ +' if diff > 0 else '▼ −'}{show_stat(abs(diff))} {unit}",
                "tone": "same" if fitted or same else "better" if better else "worse",
                "side": self._how(item), "price": "—" if cost is None else f"{money(cost)} aUEC",
                "aria": f"{p.get('name') or item}, {'unknown' if v is None else show_stat(v)} {unit}, "
                        + (self._how(item) if cost is None else f"{money(cost)} aUEC") + (", fitted" if fitted else ""),
            })
        return out

    def _shown(self) -> list[str]:
        out = []
        for item in self.choices:
            p = self._part(item)
            if not p:
                continue
            if self.query and self.query not in f"{p.get('name', '')} {p.get('manufacturer') or ''}".lower():
                continue
            if self.group and self._group_of(item) != self.group:
                continue
            out.append(item)
        return out

    def _render_cards(self) -> None:
        kit.clear_layout(self.grid)
        cards = self._cards()
        for i, c in enumerate(cards):
            w = _CompareCard(c, c["item"] == self.sel, c["item"] in self.pins, self._gets(c["item"]))
            w.selected.connect(self._select)
            w.pinned.connect(self._toggle_pin)
            w.fit.connect(self._fit)
            self.grid.addWidget(w, i // self.COLUMNS, i % self.COLUMNS)
        for col in range(self.COLUMNS):
            self.grid.setColumnStretch(col, 1)
        if not cards:
            self.grid.addWidget(_label("Nothing that fits matches.", "LoTraySrc"), 0, 0, 1, self.COLUMNS)

    def _select(self, item: str) -> None:
        self.sel = item
        self._render()

    def _toggle_pin(self, item: str) -> None:
        self.pins = [x for x in self.pins if x != item] if item in self.pins else (self.pins + [item])[-3:]
        self._render()

    def _fit(self, item: str, source: str) -> None:
        self.ed.close_subview(refresh=False)
        self.ed.fit(item, source)

    def _render_dock(self) -> None:
        kit.clear_layout(self.table)
        cols = [(i, self._part(i).get("name") or i) for i in self.pins] + [None] * 3
        cols = cols[:3]
        self.table.addWidget(_caps("Compare"), 0, 0)
        for j, col in enumerate(cols):
            if col is None:
                self.table.addWidget(_label("+ pin a part", "LoHint"), 0, j + 1)
                continue
            head = QHBoxLayout()
            name = _label(col[1], "LoCompareName")
            set_font(name, ui_font(14, QFont.ExtraBold))
            head.addWidget(name)
            x = QPushButton("×", objectName="LoLink")
            x.setAccessibleName(f"Stop comparing {col[1]}")
            x.setCursor(Qt.PointingHandCursor)
            x.clicked.connect(lambda _c=False, i=col[0]: self._toggle_pin(i))
            head.addWidget(x)
            head.addStretch(1)
            holder = QWidget()
            holder.setLayout(head)
            head.setContentsMargins(0, 0, 0, 0)
            self.table.addWidget(holder, 0, j + 1)
        for r, m in enumerate(self.metrics, start=1):
            self.table.addWidget(_label(m.label, "LoHint"), r, 0)
            vals = [m.of(c[0]) if c else None for c in cols]
            real = [v for v in vals if v is not None and (m.key != "price" or v > 0)]
            best = (min(real) if m.lower else max(real)) if real else None
            mx = self.max_of.get(m.key, 1)
            for j, col in enumerate(cols):
                if col is None:
                    continue
                v = vals[j]
                cell = QHBoxLayout()
                cell.setSpacing(10)
                if v is None:
                    text = "craft" if m.key == "price" and model.availability(self.ctx, col[0]).can_craft else "—"
                    bar = _Bar(0, False)
                    is_best = False
                else:
                    text = money(v) if m.key == "price" else f"{money(v)} m" if m.unit == "m" else show_stat(v)
                    is_best = len(real) > 1 and v == best
                    bar = _Bar(min(1.0, v / mx), is_best)
                cell.addWidget(bar, 1)
                lab = _num(text, 16)
                lab.setMinimumWidth(64)
                lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                add_css(lab, f"color: {PALETTE['text_primary' if is_best else 'text_secondary']};")
                cell.addWidget(lab)
                holder = QWidget()
                cell.setContentsMargins(0, 0, 0, 0)
                holder.setLayout(cell)
                self.table.addWidget(holder, r, j + 1)
        self.table.setColumnMinimumWidth(0, 110)
        for j in range(1, 4):
            self.table.setColumnStretch(j, 1)
        # The selected part: what it does to the ship, and how to get it.
        kit.clear_layout(self.picked)
        p = self._part(self.sel)
        if not p:
            return
        self.picked.addWidget(_caps("Selected"))
        name = _label(p.get("name") or self.sel, "LoTrayName")
        self.picked.addWidget(name)
        label, of, lower = {
            "gun": ("Ship burst DPS", lambda t: t["dps"], False),
            "rack": ("Missile damage", lambda t: t["missileDamage"], False),
            "missile": ("Missile damage", lambda t: t["missileDamage"], False),
            "shield": ("Ship shield HP", lambda t: t["shieldHp"], False),
            "power": ("Power segments", lambda t: t["segments"], False),
            "cooler": ("Coolant", lambda t: t["coolant"], False),
            "quantum": ("Quantum Mm/s", lambda t: t["quantumSpeed"] / 1e6, False),
            "radar": ("Power draw", lambda t: t["powerMax"], True),
            "other": ("Power draw", lambda t: t["powerMax"], True),
        }[self.kind]
        now = of(self.now)
        fitted = self.sel == self.fitted_item
        after = now if fitted else of(model.totals_with(self.ctx, model.fit_part(self.ctx, self.ed.parts,
                                                                                  self.targets, self.sel)))
        d = after - now
        tone = "text_muted" if abs(d) < 1e-6 else "success" if (d > 0) != lower else "warning"
        delta = "no change" if abs(d) < 1e-6 else f"{'▲ +' if d > 0 else '▼ −'}{show_stat(abs(d))}"
        ship = _label(f"{label}&nbsp; <span style='font-family:Rajdhani; font-size:18px; font-weight:700; "
                      f"color:{PALETTE['text_primary']}'>{show_stat(now)} → {show_stat(after)}</span>&nbsp; "
                      f"<b style='color:{PALETTE[tone]}'>{delta}</b>", "LoTraySrc", wrap=True)
        self.picked.addWidget(ship)
        a = model.availability(self.ctx, self.sel)
        if fitted:
            how = "Fitted now"
        elif a.cheapest:
            how = f"Cheapest {money(a.cheapest['price'])} aUEC at {a.cheapest['place']} · {a.shops} shops"
        elif a.can_craft:
            how = "Craft only · goes on your craft list"
        else:
            how = self._how(self.sel)
        self.picked.addWidget(_label(how, "LoHint", wrap=True))
        self.picked.addStretch(1)
        ctas = QHBoxLayout()
        ctas.setSpacing(8)
        for g in self._gets(self.sel):
            b = QPushButton(f"{g['label']} ✓" if g["on"] else f"{g['label']}{self.fit_to}",
                            objectName="LoCta" if g["can"] and not g["on"] else "KitButton")
            b.setEnabled(g["can"] and not g["on"])
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, s=g["source"]: self._fit(self.sel, s))
            ctas.addWidget(b)
        self.picked.addLayout(ctas)


# == craft quality ==========================================================================================

class _Step(QAbstractButton):
    """One quality step: the quality, how often finds reach it (a bar), the share."""

    def __init__(self, q: int, share: str, height: int, aria: str, parent=None):
        super().__init__(parent)
        self.q, self.share, self.bar = q, share, height
        self.setCheckable(True)
        self.setAutoExclusive(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(aria)
        self.setMinimumWidth(52)
        self.setFixedHeight(84)
        self.setAttribute(Qt.WA_Hover)

    def sizeHint(self):
        return QSize(60, 84)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        p.setBrush(qc("info_soft") if on else QColor(255, 255, 255, 5))
        p.setPen(QPen(qc("info") if on or self.underMouse() or self.hasFocus() else EDGE, 1))
        p.drawRoundedRect(r, 10, 10)
        p.setFont(num_font(17))
        p.setPen(qc("text_primary"))
        p.drawText(QRectF(0, 6, self.width(), 20), Qt.AlignCenter, str(self.q))
        p.setPen(Qt.NoPen)
        p.setBrush(qc("info") if on else QColor(255, 255, 255, 41))
        p.drawRoundedRect(QRectF(6, 28 + 34 - self.bar, self.width() - 12, self.bar), 3, 3)
        p.setFont(ui_font(10))
        p.setPen(qc("text_muted"))
        p.drawText(QRectF(0, 64, self.width(), 14), Qt.AlignCenter, self.share)
        p.end()


class CraftDialog(QDialog):
    """Craft quality: one step per recipe slot; what the picks make of the part."""

    applied = Signal(list, list)          # qualities, paths

    MAIN_STAT = {"shield": "shield", "power": "power", "cooler": "coolant", "quantum": "quantum"}

    def __init__(self, editor, node: model.BusNode, paths: list[str]):
        super().__init__(editor)
        self.setObjectName("LoDialog")
        self.setModal(True)
        self.ed, self.node, self.paths = editor, node, paths
        self.ctx = editor.ctx
        self.item, self.kind = node.item, node.kind
        self.part = self.ctx.items.get(self.item) or {}
        self.recipe = self.ctx.recipes.get(self.item) or {}
        self.sides = model.slot_names(paths)
        self.target: str | None = None
        self.picks = [(node.qualities or [])[i] if node.qualities and i < len(node.qualities) else None
                      for i in range(len(self.recipe.get("slots") or []))]
        self.setWindowTitle(f"Craft {self.part.get('name') or self.item}")
        self.resize(1080, 640)
        self._build()
        self._render()

    def _dist(self, option: dict) -> list:
        odds = self.ctx.odds
        if option.get("resource"):
            key = (self.ctx.refining.get(option["resource"]) or {}).get("ore") or option["resource"]
        else:
            key = next((k for k, v in odds.items() if v["name"].lower() == option.get("name", "").lower()), None)
        systems = list(((odds.get(key) or {}).get("systems") or {}).values()) if key else []
        systems.sort(key=lambda d: -sum(q * p for q, p in d))
        return systems[0] if systems else []

    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        aside = QFrame(objectName="LoCraftAside")
        aside.setFixedWidth(340)
        self.av = QVBoxLayout(aside)
        self.av.setContentsMargins(24, 24, 24, 24)
        self.av.setSpacing(14)
        outer.addWidget(aside)
        right = QWidget()
        self.rv = QVBoxLayout(right)
        self.rv.setContentsMargins(28, 24, 28, 24)
        self.rv.setSpacing(18)
        outer.addWidget(right, 1)

    def _value(self, picks) -> float:
        return model.stat_of(self.kind, self.ctx, self.item, "craft", picks)

    def _render(self) -> None:
        kit.clear_layout(self.av)
        kit.clear_layout(self.rv)
        count = f" ×{len(self.paths)}" if len(self.paths) > 1 else ""
        self.av.addWidget(_caps(f"{self.node.label} · {self.node.size}{count}", "info"))
        title = QLabel(self.part.get("name") or self.item)
        set_font(title, ui_font(28, QFont.ExtraBold))
        title.setWordWrap(True)
        self.av.addWidget(title)
        now, base = self._value(self.picks), model.stat_of(self.kind, self.ctx, self.item)
        best = self._value(best_qualities(self.recipe))
        box = QFrame(objectName="LoPanel")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(16, 14, 16, 14)
        bv.addWidget(_caps(f"{KIND_STAT[self.kind][0]}{' each' if len(self.paths) > 1 else ''}"))
        line = QHBoxLayout()
        line.addWidget(_num(show_stat(now), 52))
        tone = "success" if now > base + 1e-9 else "warning" if now < base - 1e-9 else "text_muted"
        pct = QLabel(f"{_pct_text(now / base if base else 1)} vs uncrafted")
        add_css(pct, f"color: {PALETTE[tone]}; font-weight: 700; font-size: 14px;")
        line.addWidget(pct, alignment=Qt.AlignBottom)
        line.addStretch(1)
        bv.addLayout(line)
        meter = _Meter(now / best if best else 0, base / best if best else 0)
        bv.addWidget(meter)
        ends = QHBoxLayout()
        ends.addWidget(_label(f"uncrafted {show_stat(base)}", "LoHint"))
        ends.addStretch(1)
        ends.addWidget(_label(f"best {show_stat(best)}", "LoHint"))
        bv.addLayout(ends)
        self.av.addWidget(box)
        others = QGridLayout()
        others.setSpacing(10)
        for i, (stat, text, t) in enumerate(self._others()):
            cell = QFrame(objectName="LoPanel")
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(12, 10, 12, 10)
            cv.addWidget(_caps(stat))
            v = _num(text, 22)
            add_css(v, f"color: {PALETTE[t]};")
            cv.addWidget(v)
            others.addWidget(cell, i // 2, i % 2)
        self.av.addLayout(others)
        self.av.addStretch(1)
        if len(self.paths) > 1:
            row = QHBoxLayout()
            row.addWidget(_label("Apply to", "LoTraySrc"))
            options = [(None, "Both" if len(self.paths) == 2 else "All")] + self.sides
            for i, (path, text) in enumerate(options):
                b = QPushButton(text, objectName="LoSeg")
                b.setCheckable(True)
                b.setChecked(self.target == path)
                b.setProperty("pos", "first" if i == 0 else "last" if i == len(options) - 1 else "mid")
                b.clicked.connect(lambda _c=False, p=path: self._set_target(p))
                row.addWidget(b)
            row.addStretch(1)
            self.av.addLayout(row)

        intro = QHBoxLayout()
        intro.addWidget(_label("Pick the quality you'll craft with. Each step shows how often it turns up in finds.",
                               "LoTraySrc", wrap=True), 1)
        intro.addWidget(_label("Esc closes", "LoHint"))
        self.rv.addLayout(intro)
        for i, rs in enumerate(self.recipe.get("slots") or []):
            self.rv.addLayout(self._slot_row(i, rs))
        self.rv.addStretch(1)
        foot = QHBoxLayout()
        foot.setSpacing(16)
        foot.addWidget(_label(self._needs_text(), "LoTraySrc", wrap=True), 1)
        cancel = kit.button("Cancel", "secondary", self.reject)
        foot.addWidget(cancel)
        use = QPushButton("Use these qualities", objectName="LoCta")
        use.setCursor(Qt.PointingHandCursor)
        use.setEnabled(any(q is not None for q in self.picks))
        use.clicked.connect(self._apply)
        foot.addWidget(use)
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet("background: rgba(218, 197, 164, 0.12);")
        self.rv.addWidget(rule)
        self.rv.addLayout(foot)

    def _slot_row(self, i: int, rs: dict) -> QVBoxLayout:
        option = (rs.get("options") or [{}])[0]
        dist = self._dist(option)
        band = {q: p for q, p in dist}
        steps = [q for q in (option.get("steps") or [1000]) if q >= (option.get("minQuality") or 0)]
        mx = max([1e-9] + [band.get(q, 0) for q in steps])
        mods = rs.get("modifiers") or []
        q = self.picks[i]
        first = mods[0] if mods else None
        effect = modifier_value(first["ranges"], q) if first and q is not None else None
        amount = (f"{(option.get('scu') or 0) * (rs.get('multiplier') or 1):,.3f}".rstrip("0").rstrip(".") + " SCU"
                  if option.get("resource") else f"{option.get('qty') or 1} units")
        v = QVBoxLayout()
        v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        name = QLabel(rs.get("name") or "")
        set_font(name, ui_font(15, QFont.ExtraBold))
        head.addWidget(name)
        head.addWidget(_label(f"{option.get('name', '?')} · {amount}", "LoHint"))
        head.addStretch(1)
        head.addWidget(_label(", ".join(m.get("stat") or "" for m in mods) or "no effect", "LoTraySrc"))
        text, tone = (self._effect_text(effect), self._effect_tone(effect)) if effect else ("uncrafted", "text_muted")
        eff = _num(text, 18)
        eff.setMinimumWidth(64)
        eff.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        add_css(eff, f"color: {PALETTE[tone]};")
        head.addWidget(eff)
        v.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(6)
        for sq in steps:
            share = band.get(sq, 0)
            fx = self._effect_text(modifier_value(first["ranges"], sq)) if first else ""
            st = _Step(sq, ("<0.1%" if share < 0.1 else f"{share:.1f}%") if dist else "",
                       max(3, round(32 * share / mx)),
                       f"Quality {sq}" + (f", {share:.1f} percent of finds" if dist else "")
                       + (f", {first.get('stat')} {fx}" if fx else ""))
            st.setChecked(q == sq)
            st.clicked.connect(lambda _c=False, i=i, sq=sq: self._pick(i, sq))
            row.addWidget(st)
        v.addLayout(row)
        return v

    @staticmethod
    def _effect_text(v: tuple[float, str]) -> str:
        value, kind = v
        return _pct_text(value) if kind == "factor" else f"{'+' if value >= 0 else '−'}{abs(value):g}"

    @staticmethod
    def _effect_tone(v: tuple[float, str]) -> str:
        value, kind = v
        d = value - 1 if kind == "factor" else value
        return "success" if d > 1e-9 else "warning" if d < -1e-9 else "text_muted"

    def _others(self) -> list[tuple[str, str, str]]:
        """Every stat the recipe changes besides the main one, combined over its slots."""
        by: dict[str, list] = {}
        main = self.MAIN_STAT.get(self.kind)
        for i, rs in enumerate(self.recipe.get("slots") or []):
            q = self.picks[i]
            if q is None:
                continue
            for m in rs.get("modifiers") or []:
                if main and STAT_PROPS.get(m.get("property") or "") == main:
                    continue
                by.setdefault(m.get("stat") or "", []).append(modifier_value(m["ranges"], q))
        out = []
        for stat, values in by.items():
            kind = values[0][1]
            v = (1 + sum(x - 1 for x, _k in values), kind) if kind == "factor" else (sum(x for x, _k in values), kind)
            out.append((stat, self._effect_text(v), self._effect_tone(v)))
        return out

    def _needs_text(self) -> str:
        count = 1 if self.target else len(self.paths)
        needs: dict[str, dict] = {}
        at: dict[str, tuple[dict, int]] = {}
        for i, rs in enumerate(self.recipe.get("slots") or []):
            option = (rs.get("options") or [None])[0]
            if not option:
                continue
            q = max(option.get("minQuality") or 0, self.picks[i] or 0)
            n = needs.setdefault(option["name"], {"amount": 0.0, "scu": bool(option.get("resource")), "q": 0})
            n["amount"] += ((option.get("scu") or 0) * (rs.get("multiplier") or 1) if option.get("resource")
                            else (option.get("qty") or 0)) * count
            n["q"] = max(n["q"], q)
            if self.picks[i] is not None and (option["name"] not in at or self.picks[i] > at[option["name"]][1]):
                at[option["name"]] = (option, self.picks[i])
        parts = []
        items = list(needs.items())
        for i, (name, n) in enumerate(items):
            amount = f"{n['amount']:,.2f}".rstrip("0").rstrip(".") + " SCU" if n["scu"] else f"{n['amount']:g}"
            lead = "You'll need" if i == 0 else " and" if i == len(items) - 1 else ","
            parts.append(f"{lead} <b style='font-family:Rajdhani; font-size:17px; color:{PALETTE['text_primary']}'>"
                         f"{amount}</b> {name} at {n['q']}+")
        odds = []
        for option, q in at.values():
            share = sum(p for dq, p in self._dist(option) if dq >= q)
            odds.append(f"{option['name']} {share:,.{2 if share < 1 else 0}f}%")
        text = "".join(parts)
        if odds:
            text += f" · chance a find is good enough: <b style='color:{PALETTE['text_primary']}'>" \
                    f"{' · '.join(odds)}</b>"
        return text

    def _pick(self, i: int, q: int) -> None:
        self.picks[i] = q
        self._render()

    def _set_target(self, path: str | None) -> None:
        self.target = path
        self._render()

    def _apply(self) -> None:
        self.applied.emit(list(self.picks), [self.target] if self.target else list(self.paths))
        self.accept()


class _Meter(QWidget):
    def __init__(self, value: float, mark: float, parent=None):
        super().__init__(parent)
        self.value, self.mark = min(1.0, max(0.0, value)), min(1.0, max(0.0, mark))
        self.setFixedHeight(14)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(QRectF(0, 4, w, 6), 3, 3)
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, qc("info_dim"))
        g.setColorAt(1, qc("info"))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 4, w * self.value, 6), 3, 3)
        p.setBrush(qc("text_secondary"))
        p.drawRect(QRectF(w * self.mark - 1, 0, 2, 14))
        p.end()


# == shopping & crafting ===================================================================================

class _Check(QAbstractButton):
    """A tick box (the saved list's)."""

    def __init__(self, checked: bool, label: str, small: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setAccessibleName(label)
        self.setCursor(Qt.PointingHandCursor)
        s = 24 if small else 30
        self.setFixedSize(s, s)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(QPen(qc("info") if on or self.underMouse() or self.hasFocus() else qc("border_strong"), 1.5))
        p.setBrush(qc("info") if on else Qt.NoBrush)
        p.drawRoundedRect(r, 7, 7)
        if on:
            pen = QPen(QColor("#0b0d10"), 2.4)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            w, h = r.width(), r.height()
            p.drawPolyline([r.topLeft() + type(r.topLeft())(w * 0.25, h * 0.52),
                            r.topLeft() + type(r.topLeft())(w * 0.43, h * 0.7),
                            r.topLeft() + type(r.topLeft())(w * 0.76, h * 0.32)])
        p.end()


class _Histogram(QWidget):
    """How often finds reach each quality: a bar per quality band, the ones good enough lit."""

    def __init__(self, dist: list, need: int, parent=None):
        super().__init__(parent)
        self.dist, self.need = dist, need
        self.setFixedHeight(66)

    def paintEvent(self, _e):
        if not self.dist:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.dist)
        gap = 4
        bw = (self.width() - gap * (n - 1)) / n
        mx = max(pp for _q, pp in self.dist) or 1
        for i, (q, share) in enumerate(self.dist):
            h = max(3, 44 * share / mx)
            x = i * (bw + gap)
            p.setPen(Qt.NoPen)
            p.setBrush(qc("info") if q >= self.need else QColor(255, 255, 255, 41))
            p.drawRoundedRect(QRectF(x, 46 - h, bw, h), 2, 2)
            p.setFont(ui_font(10))
            p.setPen(qc("text_muted"))
            p.drawText(QRectF(x - 4, 50, bw + 8, 14), Qt.AlignCenter, str(q))
        p.end()


class ShoppingView(QWidget):
    """Shopping & crafting for the open loadout."""

    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.ctx = editor.ctx
        self.route = "stops"
        self._build()
        self._render()

    # -- state ------------------------------------------------------------------------------------------
    @property
    def lo(self):
        return self.ed.current()

    @property
    def basket(self) -> dict | None:
        return self.lo.basket if self.lo else None

    def plan(self, route: str | None = None) -> dict:
        return model.view_of(self.ctx, self.ed.parts, route or (self.basket or {}).get("route") or self.route)

    def _name(self, item: str) -> str:
        return (self.ctx.items.get(item) or {}).get("name") or item

    def _ticks(self) -> set[str]:
        return set(self.lo.ticks if self.lo else [])

    def _ticked(self, key: str) -> bool:
        return bool(self.basket) and key in self._ticks()

    def _tick(self, key: str) -> None:
        ticks = self._ticks()
        ticks.symmetric_difference_update({key})
        self.ed.save_ticks(sorted(ticks))
        self._render()

    # -- layout -----------------------------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(objectName="LoScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)

    def _render(self) -> None:
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 8, 24)
        v.setSpacing(16)
        lo = self.lo
        if lo is None:
            v.addWidget(kit.EmptyState("This loadout isn't here", "It may have been deleted, here or on the website.",
                                       "Back to the loadout", self.ed.close_subview))
            self.scroll.setWidget(page)
            return
        basket = self.basket
        plan = self.plan()
        stops = basket["stops"] if basket else plan["shopping"]["stops"]
        unsold = basket["unsold"] if basket else plan["shopping"]["unsold"]
        keys = model.keys_of(stops, plan["crafting"])
        done = sum(1 for k in keys if self._ticked(k))
        left = sum(i["total"] for s in stops for sh in s["shops"] for i in sh["items"]
                   if not self._ticked(f"buy:{i['item']}"))

        from app.ui.loadout_editor import _Hero
        hero = _Hero()
        image = getattr(self.ed.ship, "image_file", None)
        hero.set_image(str(image) if image is not None and image.is_file() else None)
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(24, 16, 24, 0)
        back = QPushButton(f"←  Back to the loadout", objectName="LoBack")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.ed.close_subview)
        hv.addWidget(back, alignment=Qt.AlignLeft)
        title = QHBoxLayout()
        title.setSpacing(12)
        name = QLabel((self.ed.entry.name or self.ed.entry.ship_name).upper())
        set_font(name, num_font(48))
        title.addWidget(name, alignment=Qt.AlignBottom)
        sub = QLabel(lo.name)
        set_font(sub, ui_font(17, QFont.DemiBold))
        title.addWidget(sub, alignment=Qt.AlignBottom)
        title.addStretch(1)
        stats = [("To buy", f"{money(left)}", "aUEC"), ("Stops", str(len(stops)), "")]
        if basket:
            stats.append(("Progress", str(done), f"/ {len(keys)}"))
        for label, value, small in stats:
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(_caps(label, "text_secondary"))
            box.addWidget(_num_unit(value, 32, small))
            title.addSpacing(28)
            title.addLayout(box)
        hv.addLayout(title)
        hv.addSpacing(16)
        hero.setFixedHeight(190)
        v.addWidget(hero)

        # The saved list's bar.
        bar = QFrame(objectName="LoSaveBar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(20, 16, 20, 16)
        bh.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        drift = model.drifted(basket, plan)
        if not basket:
            h = QLabel("Going shopping?")
            body = ("Save the list to tick things off as you get them. It keeps these stops, shops and prices as they "
                    "are now, so nothing moves while you're out. The website gets it too.")
        else:
            h = QLabel("Saved list")
            if drift:
                body = (f"The loadout changed after you saved this list ({_ago(basket['savedAt'])}). Update it to "
                        "plan what's fitted now; your ticks on what's still on it stay.")
            else:
                body = (f"Saved {_ago(basket['savedAt'])} for "
                        f"{'the fewest stops' if basket['route'] == 'stops' else 'the lowest price'}, at the prices "
                        "of that moment. Updating plans it again with today's prices; your ticks stay.")
        set_font(h, ui_font(16, QFont.Bold))
        texts.addWidget(h)
        texts.addWidget(_label(body, "LoTraySrc", wrap=True))
        bh.addLayout(texts, 1)
        bar.setProperty("state", "drift" if drift else "saved" if basket else "new")
        if not basket:
            save = QPushButton("Save list", objectName="LoCta")
            save.setEnabled(bool(keys))
            save.setCursor(Qt.PointingHandCursor)
            save.clicked.connect(self._save_list)
            bh.addWidget(save)
        else:
            update = QPushButton("Update list", objectName="LoCta" if drift else "KitButton")
            update.setCursor(Qt.PointingHandCursor)
            update.clicked.connect(self._update_list)
            bh.addWidget(update)
            discard = kit.button("Discard", "ghost", self._discard_list)
            bh.addWidget(discard)
        v.addWidget(bar)

        cols = QHBoxLayout()
        cols.setSpacing(18)
        cols.addWidget(self._buy_panel(plan, stops, unsold, left), 1, Qt.AlignTop)
        cols.addWidget(self._craft_panel(plan), 1, Qt.AlignTop)
        v.addLayout(cols)
        v.addStretch(1)
        self.scroll.setWidget(page)

    def _buy_panel(self, plan: dict, stops: list, unsold: list, left: float) -> QWidget:
        basket = self.basket
        panel = _Panel()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(20, 18, 20, 18)
        pv.setSpacing(10)
        head = QHBoxLayout()
        h = QLabel("Buy run")
        set_font(h, ui_font(18, QFont.Bold))
        head.addWidget(h)
        head.addStretch(1)
        if not basket:
            for i, (key, text) in enumerate((("stops", "Fewest stops"), ("price", "Lowest price"))):
                b = QPushButton(text, objectName="LoSeg")
                b.setCheckable(True)
                b.setChecked(self.route == key)
                b.setProperty("pos", "first" if i == 0 else "last")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _c=False, k=key: self._set_route(k))
                head.addWidget(b)
        pv.addLayout(head)
        if basket:
            note = (f"{'Fewest stops' if basket['route'] == 'stops' else 'Lowest price'}, prices as reported to UEX "
                    "when you saved the list.")
        else:
            other = model.view_of(self.ctx, self.ed.parts, "price" if self.route == "stops" else "stops")["shopping"]
            same = other["stops"] == plan["shopping"]["stops"]
            fetched = uexparts.fetched()
            when = f" (last {_ago(datetime.fromtimestamp(fetched, timezone.utc).isoformat())})" if fetched else ""
            note = (f"{'Same plan either way for this list. ' if same else ''}Prices players reported to UEX; the "
                    f"launcher checks UEX every 6 hours{when}.")
        pv.addWidget(_label(note, "LoHint", wrap=True))
        if not stops:
            pv.addWidget(_label("Nothing to buy in this loadout.", "LoTraySrc"))
        for i, stop in enumerate(stops):
            sh = QHBoxLayout()
            sh.setSpacing(10)
            sh.addWidget(_caps(f"Stop {i + 1}", "info"))
            place = QLabel(stop["place"])
            set_font(place, ui_font(16, QFont.Bold))
            sh.addWidget(place)
            sh.addWidget(_label(" › ".join(x for x in (stop["system"], stop["planet"], stop["moon"]) if x), "LoHint"))
            sh.addStretch(1)
            pv.addLayout(sh)
            for shop in stop["shops"]:
                for it in shop["items"]:
                    pv.addWidget(self._buy_item(shop, it))
        if stops:
            tot = QHBoxLayout()
            tot.addWidget(_label("Total" if not basket else "Left to buy" if left else "All bought", "LoTraySrc"))
            tot.addStretch(1)
            tot.addWidget(_num_unit(money(left), 30, "aUEC"))
            pv.addSpacing(6)
            pv.addLayout(tot)
        for p in plan["crafting"]["parts"]:
            pv.addWidget(self._aside("craft", f"<b>{p['count']} × {self._name(p['item'])}</b>",
                                     " · on your craft list"))
        for u in unsold:
            craftable = u["item"] in self.ctx.recipes
            pv.addWidget(self._aside("unobtainable", f"<b>{u['count']} × {self._name(u['item'])}</b>",
                                     f" · no known seller{'' if craftable else ' and no recipe'}"))
        if basket:
            foot = QHBoxLayout()
            reset = kit.button("Reset ticks", "ghost", lambda: (self.ed.save_ticks([]), self._render()))
            reset.setEnabled(bool(self.lo.ticks))
            foot.addWidget(reset)
            foot.addStretch(1)
            foot.addWidget(_label("The saved list and its ticks sync with the website", "LoHint"))
            pv.addLayout(foot)
        return panel

    def _buy_item(self, shop: dict, it: dict) -> QWidget:
        key = f"buy:{it['item']}"
        row = QFrame(objectName="LoItem")
        row.setProperty("done", self._ticked(key))
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)
        if self.basket:
            check = _Check(self._ticked(key), f"Bought {it['count']} × {self._name(it['item'])}")
            check.clicked.connect(lambda _c=False, k=key: self._tick(k))
            h.addWidget(check)
        body = QVBoxLayout()
        body.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_caps(shop["shop"], "text_secondary"))
        top.addWidget(_TagLabel("buy"))
        top.addStretch(1)
        body.addLayout(top)
        name = QLabel(self._name(it["item"]))
        set_font(name, ui_font(15, QFont.Bold))
        body.addLayout(_wrap(name))
        meta = QHBoxLayout()
        meta.setSpacing(4)
        meta.addWidget(_label(f"{it['count']} × {money(it['price'])} ·", "LoHint"))
        change = QPushButton("Change shop", objectName="LoLink")
        change.setCursor(Qt.PointingHandCursor)
        change.clicked.connect(lambda _c=False, item=it["item"]: self._change_shop(item))
        meta.addWidget(change)
        meta.addStretch(1)
        body.addLayout(meta)
        h.addLayout(body, 1)
        h.addWidget(_num(money(it["total"]), 22), alignment=Qt.AlignVCenter)
        return row

    def _aside(self, tag: str, bold: str, rest: str) -> QWidget:
        row = QFrame(objectName="LoAside")
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)
        h.addWidget(_TagLabel(tag))
        h.addWidget(_label(f"{bold}<span style='color:{PALETTE['text_muted']}'>{rest}</span>", "LoTraySrc", wrap=True),
                    1)
        return row

    def _craft_panel(self, plan: dict) -> QWidget:
        crafting = plan["crafting"]
        panel = _Panel()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(20, 18, 20, 18)
        pv.setSpacing(12)
        head = QHBoxLayout()
        h = QLabel("Craft")
        set_font(h, ui_font(18, QFont.Bold))
        head.addWidget(h)
        if crafting["parts"]:
            parts = ", ".join(f"{p['count']} × {self._name(p['item'])}" for p in crafting["parts"])
            head.addWidget(_label(f"{parts} · {self._minutes(crafting['seconds'])} at a fabricator", "LoTraySrc", True),
                           1)
        else:
            head.addStretch(1)
        pv.addLayout(head)
        if not crafting["parts"]:
            pv.addWidget(_label("Nothing to craft. Pick CRAFT for a part in the loadout to plan its materials here.",
                                "LoTraySrc", wrap=True))
            return panel
        mats = QGridLayout()
        mats.setSpacing(12)
        for i, m in enumerate(crafting["materials"]):
            mats.addWidget(self._material(m), i // 2, i % 2, Qt.AlignTop)
        pv.addLayout(mats)
        for p in crafting["parts"]:
            key = f"craft:{p['item']}"
            row = QFrame(objectName="LoItem")
            row.setProperty("done", self._ticked(key))
            hh = QHBoxLayout(row)
            hh.setContentsMargins(14, 12, 14, 12)
            if self.basket:
                check = _Check(self._ticked(key), f"Crafted {p['count']} × {self._name(p['item'])}")
                check.clicked.connect(lambda _c=False, k=key: self._tick(k))
                hh.addWidget(check)
            body = QVBoxLayout()
            body.addWidget(_caps("Then at a fabricator", "text_secondary"))
            name = QLabel(f"Craft {p['count']} × {self._name(p['item'])}")
            set_font(name, ui_font(15, QFont.Bold))
            body.addWidget(name)
            hh.addLayout(body, 1)
            hh.addWidget(_num(self._minutes(p["seconds"]), 18))
            pv.addWidget(row)
        return panel

    def _mining_key(self, m: dict) -> str | None:
        odds = self.ctx.odds
        if m["unit"] == "scu":
            return (self.ctx.refining.get(m["key"]) or {}).get("ore") or (m["key"] if m["key"] in odds else None)
        return next((k for k, v in odds.items() if v["name"].lower() == m["name"].lower()), None)

    def _odds_of(self, m: dict) -> list[tuple[str, float, list]]:
        key = self._mining_key(m)
        systems = ((self.ctx.odds.get(key) or {}).get("systems") or {}) if key else {}
        out = [(s, o, systems.get(s) or []) for s, o in m["odds"].items()]
        return sorted([x for x in out if x[2]], key=lambda x: -x[1])

    def _material(self, m: dict) -> QWidget:
        key = f"mat:{m['key']}"
        card = QFrame(objectName="LoMat")
        card.setProperty("done", self._ticked(key))
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(_caps("Mine and refine" if m["unit"] == "scu" else "Collect", "text_secondary"))
        top.addStretch(1)
        if self.basket:
            check = _Check(self._ticked(key), f"Got {m['name']}", small=True)
            check.clicked.connect(lambda _c=False, k=key: self._tick(k))
            top.addWidget(check)
        v.addLayout(top)
        name = QLabel(m["name"])
        set_font(name, ui_font(18, QFont.Bold))
        v.addWidget(name)
        line = QHBoxLayout()
        amount = f"{m['amount']:,.2f}".rstrip("0").rstrip(".") + " SCU" if m["unit"] == "scu" else f"{m['amount']:g}"
        line.addWidget(_num(amount, 28))
        line.addWidget(_label(f"quality <b style='color:{PALETTE['text_primary']}'>{m['quality']}+</b>", "LoTraySrc"),
                       alignment=Qt.AlignBottom)
        line.addStretch(1)
        v.addLayout(line)
        odds = self._odds_of(m)
        if odds:
            system, share, dist = odds[0]
            v.addWidget(_caps("How often finds reach each quality", "text_secondary"))
            v.addWidget(_Histogram(dist, m["quality"]))
            pct = lambda x: f"{x:,.{2 if x < 1 else 1}f}".rstrip("0").rstrip(".") + "%"
            v.addWidget(_label(f"<b style='color:{PALETTE['text_primary']}'>{pct(share)}</b> of finds reach "
                               f"{m['quality']}+ in {_cap(system)}", "LoTraySrc", wrap=True))
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for s, o, _d in odds:
                chips.addWidget(_label(f"{_cap(s)} {pct(o)}", "LoChip"))
            chips.addStretch(1)
            v.addLayout(chips)
        if m.get("oreScu"):
            row = self.ctx.refining.get(m["key"]) or {}
            from app import refining
            confirmed = (refining.entry(m["key"]) or {}).get("confirmed")
            v.addWidget(_label(f"Mine about {m['oreScu']:,.2f}".rstrip("0").rstrip(".")
                               + f" SCU of ore: refining yields {round((row.get('yield') or 0) * 100)}% at the best "
                               f"method{'' if confirmed else ' (community figure, unconfirmed)'}.", "LoHint", wrap=True))
        mining = self._mining_key(m)
        if mining:
            resource = (self.ctx.odds.get(mining) or {}).get("name") or m["name"]
            link = QPushButton("Open in Mining Finder →", objectName="LoLink")
            link.setCursor(Qt.PointingHandCursor)
            link.clicked.connect(lambda: self.ed.open_tool.emit("mining", resource))
            v.addWidget(link, alignment=Qt.AlignLeft)
        return card

    @staticmethod
    def _minutes(seconds: float) -> str:
        return f"{seconds / 3600:.1f} h" if seconds >= 3600 else f"{round(seconds / 60)} min"

    # -- actions ----------------------------------------------------------------------------------------
    def _set_route(self, route: str) -> None:
        self.route = route
        self._render()

    def _snapshot(self) -> dict:
        route = (self.basket or {}).get("route") or self.route
        return model.snapshot(self.plan(route), route)

    def _save_list(self) -> None:
        self.ed.save_basket(self._snapshot(), [])
        self.ed.toast.show_message("List saved. Tick things off as you get them.")
        self._render()

    def _update_list(self) -> None:
        nxt = self._snapshot()
        still = set(model.keys_of(nxt["stops"], self.plan(nxt["route"])["crafting"]))
        self.ed.save_basket(nxt, [k for k in self._ticks() if k in still])
        self.ed.toast.show_message("List updated with today's prices.")
        self._render()

    def _discard_list(self) -> None:
        was, ticks = self.basket, sorted(self._ticks())
        if not was:
            return
        self.route = was["route"]
        self.ed.save_basket(None, [])
        self._render()

        def undo():
            self.ed.save_basket(was, ticks)
            self._render()
        self.ed.toast.show_message("Saved list discarded.", undo)

    def _buy_paths(self, item: str) -> list[str]:
        return [r["path"] for r in self.plan()["rows"] if r["item"] == item and r["source"] == "buy"]

    def _change_shop(self, item: str) -> None:
        paths = self._buy_paths(item)
        current = next(((self.ed.parts.get(p) or {}).get("shop") or "" for p in paths), "")
        offers = self.ctx.offers.get((self.ctx.items.get(item) or {}).get("uuid") or "") or []
        dialog = _ShopDialog(self, self._name(item), offers, current, self.route)
        if dialog.exec() != QDialog.Accepted:
            return
        terminal = dialog.choice
        nxt = dict(self.ed.parts)
        for path in paths:
            choice = dict(nxt.get(path) or {"item": item, "source": "buy"})
            if terminal:
                choice["shop"] = terminal
            else:
                choice = {"item": choice["item"], "source": choice["source"]}
            nxt[path] = choice
        offer = next((o for o in offers if o["terminal"] == terminal), None)
        self.ed.set_parts(nxt, f"{self._name(item)}: buying at {offer['shop']}, {offer['place']}." if offer
                          else f"{self._name(item)}: the plan picks the shop.")
        if self.basket:                    # a saved list follows: planned again with the new shop
            self.ed.save_basket(self._snapshot(), sorted(self._ticks()))
        self._render()


def _wrap(w: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(w)
    row.addStretch(1)
    return row


class _TagLabel(QWidget):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        from app.ui.loadout_parts import tag_width
        self.setFixedSize(tag_width(kind), 18)

    def paintEvent(self, _e):
        p = QPainter(self)
        draw_tag(p, 0, 0, self.kind)
        p.end()


class _ShopDialog(QDialog):
    """Where to buy a part: the plan's choice, or any shop that sells it (cheapest first)."""

    def __init__(self, parent, name: str, offers: list, current: str, route: str):
        super().__init__(parent)
        self.setObjectName("LoDialog")
        self.setWindowTitle(f"Where to buy {name}")
        self.choice = current
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(8)
        title = QLabel(f"Where to buy {name}")
        set_font(title, ui_font(18, QFont.Bold))
        v.addWidget(title)
        scroll = QScrollArea(objectName="LoScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        lv = QVBoxLayout(host)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        plan = QPushButton(f"Let the plan choose\n"
                           f"{'the stop that has most of the list' if route == 'stops' else 'the cheapest shop'}",
                           objectName="LoOffer")
        plan.setCheckable(True)
        plan.setChecked(not current)
        plan.clicked.connect(lambda: self._pick(""))
        lv.addWidget(plan)
        for o in offers:
            where = " › ".join(x for x in (o["system"], o["planet"], o["moon"]) if x)
            b = QPushButton(f"{o['shop']} · {money(o['price'])} aUEC\n{o['place']} · {where}", objectName="LoOffer")
            b.setCheckable(True)
            b.setChecked(o["terminal"] == current)
            b.clicked.connect(lambda _c=False, t=o["terminal"]: self._pick(t))
            lv.addWidget(b)
        lv.addStretch(1)
        scroll.setWidget(host)
        scroll.setMinimumHeight(min(480, 70 * (len(offers) + 1)))
        v.addWidget(scroll)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(kit.button("Cancel", "secondary", self.reject))
        v.addLayout(row)

    def _pick(self, terminal: str) -> None:
        self.choice = terminal
        self.accept()


# == removing a ship (#66) ===================================================================================

class RemoveShipDialog(QDialog):
    """Removing a ship that has loadouts asks first and lists them (shared ones marked). Keep ship
    has the focus; offline, the removal happens on the next sync."""

    def __init__(self, parent, ship_name: str, items: list, offline: bool, image: str | None = None):
        super().__init__(parent)
        self.setObjectName("LoDialog")
        self.setWindowTitle(f"Remove {ship_name}?")
        self.setFixedWidth(500)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        from app.ui.loadout_editor import _Hero
        top = _Hero()
        top.set_image(image)
        top.setFixedHeight(110)
        tv = QVBoxLayout(top)
        tv.setContentsMargins(22, 0, 22, 6)
        tv.addStretch(1)
        title = QLabel(f"Remove {ship_name}?".upper())
        set_font(title, num_font(28))
        tv.addWidget(title)
        v.addWidget(top)
        body = QVBoxLayout()
        body.setContentsMargins(22, 10, 22, 0)
        body.setSpacing(10)
        body.addWidget(_label("These loadouts are deleted with it, here and on sc-toolbox.com:", "LoTraySrc", True))
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for lo in items:
            chip = QFrame(objectName="LoRemoveChip")
            ch = QHBoxLayout(chip)
            ch.setContentsMargins(10, 4, 10, 4)
            ch.setSpacing(6)
            name = QLabel(lo.name)
            set_font(name, ui_font(13, QFont.DemiBold))
            ch.addWidget(name)
            if lo.share:
                ch.addWidget(_TagLabel("shared"))
            chips.addWidget(chip)
        chips.addStretch(1)
        body.addLayout(chips)
        shared = [lo.name for lo in items if lo.share]
        if shared:
            names = " and ".join(shared) if len(shared) <= 2 else f"{', '.join(shared[:-1])} and {shared[-1]}"
            body.addWidget(_label(f"The {names} link{'s' if len(shared) > 1 else ''} will show that "
                                  f"{'they were' if len(shared) > 1 else 'it was'} removed.", "LoHint", True))
        if offline:
            note = _label("You're offline: this happens on the next sync.", "LoOfflineNote", True)
            body.addWidget(note)
        v.addLayout(body)
        row = QHBoxLayout()
        row.setContentsMargins(22, 18, 22, 20)
        row.setSpacing(8)
        row.addStretch(1)
        keep = kit.button("Keep ship", "secondary", self.reject)
        n = len(items)
        remove = kit.button(f"Remove ship and {n} loadout{'s' if n != 1 else ''}", "danger", self.accept)
        remove.setAutoDefault(False)
        row.addWidget(keep)
        row.addWidget(remove)
        v.addLayout(row)
        keep.setDefault(True)
        keep.setFocus()
        self._keep = keep

    def showEvent(self, e):
        super().showEvent(e)
        self._keep.setFocus()
