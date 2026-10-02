"""My Ships: the ships the player says they own, kept in the data folder
(hangar.json). A list rather than a set: owning the same ship twice (one
pledged, one bought in game) is common.

Entries point at the ship catalogue (app.ships) by key and keep the ship's
name too, so an entry still reads right if the catalogue ever loses it.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path

from app import config

HANGAR_FILE = config.DATA_DIR / "hangar.json"
PLEDGE, INGAME = "pledge", "ingame"
ACQUIRED = {PLEDGE: "Pledge", INGAME: "In-game"}


@dataclass
class Entry:
    ship: str                   # catalogue key (app.ships.Ship.key)
    ship_name: str
    acquired: str = PLEDGE      # PLEDGE or INGAME
    name: str = ""              # the player's own name for it
    insurance: str = ""         # "LTI", "120 months", … ("" = not set)
    notes: str = ""
    added: str = field(default_factory=lambda: date.today().isoformat())
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


def load(path: Path | None = None) -> list[Entry]:
    path = path or HANGAR_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    known = {f.name for f in fields(Entry)}
    out = []
    for item in raw.get("ships", []) if isinstance(raw, dict) else []:
        if isinstance(item, dict) and item.get("ship"):
            out.append(Entry(**{k: str(v) for k, v in item.items() if k in known}))
    return out


def save(entries: list[Entry], path: Path | None = None) -> None:
    path = path or HANGAR_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "ships": [asdict(e) for e in entries]}, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
