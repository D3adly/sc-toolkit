"""Session summaries for the SC-Toolkit service's stats backup: per game
session, only the numbers the service's stats pages show (the same sections
as My Stats), never log lines. The service stores one summary per
(channel, log id) and replaces it when it's sent again, so uploads are
idempotent: the live session can be re-sent every few minutes.

    digest(events, sessions, contracts) -> [summary, …]
    summary = {"channel", "logId", "hash", "startedAt", "endedAt", "character",
               "counters": {metric: {key: n}}, "missions": [...], "blueprints": [...]}

`hash` covers everything else, so the launcher only uploads what changed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime

from app import gamelog, stats
from app.tracker import REFINERY_REMINDER_SECONDS

_OUTCOMES = {"Complete": "complete", "Fail": "failed", "Failed": "failed",
             "Abandon": "abandoned", "Withdrawn": "abandoned"}

# event kind -> (metric, data field for the key or None for a plain count)
_COUNTED = {
    "contract_accepted": ("contracts_accepted", None),
    "contract_shared": ("contracts_shared", None),
    "qt_arrived": ("qt_arrivals", None),
    "qt_target": ("qt_targets", "target"),
    "location": ("locations", "location"),
    "ship_boarded": ("ship_boarded", "ship"),
    "hangar_request": ("hangar_requests", None),
    "death": ("deaths", None),
    "incapacitated": ("incapacitated", None),
    "med_bed": ("med_beds", None),
}
_PRETTY_KEYS = {"qt_targets", "locations"}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def digest(events: list[gamelog.Event], sessions: list[gamelog.LogSession], contracts=None) -> list[dict]:
    by_session: dict[str, list[gamelog.Event]] = defaultdict(list)
    for e in events:
        by_session[e.session].append(e)
    out = []
    for s in sessions:
        if not s.started:
            continue
        out.append(_summary(s, by_session.get(s.id, []), contracts))
    return out


def _summary(session: gamelog.LogSession, events: list[gamelog.Event], contracts) -> dict:
    counters: dict[str, Counter] = defaultdict(Counter)
    joins = [e.time for e in events if e.kind == "join_pu" and e.time]
    character = ""
    for e in events:
        if e.kind == "character" and not character:
            character = str(e.data.get("name") or e.data.get("character") or "")
        counted = _COUNTED.get(e.kind)
        if counted:
            metric, field = counted
            key = str(e.data.get(field) or "") if field else ""
            if metric in _PRETTY_KEYS and key:
                key = stats.pretty(key)
            counters[metric][key] += 1
        elif e.kind == "fatal_collision":
            hit = stats.pretty(e.data.get("hit", "")).split(" ")[0]
            counters["collisions"][f"{stats.pretty(e.data.get('ship', ''))} → {hit}"] += 1
        elif e.kind == "refinery_complete":
            # The game repeats completion notices after joining a server: not counted.
            if e.time and any(0 <= (e.time - t).total_seconds() <= REFINERY_REMINDER_SECONDS for t in joins):
                continue
            counters["refinery_completed"][str(e.data.get("location") or "")] += 1
        elif e.kind == "awarded":
            try:
                counters["awarded_auec"][""] += int(str(e.data.get("amount", "0")).replace(",", ""))
            except ValueError:
                pass

    missions = []
    for m in stats._missions(events):
        outcome = _OUTCOMES.get(m.outcome)
        if not outcome or not (m.title or m.contract):
            continue
        info = contracts.find(m.contract_id, m.contract) if contracts is not None else None
        missions.append({
            "title": m.title or stats.pretty(m.contract),
            "contractor": (info or {}).get("contractor") or stats.pretty(m.generator.replace("_Generator", "")),
            "outcome": outcome,
            "acceptedAt": _iso(m.accepted), "endedAt": _iso(m.ended),
            "rep": m.rep or 0, "blueprints": len(m.blueprints),
        })

    blueprints = []
    for e in events:
        if e.kind != "blueprint" or not e.time or not e.data.get("name"):
            continue
        name = e.data["name"]
        category = contracts.blueprint_category(name) if contracts is not None else None
        key, size = stats.blueprint_type(category)
        if category is None:
            key = stats.guess_blueprint_type(name)
        blueprints.append({"name": name, "type": key, "size": size, "receivedAt": _iso(e.time)})

    summary = {
        "channel": session.channel,
        "logId": session.id,
        "startedAt": _iso(session.started),
        "endedAt": _iso(session.ended()),
        "character": character,
        "counters": {metric: dict(c) for metric, c in sorted(counters.items())},
        "missions": missions,
        "blueprints": blueprints,
    }
    summary["hash"] = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
    return summary
