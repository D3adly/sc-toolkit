"""Overlay tabs fed by the live Game.log reader: active missions (with the
contract's details from the game data) and the current session (where you
are, what you earned, recent moments).

The overlay runs its own app.gamelog.LiveReader, gated by the launcher's
LIVE LOG switch (setting `gamelog_live_enabled`; the launcher tells a
running overlay when it changes). The reader replays the session from its
first line, so the tabs are complete even when opened mid-session.
"""

from __future__ import annotations

import html
import re
import threading
import time
import traceback
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app import channel as channel_mod, contracts, gamelog, ipc, settings
from app.stats import pretty
from app.tracker import BLUEPRINT_WINDOW_SECONDS, Mission, SessionTracker
from app.ui.overlay_panels import _Clickable, _ScrollPanel, _label, _log

RENDER_DELAY_MS = 250      # coalesces the burst of events when catching up
CLOCK_MS = 30_000          # refreshes "12 min ago" style times
RESTORE_SCROLL_MS = 300    # gives up waiting for a rebuilt page to reach the old scroll position


class LiveFeed(QObject):
    """One per overlay process: the live reader, the session tracker, and
    the lookups the tabs need (contract details, blueprints already owned)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader = gamelog.LiveReader(lambda: settings.current().game_root, self)
        self.tracker = SessionTracker(self)
        self.contracts: contracts.Contracts | None = None
        self.owned: set[str] = set()        # blueprint names received before this session
        self.enabled = settings.load().gamelog_live_enabled
        self._wanted = False                # a live tab has been opened
        self._lookups_started = False
        # Bound methods of QObjects in this thread: the reader emits from its
        # worker thread, so Qt queues these onto the GUI thread, in order.
        self.reader.session_started.connect(self._on_session_started)
        self.reader.event.connect(self.tracker.add)
        self.reader.state_changed.connect(self._on_state_changed)
        self.tracker.changed.connect(self.changed.emit)

    def _on_session_started(self, session_id: str) -> None:
        self.tracker.new_session(session_id, self.reader.channel)

    def _on_state_changed(self, _state: str) -> None:
        self.changed.emit()

    @property
    def state(self) -> str:
        return self.reader.state if self.enabled else "disabled"

    def want(self) -> None:
        """A live tab was opened: start reading (if switched on)."""
        self._wanted = True
        self._load_lookups()
        if self.enabled:
            self.reader.start()
        self.changed.emit()

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if on and self._wanted:
            self.reader.start()
        elif not on:
            self.reader.stop()
        self.changed.emit()

    def request_enable(self) -> None:
        """The tabs' "Turn on" button: flips the launcher's switch (which
        saves the setting and tells us back); works alone if it isn't running."""
        if not ipc.send(ipc.MAIN, "live-log-on"):
            self.set_enabled(True)

    def _load_lookups(self) -> None:
        if self._lookups_started:
            return
        self._lookups_started = True

        def work():
            root = settings.current().game_root
            try:
                history = gamelog.read_history(root, ["blueprint"])
                self.owned = {e.data.get("name", "") for e in history}
            except Exception:
                _log(f"reading blueprint history failed:\n{traceback.format_exc()}")
            try:
                ch = channel_mod.pick_default_channel(root)
                if ch:
                    self.contracts = contracts.load(channel_mod.resolve_channel_paths(root, ch).channel_root)
            except Exception:
                _log(f"loading contract data failed:\n{traceback.format_exc()}")
            self.changed.emit()
        threading.Thread(target=work, daemon=True).start()

    def contract(self, m: Mission) -> dict | None:
        if self.contracts is None or not (m.contract_id or m.contract):
            return None
        return self.contracts.find(m.contract_id, m.contract)


_feed: LiveFeed | None = None


def feed() -> LiveFeed:
    global _feed
    if _feed is None:
        _feed = LiveFeed()
    return _feed


