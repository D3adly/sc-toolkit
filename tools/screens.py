"""Renders every launcher screen and overlay panel to PNG, offscreen, for
design review: `python tools/screens.py OUT_DIR [name ...]`.

It never touches the real desktop or your settings: Qt runs on the offscreen
platform and every XDG directory points into OUT_DIR/xdg, which starts as a
copy of your SC-Toolbox config and cache (so the tools show real data).
Names: home, salvage, mining, stats, hangar, maps, missions, bindings,
settings, whatsnew, overlay_<tool> (missions, session, maps, mining,
salvage), overlay_bar, overlay_min; the horizontal band: overlay_h_<tool>,
overlay_h_folded, overlay_h_drop (a list open), overlay_h_menu, overlay_h_up
(at the bottom, a list open upwards), overlay_h_narrow, overlay_h_compact,
overlay_h_tall; none = all. The offscreen screen is 2560×1440.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ["home", "salvage", "mining", "stats", "hangar", "maps", "missions", "bindings", "settings",
            "whatsnew"]
OVERLAY = ["overlay_missions", "overlay_session", "overlay_maps", "overlay_mining", "overlay_salvage",
           "overlay_bar", "overlay_min"]
BAND = [f"overlay_h_{t}" for t in ("missions", "session", "mining", "salvage", "maps")] + [
    "overlay_h_folded", "overlay_h_drop", "overlay_h_menu", "overlay_h_up", "overlay_h_narrow",
    "overlay_h_compact", "overlay_h_tall"]


def _isolate(out: Path) -> None:
    xdg = out / "xdg"
    home = Path.home()
    for kind, env, real in (("cfg", "XDG_CONFIG_HOME", home / ".config"),
                            ("cache", "XDG_CACHE_HOME", home / ".cache"),
                            ("data", "XDG_DATA_HOME", home / ".local" / "share")):
        target = xdg / kind
        target.mkdir(parents=True, exist_ok=True)
        os.environ[env] = str(target)
        src = Path(os.environ.get(f"REAL_{env}", real)) / "sc-toolkit"
        if src.is_dir() and not (target / "sc-toolkit").exists():
            shutil.copytree(src, target / "sc-toolkit")
    screens = out / "screens.json"
    screens.write_text('{"screens": [{"name": "s1", "x": 0, "y": 0, "width": 2560, "height": 1440, '
                       '"logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}')
    os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={screens}"


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screens").resolve()
    wanted = sys.argv[2:] or LAUNCHER + OVERLAY + BAND
    _isolate(out)
    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from app import config

    assert str(config.USER_CONFIG_DIR).startswith(str(out)), config.USER_CONFIG_DIR
    from app.theme import build_stylesheet

    app.setStyleSheet(build_stylesheet())

    def settle(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    if any(n in LAUNCHER for n in wanted):
        from app.ui.main_window import MainWindow

        win = MainWindow(start_overlay=False)
        win.resize(int(os.environ.get("SCREENS_W", 1240)), int(os.environ.get("SCREENS_H", 760)))
        win.show()
        settle(1.0)
        for name in [n for n in LAUNCHER if n in wanted]:
            win.show_tool(name) if name != "home" else win.show_tool("launch")
            settle(4.0 if name != "home" else 1.5)
            win.grab().save(str(out / f"{name}.png"))
            print("saved", name, flush=True)
    if any(n in OVERLAY for n in wanted):
        from app.ui import overlay

        ov = overlay.OverlayWindow()
        ov.show()
        settle(0.5)
        for name in [n for n in OVERLAY if n in wanted]:
            if name == "overlay_bar":
                ov.collapse()
            elif name == "overlay_min":
                ov.set_minimized(True)
            else:
                ov.set_minimized(False)
                ov.select_tool(name.removeprefix("overlay_"), force=True)
            settle(3.0)
            ov.grab().save(str(out / f"{name}.png"))
            print("saved", name, flush=True)
    if any(n in BAND for n in wanted):
        from app.ui import overlay

        ov = overlay.OverlayWindow()
        ov.set_minimized(False)
        ov.set_layout("horizontal")
        ov.show()
        settle(0.5)
        for name in [n for n in BAND if n in wanted]:
            ov.close_drop()
            ov.set_band_height("normal")
            ov.state.pop("band_width", None)
            ov.move_to("tc")
            ov.set_folded(False)
            what = name.removeprefix("overlay_h_")
            if what in overlay.TOOLS:
                ov.select_tool(what, force=True)
            elif what == "folded":
                ov.set_folded(True)
            elif what in ("drop", "up"):
                if what == "up":
                    ov.move_to("bc")
                ov._band_panels[ov.tool].jump.showPopup()
            elif what == "menu":
                ov._show_menu(True)
            elif what == "narrow":
                ov.resize_band(1000, ov._home, ov.width(), keep_right=False)
            else:
                ov.set_band_height(what)
            settle(1.0)
            ov.grab().save(str(out / f"{name}.png"))
            print("saved", name, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
