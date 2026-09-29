"""System-wide hotkeys for the overlay: show/hide (default F7) and
click-through (default F8), configurable in Settings. They must work while
the game has focus, so they're registered with the OS, not Qt:

- **Windows:** `RegisterHotKey` on the GUI thread; WM_HOTKEY arrives through
  a Qt native event filter.
- **KDE Plasma (Wayland or X11):** a global shortcut registered with
  KGlobalAccel over D-Bus. KWin catches the key whatever window is focused
  (Star Citizen under Wine's Wayland driver is a native Wayland window) and
  keeps it from the game. Released (set inactive) when the overlay stops.
- **Other Linux desktops:** an X11 key grab on the root window (own Xlib
  connection, own thread). It only sees keys while an X11/XWayland window
  has focus; the `sc-toolkit --toggle-overlay` command (bind it to a desktop
  shortcut) is the fallback.

`GlobalHotkeys.pressed(action)` is emitted on the GUI thread.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import select
import sys
import threading

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal

ACTIONS = {
    "toggle-overlay": ("hotkey_overlay", "Show / hide the overlay"),
    "toggle-clickthrough": ("hotkey_clickthrough", "Overlay click-through"),
}
MODIFIERS = ("Ctrl", "Shift", "Alt", "Meta")   # Meta = the Windows / Super key
FKEYS = [f"F{n}" for n in range(1, 13)]
# Keys nobody types with: allowed on their own, like the F-keys.
# Names as QKeySequence.PortableText writes them.
NAV_KEYS = ["Ins", "Home", "End", "PgUp", "PgDown", "Pause", "ScrollLock"]
KEYS = ([chr(c) for c in range(ord("A"), ord("Z") + 1)] + [str(d) for d in range(10)]
        + FKEYS + NAV_KEYS)
_KEY_ALIASES = {
    "insert": "Ins", "pageup": "PgUp", "pgup": "PgUp", "pagedown": "PgDown", "pgdown": "PgDown",
    "pgdn": "PgDown", "scrolllock": "ScrollLock", "scroll": "ScrollLock", "break": "Pause",
    **{k.lower(): k for k in NAV_KEYS + FKEYS},
}
_MOD_ALIASES = {"control": "Ctrl", "ctrl": "Ctrl", "win": "Meta", "super": "Meta", "meta": "Meta",
                "shift": "Shift", "alt": "Alt"}


def parse(text: str) -> tuple[frozenset[str], str]:
    """'Ctrl+Shift+O' -> ({'Ctrl', 'Shift'}, 'O'). ValueError says what's wrong."""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        raise ValueError("Not set")
    *mods, key = parts
    if key.lower() in _MOD_ALIASES:
        raise ValueError("Finish with a key, not a modifier")
    unknown = [m for m in mods if m.lower() not in _MOD_ALIASES]
    if unknown:
        raise ValueError(f"Unknown modifier: {', '.join(sorted(unknown))}")
    mods = {_MOD_ALIASES[m.lower()] for m in mods}
    key = _KEY_ALIASES.get(key.lower(), key.upper())
    if key not in KEYS:
        raise ValueError("Use an F-key, a letter or digit, or Insert/Home/End/Page Up/Page Down/"
                         "Pause/Scroll Lock")
    if len(key) == 1 and not mods & {"Ctrl", "Alt", "Meta"}:
        # A bare or Shift-only letter/digit would be taken away from typing.
        raise ValueError("Letters and digits need Ctrl, Alt or Meta")
    if {"Ctrl", "Alt"} <= mods and key in FKEYS:
        # Linux keeps these for switching to a text console.
        raise ValueError("Ctrl+Alt+F-keys are reserved by the system")
    return frozenset(mods), key


def format_combo(mods, key: str) -> str:
    return "+".join([m for m in MODIFIERS if m in mods] + [key])


def configured() -> dict[str, str]:
    """action -> combo text from Settings; defaults where a value is invalid."""
    from dataclasses import fields

    from app import settings

    current = settings.current()
    defaults = {f.name: f.default for f in fields(settings.Settings)}
    out = {}
    for action, (field, _title) in ACTIONS.items():
        try:
            out[action] = format_combo(*parse(getattr(current, field)))
        except ValueError:
            out[action] = defaults[field]
    return out


def label(action: str) -> str:
    return configured()[action]


def release() -> None:
    """Frees the keys held for the overlay, e.g. after the overlay process
    died without doing so itself. Only KDE keeps them registered."""
    if sys.platform.startswith("linux") and _KDEHotkeys.available():
        try:
            _KDEHotkeys.deactivate_all()
        except Exception:
            pass


class GlobalHotkeys(QObject):
    pressed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self.error = ""

    def start(self) -> bool:
        combos = {action: parse(text) for action, text in configured().items()}
        try:
            if sys.platform.startswith("win"):
                self._backend = _WindowsHotkeys(self.pressed.emit, combos)
            elif _KDEHotkeys.available():
                self._backend = _KDEHotkeys(self.pressed.emit, combos)
            else:
                self._backend = _X11Hotkeys(self.pressed.emit, combos)
            self._backend.start()
            return True
        except Exception as exc:  # no X server, key already grabbed, …
            self.error = str(exc)
            self._backend = None
            return False

    def stop(self) -> None:
        if self._backend is not None:
            self._backend.stop()
            self._backend = None


