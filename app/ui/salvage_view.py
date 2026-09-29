"""Salvage claim browser: pick an Adagio claim difficulty, see every ship
that claim can spawn as an accordion — components (from the game's own
loadouts), whether each comes off (per the community spreadsheet), what it
sells or dismantles for, and the cargo aboard priced at UEX averages.

Game data is re-extracted automatically once per game build; the
spreadsheet and UEX prices are only fetched when their refresh buttons are
pressed (or once, when nothing has been fetched yet). Rendering always
works from the local copies.
"""

from __future__ import annotations

import subprocess
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, salvage, settings
from app.salvage import ComponentRow, ShipRow

ALL_TIERS = "__all__"

_STATE = {
    "yes": ("✓", "SalvageYes", "The spreadsheet records this coming off this ship"),
    "unlisted": ("?", "SalvageMaybe",
                 "Priced in the spreadsheet, but not recorded coming off this ship — "
                 "not counted in the total"),
    "unknown": ("—", "SalvageNo", "Not in the spreadsheet"),
}


def _money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f}"


def _when(ts: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "never"


def _label(text: str, name: str = "SalvageCell", tip: str = "", align=None) -> QLabel:
    lbl = QLabel(text, objectName=name)
    if tip:
        lbl.setToolTip(tip)
    if align is not None:
        lbl.setAlignment(align)
    return lbl


def _better_option(c: ComponentRow) -> str | None:
    """'sell' or 'dismantle', whichever pays more — only when both are priced."""
    if c.sell is None or c.dismantle is None or not (c.sell or c.dismantle):
        return None
    return "sell" if c.sell >= c.dismantle else "dismantle"


# -- background work -----------------------------------------------------------

class _Worker(QObject):
    game_loaded = Signal(object)
    progress = Signal(str)
    refreshed = Signal(str)          # "sheet" | "uex"
    failed = Signal(str, str)        # what, message

    def load_game(self, channel_root) -> None:
        def work():
            try:
                self.game_loaded.emit(salvage.load_game_data(channel_root, self.progress.emit))
            except Exception as exc:  # shown in the view, not fatal
                self.failed.emit("game", str(exc))
        threading.Thread(target=work, daemon=True).start()

    def refresh(self, what: str) -> None:
        fetch = salvage.refresh_sheet if what == "sheet" else salvage.refresh_uex

        def work():
            try:
                fetch()
                self.refreshed.emit(what)
            except Exception as exc:
                self.failed.emit(what, str(exc))
        threading.Thread(target=work, daemon=True).start()


# -- one ship ---------------------------------------------------------------------

class _Header(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ShipCard(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, row: ShipRow, expanded: bool, match=None, tier: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ShipCard")
        self.row = row
        self.match = match  # component filter predicate, or None
        self._detail: QWidget | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._open = False
        self.header = _Header(objectName="ShipHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.clicked.connect(lambda: self._set_open(not self._open))
        head = QHBoxLayout(self.header)
        head.setContentsMargins(14, 10, 14, 10)
        head.setSpacing(18)
        self.arrow = _label("▸", "ShipArrow")
        head.addWidget(self.arrow)
        title = QVBoxLayout()
        title.setSpacing(2)
        name = QHBoxLayout()
        name.setSpacing(10)
        name.addWidget(_label(row.name, "ShipName"))
        if tier:
            name.addWidget(_label(tier.upper(), "ShipTier"))
        name.addStretch(1)
        title.addLayout(name)
        if match is not None:
            hits = [f"{c.name} ×{c.qty}" for c in row.components if match(c)]
            title.addWidget(_label("Matches: " + ", ".join(hits), "ShipMatch"))
        head.addLayout(title, stretch=1)
        if not row.in_sheet:
            head.addWidget(_label("not in spreadsheet", "ShipMuted"))
        else:
            head.addWidget(self._stat("FEE", _money(row.fee)))
            head.addWidget(self._stat("COMPONENTS", _money(row.components_value)))
            head.addWidget(self._stat("CARGO", _money(row.cargo_value)))
            net = self._stat("NET", _money(row.net), "ShipNet")
            if row.unconfirmed_value:
                net.setToolTip(f"+{_money(row.unconfirmed_value)} more in parts the spreadsheet "
                               "hasn't recorded coming off this ship")
            head.addWidget(net)
        layout.addWidget(self.header)

        if expanded:
            self._set_open(True)

    @staticmethod
    def _stat(caption: str, value: str, name: str = "ShipStat") -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(_label(caption, "ShipCaption", align=Qt.AlignRight))
        v.addWidget(_label(value, name, align=Qt.AlignRight))
        box.setMinimumWidth(92)
        return box

    def _set_open(self, on: bool) -> None:
        self._open = on
        self.header.setProperty("open", on)
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)
        self.arrow.setText("▾" if on else "▸")
        if on and self._detail is None:
            self._detail = self._build_detail()
            self.layout().addWidget(self._detail)
        if self._detail is not None:
            self._detail.setVisible(on)
        self.toggled.emit(self.row.stem, on)

    # -- expanded body --------------------------------------------------------
    def _build_detail(self) -> QWidget:
        row = self.row
        body = QWidget(objectName="ShipDetail")
        v = QVBoxLayout(body)
        v.setContentsMargins(40, 4, 18, 14)
        v.setSpacing(8)

        if row.note:
            note = _label(row.note, "InspectorNote")
            note.setWordWrap(True)
            v.addWidget(note)

        v.addWidget(_label("COMPONENTS", "SectionLabel"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        heads = ["Type", "Component", "Size", "Grade", "Class", "Qty", "Sell", "Dismantle", "Salvage"]
        right = {"Size", "Qty", "Sell", "Dismantle"}
        for col, text in enumerate(heads):
            grid.addWidget(_label(text, "SalvageHead",
                                  align=Qt.AlignRight if text in right else None), 0, col)
        for r, c in enumerate(row.components, start=1):
            mark, style, tip = _STATE[c.salvageable]
            dim = "SalvageCell" if c.salvageable == "yes" else "SalvageDim"
            hit = "SalvageMatch" if self.match is not None and self.match(c) else dim
            better = _better_option(c)
            cells = [
                _label(c.type, hit),
                _label(c.name, hit),
                _label(str(c.size or ""), dim, align=Qt.AlignRight),
                _label(c.grade, dim),
                _label(c.family, dim),
                _label(f"×{c.qty}", dim, align=Qt.AlignRight),
                _label(_money(c.sell), "SalvageBest" if better == "sell" else dim,
                       tip="Selling pays more" if better == "sell" else "",
                       align=Qt.AlignRight),
                _label(_money(c.dismantle), "SalvageBest" if better == "dismantle" else dim,
                       tip="\n".join(filter(None, [
                           "Dismantling pays more" if better == "dismantle" else "",
                           f"Dismantles into: {c.materials_text()}" if c.materials else "",
                       ])),
                       align=Qt.AlignRight),
                _label(mark, style, tip=tip, align=Qt.AlignCenter),
            ]
            for col, cell in enumerate(cells):
                grid.addWidget(cell, r, col)
        grid.setColumnStretch(len(heads), 1)
        v.addLayout(grid)
        v.addWidget(_label("Amber price = the better of selling or dismantling that part.",
                           "InspectorHint"))

        v.addSpacing(4)
        v.addWidget(_label("CARGO ABOARD", "SectionLabel"))
        if row.cargo:
            cg = QGridLayout()
            cg.setHorizontalSpacing(16)
            cg.setVerticalSpacing(3)
            for col, text in enumerate(["Material", "SCU", "UEX avg sell / SCU", "Value"]):
                cg.addWidget(_label(text, "SalvageHead",
                                    align=None if col == 0 else Qt.AlignRight), 0, col)
            for r, c in enumerate(row.cargo, start=1):
                cg.addWidget(_label(c.material), r, 0)
                cg.addWidget(_label(str(c.scu), align=Qt.AlignRight), r, 1)
                cg.addWidget(_label(_money(c.price), align=Qt.AlignRight), r, 2)
                cg.addWidget(_label(_money(c.value), align=Qt.AlignRight), r, 3)
            cg.setColumnStretch(4, 1)
            v.addLayout(cg)
            v.addWidget(_label("As observed by the spreadsheet's author — contents may vary.",
                               "InspectorHint"))
        else:
            v.addWidget(_label("None recorded." if row.in_sheet else "No data yet.", "InspectorHint"))

        v.addSpacing(4)
        v.addWidget(_label("HULL", "SectionLabel"))
        v.addWidget(_label("RMC —    Construction Materials —    (yield database not built yet)",
                           "InspectorHint"))
        return body


# -- the view ------------------------------------------------------------------------

class SalvageView(QWidget):
    back_requested = Signal()

    def __init__(self, channel: str, parent=None):
        super().__init__(parent)
        self.paths = channel_mod.resolve_channel_paths(settings.current().game_root, channel)
        self.game: dict | None = None
        self.sheet: salvage.Sheet | None = None
        self.uex: tuple[float, dict] | None = None
        self.expanded: set[str] = set()
        self._busy: set[str] = set()

        self._worker = _Worker(self)
        self._worker.game_loaded.connect(self._on_game_loaded)
        self._worker.progress.connect(self._show_message)
        self._worker.refreshed.connect(self._on_refreshed)
        self._worker.failed.connect(self._on_failed)

        self._build_ui()

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

        bar.addSpacing(6)
        bar.addWidget(QLabel("CLAIM DIFFICULTY", objectName="ConfigLabel"))
        self.tier_combo = QComboBox(objectName="ConfigCombo")
        self.tier_combo.setMinimumWidth(190)
        self.tier_combo.setToolTip("Adagio salvage claim tier — each spawns ships of one size")
        self.tier_combo.activated.connect(lambda _i: self._render())
        bar.addWidget(self.tier_combo)

        bar.addSpacing(6)
        bar.addWidget(QLabel("SORT", objectName="ConfigLabel"))
        self.sort_combo = QComboBox(objectName="ConfigCombo")
        self.sort_combo.addItem("Net value", "net")
        self.sort_combo.addItem("Name", "name")
        self.sort_combo.activated.connect(lambda _i: self._render())
        bar.addWidget(self.sort_combo)

        bar.addStretch(1)
        self.sources_label = QLabel("", objectName="InspectorHint")
        self.sources_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar.addWidget(self.sources_label)

        self.sheet_btn = QPushButton("Refresh sheet", objectName="MiniButton")
        self.sheet_btn.setToolTip("Download the community salvage spreadsheet again")
        self.sheet_btn.setCursor(Qt.PointingHandCursor)
        self.sheet_btn.clicked.connect(lambda: self._refresh("sheet"))
        bar.addWidget(self.sheet_btn)

        self.uex_btn = QPushButton("Refresh prices", objectName="MiniButton")
        self.uex_btn.setToolTip("Fetch current average commodity prices from UEX")
        self.uex_btn.setCursor(Qt.PointingHandCursor)
        self.uex_btn.clicked.connect(lambda: self._refresh("uex"))
        bar.addWidget(self.uex_btn)
        outer.addLayout(bar)

        fbar = QHBoxLayout()
        fbar.setSpacing(8)
        fbar.addWidget(QLabel("FIND COMPONENT", objectName="ConfigLabel"))
        self.family_combo = QComboBox(objectName="ConfigCombo")
        self.type_combo = QComboBox(objectName="ConfigCombo")
        self.size_combo = QComboBox(objectName="ConfigCombo")
        for combo, tip in ((self.family_combo, "Component class"),
                           (self.type_combo, "Component type"),
                           (self.size_combo, "Component size")):
            combo.setToolTip(tip)
            combo.setMinimumWidth(130)
            combo.activated.connect(lambda _i: self._render())
            fbar.addWidget(combo)
        self.clear_btn = QPushButton("Clear", objectName="MiniButton")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear_filters)
        fbar.addWidget(self.clear_btn)
        fbar.addSpacing(8)
        self.result_label = QLabel("", objectName="InspectorHint")
        fbar.addWidget(self.result_label)
        fbar.addStretch(1)
        outer.addLayout(fbar)

        self.scroll = QScrollArea(objectName="InspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll, stretch=1)
        self._show_message("Loading salvage data…")

    # -- lifecycle ------------------------------------------------------------------
    def activate(self) -> None:
        """Called each time the view is shown."""
        self.sheet = salvage.load_sheet()
        self.uex = salvage.load_uex()
        self._update_sources()
        # First visit: fetch what has never been fetched; afterwards only on request.
        if self.sheet is None:
            self._refresh("sheet")
        if self.uex is None:
            self._refresh("uex")
        if self.game is None:
            self._worker.load_game(self.paths.channel_root)
        else:
            self._render()

    def deactivate(self) -> None:
        pass

    def _on_game_loaded(self, game: dict) -> None:
        self.game = game
        self.tier_combo.clear()
        for tier in game["tiers"]:
            count = len(tier["ships"])
            self.tier_combo.addItem(f"{tier['label']}  ·  {tier['size']} ({count})", tier["id"])
        total = sum(len(t["ships"]) for t in game["tiers"])
        self.tier_combo.addItem(f"All difficulties ({total})", ALL_TIERS)
        idx = self.tier_combo.findData("Easy")
        self.tier_combo.setCurrentIndex(max(idx, 0))

        comps = [c for ship in game["ships"].values() for c in ship["components"]]
        families = sorted({c["family"] for c in comps if c["family"]})
        types = [t for t in salvage.TYPE_ORDER if any(c["type"] == t for c in comps)]
        sizes = sorted({c["size"] for c in comps if c["size"] is not None})
        for combo, label, values, text in (
            (self.family_combo, "Any class", families, str),
            (self.type_combo, "Any type", types, str),
            (self.size_combo, "Any size", sizes, lambda s: f"Size {s}"),
        ):
            combo.clear()
            combo.addItem(label, None)
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
    def _refresh(self, what: str) -> None:
        if what in self._busy:
            return
        self._busy.add(what)
        btn = self.sheet_btn if what == "sheet" else self.uex_btn
        btn.setEnabled(False)
        btn.setText("Refreshing…")
        self._worker.refresh(what)

    def _done(self, what: str) -> None:
        self._busy.discard(what)
        btn = self.sheet_btn if what == "sheet" else self.uex_btn
        btn.setEnabled(True)
        btn.setText("Refresh sheet" if what == "sheet" else "Refresh prices")

    def _on_refreshed(self, what: str) -> None:
        self._done(what)
        if what == "sheet":
            self.sheet = salvage.load_sheet()
        else:
            self.uex = salvage.load_uex()
        self._update_sources()
        self._render()

    def _on_failed(self, what: str, message: str) -> None:
        if what == "game":
            self._show_message(f"Couldn't read Star Citizen's game data:\n\n{message}")
            return
        self._done(what)
        title = "Salvage — spreadsheet" if what == "sheet" else "Salvage — UEX prices"
        QMessageBox.warning(self, title, message + "\n\nThe previous local copy is still used.")

    def _update_sources(self) -> None:
        self.sources_label.setText(
            f"Sheet: {_when(self.sheet.fetched if self.sheet else None)}    "
            f"Prices: {_when(self.uex[0] if self.uex else None)}"
        )

    # -- rendering ----------------------------------------------------------------------
    def _show_message(self, text: str) -> None:
        lbl = QLabel(text, objectName="InspectorHint")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        self.scroll.setWidget(lbl)

    def _render(self) -> None:
        if self.game is None:
            return
        tier_id = self.tier_combo.currentData()
        prices = self.uex[1] if self.uex else {}
        show_all = tier_id == ALL_TIERS
        tiers = [t for t in self.game["tiers"] if show_all or t["id"] == tier_id]
        rows, tier_of = [], {}
        for tier in tiers:
            for row in salvage.build_rows(self.game, tier["id"], self.sheet, prices):
                rows.append(row)
                tier_of[row.stem] = tier["label"]
        match = self._component_filter()
        self.clear_btn.setEnabled(match is not None)
        if match is not None:
            total = len(rows)
            rows = [r for r in rows if any(match(c) for c in r.components)]
            self.result_label.setText(f"{len(rows)} of {total} ships have a salvageable match")
        else:
            self.result_label.setText("")
        if self.sort_combo.currentData() == "name":
            rows.sort(key=lambda r: r.name)
        else:
            rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))

        keep = self.scroll.verticalScrollBar().value()
        page = QWidget(objectName="Inspector")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(6)
        if not rows:
            v.addWidget(_label("No ship at this difficulty has a matching salvageable component.",
                               "InspectorHint", align=Qt.AlignCenter))
        for row in rows:
            card = ShipCard(row, row.stem in self.expanded, match,
                            tier_of[row.stem] if show_all else "")
            card.toggled.connect(self._on_card_toggled)
            v.addWidget(card)
        v.addSpacing(10)
        v.addWidget(self._footer())
        v.addStretch(1)
        page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.scroll.setWidget(page)
        self.scroll.verticalScrollBar().setValue(keep)

    def _on_card_toggled(self, stem: str, on: bool) -> None:
        if on:
            self.expanded.add(stem)
        else:
            self.expanded.discard(stem)

    def _footer(self) -> QWidget:
        box = QFrame(objectName="SidePanel")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(4)
        if self.sheet and self.sheet.where_to_sell:
            v.addWidget(_label("WHERE TO SELL", "SectionLabel"))
            for what, where in self.sheet.where_to_sell:
                lbl = _label(f"<b>{what}</b> — {where}", "InspectorText")
                lbl.setWordWrap(True)
                v.addWidget(lbl)
            v.addSpacing(6)
        if self.sheet and self.sheet.unmatched:
            warn = _label("Spreadsheet ship names not recognised (ignored): "
                          + ", ".join(self.sheet.unmatched), "InspectorNote")
            warn.setWordWrap(True)
            v.addWidget(warn)
        src = QHBoxLayout()
        src.setSpacing(6)
        src.addWidget(_label("Components from the game files · salvage data from the community "
                             "spreadsheet · commodity prices from UEX (average sell).",
                             "InspectorHint"), stretch=1)
        open_sheet = QPushButton("Open spreadsheet", objectName="MiniButton")
        open_sheet.setCursor(Qt.PointingHandCursor)
        open_sheet.clicked.connect(lambda: subprocess.Popen(
            ["xdg-open", salvage.SHEET_URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ))
        src.addWidget(open_sheet)
        v.addLayout(src)
        return box
