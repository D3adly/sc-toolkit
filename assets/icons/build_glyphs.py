"""Renders the small monochrome line glyphs used on filter buttons (My Stats
blueprint types). They're drawn white on transparent; the app tints them
(app.ui.glyphs) for the normal / hover / selected states, so one PNG per
glyph covers every theme colour.

Run manually after changing a glyph (needs the app's venv):
    .venv/bin/python assets/icons/build_glyphs.py
Writes assets/icons/glyphs/<name>.png.
"""

import os
import sys
from pathlib import Path

OUT = Path(__file__).parent / "glyphs"
RENDER = 512   # rendered this large, then downsampled for clean edges
SIZE = 64      # shown at 18-20 px

# 24-unit canvas, 1.7-unit strokes, round joins: one family of line icons.
STYLE = 'fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
SOLID = 'fill="#fff" stroke="none"'

GLYPHS = {
    # Four tiles: everything.
    "all": f"""
<rect x="4" y="4" width="6.5" height="6.5" rx="1.2" {STYLE}/>
<rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2" {STYLE}/>
<rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2" {STYLE}/>
<rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2" {STYLE}/>
""",
    # Sidearm in profile: slide, grip, trigger guard.
    "weapons": f"""
<path d="M3 7.5 H20.5 V11 H11.5 L10 12.5" {STYLE}/>
<path d="M8.5 11 L6.5 19.5 H10 L11.8 12.4" {STYLE}/>
<path d="M11.5 11 Q12.5 14.5 14.5 13.5 V11" {STYLE}/>
<path d="M17 7.5 V5.5" {STYLE}/>
""",
    # Helmet with a visor band.
    "armour": f"""
<path d="M4.5 15 V12 A7.5 7.5 0 0 1 19.5 12 V15 L17.5 19 H6.5 Z" {STYLE}/>
<path d="M7 12.5 H17 V15 H7 Z" {STYLE}/>
""",
    # Module with connector pins on every side.
    "components": f"""
<rect x="7" y="7" width="10" height="10" rx="1.5" {STYLE}/>
<rect x="10" y="10" width="4" height="4" {SOLID}/>
<path d="M10 3.5 V7 M14 3.5 V7 M10 17 V20.5 M14 17 V20.5 M3.5 10 H7 M3.5 14 H7 M17 10 H20.5 M17 14 H20.5" {STYLE}/>
""",
    # Ship cannon on its hardpoint: housing, barrel with muzzle brake, pylon.
    "ship_weapons": f"""
<rect x="3" y="7.5" width="9.5" height="7" rx="1.5" {STYLE}/>
<path d="M12.5 11 H19 M19 9 V13 M19 11 H21.5" {STYLE}/>
<path d="M5.5 14.5 L4.5 19 M10 14.5 L11 19 M3 19 H12.5" {STYLE}/>
""",
    # Spanner.
    "utility": f"""
<path d="M14.5 4.2 A4.6 4.6 0 0 0 10.2 10.4 L4.3 16.3 A1.9 1.9 0 0 0 7 19 L12.9 13.1
         A4.6 4.6 0 0 0 19.1 8.8 L16.3 11.6 L13.2 10.1 L11.7 7 Z" {STYLE}/>
""",
    # Cross in a ring.
    "medical": f"""
<circle cx="12" cy="12" r="8.5" {STYLE}/>
<path d="M10.2 7 H13.8 V10.2 H17 V13.8 H13.8 V17 H10.2 V13.8 H7 V10.2 H10.2 Z" {STYLE}/>
""",
    # Cell with a charge bolt.
    "power": f"""
<rect x="3.5" y="7.5" width="15" height="9" rx="1.5" {STYLE}/>
<path d="M18.5 10.5 H20.5 V13.5 H18.5" {STYLE}/>
<path d="M12 9 L8.5 12.5 H12 L10 15" {STYLE}/>
""",
    # Sealed cargo box.
    "mission": f"""
<path d="M12 3.5 L19.5 7.5 V16.5 L12 20.5 L4.5 16.5 V7.5 Z" {STYLE}/>
<path d="M4.5 7.5 L12 11.5 L19.5 7.5 M12 11.5 V20.5" {STYLE}/>
<path d="M8.2 5.5 L15.8 9.5" {STYLE}/>
""",
    # Anything the game data doesn't place.
    "other": f"""
<circle cx="12" cy="12" r="8.5" {STYLE}/>
<circle cx="8" cy="12" r="1.3" {SOLID}/>
<circle cx="12" cy="12" r="1.3" {SOLID}/>
<circle cx="16" cy="12" r="1.3" {SOLID}/>
""",
}


def svg(name: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
            f"{GLYPHS[name]}</svg>")


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
    OUT.mkdir(exist_ok=True)
    for name in GLYPHS:
        render(name).resize((SIZE, SIZE), Image.LANCZOS).save(OUT / f"{name}.png")
        print(f"wrote icons/glyphs/{name}.png")


if __name__ == "__main__":
    main()
