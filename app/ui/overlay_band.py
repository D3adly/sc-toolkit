"""The overlay's horizontal layout, the band (#74): each tool's view laid out
as columns side by side, a few lines tall, instead of the tall panel.

The data and following logic is the vertical panels' (overlay_live,
overlay_panels): each band view subclasses its panel and only lays the page
out differently. Columns scroll on their own and keep their place across
re-renders; when the band is too narrow, the least important columns hide.
"""

from __future__ import annotations

import html
import time
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import mining
from app.stats import pretty
from app.theme import PALETTE
from app.ui import kit, overlay_live as live
from app.ui.kit import Badge, label
from app.ui.mining_view import KIND_LABELS, LocationCard, _pct
from app.ui.overlay_panels import MapsPanel, MiningPanel, SalvagePanel, _Clickable, _combo, _label
from app.ui.salvage_view import ShipRowWidget

COL_MIN = 190            # a column's least width; below the sum of these, columns hide
KEEP_SCROLL_MS = 300     # gives up waiting for a rebuilt column to reach its old scroll position


# -- the column kit -------------------------------------------------------------------
class BandColumn(QFrame):
    """A titled column: fixed controls on top (`head`, never rebuilt, so an
    open list survives a re-render), then a page that scrolls and is rebuilt
    with page(), keeping its scroll position."""

    def __init__(self, title: str = "", weight: int = 2, priority: int = 1, min_width: int = COL_MIN):
        super().__init__(objectName="BandColumn")
        self.weight, self.priority, self.min_width = weight, priority, min_width
        # No hard minimum (it would hold the whole band wide): min_width only decides what hides.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 7, 6, 5)
        v.setSpacing(4)
        self.title = QLabel(title, objectName="BandColLabel")
        self.title.setVisible(bool(title))
        v.addWidget(self.title)
        self.head = QVBoxLayout()
        self.head.setSpacing(4)
        v.addLayout(self.head)
        self.scroll = QScrollArea(objectName="InspectorScroll")   # (transparent, as the panels' pages)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(self.scroll, stretch=1)

    def set_title(self, text: str) -> None:
        self.title.setText(text)
        self.title.setVisible(bool(text))

    def page(self) -> QVBoxLayout:
        """A new, empty page (the old one goes); the scroll position stays."""
        bar = self.scroll.verticalScrollBar()
        keep = bar.value()
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()        # not at once: a click in it may have caused this
        page = QWidget(objectName="Inspector")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(3)
        self.scroll.setWidget(page)
        if keep > 0:
            pending = [True]

            def restore(_low: int = 0, high: int = 0, final: bool = False) -> None:
                if pending[0] and (high >= keep or final):
                    pending[0] = False
                    bar.setValue(min(keep, bar.maximum()))
                    bar.rangeChanged.disconnect(restore)

            bar.rangeChanged.connect(restore)
            QTimer.singleShot(KEEP_SCROLL_MS, lambda: restore(final=True))
        return v


class BandColumns(QWidget):
    """Columns side by side, sized by weight. Too narrow for all of them at
    their least width: the lowest-priority ones hide (the highest number, the
    rightmost first)."""

    def __init__(self, columns: list[BandColumn]):
        super().__init__()
        self.columns = columns
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        for c in columns:
            h.addWidget(c, stretch=c.weight)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        shown = list(self.columns)
        while len(shown) > 1 and sum(c.min_width for c in shown) > max(self.width(), 1):
            shown.remove(max(shown, key=lambda c: (c.priority, self.columns.index(c))))
        first = True
        for c in self.columns:
            c.setVisible(c in shown)
            if c in shown:
                c.setProperty("first", first)
                c.style().unpolish(c)
                c.style().polish(c)
                first = False