# -- Windows --------------------------------------------------------------------

class _WindowsHotkeys(QAbstractNativeEventFilter):
    MODS = {"Alt": 0x0001, "Ctrl": 0x0002, "Shift": 0x0004, "Meta": 0x0008}
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312

    def __init__(self, emit, combos):
        super().__init__()
        from ctypes import wintypes

        self._wintypes = wintypes
        self._user32 = ctypes.windll.user32
        self._emit = emit
        self._combos = combos
        self._ids: dict[int, str] = {}

    NAV_VK = {"Ins": 0x2D, "Home": 0x24, "End": 0x23, "PgUp": 0x21, "PgDown": 0x22,
              "Pause": 0x13, "ScrollLock": 0x91}

    @classmethod
    def _vk(cls, key: str) -> int:
        if key in FKEYS:
            return 0x6F + int(key[1:])
        return cls.NAV_VK.get(key) or ord(key)

    def start(self) -> None:
        for i, (action, (mods, key)) in enumerate(self._combos.items(), start=1):
            flags = self.MOD_NOREPEAT
            for m in mods:
                flags |= self.MODS[m]
            if not self._user32.RegisterHotKey(None, i, flags, self._vk(key)):
                self.stop()
                raise OSError(f"{format_combo(mods, key)} is already used by another program")
            self._ids[i] = action
        QCoreApplication.instance().installNativeEventFilter(self)

    def stop(self) -> None:
        QCoreApplication.instance().removeNativeEventFilter(self)
        for i in self._ids:
            self._user32.UnregisterHotKey(None, i)
        self._ids.clear()

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = self._wintypes.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and msg.wParam in self._ids:
                self._emit(self._ids[msg.wParam])
                return True, 0
        return False, 0


# -- Linux / X11 ----------------------------------------------------------------------

class _XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong), ("x", ctypes.c_int),
        ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint), ("keycode", ctypes.c_uint), ("same_screen", ctypes.c_int),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", _XKeyEvent), ("pad", ctypes.c_long * 24)]


class _X11Hotkeys:
    LOCK, MOD2 = 1 << 1, 1 << 4   # CapsLock, NumLock: ignored
    MODS = {"Shift": 1 << 0, "Ctrl": 1 << 2, "Alt": 1 << 3, "Meta": 1 << 6}   # Alt = Mod1, Meta = Mod4
    KEY_PRESS, GRAB_ASYNC = 2, 1

    def __init__(self, emit, combos):
        path = ctypes.util.find_library("X11") or "libX11.so.6"
        x = self._x = ctypes.CDLL(path)
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XStringToKeysym.restype = ctypes.c_ulong
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int]
        x.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        x.XPending.argtypes = [ctypes.c_void_p]
        x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(_XEvent)]
        x.XConnectionNumber.argtypes = [ctypes.c_void_p]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self._emit = emit
        self._combos = combos
        self._dpy = None
        self._keys: dict[tuple[int, int], str] = {}   # (keycode, modifier mask) -> action
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors: list[int] = []
        # Keep a reference: Xlib calls this on BadAccess (combo grabbed elsewhere).
        handler_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self._handler = handler_type(lambda _d, _e: self._errors.append(1) or 0)

    NAV_KEYSYMS = {"Ins": "Insert", "PgUp": "Prior", "PgDown": "Next", "ScrollLock": "Scroll_Lock"}

    @classmethod
    def _keysym(cls, key: str) -> str:
        if key in FKEYS or key in NAV_KEYS:
            return cls.NAV_KEYSYMS.get(key, key)
        return key.lower()

    def start(self) -> None:
        x = self._x
        self._dpy = x.XOpenDisplay(None)
        if not self._dpy:
            raise OSError("No X11 display (XWayland) available for global hotkeys")
        x.XSetErrorHandler(self._handler)
        root = x.XDefaultRootWindow(self._dpy)
        for action, (mods, key) in self._combos.items():
            code = x.XKeysymToKeycode(self._dpy, x.XStringToKeysym(self._keysym(key).encode()))
            mask = 0
            for m in mods:
                mask |= self.MODS[m]
            self._keys[(code, mask)] = action
            for extra in (0, self.LOCK, self.MOD2, self.LOCK | self.MOD2):
                x.XGrabKey(self._dpy, code, mask | extra, root, True, self.GRAB_ASYNC, self.GRAB_ASYNC)
        x.XSync(self._dpy, False)
        if self._errors:
            taken = ", ".join(format_combo(*c) for c in self._combos.values())
            self.stop()
            raise OSError(f"{taken}: already grabbed by another program")
        self._root = root
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        x, fd = self._x, self._x.XConnectionNumber(self._dpy)
        event = _XEvent()
        while not self._stop.is_set():
            select.select([fd], [], [], 0.25)
            while not self._stop.is_set() and x.XPending(self._dpy):
                x.XNextEvent(self._dpy, ctypes.byref(event))
                if event.type == self.KEY_PRESS:
                    state = event.xkey.state & ~(self.LOCK | self.MOD2) & 0xFF
                    action = self._keys.get((event.xkey.keycode, state))
                    if action:
                        self._emit(action)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._dpy:
            for code, mask in self._keys:
                for extra in (0, self.LOCK, self.MOD2, self.LOCK | self.MOD2):
                    self._x.XUngrabKey(self._dpy, code, mask | extra,
                                       self._x.XDefaultRootWindow(self._dpy))
            self._x.XCloseDisplay(self._dpy)
            self._dpy = None


