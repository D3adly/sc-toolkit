"""Sync online: keeps sc-toolbox.com up to date with what the launcher reads,
and the launcher up to date with what's online. Online is the store, the
launcher the provider: nothing online is ever removed because the launcher
has less (a reinstall, deleted logs).

- Stats and blueprint receipts (launcher → online): one summary per game
  session (app.stats_digest), keyed by (channel, log id). The log id comes
  from the log itself, the same for Game.log and its later backup copy, and
  the service replaces a session whose hash changed and skips an equal one,
  so sending again never duplicates. At start: only sessions the service is
  missing or has older; while playing: the current session, soon after a
  blueprint and at most every few minutes otherwise, and when the game ends.
  LIVE and HOTFIX only (the persistent universe; app.channel).
- Blueprints owned (online → launcher): the online collection (receipts plus
  blueprints marked owned on the website), cached per account for the
  Mission Database and the overlay (app.owned).
- My Ships (both ways): app.hangar keeps per-entry edit times and
  tombstones; the service merges (newest edit wins per entry) and returns
  everything that changed since the revision the launcher last saw. The
  first sync of an account pairs local ships with online ones of the same
  model one-to-one, so ships both sides already had aren't doubled.

Everything runs on one worker thread, one job at a time; the UI hears about
it through signals. Offline is fine: the next run sends whatever is missing.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from app import channel as channel_mod, config, datahub, gamelog, hangar, portal, settings, stats, stats_digest
from app.channel import PERSISTENT_CHANNELS

SYNC_CHANNELS = [c for c in PERSISTENT_CHANNELS if c]       # LIVE, HOTFIX
UPLOAD_BATCH = 50                     # sessions per PUT (the service's limit)
BLUEPRINT_DELAY_MS = 10_000           # a new blueprint goes up this soon
LIVE_INTERVAL_MS = 5 * 60_000         # other live changes at most this often
HANGAR_DELAY_MS = 3_000               # after a local My Ships edit
HANGAR_POLL_MS = 5 * 60_000           # website edits, while My Ships is open
RETRY_MS = 2 * 60_000                 # after a failure


def _log(message: str) -> None:
    try:
        path = config.CACHE_DIR / "sync.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def _iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def _ms(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


def owned_file(account: str):
    return config.DATA_DIR / f"blueprints-owned-{account}.json"


# -- whose game logs these are ------------------------------------------------------------
# This PC's game logs are one player's: the first account that syncs them owns them, and their
# stats and blueprints never go to another account unless the player hands them over
# (Settings → Online account), e.g. after making a new account.
LOGS_OWNER_FILE = config.DATA_DIR / "sync-logs-owner.json"


def logs_owner() -> dict:
    try:
        data = json.loads(LOGS_OWNER_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_logs_owner(account: str, name: str) -> None:
    LOGS_OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOGS_OWNER_FILE.write_text(json.dumps({"account": account, "name": name}), encoding="utf-8")


def logs_belong_to(account: str, name: str) -> bool:
    """True if this account may receive this PC's game logs (claiming them if nobody has)."""
    owner = logs_owner()
    if not owner.get("account"):
        set_logs_owner(account, name)
        return True
    return owner["account"] == account


# -- hangar: the pure parts (tested without a service) ---------------------------------

def entry_to_input(e: hangar.Entry) -> dict:
    return {"id": e.id, "updatedAt": _iso_ms(e.updated_at or 1), "ship": e.ship, "shipName": e.ship_name,
            "acquired": e.acquired, "name": e.name, "insurance": e.insurance, "notes": e.notes,
            "added": e.added or None, "deleted": e.deleted}


def entry_from_remote(r: dict) -> hangar.Entry:
    return hangar.Entry(ship=r.get("ship") or "", ship_name=r.get("shipName") or "",
                        acquired=r.get("acquired") or hangar.PLEDGE, name=r.get("name") or "",
                        insurance=r.get("insurance") or "", notes=r.get("notes") or "",
                        added=r.get("added") or "", id=r["id"], updated_at=_ms(r.get("updatedAt")),
                        deleted=bool(r.get("deleted")))


