"""Mission Database: every mission (contract) in the game files, searchable by
name, contractor or the blueprints it rewards, with the website's filters
and sorts (sc-toolbox.com/missions). Cards in a grid; clicking one opens its
details in a pane on the right.

Launcher extra: "Blueprints you don't have" works without signing in — the
blueprints you received come from your own Game.logs (LIVE).

Data: app.contracts via app.datahub (built once per game version).
"""

from __future__ import annotations

import html
import re
import threading
import traceback

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.channel import PERSISTENT_CHANNELS
from app import channel as channel_mod, contracts as contracts_mod, datahub, gamelog, settings
from app.ui import kit
from app.ui.kit import Badge, label
from app.ui.widgets import Elided

WEB_URL = "https://sc-toolbox.com/missions"
PAGE = 60                      # cards shown before "Show more"
CARD_MIN_WIDTH = 300
CARD_HEIGHT = 168
DETAIL_WIDTH = 400
BLUEPRINT_CHANNELS = PERSISTENT_CHANNELS   # LIVE and HOTFIX share one universe
STAR_SYSTEMS = ("Stanton", "Pyro", "Nyx")      # "systems" in the data also holds some places

# Limited-time events, by the generator or sub-generator ("handler") their
# missions come from (the website's MissionsDataset.EVENTS). The game files
# don't say whether an event is running, so they're hidden until picked.
EVENTS = {
    "generator:CleanAir": "CleanAir",
    "generator:VisitingIasi": "RSI Discovery Month",
    "handler:ORS": "Orison Relief (ORS)",
    "handler:RoX": "Reign of Xenothreat",
}

SORTS = [
    ("Name", "title"),
    ("Most rep", "rep"),
    ("Most blueprints", "blueprints"),
    ("Blueprints you don't have", "missing"),
    ("Quickest", "time"),
    ("Easiest", "difficulty"),
    ("Contractor", "contractor"),
]

# Toggles under "More filters": (key, label, test)
TOGGLES = [
    ("bp", "Rewards blueprints", lambda m: bool(m["bp_items"])),
    ("missing", "Blueprints you don't have", lambda m: m["missing"] > 0),
    ("pay", "Fixed pay", lambda m: m["payout"] is not None),
    ("items", "Item rewards", lambda m: bool(m["items"])),
    ("ship", "Ship combat", lambda m: "ship" in m["combat"]),
    ("fps", "On-foot combat", lambda m: "fps" in m["combat"]),
    ("cargo", "Carries cargo", lambda m: m["scu"] > 0),
    ("repeat", "Repeatable", lambda m: not m["once_only"]),
    ("solo", "Not part of a chain", lambda m: not m["chain"]),
]


def mission_hue(kind: str) -> str | None:
    """A mission type's category hue, by the words the game's types use
    (the website's missionHue)."""
    t = (kind or "").lower()
    for pattern, hue in ((r"mercenary|bounty|priority|security|assassin", "combat"),
                         (r"haul|deliver|courier|cargo", "hauling"),
                         (r"mining|salvage|refuel|maintenance", "industry"),
                         (r"investigation|missing|search|recover", "search"),
                         (r"racing", "racing"), (r"wikelo|collection|trade|battaglia", "trade"),
                         (r"event", "event")):
        if re.search(pattern, t):
            return hue
    return None


def _minutes(value) -> str:
    if not value:
        return "—"
    value = round(value)
    return f"{value // 60} h {value % 60:02d} min" if value >= 60 else f"{value} min"


def _summary(c: dict, owned: set[str]) -> dict:
    """One contract as the view needs it (computed once per load)."""
    items = sorted({n for pool in c.get("blueprints") or [] for n in pool.get("items") or []})
    levels = [d.get("level") or 0 for d in (c.get("difficulty_detail") or {}).values() if d.get("level")]
    cargo = c.get("cargo") or []
    event = EVENTS.get(f"generator:{c.get('generator')}") or EVENTS.get(f"handler:{c.get('handler')}")
    m = {
        "c": c,
        "title": c.get("title") or c.get("debug") or "Untitled",
        "contractor": c.get("contractor") or c.get("faction") or "",
        "type": c.get("type") or "",
        "systems": [x for x in c.get("systems") or [] if x in STAR_SYSTEMS],
        "illegal": bool(c.get("illegal")),
        "rep": c.get("rep"),
        "rank": c.get("rank") or "",
        "minutes": c.get("est_minutes"),
        "payout": c.get("payout"),
        "items": c.get("items") or [],
        "combat": c.get("combat") or [],
        "scu": sum(max(x.get("min_scu") or 0, x.get("max_scu") or 0) for x in cargo),
        "once_only": bool(c.get("once_only")),
        "chain": int(c.get("needs_completed") or 0),
        "event": event,
        "difficulty": round(sum(levels) / len(levels) * 2) / 2 if levels else None,
        "bp_items": items,
        "missing": sum(1 for n in items if contracts_mod.blueprint_key(n) not in owned),
    }
    resources = [(x.get("resource") or "").replace("[!]", "").strip() for x in cargo]
    m["text"] = " ".join([m["title"], m["contractor"], c.get("faction") or "", m["type"], *items, *resources]).lower()
    return m