class _BandBody:
    """Mixin: swaps a vertical panel's page for columns, plus a full-width
    message line (loading, live log off, nothing yet)."""

    def _band_setup(self, columns: list[BandColumn]) -> None:
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setObjectName("BandBody")
        self.columns = BandColumns(columns)
        self._msg_box = QWidget()
        mv = QVBoxLayout(self._msg_box)
        mv.setContentsMargins(16, 10, 16, 10)
        mv.addStretch(1)
        self._msg_title = QLabel("", objectName="BandMsgTitle", alignment=Qt.AlignCenter)
        mv.addWidget(self._msg_title)
        self._msg_text = QLabel("", objectName="BandText", alignment=Qt.AlignCenter)
        self._msg_text.setWordWrap(True)
        mv.addWidget(self._msg_text)
        self._msg_btn = QPushButton("", objectName="MiniButton")
        self._msg_btn.setCursor(Qt.PointingHandCursor)
        self._msg_slot = None
        self._msg_btn.clicked.connect(lambda: self._msg_slot and self._msg_slot())
        mv.addWidget(self._msg_btn, alignment=Qt.AlignHCenter)
        mv.addStretch(1)
        self._band_stack = QStackedWidget()
        self._band_stack.addWidget(self.columns)
        self._band_stack.addWidget(self._msg_box)
        layout.addWidget(self._band_stack)

    def show_message(self, text: str, title: str = "", button: tuple[str, object] | None = None) -> None:
        self._msg_title.setText(title)
        self._msg_title.setVisible(bool(title))
        self._msg_text.setText(text)
        self._msg_btn.setVisible(button is not None)
        if button:
            self._msg_btn.setText(button[0])
            self._msg_slot = button[1]
        self._band_stack.setCurrentWidget(self._msg_box)

    def show_columns(self) -> None:
        self._band_stack.setCurrentWidget(self.columns)

    # The vertical panels' own message page → the message line.
    def _message(self, text: str, title: str = "") -> None:
        if hasattr(self, "_band_stack"):     # (the vertical panel's __init__ calls it before there is one)
            self.show_message(text.replace("\n", " "), title)


