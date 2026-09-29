"""Fixed, non-user-editable locations: assets bundled with the app and the
per-OS app directories. Everything about the user's own machine (game
install, launch script, GameGlass, backups) lives in app.settings.
"""

import shutil
from pathlib import Path

import platformdirs

APP_NAME = "sc-toolkit"
DISPLAY_NAME = "SC-Toolkit"
USER_AGENT = "sc-toolkit"
_LEGACY_APP_NAME = "sc-launcher-app"  # name before the SC-Toolkit rename
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BACKGROUND_IMAGE = ASSETS_DIR / "polaris_bg.png"
ICONS_DIR = ASSETS_DIR / "icons"
APP_ICON = ASSETS_DIR / "app_icon.png"
# Per-user app state (settings, joystick identify results, layout tweaks),
# re-derivable caches (data decoded out of Data.p4k), and default backups.
USER_CONFIG_DIR = Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))
CACHE_DIR = Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))
DATA_DIR = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def migrate_legacy_dirs() -> None:
    """One-time move of settings/cache/data from the pre-rename folder names
    (sc-launcher-app) to the current ones, so an update keeps everything.
    """
    for new in (USER_CONFIG_DIR, CACHE_DIR, DATA_DIR):
        old = Path(str(new).replace(APP_NAME, _LEGACY_APP_NAME))
        if old != new and old.is_dir() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
