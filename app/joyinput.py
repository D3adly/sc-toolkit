"""Live joystick input, reported in Star Citizen's own input names.

Linux implementation over the kernel joydev API (/dev/input/js*): no
dependencies, just 8-byte `struct js_event` reads driven by a
QSocketNotifier. joydev orders buttons by evdev key code, which follows HID
usage order — so joydev button i is the game's (Wine DirectInput)
`button{i+1}`. Axes are named from the joydev axis map; the first HAT0X/Y
pair becomes SC's `hat1`.

Windows would need a different backend (e.g. SDL3) behind the same signal.
"""

from __future__ import annotations

import array
import fcntl
import glob
import os
import struct
import sys

from PySide6.QtCore import QObject, QSocketNotifier, Signal

from app.bindings import normalize_product

_JSIOCGAXES = 0x80016A11
_JSIOCGBUTTONS = 0x80016A12
_JSIOCGNAME_128 = 0x80806A13
_JSIOCGAXMAP = 0x80406A32

_JS_EVENT = struct.Struct("IhBB")
_JS_EVENT_BUTTON = 0x01
_JS_EVENT_AXIS = 0x02
_JS_EVENT_INIT = 0x80

# evdev ABS_* code -> SC axis name
_AXIS_NAMES = {
    0x00: "x", 0x01: "y", 0x02: "z",
    0x03: "rotx", 0x04: "roty", 0x05: "rotz",
    0x06: "slider1", 0x07: "slider2",  # ABS_THROTTLE / ABS_RUDDER
    0x08: "slider2",                    # ABS_WHEEL
}
_HAT_CODES = range(0x10, 0x18)  # ABS_HAT0X .. ABS_HAT3Y

AXIS_MAX = 32767


class _Device:
    def __init__(self, path: str, fd: int, name: str, axis_codes: list[int]):
        self.path = path
        self.fd = fd
        self.name = name
        self.axis_codes = axis_codes
        self.hat_dir: dict[tuple[int, bool], str] = {}  # (hat, vertical?) -> held direction
        self.axis_values: dict[str, int] = {}


class JoystickInput(QObject):
    """Emits `pressed(device, input)` / `released(device, input)` for
    buttons and hat directions and `axis(device, input, value)` for analog
    axes (value in -32767..32767). `device` is the normalized product name,
    comparable with BindingProfile.joystick_products().
    """

    pressed = Signal(str, str)
    released = Signal(str, str)
    axis = Signal(str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: list[_Device] = []
        self._notifiers: list[QSocketNotifier] = []

    @staticmethod
    def supported() -> bool:
        return sys.platform.startswith("linux")

    def device_names(self) -> list[str]:
        return [d.name for d in self._devices]

    def find_device(self, product: str) -> str | None:
        """Live device name for a game product name. The kernel name may
        carry a vendor prefix the game's doesn't ('VKB-Sim © Alex Oz 2021
        VKBsim Gladiator EVO L' vs 'VKBsim Gladiator EVO L')."""
        for d in self._devices:
            if product and (d.name == product or d.name.endswith(" " + product)):
                return d.name
        return None

    def axis_values(self, device: str) -> dict[str, int]:
        for d in self._devices:
            if d.name == device:
                return dict(d.axis_values)
        return {}

    def start(self) -> None:
        if self._devices or not self.supported():
            return
        for path in sorted(glob.glob("/dev/input/js*")):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            try:
                raw = array.array("B", [0] * 128)
                fcntl.ioctl(fd, _JSIOCGNAME_128, raw)
                name = bytes(raw).split(b"\x00", 1)[0].decode("utf-8", "replace")
                n_axes = array.array("B", [0])
                fcntl.ioctl(fd, _JSIOCGAXES, n_axes)
                axmap = array.array("B", [0] * 64)
                fcntl.ioctl(fd, _JSIOCGAXMAP, axmap)
            except OSError:
                os.close(fd)
                continue
            dev = _Device(path, fd, normalize_product(name), list(axmap[:n_axes[0]]))
            self._devices.append(dev)
            notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
            notifier.activated.connect(lambda *_args, d=dev: self._read(d))
            self._notifiers.append(notifier)

    def stop(self) -> None:
        for n in self._notifiers:
            n.setEnabled(False)
            n.deleteLater()
        for d in self._devices:
            try:
                os.close(d.fd)
            except OSError:
                pass
        self._notifiers.clear()
        self._devices.clear()

    def _read(self, dev: _Device) -> None:
        while True:
            try:
                data = os.read(dev.fd, _JS_EVENT.size * 64)
            except BlockingIOError:
                return
            except OSError:
                return  # unplugged; the view rescans next time it opens
            if not data:
                return
            for off in range(0, len(data) - _JS_EVENT.size + 1, _JS_EVENT.size):
                _time, value, etype, number = _JS_EVENT.unpack_from(data, off)
                if etype & _JS_EVENT_INIT:
                    # Initial state burst on open: just record axis rest positions.
                    if etype & _JS_EVENT_AXIS and number < len(dev.axis_codes):
                        name = _AXIS_NAMES.get(dev.axis_codes[number])
                        if name:
                            dev.axis_values[name] = value
                    continue
                if etype & _JS_EVENT_BUTTON:
                    signal = self.pressed if value else self.released
                    signal.emit(dev.name, f"button{number + 1}")
                elif etype & _JS_EVENT_AXIS and number < len(dev.axis_codes):
                    self._axis(dev, dev.axis_codes[number], value)

    def _axis(self, dev: _Device, code: int, value: int) -> None:
        if code in _HAT_CODES:
            hat = (code - 0x10) // 2 + 1
            vertical = (code - 0x10) % 2 == 1
            if value == 0:
                direction = None
            elif vertical:
                direction = "up" if value < 0 else "down"
            else:
                direction = "left" if value < 0 else "right"
            held = dev.hat_dir.pop((hat, vertical), None)
            if held == direction:
                dev.hat_dir[(hat, vertical)] = held
                return
            if held:
                self.released.emit(dev.name, f"hat{hat}_{held}")
            if direction:
                dev.hat_dir[(hat, vertical)] = direction
                self.pressed.emit(dev.name, f"hat{hat}_{direction}")
            return
        name = _AXIS_NAMES.get(code)
        if name:
            dev.axis_values[name] = value
            self.axis.emit(dev.name, name, value)
