"""Loadouts: the player's own part setups for the ships in My Ships, several
per ship. A loadout belongs to one hangar entry (app.hangar) and holds only
what differs from the ship's stock parts (app.loadoutcalc's "parts").

Stored like My Ships, one file per owner (app.sync keeps them in step with
sc-toolbox.com, right after the hangar):
- loadouts.json: the local loadouts, used while signed out. The first
  account that syncs on this PC takes them over with the hangar.
- loadouts-<account id>.json: an account's copy, with its sync state (`rev`,
  `synced_ms`, as in app.hangar).

Every edit stamps the loadout's `updated_at` (Unix ms): per loadout, the
newer edit wins online, its shopping ticks and saved shopping list included.
A removal is kept as a tombstone until the service has it. Removing a ship
removes its loadouts (cascade), here and online.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from app import config, hangar
from app.hangar import now_ms

LOADOUTS_FILE = config.DATA_DIR / "loadouts.json"
MAX_PER_SHIP = 20               # the service's limits
MAX_TOTAL = 500
# The fields an edit changes (what the service keeps per loadout).
CONTENT = ("hangar_id", "ship", "name", "parts", "ticks", "basket")


@dataclass
class Loadout:
    hangar_id: str              # the hangar entry (app.hangar.Entry.id) it's for
    ship: str                   # catalogue key, the entry's
    name: str
    parts: dict = field(default_factory=dict)   # slot path → {item, source, qualities?, shop?}
    ticks: list = field(default_factory=list)   # shopping list keys ticked off
    basket: dict | None = None  # the saved shopping list (see app.loadoutmodel), None = not saved
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    updated_at: int = 0
    deleted: bool = False
    share: dict | None = None   # {token, url, sharedAt} from online; not an edit

    def content(self) -> tuple:
        return tuple(json.dumps(getattr(self, f), sort_keys=True) for f in CONTENT)


@dataclass
class Store:
    path: Path
    loadouts: list[Loadout] = field(default_factory=list)   # tombstones included
    account: str = ""
    rev: int = 0
    synced_ms: int = 0
    claimed_by: str = ""

    def live(self) -> list[Loadout]:
        return [lo for lo in self.loadouts if not lo.deleted]

    def pending(self) -> list[Loadout]:
        """Edits the service hasn't seen: everything changed since the last sync started."""
        return [lo for lo in self.loadouts if lo.updated_at > self.synced_ms or (not self.rev and not self.synced_ms)]


def _loadout(item: dict) -> Loadout | None:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    parts = item.get("parts")
    basket = item.get("basket")
    share = item.get("share")
    return Loadout(hangar_id=str(item.get("hangar_id") or ""), ship=str(item.get("ship") or ""),
                   name=str(item.get("name") or ""), parts=parts if isinstance(parts, dict) else {},
                   ticks=[str(t) for t in item.get("ticks") or [] if t],
                   basket=basket if isinstance(basket, dict) and basket else None, id=str(item["id"]),
                   updated_at=int(item.get("updated_at") or 0), deleted=bool(item.get("deleted")),
                   share=share if isinstance(share, dict) and share.get("url") else None)


def path_for(account: str | None) -> Path:
    return config.DATA_DIR / f"loadouts-{account}.json" if account else LOADOUTS_FILE


def read(account: str | None = None) -> Store:
    path = path_for(account)
    store = Store(path, account=account or "")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return store
    if not isinstance(raw, dict):
        return store
    store.loadouts = [lo for lo in (_loadout(i) for i in raw.get("loadouts", [])) if lo is not None]
    store.rev = int(raw.get("rev") or 0)
    store.synced_ms = int(raw.get("synced_ms") or 0)
    store.claimed_by = str(raw.get("claimed_by") or "")
    return store


def write(store: Store) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.path.with_suffix(".tmp")
    data = {"version": 1, "loadouts": [asdict(lo) for lo in store.loadouts]}
    if store.account:
        data.update(account=store.account, rev=store.rev, synced_ms=store.synced_ms)
    if store.claimed_by:
        data["claimed_by"] = store.claimed_by
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(store.path)


# -- what the UI works on (the active owner is My Ships' one: hangar.active()) -------------
_listeners: list = []


def on_change(callback) -> None:
    """`callback()` after every local save (app.sync debounces a sync)."""
    _listeners.append(callback)


def _changed() -> None:
    for callback in list(_listeners):
        try:
            callback()
        except Exception:
            pass


def for_ship(hangar_id: str) -> list[Loadout]:
    """A hangar entry's loadouts, oldest first (the order the pills show)."""
    return [lo for lo in read(hangar.active()).live() if lo.hangar_id == hangar_id]


def get(loadout_id: str) -> Loadout | None:
    return next((lo for lo in read(hangar.active()).live() if lo.id == loadout_id), None)


class LimitReached(Exception):
    pass


def check_room(hangar_id: str) -> None:
    """Raises LimitReached when a new loadout for this ship wouldn't fit the service's limits."""
    live = read(hangar.active()).live()
    if len(live) >= MAX_TOTAL:
        raise LimitReached(f"You can keep at most {MAX_TOTAL} loadouts.")
    if sum(1 for lo in live if lo.hangar_id == hangar_id) >= MAX_PER_SHIP:
        raise LimitReached(f"A ship can have at most {MAX_PER_SHIP} loadouts.")


def save(loadout: Loadout) -> Loadout:
    """Adds or updates one loadout: a changed one gets a new `updated_at`. Returns it as saved."""
    store = read(hangar.active())
    i = next((n for n, lo in enumerate(store.loadouts) if lo.id == loadout.id), None)
    before = store.loadouts[i] if i is not None else None
    if before is not None and not before.deleted and before.content() == loadout.content():
        return before
    stamp = max(now_ms(), (before.updated_at + 1) if before else 0)
    saved = replace(loadout, updated_at=stamp, deleted=False,
                    share=before.share if before is not None else loadout.share)
    if i is None:
        store.loadouts.append(saved)
    else:
        store.loadouts[i] = saved
    write(store)
    _changed()
    return saved


def _tombstone(store: Store, ids: set[str]) -> bool:
    stamp = now_ms()
    out, changed = [], False
    for lo in store.loadouts:
        if lo.id in ids and not lo.deleted:
            changed = True
            if not store.account:          # never synced: nothing to tell the service
                continue
            lo = replace(lo, deleted=True, share=None, updated_at=max(stamp, lo.updated_at + 1))
        out.append(lo)
    store.loadouts = out
    return changed


def remove(loadout_id: str) -> None:
    store = read(hangar.active())
    if _tombstone(store, {loadout_id}):
        write(store)
        _changed()


def cascade(hangar_ids: set[str], account: str | None = None) -> None:
    """Removes the loadouts of ships that left My Ships (the service does the same on its side)."""
    store = read(account if account is not None else hangar.active())
    if _tombstone(store, {lo.id for lo in store.loadouts if lo.hangar_id in hangar_ids}):
        write(store)
        _changed()


def set_share(loadout_id: str, share: dict | None) -> None:
    """Records the share link the service made (or that sharing stopped): not an edit."""
    store = read(hangar.active())
    for i, lo in enumerate(store.loadouts):
        if lo.id == loadout_id:
            store.loadouts[i] = replace(lo, share=share)
            write(store)
            _changed()
            return
