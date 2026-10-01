"""Star Citizen Game.log reader: turns log lines into typed events.

Two ways to read:

- **History** (`read_history`): every log on disk, `logbackups/*.log`
  (oldest first) and then the current `Game.log`, of every channel folder.
  It picks out the requested event kinds and returns either the events
  themselves or an aggregate of them. `HistoryJob` runs it off the UI thread.
- **Live** (`LiveReader`): follows the current game session's `Game.log`.
  If the game is already running when the reader starts, it reads that
  session from its first line; otherwise it waits for the next game start
  (the game begins a fresh Game.log each time). Every event is emitted as a
  Qt signal and passed to registered listeners, and the session's running
  aggregate is kept in memory.

Event kinds live in `EVENT_TYPES`; features add their own with `register`.
Log formats are not an API and CIG changes them between patches, so every
kind is matched on its own: one broken format loses that kind only. See
~/.ai/plans/sc-toolkit-gamelog-events.md for the survey behind the patterns.
"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import psutil
from PySide6.QtCore import QObject, Signal

from app import channel, osutil

LOG_NAME = "Game.log"
BACKUP_DIR = "logbackups"
LIVE_POLL_SECONDS = 1.0
PROCESS_POLL_SECONDS = 5.0

_TIME_RE = re.compile(r"^<(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z>")
# Some notification texts end in a line break: the line then stops inside
# the quotes, and the queue position and MissionId follow on the next line.
_NOTIFICATION_RE = re.compile(r'Added notification "(.*?)(?:(?:: )?" \[\d+\]|$)')
_OBJECTIVE_ID_RE = re.compile(r"ObjectiveId: \[([0-9a-f-]{36})\]")
_MISSION_ID_RE = re.compile(r"MissionId: \[([0-9a-f-]{36})\]")
_NULL_MISSION = "00000000-0000-0000-0000-000000000000"
_TITLE_MARKERS_RE = re.compile(r"\s*<EM\d>(.*?)</EM\d>\s*")


# -- events -------------------------------------------------------------------
@dataclass
class Event:
    kind: str
    time: datetime | None           # UTC, from the line's timestamp
    data: dict
    session: str = ""                # which play session (see LogSession.id)
    line: str = field(default="", repr=False)
    # Live reads only: True for what was already in the log when the reader
    # attached to the session (catch-up), False for what happened since.
    backlog: bool = False
    channel: str = ""                # LIVE, PTU, … (the folder the log is in)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "time": self.time.isoformat() if self.time else None,
            "session": self.session,
            "channel": self.channel,
            "backlog": self.backlog,
            "data": self.data,
        }


@dataclass
class EventType:
    """One kind of event.

    `needle` is a plain substring every matching line contains (a cheap
    pre-filter, so a 300 MB history isn't regex-matched line by line);
    `parse` gets the whole line and returns the event's data, or None if
    the line isn't one after all. For aggregates, `sum_fields` are added
    up and `group_field` is counted per value.
    """
    kind: str
    needle: str
    parse: Callable[[str], dict | None]
    description: str = ""
    sum_fields: tuple[str, ...] = ()
    group_field: str | None = None


EVENT_TYPES: dict[str, EventType] = {}


def register(event_type: EventType) -> EventType:
    """Adds (or replaces) an event kind. Features call this at import."""
    EVENT_TYPES[event_type.kind] = event_type
    return event_type


def _num(text: str) -> float | int:
    value = float(text)
    return int(value) if value.is_integer() else value


def _fields(line: str, *names: str) -> dict | None:
    """`name[value]` pairs from a line; None if any is missing."""
    out = {}
    for name in names:
        m = re.search(re.escape(name) + r"\[([^\]]*)\]", line)
        if m is None:
            return None
        out[name] = m.group(1)
    return out


def _regex(pattern: str, numbers: tuple[str, ...] = ()) -> Callable[[str], dict | None]:
    compiled = re.compile(pattern)

    def parse(line: str) -> dict | None:
        m = compiled.search(line)
        if m is None:
            return None
        data = m.groupdict()
        for key in numbers:
            if data.get(key) is not None:
                data[key] = _num(data[key])
        return data
    return parse


def _notification_text(line: str) -> str | None:
    m = _NOTIFICATION_RE.search(line)
    return m.group(1).strip() if m else None


def _notification(prefix: str, key: str | None = None, numbers: tuple[str, ...] = ()):
    """HUD notifications whose text starts with `prefix`. `key` names the
    rest of the text (or a regex with named groups when it contains '(?P').
    """
    pattern = re.compile(key) if key and "(?P" in key else None

    def parse(line: str) -> dict | None:
        text = _notification_text(line)
        if text is None or not text.startswith(prefix):
            return None
        rest = text[len(prefix):].strip(" :")
        data: dict = {}
        if pattern is not None:
            m = pattern.search(rest)
            if m is None:
                return None
            data.update(m.groupdict())
        elif key:
            data[key] = rest
        for k in numbers:
            if data.get(k) is not None:
                data[k] = _num(data[k].replace(",", ""))
        m = _MISSION_ID_RE.search(line)
        if m and m.group(1) != _NULL_MISSION:
            data["mission_id"] = m.group(1)
        m = _OBJECTIVE_ID_RE.search(line)
        if m:
            data["objective_id"] = m.group(1)
        return data
    return parse


def _contract(prefix: str):
    base = _notification(prefix, "title")

    def parse(line: str) -> dict | None:
        data = base(line)
        if data is None:
            return None
        # "Salvage Job: Small <EM4>[200 Rep] [BP]*</EM4>" → title + markers
        title = data["title"]
        m = _TITLE_MARKERS_RE.search(title)
        if m:
            markers = m.group(1)
            rep = re.search(r"\[(\d+) Rep\]", markers)
            data["rep"] = int(rep.group(1)) if rep else None
            data["blueprint_chance"] = "[BP]" in markers
            title = _TITLE_MARKERS_RE.sub(" ", title).strip()
        data["title"] = title
        return data
    return parse


def _shop(line: str) -> dict | None:
    f = _fields(line, "shopName", "client_price", "itemName", "quantity")
    if f is None:
        return None
    return {"shop": f["shopName"], "item": f["itemName"],
            "price": _num(f["client_price"]), "quantity": _num(f["quantity"])}


def _objective_push(line: str) -> dict | None:
    """The mission server's objective updates: exact ids and state
    (INPROGRESS / COMPLETED / WITHDRAWN / FAILED), and whether it's hidden."""
    m = re.search(r"mission_id (\S+) - objective_id (\S+) - state MISSION_OBJECTIVE_STATE_(\w+)"
                  r"(?: - created \d - flags=(\S*))?", line)
    if m is None:
        return None
    flags = (m.group(4) or "").split("|")
    return {"mission_id": m.group(1), "objective_id": m.group(2), "state": m.group(3),
            "hidden": "Hidden" in flags or "HiddenInUI" in flags}


def _objective_text(line: str) -> dict | None:
    """The client's objective list: id → text as shown (may hold unresolved
    ~mission() tokens) and visibility."""
    m = re.search(r"Objective updated id=(\S+), flags=\S*, hidden=(\d), hiddenInUI=(\d), "
                  r"markerHidden=\d, uiDisplay\[Priority=-?\d+\]\[Text=(.*)\] \[Team", line)
    if m is None:
        return None
    return {"objective_id": m.group(1), "hidden": m.group(2) == "1" or m.group(3) == "1",
            "text": m.group(4).strip()}


def _commodity(price_field: str) -> Callable[[str], dict | None]:
    def parse(line: str) -> dict | None:
        f = _fields(line, "shopName", price_field, "resourceGUID", "quantity")
        if f is None:
            return None
        qty = f["quantity"].split()
        data = {"shop": f["shopName"], "resource_guid": f["resourceGUID"],
                "price": _num(f[price_field]), "quantity": _num(qty[0])}
        if len(qty) > 1:
            data["unit"] = qty[1]           # "cSCU" on purchases
        return data
    return parse


def _med_bed(line: str) -> dict | None:
    m = re.search(r"surgery event (\w+), med bed name: ([^,]*), vehicle name: ([^,]*),(.*?)\[Team", line)
    if m is None:
        return None
    parts = dict(re.findall(r"(\w+): (true|false)", m.group(4)))
    return {"result": m.group(1), "bed": m.group(2).strip(), "vehicle": m.group(3).strip(),
            "treated": [name for name, v in parts.items() if v == "true"]}


def _builtin_types() -> list[EventType]:
    n = "<SHUDEvent_OnNotification>"
    return [
        # Session and player
        EventType("session_start", "Log started", _regex(r"Log started on (?P<started>.+)$"),
                  "Game started a new log"),
        EventType("character", "<AccountLoginCharacterStatus_Character>",
                  _regex(r"geid (?P<geid>\d+) .*? name (?P<name>\S+)"), "Character logged in"),
        EventType("join_pu", "<Join PU>", _regex(r"shard\[(?P<shard>[^\]]*)\]"),
                  "Joined a PU shard", group_field="shard"),
        EventType("spawned", "OnClientSpawned] Spawned!", lambda _l: {}, "Player spawned"),
        # Notifications (every HUD notification, plus the specific ones below)
        EventType("notification", n, lambda l: (lambda t: None if t is None else {"text": t})(
            _notification_text(l)), "Any HUD notification", group_field="text"),
        EventType("contract_accepted", n, _contract("Contract Accepted:"), "Contract accepted",
                  sum_fields=("rep",), group_field="title"),
        EventType("contract_complete", n, _contract("Contract Complete:"), "Contract completed",
                  group_field="title"),
        EventType("contract_failed", n, _contract("Contract Failed:"), "Contract failed",
                  group_field="title"),
        EventType("contract_withdrawn", n, _contract("Contract Withdrawn:"), "Contract withdrawn",
                  group_field="title"),
        EventType("contract_shared", n, _contract("Contract Shared:"), "Contract shared",
                  group_field="title"),
        EventType("objective", n, _notification("New Objective:", "objective"),
                  "New or updated objective", group_field="objective"),
        EventType("objective_complete", n, _notification("Objective Complete:", "objective"),
                  "Objective completed", group_field="objective"),
        EventType("objective_withdrawn", n, _notification("Objective Withdrawn:", "objective"),
                  "Objective withdrawn", group_field="objective"),
        EventType("ship_boarded", n, _notification(
            "You have joined channel", r"^'(?P<ship>.+?) : (?P<player>[^']+)'"),
            "Boarded a ship (joined its comms channel)", group_field="ship"),
        EventType("hangar_request", n, _notification("Hangar Request Completed"),
                  "Hangar request completed"),
        EventType("awarded", n, _notification("Awarded", r"(?P<amount>[\d,]+) aUEC", ("amount",)),
                  "aUEC awarded", sum_fields=("amount",)),
        EventType("blueprint", n, _notification("Received Blueprint:", "name"),
                  "Blueprint received", group_field="name"),
        EventType("jurisdiction", n, _notification("Entered", r"^(?P<jurisdiction>.+) Jurisdiction$"),
                  "Entered a jurisdiction", group_field="jurisdiction"),
        EventType("armistice_enter", n, _notification("Entering Armistice Zone"), "Entered armistice"),
        EventType("armistice_leave", n, _notification("Leaving Armistice Zone"), "Left armistice"),
        EventType("monitored_space", n, _notification(
            "", r"^(?P<state>Entered|Exited) Monitored Space$"), "Entered/left monitored space",
            group_field="state"),
        EventType("comm_array", n, _notification(
            "Monitored Space ", r"^(?P<state>Down|Restored)$"), "Monitored space down/restored",
            group_field="state"),
        EventType("refinery_complete", n, _notification(
            "A Refinery Work Order has been Completed at", "location"),
            "Refinery work order completed", group_field="location"),
        EventType("incapacitated", n, _notification("Incapacitated:"), "Player incapacitated"),
        EventType("low_fuel", n, _notification("Low Fuel:"), "Low fuel warning"),
        EventType("qt_obstructed", n, _notification("Quantum Travel: Your destination is obstructed"),
                  "Quantum destination obstructed"),
        # Missions
        EventType("mission_end", "<EndMission>", _regex(
            r"MissionId\[(?P<mission_id>[^\]]*)\].*?CompletionType\[(?P<outcome>[^\]]*)\]"
            r"(?: Reason\[(?P<reason>[^\]]*)\])?"), "Mission ended", group_field="outcome"),
        EventType("objective_upserted", "<ObjectiveUpserted>", _objective_push,
                  "Objective created or changed (server push)", group_field="state"),
        EventType("objective_result", "<ObjectiveComplete>", _objective_push,
                  "Objective completed or withdrawn (server push)", group_field="state"),
        EventType("objective_text", "<CMissionLogEntry::UpdateActiveObjective>", _objective_text,
                  "Objective text and visibility (client)"),
        EventType("mission_marker", "<CLocalMissionPhaseMarker::CreateMarker>", _regex(
            r"missionId \[(?P<mission_id>[^\]]*)\], generator name \[(?P<generator>[^\]]*)\], "
            r"contract \[(?P<contract>[^\]]*)\], contractDefinitionId\[(?P<contract_id>[^\]]*)\]"),
            "Mission objective marker (contract identity)", group_field="contract"),
        # Travel and location
        EventType("qt_target", "<Player Selected Quantum Target", _regex(
            r"\| (?P<ship>[A-Za-z0-9_]+?)_\d+\[\d+\]\|.*?selected point (?P<target>\S+) as their destination"),
            "Quantum target selected", group_field="target"),
        EventType("qt_arrived", "<Quantum Drive Arrived", _regex(
            r"\| (?P<ship>[A-Za-z0-9_]+?)_\d+\[\d+\]\|"), "Quantum travel arrived"),
        EventType("location", "<RequestLocationInventory>", _regex(
            r"Player\[(?P<player>[^\]]*)\] requested inventory for Location\[(?P<location>[^\]]*)\]"),
            "At a location (inventory opened)", group_field="location"),
        EventType("ship_left", "<Vehicle Control Flow>", _regex(
            r"releasing control token for '(?P<ship>[A-Za-z0-9_]+?)_(?P<ship_id>\d+)'"),
            "Left a ship's pilot seat", group_field="ship"),
        # Money
        EventType("shop_buy", "SendShopBuyRequest>", _shop, "Shop purchase (request)",
                  sum_fields=("price",), group_field="item"),
        EventType("shop_sell", "SendShopSellRequest>", _shop, "Shop sale (request)",
                  sum_fields=("price",), group_field="item"),
        EventType("commodity_buy", "SendCommodityBuyRequest>", _commodity("price"),
                  "Commodity purchase (request)", sum_fields=("price",), group_field="resource_guid"),
        EventType("commodity_sell", "SendCommoditySellRequest>", _commodity("amount"),
                  "Commodity sale (request)", sum_fields=("price", "quantity"), group_field="resource_guid"),
        EventType("refinery_request", "OnRefineryRequest>", _regex(r"shopName\[(?P<shop>[^\]]*)\]"),
                  "Refinery job started", group_field="shop"),
        # Health and losses
        EventType("med_bed", "<MED BED HEAL>", _med_bed, "Med bed treatment"),
        EventType("death", "<[ActorState] Dead>", _regex(
            r"Actor '(?P<actor>[^']*)' .*?ejected from zone '(?P<zone>[^']*)'"),
            "Own death (ejected from a destroyed vehicle)", group_field="zone"),
        EventType("fatal_collision", "<FatalCollision>", _regex(
            r"for vehicle (?P<ship>[A-Za-z0-9_]+?)_\d+ \[.*?Zone: (?P<zone>[^,]*),.*?after hitting "
            r"entity: (?P<hit>\S+)"), "Ship lost to a collision", group_field="ship"),
    ]


for _t in _builtin_types():
    register(_t)


def parse_line(line: str, kinds: Iterable[str] | None = None, session: str = "",
               channel: str = "", backlog: bool = False) -> list[Event]:
    """Every event of the given kinds (all if None) in one log line."""
    events = []
    ts = None
    for kind in (EVENT_TYPES if kinds is None else kinds):
        et = EVENT_TYPES.get(kind)
        if et is None or et.needle not in line:
            continue
        try:
            data = et.parse(line)
        except Exception:        # a changed format loses this kind, never the reader
            data = None
        if data is None:
            continue
        if ts is None:
            ts = _line_time(line)
        events.append(Event(kind, ts, data, session, line, backlog, channel))
    return events


def _line_time(line: str) -> datetime | None:
    m = _TIME_RE.match(line)
    if m is None:
        return None
    try:
        return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# -- aggregation --------------------------------------------------------------
class Aggregator:
    """Running totals per event kind: count, first/last time, number of
    sessions, sums of the kind's `sum_fields` and counts per `group_field`
    value. Used by the history read and by the live reader alike.
    """

    def __init__(self):
        self._count: Counter = Counter()
        self._first: dict[str, datetime] = {}
        self._last: dict[str, datetime] = {}
        self._sessions: dict[str, set] = defaultdict(set)
        self._sums: dict[str, Counter] = defaultdict(Counter)
        self._groups: dict[str, Counter] = defaultdict(Counter)

    def add(self, event: Event) -> None:
        kind = event.kind
        self._count[kind] += 1
        if event.time is not None:
            if kind not in self._first or event.time < self._first[kind]:
                self._first[kind] = event.time
            if kind not in self._last or event.time > self._last[kind]:
                self._last[kind] = event.time
        if event.session:
            self._sessions[kind].add(event.session)
        et = EVENT_TYPES.get(kind)
        if et is None:
            return
        for name in et.sum_fields:
            value = event.data.get(name)
            if isinstance(value, (int, float)):
                self._sums[kind][name] += value
        if et.group_field is not None and event.data.get(et.group_field) is not None:
            self._groups[kind][str(event.data[et.group_field])] += 1

    def result(self) -> dict:
        out = {}
        for kind, count in self._count.items():
            entry: dict = {
                "count": count,
                "first": self._first[kind].isoformat() if kind in self._first else None,
                "last": self._last[kind].isoformat() if kind in self._last else None,
                "sessions": len(self._sessions[kind]),
            }
            if self._sums[kind]:
                entry["sums"] = dict(self._sums[kind])
            if self._groups[kind]:
                entry["by"] = dict(self._groups[kind].most_common())
            out[kind] = entry
        return out


# -- log files ----------------------------------------------------------------
@dataclass(frozen=True)
class LogSession:
    """One Game.log (current or backed up), i.e. one game run."""
    path: Path
    id: str                     # the name the game gives it when backing it up
    started: datetime | None

    @property
    def channel(self) -> str:
        """LIVE, PTU, … : Game.log sits in the channel folder, backups one below."""
        folder = self.path.parent
        return (folder.parent if folder.name.lower() == BACKUP_DIR else folder).name.upper()

    def ended(self) -> datetime | None:
        """The last timestamp in the log (when the game stopped writing)."""
        try:
            with self.path.open("rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 65536))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return None
        for line in reversed(tail.splitlines()):
            ts = _line_time(line)
            if ts is not None:
                return ts
        return None


def _read_head(path: Path) -> tuple[str, datetime | None]:
    """(session id, start time) from a log's first lines."""
    try:
        with path.open("rb") as f:
            head = f.read(4096).decode("utf-8", "replace")
    except OSError:
        return path.stem, None
    started = None
    session_id = ""
    for line in head.splitlines()[:5]:
        started = started or _line_time(line)
        m = re.search(r'BackupNameAttachment="([^"]*)"', line)
        if m:
            session_id = "Game" + m.group(1)
    return session_id or path.stem, started


def channel_dirs(game_root: Path | None) -> list[Path]:
    """Every channel folder (LIVE, PTU…) under the StarCitizen folder."""
    if game_root is None:
        return []
    return [channel.resolve_ci(game_root, ch) for ch in channel.detect_channels(game_root)]


def log_sessions(channel_dir: Path) -> list[LogSession]:
    """A channel's logs, oldest first: the backups, then Game.log (the
    newest session, or the running one)."""
    sessions = []
    backups = channel.resolve_ci(channel_dir, BACKUP_DIR)
    paths = sorted(backups.glob("*.log")) if backups.is_dir() else []
    current = channel_dir / LOG_NAME
    if current.is_file():
        paths.append(current)
    seen = set()
    for path in paths:
        session_id, started = _read_head(path)
        if session_id in seen:
            continue
        seen.add(session_id)
        sessions.append(LogSession(path, session_id, started))
    far_past = datetime.min.replace(tzinfo=timezone.utc)
    sessions.sort(key=lambda s: s.started or far_past)
    return sessions


def _events_in_file(path: Path, kinds: list[str], session: str, channel: str = "") -> list[Event]:
    """Every event of `kinds` in one file. Searches the raw bytes for each
    kind's needle and only decodes the lines that contain one, which keeps
    a full-history read to seconds."""
    try:
        blob = path.read_bytes()
    except OSError:
        return []
    by_needle: dict[bytes, list[str]] = defaultdict(list)
    for kind in kinds:
        if kind in EVENT_TYPES:
            by_needle[EVENT_TYPES[kind].needle.encode()].append(kind)
    found: list[tuple[int, Event]] = []
    for needle, needle_kinds in by_needle.items():
        pos = blob.find(needle)
        while pos != -1:
            start = blob.rfind(b"\n", 0, pos) + 1
            end = blob.find(b"\n", pos)
            end = len(blob) if end == -1 else end
            line = blob[start:end].decode("utf-8", "replace").rstrip("\r")
            for event in parse_line(line, needle_kinds, session, channel):
                found.append((start, event))
            pos = blob.find(needle, end)
    found.sort(key=lambda pair: pair[0])     # log order, whichever needle found it
    return [event for _pos, event in found]


def all_sessions(game_root: Path | None, channels: Iterable[str] | None = None) -> list[LogSession]:
    """Every log on disk, of the given channels (default: all), oldest first."""
    wanted = {c.upper() for c in channels} if channels is not None else None
    sessions = [
        s for d in channel_dirs(game_root)
        if wanted is None or d.name.upper() in wanted
        for s in log_sessions(d)
    ]
    far_past = datetime.min.replace(tzinfo=timezone.utc)
    sessions.sort(key=lambda s: s.started or far_past)
    return sessions


# -- history ------------------------------------------------------------------
OUTPUT_EVENTS = "events"
OUTPUT_AGGREGATE = "aggregate"


class Cancelled(Exception):
    pass


def read_history(
    game_root: Path | None,
    kinds: Iterable[str],
    output: str = OUTPUT_EVENTS,
    *,
    channels: Iterable[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[Event] | dict:
    """Reads every log on disk for the given event kinds.

    `output` is OUTPUT_EVENTS (a list of Event, oldest first) or
    OUTPUT_AGGREGATE (Aggregator.result(): per-kind totals). `channels`
    limits the channel folders (default: all found). `progress(done, total)`
    is called after each file; setting `cancel` stops with Cancelled.
    """
    kinds = list(kinds)
    unknown = [k for k in kinds if k not in EVENT_TYPES]
    if unknown:
        raise ValueError(f"Unknown event kinds: {', '.join(unknown)}")
    if output not in (OUTPUT_EVENTS, OUTPUT_AGGREGATE):
        raise ValueError(f"Unknown output type: {output}")
    sessions = all_sessions(game_root, channels)
    agg = Aggregator() if output == OUTPUT_AGGREGATE else None
    events: list[Event] = []
    for i, session in enumerate(sessions):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        for event in _events_in_file(session.path, kinds, session.id, session.channel):
            if event.time is not None and (
                    (since is not None and event.time < since) or (until is not None and event.time > until)):
                continue
            if agg is not None:
                agg.add(event)
            else:
                events.append(event)
        if progress is not None:
            progress(i + 1, len(sessions))
    if agg is not None:
        return agg.result()
    far_past = datetime.min.replace(tzinfo=timezone.utc)
    events.sort(key=lambda e: e.time or far_past)   # stable: log order within a time
    return events


class HistoryJob(QObject):
    """Runs read_history on a worker thread. Connect to `finished` (the
    list of events or the aggregate dict), `failed` and `progress`."""
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, game_root: Path | None, kinds: Iterable[str], output: str = OUTPUT_EVENTS,
                 parent=None, **options):
        super().__init__(parent)
        self._args = (game_root, list(kinds), output)
        self._options = options
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        try:
            result = read_history(*self._args, progress=self.progress.emit, cancel=self._cancel,
                                  **self._options)
        except Cancelled:
            self.failed.emit("Cancelled")
        except Exception as exc:
            self.failed.emit(f"Reading the game logs failed: {exc}")
        else:
            self.finished.emit(result)


# -- live ---------------------------------------------------------------------
def _game_started_at() -> float | None:
    """When the running StarCitizen.exe started (epoch seconds), or None."""
    for proc in psutil.process_iter(["name", "cmdline", "create_time"]):
        try:
            name = (proc.info["name"] or "").lower()
            argv0 = ((proc.info["cmdline"] or [""])[0] or "").lower().replace("\\", "/")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        exe = osutil.GAME_EXE
        if name == exe or argv0 == exe or argv0.endswith("/" + exe):
            return proc.info["create_time"]
    return None


Listener = Callable[[Event], None]


class LiveReader(QObject):
    """Follows the current play session's Game.log.

    States: "off", "waiting" (no game running, or its log isn't there yet),
    "reading" (following a session). A session counts as current when
    StarCitizen.exe is running and its Game.log was started after the game
    process; a leftover Game.log from an earlier run is never read.

    Hook features in with `add_listener(callback, kinds)` (called on the UI
    thread) or connect to the `event` signal; `session_aggregate()` has the
    running totals of this session and `session_events()` the events.
    """
    event = Signal(object)                  # Event
    session_started = Signal(str)           # session id
    session_ended = Signal(str)
    state_changed = Signal(str)

    # Where the log may lag behind the process start (and clock rounding).
    START_SLACK_SECONDS = 120

    def __init__(self, game_root_fn: Callable[[], Path | None], parent=None):
        super().__init__(parent)
        self._game_root_fn = game_root_fn
        self._listeners: list[tuple[Listener, frozenset | None]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "off"
        self._session: LogSession | None = None
        self._aggregate = Aggregator()
        self._events: list[Event] = []
        self.event.connect(self._dispatch)

    # -- public ----------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def session(self) -> LogSession | None:
        return self._session

    @property
    def channel(self) -> str:
        return self._session.channel if self._session is not None else ""

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="gamelog-live")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        self._set_state("off")

    def add_listener(self, callback: Listener, kinds: Iterable[str] | None = None) -> Callable[[], None]:
        """Calls `callback(event)` for live events of `kinds` (all if None).
        Returns a function that removes the listener again."""
        entry = (callback, frozenset(kinds) if kinds is not None else None)
        self._listeners.append(entry)
        return lambda: self._listeners.remove(entry) if entry in self._listeners else None

    def session_aggregate(self) -> dict:
        with self._lock:
            return self._aggregate.result()

    def session_events(self, kinds: Iterable[str] | None = None) -> list[Event]:
        wanted = set(kinds) if kinds is not None else None
        with self._lock:
            return [e for e in self._events if wanted is None or e.kind in wanted]

    # -- internals -------------------------------------------------------------
    def _dispatch(self, event: Event) -> None:
        for callback, kinds in list(self._listeners):
            if kinds is None or event.kind in kinds:
                try:
                    callback(event)
                except Exception as exc:       # one broken feature mustn't stop the rest
                    print(f"gamelog listener {callback!r} failed: {exc}")

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _current_log(self) -> Path | None:
        """The newest Game.log among the channel folders (the channel being
        played writes to its own)."""
        best, best_mtime = None, -1.0
        for d in channel_dirs(self._game_root_fn()):
            path = d / LOG_NAME
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best, best_mtime = path, mtime
        return best

    def _run(self) -> None:
        self._set_state("waiting")
        offset = 0
        pending = b""
        next_process_check = 0.0
        game_start: float | None = None
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_process_check:
                next_process_check = now + PROCESS_POLL_SECONDS
                game_start = _game_started_at()
                if game_start is None and self._session is not None:
                    self._read_more(self._session.path, offset, pending)   # last lines
                    self._end_session()
            if game_start is not None:
                if self._session is None:
                    session = self._find_session(game_start)
                    if session is not None:
                        self._begin_session(session)
                        offset, pending = 0, b""
                        # Whatever is in the log already happened before we
                        # attached: mark it as backlog (catch-up).
                        offset, pending, _ = self._read_more(session.path, 0, b"", backlog=True)
                else:
                    offset, pending, replaced = self._read_more(self._session.path, offset, pending)
                    if replaced:
                        # The game restarted between two process checks.
                        self._end_session()
                        offset, pending = 0, b""
                        continue
            self._stop.wait(LIVE_POLL_SECONDS)
        if self._session is not None:
            self._end_session()

    def _find_session(self, game_start: float) -> LogSession | None:
        path = self._current_log()
        if path is None:
            return None
        session_id, started = _read_head(path)
        if started is None or started.timestamp() < game_start - self.START_SLACK_SECONDS:
            return None      # still the previous run's log
        return LogSession(path, session_id, started)

    def _begin_session(self, session: LogSession) -> None:
        with self._lock:
            self._session = session
            self._aggregate = Aggregator()
            self._events = []
        self._set_state("reading")
        self.session_started.emit(session.id)

    def _end_session(self) -> None:
        session = self._session
        self._session = None
        self._set_state("waiting")
        if session is not None:
            self.session_ended.emit(session.id)

    def _read_more(self, path: Path, offset: int, pending: bytes,
                   backlog: bool = False) -> tuple[int, bytes, bool]:
        """Reads what was appended since `offset`. The file is opened and
        closed on every poll, so the game can still move it to logbackups
        on Windows. Returns (offset, unfinished line, file was replaced)."""
        session = self._session
        if offset and session is not None:
            head_id, head_started = _read_head(path)
            if head_started is not None and head_id != session.id:   # unreadable ≠ replaced
                return offset, pending, True
        try:
            with path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                if size < offset:
                    return offset, pending, True
                f.seek(offset)
                chunk = f.read(size - offset)
        except OSError:
            return offset, pending, False
        offset += len(chunk)
        data = pending + chunk
        lines = data.split(b"\n")
        pending = lines.pop()               # last piece may be a half-written line
        session_id = session.id if session is not None else ""
        channel_name = session.channel if session is not None else ""
        for raw in lines:
            line = raw.decode("utf-8", "replace").rstrip("\r")
            for event in parse_line(line, session=session_id, channel=channel_name, backlog=backlog):
                with self._lock:
                    self._aggregate.add(event)
                    self._events.append(event)
                self.event.emit(event)
        return offset, pending, False
