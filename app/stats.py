"""Player statistics from every Game.log on disk (app.gamelog history), for
the My Stats view: all time, and the last play session.

`compute()` returns display-ready sections, so the view only lays them out:
    {"sessions": n, "first": datetime, "last": datetime,
     "scopes": {"all": [Section…], "last": [Section…]}, "last_label": str}
    Section = {"title", "tiles": [(label, value, hint)], "lists": [List…],
               "filter": bool, "note"}
    List = {"title", "rows": [(name, value)] (all of them),
            "limit": rows shown before "…and n more" (None: all),
            "columns": flow the rows into as many columns as fit,
            "key": filter key and glyph name (filter sections)}
A "filter" section shows its lists one at a time, or all, from a row of
glyph buttons (Blueprints: one list per blueprint type).
Missions are rebuilt per session with app.tracker, so a mission's title,
contract, outcome and blueprints are joined the same way as in the overlay.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import gamelog
from app.tracker import REFINERY_REMINDER_SECONDS, Mission, SessionTracker

# Everything except the catch-all notification kind (big, and covered by
# the specific ones).
KINDS = [k for k in gamelog.EVENT_TYPES if k != "notification"]
LIST_ROWS = 12
BLUEPRINT_ROWS = 8   # per type, before "…and n more"

# Blueprint types: (key = glyph name, title, game categories by prefix). The
# game's categories (BlueprintCategoryRecord) have no display names.
BLUEPRINT_TYPES = [
    ("weapons", "Personal weapons", ("FPSWeapons",)),
    ("armour", "Armour", ("FPSArmours",)),
    ("components", "Ship components", ("VehicleComponent",)),
    ("ship_weapons", "Ship weapons", ("VehicleWeapons",)),
    ("utility", "Utility", ("Utility",)),
    ("medical", "Medical", ("Medical",)),
    ("power", "Fuses & batteries", ("FuseBattery",)),
    ("mission", "Mission items", ("MissionItem",)),
    ("other", "Other", ()),
]


def load(game_root: Path | None, contracts=None, progress=None, cancel=None) -> dict:
    """Reads the logs and computes everything. Call off the UI thread."""
    sessions = gamelog.all_sessions(game_root)
    events = gamelog.read_history(game_root, KINDS, gamelog.OUTPUT_EVENTS,
                                  progress=progress, cancel=cancel)
    return compute(events, sessions, contracts)


# -- formatting ----------------------------------------------------------------
def _n(value) -> str:
    return f"{value:,.0f}"


def _duration(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    if hours >= 100:
        return f"{hours:,}h"
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _date(dt: datetime | None) -> str:
    # Not strftime("%b"): that follows the system language, the app is English.
    if dt is None:
        return "—"
    dt = dt.astimezone()
    return f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"


def _datetime(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    dt = dt.astimezone()
    return f"{dt.day} {_MONTHS[dt.month - 1]} {dt:%H:%M}"


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


def pretty(name: str) -> str:
    """Log identifiers → readable text: 'Stanton2_Orison' → 'Stanton2 Orison',
    'levski_all-001' → 'Levski'."""
    name = re.sub(r"[-_]\d{2,}$", "", name)        # instance numbers
    name = re.sub(r"_all$", "", name)
    words = [w for w in re.split(r"[_]+", name) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or name


def _list(title: str, counter: Counter, fmt=_n, limit: int | None = LIST_ROWS, columns: bool = False) -> dict:
    rows = [(name, fmt(value)) for name, value in counter.most_common() if name]
    return {"title": title, "rows": rows, "limit": limit, "columns": columns}


# The name already says the size: "Singe Cannon (S2)", "Ind/0/B Defiant".
_HAS_SIZE_RE = re.compile(r"\(S\d\)|^[A-Za-z]{3}/\d/")


def blueprint_type(category: str | None) -> tuple[str, str]:
    """Game category -> (type key, size label or "")."""
    for key, _title, prefixes in BLUEPRINT_TYPES:
        if category and category.startswith(prefixes):
            size = re.search(r"S(\d)$", category)
            return key, f"S{size.group(1)}" if size else ""
    return "other", ""


# -- computing -----------------------------------------------------------------


def _missions(events: list[gamelog.Event]) -> list[Mission]:
    tracker = SessionTracker()
    missions: list[Mission] = []
    session = None
    for e in events:
        if e.session != session:
            missions.extend(tracker.missions.values())
            tracker.new_session(e.session, e.channel)
            session = e.session
        tracker.add(e)
    missions.extend(tracker.missions.values())
    return missions


def _scope(events: list[gamelog.Event], sessions: list[gamelog.LogSession], contracts) -> list[dict]:
    single = len(sessions) == 1
    by_kind: dict[str, list[gamelog.Event]] = {}
    for e in events:
        by_kind.setdefault(e.kind, []).append(e)

    def kind(k: str) -> list[gamelog.Event]:
        return by_kind.get(k, [])

    def count(k: str, field: str, fmt=str) -> Counter:
        return Counter(fmt(e.data.get(field) or "") for e in kind(k))

    sections = []

    # Play time
    spans = []
    longest: list[tuple[datetime, timedelta]] = []
    for s in sessions:
        end = s.ended()
        if s.started and end and end > s.started:
            spans.append(end - s.started)
            longest.append((s.started, end - s.started))
    longest.sort(key=lambda pair: pair[1], reverse=True)
    total = sum(spans, timedelta())
    tiles = [("Time played", _duration(total), "From game start to the log's last line, summed")]
    if not single:
        tiles = [("Sessions", _n(len(sessions)), "Game launches with a log on disk"), *tiles,
                 ("Average session", _duration(total / len(spans)) if spans else "—", ""),
                 ("Longest session", _duration(max(spans)) if spans else "—", "")]
    sections.append({
        "title": "Play time",
        "tiles": tiles,
        "lists": [{
            "title": "Longest sessions",
            "rows": [(_datetime(start), _duration(span)) for start, span in longest],
            "limit": 5,
        }] if not single else [],
    })

    # Missions
    missions = [m for m in _missions(events) if m.title or m.contract]
    outcomes = Counter(m.outcome or "Active" for m in missions)
    accepted = len(kind("contract_accepted"))
    completed = [m for m in missions if m.outcome == "Complete"]
    failed = outcomes["Fail"] + outcomes["Failed"]
    abandoned = outcomes["Abandon"] + outcomes["Withdrawn"]
    finished = len(completed) + failed + abandoned
    rep = sum(m.rep or 0 for m in completed)
    durations = [m.ended - m.accepted for m in completed if m.ended and m.accepted and m.ended > m.accepted]
    contractors: Counter = Counter()
    kinds: Counter = Counter()
    for m in completed:
        info = contracts.find(m.contract_id, m.contract) if contracts is not None else None
        contractors[(info or {}).get("contractor") or pretty(m.generator.replace("_Generator", ""))] += 1
        kinds[m.title or pretty(m.contract)] += 1
    sections.append({
        "title": "Missions",
        "tiles": [
            ("Accepted", _n(accepted), ""),
            ("Completed", _n(len(completed)), ""),
            ("Failed", _n(failed), ""),
            ("Abandoned", _n(abandoned), "Abandoned or withdrawn"),
            ("Success rate", _pct(len(completed), finished), "Completed out of all finished missions"),
            ("Reputation earned", _n(rep), "From the [n Rep] marker in completed contract titles"),
            ("Average mission", _duration(sum(durations, timedelta()) / len(durations)) if durations else "—",
             "Accepted to completed"),
            ("Shared with you", _n(len(kind("contract_shared"))), ""),
        ],
        "lists": [
            _list("Most completed", kinds),
            _list("Contractors (completed)", contractors),
        ],
    })

    # Blueprints, grouped by the game's blueprint categories
    blueprints = kind("blueprint")
    names = Counter(e.data.get("name", "") for e in blueprints)
    latest: dict[str, datetime | None] = {}
    for e in sorted(blueprints, key=lambda e: e.time or datetime.min.replace(tzinfo=timezone.utc)):
        latest[e.data.get("name", "")] = e.time
    by_type: dict[str, list[tuple[str, str]]] = {}
    for name in sorted(latest, key=lambda n: latest[n] or datetime.min.replace(tzinfo=timezone.utc),
                       reverse=True):
        if not name:
            continue
        key, size = blueprint_type(contracts.blueprint_category(name) if contracts is not None else None)
        value = _datetime(latest[name])
        if names[name] > 1:
            value = f"×{names[name]} · {value}"
        if size and not _HAS_SIZE_RE.search(name):
            name = f"{name}  ({size})"
        by_type.setdefault(key, []).append((name, value))
    sections.append({
        "title": "Blueprints",
        "tiles": [
            ("Received", _n(len(blueprints)), ""),
            ("Different", _n(len(names)), ""),
            ("From missions", _n(sum(len(m.blueprints) for m in completed)),
             "Received within seconds of completing a mission"),
        ],
        "filter": True,
        "lists": [{"title": title, "key": key, "rows": by_type[key], "limit": BLUEPRINT_ROWS,
                   "columns": True}
                  for key, title, _prefixes in BLUEPRINT_TYPES if by_type.get(key)],
        "note": "" if contracts is not None else
                "Blueprint types come from the game files, which couldn't be read; all are under Other.",
    })

    # Travel
    locations = count("location", "location", pretty)
    sections.append({
        "title": "Travel",
        "tiles": [
            ("Quantum jumps", _n(len(kind("qt_arrived"))), "Arrivals at a quantum destination"),
            ("Places visited", _n(len([k for k in locations if k])), "Stations and cities where you opened your inventory"),
        ],
        "lists": [
            _list("Top quantum destinations", count("qt_target", "target", pretty)),
            _list("Top places", locations),
        ],
    })

    # Ships
    ships = count("ship_boarded", "ship")
    sections.append({
        "title": "Ships",
        "tiles": [
            ("Ships flown", _n(len([k for k in ships if k])), "Different ships you boarded"),
            ("Boardings", _n(len(kind("ship_boarded"))), ""),
            ("Hangar requests", _n(len(kind("hangar_request"))), ""),
        ],
        "lists": [_list("Boardings per ship", ships, limit=None, columns=True)],
    })

    # Health and losses
    collisions = Counter(
        f"{pretty(e.data.get('ship', ''))} → {pretty(e.data.get('hit', '')).split(' ')[0]}"
        for e in kind("fatal_collision"))
    sections.append({
        "title": "Health & losses",
        "tiles": [
            ("Deaths", _n(len(kind("death"))), "Logged when you're ejected from a destroyed ship"),
            ("Incapacitated", _n(len(kind("incapacitated"))), ""),
            ("Med bed treatments", _n(len(kind("med_bed"))), ""),
            ("Ships lost to collisions", _n(len(kind("fatal_collision"))), ""),
        ],
        "lists": [_list("Collisions (ship → what it hit)", collisions)],
    })

    # Refining: completion notices, minus the repeats after joining a server
    joins: dict[str, list[datetime]] = {}
    for e in kind("join_pu"):
        if e.time:
            joins.setdefault(e.session, []).append(e.time)

    def reminder(e: gamelog.Event) -> bool:
        return bool(e.time) and any(0 <= (e.time - t).total_seconds() <= REFINERY_REMINDER_SECONDS
                                    for t in joins.get(e.session, []))

    done = [e for e in kind("refinery_complete") if not reminder(e)]
    sections.append({
        "title": "Refining",
        "tiles": [
            ("Work orders completed", _n(len(done)),
             "Completion notices while you played. The game repeats them each time you join a "
             "server; those aren't counted."),
        ],
        "lists": [_list("Completed at", Counter(e.data.get("location") or "" for e in done))],
    })
    return sections


def compute(events: list[gamelog.Event], sessions: list[gamelog.LogSession], contracts=None) -> dict:
    result = {
        "sessions": len(sessions),
        "first": sessions[0].started if sessions else None,
        "last": sessions[-1].started if sessions else None,
        "scopes": {"all": _scope(events, sessions, contracts)},
        "last_label": "",
    }
    if sessions:
        latest = sessions[-1]
        last_events = [e for e in events if e.session == latest.id]
        result["scopes"]["last"] = _scope(last_events, [latest], contracts)
        end = latest.ended()
        result["last_label"] = (f"{_datetime(latest.started)} – {end.astimezone():%H:%M}"
                                if end else _datetime(latest.started))
    result["range"] = f"{_date(result['first'])} – {_date(sessions[-1].ended() if sessions else None)}"
    return result
