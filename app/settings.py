"""User-editable machine settings, stored as JSON in the per-OS config
directory. Nothing else in the app hardcodes a location on the user's
machine: the game install, launch script, GameGlass and backups all
resolve from here.

`live_dir` points at the game's LIVE folder; the other channels (PTU,
EPTU, TECH-PREVIEW) are its sibling folders, so `game_root` is its parent.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from app import config

SETTINGS_FILE = config.USER_CONFIG_DIR / "settings.json"
DEFAULT_BACKUP_DIR = config.DATA_DIR / "backups"


@dataclass
class Settings:
    live_dir: str = ""        # …/StarCitizen/LIVE
    launch_path: str = ""     # LUG sc-launch.sh (Linux) or RSI Launcher.exe
    gameglass_path: str = ""  # optional
    backup_dir: str = ""      # "" = DEFAULT_BACKUP_DIR

    @property
    def game_root(self) -> Path | None:
        return Path(self.live_dir).parent if self.live_dir else None

    @property
    def backup_root(self) -> Path:
        return Path(self.backup_dir) if self.backup_dir else DEFAULT_BACKUP_DIR

    @property
    def gameglass(self) -> Path | None:
        return Path(self.gameglass_path) if self.gameglass_path else None

    @property
    def launch(self) -> Path | None:
        return Path(self.launch_path) if self.launch_path else None


def validate_live_dir(path: str) -> str | None:
    """None if `path` looks like a Star Citizen channel folder, else why not."""
    if not path:
        return "Not set"
    p = Path(path)
    if not p.is_dir():
        return "Folder not found"
    if not (p / "Data.p4k").is_file():
        return "No Data.p4k here — pick the LIVE folder inside StarCitizen"
    return None


def validate_file(path: str) -> str | None:
    if not path:
        return "Not set"
    return None if Path(path).is_file() else "File not found"


def load() -> Settings:
    try:
        raw = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: str(v) for k, v in raw.items() if k in known})


def save(settings: Settings) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2))
    tmp.replace(SETTINGS_FILE)


_current: Settings | None = None


def current() -> Settings:
    global _current
    if _current is None:
        _current = load()
    return _current


def apply(settings: Settings) -> None:
    global _current
    save(settings)
    _current = settings


def autodetect() -> Settings:
    """Best guesses from standard install locations; empty fields where
    nothing was found.
    """
    found = Settings()
    home = Path.home()
    candidates: list[tuple[Path, Path | None]] = []  # (LIVE dir, launch file)
    if sys.platform.startswith("win"):
        for base in (Path("C:/Program Files"), Path("D:/Program Files"), Path("C:/Games"), Path("D:/Games")):
            rsi = base / "Roberts Space Industries"
            candidates.append((rsi / "StarCitizen" / "LIVE", rsi / "RSI Launcher" / "RSI Launcher.exe"))
    else:
        # LUG Helper's default prefix, then other common Wine managers.
        prefixes = [home / "Games" / "star-citizen", home / "Games" / "star-citizen-prefix",
                    home / ".wine", home / "Games" / "lutris" / "star-citizen"]
        for prefix in prefixes:
            rsi = prefix / "drive_c" / "Program Files" / "Roberts Space Industries"
            candidates.append((rsi / "StarCitizen" / "LIVE", prefix / "sc-launch.sh"))
    for live, launch in candidates:
        if validate_live_dir(str(live)) is None:
            found.live_dir = str(live)
            if launch is not None and launch.is_file():
                found.launch_path = str(launch)
            break
    names = ["GameGlass.exe"] if sys.platform.startswith("win") else ["GameGlass.AppImage", "GameGlass*.AppImage"]
    for folder in (home / "Downloads", home / "Applications", home / "Desktop"):
        for pattern in names:
            match = next(iter(sorted(folder.glob(pattern))), None) if folder.is_dir() else None
            if match:
                found.gameglass_path = str(match)
                break
        if found.gameglass_path:
            break
    return found