class _OwnedLoader(QObject):
    """The blueprints you received on LIVE, from every Game.log on disk."""

    loaded = Signal(object)

    def run(self) -> None:
        def work():
            owned: set[str] = set()
            try:
                for e in gamelog.read_history(settings.current().game_root, ["blueprint"]):
                    if e.channel.upper() in BLUEPRINT_CHANNELS:
                        owned.add(contracts_mod.blueprint_key(e.data.get("name", "")))
            except Exception:
                traceback.print_exc()
            from app import owned as owned_mod

            owned |= owned_mod.online_owned()       # Sync online: the website's collection too
            self.loaded.emit(owned)
        threading.Thread(target=work, daemon=True).start()


# -- a card ---------------------------------------------------------------------------

class MissionCard(QFrame):
    clicked = Signal(object)

    def __init__(self, m: dict, matched: list[str], selected: bool, owned_known: bool, parent=None):
        super().__init__(parent, objectName="MissionCard")
        self.m = m
        self.setProperty("selected", selected)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(CARD_HEIGHT)
        self.setMinimumWidth(CARD_MIN_WIDTH - 20)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 11, 14, 11)
        v.setSpacing(4)
        v.addWidget(Elided(m["title"], "CardTitle", m["title"]))
        v.addWidget(Elided(m["contractor"] or "Unlisted contractor", "MutedText"))
        badges = QHBoxLayout()
        badges.setSpacing(5)
        shown = 0
        for text, variant, hue in self._badges(m):
            if shown >= 4:
                break
            badges.addWidget(Badge(text, variant, hue))
            shown += 1
        badges.addStretch(1)
        v.addLayout(badges)
        v.addStretch(1)
        stats = QHBoxLayout()
        stats.setSpacing(16)
        for caption, value in self._stats(m):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(kit.caps(caption))
            col.addWidget(label(value, "StatSmall"))
            stats.addLayout(col)
        stats.addStretch(1)
        v.addLayout(stats)
        if matched:
            line = Elided("Blueprint: " + ", ".join(matched), "MatchText")
        elif m["bp_items"]:
            n = len(m["bp_items"])
            text = f"{n} blueprint{'s' if n != 1 else ''}"
            if owned_known:
                text += f" · {m['missing']} you don't have" if m["missing"] else " · you have them all"
            line = label(text, "BestText" if owned_known and m["missing"] else "MutedText")
        else:
            line = label("No blueprint reward", "MutedText")
        v.addWidget(line)

    @staticmethod
    def _badges(m: dict) -> list[tuple[str, str, str | None]]:
        out = []
        if m["type"]:
            out.append((m["type"], "neutral", mission_hue(m["type"])))
        for s in m["systems"][:2]:
            out.append((s, "neutral", s.lower()))
        if not m["systems"]:
            out.append(("Anywhere", "neutral", None))
        if m["event"]:
            out.append((m["event"], "neutral", "event"))
        if m["illegal"]:
            out.append(("Illegal", "warning", None))
        if "ship" in m["combat"]:
            out.append(("Ship combat", "neutral", "combat"))
        if "fps" in m["combat"]:
            out.append(("On foot", "neutral", "combat"))
        return out

    @staticmethod
    def _stats(m: dict) -> list[tuple[str, str]]:
        out = [("Rep", f"+{m['rep']:,}" if m["rep"] else "—"),
               ("Rank", m["rank"] or "Any"),
               ("Time", _minutes(m["minutes"]))]
        if m["payout"]:
            out.append(("Pay", f"{m['payout']['amount']:,} {m['payout'].get('currency', 'aUEC')}"))
        elif m["scu"]:
            out.append(("Cargo", f"{m['scu']:g} SCU"))
        return out

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.m)
        super().mouseReleaseEvent(event)


