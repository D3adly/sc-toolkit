"""Every data source the launcher reads from the game files or the web, in
one place, with one caching rule each:

- **Game data** (missions, mining, salvage ships, ship stats): read from
  Data.p4k once per game patch per channel, all in one pass that opens
  Game2.dcb once (GameFiles), and cached. Only this module reads the game
  files: at SC-Toolkit start and game start when the build changed, and
  when the RSI Launcher's log says an update completed (app.patchwatch).
  While an update runs, the channel is frozen: nothing reads its files, and
  everyone gets the previous version's cache until the new one is built.
- **Web data** (ship list, salvage spreadsheet, UEX prices): downloaded at
  startup when older than its maximum age, and never more often than that,
  even on request.

Views and the overlay only read the caches (read_game / Hub.game). Pictures
(ships, sticks, maps) are fetched on demand where they're shown and kept for
good; the update check (app.updater) keeps its own daily schedule.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from app import bindings, config, contracts, mining, p4k, salvage, shipdata, ships
from app.datacore import DataCore

GAME2_ENTRY = "Data\\Game2.dcb"
DAY = 24 * 3600


def channel_name(channel_root: Path) -> str:
    """LIVE, PTU, EPTU, TECH-PREVIEW…: the channel folder's name."""
    return channel_root.name.upper()


def patch_key(channel_root: Path) -> str:
    """Identifies a game build: Data.p4k's size and modification time."""
    return bindings._cache_key(channel_root / "Data.p4k")


class GameFiles:
    """One channel's game files, opened lazily and shared by every builder
    in a refresh pass, so Game2.dcb is extracted and parsed only once."""

    def __init__(self, channel_root: Path):
        self.channel_root = channel_root
        self.p4k_path = channel_root / "Data.p4k"
        if not self.p4k_path.is_file():
            raise FileNotFoundError(f"Data.p4k not found in {channel_root}")

    @cached_property
    def dc(self) -> DataCore:
        raw = p4k.extract(self.p4k_path, [GAME2_ENTRY]).get(GAME2_ENTRY)
        if raw is None:
            raise RuntimeError("Game2.dcb not found in Data.p4k")
        return DataCore(raw)

    @cached_property
    def loc(self) -> dict[str, str]:
        """The game's packed global.ini (vanilla English names)."""
        raw = bindings._load_from_p4k_cached(self.channel_root, bindings.GLOBAL_INI_ENTRY, "global.ini")
        return bindings._parse_ini(raw) if raw else {}

    @cached_property
    def installed_loc(self) -> dict[str, str]:
        """A localization installed next to the game (StarStrings…), or {}."""
        try:
            return bindings._parse_ini(contracts.installed_ini(self.channel_root).read_bytes())
        except OSError:
            return {}


