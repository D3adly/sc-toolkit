"""Product photos for the bindings diagram.

The photos are the manufacturer's, so they're downloaded on first use and
cached (never shipped with the app). Each is cropped, has its white studio
background keyed out so it sits on the dark UI, and is scaled to the
template's display size.
"""

from __future__ import annotations

import urllib.request
from collections import deque
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

from app import config

PHOTO_DIR = config.CACHE_DIR / "sticks"

# min(r, g, b) at/above which a border-connected pixel counts as background;
# between EDGE and SOLID it is treated as an anti-aliased edge.
_BG_EDGE = 130
_BG_SOLID = 246
_FG_TONE = 24  # approximate colour of the (black) stick at its edges


def photo_path(template) -> Path:
    return PHOTO_DIR / f"{template.id}.png"


def ensure_photo(template) -> Path | None:
    """Returns the processed photo, downloading it if needed. Slow the
    first time (network + keying); call off the UI thread."""
    out = photo_path(template)
    if out.is_file():
        return out
    photo = template.photo
    try:
        req = urllib.request.Request(photo.url, headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except OSError:
        return None

    image = QImage()
    if not image.loadFromData(data):
        return None
    x, y, w, h = photo.crop
    image = image.copy(QRect(x, y, w, h)).convertToFormat(QImage.Format_ARGB32)
    _key_out_background(image)
    size = template.size
    image = image.scaled(int(size[0]), int(size[1]), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.png")
    if not image.save(str(tmp), "PNG"):
        return None
    tmp.replace(out)
    return out


def _key_out_background(image: QImage) -> None:
    """Flood-fills from the image border through near-white pixels and makes
    them transparent, so white parts *inside* the stick (e.g. a silver
    button) are kept."""
    w, h = image.width(), image.height()
    bpl = image.bytesPerLine()
    buf = image.bits()  # BGRA, writable memoryview
    px = bytearray(buf)

    def light(i: int) -> int:
        return min(px[i], px[i + 1], px[i + 2])

    seen = bytearray(w * h)
    queue: deque[int] = deque()
    for xx in range(w):
        queue.append(xx)
        queue.append((h - 1) * w + xx)
    for yy in range(h):
        queue.append(yy * w)
        queue.append(yy * w + w - 1)

    while queue:
        p = queue.popleft()
        if seen[p]:
            continue
        seen[p] = 1
        yy, xx = divmod(p, w)
        i = yy * bpl + xx * 4
        lum = light(i)
        if lum < _BG_EDGE:
            continue
        if lum >= _BG_SOLID:
            px[i + 3] = 0
        else:
            alpha = int(255 * (_BG_SOLID - lum) / (_BG_SOLID - _BG_EDGE))
            px[i] = px[i + 1] = px[i + 2] = _FG_TONE
            px[i + 3] = alpha
            continue  # an edge pixel: don't flood past it into the stick
        if xx > 0:
            queue.append(p - 1)
        if xx < w - 1:
            queue.append(p + 1)
        if yy > 0:
            queue.append(p - w)
        if yy < h - 1:
            queue.append(p + w)

    buf[:] = px
