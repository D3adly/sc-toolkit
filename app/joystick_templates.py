"""Joystick model templates for the bindings diagram, plus the per-user
device setup (which physical control produced which button number, and any
hand-adjusted marker positions).

A template is a product photo (downloaded on first use, see stick_photos)
plus named controls with a marker position in display coordinates.

Button numbering on VKB sticks depends on the firmware profile loaded in
VKBDevCfg, so templates deliberately don't hardcode button numbers — the
Identify wizard records them from the real device. Only the conventional
main axes get defaults.
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


@dataclass(frozen=True)
class StickTemplate:
    id: str
    name: str
    photo: Photo
    controls: tuple[Control, ...]

    @property
    def size(self) -> tuple[float, float]:
        _, _, w, h = self.photo.crop
        return (w * self.photo.scale, h * self.photo.scale)

    def control(self, control_id: str) -> Control | None:
        return next((c for c in self.controls if c.id == control_id), None)


def _button(prompt: str) -> tuple[InputSlot, ...]:
    return (InputSlot("press", "●", prompt),)


def _hat(name: str) -> tuple[InputSlot, ...]:
    return (
        InputSlot("up", "▲", f"Push the {name} UP"),
        InputSlot("right", "▶", f"Push the {name} RIGHT"),
        InputSlot("down", "▼", f"Push the {name} DOWN"),
        InputSlot("left", "◀", f"Push the {name} LEFT"),
        InputSlot("push", "●", f"Press the {name} straight IN"),
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


def _controls(photo: Photo, positions: dict[str, tuple[int, int]]) -> tuple[Control, ...]:
    """Builds controls from marker positions measured in source-photo pixels."""
    x0, y0, _, _ = photo.crop
    out = []
    for cid, label, inputs in _EVO_SCE_STD:
        sx, sy = positions[cid]
        out.append(Control(cid, label, ((sx - x0) * photo.scale, (sy - y0) * photo.scale), inputs))
    return tuple(out)


_PHOTO_CDN = "https://cdn.shopify.com/s/files/1/0571/3192/5689/products/"
_PHOTO_R = Photo(_PHOTO_CDN + "68_GNX-EVO_SCG-R_1024_2-nologo.jpg", (150, 30, 780, 950), 0.8)
_PHOTO_L = Photo(_PHOTO_CDN + "67_GNX-EVO_SCG-L_1024_3-nologo.jpg", (115, 45, 780, 950), 0.8)

TEMPLATES: dict[str, StickTemplate] = {
    t.id: t
    for t in (
        StickTemplate(
            "vkb_evo_sce_std_r", "VKB Gladiator EVO SCE (Standard) — Right", _PHOTO_R,
            _controls(_PHOTO_R, {
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
            _controls(_PHOTO_L, {
                "hat_tl": (570, 112), "hat_tr": (636, 130), "hat_c": (580, 186),
                "btn_red": (638, 220), "btn_front": (782, 198), "trigger": (675, 302),
                "btn_thumb": (566, 374), "btn_pinky": (410, 548), "twist": (500, 440),
                "stick": (522, 628),
                "base_f2": (300, 712), "base_f1": (352, 724), "base_f3": (402, 748),
                "switch": (240, 792), "wheel": (293, 815), "encoder": (346, 832),
            }),
        ),
    )
}


def guess_template(product: str) -> str | None:
    p = product.lower()
    if "gladiator" in p and "evo" in p:
        if p.endswith(" l"):
            return "vkb_evo_sce_std_l"
        if p.endswith(" r"):
            return "vkb_evo_sce_std_r"
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