# -- the detail pane --------------------------------------------------------------------

class _DetailPane(QFrame):
    closed = Signal()
    open_mining = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, objectName="Panel")
        self.setFixedWidth(DETAIL_WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 10, 8, 0)
        head.addWidget(kit.caps("Mission"))
        head.addStretch(1)
        close = QPushButton("✕", objectName="NoticeClose")
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(24, 24)
        close.setToolTip("Close")
        close.clicked.connect(self.closed.emit)
        head.addWidget(close)
        outer.addLayout(head)
        self.scroll = kit.scroll_area()
        outer.addWidget(self.scroll, stretch=1)

    def show_mission(self, m: dict, owned: set[str] | None) -> None:
        c = m["c"]
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 4, 14, 16)
        v.setSpacing(8)
        v.addWidget(label(m["title"], "DetailTitle", wrap=True))
        v.addWidget(label(m["contractor"] or "Unlisted contractor", "BodyText"))
        badges = QHBoxLayout()
        badges.setSpacing(5)
        for text, variant, hue in MissionCard._badges(m)[:5]:
            badges.addWidget(Badge(text, variant, hue))
        badges.addStretch(1)
        v.addLayout(badges)
        if c.get("description"):
            desc = label(html.escape(c["description"][:1600]).replace("\n", "<br>"), "BodyText", wrap=True, rich=True)
            v.addWidget(desc)

        facts = []
        where = list(dict.fromkeys((c.get("systems") or []) + (c.get("locations") or [])))
        facts.append(("Where", ", ".join(where) or "Anywhere"))
        if c.get("rank") or c.get("max_rank"):
            facts.append(("Rank", (c.get("rank") or "Any") + (f" – {c['max_rank']}" if c.get("max_rank") else "")))
        if m["rep"]:
            facts.append(("Reputation", f"+{m['rep']:,}"))
        if m["payout"]:
            facts.append(("Pay", f"{m['payout']['amount']:,} {m['payout'].get('currency', 'aUEC')} (fixed)"))
        elif c.get("calculated_payout"):
            facts.append(("Pay", "Worked out by the server when offered"))
        for item in m["items"]:
            facts.append(("Item reward", f"{item.get('amount', 1)} × {item.get('name', '')}"))
        for cg in c.get("cargo") or []:
            low, high = cg.get("min_scu") or 0, cg.get("max_scu") or 0
            amount = f"{low:g} SCU" if not high or high == low else f"{low:g}–{high:g} SCU"
            facts.append(("Cargo", f"{cg.get('resource', '').replace('[!]', '').strip()} · {amount}"))
        if c.get("salvage_percent"):
            facts.append(("Salvage", f"{c['salvage_percent']}% of the hull"))
        times = []
        if m["minutes"]:
            times.append(f"~{_minutes(m['minutes'])}")
        if c.get("deadline_minutes"):
            times.append(f"{_minutes(c['deadline_minutes'])} limit")
        if times:
            facts.append(("Time", " · ".join(times)))
        if (c.get("max_players") or 0) > 1:
            facts.append(("Players", f"up to {c['max_players']}"))
        if m["chain"]:
            facts.append(("Chain", f"Needs {m['chain']} earlier mission{'s' if m['chain'] != 1 else ''} completed"))
        if m["once_only"]:
            facts.append(("Repeat", "Once only"))
        detail = c.get("difficulty_detail") or {}
        if detail:
            facts.append(("Difficulty", " · ".join(f"{k} {d['level']}/7" for k, d in detail.items())))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        for i, (k, val) in enumerate(facts):
            grid.addWidget(label(k, "MutedText"), i, 0, Qt.AlignTop)
            grid.addWidget(label(val, "BodyText", wrap=True), i, 1)
        v.addWidget(kit.caps("Details"))
        v.addLayout(grid)

        pools = c.get("blueprints") or []
        if pools:
            have = sum(1 for n in m["bp_items"] if owned is not None and contracts_mod.blueprint_key(n) in owned)
            chance = max((p.get("chance") or 0) for p in pools)
            title = f"Possible blueprints · {len(m['bp_items'])}"
            if owned is not None:
                title += f" · {have} you have"
            v.addSpacing(4)
            v.addWidget(kit.caps(title))
            v.addWidget(label(f"One of these on completion ({chance:.0%} chance in the game data)."
                              + (" ✓ = you received it (from your logs)." if owned is not None else ""),
                              "MutedText", wrap=True))
            for name in m["bp_items"]:
                got = owned is not None and contracts_mod.blueprint_key(name) in owned
                v.addWidget(label(("✓  " if got else "•  ") + name, "BestText" if got else "BodyText", wrap=True))
        stages = c.get("stages") or []
        if stages:
            v.addSpacing(4)
            v.addWidget(kit.caps("Stages"))
            for i, st in enumerate(stages, 1):
                v.addWidget(label(f"{i}. {st.get('name', '')}", "BodyText", wrap=True))
        for cg in c.get("cargo") or []:
            res = (cg.get("resource") or "").replace("[!]", "").strip()
            if res:
                v.addSpacing(4)
                v.addWidget(kit.button(f"Find {res} in the Mining Finder →", "ghost",
                                       lambda _c=False, r=res: self.open_mining.emit(r)), alignment=Qt.AlignLeft)
                break
        v.addStretch(1)
        self.scroll.setWidget(page)
        self.scroll.verticalScrollBar().setValue(0)


