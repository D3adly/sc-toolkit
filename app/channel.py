"""Star Citizen channel (LIVE/PTU/EPTU/TECH-PREVIEW) detection.

The on-disk casing of RSI's own directory names (USER/Client/0/Controls/
Mappings vs. user/client/0/controls/mappings) has been inconsistent across
game builds, so every path component is resolved case-insensitively against
whatever actually exists on disk instead of a hardcoded case.
"""

from dataclasses import dataclass
from pathlib import Path

CHANNELS = ["LIVE", "HOTFIX", "PTU", "EPTU", "TECH-PREVIEW"]


def resolve_ci(base: Path, *components: str) -> Path:
    cur = base
    for comp in components:
        direct = cur / comp
        if direct.is_dir():
            cur = direct
            continue
        match = None
        if cur.is_dir():
            lowered = comp.lower()
            for entry in cur.iterdir():
                if entry.is_dir() and entry.name.lower() == lowered:
                    match = entry
                    break
        cur = match if match is not None else direct
    return cur


@dataclass(frozen=True)
class ChannelPaths:
    channel: str
    channel_root: Path
    mappings_dir: Path
    profile_dir: Path


def detect_channels(game_root: Path | None) -> list[str]:
    """Channel folders present under the StarCitizen folder (the parent of
    the LIVE folder chosen in settings).
    """
    if game_root is None:
        return []
    base = game_root
    if not base.is_dir():
        return []
    found = []
    for name in CHANNELS:
        if resolve_ci(base, name).is_dir():
            found.append(name)
    return found


def pick_default_channel(game_root: Path | None) -> str | None:
    found = detect_channels(game_root)
    if not found:
        return None
    if "LIVE" in found:
        return "LIVE"
    return found[0]


def resolve_channel_paths(game_root: Path, channel: str) -> ChannelPaths:
    channel_root = resolve_ci(game_root, channel)
    user_dir = resolve_ci(channel_root, "user", "client", "0")
    mappings_dir = resolve_ci(user_dir, "controls", "mappings")
    profile_dir = resolve_ci(user_dir, "Profiles", "default")
    return ChannelPaths(
        channel=channel,
        channel_root=channel_root,
        mappings_dir=mappings_dir,
        profile_dir=profile_dir,
    )