# -- helpers -----------------------------------------------------------------------
def _ago(dt: datetime | None) -> str:
    if dt is None:
        return ""
    minutes = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _clock(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%H:%M") if dt else ""


def _chip(text: str, tone: str = "", tip: str = "") -> QLabel:
    lbl = QLabel(text, objectName="LiveChip")
    if tone:
        lbl.setProperty("tone", tone)
    if tip:
        lbl.setToolTip(tip)
    return lbl


class _LivePanel(_ScrollPanel):
    """Shared plumbing: renders on feed changes (coalesced), shows the
    reader's state when there's nothing to show yet."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._add_scroll()
        self._render_timer = QTimer(self, singleShot=True, interval=RENDER_DELAY_MS, timeout=self._render)
        self._clock = QTimer(self, interval=CLOCK_MS, timeout=self._render)
        feed().changed.connect(self._schedule)

    def activate(self) -> None:
        feed().want()
        self._clock.start()
        self._render()

    def _schedule(self) -> None:
        if self.isVisible() and not self._render_timer.isActive():
            self._render_timer.start()

    def _render(self) -> None:
        """Rebuilds the page (live updates, clicks) and keeps the reader's
        scroll position. The new page gets its height a little later, so the
        position goes back once the scroll range has grown enough for it."""
        bar = self.scroll.verticalScrollBar()
        keep = bar.value()
        self._build()
        if keep <= 0:
            return
        if bar.maximum() >= keep:
            bar.setValue(keep)
            return

        pending = [True]

        def restore(_low: int = 0, high: int = 0, final: bool = False) -> None:
            if pending[0] and (high >= keep or final):
                pending[0] = False
                bar.setValue(min(keep, bar.maximum()))
                bar.rangeChanged.disconnect(restore)

        bar.rangeChanged.connect(restore)
        # If the page ends up shorter than the old position: as far down as it goes.
        QTimer.singleShot(RESTORE_SCROLL_MS, lambda: restore(final=True))

    def showEvent(self, event):
        super().showEvent(event)
        self._render()

    def _state_message(self) -> bool:
        """Shows why there's nothing live yet; True if it did."""
        state = feed().state
        if state == "disabled":
            v = self._new_page()
            v.addStretch(1)
            lbl = _label("The live log reader is off.\nTurn on LIVE LOG in SC-Toolkit to follow your "
                         "missions and session here.", "InspectorHint", wrap=True)
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
            btn = QPushButton("Turn on live log", objectName="MiniButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(feed().request_enable)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(btn)
            row.addStretch(1)
            v.addLayout(row)
            v.addStretch(2)
            return True
        if state in ("off", "waiting") and not feed().tracker.session:
            self._message("Waiting for Star Citizen…\nThis fills in as soon as the game is running.")
            return True
        return False

    def _build(self) -> None:
        raise NotImplementedError


# -- Missions ------------------------------------------------------------------------
REWARD_SECONDS = 60        # a completed mission stays in the active list (green) this long
CARD_HEIGHT = 118          # every mission block's collapsed height; expanded is never smaller
FLASH_RECENT_SECONDS = 20  # an objective change this recent (log time) is new to the player
FLASH_MS = 700             # the tracked mission's one blink
COMBAT_TAGS = {"ship": "Ship combat", "fps": "FPS combat"}
OUTCOMES = {"Complete": "Completed", "Fail": "Failed", "Abandon": "Abandoned"}   # the log's words → ours
_CLASS_PREFIX_RE = re.compile(r"^[A-Za-z]+/\d+/[A-Za-z]+\s+")


def blueprint_key(name: str) -> str:
    """For "already owned" matching: StarStrings versions differ in whether
    they prefix a class code ("Ind/0/A FullSpec-Go" vs "FullSpec-Go"), and the
    log keeps whatever the version installed at the time showed."""
    return _CLASS_PREFIX_RE.sub("", name).strip().lower()


class _Elided(QLabel):
    """One line that ends in "…" when it doesn't fit (full text in the tooltip)."""

    def __init__(self, text: str, name: str, tip: str = ""):
        super().__init__(text, objectName=name)
        self.setToolTip(tip or text)
        self.setMinimumWidth(40)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(40)
        return hint

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        p.drawText(self.rect(), int(self.alignment() | Qt.AlignVCenter), text)


def _mission_title(m: Mission, info: dict | None) -> str:
    return m.title or (info or {}).get("title") or pretty(m.contract) or "Mission"


def _contractor(m: Mission, info: dict | None) -> str:
    """Who issued it (and whose reputation it pays): the contract's
    contractor from the game data, else the generator's name."""
    if info and info.get("contractor"):
        return info["contractor"]
    if m.generator:
        return pretty(m.generator.replace("_Generator", "").replace("Generator", ""))
    return "Unknown contractor"


def _reward_age(m: Mission) -> float | None:
    """Seconds since a mission completed, if it's still in its reward window."""
    if m.outcome != "Complete" or m.ended is None:
        return None
    age = (datetime.now(timezone.utc) - m.ended).total_seconds()
    return age if 0 <= age < REWARD_SECONDS else None


def _activity(m: Mission) -> datetime:
    """When the mission last moved: objective change, end, or acceptance."""
    times = [t for t in (m.objective_changed, m.ended, m.accepted) if t is not None]
    return max(times) if times else datetime.min.replace(tzinfo=timezone.utc)


def _rewards(m: Mission, info: dict | None) -> list[QLabel]:
    """Reputation and non-aUEC rewards (merits, items such as scrip). aUEC
    isn't shown: most contracts pay a rate the game calculates, which is in
    neither the game files nor the log."""
    chips = []
    rep = m.rep if m.rep is not None else (info or {}).get("rep")
    if rep:
        chips.append(_chip(f"+{rep:,} rep", tip="Reputation with the contractor"))
    fixed = (info or {}).get("payout") or {}
    if fixed.get("currency") == "merits":
        chips.append(_chip(f"+{fixed['amount']:,} merits", "good"))
    for item in (info or {}).get("items") or []:
        chips.append(_chip(f"+{item['amount']} {item['name']}", "good", "Item reward"))
    return chips


def _tags(info: dict | None) -> list[QLabel]:
    if not info:
        return []
    tags = []
    if info.get("type"):
        tags.append(_chip(info["type"], "info", "Mission type"))
    for kind in info.get("combat") or []:
        tags.append(_chip(COMBAT_TAGS[kind], "info",
                          "The mission spawns hostile ships" if kind == "ship"
                          else "The mission spawns hostile people on foot"))
    if info.get("illegal"):
        tags.append(_chip("Illegal", "bad"))
    return tags


def _row(v: QVBoxLayout, widgets: list[QWidget], lead: QWidget | None = None) -> None:
    row = QHBoxLayout()
    row.setSpacing(4)
    if lead is not None:
        row.addWidget(lead)
    for w in widgets:
        row.addWidget(w)
    row.addStretch(1)
    v.addLayout(row)


def _possible_blueprints(info: dict | None, owned: set[str]) -> list[tuple[str, bool]]:
    items = sorted({name for pool in (info or {}).get("blueprints") or [] for name in pool["items"]})
    return [(n, blueprint_key(n) in owned) for n in items]


def _mission_card(m: Mission, info: dict | None, owned: set[str], *, expanded: bool, toggle,
                  state: str = "", flash: bool = False, reward_age: float | None = None) -> QFrame:
    """Every mission looks the same: title, contractor, rewards, tags, the
    next objective (or how it ended), blueprints owned out of possible.
    A click expands it in place (objectives, details, blueprints); it never
    gets smaller than the collapsed block."""
    card = _Clickable(objectName="LiveCard")
    card.clicked.connect(toggle)
    if state:
        card.setProperty("state", state)
    if flash:
        card.setProperty("flash", "true")
    if expanded:
        card.setMinimumHeight(CARD_HEIGHT)
    else:
        card.setFixedHeight(CARD_HEIGHT)
    v = QVBoxLayout(card)
    v.setContentsMargins(10, 8, 10, 8)
    v.setSpacing(3)

    # Title, and when / how it ended
    head = QHBoxLayout()
    head.setSpacing(6)
    tip = ""
    if info and info.get("description"):
        tip = "<p style='white-space:pre-wrap'>" + html.escape(info["description"][:1500]) + "</p>"
    title = _mission_title(m, info)
    head.addWidget(_label(title, "LiveTitle", tip, wrap=True) if expanded else _Elided(title, "LiveTitle", tip or title),
                   stretch=1)
    if m.active:
        head.addWidget(_label(_ago(m.accepted), "LiveMuted", "Time since you accepted it"), alignment=Qt.AlignTop)
    elif m.outcome == "Complete":
        head.addWidget(_chip("COMPLETE", "good"), alignment=Qt.AlignTop)
    else:
        head.addWidget(_chip(OUTCOMES.get(m.outcome, m.outcome).upper(), "bad"), alignment=Qt.AlignTop)
    head.addWidget(_label("▾" if expanded else "▸", "LiveMuted"), alignment=Qt.AlignTop)
    v.addLayout(head)

    _row(v, _rewards(m, info), _Elided(_contractor(m, info), "LiveMuted", "Issued by (reputation goes to them)"))
    _row(v, _tags(info))

    # The next objective, or how it ended
    objectives = m.visible_objectives
    current = m.current_objective
    if m.active:
        if current is not None:
            v.addWidget(_Elided(f"○  {current.text}", "LiveText"))
        elif objectives:
            v.addWidget(_Elided(f"✓  {objectives[-1].text}", "LiveMuted"))
    elif m.outcome == "Complete":
        if m.blueprints:
            v.addWidget(_Elided("Blueprint: " + ", ".join(m.blueprints), "LiveGood"))
        elif reward_age is not None and reward_age < BLUEPRINT_WINDOW_SECONDS and (
                m.blueprint_chance or (info or {}).get("blueprints")):
            v.addWidget(_label("Blueprint: checking…", "LiveMuted"))   # the notice follows by a few seconds
        else:
            v.addWidget(_label(f"Completed {_clock(m.ended)}", "LiveMuted"))
    else:
        v.addWidget(_label(f"{OUTCOMES.get(m.outcome, m.outcome)} {_clock(m.ended)}", "LiveBad"))

    possible = _possible_blueprints(info, owned)
    if possible:
        have = sum(1 for _n, o in possible if o)
        v.addWidget(_label(f"Blueprints {have}/{len(possible)} owned", "LiveMuted",
                           "Blueprints this mission can give, and how many of them you already have"))
    elif m.blueprint_chance:
        v.addWidget(_label("Blueprint chance", "LiveMuted"))

    if not expanded:
        v.addStretch(1)
        return card

    if objectives:
        v.addWidget(_label("OBJECTIVES", "LiveGroup"))
        for o in objectives:
            mark = "✓" if o.done else ("▶" if o is current else "○")
            v.addWidget(_label(f"{mark}  {o.text}", "LiveMuted" if o.done else "LiveText", wrap=True))
    if not m.active and m.outcome == "Complete":
        rewards = [c.text() for c in _rewards(m, info)]
        v.addWidget(_label("REWARD", "LiveGroup"))
        v.addWidget(_label("  ·  ".join(rewards) if rewards else "No reputation or item reward", "LiveText", wrap=True))
        v.addWidget(_label("Blueprint received: " + ", ".join(m.blueprints) if m.blueprints
                           else "No blueprint received", "LiveGood" if m.blueprints else "LiveMuted", wrap=True))
    _details(v, info)
    if possible:
        chance = max((pool.get("chance") or 0) for pool in info["blueprints"])
        v.addWidget(_label(f"POSSIBLE BLUEPRINTS · {sum(1 for _n, o in possible if o)}/{len(possible)} OWNED",
                           "LiveGroup", f"The mission can give one of these on completion ({chance:.0%} chance in "
                           "the game data). ✓ = you already received it (from your logs)."))
        for name, have in possible:
            v.addWidget(_label(f"✓  {name}" if have else f"•  {name}",
                               "LiveBlueprintOwned" if have else "LiveText", wrap=True))
    return card


def _minutes(value: float | None) -> str:
    if not value:
        return ""
    value = round(value)
    return f"{value // 60} h {value % 60:02d} min" if value >= 60 else f"{value} min"


def _details(v: QVBoxLayout, info: dict | None) -> None:
    """The mission database's facts about the contract, a line each."""
    if not info:
        return
    rows = []
    where = info.get("systems", []) + info.get("locations", [])
    if where:
        rows.append(("Where", ", ".join(dict.fromkeys(where))))
    if info.get("rank"):
        rows.append(("Rank", info["rank"] + (f" – {info['max_rank']}" if info.get("max_rank") else "")))
    for c in info.get("cargo") or []:
        low, high = c.get("min_scu") or 0, c.get("max_scu") or 0
        amount = f"{low:g} SCU" if not high or high == low else f"{low:g}–{high:g} SCU"
        rows.append(("Cargo", f"{c['resource']} · {amount}"))
    if info.get("salvage_percent"):
        rows.append(("Salvage", f"{info['salvage_percent']}% of the hull"))
    times = []
    if info.get("est_minutes"):
        times.append(f"~{_minutes(info['est_minutes'])} estimated")
    if info.get("deadline_minutes"):
        times.append(f"{_minutes(info['deadline_minutes'])} limit")
    if times:
        rows.append(("Time", " · ".join(times)))
    if info.get("max_players") and info["max_players"] > 1:
        rows.append(("Players", f"up to {info['max_players']}"))
    detail = info.get("difficulty_detail") or {}
    if detail:
        tip = "<br>".join(f"<b>{html.escape(k.capitalize())}</b>: level {d['level']}, {html.escape(d['text'])}"
                          for k, d in detail.items())
        rows.append(("Difficulty", " · ".join(f"{k.split()[0]} {d['level']}" for k, d in detail.items()), tip))
    if not rows:
        return
    v.addWidget(_label("DETAILS", "LiveGroup"))
    grid = QGridLayout()
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(1)
    grid.setColumnStretch(1, 1)
    for i, row in enumerate(rows):
        grid.addWidget(_label(row[0], "LiveMuted"), i, 0, alignment=Qt.AlignTop)
        grid.addWidget(_label(row[1], "LiveText", row[2] if len(row) > 2 else "", wrap=True), i, 1)
    v.addLayout(grid)


class MissionsPanel(_LivePanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded: set[str] = set()     # mission ids opened by a click
        self._flashed: dict[str, datetime] = {}   # mission id -> objective change already blinked for
        self._flash_until: dict[str, float] = {}  # mission id -> monotonic end of its blink
        # Re-renders when a reward block's time is up (or its blueprint window ends), and to end a blink.
        self._expire = QTimer(self, singleShot=True, timeout=self._render)

    def _toggle(self, mission_id: str) -> None:
        self._expanded ^= {mission_id}
        self._render()

    def _tracked(self, active: list[Mission]) -> Mission | None:
        """The mission you're playing: the one whose objectives changed last
        (the game doesn't log which mission is tracked)."""
        moved = [m for m in active if m.objective_changed is not None]
        return max(moved, key=lambda m: m.objective_changed) if moved else None

    def _update_flash(self, tracked: Mission | None) -> None:
        """One blink when the tracked mission's objective changes while you
        play (not for changes replayed from earlier in the log)."""
        now = time.monotonic()
        self._flash_until = {k: t for k, t in self._flash_until.items() if t > now}
        if tracked is None or self._flashed.get(tracked.id) == tracked.objective_changed:
            return
        self._flashed[tracked.id] = tracked.objective_changed
        age = (datetime.now(timezone.utc) - tracked.objective_changed).total_seconds()
        if 0 <= age < FLASH_RECENT_SECONDS:
            self._flash_until[tracked.id] = now + FLASH_MS / 1000

    def _build(self) -> None:
        if self._state_message():
            return
        f = feed()
        tr = f.tracker
        owned = {blueprint_key(n) for n in f.owned} | {blueprint_key(n) for _t, n, _m in tr.blueprints}
        v = self._new_page()

        # Active missions, plus the ones still in their reward window; the
        # tracked one first, then the rest by when they last moved.
        rewards = {m.id: age for m in tr.missions.values() if (age := _reward_age(m)) is not None}
        active = tr.active_missions()
        tracked = self._tracked(active)
        self._update_flash(tracked)
        shown = [m for m in tr.missions.values() if m.active or m.id in rewards]
        shown.sort(key=lambda m: (m is not tracked, -_activity(m).timestamp()))
        v.addWidget(_label(f"ACTIVE MISSIONS · {len(active)}", "SectionLabel"))
        self._fit_anchor = None      # the last active block: the window fits down to it
        if not shown:
            self._fit_anchor = _label("No active missions this session. Accept a contract and it shows up here.",
                                      "InspectorHint", wrap=True)
            v.addWidget(self._fit_anchor)
        for m in shown:
            state = "reward" if m.id in rewards else ("tracked" if m is tracked else "")
            self._fit_anchor = self._card(m, state, owned, reward_age=rewards.get(m.id))
            v.addWidget(self._fit_anchor)

        # Finished: completed first, then failed / abandoned (newest first in each).
        finished = [m for m in tr.finished_missions() if m.id not in rewards]
        if finished:
            v.addWidget(_label("FINISHED THIS SESSION", "SectionLabel"))
            for m in sorted(finished, key=lambda m: m.outcome != "Complete"):
                v.addWidget(self._card(m, "done" if m.outcome == "Complete" else "failed", owned))
        if f.contracts is None:
            v.addWidget(_label("Loading contract details…", "LiveMuted"))
        v.addStretch(1)

        # Wake up when a reward block changes (blueprint window ends) or expires, or a blink ends.
        waits = []
        for age in rewards.values():
            if age < BLUEPRINT_WINDOW_SECONDS:
                waits.append(BLUEPRINT_WINDOW_SECONDS - age)
            waits.append(REWARD_SECONDS - age)
        waits += [t - time.monotonic() for t in self._flash_until.values()]
        if waits:
            self._expire.start(max(50, int(min(waits) * 1000) + 50))

        # The window fits the collapsed list; opening a card scrolls instead.
        if not self._expanded:
            QTimer.singleShot(0, self._fit)

    def _card(self, m: Mission, state: str, owned: set[str], reward_age: float | None = None) -> QFrame:
        return _mission_card(m, feed().contract(m), owned, expanded=m.id in self._expanded,
                             toggle=lambda mid=m.id: self._toggle(mid), state=state,
                             flash=m.id in self._flash_until, reward_age=reward_age)

    def _fit(self) -> None:
        """Active missions (collapsed) fit without scrolling; the finished
        ones below are a scroll away."""
        page, anchor, win = self.scroll.widget(), getattr(self, "_fit_anchor", None), self.window()
        if page is None or anchor is None or not hasattr(win, "fit_height"):
            return
        # Measured from the layout, not the widgets' geometry (not placed yet
        # right after a render): everything above the anchor, plus the anchor.
        layout = page.layout()
        margins = layout.contentsMargins()
        bottom = margins.top()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() is None:
                continue
            hint = item.widget().sizeHint().height()
            if item.widget().hasHeightForWidth():
                hint = item.widget().heightForWidth(self.scroll.viewport().width() - margins.left() - margins.right())
            bottom += hint + layout.spacing()
            if item.widget() is anchor:
                break
        win.fit_height("missions", bottom + margins.bottom() + 2 * self.scroll.frameWidth() + 14)


# -- Session -------------------------------------------------------------------------
def _status_row(grid: QGridLayout, row: int, name: str, value: QWidget | str) -> None:
    grid.addWidget(_label(name, "LiveMuted"), row, 0, alignment=Qt.AlignTop)
    widget = _label(value, "LiveText", wrap=True) if isinstance(value, str) else value
    grid.addWidget(widget, row, 1)


class SessionPanel(_LivePanel):
    def _build(self) -> None:
        if self._state_message():
            return
        tr = feed().tracker
        v = self._new_page()

        head = "NOW" if feed().state == "reading" else "LAST SESSION (GAME CLOSED)"
        v.addWidget(_label(head, "SectionLabel"))
        status = QGridLayout()
        status.setHorizontalSpacing(10)
        status.setVerticalSpacing(3)
        status.setColumnStretch(1, 1)
        _status_row(status, 0, "Ship", tr.ship or "—")
        _status_row(status, 1, "Location", pretty(tr.location) if tr.location else "—")
        row = 2
        if tr.comm_down or tr.monitored is not None:
            space = QHBoxLayout()
            space.setContentsMargins(0, 0, 0, 0)
            if tr.comm_down:
                space.addWidget(_chip("COMMS DOWN", "bad", "Monitored space is down (comm array offline)"))
            else:
                space.addWidget(_chip("MONITORED" if tr.monitored else "UNMONITORED",
                                      "info" if tr.monitored else "bad"))
            space.addStretch(1)
            space_w = QWidget()
            space_w.setLayout(space)
            _status_row(status, row, "Space", space_w)
            row += 1
        if tr.qt_target:
            _status_row(status, row, "Quantum to", pretty(tr.qt_target))
        v.addLayout(status)

        v.addWidget(_label("THIS SESSION", "SectionLabel"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        playing = (tr.last_time - tr.started) if tr.started and tr.last_time else None
        tiles = [
            ("Played", f"{int(playing.total_seconds() // 3600)}h {int(playing.total_seconds() // 60 % 60):02d}m"
             if playing else "—"),
            ("Missions done", f"{tr.completed}" + (f" · {tr.failed} failed" if tr.failed else "")),
            ("Rep earned", f"{tr.rep_earned:,}"),
            ("Quantum jumps", str(tr.qt_jumps)),
            ("Deaths", str(tr.deaths) + (f" · {tr.incapacitated} downed" if tr.incapacitated else "")),
            ("Refinery orders done", str(tr.refinery_done)),
        ]
        for i, (name, value) in enumerate(tiles):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(_label(value, "LiveValue"))
            box.addWidget(_label(name, "LiveMuted"))
            grid.addLayout(box, i // 2, i % 2)
        v.addLayout(grid)

        if tr.blueprints:
            v.addWidget(_label(f"BLUEPRINTS · {len(tr.blueprints)}", "SectionLabel"))
            for when, name, source in reversed(tr.blueprints[-8:]):
                tip = f"From: {source}" if source else ""
                v.addWidget(_label(f"{_clock(when)}  {name}", "LiveGood", tip, wrap=True))

        if tr.feed:
            v.addWidget(_label("RECENT", "SectionLabel"))
            for item in tr.feed:
                name = {"good": "LiveGood", "bad": "LiveBad"}.get(item.kind, "LiveText")
                v.addWidget(_label(f"{_clock(item.time)}  {item.text}", name, wrap=True))
        v.addStretch(1)