# -- the view ------------------------------------------------------------------------

class MissionsView(kit.ToolPage):
    def __init__(self, channel: str, parent=None):
        super().__init__("missions", "Mission Database",
                         "Every mission in the game: search by name, contractor, cargo or the blueprints it rewards",
                         web_url=WEB_URL, parent=parent)
        self.channel = channel
        self.paths = channel_mod.resolve_channel_paths(settings.current().game_root, channel)
        self.missions: list[dict] = []
        self._raw: list[dict] = []
        self.owned: set[str] | None = None
        self.shown = PAGE
        self.selected: dict | None = None
        self._columns = 2
        self._loader = datahub.GameDataWaiter("contracts", self)
        self._loader.ready.connect(self._on_loaded)
        self._loader.progress.connect(self.show_message)
        self._loader.failed.connect(lambda msg: self.show_empty(
            "Couldn't read the game files", msg.splitlines()[0] if msg else "",
            "Open Settings", lambda: self.window().show_tool("settings")))
        self._owned_loader = _OwnedLoader(self)
        self._owned_loader.loaded.connect(self._on_owned)
        self._debounce = QTimer(self, singleShot=True, interval=180, timeout=self._render)
        self._build_ui()

    # -- layout ---------------------------------------------------------------------
    def _build_ui(self) -> None:
        f = self.filters
        self.search = f.add_search("Mission, contractor or blueprint", 260)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        self.systems = kit.Segmented([(None, "All")], None)
        self.systems.changed.connect(lambda _v: self._render())
        f.add(self.systems)
        self.type_combo = kit.Dropdown(min_width=120, tip="Mission type")
        self.type_combo.activated.connect(lambda _i: self._render())
        f.add(self.type_combo)
        self.contractor_combo = kit.Dropdown(min_width=140, tip="Contractor")
        self.contractor_combo.setMaxVisibleItems(24)
        self.contractor_combo.activated.connect(lambda _i: self._render())
        f.add(self.contractor_combo)
        self.more_btn = kit.button("More filters", checkable=True)
        self.more_btn.toggled.connect(lambda on: self.more_panel.setVisible(on))
        f.add(self.more_btn)
        self.sort = kit.Dropdown(SORTS, marks=False)
        self.sort.activated.connect(lambda _i: self._render())
        f.add_sort(self.sort)

        self.more_panel = QFrame(objectName="FilterBar")
        mv = QVBoxLayout(self.more_panel)
        mv.setContentsMargins(10, 8, 10, 8)
        mv.setSpacing(8)
        first = QHBoxLayout()
        first.setSpacing(8)
        self.legal = kit.Segmented([("", "Legal and illegal"), ("legal", "Legal"), ("illegal", "Illegal")], "")
        self.legal.changed.connect(lambda _v: self._render())
        first.addWidget(self.legal)
        first.addSpacing(6)
        first.addWidget(kit.caps("Events"))
        self.event_combo = kit.Dropdown(min_width=170, tip="Event missions are hidden until you pick an event")
        self.event_combo.activated.connect(lambda _i: self._render())
        first.addWidget(self.event_combo)
        first.addStretch(1)
        mv.addLayout(first)
        self.toggles: dict[str, QPushButton] = {}
        for caption, keys in (("Rewards", ("bp", "missing", "pay", "items")),
                              ("The work", ("ship", "fps", "cargo", "repeat", "solo"))):
            line = QHBoxLayout()
            line.setSpacing(6)
            cap = kit.caps(caption)
            cap.setFixedWidth(74)
            line.addWidget(cap)
            for key, text, _test in TOGGLES:
                if key not in keys:
                    continue
                btn = QPushButton(text, objectName="ToggleChip")
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.toggled.connect(lambda _on: self._render())
                self.toggles[key] = btn
                line.addWidget(btn)
            line.addStretch(1)
            mv.addLayout(line)
        self.more_panel.hide()
        self.add_filter_panel(self.more_panel)
        self.result.clear_requested.connect(self._clear)

        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.grid_scroll = kit.scroll_area()
        row.addWidget(self.grid_scroll, stretch=1)
        self.detail = _DetailPane()
        self.detail.closed.connect(self._close_detail)
        self.detail.open_mining.connect(lambda r: self.open_tool.emit("mining", r))
        self.detail.hide()
        row.addWidget(self.detail)
        self.set_content(body)
        self.show_message("Loading the mission database…")

    def add_filter_panel(self, panel: QWidget) -> None:
        lay = self.layout()
        lay.insertWidget(lay.indexOf(self.filters) + 1, panel)

    # -- lifecycle ------------------------------------------------------------------
    def activate(self) -> None:
        if not self._raw:
            self._loader.request(self.paths.channel_root)
        if self.owned is None:
            self._owned_loader.run()

    def focus_on(self, text: str) -> None:
        """Links from other tools: search for this (a mission, contractor or blueprint)."""
        self.search.setText(str(text))
        self._render()

    def _on_loaded(self, data) -> None:
        self._raw = data.all() if hasattr(data, "all") else list((data or {}).get("contracts", {}).values())
        self._summarise()
        systems = [s for s in STAR_SYSTEMS if any(s in m["systems"] for m in self.missions)]
        self.systems.set_options([(None, "All")] + [(s, s) for s in systems], self.systems.value())
        self._fill_combo(self.type_combo, "All types", [m["type"] for m in self.missions])
        self._fill_combo(self.contractor_combo, "All contractors", [m["contractor"] for m in self.missions])
        events = [m["event"] for m in self.missions if m["event"]]
        self.event_combo.clear()
        self.event_combo.addItem("Events hidden", None)
        for name in sorted(set(events)):
            self.event_combo.addItem(f"{name} ({events.count(name)})", name)
        self.event_combo.addItem("All events", "*")
        self.set_data_chip(f"Game data <b>{self.channel}</b> · {len(self.missions):,} missions")
        self._render()

    def _on_owned(self, owned: set) -> None:
        self.owned = owned
        if self._raw:
            self._summarise()
            self._render()

    def _summarise(self) -> None:
        owned = self.owned or set()
        self.missions = [_summary(c, owned) for c in self._raw]
        self.toggles["missing"].setEnabled(self.owned is not None)

    @staticmethod
    def _fill_combo(combo, first: str, values: list[str]) -> None:
        current = combo.currentData()
        counts: dict[str, int] = {}
        for v in values:
            if v:
                counts[v] = counts.get(v, 0) + 1
        combo.clear()
        combo.addItem(first, None)
        for v in sorted(counts, key=str.lower):
            combo.addItem(f"{v} ({counts[v]})", v)
        i = combo.findData(current)
        combo.setCurrentIndex(max(0, i))

    # -- filtering -------------------------------------------------------------------
    def _clear(self) -> None:
        self.search.clear()
        self.systems.set_value(None)
        for combo in (self.type_combo, self.contractor_combo, self.event_combo):
            combo.setCurrentIndex(0)
        self.legal.set_value("")
        for btn in self.toggles.values():
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        self._render()

    def _visible(self) -> tuple[list[dict], int]:
        words = self.search.text().lower().split()
        system = self.systems.value()
        kind = self.type_combo.currentData()
        contractor = self.contractor_combo.currentData()
        legal = self.legal.value()
        event = self.event_combo.currentData()
        tests = [t for key, _l, t in TOGGLES if self.toggles[key].isChecked()]
        hidden = 0
        out = []
        for m in self.missions:
            if m["event"] and event != "*" and m["event"] != event:
                hidden += 1
                continue
            if system and m["systems"] and system not in m["systems"]:
                continue
            if kind and m["type"] != kind:
                continue
            if contractor and m["contractor"] != contractor:
                continue
            if legal and m["illegal"] != (legal == "illegal"):
                continue
            if any(not t(m) for t in tests):
                continue
            if words and not all(w in m["text"] for w in words):
                continue
            out.append(m)
        key = self.sort.currentData()
        sorters = {
            "title": (lambda m: m["title"].lower(), False),
            "rep": (lambda m: m["rep"] or -1, True),
            "blueprints": (lambda m: len(m["bp_items"]), True),
            "missing": (lambda m: m["missing"], True),
            "time": (lambda m: m["minutes"] or 1e6, False),
            "difficulty": (lambda m: m["difficulty"] if m["difficulty"] is not None else 8, False),
            "contractor": (lambda m: m["contractor"].lower(), False),
        }
        by, desc = sorters.get(key, sorters["title"])
        out.sort(key=lambda m: m["title"].lower())
        out.sort(key=by, reverse=desc)
        return out, hidden

    def _chips(self) -> list:
        chips = []
        if self.search.text().strip():
            chips.append((f"“{self.search.text().strip()}”", lambda _c=False: self.search.clear()))
        if self.systems.value():
            chips.append((self.systems.value(), lambda _c=False: (self.systems.set_value(None), self._render())))
        for combo in (self.type_combo, self.contractor_combo, self.event_combo):
            if combo.currentIndex() > 0:
                chips.append((combo.currentText().rsplit(" (", 1)[0],
                              lambda _c=False, c=combo: (c.setCurrentIndex(0), self._render())))
        if self.legal.value():
            chips.append((self.legal.value().title(), lambda _c=False: (self.legal.set_value(""), self._render())))
        for key, text, _t in TOGGLES:
            if self.toggles[key].isChecked():
                chips.append((text, lambda _c=False, b=self.toggles[key]: b.setChecked(False)))
        return chips

    # -- rendering ----------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._relayout)

    def _wanted_columns(self) -> int:
        width = self.body.width() - (DETAIL_WIDTH + 12 if self.detail.isVisible() else 0) - 14
        return max(1, min(4, width // CARD_MIN_WIDTH))

    def _relayout(self) -> None:
        if self._wanted_columns() != self._columns and self.missions:
            self._render(keep_page=True)

    def _render(self, keep_page: bool = False) -> None:
        if not self.missions:
            return
        if not keep_page:
            self.shown = PAGE
        visible, hidden = self._visible()
        total = len(self.missions)
        n = len(visible)
        text = f"{n:,} of {total:,} missions" if n != total else f"{total:,} missions"
        if hidden:
            text += f" · {hidden} event missions hidden (pick an event under More filters)"
        self.result.set_count(text)
        self.result.set_chips(self._chips())
        self.show_content()
        if not visible:
            self.grid_scroll.setWidget(kit.EmptyState(
                "No mission matches",
                "Try fewer words, another system or type, or clear the filters.", "Clear filters", self._clear))
            return
        words = self.search.text().lower().split()
        self._columns = self._wanted_columns()
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(10)
        cols = self._columns
        for i, m in enumerate(visible[:self.shown]):
            matched = []
            if words:
                head = f"{m['title']} {m['contractor']} {m['type']}".lower()
                if not all(w in head for w in words):
                    matched = [b for b in m["bp_items"] if any(w in b.lower() for w in words)][:3]
            card = MissionCard(m, matched, m is self.selected, self.owned is not None)
            card.clicked.connect(self._open_detail)
            grid.addWidget(card, i // cols, i % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        rows = (min(len(visible), self.shown) + cols - 1) // cols
        if len(visible) > self.shown:
            more = kit.button(f"Show more ({len(visible) - self.shown:,} left)", slot=self._show_more)
            grid.addWidget(more, rows, 0, 1, cols, Qt.AlignHCenter)
            rows += 1
        grid.setRowStretch(rows, 1)
        keep = self.grid_scroll.verticalScrollBar().value() if keep_page else 0
        self.grid_scroll.setWidget(host)
        self.grid_scroll.verticalScrollBar().setValue(keep)

    def _show_more(self) -> None:
        self.shown += PAGE
        self._render(keep_page=True)

    def _open_detail(self, m: dict) -> None:
        self.selected = m
        self.detail.show_mission(m, self.owned)
        self.detail.show()
        QTimer.singleShot(0, lambda: self._render(keep_page=True))

    def _close_detail(self) -> None:
        self.selected = None
        self.detail.hide()
        QTimer.singleShot(0, lambda: self._render(keep_page=True))
