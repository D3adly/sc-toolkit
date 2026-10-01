"""Player statistics from every Game.log on disk (app.gamelog history), for
the My Stats view: all time, and the last play session.

`compute()` returns display-ready sections, so the view only lays them out:
    {"sessions": n, "first": datetime, "last": datetime,
     "scopes": {"all": [Section…], "last": [Section…]}, "last_label": str}
    Section = {"title", "tiles": [(label, value, hint)],
               "lists": [{"title", "rows": [(name, value)], "more": n}], "note"}
Missions are rebuilt per session with app.tracker, so a mission's title,
contract, outcome and blueprints are joined the same way as in the overlay.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import gamelog
from app.tracker import Mission, SessionTracker

# Everything except the catch-all notification kind (big, and covered by
# the specific ones).
KINDS = [k for k in gamelog.EVENT_TYPES if k != "notification"]
LIST_ROWS = 12


def load(game_root: Path | None, contracts=None, progress=None, cancel=None) -> dict:
    """Reads the logs and computes everything. Call off the UI thread."""
    sessions = gamelog.all_sessions(game_root)
    events = gamelog.read_history(game_root, KINDS, gamelog.OUTPUT_EVENTS,
                                  progress=progress, cancel=cancel)
    return compute(events, sessions, contracts)


# -- formatting ----------------------------------------------------------------
def _n(value) -> str:
    return f"{value:,.0f}"


def _money(value) -> str:
    return f"{value:,.0f} aUEC"


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


def _top(counter: Counter, fmt=_n, limit: int = LIST_ROWS) -> tuple[list, int]:
    rows = [(name, fmt(value)) for name, value in counter.most_common(limit) if name]
    return rows, max(0, len([k for k in counter if k]) - limit)


def _list(title: str, counter: Counter, fmt=_n, limit: int = LIST_ROWS) -> dict:
    rows, more = _top(counter, fmt, limit)
    return {"title": title, "rows": rows, "more": more}


# -- computing -----------------------------------------------------------------
def _lookup(contracts):
    if contracts is None:
        return lambda _m: None
    return lambda m: contracts.find(m.contract_id, m.contract) if (m.contract_id or m.contract) else None


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
    sections.append({
        "title": "Play time",
        "tiles": [
            ("Sessions", _n(len(sessions)), "Game launches with a log on disk"),
            ("Time played", _duration(total), "From game start to the log's last line, summed"),
            ("Average session", _duration(total / len(spans)) if spans else "—", ""),
            ("Longest session", _duration(max(spans)) if spans else "—", ""),
        ],
        "lists": [{
            "title": "Longest sessions",
            "rows": [(_datetime(start), _duration(span)) for start, span in longest[:5]],
            "more": 0,
        }] if len(sessions) > 1 else [],
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

    # Blueprints
    blueprints = kind("blueprint")
    names = Counter(e.data.get("name", "") for e in blueprints)
    recent = sorted(blueprints, key=lambda e: e.time or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    sections.append({
        "title": "Blueprints",
        "tiles": [
            ("Received", _n(len(blueprints)), ""),
            ("Different", _n(len(names)), ""),
            ("From missions", _n(sum(len(m.blueprints) for m in completed)),
             "Received within seconds of completing a mission"),
        ],
        "lists": [{
            "title": "Latest",
            "rows": [(e.data.get("name", ""), _datetime(e.time)) for e in recent[:LIST_ROWS * 2]],
            "more": max(0, len(recent) - LIST_ROWS * 2),
        }],
    })

    # Money
    def total(k: str) -> float:
        return sum(e.data.get("price") or 0 for e in kind(k))

    awarded = sum(e.data.get("amount") or 0 for e in kind("awarded"))
    payer = SessionTracker(lookup=_lookup(contracts))
    paid = [payer.payout(m) for m in completed]
    mission_auec = sum(p.auec for p in paid)
    other_awards = awarded - sum(m.awarded for m in completed)
    scrip: Counter = Counter()
    for p in paid:
        for name, amount in p.items:
            scrip[name] += amount
    spent_items = Counter()
    for e in kind("shop_buy"):
        spent_items[pretty(e.data.get("item", ""))] += e.data.get("price") or 0
    shops = Counter()
    for e in kind("commodity_sell"):
        shops[pretty(e.data.get("shop", "").removeprefix("SCShop_"))] += e.data.get("price") or 0
    trade = total("commodity_sell") - total("commodity_buy")
    sections.append({
        "title": "Money",
        "tiles": [
            ("Mission payouts (known)", _money(mission_auec),
             "Fixed contract rewards and aUEC logged right after a completion. Most contracts pay a "
             "rate the game calculates, which isn't in the game files or the log."),
            ("Other awards", _money(other_awards), "\"Awarded n aUEC\" notifications not tied to a mission"),
            ("Shop purchases", _money(total("shop_buy")), ""),
            ("Shop sales", _money(total("shop_sell")), ""),
            ("Commodities bought", _money(total("commodity_buy")), ""),
            ("Commodities sold", _money(total("commodity_sell")), ""),
            ("Trade balance", _money(trade), "Commodities sold minus bought"),
        ],
        "lists": [
            _list("Biggest purchases", spent_items, _money),
            _list("Where you sold cargo", shops, _money),
            _list("Item rewards from missions", scrip),
        ],
        "note": "From the game's purchase and sale requests; a transaction that failed may still count. "
                "Mission payouts and your balance aren't in the log.",
    })

    # Travel
    locations = count("location", "location", pretty)
    sections.append({
        "title": "Travel",
        "tiles": [
            ("Quantum jumps", _n(len(kind("qt_arrived"))), "Arrivals at a quantum destination"),
            ("Places visited", _n(len([k for k in locations if k])), "Stations and cities where you opened your inventory"),
            ("Armistice zones entered", _n(len(kind("armistice_enter"))), ""),
            ("Jurisdictions entered", _n(len(kind("jurisdiction"))), ""),
        ],
        "lists": [
            _list("Top quantum destinations", count("qt_target", "target", pretty)),
            _list("Top places", locations),
            _list("Jurisdictions", count("jurisdiction", "jurisdiction")),
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
        "lists": [_list("Most boarded", ships)],
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
            ("Low fuel warnings", _n(len(kind("low_fuel"))), ""),
        ],
        "lists": [_list("Collisions (ship → what it hit)", collisions)],
    })

    # Industry
    sections.append({
        "title": "Mining & refining",
        "tiles": [
            ("Refinery jobs started", _n(len(kind("refinery_request"))), ""),
            ("Refinery jobs completed", _n(len(kind("refinery_complete"))), ""),
        ],
        "lists": [_list("Refinery orders completed at", count("refinery_complete", "location"))],
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