@dataclass
class GameSource:
    name: str
    label: str                                    # for progress messages
    folder: Path
    prefix: str
    format: int
    build: Callable[[GameFiles, Callable[[str], None]], dict]
    wrap: Callable[[dict], object] = lambda data: data
    extra_key: Callable[[Path], str] = lambda _root: ""

    def file(self, channel_root: Path) -> Path:
        return self.folder / (f"{self.prefix}-{channel_name(channel_root)}-{patch_key(channel_root)}"
                              f"{self.extra_key(channel_root)}.json")

    def _load(self, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return self.wrap(data) if data.get("format") == self.format else None

    def read(self, channel_root: Path):
        """The cached data for this game build, or None."""
        return self._load(self.file(channel_root))

    def latest(self, channel_root: Path) -> tuple[object, bool] | None:
        """(data, current) for this channel: this build's cache, else the
        newest one from an earlier build (current=False); None if neither."""
        data = self.read(channel_root)
        if data is not None:
            return data, True
        older = sorted(self.folder.glob(f"{self.prefix}-{channel_name(channel_root)}-*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for path in older:
            data = self._load(path)
            if data is not None:
                return data, False
        return None

    def fresh(self, channel_root: Path) -> bool:
        try:
            with self.file(channel_root).open("rb") as f:
                head = f.read(64)
        except OSError:
            return False
        return f'"format": {self.format},'.encode() in head or f'"format":{self.format},'.encode() in head

    def write(self, channel_root: Path, data: dict) -> None:
        data["format"] = self.format
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.file(channel_root)
        channel = channel_name(channel_root)
        for stale in self.folder.glob(f"{self.prefix}-*.json"):
            # This channel's older builds, and files from before caches were
            # per channel ("<prefix>-<size>-…"); other channels' stay.
            tag = stale.stem[len(self.prefix) + 1:].split("-", 1)[0]
            if stale != target and (tag == channel or tag.isdigit()):
                stale.unlink(missing_ok=True)
        tmp = target.with_suffix(".tmp")
        # "format" first, so fresh() can check it without parsing the file.
        tmp.write_text(json.dumps({"format": self.format, **data}), encoding="utf-8")
        tmp.replace(target)


@dataclass
class WebSource:
    name: str
    label: str
    max_age: float                                # seconds between downloads, at most
    fetch: Callable[[Callable[[str], None]], None]
    fetched: Callable[[], float]                  # time of the last download, 0 if never

    def age(self) -> float:
        when = self.fetched()
        return time.time() - when if when else float("inf")

    def fresh(self) -> bool:
        return self.age() < self.max_age


GAME_SOURCES: dict[str, GameSource] = {
    "contracts": GameSource("contracts", "missions", contracts.CACHE, "contracts", contracts.FORMAT,
                            contracts.build, contracts.Contracts, contracts.localization_key),
    "mining": GameSource("mining", "mining", mining.CACHE, "mining", mining.FORMAT, mining.build),
    "salvage": GameSource("salvage", "salvage ships", salvage.CACHE, "game", salvage.GAME_FORMAT,
                          salvage.build_game_data),
    "shipdata": GameSource("shipdata", "ship stats", shipdata.CACHE, "shipdata", shipdata.FORMAT,
                           lambda game, progress: shipdata.build(game, progress, ships.load().class_ids()),
                           shipdata.ShipData),
}

WEB_SOURCES: dict[str, WebSource] = {
    "ships": WebSource("ships", "ship list", 7 * DAY, lambda progress: ships.refresh(progress),
                       lambda: ships.load().fetched),
    "salvage_sheet": WebSource("salvage_sheet", "salvage spreadsheet", DAY, lambda _p: salvage.refresh_sheet(),
                               salvage.sheet_fetched),
    "uex": WebSource("uex", "UEX prices", DAY, lambda _p: salvage.refresh_uex(), salvage.uex_fetched),
}


def label(name: str) -> str:
    source = GAME_SOURCES.get(name) or WEB_SOURCES.get(name)
    return source.label if source else name


def read_game(name: str, channel_root: Path | None):
    """Cached game data (no game files are read): this build's, else the
    previous build's while the new one is prepared; None if there's none.
    Safe from any thread or process (the overlay)."""
    if channel_root is None or not (channel_root / "Data.p4k").is_file():
        return None
    found = GAME_SOURCES[name].latest(channel_root)
    return found[0] if found else None


def stale_game(channel_root: Path, names=None) -> list[str]:
    return [n for n in (names or GAME_SOURCES) if not GAME_SOURCES[n].fresh(channel_root)]


def build_game(channel_root: Path, names: list[str], progress=lambda _msg: None,
               done=lambda _name: None) -> dict[str, str]:
    """Builds the given game sources in one pass over the game files.
    Returns {name: error} for the ones that failed."""
    game = GameFiles(channel_root)
    errors = {}
    for i, name in enumerate(names, 1):
        source = GAME_SOURCES[name]
        prefix = f"Reading the game files after a patch ({i}/{len(names)}: {source.label})"
        progress(prefix + "…")
        try:
            source.write(channel_root, source.build(game, lambda msg, p=prefix: progress(f"{p}: {msg}")))
            done(name)
        except Exception as exc:          # a patch can change anything in there
            traceback.print_exc()
            errors[name] = str(exc)
    return errors


# -- background runner -----------------------------------------------------------

@dataclass(order=True)
class _Job:
    priority: int
    seq: int
    kind: str = field(compare=False)              # "startup" | "game" | "web"
    channel_root: Path | None = field(compare=False, default=None)
    names: tuple = field(compare=False, default=())
    force: bool = field(compare=False, default=False)


class Hub(QObject):
    """The launcher's data runner: one worker thread, so the game files are
    never read twice at once. Signals arrive on the UI thread."""

    updated = Signal(str)                 # a source has new data
    failed = Signal(str, str)             # source, message
    status = Signal(str)                  # progress text; "" when idle
    refreshed = Signal(str)               # a manual refresh finished: summary

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = 0
        self._busy: set[tuple[str, str]] = set()      # (source, channel) queued or running
        self._memo: dict[tuple[str, str], tuple[object, bool]] = {}
        self._lock = threading.Lock()
        self.updating: dict[str, str] = {}             # channel → version being installed (frozen)
        threading.Thread(target=self._loop, daemon=True, name="datahub").start()

    # -- reading ------------------------------------------------------------
    def game(self, name: str, channel_root: Path | None):
        """Cached game data for this channel: this build's, else the previous
        build's (see is_current); None when there's none at all (then call
        ensure_game and wait for `updated`)."""
        found = self._lookup(name, channel_root)
        return found[0] if found else None

    def is_current(self, name: str, channel_root: Path | None) -> bool:
        found = self._lookup(name, channel_root)
        return bool(found and found[1])

    def _lookup(self, name: str, channel_root: Path | None):
        if channel_root is None or not (channel_root / "Data.p4k").is_file():
            return None
        key = (name, str(GAME_SOURCES[name].file(channel_root)))
        if key not in self._memo:
            found = GAME_SOURCES[name].latest(channel_root)
            if found is None:
                return None
            if not found[1]:
                return found            # an earlier build's: don't remember it under this key
            self._memo = {k: v for k, v in self._memo.items() if k[0] != name}   # one build per source
            self._memo[key] = found
        return self._memo[key]

    def set_updating(self, channel: str, version: str | None) -> None:
        """Freezes a channel while the RSI Launcher updates it (version) or
        thaws it (None). Frozen channels' game files are never read."""
        if version:
            self.updating[channel.upper()] = version
        else:
            self.updating.pop(channel.upper(), None)

    def frozen(self, channel_root: Path | None) -> bool:
        return channel_root is not None and channel_name(channel_root) in self.updating

    def pending(self, name: str, channel_root: Path | None = None) -> bool:
        with self._lock:
            return any(n == name and (channel_root is None or c == str(channel_root)) for n, c in self._busy)

    def web_age(self, name: str) -> float:
        return WEB_SOURCES[name].age()

    # -- requests -----------------------------------------------------------
    def startup(self, channel_root: Path | None) -> None:
        """Refreshes whatever is out of date: web data older than its maximum
        age, and game data built for another patch."""
        self._put(_Job(0, 0, "startup", channel_root))

    def refresh_all(self, channel_root: Path | None) -> None:
        """The Settings button, for when something went wrong: reads the game
        files again even if the cache looks current, and downloads web data
        that's due (the daily / weekly limits still apply)."""
        self._put(_Job(1, 0, "manual", channel_root, tuple(GAME_SOURCES)))

    def ensure_game(self, names, channel_root: Path | None) -> None:
        """A view found no data for this build (e.g. a tool opened on PTU):
        reads the game files in one pass for every source that's out of
        date there, not just the asked-for ones. No-op while the channel is
        being updated, or when it's cached or queued."""
        if channel_root is None or self.frozen(channel_root) or not (channel_root / "Data.p4k").is_file():
            return
        if all(self.is_current(n, channel_root) or self.pending(n, channel_root) for n in names):
            return
        todo = [n for n in stale_game(channel_root) if not self.pending(n, channel_root)]
        if todo:
            self._put(_Job(1, 0, "game", channel_root, tuple(todo)))

    def refresh_web(self, name: str) -> bool:
        """Downloads a web source again, unless it's younger than its maximum
        age. Returns False when it was too recent to refresh."""
        if WEB_SOURCES[name].fresh():
            return False
        self._put(_Job(1, 0, "web", None, (name,)))
        return True

    def _put(self, job: _Job) -> None:
        with self._lock:
            self._seq += 1
            job.seq = self._seq
            for n in job.names:
                self._busy.add((n, str(job.channel_root or "")))
        self._jobs.put(job)

    # -- worker -------------------------------------------------------------
    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job.kind == "startup":
                    self._run_startup(job.channel_root)
                elif job.kind == "game":
                    self._run_game(job.channel_root, [n for n in job.names
                                                      if not GAME_SOURCES[n].fresh(job.channel_root)])
                elif job.kind == "web":
                    self._run_web([n for n in job.names if not WEB_SOURCES[n].fresh()])
                elif job.kind == "manual":
                    self._run_manual(job.channel_root)
            except Exception:
                traceback.print_exc()
            finally:
                with self._lock:
                    for n in job.names:
                        self._busy.discard((n, str(job.channel_root or "")))
                self.status.emit("")

    def _run_startup(self, channel_root: Path | None) -> None:
        # Web first: the ship list tells the ship-stats builder which ships to read.
        self._run_web([n for n, s in WEB_SOURCES.items() if not s.fresh()])
        if channel_root is not None and (channel_root / "Data.p4k").is_file():
            self._run_game(channel_root, stale_game(channel_root))

    def _run_manual(self, channel_root: Path | None) -> None:
        due = [n for n, s in WEB_SOURCES.items() if not s.fresh()]
        failures = self._run_web(due)
        if channel_root is None or not (channel_root / "Data.p4k").is_file():
            summary = "No game folder set: only web data was refreshed."
        elif self.frozen(channel_root):
            summary = (f"Star Citizen {channel_name(channel_root)} is being updated: its game files are "
                       "read when the update is done.")
        else:
            failures += self._run_game(channel_root, list(GAME_SOURCES))
            summary = f"Game data for {channel_name(channel_root)} read again."
        fresh = [WEB_SOURCES[n].label for n in WEB_SOURCES if n not in due]
        if fresh:
            summary += f" Up to date, not downloaded again: {', '.join(fresh)}."
        if failures:
            summary = f"Failed: {', '.join(label(n) for n in failures)}. " + summary
        self.refreshed.emit(summary)

    def _run_web(self, names: list[str]) -> list[str]:
        """Downloads; returns the names that failed."""
        failed = []
        for name in names:
            source = WEB_SOURCES[name]
            self.status.emit(f"Updating the {source.label}…")
            try:
                source.fetch(lambda msg: self.status.emit(msg))
                self.updated.emit(name)
            except Exception as exc:
                failed.append(name)
                self.failed.emit(name, str(exc))
        return failed

    def _run_game(self, channel_root: Path, names: list[str]) -> list[str]:
        """Reads the game files in one pass; returns the names that failed."""
        if not names or self.frozen(channel_root):
            return []
        try:
            errors = build_game(channel_root, names, self.status.emit, self.updated.emit)
        except Exception as exc:
            errors = {n: str(exc) for n in names}
        for name, message in errors.items():
            self.failed.emit(name, message)
        return list(errors)


_hub: Hub | None = None


def hub() -> Hub:
    """The launcher's Hub (created on first use, on the UI thread)."""
    global _hub
    if _hub is None:
        _hub = Hub()
    return _hub


class GameDataWaiter(QObject):
    """A view's handle on one game source. `ready` fires with the data at
    once when any is cached (the previous game version's during an update,
    see `current`) and again when this version's has been built; meanwhile
    `progress` messages. Views never read the game files themselves."""

    ready = Signal(object)
    progress = Signal(str)
    failed = Signal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.current = False            # the delivered data is for the installed game version
        self._root: Path | None = None  # waiting for this channel's newer data
        h = hub()
        h.updated.connect(self._on_updated)
        h.failed.connect(self._on_failed)
        h.status.connect(self._on_status)

    def request(self, channel_root: Path | None) -> None:
        if channel_root is None or not (channel_root / "Data.p4k").is_file():
            self.failed.emit("The Star Citizen game folder isn't set or has no Data.p4k (see Settings).")
            return
        h = hub()
        data = h.game(self.name, channel_root)
        self.current = h.is_current(self.name, channel_root)
        self._root = None if self.current else channel_root
        if data is not None:
            self.ready.emit(data)
        else:
            self.progress.emit(f"Reading the {GAME_SOURCES[self.name].label} from the game files "
                               "(once per game version)…")
        if not self.current:
            h.ensure_game([self.name], channel_root)

    def _on_updated(self, name: str) -> None:
        if name == self.name and self._root is not None:
            root, self._root = self._root, None
            data = hub().game(self.name, root)
            self.current = hub().is_current(self.name, root)
            if data is not None:
                self.ready.emit(data)

    def _on_failed(self, name: str, message: str) -> None:
        if name == self.name and self._root is not None and hub().game(self.name, self._root) is None:
            self._root = None
            self.failed.emit(message)

    def _on_status(self, text: str) -> None:
        if self._root is not None and text and hub().game(self.name, self._root) is None:
            self.progress.emit(text)
