"""The in-game overlay: a small always-on-top window that floats over Star
Citizen (borderless windowed mode). It never touches the game process, so
it's anti-cheat safe.

It runs as its own process (`sc-toolkit --overlay`), started by the main
app: on Linux it runs on XWayland (xcb), because Wayland doesn't let a
window keep itself on top of others and doesn't allow global hotkeys,
while X11 windows can do both over the (also XWayland) game. The main
launcher stays native Wayland.

Layout: a slim bar with the tools (icon, one-word caption, its key 1–5
while the overlay has the keyboard), the click-through dot, minimise and
⋯ (opacity, hide, settings), and a status line under it that names
whatever the pointer is on — the overlay has no tooltips (on layer-shell each
is a popup window that flickers). Picking a tool expands its panel
underneath; picking it again collapses back to the bar. Minimised, the
overlay is one line: the current objective, how long you've been on it,
where you are. The opacity fades the background only, never the text.
Position, opacity and each tool's size are remembered.
"""

from __future__ import annotations

import json
import sys

import psutil
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import config, ipc
from app.hotkeys import GlobalHotkeys, label as hotkey_label

STATE_FILE = config.USER_CONFIG_DIR / "overlay.json"

# tool id -> (what it is, for the status line; icon in assets/icons; default panel size; caption)
TOOLS = {
    "missions": ("what you're on, objectives, possible blueprints", "missions", QSize(440, 600), "Missions"),
    "session": ("where you are, this session's numbers and blueprints", "session", QSize(400, 600), "Session"),
    "mining": ("where ores spawn, radar signatures", "mining", QSize(480, 640), "Mining"),
    "salvage": ("which claim ship pays the most", "salvage", QSize(480, 620), "Salvage"),
    "maps": ("community one-page guides", "scmaps", QSize(560, 640), "Maps"),
}
TOOL_ICON = QSize(20, 20)
BAR_MIN_WIDTH = 400
# Tools whose panel height follows their content (see fit_height); the
# user's own resizing only changes their width.
AUTO_HEIGHT_TOOLS = {"missions"}
AUTO_HEIGHT_MAX = 0.7        # of the screen's height, then the panel scrolls

MIN_OPACITY, MAX_OPACITY = 30, 100


def _skip_taskbar(win_id: int) -> None:
    """X11: keep the overlay out of the taskbar and pager (Qt.Tool doesn't
    on X11; on Windows it does). A _NET_WM_STATE request to the WM, sent
    after every show because the WM resets the state on map."""
    import ctypes
    import ctypes.util

    class XClientMessageEvent(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                    ("display", ctypes.c_void_p), ("window", ctypes.c_ulong),
                    ("message_type", ctypes.c_ulong), ("format", ctypes.c_int),
                    ("data", ctypes.c_long * 5)]

    class XEvent(ctypes.Union):
        _fields_ = [("xclient", XClientMessageEvent), ("pad", ctypes.c_long * 24)]

    try:
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    except OSError:
        return
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
                             ctypes.POINTER(XEvent)]
    x.XFlush.argtypes = x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    dpy = x.XOpenDisplay(None)
    if not dpy:
        return
    CLIENT_MESSAGE, NET_WM_STATE_ADD = 33, 1
    SUBSTRUCTURE_REDIRECT, SUBSTRUCTURE_NOTIFY = 1 << 20, 1 << 19
    ev = XEvent()
    ev.xclient.type = CLIENT_MESSAGE
    ev.xclient.window = win_id
    ev.xclient.message_type = x.XInternAtom(dpy, b"_NET_WM_STATE", False)
    ev.xclient.format = 32
    ev.xclient.data[0] = NET_WM_STATE_ADD
    ev.xclient.data[1] = x.XInternAtom(dpy, b"_NET_WM_STATE_SKIP_TASKBAR", False)
    ev.xclient.data[2] = x.XInternAtom(dpy, b"_NET_WM_STATE_SKIP_PAGER", False)
    ev.xclient.data[3] = 1   # source: application
    x.XSendEvent(dpy, x.XDefaultRootWindow(dpy), False,
                 SUBSTRUCTURE_REDIRECT | SUBSTRUCTURE_NOTIFY, ctypes.byref(ev))
    x.XFlush(dpy)
    x.XCloseDisplay(dpy)


