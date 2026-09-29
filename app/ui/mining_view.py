"""Mining resource finder: pick resources (and a system / mining method),
see every location whose rocks hold *all* of them, with each location's
rock types, how often each spawns, and — for the rocks that carry a picked
resource — how much of it they hold and at what quality.

All data is extracted from the game files once per build (app.mining).
"""

from __future__ import annotations

import html
import threading

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, mining, settings
from app.theme import PALETTE

KIND_LABELS = {"planet": "Planet", "moon": "Moon", "lagrange": "Lagrange point",
               "belt": "Asteroid belt", "cluster": "Asteroid cluster"}
RARITY_COLORS = {"Common": "#9a958c", "Uncommon": "#7cc47f", "Rare": "#5fa8e8",
                 "Epic": "#b98ae8", "Legendary": "#e8935a"}


def _label(text: str, name: str = "SalvageCell", tip: str = "", align=None) -> QLabel:
    lbl = QLabel(text, objectName=name)
    if tip:
        lbl.setToolTip(tip)
    if align is not None:
        lbl.setAlignment(align)
    return lbl


def _pct(value: float) -> str:
    return f"{value:.1f}%" if value < 10 else f"{value:.0f}%"


class _Bar(QWidget):
    """A thin horizontal bar showing a spawn chance."""

    def __init__(self, value: float, lit: bool, parent=None):
        super().__init__(parent)
        self.value = max(0.0, min(100.0, value))
        self.lit = lit
        self.setFixedSize(64, 8)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(self.rect()), 3, 3)
        fill = QColor(PALETTE["accent_cyan"] if self.lit else PALETTE["text_muted"])
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.value / 100, self.height()), 3, 3)


def _chance(p: float) -> str:
    if p >= 10:
        return f"{p:.0f}%"
    if p >= 1:
        return f"{p:.1f}%"
    # Two significant digits for rare outcomes (0.18%, 0.0042%); never a
    # "<" — tooltips are HTML and would swallow it as a tag.
    return f"{p:.2g}%"


def _quality_tip(name: str, q: dict) -> str:
    dist = q["dist"]
    peak = max(p for _, p in dist) or 1
    rows = "".join(
        f"<tr><td align='right'>Q {v}</td><td align='right'>&nbsp;{html.escape(_chance(p))}&nbsp;</td>"
        f"<td><span style='color:{PALETTE['accent_amber']}'>"
        f"{'▇' * max(1, round(12 * p / peak)) if p >= 0.05 else '·'}</span></td></tr>"
        for v, p in dist
    )
    tail = []
    for threshold in (700, 900):
        share = sum(p for v, p in dist if v >= threshold)
        if 0 < share < 100:
            tail.append(f"Q ≥ {threshold}: <b>{html.escape(_chance(share))}</b>")
    return (f"<b>{name}</b> — chance of each quality<br>"
            f"<table cellspacing='0' cellpadding='1'>{rows}</table>"
            + ("<br>" + " &nbsp; ".join(tail) if tail else "")
            + "<br><i>Estimated from the game's quality settings.</i>")


class _QualityHist(QWidget):
    """Tiny histogram: one bar per possible quality, height ~ its chance
    (square-root scaled so rare high qualities stay visible).
    """

    def __init__(self, dist: list, parent=None):
        super().__init__(parent)
        self.dist = dist
        self.setFixedSize(max(24, 7 * len(dist)), 16)

    def paintEvent(self, _event):
        if not self.dist:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        peak = max(x for _, x in self.dist) or 1
        low, high = QColor(PALETTE["text_muted"]), QColor(PALETTE["accent_amber"])
        for i, (value, chance) in enumerate(self.dist):
            h = max(1.5, (chance / peak) ** 0.5 * self.height()) if chance > 0 else 0
            t = max(0.0, min(1.0, (value - 300) / 700))
            p.setBrush(QColor(
                round(low.red() + (high.red() - low.red()) * t),
                round(low.green() + (high.green() - low.green()) * t),
                round(low.blue() + (high.blue() - low.blue()) * t),
            ))
            p.drawRect(QRectF(i * 7, self.height() - h, 5, h))