def pair_first_link(local: list[hangar.Entry], remote: list[dict]) -> list[hangar.Entry]:
    """The first sync of an account that may already have ships online: each
    local ship takes over one unpaired online ship of the same model (same
    pledge / in-game first), so a ship both sides have becomes one entry.
    The merged entry keeps the newer edit, and a filled name, insurance or
    notes over an empty one. Returns the local list to send."""
    remote_live = [entry_from_remote(r) for r in remote if not r.get("deleted")]
    free = list(remote_live)
    out = []
    remote_ids = {r.id for r in remote_live}
    for strict in (True, False):
        for e in [x for x in local if not x.deleted and x.id not in remote_ids]:
            match = next((r for r in free if r.ship == e.ship and (not strict or r.acquired == e.acquired)), None)
            if match is None:
                continue
            free.remove(match)
            newer, older = (e, match) if e.updated_at > match.updated_at else (match, e)
            merged = hangar.Entry(**{**newer.__dict__})
            for f in ("name", "insurance", "notes"):
                if not getattr(merged, f) and getattr(older, f):
                    setattr(merged, f, getattr(older, f))
            merged.id = match.id
            merged.deleted = False
            # Unchanged from what's online: nothing to send; else a new edit that wins.
            merged.updated_at = (match.updated_at if merged.content() == match.content()
                                 else max(e.updated_at, match.updated_at) + 1)
            out.append(merged)
            e.id = match.id            # paired: skipped by the next pass and below
            remote_ids.add(match.id)
    paired_ids = {x.id for x in out}
    for e in local:
        if e.id not in paired_ids and not e.deleted:
            out.append(e)              # online doesn't have it (or it's the same entry): it goes up
    return out


def apply_remote(store: hangar.Store, changes: list[dict]) -> None:
    """The service's resolved changes into the local copy: a change replaces
    the local entry unless the local one was edited later (that edit goes
    up next time); deletions remove it."""
    by_id = {e.id: i for i, e in enumerate(store.entries)}
    for r in changes:
        incoming = entry_from_remote(r)
        i = by_id.get(incoming.id)
        if i is not None and store.entries[i].updated_at > incoming.updated_at:
            continue
        if incoming.deleted:
            if i is not None:
                store.entries[i] = None      # type: ignore[call-overload]
            continue
        if i is None:
            by_id[incoming.id] = len(store.entries)
            store.entries.append(incoming)
        else:
            store.entries[i] = incoming
    store.entries = [e for e in store.entries if e is not None]


# -- the controller -------------------------------------------------------------------

