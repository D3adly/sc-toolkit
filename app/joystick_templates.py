"""Joystick model templates for the bindings diagram, plus the per-user
device setup (which physical control produced which button number, and any
hand-adjusted marker positions).

A template is a product photo (downloaded on first use, see stick_photos)
plus named controls with a marker position in display coordinates.

Button numbering on VKB sticks depends on the firmware profile loaded in
VKBDevCfg, so those templates deliberately don't hardcode button numbers: the
Identify wizard records them from the real device. Only the conventional
main axes get defaults. Devices with fixed numbering (the Logitech/Saitek X56)
come with defaults for every input that is known for sure; Identify can still
correct or fill any of them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app import config

SETUP_FILE = config.USER_CONFIG_DIR / "joysticks.json"


@dataclass(frozen=True)
class InputSlot:
    key: str      # unique within the control, e.g. "up", "s1"
    tag: str      # short glyph shown in the callout
    prompt: str   # Identify instruction
    axis: bool = False
    default: str = ""  # default SC input, e.g. "x"


@dataclass(frozen=True)
class Control:
    id: str
    label: str
    pos: tuple[float, float]
    inputs: tuple[InputSlot, ...]


@dataclass(frozen=True)
class Photo:
    url: str
    crop: tuple[int, int, int, int]  # x, y, w, h in source pixels
    scale: float                     # source pixels -> display units
    key_background: bool = True      # white studio background to key out (False: already transparent)


@dataclass(frozen=True)
class StickTemplate:
    id: str
    name: str
    photo: Photo
    controls: tuple[Control, ...]
    # True when the device's button numbers are fixed in hardware, so the defaults are
    # trustworthy and only inputs without a default need identifying.
    fixed_numbering: bool = False

    @property
    def size(self) -> tuple[float, float]:
        _, _, w, h = self.photo.crop
        return (w * self.photo.scale, h * self.photo.scale)

    def control(self, control_id: str) -> Control | None:
        return next((c for c in self.controls if c.id == control_id), None)


def _button(prompt: str, default: str = "") -> tuple[InputSlot, ...]:
    return (InputSlot("press", "●", prompt, default=default),)


def _hat(name: str) -> tuple[InputSlot, ...]:
    return (
        InputSlot("up", "▲", f"Push the {name} UP"),
        InputSlot("right", "▶", f"Push the {name} RIGHT"),
        InputSlot("down", "▼", f"Push the {name} DOWN"),
        InputSlot("left", "◀", f"Push the {name} LEFT"),
        InputSlot("push", "●", f"Press the {name} straight IN"),
    )


def _hat4(name: str, defaults: tuple[str, str, str, str] = ("", "", "", "")) -> tuple[InputSlot, ...]:
    """A 4-way hat without a centre push. `defaults` in up, right, down, left order."""
    up, right, down, left = defaults
    return (
        InputSlot("up", "▲", f"Push the {name} UP", default=up),
        InputSlot("right", "▶", f"Push the {name} RIGHT", default=right),
        InputSlot("down", "▼", f"Push the {name} DOWN", default=down),
        InputSlot("left", "◀", f"Push the {name} LEFT", default=left),
    )


def _buttons4(first: int) -> tuple[str, str, str, str]:
    """Default inputs for a hat reported as four consecutive buttons (up, right, down, left)."""
    return tuple(f"button{first + i}" for i in range(4))  # type: ignore[return-value]


def _rocker(name: str, up: str = "", down: str = "", up_label: str = "UP", down_label: str = "DOWN") -> tuple[InputSlot, ...]:
    """A two-way switch (toggle or rocker) reported as one button per direction."""
    return (
        InputSlot("up", "▲", f"Flip the {name} {up_label}", default=up),
        InputSlot("down", "▼", f"Flip the {name} {down_label}", default=down),
    )


def _axis(key: str, tag: str, prompt: str, default: str = "") -> InputSlot:
    return InputSlot(key, tag, prompt, axis=True, default=default)


# Gladiator NXT EVO "Space Combat Edition", Standard grip (C1 thumb button,
# no analog mini-stick / rapid-fire trigger) on the EVO base. Hat names are
# as seen by the pilot looking at the grip head.
_EVO_SCE_STD = (
    ("hat_tl", "Hat (top left)", _hat("top-left hat")),
    ("hat_tr", "Hat (top right)", _hat("top-right hat")),
    ("hat_c", "Hat (centre)", _hat("centre hat")),
    ("btn_red", "Red button", _button("Press the red button")),
    ("btn_front", "Front top button", _button("Press the small button on the front tip of the grip head")),
    ("trigger", "Trigger", (
        InputSlot("s1", "①", "Pull the trigger to the FIRST stage"),
        InputSlot("s2", "②", "Pull the trigger ALL THE WAY (second stage)"),
    )),
    ("btn_thumb", "Thumb button (C1)", _button("Press the silver thumb button (C1)")),
    ("btn_pinky", "Pinky lever", _button("Press the pinky lever at the bottom of the grip")),
    ("twist", "Twist", (_axis("twist", "⟲", "Twist the grip fully one way", default="rotz"),)),
    ("stick", "Stick", (
        _axis("x", "↔", "Push the stick fully LEFT or RIGHT", default="x"),
        _axis("y", "↕", "Push the stick fully FORWARD or BACK", default="y"),
    )),
    ("base_f1", "Base button F1", _button("Press base button F1 (middle)")),
    ("base_f2", "Base button F2", _button("Press base button F2")),
    ("base_f3", "Base button F3", _button("Press base button F3")),
    ("switch", "Switch (Sw1)", (
        InputSlot("up", "▲", "Push the Sw1 switch UP"),
        InputSlot("down", "▼", "Push the Sw1 switch DOWN"),
    )),
    ("wheel", "Throttle wheel", (_axis("wheel", "⇅", "Roll the throttle wheel fully one way"),)),
    ("encoder", "Encoder (En1)", (
        InputSlot("up", "▲", "Roll the En1 encoder UP"),
        InputSlot("down", "▼", "Roll the En1 encoder DOWN"),
        InputSlot("push", "●", "Press the En1 encoder in (Skip if it doesn't click)"),
    )),
)


def _controls(photo: Photo, layout, positions: dict[str, tuple[int, int]]) -> tuple[Control, ...]:
    """Builds controls from a control layout and marker positions measured in source-photo pixels."""
    x0, y0, _, _ = photo.crop
    out = []
    for cid, label, inputs in layout:
        sx, sy = positions[cid]
        out.append(Control(cid, label, ((sx - x0) * photo.scale, (sy - y0) * photo.scale), inputs))
    return tuple(out)


# Logitech (formerly Saitek) X56 H.O.T.A.S. Its numbering is fixed in hardware. Defaults are the
# ones two independent community maps agree on (Joystick Diagrams' Saitek and Logitech X56
# templates); the throttle's H/I buttons, mini-stick click, SLD slider and mode switch disagree or
# are missing there, so they have no default and Identify fills them.
_X56_STICK = (
    ("pov", "POV hat", _hat4("POV hat (silver, left of the head)", ("hat1_up", "hat1_right", "hat1_down", "hat1_left"))),
    ("btn_a", "Button A", _button("Press button A (top of the head)", "button2")),
    ("btn_b", "Button B", _button("Press button B (right side of the head)", "button3")),
    ("h1", "Hat H1", _hat4("H1 hat (top right)", _buttons4(7))),
    ("h2", "Hat H2", _hat4("H2 hat (lower right)", _buttons4(11))),
    ("trigger", "Trigger", _button("Pull the trigger", "button1")),
    ("ministick", "Mini-stick (C)", (
        _axis("x", "↔", "Push the C mini-stick fully LEFT or RIGHT", default="rotx"),
        _axis("y", "↕", "Push the C mini-stick fully UP or DOWN", default="roty"),
        InputSlot("push", "●", "Press the C mini-stick in", default="button4"),
    )),
    ("btn_d", "Button D", _button("Press button D (front of the grip, near the pinkie)", "button5")),
    ("pinkie", "Pinkie lever (E)", _button("Squeeze the pinkie lever", "button6")),
    ("twist", "Twist", (_axis("twist", "⟲", "Twist the grip fully one way", default="rotz"),)),
    ("stick", "Stick", (
        _axis("x", "↔", "Push the stick fully LEFT or RIGHT", default="x"),
        _axis("y", "↕", "Push the stick fully FORWARD or BACK", default="y"),
    )),
)

_X56_THROTTLE = (
    ("k1", "K1 rocker", _rocker("K1 rocker (back of the left lever)", "button28", "button29")),
    ("btn_h", "Button H", _button("Press button H (back of the left lever)")),
    ("btn_i", "Button I", _button("Press button I (back of the left lever)")),
    ("lever_l", "Left throttle", (_axis("lever", "⇅", "Move the LEFT throttle lever end to end", default="x"),)),
    ("lever_r", "Right throttle", (_axis("lever", "⇅", "Move the RIGHT throttle lever end to end", default="y"),)),
    ("rty1", "Rotary 1 (F)", (
        _axis("turn", "⟲", "Turn the top rotary (RTY1) fully one way", default="z"),
        InputSlot("push", "●", "Press the top rotary in (F)", default="button2"),
    )),
    ("sld", "Slider (SLD)", _button("Slide the SLD switch")),
    ("rty2", "Rotary 2 (G)", (
        _axis("turn", "⟲", "Turn the lower rotary (RTY2) fully one way", default="rotz"),
        InputSlot("push", "●", "Press the lower rotary in (G)", default="button3"),
    )),
    ("btn_e", "Button E", _button("Press button E (thumb)", "button1")),
    ("h3", "Hat H3", _hat4("H3 hat (upper thumb hat)", _buttons4(20))),
    ("ministick", "Mini-stick", (
        _axis("x", "↔", "Push the thumb mini-stick fully LEFT or RIGHT", default="rotx"),
        _axis("y", "↕", "Push the thumb mini-stick fully UP or DOWN", default="roty"),
        InputSlot("push", "●", "Press the thumb mini-stick in"),
    )),
    ("h4", "Hat H4", _hat4("H4 hat (lower thumb hat)", _buttons4(24))),
    ("mode", "Mode switch", (
        InputSlot("m1", "1", "Turn the mode switch to M1"),
        InputSlot("m2", "2", "Turn the mode switch to M2"),
        InputSlot("s1", "S", "Turn the mode switch to S1"),
    )),
    ("sw12", "Switch SW1 / SW2", _rocker("SW1/SW2 switch", "button6", "button7", "to SW1", "to SW2")),
    ("sw34", "Switch SW3 / SW4", _rocker("SW3/SW4 switch", "button8", "button9", "to SW3", "to SW4")),
    ("sw56", "Switch SW5 / SW6", _rocker("SW5/SW6 switch", "button10", "button11", "to SW5", "to SW6")),
    ("rty3", "Rotary 3", (_axis("turn", "⟲", "Turn the RTY3 knob on the base fully one way", default="slider1"),)),
    ("rty4", "Rotary 4", (_axis("turn", "⟲", "Turn the RTY4 knob on the base fully one way", default="slider2"),)),
    ("tgl1", "Toggle TGL1", _rocker("TGL1 toggle", "button12", "button13")),
    ("tgl2", "Toggle TGL2", _rocker("TGL2 toggle", "button14", "button15")),
    ("tgl3", "Toggle TGL3", _rocker("TGL3 toggle", "button16", "button17")),
    ("tgl4", "Toggle TGL4", _rocker("TGL4 toggle", "button18", "button19")),
)


_PHOTO_CDN = "https://cdn.shopify.com/s/files/1/0571/3192/5689/products/"
_LOGI_CDN = "https://resource.logitechg.com/content/dam/gaming/en/products/x56/2025/gallery/"
_PHOTO_R = Photo(_PHOTO_CDN + "68_GNX-EVO_SCG-R_1024_2-nologo.jpg", (150, 30, 780, 950), 0.8)
_PHOTO_L = Photo(_PHOTO_CDN + "67_GNX-EVO_SCG-L_1024_3-nologo.jpg", (115, 45, 780, 950), 0.8)
# Logitech's gallery renders are transparent PNGs (2500x2160), one per unit.
_PHOTO_X56_STICK = Photo(_LOGI_CDN + "x56-3qtr-left-angle-gallery-4.png", (722, 353, 1144, 1443), 0.55, key_background=False)
_PHOTO_X56_THROTTLE = Photo(_LOGI_CDN + "x56-3qtr-left-angle-gallery-5.png", (601, 592, 1254, 1055), 0.62, key_background=False)


def _at(photo: Photo, positions: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    """Marker positions given relative to the photo's crop, converted to source-photo pixels."""
    x0, y0, _, _ = photo.crop
    return {cid: (x + x0, y + y0) for cid, (x, y) in positions.items()}

