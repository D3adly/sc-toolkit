"""Org events from sc-toolbox.com: the agenda, an event's details, and signing up.

Planning events happens on the website; the launcher shows your orgs' ops, lets you take, change
and leave a seat, and keeps the next ops you're in for the overlay's reminder. The service owns
every rule (who may sign up where, which seat "join as" gets): the launcher asks and shows.

`EventsController` (one per app, `controller()`) does the calls on a worker thread and reports
through signals. While signed in it refreshes the agenda every few minutes and writes the ops
you're in to UPCOMING_FILE, which the overlay process reads.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from app import config, portal

UPCOMING_FILE = config.DATA_DIR / "events-upcoming.json"
POLL_MS = 5 * 60_000            # the agenda, while signed in
RUNNING_FOR_MIN = 120           # an event without a duration counts as two hours

# The service's EventKind keys: label and the theme hue the badge uses.
KINDS = {
    "combat": ("Combat", "combat"),
    "mining": ("Mining", "industry"),
    "salvage": ("Salvage", "pyro"),
    "hauling": ("Hauling", "hauling"),
    "exploration": ("Exploration", "search"),
    "racing": ("Racing", "racing"),
    "social": ("Social", "event"),
    "training": ("Training", "stanton"),
}

CATEGORIES = {
    "capital": "Capital", "medium": "Sub-capital", "fighter": "Fighters", "snub": "Snubs",
    "cargo": "Cargo", "medical": "Medical", "salvage": "Salvage", "mining": "Mining",
}
ROLE_LABELS = {"pilot": "Pilot", "gunner": "Gunner", "infantry": "Ground team"}


# -- reading an event -------------------------------------------------------------------------

def parse_time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def local_time(iso: str) -> str:
    """"Mon 19 Oct, 17:00" in this PC's time zone (English names, like the rest of the app, not
    the system locale's)."""
    t = parse_time(iso).astimezone()
    return f"{DAYS[t.weekday()]} {t.day} {MONTHS[t.month - 1]}, {t:%H:%M}"


