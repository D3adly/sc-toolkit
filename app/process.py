"""Process-presence check, used to refuse restoring/launching into an
already-running game or RSI Launcher.
"""

from app.osutil import is_game_running

__all__ = ["is_game_running"]
