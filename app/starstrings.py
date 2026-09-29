"""StarStrings community translation (https://github.com/MrKraken/StarStrings)
update check + install.

Compatibility check: StarStrings' README titles each release against the
exact game build it was made for, e.g.
    Star Citizen [Build: sc-alpha-4.10.1_live_12660092]
The trailing number (12660092) is a Perforce changelist number — the same
value Star Citizen's own build_manifest.id exposes as RequestedP4ChangeNum.
That's the precise identifier compared here, not the human-readable
X.Y.Z version string, since it's what StarStrings itself keys off.

Their GitHub "latest" release tag is permanently reused ("latest"), so the
release is never identified by tag — only by the release asset's sha256
digest, which is also verified before anything is installed.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app import config

README_URL = "https://raw.githubusercontent.com/MrKraken/StarStrings/master/readme.md"
RELEASES_API = "https://api.github.com/repos/MrKraken/StarStrings/releases/latest"
ASSET_NAME = "StarStrings-LIVE.zip"
BUILD_ID_RE = re.compile(r"_live_(\d+)", re.IGNORECASE)
TIMEOUT = 15


class StarStringsError(Exception):
    pass


class VersionMismatch(Exception):
    def __init__(self, installed: str, required: str):
        super().__init__(f"installed {installed} != required {required}")
        self.installed = installed
        self.required = required


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    digest_sha256: str
    release_name: str


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def get_installed_build_id(channel_root: Path) -> str:
    manifest = channel_root / "build_manifest.id"
    if not manifest.is_file():
        raise StarStringsError(f"build_manifest.id not found:\n{manifest}")
    try:
        data = json.loads(manifest.read_text())
        return str(data["Data"]["RequestedP4ChangeNum"])
    except (json.JSONDecodeError, KeyError) as exc:
        raise StarStringsError(f"Could not read game build number:\n{exc}") from exc


def get_repo_target_build_id() -> str:
    try:
        text = _http_get(README_URL).decode("utf-8", errors="replace")
    except OSError as exc:
        raise StarStringsError(f"Could not reach StarStrings repository:\n{exc}") from exc
    match = BUILD_ID_RE.search(text)
    if not match:
        raise StarStringsError("Could not find a build number in the StarStrings README.")
    return match.group(1)


def get_latest_release_asset() -> ReleaseAsset:
    try:
        raw = _http_get(RELEASES_API)
    except OSError as exc:
        raise StarStringsError(f"Could not reach GitHub:\n{exc}") from exc

    data = json.loads(raw)
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            digest = asset.get("digest", "")
            digest = digest.split(":", 1)[1] if ":" in digest else digest
            return ReleaseAsset(
                name=asset["name"],
                download_url=asset["browser_download_url"],
                digest_sha256=digest,
                release_name=data.get("name", ASSET_NAME),
            )
    raise StarStringsError(f"No '{ASSET_NAME}' asset found in the latest release.")


def download_and_install(asset: ReleaseAsset, channel_root: Path) -> None:
    import hashlib

    tmp_dir = Path(tempfile.mkdtemp(prefix="starstrings_"))
    try:
        zip_path = tmp_dir / asset.name
        try:
            data = _http_get(asset.download_url)
        except OSError as exc:
            raise StarStringsError(f"Download failed:\n{exc}") from exc
        zip_path.write_bytes(data)

        actual = hashlib.sha256(data).hexdigest()
        if asset.digest_sha256 and actual != asset.digest_sha256:
            raise StarStringsError(
                "Downloaded file failed its checksum check — aborting, nothing changed."
            )

        extract_dir = tmp_dir / "extracted"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        global_ini = next(extract_dir.rglob("global.ini"), None)
        if global_ini is None:
            raise StarStringsError(
                "The downloaded archive did not contain global.ini — aborting, nothing changed."
            )

        target_dir = channel_root / "Data" / "Localization" / "english"
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(global_ini, target_dir / "global.ini")

        _ensure_user_cfg_language(channel_root / "user.cfg")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _ensure_user_cfg_language(user_cfg: Path) -> None:
    line = "g_language = english"
    if not user_cfg.is_file():
        user_cfg.write_text(line + "\n")
        return
    existing = user_cfg.read_text()
    if any(l.strip() == line for l in existing.splitlines()):
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    user_cfg.write_text(existing + line + "\n")