def countdown(starts_at: str, duration: int | None, now: float | None = None) -> str:
    """"T-2d 03:14", "T-03:14:09" in the last day, "Live" while it runs, "Over" after."""
    now = time.time() if now is None else now
    start = parse_time(starts_at).timestamp()
    left = int(start - now)
    if left <= 0:
        return "Live" if now < start + (duration or RUNNING_FOR_MIN) * 60 else "Over"
    d, rest = divmod(left, 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    return f"T-{d}d {h:02}:{m:02}" if d else f"T-{h:02}:{m:02}:{s:02}"


def crew(groups: list[dict]) -> dict:
    """Seats per role, taken and total; `open_spots`: spots whose gunner seats come with a pilot."""
    c = {"pilot": [0, 0], "gunner": [0, 0], "infantry": [0, 0], "open_spots": 0}
    for g in groups:
        if g.get("type") == "infantry":
            c["infantry"][0] += g.get("taken", 0)
            c["infantry"][1] += g.get("slots", 0)
            continue
        for v in g.get("vehicles", []):
            c["pilot"][0] += int(bool(v.get("pilotTaken")))
            c["pilot"][1] += 1
            c["gunner"][0] += v.get("gunnersTaken", 0)
            c["gunner"][1] += v.get("gunners", 0)
            if not v.get("ship") and not v.get("pilotTaken"):
                c["open_spots"] += 1
    c["taken"] = sum(c[k][0] for k in ROLE_LABELS)
    c["total"] = sum(c[k][1] for k in ROLE_LABELS)
    return c


def needs(c: dict) -> str:
    """"Needs 1 pilot, 4 gunners, 3 ground" or "Full"."""
    parts = []
    for key, one, many in (("pilot", "pilot", "pilots"), ("gunner", "gunner", "gunners"), ("infantry", "ground", "ground")):
        free = c[key][1] - c[key][0]
        if free > 0:
            parts.append(f"{free} {one if free == 1 else many}")
    return "Needs " + ", ".join(parts) if parts else "Full"


def my_seat(event: dict) -> str | None:
    """"Gunner · Polaris · Capital" (+ more), "Backup · Escort"; None when not signed up."""
    groups = {g["id"]: g for g in event.get("groups", [])}
    seats, backup = [], None
    for s in event.get("mySignups", []):
        g = groups.get(s.get("groupId"), {})
        if s.get("backup"):
            backup = backup or f"Backup · {g.get('name', '')}"
            continue
        seat = s.get("seat") or "infantry"
        if seat == "infantry":
            seats.append(f"Ground team · {g.get('name', '')}")
            continue
        v = next((x for x in g.get("vehicles", []) if x["id"] == s.get("vehicleId")), {})
        ship = v.get("shipName") or s.get("shipName") or "open spot"
        seats.append(f"{ROLE_LABELS[seat]} · {ship} · {g.get('name', '')}")
    return " + ".join(seats) if seats else backup


# -- the ops you're in, for the overlay -----------------------------------------------------

def write_upcoming(events: list[dict]) -> None:
    """The published ops you hold a seat in (or are backup for) that aren't over: soonest first."""
    now = time.time()
    mine = [e for e in events if e.get("status") == "published" and e.get("mySignups")
            and countdown(e["startsAt"], e.get("durationMinutes"), now) != "Over"]
    try:
        UPCOMING_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPCOMING_FILE.write_text(json.dumps({"written": now, "events": mine}))
    except OSError:
        pass


def read_upcoming() -> list[dict]:
    try:
        data = json.loads(UPCOMING_FILE.read_text())
    except (OSError, ValueError):
        return []
    now = time.time()
    return [e for e in data.get("events", []) if countdown(e["startsAt"], e.get("durationMinutes"), now) != "Over"]


def clear_upcoming() -> None:
    try:
        UPCOMING_FILE.unlink()
    except OSError:
        pass


# -- the controller -----------------------------------------------------------------------------

class EventsController(QObject):
    """The agenda and one open event, from the service, one call at a time on a worker thread."""

    listed = Signal(list)               # the agenda (event summaries, soonest first)
    loaded = Signal(dict)               # an event's details, after loading or a sign-up change
    failed = Signal(str, str, dict)     # message, API code, problem body (an action that didn't go)
    state = Signal(str)                 # "signed_out" | "loading" | "ready" | "offline"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events: list[dict] = []
        self.status = "signed_out"
        self._jobs: queue.Queue = queue.Queue()
        self._results: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        self._drain = QTimer(self, interval=100, timeout=self._deliver)
        self._drain.start()
        self._poll = QTimer(self, interval=POLL_MS, timeout=self.refresh)
        from app.account_controller import controller as account_controller

        account_controller().changed.connect(self._on_account)
        self._on_account(account_controller().state)

    # what the UI asks for
    def refresh(self) -> None:
        self._submit("list", lambda s: s.api("GET", "/events")["items"])

    def load(self, event_id: str) -> None:
        self._submit("detail", lambda s: s.api("GET", f"/events/{event_id}"))

    def sign_up(self, event_id: str, body: dict) -> None:
        """Takes a seat: `{groupId, vehicleId, seat, ship}`, `{role, ship}`, or `{groupId, backup}`."""
        self._submit("change", lambda s: s.api("POST", f"/events/{event_id}/signup", body))

    def leave(self, event_id: str, group_id: str) -> None:
        self._submit("change", lambda s: s.api("DELETE", f"/events/{event_id}/signup/{group_id}"))

    # plumbing
    def _on_account(self, st) -> None:
        if st.status == "signed_in":
            if self.status == "signed_out":
                self._set("loading")
            self._poll.start()
            self.refresh()
        elif st.status in ("signed_out", "off"):
            self._poll.stop()
            self.events = []
            clear_upcoming()
            self._set("signed_out")
            self.listed.emit([])

    def _set(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self.state.emit(status)

    def _submit(self, kind: str, call) -> None:
        from app.account_controller import controller as account_controller

        session = account_controller().session
        if session is None:
            return
        self._jobs.put((kind, session, call))

    def _worker(self) -> None:
        while True:
            kind, session, call = self._jobs.get()
            try:
                self._results.put((kind, call(session), None))
            except portal.PortalError as exc:
                self._results.put((kind, None, exc))
            except Exception as exc:  # noqa: BLE001 (a bug must not kill the worker)
                self._results.put((kind, None, portal.PortalError(f"Something went wrong: {exc}")))

    def _deliver(self) -> None:
        while not self._results.empty():
            kind, result, error = self._results.get()
            if error is not None:
                if kind == "upcoming":
                    continue        # the reminder just goes without the briefing
                if kind == "list":
                    self._set("offline" if isinstance(error, portal.Unreachable) else self.status)
                    if not self.events:
                        self.listed.emit([])
                else:
                    self.failed.emit(str(error), error.code, error.data)
                continue
            if kind == "list":
                self.events = result
                write_upcoming(result)
                self._set("ready")
                self.listed.emit(result)
                # The overlay's reminder shows the briefing too: the list has no descriptions.
                nxt = next((e for e in result if e.get("status") == "published"
                            and any(not s.get("backup") for s in e.get("mySignups", []))), None)
                if nxt is not None:
                    self._submit("upcoming", lambda s, i=nxt["id"]: s.api("GET", f"/events/{i}"))
            elif kind == "upcoming":
                for e in self.events:
                    if e["id"] == result.get("id"):
                        e["description"] = result.get("description", "")
                write_upcoming(self.events)
            else:
                self.loaded.emit(result)
                if kind == "change":
                    self.refresh()      # the agenda's "you're in" and the overlay follow


_controller: EventsController | None = None


def controller() -> EventsController:
    global _controller
    if _controller is None:
        _controller = EventsController()
    return _controller
