"""Compact ("minimised") layouts of SC-Toolkit's tools for the in-game
overlay. They're narrow widgets over the same data code as the full views
(app.maps / app.mining / app.salvage) and reuse their helpers; only the
layout differs.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, maps, mining, salvage, settings
from app.theme import PALETTE
from app.ui.maps_view import ZOOM_STEP, ZoomView, _cache_path, _ImageLoader
from app.ui.mining_view import _QualityHist, _pct, _quality_tip, _signature_line
from app.ui.salvage_view import _better_option, _money


def _label(text: str, name: str = "SalvageCell", tip: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text, objectName=name)
    lbl.setWordWrap(wrap)
    if tip:
        lbl.setToolTip(tip)
    return lbl


def _combo(min_width: int = 0) -> QComboBox:
    combo = QComboBox(objectName="ConfigCombo")
    combo.setMaxVisibleItems(20)
    if min_width:
        combo.setMinimumWidth(min_width)
    combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return combo


def _channel_root():
    root = settings.current().game_root
    ch = channel_mod.pick_default_channel(root)
    return channel_mod.resolve_channel_paths(root, ch).channel_root if ch else None


class _Task(QObject):
    """Runs a function off the GUI thread; emits done(result) / failed(msg)."""

    done = Signal(object)
    failed = Signal(str)

    def run(self, fn) -> None:
        def work():
            try:
                self.done.emit(fn())
            except Exception as exc:
                self.failed.emit(str(exc))
        threading.Thread(target=work, daemon=True).start()


class _ScrollPanel(QWidget):
    """Controls on top, a scrollable page below that is rebuilt on each render."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        self.scroll = QScrollArea(objectName="InspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)

    def _add_scroll(self) -> None:
        self.layout_.addWidget(self.scroll, stretch=1)

    def _new_page(self) -> QVBoxLayout:
        page = QWidget(objectName="Inspector")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(6)
        self.scroll.setWidget(page)
        return v

    def _message(self, text: str) -> None:
        v = self._new_page()
        lbl = _label(text, "InspectorHint", wrap=True)
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl, stretch=1)


# -- Maps -----------------------------------------------------------------------

class MapsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._loader = _ImageLoader(self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(lambda url, msg: url == self._wanted and self._msg(f"Couldn't load:\n{msg}"))
        self._wanted: str | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.guide = _combo()
        for title, pages, source in maps.GUIDES:
            self.guide.addItem(title, pages)
        self.guide.currentIndexChanged.connect(self._on_guide)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.guide, stretch=1)
        for text, slot in (("−", lambda: self.viewer.zoom_by(1 / ZOOM_STEP)),
                           ("Fit", lambda: self.viewer.fit()),
                           ("+", lambda: self.viewer.zoom_by(ZOOM_STEP))):
            btn = QPushButton(text, objectName="MiniButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        v.addLayout(row)
        self.page = _combo()   # only shown for guides with several pages
        self.page.currentIndexChanged.connect(self._on_page)
        v.addWidget(self.page)

        frame = QFrame(objectName="MapFrame")
        stack = QStackedLayout(frame)
        stack.setStackingMode(QStackedLayout.StackAll)
        self.viewer = ZoomView()
        self.message = QLabel("", objectName="InspectorHint")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setAttribute(Qt.WA_TransparentForMouseEvents)
        stack.addWidget(self.viewer)
        stack.addWidget(self.message)
        stack.setCurrentWidget(self.message)
        v.addWidget(frame, stretch=1)
        v.addWidget(_label("Community guides by Mr Kraken, all credit to the author.", "InspectorHint"))

    def activate(self) -> None:
        if self._wanted is None:
            self._on_guide(self.guide.currentIndex())

    def _on_guide(self, index: int) -> None:
        pages = self.guide.itemData(index) or []
        self.page.blockSignals(True)
        self.page.clear()
        for label, url in pages:
            self.page.addItem(label, url)
        self.page.blockSignals(False)
        self.page.setVisible(len(pages) > 1)
        self._on_page(0)

    def _on_page(self, index: int) -> None:
        url = self.page.itemData(index)
        if url:
            self._wanted = url
            self._msg("" if _cache_path(url).is_file() else "Loading…")
            self._loader.load(url)

    def _msg(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _on_loaded(self, url: str, data: bytes) -> None:
        from PySide6.QtGui import QPixmap

        if url != self._wanted:
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            self._msg("")
            self.viewer.set_pixmap(pix)
        else:
            self._msg("Couldn't read this image.")


# -- Mining ---------------------------------------------------------------------

class MiningPanel(_ScrollPanel):
    """Pick one resource → the best places to find it, with the rock types
    that carry it: spawn %, radar signatures, avg share and quality."""

    MAX_LOCATIONS = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: dict | None = None
        v = self.layout_
        self.resource = _combo()
        self.resource.currentIndexChanged.connect(self._render)
        v.addWidget(self.resource)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.method = _combo()
        for key, label in mining.METHOD_LABELS.items():
            self.method.addItem(label, key)
        self.method.currentIndexChanged.connect(self._fill_resources)
        row.addWidget(self.method)
        self.system = _combo()
        self.system.currentIndexChanged.connect(self._fill_resources)
        row.addWidget(self.system)
        v.addLayout(row)
        self._add_scroll()
        self._task = _Task(self)
        self._task.done.connect(self._on_loaded)
        self._task.failed.connect(lambda msg: self._message(f"Couldn't read the game data:\n{msg}"))
        self._message("Loading mining data…")

    def activate(self) -> None:
        if self.data is None:
            root = _channel_root()
            if root is None:
                self._message("Set up your Star Citizen folder in the launcher first.")
                return
            self._task.run(lambda: mining.load(root))

    def _on_loaded(self, data: dict) -> None:
        self.data = data
        self.system.blockSignals(True)
        self.system.addItem("All systems", None)
        for s in data["systems"]:
            self.system.addItem(s["name"], s["id"])
        self.system.blockSignals(False)
        self._fill_resources()

    def _locations(self) -> list[dict]:
        method, system = self.method.currentData(), self.system.currentData()
        return [l for l in self.data["locations"]
                if method in l["groups"] and (system is None or l["system"] == system)]

    def _fill_resources(self) -> None:
        if self.data is None:
            return
        method = self.method.currentData()
        found = {p["res"] for l in self._locations() for i in l["groups"][method]
                 for p in self.data["rocks"][i["rock"]]["parts"]}
        current = self.resource.currentData()
        self.resource.blockSignals(True)
        self.resource.clear()
        self.resource.addItem("Pick a resource…", None)
        for res in sorted(found, key=lambda r: self.data["resources"][r]["name"]):
            self.resource.addItem(self.data["resources"][res]["name"], res)
        idx = self.resource.findData(current)
        self.resource.setCurrentIndex(max(idx, 0))
        self.resource.blockSignals(False)
        self._render()

    def _render(self) -> None:
        if self.data is None:
            return
        res = self.resource.currentData()
        if res is None:
            self._message("Pick a resource to see where to find it.")
            return
        method = self.method.currentData()
        rocks, quality = self.data["rocks"], self.data["quality"]

        def share(loc):
            return sum(i["chance"] for i in loc["groups"][method]
                       if any(p["res"] == res for p in rocks[i["rock"]]["parts"]))

        locs = sorted((l for l in self._locations() if share(l) > 0), key=lambda l: -share(l))
        body = self._new_page()
        name = self.data["resources"][res]["name"]
        body.addWidget(_label(f"{len(locs)} locations with {name}, best first", "InspectorHint"))
        for loc in locs[: self.MAX_LOCATIONS]:
            card = QFrame(objectName="ShipCard")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(10, 8, 10, 8)
            cv.setSpacing(2)
            head = QHBoxLayout()
            head.addWidget(_label(loc["name"], "ShipName"))
            head.addStretch(1)
            head.addWidget(_label(f"{_pct(share(loc))} of rocks", "MiningChance"))
            cv.addLayout(head)
            for item in loc["groups"][method]:
                rock = rocks[item["rock"]]
                hits = [p for p in rock["parts"] if p["res"] == res]
                if not hits:
                    continue
                title = rock["name"] + (" asteroid" if rock["asteroid"] else "")
                cv.addWidget(_label(f"{_pct(item['chance'])}  {title}", "MiningRockHit"))
                sig, sig_tip = _signature_line(rock, item, method)
                if sig:
                    cv.addWidget(_label(sig, "MiningSignature", tip=sig_tip))
                for part in hits:
                    q = quality.get(res, {}).get(loc["system"], {}).get(str(part["scale"]))
                    line = QHBoxLayout()
                    line.setSpacing(8)
                    line.addWidget(_label(f"↳ avg {_pct(part['avg'])}", "MiningAmount"))
                    line.addWidget(_label(f"({part['min']:g}–{part['max']:g}%)", "InspectorHint"))
                    if q is not None:
                        tip = _quality_tip(name, q)
                        line.addWidget(_label(f"Q ≈ {q['avg']}", "MiningQuality", tip=tip))
                        hist = _QualityHist(q["dist"])
                        hist.setToolTip(tip)
                        line.addWidget(hist)
                    line.addStretch(1)
                    cv.addLayout(line)
            body.addWidget(card)
        if len(locs) > self.MAX_LOCATIONS:
            body.addWidget(_label(
                f"+{len(locs) - self.MAX_LOCATIONS} more in the launcher's Mining Finder", "InspectorHint"))
        body.addStretch(1)


# -- Salvage ------------------------------------------------------------------------

class SalvagePanel(_ScrollPanel):
    """Pick a claim difficulty and a ship → net value, what comes off it
    (sell vs dismantle), and cargo aboard. Uses the prices downloaded by the
    launcher's Salvage Claims view (no network access from the overlay)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game: dict | None = None
        v = self.layout_
        row = QHBoxLayout()
        row.setSpacing(6)
        self.tier = _combo()
        self.tier.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.tier.setMinimumWidth(120)
        self.tier.currentIndexChanged.connect(self._fill_ships)
        row.addWidget(self.tier)
        self.ship = _combo()
        self.ship.currentIndexChanged.connect(self._render)
        row.addWidget(self.ship, stretch=2)
        v.addLayout(row)
        self._add_scroll()
        self._task = _Task(self)
        self._task.done.connect(self._on_loaded)
        self._task.failed.connect(lambda msg: self._message(f"Couldn't read the game data:\n{msg}"))
        self._rows: list = []
        self._message("Loading salvage data…")

    def activate(self) -> None:
        if self.game is None:
            root = _channel_root()
            if root is None:
                self._message("Set up your Star Citizen folder in the launcher first.")
                return
            self._task.run(lambda: salvage.load_game_data(root))

    def _on_loaded(self, game: dict) -> None:
        self.game = game
        self.sheet = salvage.load_sheet()
        uex = salvage.load_uex()
        self.prices = uex[1] if uex else {}
        self.tier.blockSignals(True)
        for i, t in enumerate(game["tiers"]):
            self.tier.addItem(t["label"], t["id"])
            self.tier.setItemData(i, f"Claim size: {t['size']}", Qt.ToolTipRole)
        self.tier.setCurrentIndex(max(self.tier.findData("Easy"), 0))
        self.tier.blockSignals(False)
        self._fill_ships()

    def _fill_ships(self) -> None:
        if self.game is None:
            return
        self._rows = salvage.build_rows(self.game, self.tier.currentData(), self.sheet, self.prices)
        self._rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))
        self.ship.blockSignals(True)
        self.ship.clear()
        for r in self._rows:
            suffix = f"  ·  {_money(r.net)}" if r.in_sheet else ""
            self.ship.addItem(r.name + suffix, r.stem)
        self.ship.blockSignals(False)
        self._render()

    def _render(self) -> None:
        row = next((r for r in self._rows if r.stem == self.ship.currentData()), None)
        if row is None:
            return
        body = self._new_page()
        if self.sheet is None:
            body.addWidget(_label(
                "Prices not downloaded yet: open Salvage Claims in the launcher once.",
                "InspectorNote", wrap=True))
        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        for col, (cap, val, name) in enumerate((
            ("FEE", _money(row.fee), "ShipStat"),
            ("COMPONENTS", _money(row.components_value), "ShipStat"),
            ("CARGO", _money(row.cargo_value), "ShipStat"),
            ("NET", _money(row.net) if row.in_sheet else "—", "ShipNet"),
        )):
            stats.addWidget(_label(cap, "ShipCaption"), 0, col)
            stats.addWidget(_label(val, name), 1, col)
        body.addLayout(stats)
        if row.note:
            body.addWidget(_label(row.note, "InspectorNote", wrap=True))

        body.addWidget(_label("COMPONENTS", "SectionLabel"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        marks = {"yes": ("✓", "SalvageYes"), "unlisted": ("?", "SalvageMaybe"), "unknown": ("—", "SalvageNo")}
        for r, c in enumerate(row.components):
            # Same value the ship's total counts: the better of sell / dismantle.
            priced = bool(c.sell or c.dismantle)
            better = _better_option(c) or ("sell" if c.sell else "dismantle" if c.dismantle else None)
            price = _money(c.best) if priced else "—"
            how = better or ""
            style = "SalvageCell" if c.salvageable == "yes" else "SalvageDim"
            mark, mark_style = marks[c.salvageable]
            grid.addWidget(_label(mark, mark_style), r, 0)
            grid.addWidget(_label(f"{c.qty}× {c.name}", style, tip=f"{c.type} · size {c.size} {c.grade}"), r, 1)
            grid.addWidget(_label(price, "SalvageBest" if priced and c.salvageable == "yes" else style), r, 2, Qt.AlignRight)
            grid.addWidget(_label(how, "InspectorHint"), r, 3)
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)

        if row.cargo:
            body.addWidget(_label("CARGO ABOARD", "SectionLabel"))
            cargo = QGridLayout()
            cargo.setHorizontalSpacing(10)
            for r, c in enumerate(row.cargo):
                cargo.addWidget(_label(f"{c.scu} SCU {c.material}"), r, 0)
                cargo.addWidget(_label(_money(c.value), "SalvageCell"), r, 1, Qt.AlignRight)
            cargo.setColumnStretch(0, 1)
            body.addLayout(cargo)
        body.addStretch(1)
