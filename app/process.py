"""Tiny process-presence check, used to refuse restoring/launching into an
already-running game or RSI Launcher.
"""

import subprocess

_PATTERNS = ("StarCitizen.exe", "RSI Launcher.exe")


def is_game_running() -> bool:
    for pattern in _PATTERNS:
        result = subprocess.run(
            ["pgrep", "-f", pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            return True
    return False
