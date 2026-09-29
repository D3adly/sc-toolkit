"""Star Citizen joystick bindings: game defaults + the user's overrides.

The game's own `actionmaps.xml` only stores *differences* from the
defaults, which live in `Data\\Libs\\Config\\defaultProfile.xml` inside
Data.p4k. Joystick defaults there (`joystick="button8"`) apply to js1 only;
a user `<rebind input="jsN_...">` replaces whatever instance N had for that
action, and `input="jsN_ "` (trailing space) means explicitly unbound.

Action/category labels are resolved through global.ini — preferring a loose
copy in the install (e.g. StarStrings) since that is what the game shows.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app import config, cryxml, p4k

DEFAULT_PROFILE_ENTRY = "Data\\Libs\\Config\\defaultProfile.xml"
GLOBAL_INI_ENTRY = "Data\\Localization\\english\\global.ini"

ActionKey = tuple[str, str]  # (actionmap name, action name)


@dataclass(frozen=True)
class ActionDef:
    actionmap: str
    name: str
    label: str
    category: str    # localized UICategory of the actionmap ("" = not in game UI)
    group: str       # localized actionmap label, e.g. "Flight - Movement"
    default_js: str  # default joystick input for js1, "" if none
    listed: bool     # appears in the game's own keybinding screen

    @property
    def key(self) -> ActionKey:
        return (self.actionmap, self.name)


@dataclass
class GameData:
    actions: dict[ActionKey, ActionDef]
    categories: list[str]

    def action(self, key: ActionKey) -> ActionDef:
        found = self.actions.get(key)
        if found is not None:
            return found
        return ActionDef(key[0], key[1], key[1], "", key[0], "", False)


# -- loading game data ----------------------------------------------------

def _cache_key(p4k_path: Path) -> str:
    st = p4k_path.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def _load_from_p4k_cached(channel_root: Path, entry: str, cache_name: str) -> bytes | None:
    p4k_path = channel_root / "Data.p4k"
    if not p4k_path.is_file():
        return None
    cache_file = config.CACHE_DIR / f"{cache_name}-{_cache_key(p4k_path)}"
    if cache_file.is_file():
        return cache_file.read_bytes()

    raw = p4k.extract(p4k_path, [entry]).get(entry)
    if raw is None:
        return None
    if cryxml.is_cryxml(raw):
        raw = ET.tostring(cryxml.parse(raw), encoding="utf-8")

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for stale in config.CACHE_DIR.glob(f"{cache_name}-*"):
        stale.unlink(missing_ok=True)
    cache_file.write_bytes(raw)
    return raw


def _parse_ini(data: bytes) -> dict[str, str]:
    out = {}
    for line in data.decode("utf-8-sig", "replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            # StarStrings-style keys carry a ",P" suffix.
            out[key.split(",", 1)[0].strip().lower()] = value.strip()
    return out


def _load_localization(channel_root: Path) -> dict[str, str]:
    loose = channel_root / "Data" / "Localization" / "english" / "global.ini"
    if loose.is_file():
        return _parse_ini(loose.read_bytes())
    raw = _load_from_p4k_cached(channel_root, GLOBAL_INI_ENTRY, "global.ini")
    return _parse_ini(raw) if raw else {}


def _tidy_category(text: str) -> str:
    # Category labels come in mixed styles ("FLIGHT", "ON FOOT", "Vehicle").
    return text.title() if text.isupper() else text


# Some UICategory keys have no global.ini entry at all.
_CATEGORY_FALLBACK = {
    "ui_ccturrets": "Turrets",
    "ui_ccseatgeneral": "Seats & Operator Modes",
    "ui_ccflightmodes": "Flight Modes",
    "ui_ccorientationcontrol": "Orientation Control",
    "ui_cc_drivemodes": "Drive Modes",
    "ui_ccevazgt": "E.V.A. (Zero-G)",
    "ui_cglightcontrollerdesc": "Lights",
}


def _category_from_key(key: str) -> str:
    """'@ui_CCSomeThing' -> 'Some Thing' when nothing better is known."""
    bare = key.lstrip("@")
    known = _CATEGORY_FALLBACK.get(bare.lower())
    if known:
        return known
    bare = re.sub(r"^ui_(CC|CG)?_?", "", bare)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", bare).replace("_", " ").strip()


def load_game_data(channel_root: Path) -> GameData:
    """Slow on first run after a game patch (reads Data.p4k, ~seconds);
    cached afterwards. Call off the UI thread.
    """
    raw = _load_from_p4k_cached(channel_root, DEFAULT_PROFILE_ENTRY, "defaultProfile.xml")
    if raw is None:
        raise FileNotFoundError(f"Could not read default bindings from {channel_root / 'Data.p4k'}")
    root = ET.fromstring(raw)
    loc = _load_localization(channel_root)

    def resolve(label: str) -> tuple[str, bool]:
        if label.startswith("@"):
            text = loc.get(label[1:].lower())
            if text:
                return text, True
        return label, False

    actions: dict[ActionKey, ActionDef] = {}
    categories: list[str] = []
    for am in root.iter("actionmap"):
        category = ""
        if am.get("UICategory"):
            category, ok = resolve(am.get("UICategory"))
            category = _tidy_category(category) if ok else _category_from_key(category)
        if category and category not in categories:
            categories.append(category)
        group, _ = resolve(am.get("UILabel", am.get("name")))

        for a in am.findall("action"):
            label, localized = resolve(a.get("UILabel", a.get("name")))
            default_js = (a.get("joystick") or "").strip()
            nested = a.find("joystick")
            if nested is not None and nested.get("input", "").strip():
                default_js = nested.get("input").strip()
            action = ActionDef(
                actionmap=am.get("name"),
                name=a.get("name"),
                label=label,
                category=category,
                group=group,
                default_js=default_js.lower(),
                listed=bool(category) and localized,
            )
            actions[action.key] = action

    return GameData(actions=actions, categories=categories)


# -- user profile (actionmaps.xml) -----------------------------------------

_JS_INPUT = re.compile(r"^js(\d+)_(.*)$", re.DOTALL)


def split_js_input(raw: str) -> tuple[int, str] | None:
    """'js2_button28' -> (2, 'button28'); 'js2_ ' -> (2, ''); non-joystick -> None."""
    m = _JS_INPUT.match(raw)
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip().lower()


def normalize_product(product: str) -> str:
    """' VKBsim Gladiator EVO  R    {0200231D-...}' -> 'VKBsim Gladiator EVO R'."""
    product = re.sub(r"\{[^}]*\}", "", product)
    return " ".join(product.split())


class BindingProfile:
    """An actionmaps.xml document — the game's live profile file or an
    exported layout (both share the same <actionmap>/<rebind> structure;
    the live file nests it under <ActionProfiles>).
    """

    def __init__(self, root: ET.Element):
        self.root = root

    @classmethod
    def from_bytes(cls, data: bytes) -> "BindingProfile":
        return cls(ET.fromstring(data))

    @classmethod
    def load(cls, path: Path) -> "BindingProfile":
        return cls.from_bytes(path.read_bytes())

    def to_bytes(self) -> bytes:
        ET.indent(self.root, space=" ")
        return ET.tostring(self.root, encoding="utf-8")

    @property
    def _container(self) -> ET.Element:
        profiles = self.root.find("ActionProfiles")
        return profiles if profiles is not None else self.root

    def joystick_products(self) -> dict[int, str]:
        out = {}
        for opt in self._container.findall("options"):
            if opt.get("type") == "joystick" and opt.get("Product"):
                out[int(opt.get("instance"))] = normalize_product(opt.get("Product"))
        return out

    def rebinds(self) -> dict[ActionKey, dict[int, str]]:
        out: dict[ActionKey, dict[int, str]] = {}
        for am in self._container.findall("actionmap"):
            for a in am.findall("action"):
                for r in a.findall("rebind"):
                    parsed = split_js_input(r.get("input", ""))
                    if parsed:
                        out.setdefault((am.get("name"), a.get("name")), {})[parsed[0]] = parsed[1]
        return out

    def set_input(self, game: GameData, key: ActionKey, instance: int, inp: str) -> None:
        """Binds action `key` on joystick `instance` to `inp` ('' unbinds),
        keeping the file a minimal diff against the defaults.
        """
        default = game.action(key).default_js if instance == 1 else ""
        container = self._container
        am = next((m for m in container.findall("actionmap") if m.get("name") == key[0]), None)
        action = None
        if am is not None:
            action = next((a for a in am.findall("action") if a.get("name") == key[1]), None)
        rebind = None
        if action is not None:
            for r in action.findall("rebind"):
                parsed = split_js_input(r.get("input", ""))
                if parsed and parsed[0] == instance:
                    rebind = r
                    break

        if inp == default:
            if rebind is not None:
                action.remove(rebind)
                if len(action) == 0:
                    am.remove(action)
                if len(am) == 0:
                    container.remove(am)
            return

        if am is None:
            am = ET.SubElement(container, "actionmap", {"name": key[0]})
        if action is None:
            action = ET.SubElement(am, "action", {"name": key[1]})
        if rebind is None:
            rebind = ET.SubElement(action, "rebind")
        rebind.set("input", f"js{instance}_{inp or ' '}")


# -- effective bindings ----------------------------------------------------

@dataclass
class Bindings:
    by_input: dict[tuple[int, str], list[ActionDef]] = field(default_factory=dict)
    by_action: dict[ActionKey, dict[int, str]] = field(default_factory=dict)


def effective_bindings(game: GameData, profile: BindingProfile) -> Bindings:
    per_action: dict[ActionKey, dict[int, str]] = {
        key: {1: a.default_js} for key, a in game.actions.items() if a.default_js
    }
    for key, devices in profile.rebinds().items():
        per_action.setdefault(key, {}).update(devices)

    by_input: dict[tuple[int, str], list[ActionDef]] = defaultdict(list)
    by_action: dict[ActionKey, dict[int, str]] = {}
    for key, devices in per_action.items():
        live = {inst: inp for inst, inp in devices.items() if inp}
        if not live:
            continue
        by_action[key] = live
        action = game.action(key)
        for inst, inp in live.items():
            by_input[(inst, inp)].append(action)

    for actions in by_input.values():
        actions.sort(key=lambda a: (not a.listed, a.group, a.label))
    return Bindings(by_input=dict(by_input), by_action=by_action)