def _hrow(*widgets, stretch_last: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    for w in widgets:
        row.addWidget(w)
    if not stretch_last:
        row.addStretch(1)
    return row


# -- live log: the state shared by Missions and Session --------------------------------
class _LiveBand(_BandBody):
    def _render(self) -> None:
        self._build()          # each column keeps its own scroll position

    def _state_message(self) -> bool:
        f = live.feed()
        if f.state == "disabled":
            self.show_message("The live log reader is off. Turn on LIVE LOG to follow your missions and "
                              "session here.", button=("Turn on live log", f.request_enable))
            return True
        if f.state in ("off", "waiting") and not f.tracker.session:
            self.show_message("Waiting for Star Citizen… This fills in as soon as the game is running.")
            return True
        self.show_columns()
        return False


# -- Missions -------------------------------------------------------------------------
class MissionsBand(_LiveBand, live.MissionsPanel):
    """The mission you're on (or picked), its objectives, reward or outcome,
    the blueprints it can drop and its details, side by side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_mission = BandColumn("MISSION", 3, 1, 230)
        self.c_objectives = BandColumn("OBJECTIVES", 3, 1, 220)
        self.c_reward = BandColumn("REWARD", 2, 2)
        self.c_blueprints = BandColumn("POSSIBLE BLUEPRINTS", 2, 2)
        self.c_details = BandColumn("DETAILS", 2, 3)
        self.pick = _combo()
        self.pick.activated.connect(self._on_pick)
        self.c_mission.head.addWidget(self.pick)
        self._band_setup([self.c_mission, self.c_objectives, self.c_reward, self.c_blueprints, self.c_details])
        self._ids: list[str] = []
        self._picked: str | None = None      # a mission picked in the list (else: the tracked one)
        self._last_tracked: str | None = None
        self._last_current = None

    def _on_pick(self, index: int) -> None:
        if 0 <= index < len(self._ids):
            self._picked = self._ids[index]
            self._build()

    def _build(self) -> None:
        if self._state_message():
            return
        f = live.feed()
        tr = f.tracker
        owned = ({live.blueprint_key(n) for n in f.owned_for(tr.channel)}
                 | {live.blueprint_key(n) for _t, n, _m in tr.blueprints})
        rewards = {m.id: age for m in tr.missions.values() if (age := live._reward_age(m)) is not None}
        active = tr.active_missions()
        tracked = self._tracked(active)
        self._update_flash(tracked)
        shown = [m for m in tr.missions.values() if m.active or m.id in rewards]
        shown.sort(key=lambda m: (m is not tracked, -live._activity(m).timestamp()))
        finished = sorted((m for m in tr.finished_missions() if m.id not in rewards),
                          key=lambda m: m.outcome != "Complete")
        missions = shown + finished
        if not missions:
            self.show_message("No missions this session yet. Accept a contract and it shows up here.",
                              "NO ACTIVE MISSIONS")
            return
        # A newly tracked mission takes over from an older pick.
        if tracked is not None and tracked.id != self._last_tracked:
            self._last_tracked, self._picked = tracked.id, None
        ids = [m.id for m in missions]
        if self._picked not in ids:
            self._picked = None
        m = next(x for x in missions if x.id == (self._picked or ids[0]))
        info = f.contract(m)

        # The list of missions (not refilled while it's open).
        lst = getattr(self.pick, "_list", None)
        if lst is None or not lst.isVisible():
            self.pick.blockSignals(True)
            self.pick.clear()
            for x in missions:
                prefix = "▶ " if x is tracked else ("✓ " if x.outcome == "Complete" else
                                                    "✕ " if not x.active else "")
                self.pick.addItem(prefix + live._mission_title(x, f.contract(x)))
            self.pick.setCurrentIndex(ids.index(m.id))
            self.pick.blockSignals(False)
        self._ids = ids
        self.pick.setVisible(len(missions) > 1)
        n_active = len(active)
        self.c_mission.set_title(f"MISSION · {ids.index(m.id) + 1} OF {len(missions)}"
                                 + (f" · {n_active} ACTIVE" if n_active != len(missions) else ""))
        state = "reward" if m.id in rewards else ("tracked" if m is tracked else
                                                  "" if m.active else "done" if m.outcome == "Complete" else "failed")
        self.c_mission.setProperty("state", state)
        self.c_mission.setProperty("flash", m.id in self._flash_until)
        self.c_mission.style().unpolish(self.c_mission)
        self.c_mission.style().polish(self.c_mission)

        # Mission: title (when there's no list), tags, contractor, time.
        v = self.c_mission.page()
        if len(missions) == 1:
            v.addWidget(_label(live._mission_title(m, info), "LiveTitle", wrap=True))
        tags = live._tags(info)[:3]
        if tags:
            v.addLayout(_hrow(*tags))
        v.addWidget(_label(live._contractor(m, info), "LiveMuted", wrap=True))
        if m.active:
            limit = (info or {}).get("deadline_minutes")
            # "on it" counts from acceptance; the limit isn't a countdown until we know when it starts.
            v.addWidget(_label(f"on it {live._ago(m.accepted)}"
                               + (f" · limit {live._minutes(limit)}" if limit else ""), "LiveText"))
        elif m.outcome == "Complete":
            v.addLayout(_hrow(live._chip("COMPLETE", "good"), _label(live._clock(m.ended), "LiveMuted")))
        else:
            v.addLayout(_hrow(live._chip(live.OUTCOMES.get(m.outcome, m.outcome).upper(), "bad"),
                              _label(live._clock(m.ended), "LiveMuted")))
        v.addStretch(1)

        # Objectives
        v = self.c_objectives.page()
        objectives = m.visible_objectives
        current = m.current_objective
        current_label = None
        if not objectives:
            v.addWidget(_label("No objectives in the log yet", "LiveMuted", wrap=True))
        for o in objectives:
            if o is current and m.active:
                current_label = _label(f"▶  {o.text}", "LiveObjective", wrap=True)
                v.addWidget(current_label)
            else:
                mark = "✓" if o.done else "○"
                v.addWidget(_label(f"{mark}  {o.text}", "LiveMuted" if o.done else "LiveText", wrap=True))
        v.addStretch(1)
        key = (m.id, current.text if current is not None else None)
        if current_label is not None and key != self._last_current:
            # A new current objective: bring it into sight (else the reader's scroll position stays).
            QTimer.singleShot(50, lambda: current_label and self.c_objectives.scroll.ensureWidgetVisible(
                current_label, 0, 10))
        self._last_current = key

        # Reward / outcome
        v = self.c_reward.page()
        chips = live._rewards(m, info)
        for c in chips:
            v.addWidget(c, alignment=Qt.AlignLeft)
        if not chips:
            v.addWidget(_label("No reputation or item reward", "LiveMuted", wrap=True))
        if m.outcome == "Complete":
            age = rewards.get(m.id)
            if m.blueprints:
                v.addWidget(_label("Blueprint: " + ", ".join(m.blueprints), "LiveGood", wrap=True))
            elif age is not None and age < live.BLUEPRINT_WINDOW_SECONDS and (
                    m.blueprint_chance or (info or {}).get("blueprints")):
                v.addWidget(_label("Blueprint: checking…", "LiveMuted"))
            else:
                v.addWidget(_label("No blueprint received", "LiveMuted"))
        v.addStretch(1)

        # Possible blueprints: new ones first
        v = self.c_blueprints.page()
        possible = live._possible_blueprints(info, owned)
        if possible:
            new = sum(1 for _n, o in possible if not o)
            chance = max((pool.get("chance") or 0) for pool in info["blueprints"])
            self.c_blueprints.set_title(f"POSSIBLE BLUEPRINTS · {new} NEW OF {len(possible)}"
                                        + (f" · {chance:.0%}" if chance else ""))
            for name, have in sorted(possible, key=lambda p: p[1]):
                v.addWidget(_label(f"✓  {name}" if have else f"＋  {name}", "LiveMuted" if have else "LiveGood",
                                   wrap=True))
        else:
            self.c_blueprints.set_title("POSSIBLE BLUEPRINTS")
            v.addWidget(_label("Blueprint chance" if m.blueprint_chance else
                               "None" if info else "Loading contract details…" if f.contracts is None else
                               "Not in the mission database", "LiveMuted", wrap=True))
        v.addStretch(1)

        # Details
        v = self.c_details.page()
        rows = live._detail_rows(info)
        if info and info.get("description"):
            rows.append(("About", info["description"][:600]))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(1)
        grid.setColumnStretch(1, 1)
        for i, row in enumerate(rows):
            grid.addWidget(_label(row[0], "LiveMuted"), i, 0, alignment=Qt.AlignTop)
            grid.addWidget(_label(row[1], "LiveText", wrap=True), i, 1)
        v.addLayout(grid)
        if not rows:
            v.addWidget(_label("Loading contract details…" if f.contracts is None else "No details",
                               "LiveMuted"))
        v.addStretch(1)

        # Wake up when a reward block changes or expires, or a blink ends.
        waits = []
        for age in rewards.values():
            if age < live.BLUEPRINT_WINDOW_SECONDS:
                waits.append(live.BLUEPRINT_WINDOW_SECONDS - age)
            waits.append(live.REWARD_SECONDS - age)
        waits += [t - time.monotonic() for t in self._flash_until.values()]
        if waits:
            self._expire.start(max(50, int(min(waits) * 1000) + 50))


# -- Session --------------------------------------------------------------------------
class SessionBand(_LiveBand, live.SessionPanel):
    """Where you are, this session's six numbers, blueprints, recent moments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_now = BandColumn("NOW", 2, 1)
        self.c_numbers = BandColumn("THIS SESSION", 3, 1, 260)
        self.c_blueprints = BandColumn("BLUEPRINTS", 2, 2)
        self.c_recent = BandColumn("RECENT", 3, 2)
        self._band_setup([self.c_now, self.c_numbers, self.c_blueprints, self.c_recent])

    def _build(self) -> None:
        if self._state_message():
            return
        tr = live.feed().tracker
        self.c_now.set_title("NOW" if live.feed().state == "reading" else "LAST SESSION")
        v = self.c_now.page()
        v.addWidget(_label(tr.ship or "No ship", "LiveTitle", wrap=True))
        v.addWidget(_label(pretty(tr.location) if tr.location else "Location not known yet", "LiveText", wrap=True))
        if tr.comm_down:
            v.addLayout(_hrow(live._chip("COMMS DOWN", "bad")))
        elif tr.monitored is not None:
            v.addLayout(_hrow(live._chip("MONITORED" if tr.monitored else "UNMONITORED",
                                         "info" if tr.monitored else "bad")))
        if tr.qt_target:
            v.addWidget(_label(f"Quantum to {pretty(tr.qt_target)}", "LiveMuted", wrap=True))
        v.addStretch(1)

        v = self.c_numbers.page()
        playing = (tr.last_time - tr.started) if tr.started and tr.last_time else None
        numbers = [
            (f"{int(playing.total_seconds() // 3600)}:{int(playing.total_seconds() // 60 % 60):02d}"
             if playing else "—", "played"),
            (f"{tr.completed}" + (f" · {tr.failed}" if tr.failed else ""),
             "missions done" + (" · failed" if tr.failed else "")),
            (f"{tr.rep_earned:,}", "rep earned"),
            (str(tr.qt_jumps), "quantum jumps"),
            (str(tr.deaths) + (f" · {tr.incapacitated}" if tr.incapacitated else ""),
             "deaths" + (" · downed" if tr.incapacitated else "")),
            (str(tr.refinery_done), "refinery orders"),
        ]
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        for i, (value, name) in enumerate(numbers):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(_label(value, "BandNumber"))
            cell.addWidget(_label(name, "LiveMuted"))
            grid.addLayout(cell, i // 3, i % 3)
        v.addLayout(grid)
        v.addStretch(1)

        self.c_blueprints.set_title(f"BLUEPRINTS · {len(tr.blueprints)}")
        v = self.c_blueprints.page()
        if not tr.blueprints:
            v.addWidget(_label("None received this session", "LiveMuted"))
        for when, name, source in reversed(tr.blueprints):
            v.addWidget(live._timed(name, when, "LiveGood", f"from {source}" if source else ""))
        v.addStretch(1)

        v = self.c_recent.page()
        if not tr.feed:
            v.addWidget(_label("Nothing yet", "LiveMuted"))
        for item in tr.feed:
            name = {"good": "LiveGood", "bad": "LiveBad"}.get(item.kind, "LiveText")
            v.addWidget(live._timed(item.text, item.time, name))
        v.addStretch(1)


# -- Mining ---------------------------------------------------------------------------
class MiningBand(_BandBody, MiningPanel):
    """Filters, the places (best first for the picked ore; a click selects
    one) and the selected place's rock types, side by side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_filters = BandColumn("FIND", 2, 1, 230)
        self.c_places = BandColumn("PLACES", 4, 1, 260)
        self.c_place = BandColumn("", 4, 2, 260)
        page = QWidget(objectName="Inspector")
        fv = QVBoxLayout(page)
        fv.setContentsMargins(0, 0, 6, 0)
        fv.setSpacing(5)
        for w in (self.resource, self.method, self.system, self.follow_line):
            if w in (self.method, self.system):
                fv.addWidget(w, alignment=Qt.AlignLeft)
            else:
                fv.addWidget(w)
            w.show()
        fv.addStretch(1)
        self.c_filters.scroll.setWidget(page)
        self._band_setup([self.c_filters, self.c_places, self.c_place])
        self.show_message("Loading mining data…")

    def _on_loaded(self, data: dict) -> None:
        self.show_columns()
        super()._on_loaded(data)

    def _open(self, loc_id) -> None:
        self.location = loc_id
        self._render()

    def _render(self) -> None:
        if self.data is None:
            return
        self.show_columns()
        locs = self._locations()
        res = self.resource.currentData()
        if res is not None:
            locs = sorted((l for l in locs if self._share(l, res) > 0), key=lambda l: -self._share(l, res))
            name = self.data["resources"][res]["name"]
            self.c_places.set_title(f"{len(locs)} PLACES WITH {name.upper()} · "
                                    + ("NEAR YOU, THEN " if self._near else "") + "MOST FIRST")
        else:
            self.c_places.set_title(f"{len(locs)} PLACES · PICK AN ORE FOR THE BEST")
        near = {lid: i for i, lid in enumerate(self._near)}
        here = mining.place_from_log(self._here)[1]
        if near:
            locs.sort(key=lambda l: near.get(l["id"], len(near)))
        ids = [l["id"] for l in locs]
        if self.location not in ids:
            self.location = ids[0] if ids else None
        v = self.c_places.page()
        if not locs:
            v.addWidget(_label("This ore doesn't spawn in this system with this mining method. Try All "
                               "systems or another method.", "LiveMuted", wrap=True))
        systems = {s["id"]: s["name"] for s in self.data["systems"]}
        show_system = self.system.value() is None
        top = max((self._share(l, res) for l in locs), default=0) if res is not None else 0
        for loc in locs:
            row = _Clickable(objectName="BandRow")
            row.setProperty("selected", loc["id"] == self.location)
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 3, 6, 3)
            h.setSpacing(6)
            h.addWidget(label(loc["name"], "RowName"))
            if loc["id"] in near:
                h.addWidget(Badge("You're here" if loc["id"] == here else "Near", "info"))
            if show_system and loc["system"] in systems:
                h.addWidget(Badge(systems[loc["system"]], hue=loc["system"]))
            h.addStretch(1)
            if res is not None:
                share = self._share(loc, res)
                h.addWidget(kit.Bar(share / top if top else 0, PALETTE["success"], 40, 5), alignment=Qt.AlignVCenter)
                h.addWidget(label(f"<b>{_pct(share)}</b>", "ChanceText", rich=True))
                q = self._quality(loc, res)
                if q is not None:
                    h.addWidget(label(f"Q {q}", "MutedText"))
            else:
                n = len(loc["groups"][self._method])
                h.addWidget(label(f"{n} rock type{'s' if n != 1 else ''}", "MutedText"))
            row.clicked.connect(lambda lid=loc["id"]: QTimer.singleShot(0, lambda: self._open(lid)))
            v.addWidget(row)
        v.addStretch(1)

        v = self.c_place.page()
        loc = next((l for l in locs if l["id"] == self.location), None)
        if loc is None:
            self.c_place.set_title("")
            v.addStretch(1)
            return
        kind = KIND_LABELS.get(loc["kind"], loc["kind"].title())
        self.c_place.set_title(f"{loc['name'].upper()} · {kind.upper()} · {mining.METHOD_LABELS[self._method].upper()}"
                               " · RS radar signature (×2, ×3 a group) · Q avg quality")
        v.addWidget(LocationCard(loc, self._method, self.data, [res] if res else [], show_system, compact=True))
        v.addStretch(1)


# -- Salvage --------------------------------------------------------------------------
class SalvageBand(_BandBody, SalvagePanel):
    """The claim difficulty, its ships (most valuable first; a click selects
    one) and the selected ship's fee, parts and cargo, side by side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_filters = BandColumn("CLAIM", 2, 1, 220)
        self.c_ships = BandColumn("SHIPS", 5, 1, 280)
        self.c_breakdown = BandColumn("", 3, 2, 240)
        page = QWidget(objectName="Inspector")
        fv = QVBoxLayout(page)
        fv.setContentsMargins(0, 0, 6, 0)
        fv.setSpacing(5)
        for w in (self.tier, self.follow_line):
            if w is self.tier:
                fv.addWidget(w, alignment=Qt.AlignLeft)
            else:
                fv.addWidget(w)
            w.show()
        fv.addStretch(1)
        self.c_filters.scroll.setWidget(page)
        self._band_setup([self.c_filters, self.c_ships, self.c_breakdown])
        self.show_message("Loading salvage data…")

    def _fill_ships(self) -> None:
        if self.game is None:
            return
        from app import salvage

        self.show_columns()
        rows = salvage.build_rows(self.game, self._tier, self.sheet, self.prices)
        rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))
        tier = next((t for t in self.game["tiers"] if t["id"] == self._tier), None)
        self.c_ships.set_title(f"{len(rows)} SHIPS · MOST VALUABLE FIRST"
                               + (f" · {tier['size'].upper()} SHIPS" if tier else ""))
        stems = [r.stem for r in rows]
        if self.opened not in stems:
            self.opened = stems[0] if stems else None
        v = self.c_ships.page()
        if self.sheet is None:
            v.addWidget(_label("Prices aren't downloaded yet: open Salvage Claims in the launcher once.",
                               "LiveBad", wrap=True))
        best = max((r.net for r in rows if r.in_sheet), default=None)
        top = max((r.components_value + r.cargo_value for r in rows if r.in_sheet), default=0)
        claim = self._claim if self.following() else None
        self._rows = {}
        for row in rows:
            mine = claim is not None and claim.get("stem") == row.stem and claim["tier"] == self._tier
            w = ShipRowWidget(row, False, best=row.in_sheet and row.net == best and row.net > 0, top=top,
                              compact=True, flag=f"Your claim #{claim['number']}" if mine else "")
            w.header.setProperty("selected", row.stem == self.opened)
            w.toggled.connect(self._toggled)
            self._rows[row.stem] = w
            v.addWidget(w)
        v.addStretch(1)

        v = self.c_breakdown.page()
        row = next((r for r in rows if r.stem == self.opened), None)
        self.c_breakdown.set_title(row.name.upper() if row else "")
        if row is not None:
            mine = claim is not None and claim.get("stem") == row.stem and claim["tier"] == self._tier
            w = ShipRowWidget(row, True, best=row.in_sheet and row.net == best and row.net > 0, top=top,
                              compact=True, flag=f"Your claim #{claim['number']}" if mine else "")
            w.toggled.connect(lambda *_a: QTimer.singleShot(0, self._fill_ships))   # stays open
            v.addWidget(w)
        v.addStretch(1)

    def _toggled(self, stem: str, _on: bool) -> None:
        """A click on a ship selects it (no accordion: the breakdown is its own column)."""
        self.opened = stem
        QTimer.singleShot(0, self._fill_ships)


