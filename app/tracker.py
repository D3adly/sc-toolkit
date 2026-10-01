"""The current play session's state, built from live Game.log events
(app.gamelog.LiveReader): active and finished missions with their
objectives, where you are and in what, what you earned and spent, and a
short feed of notable moments.

The live reader replays a session from its first line, so the tracker is
complete even when it starts mid-session. Feed it events with `add()`;
`changed` fires after each one.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal

from app.gamelog import Event

# A blueprint (or aUEC award) arriving this soon after a mission completes
# came from it. The log never links them by id.
BLUEPRINT_WINDOW_SECONDS = 15
MAX_FINISHED = 6
MAX_FEED = 12


_TOKEN_RE = re.compile(r"~mission\((\w+)[^)]*\)")
_PLACEHOLDER = "<= UNINITIALIZED =>"


def clean_objective_text(text: str) -> str:
    """The client's objective text can hold unfilled template tokens:
    'Board The ~mission(Ship)' → 'Board The Ship', 'Defeat Vanduul %ls' → 'Defeat Vanduul'."""
    if not text or text == _PLACEHOLDER:
        return ""
    text = _TOKEN_RE.sub(lambda m: re.sub(r"(?<!^)([A-Z])", r" \1", m.group(1)), text)
    return re.sub(r"\s*%ls\b", "", text).strip()


@dataclass
class Objective:
    text: str
    id: str = ""
    state: str = "INPROGRESS"           # INPROGRESS | COMPLETED | WITHDRAWN | FAILED (server)
    hidden: bool = False                # internal phase / not shown in the game's UI
    resolved: bool = False              # text from the HUD notification (tokens filled in)

    @property
    def done(self) -> bool:
        return self.state == "COMPLETED"

    @done.setter
    def done(self, value: bool) -> None:
        self.state = "COMPLETED" if value else "INPROGRESS"

    @property
    def visible(self) -> bool:
        return bool(self.text) and not self.hidden and self.state != "WITHDRAWN"


@dataclass
class Mission:
    id: str
    title: str = ""
    rep: int | None = None
    blueprint_chance: bool = False
    contract: str = ""                  # debug name (from the marker line)
    contract_id: str = ""               # contractDefinitionId
    generator: str = ""
    accepted: datetime | None = None
    objectives: list[Objective] = field(default_factory=list)
    outcome: str = ""                   # "", Complete, Fail, Abandon, Withdrawn…
    ended: datetime | None = None
    blueprints: list[str] = field(default_factory=list)
    awarded: int = 0                    # aUEC notifications right after completion
    server_objectives: bool = False     # objective states come from server pushes (exact)

    @property
    def active(self) -> bool:
        return not self.outcome

    @property
    def visible_objectives(self) -> list[Objective]:
        return [o for o in self.objectives if o.visible]

    @property
    def current_objective(self) -> Objective | None:
        """The newest shown objective still in progress (each step adds one)."""
        return next((o for o in reversed(self.visible_objectives) if o.state == "INPROGRESS"), None)

    def objective(self, text: str, oid: str = "") -> Objective:
        for o in self.objectives:
            if (oid and o.id == oid) or (not oid and text and o.text == text):
                return o
        o = Objective(text, oid)
        self.objectives.append(o)
        return o


@dataclass
class FeedItem:
    time: datetime | None
    kind: str        # "good" | "bad" | "info"
    text: str


@dataclass
class Payout:
    """What a completed mission paid, as far as we can tell."""
    auec: int = 0                # logged "Awarded" right after it, else the contract's fixed reward
    merits: int = 0
    items: list[tuple[str, int]] = field(default_factory=list)   # (name, amount), e.g. scrip
    from_log: bool = False       # the aUEC was in the log (not only the game data)
    calculated: bool = False     # the contract pays a server-calculated amount we can't see


class SessionTracker(QObject):
    changed = Signal()

    def __init__(self, parent=None, lookup=None):
        super().__init__(parent)
        # Mission → contract details (app.contracts) or None; used for
        # payouts. Looked up when asked, so it works once the data loads.
        self.lookup = lookup or (lambda _m: None)
        self.reset()

    def reset(self) -> None:
        self.session = ""
        self.channel = ""
        self.started: datetime | None = None
        self.last_time: datetime | None = None
        self.character = ""
        self.shard = ""
        self.missions: dict[str, Mission] = {}
        self._objective_texts: dict[str, tuple[str, bool]] = {}   # objective id → (text, hidden)
        self.ship = ""
        self.location = ""
        self.jurisdiction = ""
        self.armistice: bool | None = None
        self.monitored: bool | None = None
        self.comm_down = False
        self.qt_target = ""
        self.awarded = 0
        self.shop_spent = 0.0
        self.shop_sold = 0.0
        self.commodity_spent = 0.0
        self.commodity_sold = 0.0
        self.rep_earned = 0
        self.completed = 0
        self.failed = 0
        self.deaths = 0
        self.incapacitated = 0
        self.qt_jumps = 0
        self.blueprints: list[tuple[datetime | None, str, str]] = []   # (when, name, mission title)
        self.feed: deque[FeedItem] = deque(maxlen=MAX_FEED)

    # -- views ----------------------------------------------------------------
    def active_missions(self) -> list[Mission]:
        return [m for m in self.missions.values() if m.active]

    def finished_missions(self) -> list[Mission]:
        done = [m for m in self.missions.values() if not m.active]
        done.sort(key=lambda m: m.ended or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return done[:MAX_FINISHED]

    @property
    def trade_net(self) -> float:
        return self.commodity_sold - self.commodity_spent

    def payout(self, m: Mission) -> Payout:
        """A completed mission counts as paid: the aUEC logged right after it
        if any, else the fixed reward in the contract data; plus its item
        rewards."""
        info = self.lookup(m) or {}
        p = Payout(calculated=bool(info.get("calculated_payout")))
        fixed = info.get("payout") or {}
        if m.awarded:
            p.auec, p.from_log = m.awarded, True
        elif fixed.get("currency") == "aUEC":
            p.auec = fixed.get("amount") or 0
        if fixed.get("currency") == "merits":
            p.merits = fixed.get("amount") or 0
        p.items = [(i["name"], i["amount"]) for i in info.get("items") or []]
        return p

    @property
    def mission_payouts(self) -> int:
        """aUEC from completed missions (logged or fixed rewards)."""
        return sum(self.payout(m).auec for m in self.missions.values() if m.outcome == "Complete")

    @property
    def other_awards(self) -> int:
        """Logged aUEC awards that didn't follow a mission completion."""
        return self.awarded - sum(m.awarded for m in self.missions.values())

    # -- events -----------------------------------------------------------------
    def new_session(self, session_id: str, channel: str = "") -> None:
        self.reset()
        self.session, self.channel = session_id, channel
        self.changed.emit()

    def add(self, event: Event) -> None:
        handler = getattr(self, "_on_" + event.kind, None)
        if event.time is not None:
            self.last_time = event.time
        if handler is None:
            return
        handler(event, event.data)
        self.changed.emit()

    def _say(self, event: Event, kind: str, text: str) -> None:
        self.feed.appendleft(FeedItem(event.time, kind, text))

    def _mission(self, mission_id: str | None) -> Mission | None:
        if not mission_id:
            return None
        if mission_id not in self.missions:
            self.missions[mission_id] = Mission(mission_id)
        return self.missions[mission_id]

    def _on_session_start(self, e: Event, d: dict) -> None:
        self.started = self.started or e.time

    def _on_character(self, e: Event, d: dict) -> None:
        self.character = d.get("name", "")

    def _on_join_pu(self, e: Event, d: dict) -> None:
        self.shard = d.get("shard", "")

    def _on_contract_accepted(self, e: Event, d: dict) -> None:
        m = self._mission(d.get("mission_id"))
        if m is None:
            return
        m.title = d.get("title") or m.title
        m.rep = d.get("rep", m.rep)
        m.blueprint_chance = d.get("blueprint_chance", m.blueprint_chance)
        m.accepted = m.accepted or e.time
        m.outcome, m.ended = "", None       # re-accepted after a withdraw
        self._say(e, "info", f"Accepted: {m.title}")

    def _on_mission_marker(self, e: Event, d: dict) -> None:
        m = self._mission(d.get("mission_id"))
        if m is None:
            return
        m.contract = d.get("contract") or m.contract
        m.contract_id = d.get("contract_id") or m.contract_id
        m.generator = d.get("generator") or m.generator
        m.accepted = m.accepted or e.time

    # Objectives. Exact source: the server's ObjectiveUpserted/ObjectiveComplete
    # pushes (mission id, objective id, state, hidden). Text: the HUD's "New
    # Objective" notification (tokens filled in), else the client's objective
    # list (UpdateActiveObjective, which has only the objective id). Logs
    # without server pushes fall back to matching notification texts.
    def _on_objective(self, e: Event, d: dict) -> None:
        m = self._mission(d.get("mission_id"))
        text, oid = d.get("objective", ""), d.get("objective_id", "")
        if m is None or not m.active or not text:
            return
        o = None
        if not oid:
            # Deliveries: the server pushes the objective without text and the
            # HUD names it without an id. Pair them up, oldest first.
            o = next((x for x in m.objectives if x.id and not x.resolved and not x.hidden
                      and x.state == "INPROGRESS" and not x.id.startswith("phase_")
                      and not self._objective_texts.get(x.id, ("",))[0]), None)
        o = o or m.objective(text, oid)
        o.text, o.resolved = text, True
        if not m.server_objectives:
            o.done = False

    def _objective_push(self, d: dict) -> None:
        m = self._mission(d.get("mission_id"))
        oid = d.get("objective_id", "")
        if m is None or not oid:
            return
        m.server_objectives = True
        new = not any(x.id == oid for x in m.objectives)
        o = m.objective("", oid)
        if new and not d.get("hidden") and not oid.startswith("phase_"):
            # A HUD notification may have named it first (without an id).
            named = next((x for x in m.objectives if not x.id and x.resolved and x.state == "INPROGRESS"), None)
            if named is not None and not self._objective_texts.get(oid, ("",))[0]:
                m.objectives.remove(o)
                o = named
                o.id = oid
        o.state, o.hidden = d.get("state", o.state), bool(d.get("hidden"))
        known = self._objective_texts.get(oid)
        if known and not o.resolved:
            o.text, hidden = known
            o.hidden = o.hidden or hidden

    def _on_objective_upserted(self, e: Event, d: dict) -> None:
        self._objective_push(d)

    def _on_objective_result(self, e: Event, d: dict) -> None:
        self._objective_push(d)

    def _on_objective_text(self, e: Event, d: dict) -> None:
        oid = d.get("objective_id", "")
        text = clean_objective_text(d.get("text", ""))
        if not oid:
            return
        if text or oid not in self._objective_texts:
            self._objective_texts[oid] = (text, bool(d.get("hidden")))
        for m in self.missions.values():
            for o in m.objectives:
                if o.id == oid:
                    if text and not o.resolved:
                        o.text = text
                    if not o.resolved and d.get("hidden"):
                        o.hidden = True

    def _on_objective_complete(self, e: Event, d: dict) -> None:
        # For "local-only" objectives (e.g. Locate Salvage Claim), which the
        # server never pushes, and logs without pushes. This notification
        # spans two log lines, so it usually has no mission id: match by text.
        text = d.get("objective", "")
        for m in self.active_missions():
            for o in m.objectives:
                if o.text == text and o.state == "INPROGRESS":
                    o.done = True
                    return

    def _on_objective_withdrawn(self, e: Event, d: dict) -> None:
        text = d.get("objective", "")
        for m in self.active_missions():
            if not m.server_objectives:
                m.objectives = [o for o in m.objectives if o.text != text]

    def _end(self, e: Event, mission_id: str | None, outcome: str) -> Mission | None:
        m = self.missions.get(mission_id or "")
        if m is None or not m.active:
            return None
        m.outcome, m.ended = outcome, e.time
        if outcome == "Complete":
            for o in m.objectives:      # deliveries don't always log their own completion
                if o.state == "INPROGRESS":
                    o.done = True
            self.completed += 1
            self.rep_earned += m.rep or 0
            self._say(e, "good", f"Complete: {m.title or m.contract}")
        elif outcome in ("Fail", "Failed"):
            self.failed += 1
            self._say(e, "bad", f"Failed: {m.title or m.contract}")
        else:
            self._say(e, "info", f"{outcome}: {m.title or m.contract}")
        return m

    def _on_contract_complete(self, e: Event, d: dict) -> None:
        self._end(e, d.get("mission_id"), "Complete")

    def _on_contract_failed(self, e: Event, d: dict) -> None:
        self._end(e, d.get("mission_id"), "Fail")

    def _on_contract_withdrawn(self, e: Event, d: dict) -> None:
        self._end(e, d.get("mission_id"), "Withdrawn")

    def _on_mission_end(self, e: Event, d: dict) -> None:
        self._end(e, d.get("mission_id"), d.get("outcome") or "Ended")

    def _just_completed(self, when: datetime | None) -> Mission | None:
        """The mission completed within BLUEPRINT_WINDOW_SECONDS before `when`."""
        source = None
        if when is not None:
            for m in self.missions.values():
                if (m.outcome == "Complete" and m.ended is not None
                        and 0 <= (when - m.ended).total_seconds() <= BLUEPRINT_WINDOW_SECONDS):
                    source = m
        return source

    def _on_blueprint(self, e: Event, d: dict) -> None:
        name = d.get("name", "")
        source = self._just_completed(e.time)
        if source is not None:
            source.blueprints.append(name)
        self.blueprints.append((e.time, name, source.title if source else ""))
        self._say(e, "good", f"Blueprint: {name}")

    def _on_awarded(self, e: Event, d: dict) -> None:
        self.awarded += d.get("amount") or 0
        source = self._just_completed(e.time)
        if source is not None:
            source.awarded += d.get("amount") or 0
        self._say(e, "good", f"Awarded {d.get('amount', 0):,} aUEC")

    def _on_shop_buy(self, e: Event, d: dict) -> None:
        self.shop_spent += d.get("price") or 0

    def _on_shop_sell(self, e: Event, d: dict) -> None:
        self.shop_sold += d.get("price") or 0

    def _on_commodity_buy(self, e: Event, d: dict) -> None:
        self.commodity_spent += d.get("price") or 0

    def _on_commodity_sell(self, e: Event, d: dict) -> None:
        self.commodity_sold += d.get("price") or 0
        self._say(e, "good", f"Sold cargo for {d.get('price', 0):,.0f} aUEC")

    def _on_ship_boarded(self, e: Event, d: dict) -> None:
        self.ship = d.get("ship", "")

    def _on_location(self, e: Event, d: dict) -> None:
        self.location = d.get("location", "")

    def _on_jurisdiction(self, e: Event, d: dict) -> None:
        self.jurisdiction = d.get("jurisdiction", "")

    def _on_armistice_enter(self, e: Event, d: dict) -> None:
        self.armistice = True

    def _on_armistice_leave(self, e: Event, d: dict) -> None:
        self.armistice = False

    def _on_monitored_space(self, e: Event, d: dict) -> None:
        self.monitored = d.get("state") == "Entered"

    def _on_comm_array(self, e: Event, d: dict) -> None:
        self.comm_down = d.get("state") == "Down"

    def _on_qt_target(self, e: Event, d: dict) -> None:
        self.qt_target = d.get("target", "")

    def _on_qt_arrived(self, e: Event, d: dict) -> None:
        self.qt_jumps += 1
        self.qt_target = ""

    def _on_death(self, e: Event, d: dict) -> None:
        self.deaths += 1
        self._say(e, "bad", "You died")

    def _on_incapacitated(self, e: Event, d: dict) -> None:
        self.incapacitated += 1
        self._say(e, "bad", "Incapacitated")

    def _on_fatal_collision(self, e: Event, d: dict) -> None:
        self._say(e, "bad", f"Lost {d.get('ship', 'ship')} in a collision")

    def _on_refinery_complete(self, e: Event, d: dict) -> None:
        self._say(e, "good", f"Refinery order done at {d.get('location', '?')}")

    def _on_low_fuel(self, e: Event, d: dict) -> None:
        self._say(e, "bad", "Low fuel")