TEMPLATES: dict[str, StickTemplate] = {
    t.id: t
    for t in (
        StickTemplate(
            "vkb_evo_sce_std_r", "VKB Gladiator EVO SCE (Standard) — Right", _PHOTO_R,
            _controls(_PHOTO_R, _EVO_SCE_STD, {
                "hat_tl": (368, 122), "hat_tr": (455, 95), "hat_c": (425, 168),
                "btn_red": (370, 203), "btn_front": (258, 175), "trigger": (362, 282),
                "btn_thumb": (440, 355), "btn_pinky": (622, 520), "twist": (520, 440),
                "stick": (505, 612),
                "base_f2": (610, 722), "base_f1": (672, 698), "base_f3": (728, 682),
                "switch": (668, 812), "wheel": (730, 792), "encoder": (786, 772),
            }),
        ),
        StickTemplate(
            "vkb_evo_sce_std_l", "VKB Gladiator EVO SCE (Standard) — Left", _PHOTO_L,
            _controls(_PHOTO_L, _EVO_SCE_STD, {
                "hat_tl": (570, 112), "hat_tr": (636, 130), "hat_c": (580, 186),
                "btn_red": (638, 220), "btn_front": (782, 198), "trigger": (675, 302),
                "btn_thumb": (566, 374), "btn_pinky": (410, 548), "twist": (500, 440),
                "stick": (522, 628),
                "base_f2": (300, 712), "base_f1": (352, 724), "base_f3": (402, 748),
                "switch": (240, 792), "wheel": (293, 815), "encoder": (346, 832),
            }),
        ),
        StickTemplate(
            "logitech_x56_stick", "Logitech / Saitek X56 — Stick", _PHOTO_X56_STICK,
            _controls(_PHOTO_X56_STICK, _X56_STICK, _at(_PHOTO_X56_STICK, {
                "pov": (433, 125), "btn_a": (462, 48), "btn_b": (640, 120), "h1": (552, 38),
                "h2": (592, 142), "trigger": (432, 335), "ministick": (385, 410), "btn_d": (440, 600),
                "pinkie": (352, 575), "twist": (570, 520), "stick": (540, 905),
            })),
            fixed_numbering=True,
        ),
        StickTemplate(
            "logitech_x56_throttle", "Logitech / Saitek X56 — Throttle", _PHOTO_X56_THROTTLE,
            _controls(_PHOTO_X56_THROTTLE, _X56_THROTTLE, _at(_PHOTO_X56_THROTTLE, {
                # K1, H and I sit on the back of the left lever, out of sight in this photo.
                "k1": (500, 75), "btn_h": (430, 150), "btn_i": (425, 225),
                "lever_l": (480, 300), "lever_r": (640, 210),
                "rty1": (945, 50), "sld": (835, 225), "rty2": (952, 290), "btn_e": (775, 340),
                "h3": (866, 352), "ministick": (728, 402), "h4": (838, 428),
                "mode": (138, 520), "sw12": (308, 558), "sw34": (415, 597), "sw56": (535, 643),
                "rty3": (704, 608), "rty4": (838, 612),
                "tgl1": (973, 551), "tgl2": (850, 535), "tgl3": (1104, 482), "tgl4": (985, 485),
            })),
            fixed_numbering=True,
        ),
    )
}


