"""The in-game overlay: a small always-on-top window that floats over Star
Citizen (borderless windowed mode). It never touches the game process, so
it's anti-cheat safe.

It runs as its own process (`sc-toolkit --overlay`), started by the main
app: on Linux it runs on XWayland (xcb), because Wayland doesn't let a
window keep itself on top of others and doesn't allow global hotkeys,
while X11 windows can do both over the (also XWayland) game. The main
launcher stays native Wayland.

Layout: a slim header ("minimised menu") with the tool buttons, opacity
slider and click-through toggle. Picking a tool expands its compact panel
underneath; picking it again collapses back to the header. Position,
opacity and each tool's size are remembered.
"""

from __future__ import annotations

import json
import sys

import psutil
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import config, ipc
from app.hotkeys import GlobalHotkeys, label as hotkey_label

STATE_FILE = config.USER_CONFIG_DIR / "overlay.json"

# tool id -> (button label, default panel size)
TOOLS = {
    "maps": ("Maps", QSize(560, 640)),
    "mining": ("Mining", QSize(480, 640)),
    "salvage": ("Salvage", QSize(480, 620)),
}
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
    """Resizes the window itself: KWin doesn't resize OSD windows."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            win = self.window()
            self._start = (event.globalPosition().toPoint(), win.size())
            event.accept()

    def mouseMoveEvent(self, event):
        start = getattr(self, "_start", None)
        if start is None:
            return
        win = self.window()
        delta = event.globalPosition().toPoint() - start[0]
        minimum = win.minimumSizeHint()
        win.resize(max(minimum.width(), start[1].width() + delta.x()),
                   max(minimum.height(), start[1].height() + delta.y()))
        event.accept()

    def mouseReleaseEvent(self, event):
        self._start = None
        event.accept()


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
        self.setWindowTitle("SC-Toolkit overlay shield")

    def cover(self, screen) -> None:
        self._target = screen.geometry()
        self.setGeometry(self._target)
        self.show()

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


class OverlayWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SC-Toolkit overlay")
        self.setWindowIcon(QIcon(str(config.APP_ICON)))
        # Not Qt.Tool on X11: that makes a "utility" window, which KWin hides
        # whenever its app isn't active, i.e. as soon as the game has focus.
        # The taskbar entry is dropped by _skip_taskbar() instead.
        kind = Qt.Window if sys.platform.startswith("linux") else Qt.Tool
        self.setWindowFlags(kind | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Showing it must not take focus from the game; click it to type.
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.state = _load_state()
        self.tool: str | None = None
        self.click_through = False
        self._anchor: QPoint | None = None   # where the overlay belongs (see moveEvent)
        self._shield: _InputShield | None = None
        self._resizing = False
        self._panels: dict[str, QWidget] = {}
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_state)
        self._build_ui()
        self.setWindowOpacity(self.state.get("opacity", 92) / 100)
        pos = self.state.get("pos")
        if pos:
            self._anchor = QPoint(*pos)
            self.move(self._anchor)
        self._collapse()

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
        head.setContentsMargins(4, 0, 0, 0)
        head.setSpacing(6)
        grip = QLabel("⠿", objectName="OverlayGrip")
        grip.setToolTip("Drag to move")
        head.addWidget(grip)
        head.addWidget(QLabel("SC-TOOLKIT", objectName="OverlayTitle"))
        head.addSpacing(4)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(False)
        for tool, (label, _size) in TOOLS.items():
            btn = QPushButton(label, objectName="OverlayTool")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, t=tool: self.select_tool(t))
            self.tool_group.addButton(btn)
            btn.setProperty("tool", tool)
            head.addWidget(btn)
        head.addStretch(1)
        self.opacity = QSlider(Qt.Horizontal, objectName="OverlayOpacity")
        self.opacity.setRange(MIN_OPACITY, MAX_OPACITY)
        self.opacity.setValue(self.state.get("opacity", 92))
        self.opacity.setFixedWidth(70)
        self.opacity.setToolTip("Opacity")
        self.opacity.valueChanged.connect(self._on_opacity)
        head.addWidget(self.opacity)
        self.ct_btn = QPushButton("⇲", objectName="OverlayIcon")
        self.ct_btn.setToolTip(f"Click-through: clicks go to the game ({hotkey_label('toggle-clickthrough')})")
        self.ct_btn.setCursor(Qt.PointingHandCursor)
        self.ct_btn.clicked.connect(self.toggle_click_through)
        head.addWidget(self.ct_btn)
        hide = QPushButton("✕", objectName="OverlayIcon")
        hide.setToolTip(f"Hide overlay ({hotkey_label('toggle-overlay')})")
        hide.setCursor(Qt.PointingHandCursor)
        hide.clicked.connect(self.hide)
        head.addWidget(hide)
        v.addWidget(self.header)

        self.ct_banner = QLabel(
            f"CLICK-THROUGH: clicks go to the game · {hotkey_label('toggle-clickthrough')} to use the overlay again",
            objectName="OverlayBanner",
        )
        self.ct_banner.setVisible(False)
        v.addWidget(self.ct_banner)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, stretch=1)
        self.size_grip = _ResizeGrip(self)
        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        grip_row.addWidget(self.size_grip)
        v.addLayout(grip_row)

    # -- tools ------------------------------------------------------------------------
    def select_tool(self, tool: str) -> None:
        if tool == self.tool:
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
        self.setMinimumSize(360, 300)
        self.setMaximumSize(16777215, 16777215)
        self.resize(QSize(*size) if size else TOOLS[tool][1])
        self._resizing = False
        self._sync_buttons()
        activate = getattr(self._panels[tool], "activate", None)
        if activate:
            activate()

    def _make_panel(self, tool: str) -> QWidget:
        from app.ui import overlay_panels

        return {
            "maps": overlay_panels.MapsPanel,
            "mining": overlay_panels.MiningPanel,
            "salvage": overlay_panels.SalvagePanel,
        }[tool]()

    def _collapse(self) -> None:
        if self.tool:
            self._remember_size()
        self.tool = None
        self.stack.setVisible(False)
        self.size_grip.setVisible(False)
        self._sync_buttons()
        self.setMinimumSize(0, 0)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())
        self.setMaximumWidth(16777215)
        self.resize(max(self.sizeHint().width(), 440), self.sizeHint().height())

    def _sync_buttons(self) -> None:
        for btn in self.tool_group.buttons():
            btn.setChecked(btn.property("tool") == self.tool)

    # -- visibility / click-through ------------------------------------------------------
    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_overlay()

    def show_overlay(self) -> None:
        """Shows it with the mouse and keyboard (the game lets go of the
        pointer once it loses focus); in click-through mode it's shown
        without taking focus, so the game keeps it."""
        pos = self.state.get("pos")
        if pos:
            self._anchor = QPoint(*pos)
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
        """Shield under the overlay while it takes the mouse; none in click-through."""
        if self.isVisible() and not self.click_through:
            if self._shield is None:
                self._shield = _InputShield(
                    f"SC-Toolkit overlay has the mouse  ·  {hotkey_label('toggle-clickthrough')} "
                    f"gives it back to the game  ·  {hotkey_label('toggle-overlay')} hides the overlay", self)
            self._shield.cover(self.screen())
            self.raise_()   # the overlay stays above its shield
        elif self._shield is not None:
            self._shield.hide()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._shield is not None:
            self._shield.hide()

    def toggle_click_through(self) -> None:
        self.click_through = not self.click_through
        visible = self.isVisible()
        # Changing window flags re-creates the native window; show it again.
        self.setWindowFlag(Qt.WindowTransparentForInput, self.click_through)
        self.frame.setProperty("clickThrough", self.click_through)
        self.frame.style().unpolish(self.frame)
        self.frame.style().polish(self.frame)
        self.ct_banner.setVisible(self.click_through)
        if visible or self.click_through:
            self.show_overlay()

    # -- persistence ------------------------------------------------------------------------
    def _on_opacity(self, value: int) -> None:
        self.setWindowOpacity(value / 100)
        self.state["opacity"] = value
        self._save_timer.start()

    def _remember_size(self) -> None:
        if self.tool:
            self.state.setdefault("sizes", {})[self.tool] = [self.width(), self.height()]
            self._save_timer.start()

    def moveEvent(self, event):
        # KWin places an OSD itself (bottom centre) when it's mapped and
        # whenever its size changes; any move the overlay didn't make is undone.
        super().moveEvent(event)
        if self._anchor is not None and self.pos() != self._anchor:
            self.move(self._anchor)
            return
        self.state["pos"] = [self.x(), self.y()]
        self._save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
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
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_drag", None) is not None:
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


def run(parent_pid: int | None) -> int:
    """Entry point of the overlay process (`sc-toolkit --overlay`)."""
    from app.theme import build_stylesheet

    app = QApplication(sys.argv)
    app.setApplicationName(config.DISPLAY_NAME + " overlay")
    app.setQuitOnLastWindowClosed(False)   # hidden overlay keeps running for the hotkeys
    app.setStyleSheet(build_stylesheet())
    overlay = OverlayWindow()

    server = ipc.CommandServer(ipc.OVERLAY)
    if not server.listen():
        return 0   # another overlay process already runs
    actions = {
        "toggle": overlay.toggle,
        "toggle-overlay": overlay.toggle,
        "show": overlay.show_overlay,
        "hide": overlay.hide,
        "toggle-clickthrough": overlay.toggle_click_through,
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