# -- Maps -----------------------------------------------------------------------------
class MapsBand(_BandBody, MapsPanel):
    """The guide picker, suggestions and credit, next to a strip of the guide
    (fitting the width, scroll or drag along it; ⤢ or L: large)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        frame = self.viewer.parentWidget()
        credit = next(w for w in self.findChildren(QLabel) if "Mr Kraken" in w.text())
        buttons = [b for b in self.findChildren(QPushButton, "MiniButton") if b.text() in ("−", "Fit", "+", "⤢")]
        self.c_guide = BandColumn("GUIDE", 2, 1, 240)
        self.c_view = BandColumn("", 8, 1, 300)
        page = QWidget(objectName="Inspector")
        fv = QVBoxLayout(page)
        fv.setContentsMargins(0, 0, 6, 0)
        fv.setSpacing(5)
        fv.addWidget(self.guide)
        fv.addWidget(self.page)
        row = QHBoxLayout()
        row.setSpacing(4)
        for b in buttons:
            row.addWidget(b)
            b.show()
        row.addStretch(1)
        fv.addLayout(row)
        fv.addWidget(self.follow_line)
        credit.setText("Guides by Mr Kraken, all credit to the author · ⤢ or L: large, Esc back")
        fv.addWidget(credit)
        for w in (self.guide, self.follow_line, credit):
            w.show()
        fv.addStretch(1)
        self.c_guide.scroll.setWidget(page)
        self.c_view.scroll.hide()
        self.c_view.layout().setContentsMargins(0, 0, 0, 0)
        self.c_view.layout().addWidget(frame, stretch=1)
        frame.show()
        self._band_setup([self.c_guide, self.c_view])
        self._shape_pending = False      # the band has its own shape

    def _toggle_large(self) -> None:
        from app.ui.overlay_panels import _overlay_of

        win = _overlay_of(self)
        if win is not None:
            win.toggle_large()

    def _on_guide(self, index: int, shape: bool = False) -> None:
        super()._on_guide(index, False)

    def _on_page(self, index: int, shape: bool = False) -> None:
        super()._on_page(index, False)


BANDS = {"missions": MissionsBand, "session": SessionBand, "mining": MiningBand, "salvage": SalvageBand,
         "maps": MapsBand}


def make(tool: str) -> QWidget:
    return BANDS[tool]()
