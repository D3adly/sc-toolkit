"""Renders SC-Toolkit's own icons (the app icon and the tool icons) from the
vector sources below. They share one look: a gunmetal badge with a gold
bevelled rim and a gold glyph with sky-steel highlights (app.theme's accent
and info colours). Third-party favicons are handled by build_chips.py.

Run manually after changing a glyph (needs the app's venv):
    .venv/bin/python assets/icons/build_icons.py
Writes assets/icons/<tool>.png, assets/app_icon.png and assets/app_icon.ico.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
ASSETS = HERE.parent
RENDER = 1024        # rendered this large, then downsampled for clean edges
TOOL_SIZE = 128      # shown at 48 px in the tool tiles, 20 px on buttons
APP_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Shared paints. Gradients are in user space (the 128-unit canvas) so every
# glyph gets the same light from above.
DEFS = """
<linearGradient id="chipFill" x1="0" y1="4" x2="0" y2="124" gradientUnits="userSpaceOnUse">
  <stop offset="0" stop-color="#2d353d"/><stop offset="1" stop-color="#0e1114"/>
</linearGradient>
<linearGradient id="rim" x1="0" y1="4" x2="0" y2="124" gradientUnits="userSpaceOnUse">
  <stop offset="0" stop-color="#f7cf7e"/><stop offset="0.5" stop-color="#c98f33"/>
  <stop offset="1" stop-color="#6e4f1c"/>
</linearGradient>
<radialGradient id="glow" cx="64" cy="60" r="56" gradientUnits="userSpaceOnUse">
  <stop offset="0" stop-color="#e3a33b" stop-opacity="0.22"/>
  <stop offset="1" stop-color="#e3a33b" stop-opacity="0"/>
</radialGradient>
<linearGradient id="gold" x1="0" y1="16" x2="0" y2="110" gradientUnits="userSpaceOnUse">
  <stop offset="0" stop-color="#ffe3a0"/><stop offset="0.45" stop-color="#eab04c"/>
  <stop offset="1" stop-color="#b37622"/>
</linearGradient>
<linearGradient id="goldDark" x1="0" y1="16" x2="0" y2="110" gradientUnits="userSpaceOnUse">
  <stop offset="0" stop-color="#d9a045"/><stop offset="1" stop-color="#7d5419"/>
</linearGradient>
<linearGradient id="steel" x1="0" y1="16" x2="0" y2="110" gradientUnits="userSpaceOnUse">
  <stop offset="0" stop-color="#d6ecfa"/><stop offset="1" stop-color="#7fa9c6"/>
</linearGradient>
<linearGradient id="beam" x1="0" y1="44" x2="0" y2="90" gradientUnits="userSpaceOnUse">
  <stop offset="0" stop-color="#bfe0f5" stop-opacity="0.95"/>
  <stop offset="1" stop-color="#8db4cf" stop-opacity="0.25"/>
</linearGradient>
"""

CHIP = """
<rect x="5" y="5" width="118" height="118" rx="26" fill="url(#chipFill)"/>
<rect x="5" y="5" width="118" height="118" rx="26" fill="url(#glow)"/>
<rect x="5" y="5" width="118" height="118" rx="26" fill="none" stroke="url(#rim)" stroke-width="3.5"/>
<rect x="9.5" y="9.5" width="109" height="109" rx="22" fill="none" stroke="#ffffff" stroke-opacity="0.07" stroke-width="1.5"/>
"""

INK = "#14171b"   # cut lines inside the gold

GLYPHS = {
    # Delta-wing ship crossing an orbit ring.
    "app": f"""
<ellipse cx="64" cy="68" rx="50" ry="15" transform="rotate(-18 64 68)" fill="none"
         stroke="#8db4cf" stroke-width="3.2" stroke-opacity="0.75"/>
<path d="M64 14 L99 98 L64 83 L29 98 Z" fill="url(#gold)"/>
<path d="M64 14 L99 98 L64 83 Z" fill="url(#goldDark)" fill-opacity="0.55"/>
<path d="M64 14 L64 83" stroke="{INK}" stroke-width="1.6" stroke-opacity="0.5"/>
<path d="M64 33 L70 53 L64 58 L58 53 Z" fill="url(#steel)"/>
<path d="M44 80 L64 72 L84 80" fill="none" stroke="{INK}" stroke-width="2" stroke-opacity="0.45"
      stroke-linejoin="round"/>
<path d="M110.27 58.36 A50 15 -18 0 1 68.64 82.27 A50 15 -18 0 1 20.9 87.4" fill="none"
      stroke="{INK}" stroke-width="8"/>
<path d="M111.55 52.55 A50 15 -18 0 1 68.64 82.27 A50 15 -18 0 1 16.45 83.45" fill="none"
      stroke="url(#steel)" stroke-width="3.2" stroke-linecap="round"/>
<circle cx="26" cy="28" r="1.8" fill="#f3ede2" fill-opacity="0.8"/>
<circle cx="101" cy="24" r="1.3" fill="#f3ede2" fill-opacity="0.6"/>
<circle cx="106" cy="102" r="1.5" fill="#f3ede2" fill-opacity="0.5"/>
""",
    # HOTAS flight stick in side profile: head overhanging forward, trigger
    # under it, hat switch on top.
    "joystick": f"""
