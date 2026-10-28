"""Loadouts in My Ships (design: Loadouts canvas, "V-Launcher" with the
website's full editing, "B2-Bus"): the ship's banner with its loadouts and
totals, the power ring and the bus of parts, and the swap tray. The same
editor as on sc-toolbox.com (app.loadoutmodel is a port of its model) and
synced with it (app.loadouts, app.sync).

Stock is read-only: changing a part there starts a new loadout. Every change
is saved at once and can be undone (toast, Ctrl+Z). Pointing at a part
previews it on every number; clicking holds the preview; Buy or Craft puts
it on. Compare, craft quality and the shopping list are app.ui.loadout_views.
"""

from __future__ import annotations

import threading
from dataclasses import replace

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QLinearGradient, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from app import hangar, loadouts, loadoutcalc, loadoutmodel as model, portal
from app.loadoutcalc import ceilings, fitted, totals
from app.loadoutmodel import money, show_stat
from app.theme import PALETTE
from app.ui import kit
from app.ui.loadout_parts import BusView, HudStat, PartCardWidget, Toast, draw_tag, icon_pixmap, num_font, tag_width, \
    set_font, ui_font

MAX_CARDS = 12


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    lab = QLabel(text, objectName=name)
    lab.setWordWrap(wrap)
    return lab


# -- the ship banner ----------------------------------------------------------------------------------

