#!/usr/bin/env python3
"""Overlay probe (KDE Wayland): does a Wayland layer-shell overlay keep the mouse
and keyboard away from Star Citizen when you click it? A test tool, not part of
the app. See ~/.ai/plans/sc-toolkit-overlay-attempts.md.

Run it with the SYSTEM Python (its PySide6 matches the system's LayerShellQt):
    /usr/bin/python3 tools/overlay_probe.py [--delay 8] [--keyboard ondemand|exclusive]

It waits --delay seconds (switch back into the game meanwhile), then shows a
dimmed full-screen layer with a small panel on the active screen. Click the
panel, the dimmed area and your other screen, and type in the box. Close it
with its Close button or Esc; it also closes itself after 90 seconds.
Everything it notices goes to ~/.cache/sc-toolkit/overlay-probe.log.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
os.environ["QT_WAYLAND_SHELL_INTEGRATION"] = "layer-shell"

from PySide6.QtCore import QEvent, QObject, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget,
)
import shiboken6  # noqa: E402

LOG = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sc-toolkit" / "overlay-probe.log"
AUTO_CLOSE_SECONDS = 90
LAYER_OVERLAY = 3
KEYBOARD = {"exclusive": 1, "ondemand": 2}
ANCHOR_ALL = 1 | 2 | 4 | 8
T0 = time.monotonic()


def log(text: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} +{time.monotonic() - T0:6.2f}s  {text}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")
    if probe is not None:
        probe.events.addItem(line)
        probe.events.scrollToBottom()


class Probe(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SC-Toolkit overlay probe")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        panel = QWidget(self, objectName="panel")
        panel.setStyleSheet("#panel{background:#1d2126;border:1px solid #e3a33b;border-radius:10px}"
                            "QLabel,QListWidget{color:#f3ede2} QPushButton{padding:6px 12px}")
        panel.setGeometry(120, 120, 520, 420)
        v = QVBoxLayout(panel)
        v.addWidget(QLabel("<b>SC-Toolkit overlay probe</b><br>Click here, on the dimmed area and on your "
                           "other screen; type in the box. Does the game react or make sound?"))
        row = QWidget()
        rv = QVBoxLayout(row)
        rv.setContentsMargins(0, 0, 0, 0)
        for name in ("Button A", "Button B"):
            b = QPushButton(name)
            b.clicked.connect(lambda _c=False, n=name: log(f"clicked {n}"))
            rv.addWidget(b)
        v.addWidget(row)
        self.edit = QLineEdit(placeholderText="type here")
        self.edit.textEdited.connect(lambda t: log(f"typed: {t!r}"))
        v.addWidget(self.edit)
        self.events = QListWidget()
        v.addWidget(self.events, stretch=1)
        close = QPushButton("Close probe")
        close.clicked.connect(QApplication.quit)
        v.addWidget(close)

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 90))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            log("Esc: closing")
            QApplication.quit()
        super().keyPressEvent(event)


class Spy(QObject):
    def eventFilter(self, obj, event):
        t = event.type()
        if obj is probe and t in (QEvent.WindowActivate, QEvent.WindowDeactivate):
            log(f"overlay {'ACTIVE (has focus)' if t == QEvent.WindowActivate else 'INACTIVE (lost focus)'}")
        elif t == QEvent.MouseButtonPress and obj is probe:
            p = event.position().toPoint()
            log(f"click on the dimmed area at {p.x()},{p.y()}")
        return False


def make_layer(window: QWidget, keyboard: int) -> None:
    lib = ctypes.CDLL("libLayerShellQtInterface.so.6")
    get = lib._ZN12LayerShellQt6Window3getEP7QWindow   # LayerShellQt::Window::get(QWindow*)
    get.restype = ctypes.c_void_p
    get.argtypes = [ctypes.c_void_p]
    window.winId()
    shell = shiboken6.wrapInstance(get(shiboken6.getCppPointer(window.windowHandle())[0]), QObject)
    for key, value in (("layer", LAYER_OVERLAY), ("keyboardInteractivity", keyboard),
                       ("anchors", ANCHOR_ALL), ("exclusionZone", -1), ("scope", "sc-toolkit-overlay-probe"),
                       ("activateOnShow", True), ("wantsToBeOnActiveScreen", True)):
        if not shell.setProperty(key, value):
            log(f"warning: couldn't set {key}")


probe: Probe | None = None


def main() -> int:
    global probe
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=8)
    parser.add_argument("--keyboard", choices=KEYBOARD, default="ondemand")
    args = parser.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    if app.platformName() != "wayland":
        print("Needs a Wayland session (KDE Plasma).", file=sys.stderr)
        return 1
    probe = Probe()
    spy = Spy()
    app.installEventFilter(spy)
    make_layer(probe, KEYBOARD[args.keyboard])
    log(f"--- probe start (keyboard={args.keyboard}); showing in {args.delay:g}s: switch to the game now")

    def show():
        probe.show()
        log("overlay shown")
        QTimer.singleShot(AUTO_CLOSE_SECONDS * 1000, lambda: (log("auto-close"), app.quit()))
    QTimer.singleShot(int(args.delay * 1000), show)
    code = app.exec()
    log("--- probe end")
    return code


if __name__ == "__main__":
    sys.exit(main())