def _set_osd_type(win_id: int) -> None:
    """X11: mark the overlay as an on-screen display. KWin stacks active
    fullscreen windows (the game) above ordinary keep-above windows, but
    OSDs above those. Must be set before the window is mapped. KWin then
    won't move or resize it itself, so the overlay does that on its own
    (see _drag and _ResizeGrip)."""
    import ctypes
    import ctypes.util

    try:
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    except OSError:
        return
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    x.XFlush.argtypes = x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    dpy = x.XOpenDisplay(None)
    if not dpy:
        return
    XA_ATOM, PROP_MODE_REPLACE = 4, 0
    # KDE's OSD type, with the standard notification type for other WMs.
    names = (b"_KDE_NET_WM_WINDOW_TYPE_ON_SCREEN_DISPLAY", b"_NET_WM_WINDOW_TYPE_NOTIFICATION")
    atoms = (ctypes.c_ulong * len(names))(*[x.XInternAtom(dpy, n, False) for n in names])
    x.XChangeProperty(dpy, win_id, x.XInternAtom(dpy, b"_NET_WM_WINDOW_TYPE", False), XA_ATOM, 32,
                      PROP_MODE_REPLACE, atoms, len(names))
    x.XFlush(dpy)
    x.XCloseDisplay(dpy)


class _ResizeGrip(QSizeGrip):
    """Resizes the overlay itself: KWin doesn't resize OSD windows, and on
    layer-shell the overlay is a panel inside the surface, not a window."""

    def _overlay(self) -> QWidget:
        w = self.parentWidget()
        while w is not None and not isinstance(w, OverlayWindow):
            w = w.parentWidget()
        return w or self.window()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            win = self._overlay()
            self._start = (event.globalPosition().toPoint(), win.size())
            event.accept()

    def mouseMoveEvent(self, event):
        start = getattr(self, "_start", None)
        if start is None:
            return
        win = self._overlay()
        delta = event.globalPosition().toPoint() - start[0]
        minimum = win.minimumSizeHint()
        win.resize(max(minimum.width(), start[1].width() + delta.x()),
                   max(minimum.height(), start[1].height() + delta.y()))
        event.accept()

    def mouseReleaseEvent(self, event):
        self._start = None
        event.accept()


def _copy_shape_to_input(win_id: int) -> None:
    """X11: Qt's setMask() only shapes what is drawn; make the input shape
    match, so clicks inside the hole go to the window underneath."""
    import ctypes
    import ctypes.util

    try:
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        xe = ctypes.CDLL(ctypes.util.find_library("Xext") or "libXext.so.6")
    except OSError:
        return

    class XRectangle(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                    ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]

    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XFree.argtypes = [ctypes.c_void_p]
    x.XFlush.argtypes = x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xe.XShapeGetRectangles.restype = ctypes.POINTER(XRectangle)
    xe.XShapeGetRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    xe.XShapeCombineRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.POINTER(XRectangle), ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int]
    dpy = x.XOpenDisplay(None)
    if not dpy:
        return
    SHAPE_BOUNDING, SHAPE_INPUT, SHAPE_SET = 0, 2, 0
    count, ordering = ctypes.c_int(), ctypes.c_int()
    rects = xe.XShapeGetRectangles(dpy, win_id, SHAPE_BOUNDING, ctypes.byref(count), ctypes.byref(ordering))
    if rects:
        xe.XShapeCombineRectangles(dpy, win_id, SHAPE_INPUT, 0, 0, rects, count.value,
                                   SHAPE_SET, ordering.value)
        x.XFree(rects)
    x.XFlush(dpy)
    x.XCloseDisplay(dpy)


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


class _InputShield(QWidget):
    """A dimmed, full-screen layer under the overlay while it's interactive:
    every click and mouse movement lands here instead of in the game (which
    would otherwise shoot or turn). Click-through mode or hiding the overlay
    removes it."""

    def __init__(self, hint: str, overlay: QWidget):
        super().__init__()
        self.hint = hint
        self.overlay = overlay
        kind = Qt.Window if sys.platform.startswith("linux") else Qt.Tool
        self.setWindowFlags(kind | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("SC-Toolbox overlay shield")

    def cover(self, screen) -> None:
        self._target = screen.geometry()
        self.setGeometry(self._target)
        self.show()   # before set_hole(): the input shape needs the native window

    def set_hole(self, rect: QRect) -> None:
        """Leaves out the overlay's own area (screen coordinates), so the
        shield never covers it: XWayland routes clicks by its own stacking
        order, which can differ from KWin's."""
        local = QRect(rect.topLeft() - self.geometry().topLeft(), rect.size())
        self.setMask(QRegion(self.rect()).subtracted(QRegion(local)))
        if QApplication.platformName() == "xcb" and self.isVisible():
            QApplication.sync()   # Qt's shape request must reach the X server first
            _copy_shape_to_input(int(self.winId()))

    def moveEvent(self, event):
        # KWin re-places OSD windows (like the overlay itself); stay on the screen.
        super().moveEvent(event)
        target = getattr(self, "_target", None)
        if target is not None and self.pos() != target.topLeft():
            self.move(target.topLeft())

    def showEvent(self, event):
        if QApplication.platformName() == "xcb":
            _set_osd_type(int(self.winId()))
        super().showEvent(event)
        if QApplication.platformName() == "xcb":
            QTimer.singleShot(0, lambda: _skip_taskbar(int(self.winId())))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 70))
        font = p.font()
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(self.rect().adjusted(0, 0, 0, -28), Qt.AlignHCenter | Qt.AlignBottom, self.hint)

    def mousePressEvent(self, event):
        # Swallowed, so it never reaches the game; keep the overlay on top and focused.
        event.accept()
        self.overlay.raise_()
        self.overlay.activateWindow()


