"""Salvage Claims: which claim ship pays the most. Pick an Adagio claim
difficulty and see every ship that claim can spawn, best net value first —
components (from the game's own loadouts), whether each comes off (per the
community spreadsheet), what it sells or dismantles for, and the cargo aboard
priced at UEX averages. A row expands in place with the details.

Game data is re-extracted automatically once per game build; the
spreadsheet and UEX prices come from app.datahub (at most daily, or on the
refresh buttons). Rendering always works from the local copies.
"""

from __future__ import annotations

import urllib.parse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, datahub, osutil, salvage, settings
from app.salvage import ComponentRow, ShipRow
from app.theme import PALETTE
from app.ui import kit
from app.ui.kit import Badge, label

ALL_TIERS = "__all__"
WEB_URL = "https://sc-toolbox.com/salvage"

# Column widths of the table (header and rows share them).
COLS = {"arrow": 18, "fee": 84, "components": 108, "cargo": 92, "net": 196}

_STATE = {
    "yes": ("✓", "success", "The spreadsheet records this coming off this ship"),
    "unlisted": ("?", "warning",
                 "Priced in the spreadsheet, but not recorded coming off this ship: not counted in the total"),
    "unknown": ("—", "neutral", "Not in the spreadsheet"),
}

HELP = (
    "<b>Net value</b> = salvageable components + cargo aboard − the claim fee.<br>"
    "<b>Components</b>: each part the community spreadsheet confirms comes off the ship, at the better of "
    "its sell or dismantle price (shown green in the expanded row). Parts marked <b>?</b> are priced but not "
    "confirmed and aren't counted.<br>"
    "<b>Cargo</b>: what the spreadsheet's author found aboard, at UEX average sell prices; contents vary.<br>"
    "The bar shows how the value splits: <span style='color:%s'>■</span> components, "
    "<span style='color:%s'>■</span> cargo." % (PALETTE["info"], PALETTE["hue_industry"])
)


def _money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f}"


def _when(ts: float | None) -> str:
    return kit.short_date(ts)


def _better_option(c: ComponentRow) -> str | None:
    """'sell' or 'dismantle', whichever pays more — only when both are priced."""
    if c.sell is None or c.dismantle is None or not (c.sell or c.dismantle):
        return None
    return "sell" if c.sell >= c.dismantle else "dismantle"