<path d="M34 90 L94 90 Q97 90 98.5 93 L103 101 Q105 106 100 106 L28 106 Q23 106 25 101 L29.5 93 Q31 90 34 90 Z"
      fill="url(#goldDark)"/>
<ellipse cx="64" cy="92" rx="16" ry="4" fill="{INK}" fill-opacity="0.55"/>
<rect x="57" y="72" width="14" height="20" rx="3" fill="url(#goldDark)"/>
<path d="M57 78 H71 M57 83 H71 M57 88 H71" stroke="{INK}" stroke-width="1.6" stroke-opacity="0.6"/>
<rect x="50" y="68" width="28" height="8" rx="3.5" fill="url(#gold)"/>
<path d="M47 14.5 L57 12.5 L58 18 L48 20 Z" fill="url(#steel)"/>
<path d="M55 68 L51 50 L46 45 L40 41 L36 31 L42 20 L70 15 L81 22 L81 36 L77 50 L75 68 Z"
      fill="url(#gold)" stroke="url(#gold)" stroke-width="2.5" stroke-linejoin="round"/>
<path d="M70 15 L81 22 L81 36 L77 50 L75 68 L68 68 L70 50 L73 36 L73 23 Z" fill="url(#goldDark)"
      fill-opacity="0.65"/>
<path d="M38 35 L81 30" stroke="{INK}" stroke-width="1.8" stroke-opacity="0.55"/>
<path d="M45 43 L40 51 L46 54" fill="none" stroke="url(#steel)" stroke-width="4.5"
      stroke-linecap="round" stroke-linejoin="round"/>
<path d="M51 55 H60 M52 61 H61" stroke="{INK}" stroke-width="1.8" stroke-opacity="0.5" stroke-linecap="round"/>
<rect x="63" y="24" width="11" height="5" rx="2" fill="{INK}" transform="rotate(-10 68 26)"/>
<rect x="64.5" y="25.2" width="8" height="2.6" rx="1.3" fill="#e26a55" transform="rotate(-10 68 26)"/>
""",
    # Faceted ore crystals on rock, with scan arcs.
    "mining": f"""
<path d="M18 106 L30 92 L52 88 L84 90 L104 98 L110 106 Z" fill="url(#goldDark)" fill-opacity="0.8"/>
<path d="M30 92 L52 88 L84 90" fill="none" stroke="{INK}" stroke-width="1.5" stroke-opacity="0.5"/>
<path d="M28 94 L22 62 L32 50 L42 60 L42 92 Z" fill="url(#gold)" transform="rotate(-14 32 92)"/>
<path d="M32 50 L42 60 L42 92 L34 94 Z" fill="url(#goldDark)" fill-opacity="0.65" transform="rotate(-14 32 92)"/>
<path d="M58 28 L74 44 L74 88 L58 98 L42 88 L42 44 Z" fill="url(#gold)"/>
<path d="M58 28 L74 44 L74 88 L58 98 Z" fill="url(#goldDark)" fill-opacity="0.6"/>
<path d="M42 44 L58 52 L74 44 M58 52 L58 98" fill="none" stroke="{INK}" stroke-width="1.6"
      stroke-opacity="0.55" stroke-linejoin="round"/>
<path d="M47 50 L52 53 L52 70" fill="none" stroke="#fff6dc" stroke-width="2" stroke-opacity="0.7"
      stroke-linecap="round"/>
<path d="M84 34 A30 30 0 0 1 96 58" fill="none" stroke="url(#steel)" stroke-width="3.2" stroke-linecap="round"/>
<path d="M88 22 A42 42 0 0 1 106 56" fill="none" stroke="url(#steel)" stroke-width="3.2"
      stroke-linecap="round" stroke-opacity="0.7"/>
<path d="M93 12 A54 54 0 0 1 114 52" fill="none" stroke="url(#steel)" stroke-width="3.2"
      stroke-linecap="round" stroke-opacity="0.4"/>
""",
    # Scraper head beaming onto a riveted hull plate.
    "salvage": f"""
<path d="M52 44 L76 44 L96 84 L34 92 Z" fill="url(#beam)"/>
<path d="M18 84 L82 68 L110 86 L46 102 Z" fill="url(#gold)"/>
<path d="M18 84 L46 102 L46 110 L18 92 Z" fill="url(#goldDark)"/>
<path d="M46 102 L110 86 L110 94 L46 110 Z" fill="url(#goldDark)" fill-opacity="0.75"/>
<path d="M34 80 L62 98 M58 74 L86 92" stroke="{INK}" stroke-width="1.6" stroke-opacity="0.5"/>
<path d="M36 90 L94 82" stroke="#d6ecfa" stroke-width="4" stroke-opacity="0.9" stroke-linecap="round"/>
<circle cx="26" cy="86" r="1.8" fill="{INK}" fill-opacity="0.6"/>
<circle cx="80" cy="73" r="1.8" fill="{INK}" fill-opacity="0.6"/>
<circle cx="100" cy="85" r="1.8" fill="{INK}" fill-opacity="0.6"/>
<rect x="54" y="10" width="20" height="8" rx="2" fill="url(#goldDark)"/>
<path d="M42 18 L86 18 L82 38 L46 38 Z" fill="url(#gold)"/>
<path d="M64 18 L86 18 L82 38 L64 38 Z" fill="url(#goldDark)" fill-opacity="0.55"/>
<path d="M46 25 H82" stroke="{INK}" stroke-width="1.6" stroke-opacity="0.5"/>
<rect x="48" y="37" width="32" height="8" rx="2" fill="{INK}"/>
<rect x="51" y="39.5" width="26" height="3.5" rx="1.5" fill="url(#steel)"/>
""",
    # Folded map with a route and a location pin.
    "scmaps": f"""