class _ToolButton(QPushButton):
    """A tool in the bar: its icon, a one-word caption under it, and its key."""

    def __init__(self, icon: str, caption: str, key: str, parent=None):
        super().__init__(parent, objectName="OverlayTool")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(52, 44)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 3)
        v.setSpacing(1)
        ic = QLabel()
        ic.setPixmap(QIcon(str(config.ICONS_DIR / f"{icon}.png")).pixmap(TOOL_ICON))
        ic.setAlignment(Qt.AlignHCenter)
        ic.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(ic)
        cap = QLabel(caption, objectName="OverlayCaption")
        cap.setAlignment(Qt.AlignHCenter)
        cap.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(cap)
        k = QLabel(key, self, objectName="OverlayKey")
        k.setAttribute(Qt.WA_TransparentForMouseEvents)
        k.move(40, 2)


class _Dot(QWidget):
    """The click-through state: filled green while the overlay takes clicks,
    hollow while they go through to the game."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.on = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(30, 30)

    def set_on(self, on: bool) -> None:
        self.on = on
        self.update()

    def paintEvent(self, _e):
        from app.theme import PALETTE

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(10, 10, 10, 10)
        if self.on:
            halo = QColor(PALETTE["success"])
            halo.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(r.adjusted(-3, -3, 3, 3))
            p.setBrush(QColor(PALETTE["success"]))
            p.drawEllipse(r)
        else:
            from PySide6.QtGui import QPen

            p.setPen(QPen(QColor(PALETTE["text_muted"]), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(1, 1, -1, -1))


class _InlineMenu(QFrame):
    """The ⋯ menu, as a child of the overlay (a QMenu would be a popup
    window: those flicker on the layer-shell surface)."""

    def __init__(self, overlay: "OverlayWindow"):
        super().__init__(overlay, objectName="OverlayMenu")
        self.overlay = overlay
        self.setFixedWidth(250)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(2)
        row = QHBoxLayout()
        row.setContentsMargins(9, 2, 4, 2)
        row.addWidget(QLabel("Background opacity", objectName="OverlayMenuText"), stretch=1)
        minus = QPushButton("−", objectName="OverlayStep")
        minus.clicked.connect(lambda: overlay.set_opacity(overlay._opacity - 10))
        row.addWidget(minus)
        self.value = QLabel("", objectName="OverlayMenuValue")
        self.value.setFixedWidth(40)
        self.value.setAlignment(Qt.AlignCenter)
        row.addWidget(self.value)
        plus = QPushButton("+", objectName="OverlayStep")
        plus.clicked.connect(lambda: overlay.set_opacity(overlay._opacity + 10))
        row.addWidget(plus)
        v.addLayout(row)
        self.ct = self._item(v, "Click-through", hotkey_label("toggle-clickthrough"), overlay.toggle_click_through)
        self._item(v, "Minimise to one line", "", lambda: overlay.set_minimized(True))
        sep = QFrame(objectName="OverlayMenuSep")
        sep.setFixedHeight(1)
        v.addWidget(sep)
        self._item(v, "Hide overlay", hotkey_label("toggle-overlay"), overlay.hide_overlay)
        self._item(v, "Overlay settings in SC-Toolbox", "", lambda: ipc.send(ipc.MAIN, "settings"))

    def _item(self, v, text: str, key: str, slot) -> QPushButton:
        btn = QPushButton(objectName="OverlayMenuItem")
        btn.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(btn)
        row.setContentsMargins(9, 0, 6, 0)
        t = QLabel(text, objectName="OverlayMenuText")
        t.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(t, stretch=1)
        if key:
            k = QLabel(key, objectName="OverlayMenuKey")
            k.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(k)
        btn.setFixedHeight(32)

        def run():
            self.overlay._show_menu(False)
            slot()
        btn.clicked.connect(run)
        v.addWidget(btn)
        return btn

    def sync(self) -> None:
        self.set_opacity(self.overlay._opacity)

    def set_opacity(self, value: int) -> None:
        self.value.setText(f"{value}%")


class _MinimisedBar(QFrame):
    """The minimised overlay: the tracked mission's current objective, how
    long ago you accepted it, and where you are (from the live log)."""

    expand = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, objectName="OverlayMini")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 2, 2)
        row.setSpacing(10)
        grip = QLabel("⠿", objectName="OverlayGrip")
        row.addWidget(grip)
        self.objective = QLabel("", objectName="OverlayMiniObjective")
        row.addWidget(self.objective)
        self.timer = QLabel("", objectName="OverlayMiniTimer")
        row.addWidget(self.timer)
        self.place = QLabel("", objectName="OverlayMiniPlace")
        row.addWidget(self.place)
        row.addStretch(1)
        expand = QPushButton("⤢", objectName="OverlayIcon")
        expand.setCursor(Qt.PointingHandCursor)
        expand.setFixedSize(30, 30)
        expand.clicked.connect(self.expand.emit)
        row.addWidget(expand)
        self._clock = QTimer(self, interval=20_000, timeout=self.refresh)
        self._feed = None

    def start(self) -> None:
        from app.ui import overlay_live

        if self._feed is None:
            self._feed = overlay_live.feed()
            self._feed.changed.connect(self.refresh)
        self._feed.want()
        self._clock.start()
        self.refresh()

    def stop(self) -> None:
        self._clock.stop()

    def refresh(self) -> None:
        if self._feed is None or not self.isVisible() and not self.parent():
            return
        from app.stats import pretty
        from app.ui import overlay_live

        tr = self._feed.tracker
        active = tr.active_missions()
        moved = [m for m in active if m.objective_changed is not None]
        tracked = max(moved, key=lambda m: m.objective_changed) if moved else (active[0] if active else None)
        state = self._feed.state
        if tracked is not None:
            current = tracked.current_objective
            text = current.text if current is not None else overlay_live._mission_title(tracked, None)
            self.objective.setText("▶  " + text[:70] + ("…" if len(text) > 70 else ""))
            self.timer.setText(overlay_live._ago(tracked.accepted))
        elif state == "disabled":
            self.objective.setText("The live log is off (LIVE LOG in SC-Toolbox)")
            self.timer.setText("")
        elif state in ("off", "waiting") and not tr.session:
            self.objective.setText("Waiting for Star Citizen…")
            self.timer.setText("")
        else:
            self.objective.setText("No active mission")
            self.timer.setText("")
        self.place.setText(("· " + pretty(tr.location)) if tr.location else "")
        win = self.window()
        if hasattr(win, "minimized") and win.minimized:
            QTimer.singleShot(0, win._fit_bar)


class OverlayWindow(QWidget):
    """The overlay panel. Its own window (X11 / Windows), or, with `host`, a
    panel inside a full-screen layer-shell surface (KDE Wayland; see
    app.ui.layer_overlay), which then does the showing, hiding and input."""

    def __init__(self, parent=None, host=None):
        super().__init__(host or parent)
        self._host = host
        self.setWindowTitle("SC-Toolbox overlay")
        self.setWindowIcon(QIcon(str(config.APP_ICON)))
        if host is None:
            # Not Qt.Tool on X11: that makes a "utility" window, which KWin hides
            # whenever its app isn't active, i.e. as soon as the game has focus.
            # The taskbar entry is dropped by _skip_taskbar() instead.
            kind = Qt.Window if sys.platform.startswith("linux") else Qt.Tool
            self.setWindowFlags(kind | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground)
            # Showing it must not take focus from the game; click it to type.
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._opacity_effect = None
        self.state = _load_state()
        self.tool: str | None = None
        self.click_through = False
        self._anchor: QPoint | None = None   # where the overlay belongs (see moveEvent)
        self._shield: _InputShield | None = None
        self._bar_width = 440   # the collapsed bar's width (set by _collapse)
        self._resizing = False
        self._panels: dict[str, QWidget] = {}
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_state)
        self._build_ui()
        self.minimized = False
        self._apply_opacity(self.state.get("opacity", 92))
        for i, tool in enumerate(TOOLS, 1):
            QShortcut(QKeySequence(str(i)), self, activated=lambda t=tool: self.select_tool(t, force=True),
                      context=Qt.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._escape, context=Qt.WindowShortcut)
        pos = self.state.get(self._pos_key)
        if pos:
            self._anchor = QPoint(*pos)
            self.move(self._anchor)
        self._collapse()
        if self.state.get("minimized"):
            self.set_minimized(True)

    @property
    def _pos_key(self) -> str:
        # Screen coordinates for the X11 window, surface (screen-local) ones on layer-shell.
        return "layer_pos" if self._host is not None else "pos"

    def _apply_opacity(self, value: int) -> None:
        """Fades the panel's background only: text and icons stay readable
        over any scene (#51)."""
        self._opacity = value
        alpha = max(0.0, min(1.0, value / 100))
        self.frame.setStyleSheet(
            f"#OverlayFrame {{ background: rgba(16, 19, 23, {alpha * 0.97:.3f}); }}")
        if hasattr(self, "menu"):
            self.menu.set_opacity(value)

    def keep_inside(self) -> None:
        """Layer-shell: back inside the surface if it's off-screen (e.g. shown
        on a smaller screen than last time)."""
        if self._host is None or self._host.width() <= 0:
            return
        x = min(max(0, self.x()), max(0, self._host.width() - self.width()))
        y = min(max(0, self.y()), max(0, self._host.height() - 40))
        if (x, y) != (self.x(), self.y()):
            self._anchor = QPoint(x, y)
            self.move(self._anchor)

    def is_shown(self) -> bool:
        return (self._host if self._host is not None else self).isVisible()

    def hide_overlay(self) -> None:
        if self._host is not None:
            self._host.hide()
        else:
            self.hide()

    # -- layout -------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(objectName="OverlayFrame")
        outer.addWidget(self.frame)
        v = QVBoxLayout(self.frame)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(6)

        self.header = QFrame(objectName="OverlayHeader")
        head = QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(2)
        grip = QLabel("⠿", objectName="OverlayGrip")
        self._hint(grip, "<b>Drag</b> to move the overlay")
        head.addWidget(grip)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(False)
        for i, (tool, (what, icon, _size, caption)) in enumerate(TOOLS.items(), 1):
            btn = _ToolButton(icon, caption, str(i))
            btn.clicked.connect(lambda _c=False, t=tool: self.select_tool(t))
            self.tool_group.addButton(btn)
            btn.setProperty("tool", tool)
            self._hint(btn, f"<b>{caption}</b> · {what} · <kbd>{i}</kbd>")
            head.addWidget(btn)
        head.addStretch(1)
        self.ct_btn = QPushButton(objectName="OverlayIcon")
        self.ct_btn.setCursor(Qt.PointingHandCursor)
        self.ct_btn.clicked.connect(self.toggle_click_through)
        self.ct_dot = _Dot(self.ct_btn)
        self.ct_btn.setFixedSize(30, 30)
        self._hint(self.ct_btn, lambda: (
            "<b>Click-through</b> " + ("on: clicks go to the game" if self.click_through
                                       else "off: the overlay takes clicks")
            + f" · <kbd>{hotkey_label('toggle-clickthrough')}</kbd>"))
        head.addWidget(self.ct_btn)
        mini = QPushButton("▭", objectName="OverlayIcon")
        mini.setCursor(Qt.PointingHandCursor)
        mini.setFixedSize(30, 30)
        mini.clicked.connect(lambda: self.set_minimized(True))
        self._hint(mini, "<b>Minimise</b> to one line: objective, time on it, location")
        head.addWidget(mini)
        self.menu_btn = QPushButton("⋯", objectName="OverlayIcon")
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu_btn.setCheckable(True)
        self.menu_btn.setFixedSize(30, 30)
        self.menu_btn.toggled.connect(self._show_menu)
        self._hint(self.menu_btn, "<b>More</b>: background opacity, hide, settings")
        head.addWidget(self.menu_btn)
        v.addWidget(self.header)

        # The status line: the click-through state, or what the pointer is on.
        self.status = QLabel("", objectName="OverlayStatus")
        self.status.setTextFormat(Qt.RichText)
        v.addWidget(self.status)
        self._update_status()

        # Minimised: one line.
        self.mini_bar = _MinimisedBar(self)
        self.mini_bar.expand.connect(lambda: self.set_minimized(False))
        self.mini_bar.hide()
        v.addWidget(self.mini_bar)

        # ⋯ menu: drawn inside the overlay (a QMenu would be its own popup window).
        self.menu = _InlineMenu(self)
        self.menu.hide()

        self.stack = QStackedWidget()
        v.addWidget(self.stack, stretch=1)
        self.size_grip = _ResizeGrip(self)
        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        grip_row.addWidget(self.size_grip)
        v.addLayout(grip_row)
        # Takes the slack when the panel is closed (e.g. the window grew for the ⋯ menu).
        v.addStretch(0)

    # -- tools ------------------------------------------------------------------------
    def select_tool(self, tool: str, force: bool = False) -> None:
        """Opens a tool's panel; picking the open one again collapses to the
        bar (unless `force`: keys 1–5 always open)."""
        if self.minimized:
            self.set_minimized(False)
        self._show_menu(False)
        if tool == self.tool:
            if not force:
                self._collapse()
            return
        if self.tool:
            self._remember_size()
        size = self.state.get("sizes", {}).get(tool)
        self._resizing = True   # constraint changes below resize; don't record those
        self.tool = tool
        if tool not in self._panels:
            panel = self._make_panel(tool)
            self._panels[tool] = panel
            self.stack.addWidget(panel)
        self.stack.setCurrentWidget(self._panels[tool])
        self.stack.setVisible(True)
        self.size_grip.setVisible(True)
        # Never narrower than the bar, or its buttons get cut off.
        min_width = max(BAR_MIN_WIDTH, self._bar_width)
        self.setMinimumSize(min_width, 300)
        self.setMaximumSize(16777215, 16777215)
        size = QSize(*size) if size else TOOLS[tool][2]
        self.resize(max(size.width(), min_width), size.height())
        self._resizing = False
        self._sync_buttons()
        activate = getattr(self._panels[tool], "activate", None)
        if activate:
            activate()

    def reload_game_data(self) -> None:
        """The launcher has read a new game version: panels built on game
        data load it again (now, if showing; else when next opened)."""
        for tool, attr in (("mining", "data"), ("salvage", "game")):
            panel = self._panels.get(tool)
            if panel is not None and hasattr(panel, attr):
                setattr(panel, attr, None)
                if self.tool == tool and self.stack.isVisible():
                    panel.activate()

    def fit_height(self, tool: str, content_height: int) -> None:
        """Called by auto-height panels after each render: the window grows or
        shrinks to show all of `content_height`, up to AUTO_HEIGHT_MAX of the
        screen (the panel scrolls beyond that)."""
        if tool != self.tool or tool not in AUTO_HEIGHT_TOOLS or tool not in self._panels:
            return
        panel = self._panels[tool]
        chrome = self.height() - panel.height()          # header, margins, grip
        limit = int(self.screen().availableGeometry().height() * AUTO_HEIGHT_MAX)
        target = max(self.minimumHeight(), min(chrome + content_height, limit))
        if abs(target - self.height()) > 2:
            self._resizing = True
            self.resize(self.width(), target)
            self._resizing = False

    def _make_panel(self, tool: str) -> QWidget:
        from app.ui import overlay_live, overlay_panels

        return {
            "missions": overlay_live.MissionsPanel,
            "session": overlay_live.SessionPanel,
            "maps": overlay_panels.MapsPanel,
            "mining": overlay_panels.MiningPanel,
            "salvage": overlay_panels.SalvagePanel,
        }[tool]()

    def collapse(self) -> None:
        self._collapse()

    def _collapse(self) -> None:
        if self.tool:
            self._remember_size()
        self.tool = None
        self.stack.setVisible(False)
        self.size_grip.setVisible(False)
        self._sync_buttons()
        self._fit_bar()

    def _fit_bar(self) -> None:
        """Collapsed (or minimised) size: as wide as the bar needs, as tall
        as its content."""
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.layout().activate()
        self.adjustSize()
        hint = self.sizeHint()
        width = hint.width() if self.minimized else max(hint.width(), BAR_MIN_WIDTH)
        if not self.minimized:
            self._bar_width = width
        self.setFixedSize(width, hint.height())
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.resize(width, hint.height())

    def set_minimized(self, on: bool) -> None:
        """One line (#53): the current objective, time on it, location."""
        if on == self.minimized:
            return
        self._show_menu(False)
        if on and self.tool:
            self._remember_size()
        self.minimized = on
        self.header.setVisible(not on)
        self.status.setVisible(not on)
        self.mini_bar.setVisible(on)
        if on:
            self.mini_bar.start()
            self.stack.setVisible(False)
            self.size_grip.setVisible(False)
            self._fit_bar()
        else:
            self.mini_bar.stop()
            tool, self.tool = self.tool, None
            if tool:
                self.select_tool(tool)
            else:
                self._collapse()
        self.state["minimized"] = on
        self._save_timer.start()

    def _escape(self) -> None:
        if self.menu.isVisible():
            self._show_menu(False)
        elif self.tool:
            self._collapse()

    # -- the status line and the ⋯ menu --------------------------------------------------
    def _hint(self, widget: QWidget, text) -> None:
        """What the status line says while the pointer is on `widget`."""
        widget.setProperty("hint", text if isinstance(text, str) else "")
        widget._hint_fn = text if callable(text) else None
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter and (obj.property("hint") or getattr(obj, "_hint_fn", None)):
            fn = getattr(obj, "_hint_fn", None)
            self.status.setText(fn() if fn else obj.property("hint"))
        elif event.type() == QEvent.Leave and (obj.property("hint") or getattr(obj, "_hint_fn", None)):
            self._update_status()
        return super().eventFilter(obj, event)

    def _update_status(self) -> None:
        key = hotkey_label("toggle-clickthrough")
        if self.click_through:
            self.status.setText(f"Click-through <b>on</b> · clicks go to the game · <kbd>{key}</kbd> "
                                "to use the overlay")
        else:
            self.status.setText(f"Click-through <b>off</b> · the overlay takes clicks · <kbd>{key}</kbd>")
        self.ct_dot.set_on(not self.click_through)

    def _show_menu(self, on: bool) -> None:
        if not hasattr(self, "menu"):
            return
        if on:
            self.menu.sync()
            self.menu.adjustSize()
            pos = self.menu_btn.mapTo(self, self.menu_btn.rect().bottomRight())
            x = max(4, pos.x() - self.menu.width())
            self.menu.move(x, pos.y() + 4)
            self.menu.show()
            self.menu.raise_()
            # Short bar (collapsed): the window grows so the menu fits inside it.
            need = self.menu.geometry().bottom() + 8
            if self.height() < need:
                self._menu_grew = self.height()
                self.setMinimumHeight(need)
                self.resize(self.width(), need)
        else:
            self.menu.hide()
            grew = getattr(self, "_menu_grew", None)
            if grew is not None:
                self._menu_grew = None
                if self.tool is None:
                    self._fit_bar()
        if self.menu_btn.isChecked() != on:
            self.menu_btn.blockSignals(True)
            self.menu_btn.setChecked(on)
            self.menu_btn.blockSignals(False)

    def _sync_buttons(self) -> None:
        for btn in self.tool_group.buttons():
            btn.setChecked(btn.property("tool") == self.tool)

    # -- visibility / click-through ------------------------------------------------------
    def toggle(self) -> None:
        if self.is_shown():
            self.hide_overlay()
        else:
            self.show_overlay()

    def show_overlay(self) -> None:
        """Shows it with the mouse and keyboard (the game lets go of the
        pointer once it loses focus); in click-through mode it's shown
        without taking focus, so the game keeps it."""
        pos = self.state.get(self._pos_key)
        if pos:
            self._anchor = QPoint(*pos)
        if self._host is not None:
            self.show()
            if self._anchor is not None:
                self.move(self._anchor)
            self._host.present(passive=self.click_through)
            self.keep_inside()
            return
        self.show()
        self.raise_()
        if self._anchor is not None:
            self.move(self._anchor)
        self._update_shield()
        if not self.click_through:
            self.activateWindow()
            # Once mapped: an activation request for an unmapped window can get lost.
            QTimer.singleShot(150, lambda: self.isVisible() and not self.click_through
                              and self.activateWindow())

    def showEvent(self, event):
        if QApplication.platformName() == "xcb":
            # Before the native window is mapped (and again whenever changing
            # the click-through flag re-created it).
            _set_osd_type(int(self.winId()))
        super().showEvent(event)
        if QApplication.platformName() == "xcb":
            QTimer.singleShot(0, lambda: _skip_taskbar(int(self.winId())))

    def _update_shield(self) -> None:
        """Shield under the overlay while it takes the mouse; none in click-through.
        (X11 only: the layer-shell surface is its own shield.)"""
        if self._host is None and self.isVisible() and not self.click_through:
            if self._shield is None:
                self._shield = _InputShield(
                    f"SC-Toolbox overlay has the mouse  ·  {hotkey_label('toggle-clickthrough')} "
                    f"gives it back to the game  ·  {hotkey_label('toggle-overlay')} hides the overlay", self)
            self._shield.cover(self.screen())
            self._shield.set_hole(self.frameGeometry())
            self.raise_()   # the overlay stays above its shield
        elif self._shield is not None:
            self._shield.hide()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._shield is not None:
            self._shield.hide()

    def toggle_click_through(self) -> None:
        if self._host is not None:
            self.click_through = not self.click_through
            self.frame.setProperty("clickThrough", self.click_through)
            self.frame.style().unpolish(self.frame)
            self.frame.style().polish(self.frame)
            self._update_status()
            self.show_overlay()        # click-through shows it too, like on X11
            return
        self.click_through = not self.click_through
        visible = self.isVisible()
        # Changing window flags re-creates the native window; show it again.
        self.setWindowFlag(Qt.WindowTransparentForInput, self.click_through)
        self.frame.setProperty("clickThrough", self.click_through)
        self.frame.style().unpolish(self.frame)
        self.frame.style().polish(self.frame)
        self._update_status()
        if visible or self.click_through:
            self.show_overlay()
        if self.tool is None:
            self._fit_bar()

    # -- persistence ------------------------------------------------------------------------
    def set_opacity(self, value: int) -> None:
        self._on_opacity(max(MIN_OPACITY, min(MAX_OPACITY, value)))

    def _on_opacity(self, value: int) -> None:
        self._apply_opacity(value)
        self.state["opacity"] = value
        self._save_timer.start()

    def _remember_size(self) -> None:
        if self.tool:
            sizes = self.state.setdefault("sizes", {})
            height = self.height()
            if self.tool in AUTO_HEIGHT_TOOLS:   # its height follows the content
                height = TOOLS[self.tool][2].height()
            sizes[self.tool] = [self.width(), height]
            self._save_timer.start()

    def moveEvent(self, event):
        # KWin places an OSD itself (bottom centre) when it's mapped and
        # whenever its size changes; any move the overlay didn't make is undone.
        super().moveEvent(event)
        if self._anchor is not None and self.pos() != self._anchor:
            self.move(self._anchor)
            return
        self._sync_hole()
        self.state[self._pos_key] = [self.x(), self.y()]
        self._save_timer.start()

    def _sync_hole(self) -> None:
        if self._shield is not None and self._shield.isVisible():
            self._shield.set_hole(self.frameGeometry())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_hole()
        if self.tool and not self._resizing:
            self._remember_size()

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self.state, indent=2))
        except OSError:
            pass

    # -- dragging -------------------------------------------------------------------------------
    # Moved by the app itself, not the window manager: KWin doesn't move OSDs.
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.header.geometry().contains(
                self.frame.mapFrom(self, event.position().toPoint())):
            self._drag = event.globalPosition().toPoint() - self.pos()
            if self._host is not None:   # surface coordinates (Wayland has no global ones)
                self._drag = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_drag", None) is not None:
            if self._host is not None:
                self._anchor = self.mapToParent(event.position().toPoint()) - self._drag
            else:
                self._anchor = event.globalPosition().toPoint() - self._drag
            self.move(self._anchor)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_drag", None) is not None:
            self._drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _NoToolTips(QObject):
    """Swallows every tooltip in the overlay process. Over the game they're
    in the way, and on the layer-shell surface each one is a popup window
    that opens and closes (the user saw it as constant flicker)."""

    def eventFilter(self, obj, event):
        return event.type() == QEvent.ToolTip