class _Hero(QWidget):
    """The ship's picture, darkened towards the left and the bottom so the text over it reads."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: QPixmap | None = None
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_image(self, path: str | None) -> None:
        self.pixmap = QPixmap(path) if path else None
        if self.pixmap is not None and self.pixmap.isNull():
            self.pixmap = None
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.rect()
        path_rect = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        from PySide6.QtGui import QPainterPath
        clip = QPainterPath()
        clip.addRoundedRect(path_rect, 16, 16)
        p.setClipPath(clip)
        p.fillRect(r, QColor("#0f1215"))
        if self.pixmap is not None:
            pm = self.pixmap
            scale = max(r.width() / pm.width(), r.height() / pm.height())
            w, h = pm.width() * scale, pm.height() * scale
            # object-position 50% 42%
            p.drawPixmap(QRectF((r.width() - w) * 0.5, (r.height() - h) * 0.42, w, h), pm, QRectF(pm.rect()))
        side = QLinearGradient(0, 0, r.width(), 0)
        side.setColorAt(0, QColor(7, 9, 11, 242))
        side.setColorAt(0.45, QColor(7, 9, 11, 140))
        side.setColorAt(0.75, QColor(7, 9, 11, 38))
        side.setColorAt(1, QColor(7, 9, 11, 20))
        p.fillRect(r, side)
        bottom = QLinearGradient(0, r.height(), 0, r.height() - 190)
        bottom.setColorAt(0, QColor(11, 13, 16, 242))
        bottom.setColorAt(0.55, QColor(11, 13, 16, 150))
        bottom.setColorAt(1, QColor(11, 13, 16, 0))
        p.fillRect(r, bottom)
        p.setClipping(False)
        p.setPen(QColor(218, 197, 164, 36))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(path_rect, 16, 16)
        p.end()


class _Pill(QPushButton):
    """A loadout tab: its name, SHARED when it has a link, a lock on Stock."""

    def __init__(self, text: str, shared: bool = False, lock: bool = False, parent=None):
        super().__init__(parent, objectName="LoPill")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._text, self._shared, self._lock = text, shared, lock
        self.setAccessibleName(text + (", shared" if shared else ""))
        fm = self.fontMetrics()
        extra = (tag_width("shared") + 2 if shared else 0) + (18 if lock else 0)
        self.setFixedWidth(fm.horizontalAdvance(text) + 26 + extra)

    def paintEvent(self, e):
        super().paintEvent(e)          # the frame (stylesheet)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        colour = "#0b0d10" if self.isChecked() else PALETTE["text_secondary"]
        x = 13
        if self._lock:
            p.drawPixmap(x, (self.height() - 12) // 2, icon_pixmap("lock", colour, 12, self.devicePixelRatioF()))
            x += 18
        p.setPen(QColor(colour))
        p.setFont(self.font())
        tw = self.fontMetrics().horizontalAdvance(self._text)
        p.drawText(QRectF(x, 0, tw + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text)
        if self._shared:
            draw_tag(p, x + tw + 2, (self.height() - 18) / 2, "shared")
        p.end()


# -- background work (share links) ------------------------------------------------------------------

class _Call(QObject):
    done = Signal(object, object)          # result, error

    def run(self, fn) -> None:
        def work():
            try:
                result, error = fn(), None
            except Exception as exc:          # shown on the UI thread
                result, error = None, exc
            self.done.emit(result, error)

        threading.Thread(target=work, daemon=True).start()


# -- the editor -----------------------------------------------------------------------------------------

class LoadoutEditor(QWidget):
    """One ship's loadouts. The hangar view opens it with open_ship(); back_requested goes back to
    the ship grid, info_requested to the ship's stats page."""

    back_requested = Signal()
    info_requested = Signal()
    open_tool = Signal(str, object)        # tool key, target (the Mining Finder link)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sync = None
        self.entry: hangar.Entry | None = None
        self.ship = None                   # app.ships.Ship
        self.ctx: model.Ctx | None = None
        self.version = ""
        self.loadout_id: str | None = None
        self.parts: dict = {}
        self.history: list[dict] = []
        self.sel = ""
        self.side: str | None = None
        self.rack_mode = "racks"
        self.hover: str | None = None
        self.held: str | None = None
        self._stock_rows: list[dict] = []
        self._stock_totals: dict = {}
        self._ceil: dict = {}
        self._view: dict = {}
        self._cards: list[PartCardWidget] = []
        self._call = _Call(self)
        self._call.done.connect(self._on_call_done)
        self._call_then = None
        self._preview_timer = QTimer(self, singleShot=True, interval=40, timeout=self._apply_preview)
        self._build()
        QShortcut(QKeySequence.Undo, self, activated=self.undo, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._escape, context=Qt.WidgetWithChildrenShortcut)

    # -- layout ---------------------------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.scroll = QScrollArea(objectName="LoScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget(objectName="LoPage")
        self.page = page
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 8, 24)
        v.setSpacing(18)

        self.hero = _Hero()
        hv = QVBoxLayout(self.hero)
        hv.setContentsMargins(24, 16, 24, 18)
        hv.setSpacing(6)
        top = QHBoxLayout()
        self.back = QPushButton("←  All my ships", objectName="LoBack")
        self.back.setCursor(Qt.PointingHandCursor)
        self.back.clicked.connect(self.back_requested)
        top.addWidget(self.back)
        self.info_btn = QPushButton("Ship info && stats", objectName="LoBack")
        self.info_btn.setCursor(Qt.PointingHandCursor)
        self.info_btn.clicked.connect(self.info_requested)
        top.addWidget(self.info_btn)
        top.addStretch(1)
        self.sync_chip = _label("", "LoChip")
        self.sync_chip.hide()
        top.addWidget(self.sync_chip)
        self.cta = QPushButton(objectName="LoCta")
        self.cta.setCursor(Qt.PointingHandCursor)
        self.cta.clicked.connect(self.open_shopping)
        top.addWidget(self.cta)
        hv.addLayout(top)
        hv.addSpacing(12)
        title = QHBoxLayout()
        title.setSpacing(12)
        self.name = QLabel(objectName="LoShipName")
        set_font(self.name, num_font(48))
        title.addWidget(self.name, alignment=Qt.AlignBottom)
        self.subtitle = _label("", "LoShipSub")
        set_font(self.subtitle, ui_font(15, QFont.DemiBold))
        title.addWidget(self.subtitle, 1, alignment=Qt.AlignBottom)
        hv.addLayout(title)
        self.pills = QHBoxLayout()
        self.pills.setSpacing(6)
        pill_row = QHBoxLayout()
        pill_row.addLayout(self.pills)
        pill_row.addStretch(1)
        hv.addSpacing(4)
        hv.addLayout(pill_row)
        hv.addSpacing(10)
        hud = QHBoxLayout()
        hud.setSpacing(0)
        self.hud = {key: HudStat(label) for key, label in
                    (("dps", "Firepower"), ("alpha", "Alpha"), ("shieldHp", "Shields"), ("quantumSpeed", "Quantum"))}
        for w in self.hud.values():
            hud.addWidget(w)
        hv.addLayout(hud)
        v.addWidget(self.hero)

        self.patch = QFrame(objectName="LoPatch")
        ph = QHBoxLayout(self.patch)
        ph.setContentsMargins(14, 10, 14, 10)
        self.patch_text = _label("", "BodyText", wrap=True)
        ph.addWidget(self.patch_text)
        self.patch.hide()
        v.addWidget(self.patch)

        self.bus = BusView()
        self.bus.picked.connect(self.select)
        v.addWidget(self.bus)

        line = QFrame(objectName="LoRule")
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: rgba(218, 197, 164, 0.14);")
        v.addWidget(line)

        self.tray = QWidget()
        tv = QVBoxLayout(self.tray)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(12)
        self.rack_tabs = QHBoxLayout()
        self.rack_tabs.setSpacing(8)
        self.rack_tab = QPushButton(objectName="LoRackTab")
        self.missile_tab = QPushButton(objectName="LoRackTab")
        for b, mode in ((self.rack_tab, "racks"), (self.missile_tab, "missiles")):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, mode=mode: self._set_rack_mode(mode))
            self.rack_tabs.addWidget(b)
        self.rack_tabs.addStretch(1)
        self.rack_host = QWidget()
        self.rack_host.setLayout(self.rack_tabs)
        tv.addWidget(self.rack_host)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.tray_port = _label("", "LoTrayPort")
        head.addWidget(self.tray_port, alignment=Qt.AlignVCenter)
        self.tray_name = _label("", "LoTrayName")
        head.addWidget(self.tray_name, alignment=Qt.AlignVCenter)
        self.tray_src = _label("", "LoTraySrc")
        head.addWidget(self.tray_src, alignment=Qt.AlignVCenter)
        self.quality_link = QPushButton("Set quality →", objectName="LoLink")
        self.quality_link.setCursor(Qt.PointingHandCursor)
        self.quality_link.clicked.connect(self.open_craft)
        head.addWidget(self.quality_link)
        head.addStretch(1)
        self.seg_host = QWidget()
        self.seg = QHBoxLayout(self.seg_host)
        self.seg.setContentsMargins(0, 0, 0, 0)
        self.seg.setSpacing(0)
        head.addWidget(self.seg_host)
        self.compare_link = QPushButton(objectName="LoLink")
        self.compare_link.setCursor(Qt.PointingHandCursor)
        self.compare_link.clicked.connect(self.open_compare)
        head.addWidget(self.compare_link)
        tv.addLayout(head)
        self.cards_scroll = QScrollArea(objectName="LoCards")
        self.cards_scroll.setFrameShape(QFrame.NoFrame)
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cards_scroll.setFixedHeight(PartCardWidget(model.Card("", "", "", "stock", "", "", 0, "", "same", "",
                                                                   False, False, False, False, None)).height() + 16)
        self.cards_host = QWidget()
        self.cards_row = QHBoxLayout(self.cards_host)
        self.cards_row.setContentsMargins(0, 0, 0, 0)
        self.cards_row.setSpacing(12)
        self.cards_scroll.setWidget(self.cards_host)
        tv.addWidget(self.cards_scroll)
        self.tray_empty = _label("Nothing else fits this slot.", "LoTraySrc")
        tv.addWidget(self.tray_empty)
        self.tray_hint = _label("", "LoHint", wrap=True)
        tv.addWidget(self.tray_hint)
        v.addWidget(self.tray)
        v.addStretch(1)
        self.scroll.setWidget(page)
        self.stack.addWidget(self.scroll)

        self.message = kit.EmptyState()
        self.stack.addWidget(self.message)
        self.toast = Toast(self)

    # -- opening a ship ------------------------------------------------------------------------------
    def open_ship(self, entry: hangar.Entry, ship, ctx: model.Ctx | None, version: str = "",
                  loadout_id: str | None = None) -> None:
        """Shows a hangar entry's loadouts (ctx None: say why there are none)."""
        same = self.entry is not None and self.entry.id == entry.id and self.ctx is ctx
        self.entry, self.ship, self.ctx, self.version = entry, ship, ctx, version
        if ctx is None:
            return
        if not same:
            self._stock_rows = fitted(ctx.catalog["ship"], ctx.items, {})
            self._stock_totals = totals(self._stock_rows, ctx.items, ctx.recipes, ctx.catalog["ship"].get("basePower"))
            self._ceil = ceilings(ctx.catalog["ship"], self._stock_rows, ctx.items, ctx.recipes, ctx.offers)
            self.sel, self.side, self.rack_mode = "", None, "racks"
        self.stack.setCurrentWidget(self.scroll)
        image = getattr(ship, "image_file", None)
        self.hero.set_image(str(image) if image is not None and image.is_file() else None)
        self._open_loadout(loadout_id if loadout_id is not None else (self.loadout_id if same else None))

    def show_message(self, title: str, text: str) -> None:
        """No editor for this ship (concept, not in the game files, data still loading): why."""
        self.message.set(title, text, "Back to my ships", self.back_requested.emit)
        self.stack.setCurrentWidget(self.message)

    def set_image(self, path: str) -> None:
        self.hero.set_image(path)

    def set_sync_status(self, text: str) -> None:
        self.sync_chip.setText(f"● {text}" if text else "")
        self.sync_chip.setVisible(bool(text))

    def reload(self) -> None:
        """Loadouts changed from online: show them (the open one keeps its place if it's still there)."""
        if self.entry is None or self.ctx is None:
            return
        if self.loadout_id and loadouts.get(self.loadout_id) is None:
            self.loadout_id = None
            self.history = []
        self._open_loadout(self.loadout_id, keep_history=True)

    def _loadouts(self) -> list[loadouts.Loadout]:
        return loadouts.for_ship(self.entry.id) if self.entry else []

    def current(self) -> loadouts.Loadout | None:
        return loadouts.get(self.loadout_id) if self.loadout_id else None

    def _open_loadout(self, loadout_id: str | None, keep_history: bool = False) -> None:
        lo = loadouts.get(loadout_id) if loadout_id else None
        if lo is not None and lo.hangar_id != self.entry.id:
            lo = None
        if (lo.id if lo else None) != self.loadout_id or not keep_history:
            self.history = []
        self.loadout_id = lo.id if lo else None
        self.parts = dict(lo.parts) if lo else {}
        self.hover = self.held = None
        self._refresh()

    # -- what the page shows ------------------------------------------------------------------------
    def _refresh(self) -> None:
        ctx = self.ctx
        if ctx is None or self.entry is None:
            return
        self._view = model.view_of(ctx, self.parts)
        self._render_hero()
        self._render_bus()
        self._render_tray()

    def _render_hero(self) -> None:
        ship_name = self.ship.name if self.ship else self.entry.ship_name
        self.name.setText((self.entry.name or ship_name).upper())
        maker = getattr(self.ship, "manufacturer", "") or ""
        role = (getattr(self.ship, "focus", "") or getattr(self.ship, "role", "") or "").lower()
        first = f"{maker} {ship_name}".strip() if self.entry.name else maker
        self.subtitle.setText(" · ".join(x for x in (first, role, f"stats for build {self.version}" if self.version
                                                       else "") if x))
        kit.clear_layout(self.pills)
        stock = _Pill("Stock", lock=True)
        stock.setChecked(self.loadout_id is None)
        stock.clicked.connect(lambda: self._open_loadout(None))
        self.pills.addWidget(stock)
        for lo in self._loadouts():
            pill = _Pill(lo.name, shared=bool(lo.share))
            pill.setChecked(lo.id == self.loadout_id)
            pill.clicked.connect(lambda _c=False, i=lo.id: self._open_loadout(i))
            self.pills.addWidget(pill)
        new = QPushButton("+ New", objectName="LoPill")
        new.setProperty("kind", "new")
        new.setCursor(Qt.PointingHandCursor)
        new.clicked.connect(self.new_loadout)
        self.pills.addWidget(new)
        if self.loadout_id:
            more = QPushButton("⋯", objectName="LoPill")
            more.setAccessibleName("Loadout actions")
            more.setCursor(Qt.PointingHandCursor)
            more.clicked.connect(lambda: self._menu(more))
            self.pills.addWidget(more)
        self._render_hud(None)
        view = self._view
        self.cta.setVisible(self.loadout_id is not None)
        self.cta.setText(f"Shopping && crafting    {money(view['cost'])} aUEC    {view['craft']} craft")

    def _render_hud(self, preview: dict | None) -> None:
        t, s, c = self._view["totals"], self._stock_totals, self._ceil
        pt = preview["totals"] if preview else None
        shown = pt or t
        self.hud["dps"].set(t["dps"], s["dps"], c.get("dps", 0), pt["dps"] if pt else None,
                            f"burst DPS · best {money(c.get('dps', 0))}")
        self.hud["alpha"].set(t["alpha"], s["alpha"], c.get("alpha", 0), pt["alpha"] if pt else None,
                              f"per volley · best {money(c.get('alpha', 0))}")
        self.hud["shieldHp"].set(t["shieldHp"], s["shieldHp"], c.get("shieldHp", 0), pt["shieldHp"] if pt else None,
                                 f"HP · {money(shown['shieldRegen'])}/s regen")
        q = t["quantumSpeed"] / 1e6 if t["quantumSpeed"] else None
        self.hud["quantumSpeed"].set(q, s["quantumSpeed"] / 1e6, c.get("quantumSpeed", 0) / 1e6,
                                     pt["quantumSpeed"] / 1e6 if pt else None,
                                     f"Mm/s · {shown['quantumCooldown']:g} s cooldown")

    def _node_tag(self, n: model.BusNode) -> str:
        stock_at = {r["path"]: r["item"] for r in self._stock_rows}
        changed = not n.locked and any(stock_at.get(p) != n.item for p in n.paths)
        return model.tag_of(self.ctx, n.item, n.source, n.obsolete, changed)

    def _render_bus(self) -> None:
        nodes = self._view["nodes"]
        obsolete = sum(1 for r in self._view["rows"] if r["obsolete"])
        self.patch.setVisible(bool(obsolete))
        if obsolete:
            one = obsolete == 1
            self.patch_text.setText(
                f"<b style='color:{PALETTE['warning']}'>GAME UPDATE {self.version}</b>&nbsp;&nbsp; {obsolete} "
                f"{'part' if one else 'parts'} in this loadout left the game. {'It' if one else 'They'}'re out "
                f"of the stats until you replace {'it' if one else 'them'}.")
        self.bus.set_nodes(nodes, {n.id: self._node_tag(n) for n in nodes})
        self._update_ring(None)
        sel = self.selected()
        self.bus.set_selected(sel.id if sel else None, self.side)

    def _update_ring(self, preview: dict | None) -> None:
        view = preview or self._view
        t = view["totals"]
        sel = self.selected()
        self.bus.ring.set(t["segments"], t["powerMin"], t["powerMax"], [(n.id, n.draw) for n in view["nodes"]],
                          (self.ctx.catalog["ship"].get("basePower") or {}).get("max", 0), sel.id if sel else "")

    def selected(self) -> model.BusNode | None:
        nodes = self._view.get("nodes") or []
        return (next((n for n in nodes if n.id == self.sel), None)
                or next((n for n in nodes if self.sel in n.paths), None) or (nodes[0] if nodes else None))

    def select(self, node_id: str, slot: str | None = None) -> None:
        """Picks a node on the bus: all its slots, or (`slot`) just one of them."""
        if self.sel != node_id:
            self.rack_mode = "racks"
        self.sel = node_id
        self.hover = self.held = None
        self.side = slot
        sel = self.selected()
        self.bus.set_selected(sel.id if sel else None, self.side)
        self._update_ring(None)
        self._render_hud(None)
        self._render_tray()

    # -- the tray ----------------------------------------------------------------------------------------
    def missile_mode(self) -> bool:
        n = self.selected()
        return bool(n) and n.kind == "rack" and (n.locked or self.rack_mode == "missiles")

    def targets(self) -> list[str]:
        """The slots a fit goes to: the node's (or the one side picked), or its racks' missile slots."""
        n = self.selected()
        if n is None:
            return []
        paths = [self.side] if self.side and self.side in n.paths else n.paths
        if self.missile_mode():
            return [m for m in n.missile_paths if any(m.startswith(p + "/") for p in paths)]
        return paths

    def tray_kind(self) -> str:
        n = self.selected()
        return "missile" if self.missile_mode() else (n.kind if n else "other")

    def fitted_row(self) -> dict | None:
        targets = self.targets()
        return next((r for r in self._view["rows"] if targets and r["path"] == targets[0]), None)

    def stock_item(self, path: str) -> str:
        return next((r["item"] for r in self._stock_rows if r["path"] == path), "")

    def choices(self) -> list[str]:
        """What fits the open slots and can be got (bought or crafted); the fitted part and stock stay."""
        targets = self.targets()
        row = self.fitted_row()
        keep = {(row or {}).get("item") or "", self.stock_item(targets[0]) if targets else ""}
        return [c for c in model.choices_for(self.ctx, self._view["rows"], targets)
                if c in keep or model.obtainable(self.ctx, c)]

    def cards(self, choices: list[str]) -> list[model.Card]:
        ctx, kind = self.ctx, self.tray_kind()
        targets = self.targets()
        if not targets:
            return []
        row = self.fitted_row() or {}
        fitted_item = row.get("item") or ""
        fitted_value = model.stat_of(kind, ctx, fitted_item, row.get("source") or "stock", row.get("qualities"))
        lower = model.lower_is_better(kind)
        pool = sorted(((c, model.stat_of(kind, ctx, c)) for c in choices),
                      key=lambda x: ((x[1] if lower else -x[1]), ctx.items[x[0]].get("name") or x[0]))
        values = [v for _c, v in pool] + [fitted_value]
        mx, mn = max([1e-9] + values), min(values)
        stock = self.stock_item(targets[0])
        shown = [model.card_for(ctx, kind, c, fitted_item, fitted_value, row.get("source") or "stock", stock, mx, mn)
                 for c, _v in pool]
        top = shown[:MAX_CARDS]
        fitted_card = next((c for c in shown if c.fitted), None)
        if fitted_card is not None and fitted_card not in top:
            top.append(fitted_card)
        return top

    def _fitted_source(self, n: model.BusNode) -> str:
        if n.obsolete:
            return "No longer in the game: pick a replacement"
        if not n.item:
            return "Empty"
        if n.kind == "rack":
            return ", ".join(f"{c} × {m}" for m, c in n.missiles) or "No missiles"
        tag = self._node_tag(n)
        if tag == "stock":
            return "Comes with the ship"
        if tag == "craft":
            return "Crafted"
        if tag == "unobtainable":
            return "No known seller · not craftable"
        offers = self.ctx.offers.get((n.part or {}).get("uuid") or "") or []
        return f"{money(offers[0]['price'])} at {offers[0]['place']}" if offers else "Bought"

    def _render_tray(self) -> None:
        n = self.selected()
        self.tray.setVisible(n is not None)
        if n is None:
            return
        missiles = self.missile_mode()
        # Rack tabs: the rack, or its missiles.
        self.rack_host.setVisible(n.kind == "rack")
        if n.kind == "rack":
            self.rack_tab.setText(f"{'RACK · BUILT IN' if n.locked else 'RACK'}\n{n.name}")
            self.rack_tab.setEnabled(not n.locked)
            self.rack_tab.setChecked(not missiles)
            per = " · PER RACK" if len(n.paths) > 1 else ""
            self.missile_tab.setText(f"MISSILES{per}\n" + (", ".join(f"{c} × {m}" for m, c in n.missiles) or "Empty"))
            self.missile_tab.setChecked(missiles)
        sides = model.slot_names(n.paths)
        one = next((name for p, name in sides if p == self.side), None)
        targets = self.targets()
        if missiles:
            size = (model.slot_of(self._view["rows"], targets[0]) or {}).get("max", 0) if targets else 0
            port = f"Missiles · S{size} ×{len(targets)}" + (f" · {one} rack only" if one else "")
            row = self.fitted_row()
            item = (row or {}).get("item") or ""
            name = (self.ctx.items.get(item) or {}).get("name") or item or "Empty"
        else:
            count = f" ×{len(n.paths)}" if len(n.paths) > 1 else ""
            port = f"{n.label} · {n.size}" + (f" · {one} only" if one else count)
            name = n.name
        self.tray_port.setText(port.upper())
        self.tray_name.setText(name)
        self.tray_src.setText(self._fitted_source(n) if not missiles else "")
        self.quality_link.setVisible(n.source == "craft" and bool(n.item) and n.item in self.ctx.recipes
                                     and not missiles)
        kit.clear_layout(self.seg)
        self.seg_host.setVisible(len(n.paths) > 1)
        if len(n.paths) > 1:
            options = [(None, "Both" if len(n.paths) == 2 else "All")] + sides
            for i, (path, label) in enumerate(options):
                b = QPushButton(label, objectName="LoSeg")
                b.setCheckable(True)
                b.setChecked(self.side == path)
                b.setCursor(Qt.PointingHandCursor)
                b.setProperty("pos", "first" if i == 0 else "last" if i == len(options) - 1 else "mid")
                b.clicked.connect(lambda _c=False, path=path: self.select(n.id, path))
                self.seg.addWidget(b)
        choices = self.choices()
        self.compare_link.setVisible(len(choices) > 1)
        self.compare_link.setText(f"All {len(choices)} that fit →")
        cards = self.cards(choices)
        for w in self._cards:
            w.deleteLater()
        self._cards = []
        kit.clear_layout(self.cards_row)
        for c in cards:
            w = PartCardWidget(c)
            w.hovered.connect(self._on_hover)
            w.left.connect(self._on_leave)
            w.held.connect(self._on_hold)
            w.fit.connect(self.fit)
            self.cards_row.addWidget(w)
            self._cards.append(w)
        self.cards_row.addStretch(1)
        self.cards_scroll.setVisible(bool(cards))
        self.tray_empty.setVisible(not cards)
        more = f" · showing the best {len(cards)} of {len(choices)}" if len(choices) > len(cards) else ""
        self.tray_hint.setText("Point at a part to preview it on every number above · click to hold the preview · "
                               "Buy or Craft to put it on: it goes on the shopping list or the craft list" + more)

    def _set_rack_mode(self, mode: str) -> None:
        self.rack_mode = mode
        self.hover = self.held = None
        self._render_tray()
        self._apply_preview()

    # -- previews -------------------------------------------------------------------------------------
    def _on_hover(self, item: str) -> None:
        self.hover = item
        self._preview_timer.start()

    def _on_leave(self, item: str) -> None:
        if self.hover == item:
            self.hover = None
            self._preview_timer.start()

    def _on_hold(self, item: str) -> None:
        self.held = None if self.held == item else item
        self._apply_preview()

    def _escape(self) -> None:
        if self.stack.currentWidget() is not self.scroll:
            self.close_subview()
        elif self.held:
            self.held = None
            self._apply_preview()

    def preview_parts(self) -> dict | None:
        item = self.held or self.hover
        targets = self.targets()
        if not item or not targets or self.ctx is None:
            return None
        return model.fit_part(self.ctx, self.parts, targets, item)

    def _apply_preview(self) -> None:
        if self.ctx is None or not self._view:
            return
        parts = self.preview_parts()
        preview = None
        if parts is not None:
            rows = fitted(self.ctx.catalog["ship"], self.ctx.items, parts)
            preview = {"totals": totals(rows, self.ctx.items, self.ctx.recipes,
                                        self.ctx.catalog["ship"].get("basePower")),
                       "nodes": model.bus_nodes(self.ctx, rows)}
        self._render_hud(preview)
        self._update_ring(preview)
        item = self.held or self.hover
        for w in self._cards:
            w.set_previewing(w.card.item == item and not w.card.fitted)

    # -- changes --------------------------------------------------------------------------------------------
    def fit(self, item: str, source: str | None = None) -> None:
        """Puts a part on the open slots, got one way: bought, crafted (its quality is asked next) or
        the ship's stock part. On the fitted part it only switches how it's got."""
        if self.ctx is None:
            return
        source = source or model.default_source(self.ctx, item)
        row = self.fitted_row()
        is_fitted = bool(row) and row["item"] == item
        if is_fitted and (source == "craft") == (row["source"] == "craft"):
            return
        name = (self.ctx.items.get(item) or {}).get("name") or item
        nxt = model.fit_part(self.ctx, self.parts, self.targets(), item, source)
        self.hover = self.held = None
        how = "crafting it: set its quality" if source == "craft" else "stock" if source == "stock" else "buying it"
        missiles = self.tray_kind() == "missile"
        if self.side:                      # one slot of a pair changed: the selection follows it
            self.sel, self.side = self.side, None
        self.commit(nxt, f"{name}: {how}." if is_fitted else f"{name} fitted, {how}.")
        if source == "craft" and not missiles:
            self.open_craft()

    def commit(self, nxt: dict, message: str) -> None:
        """A change from Stock starts a new loadout; any other is saved and can be undone."""
        lo = self.current()
        if lo is not None:
            self.history.append(self.parts)
            self.parts = nxt
            loadouts.save(replace(lo, parts=nxt))
            self._refresh()
            self.toast.show_message(message, self.undo)
            return
        made = self._create(self._next_name(), nxt)
        if made is not None:
            self.toast.show_message(f"New loadout started from stock: {message}",
                                    lambda: self._remove(made.id, offer_undo=False))

    def undo(self) -> None:
        if not self.history or self.current() is None:
            return
        self.parts = self.history.pop()
        loadouts.save(replace(self.current(), parts=self.parts))
        self._refresh()

    def save_ticks(self, ticks: list[str]) -> None:
        lo = self.current()
        if lo is not None:
            loadouts.save(replace(lo, ticks=list(ticks)))

    def save_basket(self, basket: dict | None, ticks: list[str]) -> None:
        lo = self.current()
        if lo is not None:
            loadouts.save(replace(lo, basket=basket, ticks=list(ticks)))

    def set_parts(self, nxt: dict, message: str) -> None:
        """A change made in a sub-view (shop picked, qualities set)."""
        self.commit(nxt, message)

    def _next_name(self) -> str:
        names = {lo.name for lo in self._loadouts()}
        n = len(names) + 1
        while f"Loadout {n}" in names:
            n += 1
        return f"Loadout {n}"

    def _create(self, name: str, parts: dict, ticks=None, basket=None) -> loadouts.Loadout | None:
        try:
            loadouts.check_room(self.entry.id)
        except loadouts.LimitReached as exc:
            self.toast.show_message(str(exc))
            return None
        made = loadouts.save(loadouts.Loadout(hangar_id=self.entry.id, ship=self.entry.ship, name=name[:80],
                                              parts=dict(parts), ticks=list(ticks or []), basket=basket))
        self._open_loadout(made.id)
        return made

    def _remove(self, loadout_id: str, offer_undo: bool) -> None:
        lo = loadouts.get(loadout_id)
        if lo is None:
            return
        loadouts.remove(loadout_id)
        if self.loadout_id == loadout_id:
            self._open_loadout(None)
        else:
            self._refresh()
        if offer_undo:
            self.toast.show_message(f"{lo.name} deleted.",
                                    lambda: self._create(lo.name, lo.parts, lo.ticks, lo.basket))

    def new_loadout(self) -> None:
        made = self._create(self._next_name(), {})
        if made is not None:
            self.toast.show_message(f"{made.name} started from stock.")

    # -- the loadout menu ------------------------------------------------------------------------------------
    def _menu(self, anchor: QWidget) -> None:
        lo = self.current()
        if lo is None:
            return
        menu = QMenu(self)
        menu.addAction("Rename", self._rename)
        menu.addAction("Duplicate", self._duplicate)
        menu.addAction("Copy share link (updates it)" if lo.share else "Copy share link", self._share)
        if lo.share:
            menu.addAction("Stop sharing", self._stop_sharing)
        menu.addSeparator()
        menu.addAction("Delete loadout", lambda: self._remove(lo.id, offer_undo=True))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _rename(self) -> None:
        lo = self.current()
        if lo is None:
            return
        name, ok = QInputDialog.getText(self, "Rename loadout", "Name", text=lo.name)
        name = name.strip()[:80]
        if ok and name and name != lo.name:
            loadouts.save(replace(loadouts.get(lo.id), name=name))
            self._refresh()

    def _duplicate(self) -> None:
        lo = self.current()
        if lo is None:
            return
        made = self._create(f"{lo.name} copy", self.parts, lo.ticks, lo.basket)
        if made is not None:
            self.toast.show_message(f"{lo.name} duplicated.")

    def _online(self) -> bool:
        sync = self.sync
        if sync is None or not sync.enabled:
            self.toast.show_message("Sharing needs the online sign-in with Sync online on (Settings → Online "
                                    "account).")
            return False
        return True

    def _share(self) -> None:
        lo = self.current()
        if lo is None or not self._online():
            return
        self.toast.show_message("Making the share link…")
        self._call_then = ("share", lo.name)
        self._call.run(lambda: self.sync.share_loadout(lo.id))

    def _stop_sharing(self) -> None:
        lo = self.current()
        if lo is None or not self._online():
            return
        self._call_then = ("stop", lo.name)
        self._call.run(lambda: self.sync.stop_sharing(lo.id))

    def _on_call_done(self, result, error) -> None:
        what, name = self._call_then or ("", "")
        self._call_then = None
        if error is not None:
            text = str(error) if isinstance(error, portal.PortalError) else "Couldn't reach sc-toolbox.com."
            self.toast.show_message(f"{text} Try again in a moment.")
            return
        if what == "share":
            QGuiApplication.clipboard().setText(result.get("url", ""))
            self.toast.show_message(f"Share link copied. It shows {name} as it is now: copy it again after changes.")
        elif what == "stop":
            self.toast.show_message(f"{name} isn't shared any more: the link now says it was removed.")
        self._refresh()

    # -- sub-views (app.ui.loadout_views) ---------------------------------------------------------------
    def open_compare(self) -> None:
        from app.ui.loadout_views import CompareView

        n = self.selected()
        if n is None:
            return
        self.hover = self.held = None
        self._show_subview(CompareView(self))

    def open_shopping(self) -> None:
        from app.ui.loadout_views import ShoppingView

        if self.current() is None:
            return
        self._show_subview(ShoppingView(self))

    def open_craft(self) -> None:
        from app.ui.loadout_views import CraftDialog

        n = self.selected()
        if n is None or not n.item or n.item not in self.ctx.recipes:
            return
        dialog = CraftDialog(self, n, self.targets())
        dialog.applied.connect(self._apply_qualities)
        dialog.open()

    def _apply_qualities(self, qualities: list, paths: list) -> None:
        n = self.selected()
        if n is None:
            return
        nxt = dict(self.parts)
        for p in paths:
            nxt[p] = {"item": n.item, "source": "craft", "qualities": list(qualities)}
        self.commit(nxt, f"{(n.part or {}).get('name') or n.item}: qualities set.")

    def _show_subview(self, view: QWidget) -> None:
        self.close_subview(refresh=False)
        self.stack.addWidget(view)
        self.stack.setCurrentWidget(view)

    def close_subview(self, refresh: bool = True) -> None:
        for i in reversed(range(self.stack.count())):
            w = self.stack.widget(i)
            if w not in (self.scroll, self.message):
                self.stack.removeWidget(w)
                w.deleteLater()
        self.stack.setCurrentWidget(self.scroll)
        if refresh and self.ctx is not None:
            self._refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast._place()