class SyncController(QObject):
    """One per launcher. `status(text, tone)` for the switch's line;
    `hangar_updated` when My Ships changed from online; `owned_updated` when
    the online blueprint collection was fetched; `needs_sign_in(message)` when
    the sign-in lacks the sync permissions."""

    status = Signal(str, str)
    hangar_updated = Signal()
    owned_updated = Signal()
    needs_sign_in = Signal(str)
    _done = Signal(str, object)          # worker → UI thread: (job, result or exception)

    def __init__(self, reader: gamelog.LiveReader, parent=None):
        super().__init__(parent)
        from app.account_controller import controller as account_controller

        self.account = account_controller()
        self.reader = reader
        self._jobs: queue.Queue = queue.Queue()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._last_live_hash = ""
        self.last_synced: datetime | None = None
        self._done.connect(self._on_done)
        threading.Thread(target=self._worker, daemon=True).start()

        self._blueprint_timer = QTimer(self, singleShot=True, interval=BLUEPRINT_DELAY_MS,
                                       timeout=lambda: self.request("stats_live"))
        self._live_timer = QTimer(self, singleShot=True, interval=LIVE_INTERVAL_MS,
                                  timeout=lambda: self.request("stats_live"))
        self._hangar_timer = QTimer(self, singleShot=True, interval=HANGAR_DELAY_MS,
                                    timeout=lambda: self.request("hangar"))
        self._hangar_poll = QTimer(self, interval=HANGAR_POLL_MS, timeout=lambda: self.request("hangar"))
        self._retry = QTimer(self, singleShot=True, interval=RETRY_MS, timeout=lambda: self.request("startup"))
        reader.add_listener(self._on_event)
        reader.session_ended.connect(lambda _sid: self.request("stats_live"))
        self.account.changed.connect(self._on_account)
        hangar.on_change(self._on_hangar_edit)
        self._on_account(self.account.state)

    # -- state ------------------------------------------------------------------------
    @property
    def account_id(self) -> str:
        st = self.account.state
        return st.profile.account_id if st.status == "signed_in" and st.profile else ""

    @property
    def enabled(self) -> bool:
        return bool(settings.current().sync_enabled and self.account_id and self.account.session is not None)

    def _on_account(self, state) -> None:
        account = self.account_id
        # My Ships shows the signed-in account's copy once it has one (or sync is on); else the local list.
        use = account if account and (hangar.path_for(account).is_file() or settings.current().sync_enabled) else None
        if use != hangar.active():
            hangar.set_active(use)
            self.hangar_updated.emit()
        if self.enabled:
            self.request("startup")
        else:
            self._report()

    def set_enabled(self, on: bool) -> None:
        """The Sync online switch (the window keeps the live log in step)."""
        from dataclasses import replace

        if on != settings.current().sync_enabled:
            settings.apply(replace(settings.current(), sync_enabled=on))
        self._on_account(self.account.state)
        if on:
            self.request("startup")

    def _report(self, text: str = "", tone: str = "") -> None:
        if not text:
            if not self.account_id:
                text, tone = "Sign in to sync", "muted"
            elif not settings.current().sync_enabled:
                text, tone = "Off", "muted"
            elif logs_owner().get("account") not in (None, "", self.account_id):
                text, tone = (f"My Ships synced · your game stats go to {logs_owner().get('name') or 'another account'}",
                              "info")
            elif self.last_synced:
                text, tone = f"Synced {self.last_synced.astimezone():%H:%M}", "success"
            else:
                text, tone = "Syncing…", "info"
        self.status.emit(text, tone)

    # -- triggers -----------------------------------------------------------------------
    def request(self, job: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            if job in self._queued:
                return
            self._queued.add(job)
        self._jobs.put(job)

    def _on_event(self, event: gamelog.Event) -> None:
        if not self.enabled or event.channel.upper() not in SYNC_CHANNELS:
            return
        if event.kind == "blueprint":
            self._blueprint_timer.start()
        elif not self._live_timer.isActive():
            self._live_timer.start()

    def _on_hangar_edit(self) -> None:
        if self.enabled and hangar.active():
            self._hangar_timer.start()

    def hangar_opened(self) -> None:
        """My Ships is showing: sync now, and look for website edits now and then."""
        self.request("hangar")
        if self.enabled:
            self._hangar_poll.start()

    def hangar_closed(self) -> None:
        self._hangar_poll.stop()

    # -- the worker ---------------------------------------------------------------------
    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            with self._lock:
                self._queued.discard(job)
            try:
                result = getattr(self, f"_job_{job}")()
            except Exception as exc:          # reported on the UI thread
                if not isinstance(exc, portal.PortalError):
                    _log(f"{job} failed:\n{traceback.format_exc()}")
                result = exc
            self._done.emit(job, result)

    def _on_done(self, job: str, result) -> None:
        if isinstance(result, portal.InsufficientScope):
            self._report("Sign in again to turn on sync", "warning")
            self.needs_sign_in.emit(str(result))
            return
        if isinstance(result, portal.SignedOut):
            self._report("Sign in again: your sign-in expired", "warning")
            return
        if isinstance(result, portal.Unreachable):
            self._report("Offline: will retry", "warning")
            self._retry.start()
            return
        if isinstance(result, Exception):
            self._report("Sync failed: will retry", "danger")
            _log(f"{job}: {result}")
            self._retry.start()
            return
        self.last_synced = datetime.now(timezone.utc)
        result = result if isinstance(result, dict) else {}
        if result.get("hangar"):
            self.hangar_updated.emit()
        if result.get("owned"):
            self.owned_updated.emit()
            from app import ipc

            ipc.send(ipc.OVERLAY, "owned-updated")
        self._report()

    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        session = self.account.session
        if session is None:
            raise portal.SignedOut("Not signed in.")
        return session.api(method, path, body)

    # -- jobs (worker thread) ---------------------------------------------------------------
    def _job_startup(self) -> dict:
        changed = self._job_hangar()["hangar"]
        self._upload_all_sessions()
        self._fetch_owned()
        return {"hangar": changed, "owned": True}

    def _job_hangar(self) -> dict:
        account = self.account_id
        if not account:
            return {}
        store = hangar.read(account)
        first = not store.rev and not store.synced_ms
        if first and not hangar.path_for(account).is_file():
            # The first account on this PC takes over the local list (once).
            local = hangar.read(None)
            if not local.claimed_by and local.live():
                store.entries = [hangar.Entry(**{**e.__dict__}) for e in local.live()]
                local.claimed_by = account
                hangar.write(local)
                _log(f"hangar: {len(store.entries)} local ships go to account {account}")
        if first:
            remote = self._api("GET", "/hangar").get("entries", [])
            store.entries = pair_first_link(store.entries, remote)
            send = store.entries
        else:
            send = store.pending()
        started = hangar.now_ms()
        reply = self._api("POST", "/hangar/sync",
                          {"sinceRev": store.rev, "changes": [entry_to_input(e) for e in send]})
        # Edits made while the request ran are in the file now: merge into that.
        latest = hangar.read(account)
        if first:
            latest.entries = store.entries + [e for e in latest.entries if e.updated_at >= started
                                              and e.id not in {s.id for s in store.entries}]
        apply_remote(latest, reply.get("changes", []))
        # Confirmed deletions leave; other tombstones wait for the next sync.
        latest.rev = int(reply.get("rev") or 0)
        latest.synced_ms = started
        hangar.write(latest)
        _log(f"hangar: sent {len(send)}, got {len(reply.get('changes', []))}, rev {latest.rev}")
        return {"hangar": bool(reply.get("changes")) or first}

    def _logs_allowed(self) -> bool:
        st = self.account.state
        return logs_belong_to(self.account_id, st.profile.display_name if st.profile else "")

    def _upload_all_sessions(self) -> None:
        root = settings.current().game_root
        if root is None or not self._logs_allowed():
            return
        stored = {(s.get("channel", "").upper(), s.get("logId")): s.get("hash")
                  for s in self._api("GET", "/stats/sessions").get("sessions", [])}
        sessions = gamelog.all_sessions(root, SYNC_CHANNELS)
        if not sessions:
            return
        events = gamelog.read_history(root, stats.KINDS, gamelog.OUTPUT_EVENTS, channels=SYNC_CHANNELS)
        summaries = stats_digest.digest(events, sessions, self._contracts())
        todo = [s for s in summaries if stored.get((s["channel"].upper(), s["logId"])) != s["hash"]]
        for i in range(0, len(todo), UPLOAD_BATCH):
            self._api("PUT", "/stats/sessions", {"sessions": todo[i:i + UPLOAD_BATCH]})
        _log(f"stats: {len(summaries)} sessions, {len(todo)} sent")

    def _job_stats_live(self):
        session = self.reader.session
        if session is None or session.channel.upper() not in SYNC_CHANNELS or not self._logs_allowed():
            return {}
        events = self.reader.session_events(stats.KINDS)
        summaries = stats_digest.digest(events, [session], self._contracts())
        if not summaries or summaries[0]["hash"] == self._last_live_hash:
            return {}
        self._api("PUT", "/stats/sessions", {"sessions": summaries})
        self._last_live_hash = summaries[0]["hash"]
        got_blueprints = bool(summaries[0]["blueprints"])
        if got_blueprints:
            self._fetch_owned()
        _log(f"stats live: {session.id} sent")
        return {"owned": got_blueprints}

    def _job_owned(self):
        self._fetch_owned()
        return {"owned": True}

    def _fetch_owned(self) -> None:
        account = self.account_id
        if not account:
            return
        data = self._api("GET", "/blueprints")
        collection = data.get("collection") or {}
        out = {"names": [i.get("name") for i in data.get("items", []) if i.get("name")],
               "since": collection.get("startedAt"), "fetched": time.time()}
        path = owned_file(account)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out), encoding="utf-8")
        tmp.replace(path)

    def _contracts(self):
        root = settings.current().game_root
        ch = channel_mod.pick_default_channel(root)
        if not ch:
            return None
        try:
            return datahub.read_game("contracts", channel_mod.resolve_channel_paths(root, ch).channel_root)
        except Exception:
            return None
