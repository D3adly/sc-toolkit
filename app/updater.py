"""Updates from GitHub Releases: whole-file download, no deltas.

- check(): the newest release newer than this version (stable releases
  only, unless pre-releases are wanted). Checked at most once a day at
  startup (the result is cached), or on request.
- download(): the release file for this platform, next to the running one,
  verified against the SHA-256 digest GitHub publishes for every release
  file. Nothing is installed without a matching digest.
- install(): swaps the new file into place. Linux: the AppImage ($APPIMAGE)
  is replaced in one rename; the running copy keeps working from the old
  file until it exits. Windows: a running .exe can't be overwritten but can
  be renamed, so it becomes <name>.old.exe (deleted at the next start).
- restart(): starts the new version with --after-update <our pid>, which
  waits for this process to exit before it takes over (single instance).

Runs from source, or from a folder we can't write to, can only open the
release page (install_target() is None).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from app import __version__, config

REPO = "D3adly/sc-toolkit"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
CHECK_INTERVAL = 24 * 3600
CACHE_FILE = config.CACHE_DIR / "update_check.json"
TIMEOUT = 15
WINDOWS = sys.platform.startswith("win")
ASSET_NAME = "SC-Toolkit-windows.exe" if WINDOWS else "SC-Toolkit-linux.AppImage"


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str          # "0.1.1" (tag without the "v")
    prerelease: bool
    notes: str            # Markdown (the release's CHANGELOG section)
    page_url: str
    asset_url: str        # "" when this release has no file for our platform
    asset_size: int
    sha256: str           # "" when GitHub has no digest for it


_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)\.?(\d+)?)?$", re.IGNORECASE)


def version_key(version: str) -> tuple | None:
    """Sortable key: 0.1.0-beta.6 < 0.1.0-rc.1 < 0.1.0 < 0.1.1. None if
    it doesn't look like one of our versions."""
    match = _VERSION.match(version.strip())
    if not match:
        return None
    major, minor, patch, stage, n = match.groups()
    pre = (1, "", 0) if stage is None else (0, stage.lower(), int(n or 0))
    return int(major), int(minor), int(patch), pre


def is_newer(version: str, than: str = __version__) -> bool:
    new, current = version_key(version), version_key(than)
    return new is not None and current is not None and new > current


def _http(url: str, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def _parse(raw: dict) -> Release | None:
    version = str(raw.get("tag_name", "")).removeprefix("v")
    if raw.get("draft") or version_key(version) is None:
        return None
    asset = next((a for a in raw.get("assets", []) if a.get("name") == ASSET_NAME), {})
    digest = str(asset.get("digest") or "")
    return Release(
        version=version,
        prerelease=bool(raw.get("prerelease")),
        notes=str(raw.get("body") or ""),
        page_url=str(raw.get("html_url") or RELEASES_PAGE),
        asset_url=str(asset.get("browser_download_url") or ""),
        asset_size=int(asset.get("size") or 0),
        sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else "",
    )


def fetch_latest(prereleases: bool) -> Release | None:
    """The newest release on GitHub (pre-releases only if asked), or None."""
    try:
        with _http(RELEASES_API) as resp:
            raw = json.loads(resp.read())
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Couldn't reach GitHub: {exc}") from exc
    releases = [r for r in (_parse(item) for item in raw) if r and (prereleases or not r.prerelease)]
    return max(releases, key=lambda r: version_key(r.version), default=None)


def check(prereleases: bool, force: bool = False) -> Release | None:
    """A release newer than this version, or None. Uses the cached answer
    when the last check was less than CHECK_INTERVAL ago (unless forced)."""
    if not force:
        try:
            cached = json.loads(CACHE_FILE.read_text())
            if (time.time() - cached["checked"] < CHECK_INTERVAL and cached["prereleases"] == prereleases
                    and cached["current"] == __version__):
                release = Release(**cached["release"]) if cached["release"] else None
                return release if release and is_newer(release.version) else None
        except (OSError, ValueError, KeyError, TypeError):
            pass
    latest = fetch_latest(prereleases)
    newer = latest if latest and is_newer(latest.version) else None
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"checked": time.time(), "prereleases": prereleases,
                                          "current": __version__,
                                          "release": asdict(newer) if newer else None}))
    except OSError:
        pass
    return newer