def _signature_line(rock: dict, item: dict, method: str) -> tuple[str, str]:
    """('RS 3825  ×2 7650  ×3 11475 …', tooltip) — the scanner shows a
    group of rocks as the sum of their signatures.
    """
    sig = rock.get("signature") or 0
    if not sig:
        return "", ""
    muted = PALETTE["text_muted"]
    clus = item.get("cluster") or {}
    sizes = clus.get("sizes") or []
    top = max((n for n, _ in sizes), default=1)
    text = f"<span style='color:{muted}'>RS</span> <b>{sig}</b>"
    if method == "ship":
        text += "".join(f"&nbsp;&nbsp;<span style='color:{muted}'>×{n}</span> {sig * n}"
                        for n in range(2, top + 1))
    tip = f"Radar signature of one {rock['name']} rock: {sig}."
    if sizes:
        spread = ", ".join(f"{p:.0f}% ×{n}" for n, p in sizes)
        chance = clus.get("chance", 100)
        tip += (f"\nSpawns in groups of {sizes[0][0]}–{top} ({spread})"
                + (f"; {chance:.0f}% of spawns are groups, the rest single rocks" if chance < 100 else "")
                + ".\nA group scans as the sum of its rocks, so these multiples identify the "
                  "rock type and group size from a distance.")
    return text, tip


class _Loader(QObject):
    loaded = Signal(object)
    progress = Signal(str)
    failed = Signal(str)

    def run(self, channel_root) -> None:
        def work():
            try:
                self.loaded.emit(mining.load(channel_root, self.progress.emit))
            except Exception as exc:  # shown in the view, not fatal
                self.failed.emit(str(exc))
        threading.Thread(target=work, daemon=True).start()


# -- one location --------------------------------------------------------------

class LocationCard(QFrame):
    def __init__(self, loc: dict, method: str, data: dict, picked: list[str],
                 show_system: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("ShipCard")
        rocks, resources = data["rocks"], data["resources"]
        quality = data["quality"]
        items = loc["groups"].get(method, [])

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label(loc["name"], "ShipName"))
        kind = KIND_LABELS.get(loc["kind"], loc["kind"].title())
        if loc["parent"] and loc["kind"] in ("moon", "lagrange"):
            kind += f" · {loc['parent']}"
        head.addWidget(_label(kind.upper(), "ShipTier"))
        if show_system:
            head.addWidget(_label(loc["system"].upper(), "ShipTier"))
        head.addStretch(1)
        v.addLayout(head)

        # How likely a random rock here is to carry each picked resource.
        for res in picked:
            share = sum(i["chance"] for i in items
                        if any(p["res"] == res for p in rocks[i["rock"]]["parts"]))
            v.addWidget(_label(
                f"<b>{resources[res]['name']}</b> in {_pct(share)} of rocks here",
                "ShipMatch",
                tip="Sum of the spawn chances of every rock type below that contains it",
            ))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        row = 0
        for item in items:
            rock = rocks[item["rock"]]
            hits = [p for p in rock["parts"] if p["res"] in picked]
            lit = bool(hits) or not picked
            style = "SalvageCell" if lit else "SalvageDim"

            grid.addWidget(_Bar(item["chance"], bool(hits)), row, 0, Qt.AlignVCenter)
            grid.addWidget(_label(_pct(item["chance"]), "MiningChance" if hits else style,
                                  tip="Chance that a rock spawned here is this type",
                                  align=Qt.AlignRight | Qt.AlignVCenter), row, 1)
            name = rock["name"] + (" asteroid" if rock["asteroid"] else "")
            name_lbl = _label(name, "MiningRockHit" if hits else style,
                              tip=self._composition_tip(rock, resources))
            grid.addWidget(name_lbl, row, 2)
            if rock["rarity"]:
                rarity = _label(rock["rarity"].upper(), "MiningRarity")
                rarity.setStyleSheet(f"color: {RARITY_COLORS.get(rock['rarity'], '#9a958c')};")
                grid.addWidget(rarity, row, 3)
            row += 1

            sig_text, sig_tip = _signature_line(rock, item, method)
            if sig_text:
                sig = _label(sig_text, "MiningSignature" if lit else "MiningSignatureDim", tip=sig_tip)
                grid.addWidget(sig, row, 2, 1, 3)
                row += 1

            for part in hits:
                q = quality.get(part["res"], {}).get(loc["system"], {}).get(str(part["scale"]))
                amount = f"avg {_pct(part['avg'])}"
                rng = f"{part['min']:g}–{part['max']:g}%"
                if part["prob"] < 1:
                    rng += f", in {part['prob'] * 100:.0f}% of rocks"
                detail = QHBoxLayout()
                detail.setSpacing(10)
                vein = _label(f"↳ {resources[part['res']]['name']}", "MiningPart")
                vein.setMinimumWidth(110)
                detail.addWidget(vein)
                detail.addWidget(_label(amount, "MiningAmount",
                                        tip="Average share of the rock's mass"))
                detail.addWidget(_label(f"({rng})", "InspectorHint"))
                if q is not None:
                    tip = _quality_tip(resources[part["res"]]["name"], q)
                    detail.addWidget(_label(f"Q ≈ {q['avg']}", "MiningQuality", tip=tip))
                    hist = _QualityHist(q["dist"])
                    hist.setToolTip(tip)
                    detail.addWidget(hist)
                detail.addStretch(1)
                grid.addLayout(detail, row, 2, 1, 3)
                row += 1
        grid.setColumnStretch(4, 1)
        v.addLayout(grid)

    @staticmethod
    def _composition_tip(rock: dict, resources: dict) -> str:
        lines = ["Composition:"]
        for p in rock["parts"]:
            lines.append(f"  {resources.get(p['res'], {}).get('name', p['res'])}: "
                         f"{p['min']:g}–{p['max']:g}% (avg {p['avg']:g}%)")
        return "\n".join(lines)