# -- KDE Plasma: KGlobalAccel ------------------------------------------------------------

class _KDEHotkeys:
    """Global shortcuts through KDE's kglobalaccel D-Bus service. jeepney
    does the calls (QtDBus can't send the `ai` key lists it expects); a
    thread waits for `globalShortcutPressed`."""

    SERVICE = "org.kde.kglobalaccel"
    COMPONENT = "sc-toolkit"
    FRIENDLY = "SC-Toolkit"
    SET_PRESENT, NO_AUTOLOADING = 2, 4

    def __init__(self, emit, combos):
        self._emit = emit
        self._combos = combos
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn = None

    @classmethod
    def available(cls) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        try:
            from jeepney import DBusAddress, new_method_call
            from jeepney.io.blocking import open_dbus_connection

            with open_dbus_connection(bus="SESSION") as conn:
                bus = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus",
                                  interface="org.freedesktop.DBus")
                reply = conn.send_and_get_reply(
                    new_method_call(bus, "NameHasOwner", "s", (cls.SERVICE,)), timeout=2)
                return bool(reply.body[0])
        except Exception:
            return False

    @classmethod
    def _action_id(cls, action: str) -> list[str]:
        return [cls.COMPONENT, action, cls.FRIENDLY, ACTIONS[action][1]]

    @classmethod
    def _call(cls, conn, method: str, signature: str, *args):
        from jeepney import DBusAddress, MessageType, new_method_call

        address = DBusAddress("/kglobalaccel", bus_name=cls.SERVICE, interface="org.kde.KGlobalAccel")
        reply = conn.send_and_get_reply(new_method_call(address, method, signature, args), timeout=3)
        if reply.header.message_type == MessageType.error:
            raise OSError(f"kglobalaccel {method}: {reply.body[0] if reply.body else 'error'}")
        return reply.body

    @classmethod
    def deactivate_all(cls) -> None:
        from jeepney.io.blocking import open_dbus_connection

        with open_dbus_connection(bus="SESSION") as conn:
            for action in ACTIONS:
                cls._call(conn, "setInactive", "as", cls._action_id(action))

    @staticmethod
    def _qt_key(mods, key: str) -> int:
        from PySide6.QtGui import QKeySequence

        return QKeySequence.fromString(format_combo(mods, key), QKeySequence.PortableText)[0].toCombined()

    def start(self) -> None:
        from jeepney.bus_messages import MatchRule, message_bus
        from jeepney.io.blocking import open_dbus_connection

        self._conn = conn = open_dbus_connection(bus="SESSION")
        taken = []
        for action, (mods, key) in self._combos.items():
            action_id = self._action_id(action)
            self._call(conn, "doRegister", "as", action_id)
            wanted = self._qt_key(mods, key)
            (assigned,) = self._call(conn, "setShortcut", "asaiu", action_id, [wanted],
                                     self.SET_PRESENT | self.NO_AUTOLOADING)
            if wanted not in assigned:
                taken.append(format_combo(mods, key))
        if taken:
            self.stop()
            raise OSError(f"{', '.join(taken)}: already used by another shortcut "
                          "(System Settings → Keyboard → Shortcuts)")
        (path,) = self._call(conn, "getComponent", "s", self.COMPONENT)
        self._rule = MatchRule(type="signal", interface="org.kde.kglobalaccel.Component",
                               member="globalShortcutPressed", path=path)
        conn.send_and_get_reply(message_bus.AddMatch(self._rule), timeout=3)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        with self._conn.filter(self._rule) as queue:
            while not self._stop.is_set():
                try:
                    msg = self._conn.recv_until_filtered(queue, timeout=0.25)
                except TimeoutError:
                    continue
                except Exception:
                    return
                component, action = msg.body[0], msg.body[1]
                if component == self.COMPONENT and action in ACTIONS:
                    self._emit(action)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        if self._conn is not None:
            try:
                # Inactive: KWin stops catching the keys, so they reach the game again.
                for action in self._combos:
                    self._call(self._conn, "setInactive", "as", self._action_id(action))
            except Exception:
                pass
            self._conn.close()
            self._conn = None
