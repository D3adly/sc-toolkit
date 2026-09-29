"""Compact ("minimised") layouts of SC-Toolkit's tools for the in-game
overlay. They're narrow widgets over the same data code as the full views
(app.maps / app.mining / app.salvage) and reuse their helpers; only the
layout differs.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
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
from app.ui.mining_view import QualityChart, _pct, _quality_tip, _signature_line
from app.ui.salvage_view import _Header, _better_option, _money


def _label(text: str, name: str = "SalvageCell", tip: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text, objectName=name)
    lbl.setWordWrap(wrap)
    if tip:
        lbl.setToolTip(tip)
    return lbl


class _InlineCombo(QComboBox):
    """A combo box whose list opens inside the overlay window instead of as a
    popup window. A popup grabs the mouse; over a fullscreen game (XWayland,
    an OSD window) that grab sometimes failed, so the list closed at once and
    the click went to the game."""

    MARGIN = 6

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._list: QListView | None = None

    def showPopup(self) -> None:
        win = self.window()
        if self._list is None:
            lst = QListView(win, objectName="InlineComboList")
            lst.setModel(self.model())
            lst.setEditTriggers(QListView.NoEditTriggers)
            lst.setUniformItemSizes(True)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lst.clicked.connect(self._pick)
            lst.activated.connect(self._pick)
            self._list = lst
        lst = self._list
        lst.setCurrentIndex(self.model().index(self.currentIndex(), self.modelColumn()))
        # Below the combo if the list fits there (or there's more room), else above.
        top = self.mapTo(win, QPoint(0, 0))
        row = lst.sizeHintForRow(0) if self.count() else self.height()
        wanted = min(self.count(), self.maxVisibleItems()) * row + 8
        below = win.height() - (top.y() + self.height()) - self.MARGIN
        above = top.y() - self.MARGIN
        if wanted <= below or below >= above:
            height, y = min(wanted, below), top.y() + self.height() + 2
        else:
            height = min(wanted, above)
            y = top.y() - height - 2
        width = min(max(self.width(), 160), win.width() - 2 * self.MARGIN)
        x = max(self.MARGIN, min(top.x(), win.width() - width - self.MARGIN))
        lst.setGeometry(x, y, width, max(height, row))
        lst.show()
        lst.raise_()
        lst.scrollTo(lst.currentIndex(), QListView.PositionAtCenter)
        lst.setFocus()
        QApplication.instance().installEventFilter(self)

    def hidePopup(self) -> None:
        QApplication.instance().removeEventFilter(self)
        if self._list is not None and self._list.isVisible():
            self._list.hide()
            self.setFocus()

    def _pick(self, index) -> None:
        self.setCurrentIndex(index.row())
        self.hidePopup()

    def eventFilter(self, obj, event):
        # While open: a click anywhere else, or Esc, closes the list.
        if self._list is not None and self._list.isVisible():
            if event.type() == QEvent.MouseButtonPress and isinstance(obj, QWidget):
                if obj is not self._list and not self._list.isAncestorOf(obj):
                    self.hidePopup()
                    if obj is self:
                        return True   # clicking the combo again just closes it
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.hidePopup()
                return True
        return False


def _combo(min_width: int = 0) -> QComboBox:
    combo = _InlineCombo(objectName="ConfigCombo")
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

class _Clickable(QFrame):
    clicked = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        hit = event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint())
        super().mouseReleaseEvent(event)
        if hit:
            # Last: opening a location rebuilds the page and deletes this row.
            self.clicked.emit()


class MiningPanel(_ScrollPanel):
    """Filter by ore, system and mining method → the locations; pick one →
    every rock type that spawns there: spawn chance, radar signatures and,
    per resource, its share range and a chart of the quality odds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: dict | None = None
        self.location: str | None = None     # id of the opened location
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

    # -- filters ------------------------------------------------------------------
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
        self.resource.addItem("Any ore", None)
        for res in sorted(found, key=lambda r: self.data["resources"][r]["name"]):
            self.resource.addItem(self.data["resources"][res]["name"], res)
        self.resource.setCurrentIndex(max(self.resource.findData(current), 0))
        self.resource.blockSignals(False)
        self._render()

    def _share(self, loc: dict, res: str) -> float:
        """% of this method's spawns at loc that are rocks carrying res."""
        rocks = self.data["rocks"]
        return sum(i["chance"] for i in loc["groups"][self.method.currentData()]
                   if any(p["res"] == res for p in rocks[i["rock"]]["parts"]))

    def _render(self) -> None:
        if self.data is None:
            return
        locs = {l["id"]: l for l in self._locations()}
        if self.location in locs:
            self._render_location(locs[self.location])
        else:
            self.location = None
            self._render_list(list(locs.values()))

    def _open(self, loc_id: str | None) -> None:
        self.location = loc_id
        self._render()
        self.scroll.verticalScrollBar().setValue(0)

    # -- page 1: locations -------------------------------------------------------------
    def _render_list(self, locs: list[dict]) -> None:
        res = self.resource.currentData()
        method = self.method.currentData()
        if res is not None:
            locs = sorted((l for l in locs if self._share(l, res) > 0), key=lambda l: -self._share(l, res))
        body = self._new_page()
        if res is not None:
            name = self.data["resources"][res]["name"]
            hint = f"{len(locs)} locations with {name}, most first. Click one for its rocks."
        else:
            hint = f"{len(locs)} locations. Click one for its rocks."
        body.addWidget(_label(hint, "InspectorHint", wrap=True))
        systems = {s["id"]: s["name"] for s in self.data["systems"]}
        for loc in locs:
            row = _Clickable(objectName="ShipHeader")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 10, 6)
            h.setSpacing(8)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(_label(loc["name"], "ShipName"))
            where = ", ".join(filter(None, [loc.get("parent") or "", systems.get(loc["system"], "")]))
            col.addWidget(_label(where or loc["kind"].title(), "InspectorHint"))
            h.addLayout(col, stretch=1)
            if res is not None:
                h.addWidget(_label(f"{_pct(self._share(loc, res))} of rocks", "MiningChance"))
            else:
                h.addWidget(_label(f"{len(loc['groups'][method])} rock types", "InspectorHint"))
            h.addWidget(_label("›", "ShipArrow"))
            row.clicked.connect(lambda lid=loc["id"]: self._open(lid))
            body.addWidget(row)
        body.addStretch(1)

    # -- page 2: one location's rocks ------------------------------------------------
    def _render_location(self, loc: dict) -> None:
        res = self.resource.currentData()
        method = self.method.currentData()
        rocks, quality, names = self.data["rocks"], self.data["quality"], self.data["resources"]
        body = self._new_page()
        top = QHBoxLayout()
        back = QPushButton("‹ Locations", objectName="MiniButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self._open(None))
        top.addWidget(back)
        top.addWidget(_label(loc["name"], "ShipName"), stretch=1)
        body.addLayout(top)
        body.addWidget(_label(
            f"{mining.METHOD_LABELS[method]} mining: every rock type that spawns here, by spawn chance. "
            "Quality odds are estimated from the game's settings.", "InspectorHint", wrap=True))
        for item in loc["groups"][method]:
            rock = rocks[item["rock"]]
            carries = res is not None and any(p["res"] == res for p in rock["parts"])
            card = QFrame(objectName="ShipCard")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(10, 8, 10, 8)
            cv.setSpacing(3)
            head = QHBoxLayout()
            title = rock["name"] + (" asteroid" if rock["asteroid"] else "")
            head.addWidget(_label(title, "MiningRockHit" if carries else "ShipName"))
            if rock.get("rarity"):
                head.addWidget(_label(rock["rarity"].upper(), "ShipTier"))
            head.addStretch(1)
            head.addWidget(_label(f"{_pct(item['chance'])} of spawns", "MiningChance"))
            cv.addLayout(head)
            sig, sig_tip = _signature_line(rock, item, method)
            if sig:
                cv.addWidget(_label(sig, "MiningSignature", tip=sig_tip))
            for part in rock["parts"]:
                name = names.get(part["res"], {}).get("name", part["res"])
                line = QHBoxLayout()
                line.setSpacing(8)
                style = "MiningRockHit" if part["res"] == res else "SalvageCell"
                line.addWidget(_label(name, style))
                line.addWidget(_label(f"{part['min']:g}–{part['max']:g}%", "MiningAmount"))
                if part["prob"] < 1:
                    line.addWidget(_label(f"in {_pct(100 * part['prob'])} of rocks", "InspectorHint"))
                line.addStretch(1)
                cv.addLayout(line)
                q = quality.get(part["res"], {}).get(loc["system"], {}).get(str(part["scale"]))
                if q is not None and q["dist"]:
                    chart = QualityChart(q["dist"])
                    chart.setToolTip(_quality_tip(name, q))
                    cv.addWidget(chart)
            body.addWidget(card)
        body.addStretch(1)


# -- Salvage ------------------------------------------------------------------------

class _ShipItem(QFrame):
    """One ship in the salvage accordion: a header (name, net value) that
    opens the details underneath."""

    toggled = Signal(str)

    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setObjectName("ShipCard")
        self.row = row
        self._detail: QWidget | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = _Header(objectName="ShipHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.clicked.connect(lambda: self.toggled.emit(row.stem))
        h = QHBoxLayout(self.header)
        h.setContentsMargins(10, 7, 10, 7)
        h.setSpacing(8)
        self.arrow = _label("▸", "ShipArrow")
        h.addWidget(self.arrow)
        h.addWidget(_label(row.name, "ShipName"), stretch=1)
        h.addWidget(_label(_money(row.net), "ShipNet") if row.in_sheet else _label("no data", "ShipMuted"))
        v.addWidget(self.header)

    def set_open(self, on: bool) -> None:
        self.header.setProperty("open", on)
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)
        self.arrow.setText("▾" if on else "▸")
        if on and self._detail is None:
            self._detail = _ship_detail(self.row)
            self.layout().addWidget(self._detail)
        if self._detail is not None:
            self._detail.setVisible(on)


def _ship_detail(row) -> QWidget:
    body = QWidget(objectName="ShipDetail")
    v = QVBoxLayout(body)
    v.setContentsMargins(12, 4, 10, 10)
    v.setSpacing(6)
    stats = QGridLayout()
    stats.setHorizontalSpacing(12)
    for col, (cap, val) in enumerate((("FEE", _money(row.fee)),
                                      ("COMPONENTS", _money(row.components_value)),
                                      ("CARGO", _money(row.cargo_value)))):
        stats.addWidget(_label(cap, "ShipCaption"), 0, col)
        stats.addWidget(_label(val, "ShipStat"), 1, col)
    v.addLayout(stats)
    if row.note:
        v.addWidget(_label(row.note, "InspectorNote", wrap=True))

    v.addWidget(_label("COMPONENTS", "SectionLabel"))
    grid = QGridLayout()
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(2)
    marks = {"yes": ("✓", "SalvageYes"), "unlisted": ("?", "SalvageMaybe"), "unknown": ("—", "SalvageNo")}
    for r, c in enumerate(row.components):
        # Same value the ship's total counts: the better of sell / dismantle.
        priced = bool(c.sell or c.dismantle)
        better = _better_option(c) or ("sell" if c.sell else "dismantle" if c.dismantle else None)
        style = "SalvageCell" if c.salvageable == "yes" else "SalvageDim"
        mark, mark_style = marks[c.salvageable]
        grid.addWidget(_label(mark, mark_style), r, 0)
        grid.addWidget(_label(f"{c.qty}× {c.name}", style, tip=f"{c.type} · size {c.size} {c.grade}"), r, 1)
        grid.addWidget(_label(_money(c.best) if priced else "—",
                              "SalvageBest" if priced and c.salvageable == "yes" else style), r, 2, Qt.AlignRight)
        grid.addWidget(_label(better or "", "InspectorHint"), r, 3)
    grid.setColumnStretch(1, 1)
    v.addLayout(grid)

    if row.cargo:
        v.addWidget(_label("CARGO ABOARD", "SectionLabel"))
        cargo = QGridLayout()
        cargo.setHorizontalSpacing(10)
        for r, c in enumerate(row.cargo):
            cargo.addWidget(_label(f"{c.scu} SCU {c.material}"), r, 0)
            cargo.addWidget(_label(_money(c.value), "SalvageCell"), r, 1, Qt.AlignRight)
        cargo.setColumnStretch(0, 1)
        v.addLayout(cargo)
    return body


class SalvagePanel(_ScrollPanel):
    """Pick a claim difficulty → its ships as an accordion (name and net
    value; click for fee, what comes off it (sell vs dismantle) and cargo).
    Uses the prices downloaded by the launcher's Salvage Claims view (no
    network access from the overlay)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game: dict | None = None
        self.opened: str | None = None       # stem of the open ship
        self._items: dict[str, _ShipItem] = {}
        v = self.layout_
        self.tier = _combo()
        self.tier.currentIndexChanged.connect(self._fill_ships)
        v.addWidget(self.tier)
        self._add_scroll()
        self._task = _Task(self)
        self._task.done.connect(self._on_loaded)
        self._task.failed.connect(lambda msg: self._message(f"Couldn't read the game data:\n{msg}"))
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
            self.tier.addItem(f"{t['label']}  ·  claim size {t['size']}", t["id"])
        self.tier.setCurrentIndex(max(self.tier.findData("Easy"), 0))
        self.tier.blockSignals(False)
        self._fill_ships()

    def _fill_ships(self) -> None:
        if self.game is None:
            return
        rows = salvage.build_rows(self.game, self.tier.currentData(), self.sheet, self.prices)
        rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))
        body = self._new_page()
        if self.sheet is None:
            body.addWidget(_label(
                "Prices not downloaded yet: open Salvage Claims in the launcher once.",
                "InspectorNote", wrap=True))
        body.addWidget(_label(f"{len(rows)} ships, most valuable first. Click one for details.",
                              "InspectorHint"))
        self._items = {}
        for row in rows:
            item = _ShipItem(row)
            item.toggled.connect(self._toggle)
            self._items[row.stem] = item
            body.addWidget(item)
        body.addStretch(1)
        if self.opened in self._items:
            self._items[self.opened].set_open(True)
        else:
            self.opened = None

    def _toggle(self, stem: str) -> None:
        """Accordion: one ship open at a time."""
        if self.opened in self._items:
            self._items[self.opened].set_open(False)
        self.opened = None if stem == self.opened else stem
        if self.opened:
            item = self._items[self.opened]
            item.set_open(True)
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(item.header, 0, 0))