def guess_template(product: str) -> str | None:
    """Template for a game product name: 'VKBsim Gladiator EVO L', 'Saitek Pro Flight X-56 Rhino
    Throttle', 'X56 H.O.T.A.S. Stick' (the Logitech-era name)..."""
    p = product.lower()
    if "gladiator" in p and "evo" in p:
        if p.endswith(" l"):
            return "vkb_evo_sce_std_l"
        if p.endswith(" r"):
            return "vkb_evo_sce_std_r"
    if "x-56" in p or "x56" in p:
        if "throttle" in p:
            return "logitech_x56_throttle"
        if "stick" in p or "joystick" in p:
            return "logitech_x56_stick"
    return None


# -- per-device setup ------------------------------------------------------

@dataclass
class DeviceSetup:
    template_id: str | None
    inputs: dict[str, str]                      # "control.slot" -> SC input
    positions: dict[str, tuple[float, float]]   # control id -> template coords

    @property
    def template(self) -> StickTemplate | None:
        return TEMPLATES.get(self.template_id) if self.template_id else None

    def input_for(self, control: Control, slot: InputSlot) -> str:
        return self.inputs.get(f"{control.id}.{slot.key}", slot.default)

    def pos_for(self, control: Control) -> tuple[float, float]:
        return self.positions.get(control.id, control.pos)

    def assign(self, control: Control, slot: InputSlot, inp: str) -> None:
        """Maps `inp` to this slot, unmapping it from any other slot (one
        physical input can only be in one place)."""
        target = f"{control.id}.{slot.key}"
        template = self.template
        if template and inp:
            for other in template.controls:
                for other_slot in other.inputs:
                    other_key = f"{other.id}.{other_slot.key}"
                    if other_key != target and self.input_for(other, other_slot) == inp:
                        self.inputs[other_key] = ""
        self.inputs[target] = inp

    def slot_for_input(self, inp: str) -> tuple[Control, InputSlot] | None:
        template = self.template
        if not template or not inp:
            return None
        for c in template.controls:
            for s in c.inputs:
                if self.input_for(c, s) == inp:
                    return c, s
        return None


class SetupStore:
    """joysticks.json, keyed by normalized device product name so it
    survives the game renumbering js1/js2."""

    def __init__(self, path: Path = SETUP_FILE):
        self.path = path
        try:
            self._data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            self._data = {}
        self._data.setdefault("devices", {})

    def get(self, product: str) -> DeviceSetup:
        raw = self._data["devices"].get(product)
        if raw is None:
            return DeviceSetup(guess_template(product), {}, {})
        return DeviceSetup(
            raw.get("template"),
            dict(raw.get("inputs", {})),
            {k: tuple(v) for k, v in raw.get("positions", {}).items()},
        )

    def put(self, product: str, setup: DeviceSetup) -> None:
        self._data["devices"][product] = {
            "template": setup.template_id,
            "inputs": setup.inputs,
            "positions": {k: list(v) for k, v in setup.positions.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)
