"""Live joystick input, reported in Star Citizen's own input names — the
same on Windows and Linux, through SDL2 (bundled by the pysdl2-dll package).

Numbering matches the game:
- **Buttons**: SDL reads DirectInput on Windows (RawInput and HIDAPI are
  turned off, so nothing reorders) and evdev on Linux in joydev order —
  both are HID usage order, so SDL button i is the game's `button{i+1}`.
- **Hats**: SDL hat n is the game's `hat{n+1}`; each held direction is
  reported as its own input (`hat1_up`, …), diagonals as two.
- **Axes**: SDL doesn't say *which* axis an index is, only that present
  axes come in the standard order X, Y, Z, Rx, Ry, Rz, sliders — which is
  also the order the game names them in. Sticks that skip one of these
  (e.g. no Z) would need a per-model layout; see `_AXIS_ORDER`.

SDL events are polled on a short Qt timer; background events are enabled
because the launcher window usually isn't focused while buttons are
pressed.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QObject, QTimer, Signal

from app.bindings import normalize_product

AXIS_MAX = 32767
POLL_MS = 10

# Game axis names in the standard (DirectInput / evdev) order.
_AXIS_ORDER = ["x", "y", "z", "rotx", "roty", "rotz", "slider1", "slider2"]
_HAT_BITS = (("up", 0x01), ("right", 0x02), ("down", 0x04), ("left", 0x08))

try:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "Using SDL2 binaries from pysdl2-dll"
        import sdl2
    _SDL_ERROR = None
except Exception as exc:  # missing/broken SDL: live input reports unsupported
    sdl2 = None
    _SDL_ERROR = str(exc)


class _Stick:
    def __init__(self, handle, instance_id: int, name: str, n_axes: int):
        self.handle = handle
        self.instance_id = instance_id
        self.name = name
        self.axis_names = _AXIS_ORDER[:n_axes]
        self.hats: dict[int, int] = {}          # hat index -> last bitmask
        self.axis_values: dict[str, int] = {}


class SdlJoystickInput(QObject):
    """Emits `pressed(device, input)` / `released(device, input)` for
    buttons and hat directions and `axis(device, input, value)` for analog
    axes (value in -32768..32767). `device` is the normalized product name,
    comparable with BindingProfile.joystick_products().
    """

    pressed = Signal(str, str)
    released = Signal(str, str)
    axis = Signal(str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sticks: dict[int, _Stick] = {}   # SDL instance id -> stick
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    @staticmethod
    def supported() -> bool:
        return sdl2 is not None

    def device_names(self) -> list[str]:
        return [s.name for s in self._sticks.values()]

    def find_device(self, product: str) -> str | None:
        """Live device name for a game product name. The OS name may carry a
        vendor prefix the game's doesn't ('VKB-Sim © Alex Oz 2021 VKBsim
        Gladiator EVO L' vs 'VKBsim Gladiator EVO L')."""
        for s in self._sticks.values():
            if product and (s.name == product or s.name.endswith(" " + product)):
                return s.name
        return None

    def axis_values(self, device: str) -> dict[str, int]:
        for s in self._sticks.values():
            if s.name == device:
                return dict(s.axis_values)
        return {}

    def start(self) -> None:
        if self._running or sdl2 is None:
            return
        for hint, value in (
            (b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1"),
            (b"SDL_JOYSTICK_HIDAPI", b"0"),     # keep raw HID order; no remapping drivers
            (b"SDL_JOYSTICK_RAWINPUT", b"0"),   # Windows: plain DirectInput, like the game
        ):
            sdl2.SDL_SetHint(hint, value)
        if sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_JOYSTICK) != 0:
            return
        sdl2.SDL_JoystickEventState(sdl2.SDL_ENABLE)
        self._running = True
        # Devices present at start arrive as JOYDEVICEADDED events.
        self._poll()
        self._timer.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._timer.stop()
        for s in self._sticks.values():
            sdl2.SDL_JoystickClose(s.handle)
        self._sticks.clear()
        sdl2.SDL_QuitSubSystem(sdl2.SDL_INIT_JOYSTICK)
        self._running = False

    # -- events ---------------------------------------------------------------
    def _open(self, device_index: int) -> None:
        handle = sdl2.SDL_JoystickOpen(device_index)
        if not handle:
            return
        iid = sdl2.SDL_JoystickInstanceID(handle)
        raw = sdl2.SDL_JoystickName(handle) or b""
        stick = _Stick(handle, iid, normalize_product(raw.decode("utf-8", "replace")),
                       sdl2.SDL_JoystickNumAxes(handle))
        for i, name in enumerate(stick.axis_names):
            stick.axis_values[name] = sdl2.SDL_JoystickGetAxis(handle, i)
        for h in range(sdl2.SDL_JoystickNumHats(handle)):
            stick.hats[h] = sdl2.SDL_JoystickGetHat(handle, h)
        self._sticks[iid] = stick

    def _poll(self) -> None:
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            etype = event.type
            if etype == sdl2.SDL_JOYDEVICEADDED:
                self._open(event.jdevice.which)
            elif etype == sdl2.SDL_JOYDEVICEREMOVED:
                stick = self._sticks.pop(event.jdevice.which, None)
                if stick is not None:
                    sdl2.SDL_JoystickClose(stick.handle)
            elif etype in (sdl2.SDL_JOYBUTTONDOWN, sdl2.SDL_JOYBUTTONUP):
                stick = self._sticks.get(event.jbutton.which)
                if stick is not None:
                    signal = self.pressed if etype == sdl2.SDL_JOYBUTTONDOWN else self.released
                    signal.emit(stick.name, f"button{event.jbutton.button + 1}")
            elif etype == sdl2.SDL_JOYHATMOTION:
                stick = self._sticks.get(event.jhat.which)
                if stick is not None:
                    self._hat(stick, event.jhat.hat, event.jhat.value)
            elif etype == sdl2.SDL_JOYAXISMOTION:
                stick = self._sticks.get(event.jaxis.which)
                if stick is not None and event.jaxis.axis < len(stick.axis_names):
                    name = stick.axis_names[event.jaxis.axis]
                    stick.axis_values[name] = event.jaxis.value
                    self.axis.emit(stick.name, name, event.jaxis.value)

    def _hat(self, stick: _Stick, hat: int, mask: int) -> None:
        before = stick.hats.get(hat, 0)
        stick.hats[hat] = mask
        for direction, bit in _HAT_BITS:
            if before & bit and not mask & bit:
                self.released.emit(stick.name, f"hat{hat + 1}_{direction}")
        for direction, bit in _HAT_BITS:
            if mask & bit and not before & bit:
                self.pressed.emit(stick.name, f"hat{hat + 1}_{direction}")


JoystickInput = SdlJoystickInput
