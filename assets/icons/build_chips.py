"""One-off preprocessing: composites each raw favicon/icon onto a uniform
light rounded chip so dark-logo icons (RSI, SC Wiki) stay legible against
our dark button backgrounds, and every button gets a consistent icon size.
Run manually whenever a source icon in raw/ changes; output lands next to
this script and is what the app actually loads.
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
RAW = HERE / "raw"
SIZE = 40
LOGO_SIZE = 28
RADIUS = 9
CHIP_COLOR = (255, 255, 255, 235)

NAMES = ["rsi", "status", "scmdb", "erkul", "uexcorp", "gameglass", "starstrings", "scmaps", "joystick", "salvage", "mining"]


def rounded_chip() -> Image.Image:
    chip = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(chip)
    draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=RADIUS, fill=CHIP_COLOR)
    return chip


def main():
    for name in NAMES:
        src = RAW / f"{name}.png"
        logo = Image.open(src).convert("RGBA")
        logo.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)

        chip = rounded_chip()
        x = (SIZE - logo.width) // 2
        y = (SIZE - logo.height) // 2
        chip.alpha_composite(logo, (x, y))

        out = HERE / f"{name}.png"
        chip.save(out)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
