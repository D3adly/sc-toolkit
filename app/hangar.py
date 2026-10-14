"""My Ships: the ships the player says they own. A list rather than a set:
owning the same ship twice (one pledged, one bought in game) is common.

Entries point at the ship catalogue (app.ships) by key and keep the ship's
name too, so an entry still reads right if the catalogue ever loses it.

Storage, one file per owner (app.sync keeps them in step with sc-toolbox.com):
- hangar.json: the local list, used while signed out (and before any
  account was linked). The first account that syncs on this PC takes it
  over (`claimed_by`); later accounts start from what's online.
- hangar-<account id>.json: an account's copy, with its sync state
  (`rev`: the service's revision last seen; `synced_ms`: when the last sync
  started, so edits after it are sent next time).

Every edit stamps the entry's `updated_at` (Unix ms): per entry, the newer
edit wins online. A removal is kept as a tombstone (`deleted`) until the
service has it, so it can't come back from the other side.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date
from pathlib import Path

from app import config

HANGAR_FILE = config.DATA_DIR / "hangar.json"
PLEDGE, INGAME = "pledge", "ingame"
ACQUIRED = {PLEDGE: "Pledge", INGAME: "In-game"}
# The fields an edit changes (what the service keeps per entry).
CONTENT = ("ship", "ship_name", "acquired", "name", "insurance", "notes", "added")


def now_ms() -> int:
    return int(time.time() * 1000)


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
    updated_at: int = 0         # Unix ms of the last edit (0 = before sync existed)
    deleted: bool = False       # a removal not yet confirmed online

    def content(self) -> tuple:
        return tuple(getattr(self, f) for f in CONTENT)


@dataclass
class Store:
    path: Path
    entries: list[Entry] = field(default_factory=list)   # tombstones included
    account: str = ""
    rev: int = 0
    synced_ms: int = 0
    claimed_by: str = ""

    def live(self) -> list[Entry]:
        return [e for e in self.entries if not e.deleted]

    def pending(self) -> list[Entry]:
        """Edits the service hasn't seen: everything changed since the last sync started."""
        return [e for e in self.entries if e.updated_at > self.synced_ms or (not self.rev and not self.synced_ms)]


def _entry(item: dict) -> Entry | None:
    if not isinstance(item, dict) or not (item.get("ship") or item.get("deleted")):
        return None
    known = {f.name: f.type for f in fields(Entry)}
    values = {}
    for k, v in item.items():
        if k not in known:
            continue
        if k == "updated_at":
            values[k] = int(v or 0)
        elif k == "deleted":
            values[k] = bool(v)
        else:
            values[k] = str(v)
    values.setdefault("ship", "")
    values.setdefault("ship_name", "")
    return Entry(**values)


def path_for(account: str | None) -> Path:
    return config.DATA_DIR / f"hangar-{account}.json" if account else HANGAR_FILE


def read(account: str | None = None) -> Store:
    path = path_for(account)
    store = Store(path, account=account or "")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return store
    if not isinstance(raw, dict):
        return store
    store.entries = [e for e in (_entry(i) for i in raw.get("ships", [])) if e is not None]
    store.rev = int(raw.get("rev") or 0)
    store.synced_ms = int(raw.get("synced_ms") or 0)
    store.claimed_by = str(raw.get("claimed_by") or "")
    return store


def write(store: Store) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.path.with_suffix(".tmp")
    data = {"version": 2, "ships": [asdict(e) for e in store.entries]}
    if store.account:
        data.update(account=store.account, rev=store.rev, synced_ms=store.synced_ms)
    if store.claimed_by:
        data["claimed_by"] = store.claimed_by
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(store.path)


# -- the list the UI works on ------------------------------------------------------
# The active owner: None (signed out / sync off) or the signed-in account's id. app.sync sets it.
_active: str | None = None
_listeners: list = []


def set_active(account: str | None) -> None:
    global _active
    _active = account or None


def active() -> str | None:
    return _active


def on_change(callback) -> None:
    """`callback()` after every local save (app.sync debounces a sync)."""
    _listeners.append(callback)


def load(path: Path | None = None) -> list[Entry]:
    """The ships to show (no tombstones), of the active owner."""
    if path is not None:          # an explicit file (tests, import)
        store = Store(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            store.entries = [e for e in (_entry(i) for i in raw.get("ships", [])) if e is not None]
        except (OSError, ValueError, AttributeError):
            pass
        return store.live()
    return read(_active).live()


def save(entries: list[Entry], path: Path | None = None) -> None:
    """Saves the UI's list: changed entries get a new `updated_at`, entries no
    longer in it become tombstones."""
    store = read(_active) if path is None else Store(path)
    if path is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            store.entries = [e for e in (_entry(i) for i in raw.get("ships", [])) if e is not None]
        except (OSError, ValueError, AttributeError):
            pass
    old = {e.id: e for e in store.entries}
    stamp = now_ms()
    out: list[Entry] = []
    for e in entries:
        before = old.pop(e.id, None)
        if before is None or before.deleted or before.content() != e.content():
            e = replace(e, updated_at=max(stamp, (before.updated_at + 1) if before else 0), deleted=False)
        else:
            e = replace(e, updated_at=before.updated_at)
        out.append(e)
    for gone in old.values():          # removed in the UI: a tombstone until the service has it
        if not gone.deleted:
            gone = replace(gone, deleted=True, updated_at=max(stamp, gone.updated_at + 1))
        if store.account:              # the local (never synced) list needs no tombstones
            out.append(gone)
    store.entries = out
    write(store)
    for callback in list(_listeners):
        try:
            callback()
        except Exception:
            pass