def _live_feed():
    from app.ui import overlay_live

    return overlay_live.feed()


def run(parent_pid: int | None, layer_shell: bool = False) -> int:
    """Entry point of the overlay process (`sc-toolkit --overlay`)."""
    from app.theme import build_stylesheet

    app = QApplication(sys.argv)
    app.setApplicationName(config.DISPLAY_NAME + " overlay")
    from app import __version__, settings
    print(f"overlay: SC-Toolbox {__version__} on {sys.platform} ({QApplication.platformName()}), "
          f"settings {settings.SETTINGS_FILE} (game folder: {settings.current().live_dir or 'not set'})",
          file=sys.stderr, flush=True)
    app.setQuitOnLastWindowClosed(False)   # hidden overlay keeps running for the hotkeys
    app.setStyleSheet(build_stylesheet())
    no_tooltips = _NoToolTips(app)
    app.installEventFilter(no_tooltips)
    host = None
    if layer_shell:
        from app.ui.layer_overlay import LayerHost

        host = LayerHost(f"SC-Toolbox overlay has the mouse  ·  {hotkey_label('toggle-clickthrough')} "
                         f"gives it back to the game  ·  {hotkey_label('toggle-overlay')} hides the overlay")
        print("overlay: layer-shell surface (KDE Wayland)", file=sys.stderr, flush=True)
    overlay = OverlayWindow(host=host)

    server = ipc.CommandServer(ipc.OVERLAY)
    if not server.listen():
        return 0   # another overlay process already runs
    actions = {
        "toggle": overlay.toggle,
        "toggle-overlay": overlay.toggle,
        "show": overlay.show_overlay,
        "hide": overlay.hide_overlay,
        "toggle-clickthrough": overlay.toggle_click_through,
        "live-log-on": lambda: _live_feed().set_enabled(True),
        "live-log-off": lambda: _live_feed().set_enabled(False),
        "game-data-updated": lambda: (overlay.reload_game_data(), _live_feed().reload_lookups()),
        "quit": app.quit,
    }
    server.command.connect(lambda cmd: actions.get(cmd, lambda: None)())

    hotkeys = GlobalHotkeys()
    hotkeys.pressed.connect(lambda action: actions.get(action, lambda: None)())
    if not hotkeys.start():
        print(f"overlay: global hotkeys unavailable: {hotkeys.error}", file=sys.stderr)

    if parent_pid:
        # Quit together with the launcher, even if it crashed.
        watchdog = QTimer(interval=2000)
        watchdog.timeout.connect(lambda: psutil.pid_exists(parent_pid) or app.quit())
        watchdog.start()

    code = app.exec()
    hotkeys.stop()
    return code
