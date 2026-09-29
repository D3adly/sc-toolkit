"""Keybind/profile backup logic — a clean rewrite, not a port of the old
bash wrapper's backup code.

Layout on disk:
    BACKUP_ROOT/<channel>/<YYYYmmddTHHMMSS>/
        Mappings/...              (copy of controls/mappings)
        Profile/actionmaps.xml
        Profile/attributes.xml
        metadata.json             {"created": iso8601, "channel": str, "content_hash": str}

A backup is only kept if its content hash differs from the most recent
backup for the same channel — this is checked *before* copying anything,
so a no-op session never touches disk.

Named profiles (made in the joystick bindings editor) live beside the
rotating backups but are never deduplicated or rotated away:
    BACKUP_ROOT/<channel>/profiles/<slug>/
        Profile/actionmaps.xml
        Profile/attributes.xml
        metadata.json             {..., "name": str}
They restore exactly like a backup.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

KEEP_LATEST = 3
MAX_AGE_MONTHS = 2

_PROFILE_FILES = ("actionmaps.xml", "attributes.xml")

# Fixed English month abbreviations — strftime's "%b" follows the system
# locale (e.g. renders "Sep" as "rugs." under lt_LT), but backup names
# should read the same regardless of the machine's locale.
_MONTH_ABBR = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    channel: str
    created: datetime
    content_hash: str
    name: str | None = None  # set for named profiles

    @property
    def is_profile(self) -> bool:
        return self.name is not None

    @property
    def display_name(self) -> str:
        if self.name is not None:
            return self.name
        c = self.created
        return f"{c.day} {_MONTH_ABBR[c.month - 1]} {c.year} {c.hour:02d}:{c.minute:02d}"


def _months_ago(n: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    total_month_index = (now.year * 12 + (now.month - 1)) - n
    year, month0 = divmod(total_month_index, 12)
    month = month0 + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def _hash_snapshot(mappings_dir: Path, profile_dir: Path) -> str | None:
    """Hashes every mapping file plus the two profile files, in a stable
    order, so the same on-disk content always produces the same digest
    regardless of filesystem iteration order or mtimes. Returns None if
    there is nothing to back up yet.
    """
    hasher = hashlib.sha256()
    found_anything = False

    if mappings_dir.is_dir():
        for f in sorted(p for p in mappings_dir.rglob("*") if p.is_file()):
            found_anything = True
            hasher.update(str(f.relative_to(mappings_dir)).encode())
            hasher.update(f.read_bytes())

    for name in _PROFILE_FILES:
        f = profile_dir / name
        if f.is_file():
            found_anything = True
            hasher.update(name.encode())
            hasher.update(f.read_bytes())

    return hasher.hexdigest() if found_anything else None


def _channel_root(backup_root: Path, channel: str) -> Path:
    return backup_root / channel


def _read_infos(root: Path) -> list[BackupInfo]:
    if not root.is_dir():
        return []
    out = []
    for entry in root.iterdir():
        meta_file = entry / "metadata.json"
        if not meta_file.is_file():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            out.append(
                BackupInfo(
                    path=entry,
                    channel=meta["channel"],
                    created=datetime.fromisoformat(meta["created"]),
                    content_hash=meta["content_hash"],
                    name=meta.get("name"),
                )
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def list_backups(backup_root: Path, channel: str) -> list[BackupInfo]:
    out = _read_infos(_channel_root(backup_root, channel))
    out.sort(key=lambda b: b.created, reverse=True)
    return out


def _profiles_root(backup_root: Path, channel: str) -> Path:
    return _channel_root(backup_root, channel) / "profiles"


def list_profiles(backup_root: Path, channel: str) -> list[BackupInfo]:
    out = _read_infos(_profiles_root(backup_root, channel))
    out.sort(key=lambda b: b.name.lower())
    return out


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return slug or "profile"


def save_profile(
    backup_root: Path,
    channel: str,
    name: str,
    actionmaps: bytes,
    attributes_src: Path | None,
    existing: BackupInfo | None = None,
) -> BackupInfo:
    """Writes a named profile (new, or overwriting `existing`). The
    attributes.xml (sensitivity/curves etc.) is copied from
    `attributes_src` so restoring the profile doesn't lose those settings.
    """
    root = _profiles_root(backup_root, channel)
    root.mkdir(parents=True, exist_ok=True)

    if existing is not None:
        final_dir = existing.path
    else:
        final_dir = root / _slug(name)
        n = 2
        while final_dir.exists():
            final_dir = root / f"{_slug(name)}-{n}"
            n += 1

    tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp_profile_", dir=root))
    now = datetime.now()
    try:
        (tmp_dir / "Profile").mkdir()
        (tmp_dir / "Profile" / "actionmaps.xml").write_bytes(actionmaps)
        if existing is not None and (existing.path / "Profile" / "attributes.xml").is_file():
            shutil.copy2(existing.path / "Profile" / "attributes.xml", tmp_dir / "Profile")
        elif attributes_src is not None and attributes_src.is_file():
            shutil.copy2(attributes_src, tmp_dir / "Profile" / "attributes.xml")
        metadata = {
            "created": now.isoformat(timespec="seconds"),
            "channel": channel,
            "content_hash": hashlib.sha256(actionmaps).hexdigest(),
            "name": name,
        }
        (tmp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        if final_dir.exists():
            shutil.rmtree(final_dir)
        tmp_dir.rename(final_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return BackupInfo(
        path=final_dir, channel=channel, created=now,
        content_hash=metadata["content_hash"], name=name,
    )


def create_backup(backup_root: Path, channel: str, mappings_dir: Path, profile_dir: Path) -> BackupInfo | None:
    content_hash = _hash_snapshot(mappings_dir, profile_dir)
    if content_hash is None:
        return None

    latest = list_backups(backup_root, channel)
    if latest and latest[0].content_hash == content_hash:
        return None

    channel_root = _channel_root(backup_root, channel)
    channel_root.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    final_dir = channel_root / now.strftime("%Y%m%dT%H%M%S")
    tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp_backup_", dir=channel_root))

    try:
        if mappings_dir.is_dir() and any(mappings_dir.iterdir()):
            shutil.copytree(mappings_dir, tmp_dir / "Mappings")
        for name in _PROFILE_FILES:
            src = profile_dir / name
            if src.is_file():
                (tmp_dir / "Profile").mkdir(exist_ok=True)
                shutil.copy2(src, tmp_dir / "Profile" / name)

        metadata = {
            "created": now.isoformat(timespec="seconds"),
            "channel": channel,
            "content_hash": content_hash,
        }
        (tmp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

        tmp_dir.rename(final_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return BackupInfo(
        path=final_dir,
        channel=channel,
        created=now,
        content_hash=content_hash,
    )


def restore_backup(info: BackupInfo, mappings_dir: Path, profile_dir: Path) -> None:
    """Copies a backup's files back onto disk, merging into whatever is
    already there (matches files by name; doesn't delete anything not
    present in the backup).
    """
    mappings_src = info.path / "Mappings"
    if mappings_src.is_dir():
        mappings_dir.mkdir(parents=True, exist_ok=True)
        for f in mappings_src.rglob("*"):
            if f.is_file():
                dest = mappings_dir / f.relative_to(mappings_src)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)

    profile_src = info.path / "Profile"
    for name in _PROFILE_FILES:
        src = profile_src / name
        if src.is_file():
            profile_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, profile_dir / name)


def cleanup_backups(backup_root: Path) -> int:
    """Keeps the newest KEEP_LATEST backups per channel always; older ones
    are deleted once they're more than MAX_AGE_MONTHS old. Returns the
    number of backup folders removed.
    """
    if not backup_root.is_dir():
        return 0

    cutoff = _months_ago(MAX_AGE_MONTHS)
    removed = 0

    for channel_dir in backup_root.iterdir():
        if not channel_dir.is_dir():
            continue
        backups = list_backups(backup_root, channel_dir.name)
        for stale in backups[KEEP_LATEST:]:
            if stale.created < cutoff:
                shutil.rmtree(stale.path, ignore_errors=True)
                removed += 1

    return removed