# -- installing ---------------------------------------------------------------

def install_target() -> Path | None:
    """The file an update replaces: the AppImage on Linux, the .exe on
    Windows. None when running from source or when its folder isn't
    writable (then the release page is the way to update)."""
    if not getattr(sys, "frozen", False):
        return None
    if WINDOWS:
        target = Path(sys.executable)
    else:
        appimage = os.environ.get("APPIMAGE", "")
        if not appimage:
            return None
        target = Path(appimage)
    return target if target.is_file() and os.access(target.parent, os.W_OK) else None


def _partial(target: Path) -> Path:
    return target.with_name(f".{target.name}.download")


def _old(target: Path) -> Path:
    return target.with_name(f"{target.stem}.old{target.suffix}")


def download(release: Release, target: Path, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Downloads the release file next to `target` and verifies it.
    Returns the downloaded file (not yet installed)."""
    if not release.asset_url:
        raise UpdateError(f"Release {release.version} has no {ASSET_NAME}.")
    if not release.sha256:
        raise UpdateError("GitHub has no checksum for this file, so it can't be verified.")
    part = _partial(target)
    hasher = hashlib.sha256()
    done = 0
    try:
        with _http(release.asset_url, accept="application/octet-stream") as resp, part.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or release.asset_size or 0)
            while chunk := resp.read(256 * 1024):
                if cancelled():
                    raise UpdateError("Cancelled.")
                out.write(chunk)
                hasher.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if hasher.hexdigest() != release.sha256.lower():
            raise UpdateError("The download is damaged (its checksum doesn't match). Nothing was changed.")
    except BaseException as exc:
        part.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise UpdateError(f"Download failed: {exc}") from exc
        raise
    return part


def install(downloaded: Path, target: Path) -> None:
    """Puts the downloaded file in the place of `target`."""
    try:
        if WINDOWS:
            old = _old(target)
            old.unlink(missing_ok=True)
            target.rename(old)                 # allowed while it runs
            try:
                downloaded.rename(target)
            except OSError:
                old.rename(target)
                raise
        else:
            downloaded.chmod(0o755)
            os.replace(downloaded, target)     # the running copy keeps its open file
    except OSError as exc:
        downloaded.unlink(missing_ok=True)
        raise UpdateError(f"Couldn't replace {target.name}: {exc}") from exc


def restart(target: Path) -> None:
    """Starts the installed version, detached; the caller then quits."""
    env = dict(os.environ)
    # A fresh PyInstaller instance, not a child of this one (whose unpacked
    # files go away when we exit), with the library path we were started with.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    else:
        env.pop("LD_LIBRARY_PATH", None)
    kwargs: dict = {"env": env, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "cwd": str(target.parent)}
    if WINDOWS:
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([str(target), "--after-update", str(os.getpid())], **kwargs)


def after_update(argv: list[str]) -> None:
    """At startup: if started by restart(), wait for the old process to
    exit, so it has released the single-instance socket and its files."""
    if "--after-update" not in argv:
        return
    i = argv.index("--after-update")
    pid = argv[i + 1] if i + 1 < len(argv) else ""
    if pid.isdigit():
        import psutil

        try:
            psutil.Process(int(pid)).wait(timeout=20)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass


def clean_leftovers() -> None:
    """Removes the previous .exe (Windows) and unfinished downloads."""
    if not getattr(sys, "frozen", False):
        return
    target = Path(sys.executable) if WINDOWS else Path(os.environ.get("APPIMAGE") or sys.executable)
    for leftover in (_old(target), _partial(target)):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass    # still in use: next time