class _Header(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _cell(text: str, width: int, name: str = "RowValue") -> QWidget:
    lbl = label(text, name, align=Qt.AlignRight | Qt.AlignVCenter)
    lbl.setFixedWidth(width)
    return lbl


def _table_head() -> QWidget:
    head = QFrame(objectName="TableHead")
    row = QHBoxLayout(head)
    row.setContentsMargins(14, 9, 14, 7)
    row.setSpacing(14)
    row.addSpacing(COLS["arrow"])
    row.addWidget(kit.caps("Ship"), stretch=1)
    for key, text in (("fee", "Fee"), ("components", "Components"), ("cargo", "Cargo"), ("net", "Net value")):
        cap = kit.caps(text)
        cap.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cap.setFixedWidth(COLS[key])
        row.addWidget(cap)
    return head


# -- one ship ---------------------------------------------------------------------

class ShipRowWidget(QWidget):
    """One claim ship: a header row (name, fee, components, cargo, net value)
    that expands in place. compact=True is the overlay's: name, value bar and
    net only, the details stacked underneath and spelled out (no tooltips
    there); `flag` marks the row (e.g. "Your claim")."""

    toggled = Signal(str, bool)
    open_ship = Signal(str)

    def __init__(self, row: ShipRow, expanded: bool, *, best: bool, top: float = 0, match=None, tier: str = "",
                 compact: bool = False, flag: str = "", parent=None):
        super().__init__(parent)
        self.row = row
        self.compact = compact
        self.match = match  # component filter predicate, or None
        self._detail: QWidget | None = None
        self._open = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = _Header(objectName="PanelRow")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.clicked.connect(lambda: self._set_open(not self._open))
        if flag:
            self.header.setProperty("flagged", True)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(*((10, 7, 10, 7) if compact else (14, 9, 14, 9)))
        head.setSpacing(10 if compact else 14)
        self.arrow = label("▸", "MutedText")
        self.arrow.setFixedWidth(COLS["arrow"])
        head.addWidget(self.arrow)

        title = QVBoxLayout()
        title.setSpacing(2)
        name = QHBoxLayout()
        name.setSpacing(8)
        name.addWidget(label(row.name, "RowName"))
        if tier:
            name.addWidget(Badge(tier))
        if flag:
            name.addWidget(Badge(flag, "info"))
        name.addStretch(1)
        title.addLayout(name)
        if match is not None:
            hits = [f"{c.name} ×{c.qty}" for c in row.components if match(c)]
            hit = label("Has " + ", ".join(hits), "MatchText")
            hit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            title.addWidget(hit)
        head.addLayout(title, stretch=1)

        if not row.in_sheet:
            head.addWidget(label("no data" if compact else "Not in the spreadsheet yet", "MutedText"))
        elif compact:
            gross = row.components_value + row.cargo_value
            if gross > 0:
                head.addWidget(kit.StackedBar(
                    [(row.components_value, PALETTE["info"]), (row.cargo_value, PALETTE["hue_industry"])],
                    width=56, scale=gross / top if top else 1), alignment=Qt.AlignVCenter)
            value = label(_money(row.net), "RowKey", align=Qt.AlignRight | Qt.AlignVCenter)
            value.setMinimumWidth(64)
            if best:
                value.setProperty("tone", "success")
            head.addWidget(value)
        else:
            head.addWidget(_cell(_money(row.fee), COLS["fee"]))
            head.addWidget(_cell(_money(row.components_value), COLS["components"]))
            head.addWidget(_cell(_money(row.cargo_value), COLS["cargo"],
                                 "RowValue" if row.cargo_value else "RowValueDim"))
            net = QWidget()
            net.setFixedWidth(COLS["net"])
            nrow = QHBoxLayout(net)
            nrow.setContentsMargins(0, 0, 0, 0)
            nrow.setSpacing(10)
            nrow.addStretch(1)
            gross = row.components_value + row.cargo_value
            if gross > 0:
                nrow.addWidget(kit.StackedBar(
                    [(row.components_value, PALETTE["info"]), (row.cargo_value, PALETTE["hue_industry"])],
                    width=84, scale=gross / top if top else 1,
                    tip=f"Components {_money(row.components_value)} · cargo {_money(row.cargo_value)}"))
            value = label(_money(row.net), "RowKey", align=Qt.AlignRight | Qt.AlignVCenter)
            value.setMinimumWidth(74)
            if best:
                value.setProperty("tone", "success")
                value.setToolTip("The best net value in this list")
            if row.unconfirmed_value:
                value.setToolTip(f"+{_money(row.unconfirmed_value)} more in parts the spreadsheet "
                                 "hasn't recorded coming off this ship")
            nrow.addWidget(value)
            head.addWidget(net)
        v.addWidget(self.header)
        if expanded:
            self._set_open(True)

    def _set_open(self, on: bool) -> None:
        self._open = on
        self.header.setProperty("open", on)
        kit.repolish(self.header)
        self.arrow.setText("▾" if on else "▸")
        if on and self._detail is None:
            self._detail = self._build_detail()
            self.layout().addWidget(self._detail)
        if self._detail is not None:
            self._detail.setVisible(on)
        self.toggled.emit(self.row.stem, on)

    # -- expanded body --------------------------------------------------------
    def _build_detail(self) -> QWidget:
        if self.compact:
            return self._build_compact_detail()
        row = self.row
        body = QFrame(objectName="RowDetail")
        v = QVBoxLayout(body)
        v.setContentsMargins(46, 4, 18, 14)
        v.setSpacing(8)
        if row.note:
            v.addWidget(label(row.note, "WarnText", wrap=True))

        cols = QHBoxLayout()
        cols.setSpacing(28)
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(kit.caps("Salvageable components"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        heads = ["", "Component", "Type", "Size", "Grade", "Qty", "Sell", "Dismantle"]
        right = {"Size", "Qty", "Sell", "Dismantle"}
        for col, text in enumerate(heads):
            cap = kit.caps(text)
            if text in right:
                cap.setAlignment(Qt.AlignRight)
            grid.addWidget(cap, 0, col)
        for r, c in enumerate(row.components, start=1):
            mark, tone, tip = _STATE[c.salvageable]
            dim = "RowValue" if c.salvageable == "yes" else "RowValueDim"
            hit = "MatchText" if self.match is not None and self.match(c) else dim
            better = _better_option(c)
            badge = Badge(mark, tone, tip=tip)
            grid.addWidget(badge, r, 0)
            grid.addWidget(label(c.name, hit), r, 1)
            grid.addWidget(label(f"{c.type}" + (f" · {c.family}" if c.family else ""), dim), r, 2)
            grid.addWidget(label(str(c.size or ""), dim, align=Qt.AlignRight), r, 3)
            grid.addWidget(label(c.grade, dim), r, 4)
            grid.addWidget(label(f"×{c.qty}", dim, align=Qt.AlignRight), r, 5)
            grid.addWidget(label(_money(c.sell), "BestText" if better == "sell" else dim,
                                 tip="Selling pays more" if better == "sell" else "", align=Qt.AlignRight), r, 6)
            grid.addWidget(label(_money(c.dismantle), "BestText" if better == "dismantle" else dim,
                                 tip="\n".join(filter(None, [
                                     "Dismantling pays more" if better == "dismantle" else "",
                                     f"Dismantles into: {c.materials_text()}" if c.materials else "",
                                 ])), align=Qt.AlignRight), r, 7)
        grid.setColumnStretch(1, 1)
        left.addLayout(grid)
        cols.addLayout(left, stretch=3)

        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        right_col.addWidget(kit.caps("Cargo aboard"))
        if row.cargo:
            cg = QGridLayout()
            cg.setHorizontalSpacing(14)
            cg.setVerticalSpacing(3)
            for col, text in enumerate(["Material", "SCU", "Value"]):
                cap = kit.caps(text)
                if col:
                    cap.setAlignment(Qt.AlignRight)
                cg.addWidget(cap, 0, col)
            for r, c in enumerate(row.cargo, start=1):
                cg.addWidget(label(c.material, "RowValue"), r, 0)
                cg.addWidget(label(str(c.scu), "RowValue", align=Qt.AlignRight), r, 1)
                cg.addWidget(label(_money(c.value), "RowValue", align=Qt.AlignRight,
                                   tip=f"UEX average sell: {_money(c.price)} / SCU"), r, 2)
            cg.setColumnStretch(0, 1)
            right_col.addLayout(cg)
            right_col.addWidget(label("As the spreadsheet's author found it; contents vary.", "MutedText", wrap=True))
        else:
            right_col.addWidget(label("None recorded." if row.in_sheet else "No data yet.", "MutedText"))
        right_col.addStretch(1)
        cols.addLayout(right_col, stretch=2)
        v.addLayout(cols)
        link = kit.button(f"{row.name} in the Ship Database ↗", "ghost",
                          lambda: self.open_ship.emit(row.name))
        v.addWidget(link, alignment=Qt.AlignLeft)
        return body


    def _build_compact_detail(self) -> QWidget:
        """The overlay's: fee / components / cargo, then each part with the
        price it's counted at and whether selling or dismantling pays more,
        then the cargo."""
        row = self.row
        body = QFrame(objectName="RowDetail")
        v = QVBoxLayout(body)
        v.setContentsMargins(12, 4, 10, 10)
        v.setSpacing(6)
        stats = QHBoxLayout()
        stats.setSpacing(18)
        for caption, value in (("Fee", row.fee), ("Components", row.components_value), ("Cargo", row.cargo_value)):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(kit.caps(caption))
            col.addWidget(label(_money(value), "RowValue"))
            stats.addLayout(col)
        stats.addStretch(1)
        v.addLayout(stats)
        if row.note:
            v.addWidget(label(row.note, "WarnText", wrap=True))
        v.addWidget(kit.caps("Components"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        for r, c in enumerate(row.components):
            mark, tone, _tip = _STATE[c.salvageable]
            counted = c.salvageable == "yes"
            dim = "RowValue" if counted else "RowValueDim"
            priced = bool(c.sell or c.dismantle)
            better = _better_option(c) or ("sell" if c.sell else "dismantle" if c.dismantle else "")
            grid.addWidget(Badge(mark, tone), r, 0)
            name = label(f"{c.qty}× {c.name}", "MatchText" if self.match is not None and self.match(c) else dim)
            name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            grid.addWidget(name, r, 1)
            grid.addWidget(label(_money(c.best) if priced else "—", "BestText" if priced and counted else dim,
                                 align=Qt.AlignRight), r, 2)
            grid.addWidget(label(better, "MutedText"), r, 3)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        legend = "✓ comes off and counts · ? priced, not confirmed (not counted)"
        v.addWidget(label(legend, "MutedText", wrap=True))
        if row.cargo:
            v.addWidget(kit.caps("Cargo aboard"))
            cg = QGridLayout()
            cg.setHorizontalSpacing(8)
            cg.setVerticalSpacing(2)
            for r, c in enumerate(row.cargo):
                cg.addWidget(label(f"{c.scu} SCU {c.material}", "RowValue"), r, 0)
                cg.addWidget(label(_money(c.value), "RowValue", align=Qt.AlignRight), r, 1)
            cg.setColumnStretch(0, 1)
            v.addLayout(cg)
        return body


# -- the view ------------------------------------------------------------------------

class SalvageView(kit.ToolPage):
    def __init__(self, channel: str, parent=None):
        super().__init__("salvage", "Salvage Claims",
                         "Every ship a claim can spawn, with its fee, salvageable components, cargo and net value",
                         web_url=WEB_URL, parent=parent)
        self.paths = channel_mod.resolve_channel_paths(settings.current().game_root, channel)
        self.game: dict | None = None
        self.sheet: salvage.Sheet | None = None
        self.uex: tuple[float, dict] | None = None
        self.expanded: set[str] = set()

        # Game data and the two web sources come from app.datahub: the game
        # files are read once per patch, the sheet and prices at most daily.
        self._game = datahub.GameDataWaiter("salvage", self)
        self._game.ready.connect(self._on_game_loaded)
        self._game.progress.connect(self.show_message)
        self._game.failed.connect(lambda msg: self.show_empty(
            "Couldn't read the game files", msg.splitlines()[0] if msg else "",
            "Open Settings", lambda: self.window().show_tool("settings")))
        datahub.hub().updated.connect(self._on_hub_updated)
        datahub.hub().failed.connect(self._on_hub_failed)
        self._build_ui()

    def _build_ui(self) -> None:
        self.sheet_btn = kit.button("Refresh sheet", tip="Download the community salvage spreadsheet again")
        self.sheet_btn.clicked.connect(lambda: self._refresh("sheet"))
        self.uex_btn = kit.button("Refresh prices", tip="Fetch current average commodity prices from UEX")
        self.uex_btn.clicked.connect(lambda: self._refresh("uex"))
        self.add_action(self.sheet_btn)
        self.add_action(self.uex_btn)

        f = self.filters
        self.tiers = kit.Dropdown(marks=False, tip="Adagio salvage claim difficulty: each spawns ships of one size")
        self.tiers.setMinimumContentsLength(16)
        self.tiers.activated.connect(lambda _i: self._render())
        f.add(self.tiers, "Difficulty")
        f.add_spacing(6)
        self.family_combo = kit.Dropdown(min_width=110, tip="Find ships with a salvageable component of this class")
        self.type_combo = kit.Dropdown(min_width=110, tip="… of this type")
        self.size_combo = kit.Dropdown(min_width=96, tip="… of this size")
        for combo in (self.family_combo, self.type_combo, self.size_combo):
            combo.activated.connect(lambda _i: self._render())
            f.add(combo)
        self.sort_combo = kit.Dropdown([("Net value", "net"), ("Name", "name")], marks=False)
        self.sort_combo.activated.connect(lambda _i: self._render())
        f.add_sort(self.sort_combo)

        self.result.clear_requested.connect(self._clear_filters)
        self.set_help(HELP, "How net value is worked out")

        self.scroll = kit.scroll_area()
        page = QWidget()
        self._page = QVBoxLayout(page)
        self._page.setContentsMargins(0, 0, 6, 0)
        self._page.setSpacing(12)
        self.table = kit.panel()
        tv = QVBoxLayout(self.table)
        tv.setContentsMargins(0, 0, 0, 4)
        tv.setSpacing(0)
        tv.addWidget(_table_head())
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(0)
        tv.addLayout(self.rows_box)
        self._page.addWidget(self.table)
        self.where = kit.Section("Where to sell")
        self._page.addWidget(self.where)
        self._page.addStretch(1)
        self.scroll.setWidget(page)
        self.set_content(self.scroll)
        self.show_message("Loading salvage data…")

    # -- lifecycle ------------------------------------------------------------------
    def activate(self) -> None:
        self.sheet = salvage.load_sheet()
        self.uex = salvage.load_uex()
        self._update_sources()
        # Never downloaded (e.g. offline at startup): try now; the hub won't
        # download more than once a day either way.
        for what, data in (("sheet", self.sheet), ("uex", self.uex)):
            if data is None:
                self._refresh(what)
        if self.game is None:
            self._game.request(self.paths.channel_root)
        else:
            self._render()

    def _on_game_loaded(self, game: dict) -> None:
        self.game = game
        previous = self.tiers.currentData()
        self.tiers.clear()
        for t in game["tiers"]:
            self.tiers.addItem(f"{t['label']} · {t['size']} ({len(t['ships'])})", t["id"])
        self.tiers.addItem(f"All difficulties ({sum(len(t['ships']) for t in game['tiers'])})", ALL_TIERS)
        index = self.tiers.findData(previous if previous is not None else "Easy")
        self.tiers.setCurrentIndex(max(index, 0))

        comps = [c for ship in game["ships"].values() for c in ship["components"]]
        families = sorted({c["family"] for c in comps if c["family"]})
        types = [t for t in salvage.TYPE_ORDER if any(c["type"] == t for c in comps)]
        sizes = sorted({c["size"] for c in comps if c["size"] is not None})
        for combo, first, values, text in (
            (self.family_combo, "Any class", families, str),
            (self.type_combo, "Any type", types, str),
            (self.size_combo, "Any size", sizes, lambda s: f"Size {s}"),
        ):
            combo.clear()
            combo.addItem(first, None)
            for value in values:
                combo.addItem(text(value), value)
        self._render()

    def _clear_filters(self) -> None:
        for combo in (self.family_combo, self.type_combo, self.size_combo):
            combo.setCurrentIndex(0)
        self._render()

    def _component_filter(self):
        family = self.family_combo.currentData()
        kind = self.type_combo.currentData()
        size = self.size_combo.currentData()
        if family is None and kind is None and size is None:
            return None
        # Only parts the spreadsheet confirms come off the ship count as a find.
        return lambda c: (c.salvageable == "yes"
                          and (family is None or c.family == family)
                          and (kind is None or c.type == kind)
                          and (size is None or c.size == size))

    # -- refresh buttons ------------------------------------------------------------
    _SOURCES = {"sheet": "salvage_sheet", "uex": "uex"}

    def _refresh(self, what: str) -> None:
        btn = self.sheet_btn if what == "sheet" else self.uex_btn
        if datahub.hub().refresh_web(self._SOURCES[what]):
            btn.setEnabled(False)
            btn.setText("Refreshing…")
        self._update_sources()

    def _on_hub_updated(self, name: str) -> None:
        if name == "salvage_sheet":
            self.sheet = salvage.load_sheet()
        elif name == "uex":
            self.uex = salvage.load_uex()
        else:
            return
        self._update_sources()
        self._render()

    def _on_hub_failed(self, name: str, message: str) -> None:
        if name not in self._SOURCES.values():
            return
        self._update_sources()
        what = "spreadsheet" if name == "salvage_sheet" else "UEX prices"
        if self.isVisible():
            self.notice.show_text(f"Couldn't update the {what}: {message.splitlines()[0] if message else 'error'}. "
                                  "The previous copy is still used.", "warning")

    def _update_sources(self) -> None:
        self.set_data_chip(
            f"Sheet <b>{_when(self.sheet.fetched if self.sheet else None)}</b> · "
            f"prices <b>{_when(self.uex[0] if self.uex else None)}</b>",
            "When the community spreadsheet and the UEX prices were last downloaded")
        # Each source is downloaded at most once a day: the buttons say when
        # the next refresh is possible.
        h = datahub.hub()
        for what, btn, text in (("sheet", self.sheet_btn, "Refresh sheet"), ("uex", self.uex_btn, "Refresh prices")):
            source = self._SOURCES[what]
            busy = h.pending(source)
            fresh = datahub.WEB_SOURCES[source].fresh()
            btn.setEnabled(not busy and not fresh)
            btn.setText("Refreshing…" if busy else text)
            if fresh:
                hours = max(1, round((datahub.WEB_SOURCES[source].max_age - h.web_age(source)) / 3600))
                btn.setToolTip(f"Updated less than a day ago; it can be refreshed again in about {hours} h.")
            else:
                btn.setToolTip("Download it again (at most once a day)")

    # -- rendering ----------------------------------------------------------------------
    def _render(self) -> None:
        if self.game is None:
            return
        tier_id = self.tiers.currentData()
        prices = self.uex[1] if self.uex else {}
        show_all = tier_id == ALL_TIERS
        tiers = [t for t in self.game["tiers"] if show_all or t["id"] == tier_id]
        rows, tier_of = [], {}
        for tier in tiers:
            for row in salvage.build_rows(self.game, tier["id"], self.sheet, prices):
                rows.append(row)
                tier_of[row.stem] = tier["label"]
        total = len(rows)
        match = self._component_filter()
        if match is not None:
            rows = [r for r in rows if any(match(c) for c in r.components)]
        if self.sort_combo.currentData() == "name":
            rows.sort(key=lambda r: r.name)
        else:
            rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))
        best = max((r.net for r in rows if r.in_sheet), default=None)
        top = max((r.components_value + r.cargo_value for r in rows if r.in_sheet), default=0)

        # Result line: count, what the difficulty spawns, the component filters as chips.
        count = f"{len(rows)} of {total} claim ships" if match is not None else f"{total} claim ships"
        if not show_all and tiers:
            count += f" · {tiers[0]['label']} claims spawn {tiers[0]['size'].lower()} ships"
        self.result.set_count(count)
        chips = []
        for combo in (self.family_combo, self.type_combo, self.size_combo):
            if combo.currentIndex() > 0:
                chips.append((combo.currentText(), lambda _c=False, c=combo: (c.setCurrentIndex(0), self._render())))
        self.result.set_chips(chips)

        keep = self.scroll.verticalScrollBar().value()
        kit.clear_layout(self.rows_box)
        if not rows:
            self.show_empty("No ship here has that part",
                            "No ship at this difficulty has a matching salvageable component. Try another "
                            "difficulty, or remove a filter.", "Clear filters", self._clear_filters)
            return
        for row in rows:
            w = ShipRowWidget(row, row.stem in self.expanded, best=row.in_sheet and row.net == best and row.net > 0, top=top,
                              match=match, tier=tier_of[row.stem] if show_all else "")
            w.toggled.connect(self._on_row_toggled)
            w.open_ship.connect(lambda name: osutil.open_url(
                "https://sc-toolbox.com/ships?q=" + urllib.parse.quote(name)))
            self.rows_box.addWidget(w)
        self._fill_where()
        self.show_content()
        self.scroll.verticalScrollBar().setValue(keep)

    def _on_row_toggled(self, stem: str, on: bool) -> None:
        if on:
            self.expanded.add(stem)
        else:
            self.expanded.discard(stem)

    def _fill_where(self) -> None:
        sec = self.where
        while sec.v.count() > 1:
            item = sec.v.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                kit.clear_layout(item.layout())
        if self.sheet and self.sheet.where_to_sell:
            for what, where in self.sheet.where_to_sell:
                sec.add(label(f"<b>{what}</b> · {where}", "BodyText", wrap=True, rich=True))
        if self.sheet and self.sheet.unmatched:
            sec.add(label("Spreadsheet ship names not recognised (ignored): " + ", ".join(self.sheet.unmatched),
                          "WarnText", wrap=True))
        src = QHBoxLayout()
        src.setSpacing(8)
        src.addWidget(label("Components from the game files · salvage data from the community spreadsheet · "
                            "commodity prices from UEX (average sell).", "MutedText", wrap=True), stretch=1)
        src.addWidget(kit.button("Open spreadsheet ↗", "ghost", lambda: osutil.open_url(salvage.SHEET_URL)))
        sec.v.addLayout(src)