# -- the view ------------------------------------------------------------------------

class MiningView(QWidget):
    back_requested = Signal()

    def __init__(self, channel: str, parent=None):
        super().__init__(parent)
        self.paths = channel_mod.resolve_channel_paths(settings.current().game_root, channel)
        self.data: dict | None = None
        self.system: str | None = None   # None = all systems
        self.method = "ship"
        self.picked: list[str] = []

        self._loader = _Loader(self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.progress.connect(self._show_message)
        self._loader.failed.connect(
            lambda msg: self._show_message(f"Couldn't read Star Citizen's game data:\n\n{msg}"))
        self._columns = 2
        self._build_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wanted = 2 if self.scroll.viewport().width() >= 1000 else 1
        if wanted != self._columns:
            self._columns = wanted
            self._render()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 20)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        back = QPushButton("←  Back", objectName="ToolButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        bar.addWidget(back)
        bar.addSpacing(10)
        bar.addWidget(QLabel("SYSTEM", objectName="ConfigLabel"))
        self.system_bar = QHBoxLayout()
        self.system_bar.setSpacing(0)
        self.system_group = QButtonGroup(self)
        bar.addLayout(self.system_bar)
        bar.addSpacing(10)
        bar.addWidget(QLabel("MINING", objectName="ConfigLabel"))
        self.method_group = QButtonGroup(self)
        methods = list(mining.METHOD_LABELS.items())
        for i, (key, label) in enumerate(methods):
            btn = self._segment(label, i, len(methods))
            btn.setChecked(key == self.method)
            btn.clicked.connect(lambda _c=False, k=key: self._set_method(k))
            self.method_group.addButton(btn)
            bar.addWidget(btn)
        bar.addStretch(1)
        self.result_label = QLabel("", objectName="InspectorHint")
        bar.addWidget(self.result_label)
        outer.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(14)

        side = QFrame(objectName="SidePanel")
        side.setFixedWidth(270)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 14, 14, 14)
        sv.setSpacing(8)
        sv.addWidget(_label("RESOURCES", "SectionLabel"))
        self.search = QLineEdit(objectName="SearchField")
        self.search.setPlaceholderText("Search…")
        self.search.textChanged.connect(self._filter_list)
        sv.addWidget(self.search)
        self.res_list = QListWidget(objectName="ActionList")
        self.res_list.itemChanged.connect(self._on_item_changed)
        sv.addWidget(self.res_list, stretch=1)
        self.clear_btn = QPushButton("Clear selection", objectName="MiniButton")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear)
        sv.addWidget(self.clear_btn)
        legend = _label(
            "<b>Bar / %</b> — chance a rock spawned here is that type.<br>"
            "<b>avg %</b> — average share of the rock that is the resource (range in brackets).<br>"
            "<b>RS</b> — radar signature of one rock, then the totals for groups of 2, 3… "
            "rocks (a group scans as the sum).<br>"
            "<b>Q</b> — estimated average quality, 0–1000; the small bars show the chance of "
            "each possible quality (hover for exact numbers).<br>"
            "Many rocks hold the same resource twice: a large low-grade share and a small "
            "high-grade one — both are listed.<br>"
            "Picking several resources shows places that have all of them, "
            "not necessarily in the same rock.",
            "InspectorHint")
        legend.setWordWrap(True)
        sv.addWidget(legend)
        body.addWidget(side)

        self.scroll = QScrollArea(objectName="InspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        body.addWidget(self.scroll, stretch=1)
        outer.addLayout(body, stretch=1)
        self._show_message("Loading mining data…")

    @staticmethod
    def _segment(text: str, index: int, count: int) -> QPushButton:
        btn = QPushButton(text, objectName="Segment")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        if index == 0:
            btn.setProperty("pos", "first")
        if index == count - 1:
            btn.setProperty("pos", "last")
        return btn

    # -- lifecycle -------------------------------------------------------------------
    def activate(self) -> None:
        if self.data is None:
            self._loader.run(self.paths.channel_root)

    def deactivate(self) -> None:
        pass

    def _on_loaded(self, data: dict) -> None:
        self.data = data
        options = [(None, "All")] + [(s["id"], s["name"]) for s in data["systems"]]
        for i, (key, label) in enumerate(options):
            btn = self._segment(label, i, len(options))
            btn.setChecked(key == self.system)
            btn.clicked.connect(lambda _c=False, k=key: self._set_system(k))
            self.system_group.addButton(btn)
            self.system_bar.addWidget(btn)
        self._fill_list()
        self._render()

    # -- filters ----------------------------------------------------------------------
    def _set_system(self, system: str | None) -> None:
        self.system = system
        self._fill_list()
        self._render()

    def _set_method(self, method: str) -> None:
        self.method = method
        self._fill_list()
        self._render()

    def _locations(self) -> list[dict]:
        return [l for l in self.data["locations"]
                if (self.system is None or l["system"] == self.system) and self.method in l["groups"]]

    def _fill_list(self) -> None:
        """Only resources that can actually be found with the current system
        and method, each with how many locations have it.
        """
        counts: dict[str, int] = {}
        for loc in self._locations():
            found = {p["res"] for i in loc["groups"][self.method]
                     for p in self.data["rocks"][i["rock"]]["parts"]}
            for res in found:
                counts[res] = counts.get(res, 0) + 1
        self.picked = [r for r in self.picked if r in counts]
        self.res_list.blockSignals(True)
        self.res_list.clear()
        for res in sorted(counts, key=lambda r: self.data["resources"][r]["name"]):
            name = self.data["resources"][res]["name"]
            item = QListWidgetItem(f"{name}   ({counts[res]})")
            item.setData(Qt.UserRole, res)
            item.setToolTip(f"Found at {counts[res]} location(s)")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if res in self.picked else Qt.Unchecked)
            self.res_list.addItem(item)
        self.res_list.blockSignals(False)
        self._filter_list(self.search.text())

    def _filter_list(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.res_list.count()):
            item = self.res_list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        res = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked and res not in self.picked:
            self.picked.append(res)
        elif item.checkState() != Qt.Checked and res in self.picked:
            self.picked.remove(res)
        self._render()

    def _clear(self) -> None:
        self.picked = []
        self._fill_list()
        self._render()

    # -- rendering ------------------------------------------------------------------------
    def _show_message(self, text: str) -> None:
        lbl = QLabel(text, objectName="InspectorHint")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        self.scroll.setWidget(lbl)

    def _share(self, loc: dict, res: str) -> float:
        rocks = self.data["rocks"]
        return sum(i["chance"] for i in loc["groups"][self.method]
                   if any(p["res"] == res for p in rocks[i["rock"]]["parts"]))

    def _render(self) -> None:
        if self.data is None:
            return
        self.clear_btn.setEnabled(bool(self.picked))
        locs = self._locations()
        total = len(locs)
        if self.picked:
            locs = [l for l in locs if all(self._share(l, r) > 0 for r in self.picked)]
            # Best first: the place where the rarest picked resource is most common.
            locs.sort(key=lambda l: -min(self._share(l, r) for r in self.picked))
            names = ", ".join(self.data["resources"][r]["name"] for r in self.picked)
            self.result_label.setText(f"{len(locs)} of {total} locations have {names}")
        else:
            self.result_label.setText(f"{total} locations — pick resources on the left to search")

        page = QWidget(objectName="Inspector")
        page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        cols = QHBoxLayout(page)
        cols.setContentsMargins(0, 0, 8, 0)
        cols.setSpacing(10)
        columns, heights = [], []
        for _ in range(self._columns):
            col = QVBoxLayout()
            col.setSpacing(10)
            cols.addLayout(col, stretch=1)
            columns.append(col)
            heights.append(0)
        if not locs:
            columns[0].addWidget(_label("No location has all of the picked resources.",
                                        "InspectorHint", align=Qt.AlignCenter))
        for loc in locs:
            card = LocationCard(loc, self.method, self.data, self.picked, self.system is None)
            i = heights.index(min(heights))  # masonry: shortest column first
            columns[i].addWidget(card)
            heights[i] += card.sizeHint().height() + 10
        for col in columns:
            col.addStretch(1)
        keep = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(page)
        self.scroll.verticalScrollBar().setValue(keep)
