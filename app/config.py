"""Fixed, non-user-editable locations: assets bundled with the app and the
per-OS app directories. Everything about the user's own machine (game
install, launch script, GameGlass, backups) lives in app.settings.
"""

import shutil
import sys
from pathlib import Path

import platformdirs

APP_NAME = "sc-toolkit"
DISPLAY_NAME = "SC-Toolkit"
USER_AGENT = "sc-toolkit"
_LEGACY_APP_NAME = "sc-launcher-app"  # name before the SC-Toolkit rename
# Bundled assets live next to the package, or in PyInstaller's unpack dir
# when running as a built executable.
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ASSETS_DIR = _BASE / "assets"
# Official CIG Fankit wallpaper (SC_26, the Corsair), used under the Fankit Agreement:
# its "STAR CITIZEN" watermark must stay visible and CIG_NOTICE must be shown.
BACKGROUND_IMAGE = ASSETS_DIR / "background.jpg"
BACKGROUND_WATERMARK = (0.94, 0.917, 0.058, 0.08)  # x, y, w, h as fractions of the image
BACKGROUND_ANCHOR_RIGHT = True  # the watermark is in the bottom-right corner
CIG_NOTICE = (
    "This site is not endorsed by or affiliated with the Cloud Imperium or Roberts Space "
    "Industries group of companies. All game content and materials are copyright Cloud "
    "Imperium Rights LLC and Cloud Imperium Rights Ltd.. Star Citizen®, Squadron 42®, "
    "Roberts Space Industries®, and Cloud Imperium® are registered trademarks of Cloud "
    "Imperium Rights LLC. All rights reserved."
)
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