<path d="M18 30 L44 22 L44 98 L18 106 Z" fill="url(#gold)"/>
<path d="M44 22 L84 30 L84 106 L44 98 Z" fill="url(#goldDark)"/>
<path d="M84 30 L110 22 L110 98 L84 106 Z" fill="url(#gold)"/>
<path d="M28 90 C38 78 50 88 60 74 C68 62 80 70 88 58" fill="none" stroke="{INK}"
      stroke-width="3" stroke-dasharray="5 4" stroke-linecap="round" stroke-opacity="0.75"/>
<path d="M88 64 C80 52 76 46 76 40 A12 12 0 0 1 100 40 C100 46 96 52 88 64 Z" fill="{INK}"/>
<path d="M88 60 C82 51 79 46 79 40 A9 9 0 0 1 97 40 C97 46 94 51 88 60 Z" fill="url(#steel)"/>
<circle cx="88" cy="40" r="3.5" fill="{INK}"/>
""",
    # A HUD panel floating over the game's reticle.
    "overlay": f"""
<g fill="none" stroke="url(#steel)" stroke-width="3.2" stroke-linecap="round">
  <circle cx="78" cy="74" r="28" stroke-opacity="0.85"/>
  <path d="M78 38 V50 M78 98 V110 M42 74 H54 M102 74 H114"/>
</g>
<circle cx="78" cy="74" r="3.5" fill="url(#steel)"/>
<rect x="14" y="22" width="62" height="52" rx="7" fill="url(#gold)"/>
<rect x="14" y="22" width="62" height="10" rx="5" fill="url(#goldDark)" fill-opacity="0.6"/>
<rect x="19" y="34" width="52" height="35" rx="3.5" fill="{INK}" fill-opacity="0.88"/>
<circle cx="21" cy="27" r="1.8" fill="{INK}" fill-opacity="0.7"/>
<circle cx="27" cy="27" r="1.8" fill="{INK}" fill-opacity="0.7"/>
<g stroke-width="3.2" stroke-linecap="round">
  <path d="M25 43 H61" stroke="url(#gold)"/>
  <path d="M25 52 H52" stroke="url(#steel)"/>
  <path d="M25 61 H57" stroke="url(#gold)" stroke-opacity="0.7"/>
</g>
""",
    # Globe with an update arrow (Star Strings localisation).
    "starstrings": f"""
<circle cx="56" cy="58" r="38" fill="url(#gold)"/>
<g fill="none" stroke="{INK}" stroke-width="2.2" stroke-opacity="0.6">
  <ellipse cx="56" cy="58" rx="15" ry="38"/>
  <path d="M18 58 H94 M24 38 H88 M24 78 H88 M56 20 V96"/>
</g>
<circle cx="92" cy="92" r="24" fill="{INK}"/>
<circle cx="92" cy="92" r="21" fill="none" stroke="url(#steel)" stroke-width="2"/>
<path d="M82 98 A11 11 0 1 0 84 83" fill="none" stroke="url(#steel)" stroke-width="4" stroke-linecap="round"/>
<path d="M78 78 L88 80 L82 89 Z" fill="url(#steel)"/>
""",
}


def svg(name: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
            f"<defs>{DEFS}</defs>{CHIP}{GLYPHS[name]}</svg>")


def render(name: str):
    """-> PIL image (RENDER x RENDER, RGBA)."""
    from PIL import Image
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg(name).encode()))
    if not renderer.isValid():
        raise SystemExit(f"invalid SVG: {name}")
    image = QImage(RENDER, RENDER, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = bytes(image.constBits())
    return Image.frombuffer("RGBA", (RENDER, RENDER), data, "raw", "RGBA", 0, 1).copy()


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication(sys.argv)
    for name in GLYPHS:
        big = render(name)
        if name == "app":
            big.resize((256, 256), Image.LANCZOS).save(ASSETS / "app_icon.png")
            big.resize((256, 256), Image.LANCZOS).save(
                ASSETS / "app_icon.ico", sizes=[(s, s) for s in APP_SIZES])
            print("wrote app_icon.png, app_icon.ico")
        else:
            big.resize((TOOL_SIZE, TOOL_SIZE), Image.LANCZOS).save(HERE / f"{name}.png")
            print(f"wrote icons/{name}.png")


if __name__ == "__main__":
    main()
