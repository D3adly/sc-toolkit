"""The overlay's home on KDE Wayland: one full-screen layer-shell surface
(wlr-layer-shell, "overlay" layer) on the game's screen.

Why: KWin keeps layer-shell surfaces above fullscreen windows *and* lets
you click into them without handing the focus back to the game. The X11
approach (an OSD-type window plus a separate input shield) lost the focus
to the game on every click; see ~/.ai/plans/sc-toolkit-overlay-attempts.md.

The surface covers the whole screen. Interactive: it's dimmed around the
overlay panel (a child widget, moved and resized inside it), takes the
keyboard on demand and swallows every click, so nothing reaches the game.
Click-through: no dim, no input region, no keyboard; only the panel is
drawn and everything goes to the game.

Needs Qt's layer-shell integration (LayerShellQt, part of Plasma), loaded
with QT_WAYLAND_SHELL_INTEGRATION=layer-shell. Its plugin only loads into
the Qt it was built against: app.overlay_host starts the overlay with our
own build of it (made for our PySide6's Qt, packaging/build_layershellqt.sh)
or, in a source checkout without that, with the system Python, PySide6 and
LayerShellQt; else with the X11 overlay. See _layer_shell_mode there.
"""

from __future__ import annotations

import ctypes
import os

import shiboken6
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

LAYER_OVERLAY = 3
KEYBOARD_NONE, KEYBOARD_ON_DEMAND = 0, 2
ANCHOR_ALL = 1 | 2 | 4 | 8          # top | bottom | left | right: the whole screen
DIM = QColor(0, 0, 0, 70)


def _layer_window(window) -> QObject:
    """LayerShellQt::Window for a QWindow: a QObject whose Q_PROPERTYs
    (layer, anchors, keyboardInteractivity, …) configure the surface."""
    # Our bundled build by path (the loader would find the system's first), or the system's.
    lib = ctypes.CDLL(os.environ.get("SCT_LAYER_SHELL_LIB", "libLayerShellQtInterface.so.6"))
    get = lib._ZN12LayerShellQt6Window3getEP7QWindow    # static Window *get(QWindow *)
    get.restype = ctypes.c_void_p
    get.argtypes = [ctypes.c_void_p]
    return shiboken6.wrapInstance(get(shiboken6.getCppPointer(window)[0]), QObject)


class LayerHost(QWidget):
    """The full-screen surface; the overlay panel is its child."""

    def __init__(self, hint: str):
        super().__init__()
        self.hint = hint
        self.passive = False            # click-through
        self.setWindowTitle("SC-Toolkit overlay")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.winId()                    # the QWindow must exist to attach the layer surface
        self._shell = _layer_window(self.windowHandle())
        for key, value in (("layer", LAYER_OVERLAY), ("anchors", ANCHOR_ALL), ("exclusionZone", -1),
                           ("scope", "sc-toolkit-overlay"), ("wantsToBeOnActiveScreen", True)):
            self._shell.setProperty(key, value)
        self._apply_mode()

    def _apply_mode(self) -> None:
        """Takes effect at the next show (the surface is re-created on map)."""
        self._shell.setProperty("keyboardInteractivity", KEYBOARD_NONE if self.passive else KEYBOARD_ON_DEMAND)
        self._shell.setProperty("activateOnShow", not self.passive)
        self.windowHandle().setFlag(Qt.WindowTransparentForInput, self.passive)

    def present(self, passive: bool) -> None:
        """Shows the surface (again) in the given mode. Re-mapping is what
        hands the keyboard over: on-demand surfaces get it when shown, and
        dropping to 'none' gives it back to the game."""
        if self.isVisible() and passive == self.passive:
            return
        if self.isVisible():
            self.hide()
        self.passive = passive
        self._apply_mode()
        self.show()
        self.update()

    def paintEvent(self, _event):
        if self.passive:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), DIM)
        font = p.font()
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(self.rect().adjusted(0, 0, 0, -28), Qt.AlignHCenter | Qt.AlignBottom, self.hint)

    def mousePressEvent(self, event):
        event.accept()                  # the dimmed area: swallowed, never reaches the game

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            keep_inside = getattr(child, "keep_inside", None)
            if keep_inside:
                keep_inside()
