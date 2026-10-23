"""Loadout data from the game files: what every player ship can fit where, the
stats of every part that could go there, and how craftable parts are made.
Built once per game build by app.datahub and cached (read it with
datahub.read_game("loadoutdata", …)); the loadout editor and its calculator
(app.loadoutcalc) read only this.

Where things are:
- **Slots**: the vehicle definition XML (Data\\Scripts\\Entities\\Vehicles\\
  Implementations\\Xml, encrypted in Data.p4k, see app.p4k). Variants share a
  file: the ship's VehicleComponentParams names a modification, which may
  swap whole elements for a patch file's (matched by id) and then sets
  attributes by id ("Elems"); parts with skipPart="1" aren't fitted. A slot
  is a Part's ItemPort: size range, accepted types/subtypes, flags
  (uneditable, invisible), required tags. Hull HP: the Body part's damageMax.
- **Default parts**: the ship's SEntityComponentDefaultLoadoutParams, nested
  (guns on mounts and turrets, missiles in racks). What the parts outside the
  editable slots draw from the power plant (scanners, flight controller…) is
  the ship's basePower.
- **Slots on parts** (mounts, racks, turrets): the part's
  SItemPortContainerComponentParams; its own default children in its
  SEntityComponentDefaultLoadoutParams.
- **Part stats**: as app.shipdata reads them (power, coolant, shields,
  quantum), plus guns (app.crafting.alpha: damage by type per shot, fire
  rate, pellets; projectile speed × lifetime; ammo or capacitor), missiles
  (explosion damage, lock), component HP and the entity's uuid (UEX keys
  parts by it).
- **Recipes**: app.crafting.recipes for every part with a blueprint.

The publishing tool keeps a copy of this module; keep the two in step.
"""

from __future__ import annotations

import copy
import re
import uuid
import xml.etree.ElementTree as ET

from app import config, crafting, cryxml, p4k, shipdata
from app.datacore import DataCore

CACHE = config.CACHE_DIR / "loadoutdata"
FORMAT = 2  # 2: basePower (what the parts outside the editable slots draw)
VEHICLE_DIR = "Data\\Scripts\\Entities\\Vehicles\\Implementations\\Xml\\"

# Part types a loadout can hold (seats, doors, thrusters, lights… stay out).
TYPES = {"WeaponGun", "Turret", "TurretBase", "MissileLauncher", "BombLauncher", "Missile", "Bomb", "Shield",
         "PowerPlant", "Cooler", "QuantumDrive", "Radar", "WeaponDefensive", "WeaponMining", "TractorBeam",
         "SalvageHead", "LifeSupportGenerator", "JumpDrive"}
# Classes that aren't parts a player fits: AI, mission, test and display variants.
_SKIP = re.compile(r"(_AI_|_NPC|Template|_Test|Dummy|_Display|PLACEHOLDER|_Prop\b|_FPS_|_Hijacked|Mission)", re.I)


class LoadoutDataError(Exception):
    pass


def _components(rec: dict | None) -> dict[str, dict]:
    return {c.get("_type"): c for c in (rec or {}).get("Components") or [] if isinstance(c, dict)}


def _loc(table: dict[str, str], key, fallback: str = "") -> str:
    if isinstance(key, str) and key.startswith("@"):
        return table.get(key[1:].lower()) or fallback
    if isinstance(key, str) and key:
        return table.get(key.lower()) or fallback
    return fallback


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def entity_uuid(guid: bytes) -> str:
    """A DataCore record GUID as the text form UEX (and the game's logs) use."""
    return str(uuid.UUID(bytes=guid[7::-1] + guid[:7:-1]))


def _humanize(port: str) -> str:
    words = re.sub(r"^hardpoint_", "", port, flags=re.I).replace("_", " ").strip()
    return words[:1].upper() + words[1:]


# -- vehicle definitions ---------------------------------------------------------------------

def vehicle_files(p4k_path) -> dict[str, ET.Element]:
    """Every vehicle definition and patch file, by its path under the Xml folder in lower case
    ("aegs_gladius.xml", "modifications/rsi_constellation_taurus.xml")."""
    out = {}
    for name, data in p4k.iter_matching(p4k_path, lambda n: n.startswith(VEHICLE_DIR) and n.lower().endswith(".xml")):
        out[name[len(VEHICLE_DIR):].replace("\\", "/").lower()] = cryxml.parse(data)
    return out


def _set_attr(elem: ET.Element, name: str, value: str) -> None:
    for key in elem.attrib:
        if key.lower() == name.lower():
            elem.set(key, value)
            return
    elem.set(name, value)


def resolve_vehicle(files: dict[str, ET.Element], definition: str, modification: str = "") -> ET.Element | None:
    """The definition with the ship's modification applied (patch file, then attribute edits)."""
    key = definition.replace("\\", "/").lower().rsplit("implementations/xml/", 1)[-1]
    base = files.get(key)
    if base is None:
        return None
    root = copy.deepcopy(base)
    if not modification:
        return root
    mod = next((m for m in root.iter("Modification") if (m.get("name") or "").lower() == modification.lower()), None)
    if mod is None:
        return root
    patch_name = mod.get("patchFile") or mod.get("patchfile")
    if patch_name:
        patch = files.get(patch_name.replace("\\", "/").lower() + ".xml")
        if patch is not None:
            parents = {child: parent for parent in root.iter() for child in parent}
            by_id = {e.get("id"): e for e in root.iter() if e.get("id")}
            for top in patch:
                target = by_id.get(top.get("id") or "")
                if target is not None and target in parents:
                    parent = parents[target]
                    parent[list(parent).index(target)] = copy.deepcopy(top)
    by_id = {e.get("id"): e for e in root.iter() if e.get("id")}
    for elem in mod.iter("Elem"):
        target = by_id.get(elem.get("idRef") or "")
        if target is not None and elem.get("name"):
            _set_attr(target, elem.get("name"), elem.get("value") or "")
    return root


def _attr(elem: ET.Element, name: str, default: str = "") -> str:
    for key, value in elem.attrib.items():
        if key.lower() == name.lower():
            return value
    return default


def _parts(parts_elem: ET.Element | None):
    """Fitted parts, depth first (parts marked skipPart="1" and what's under them are not fitted)."""
    for part in parts_elem.findall("Part") if parts_elem is not None else []:
        if _attr(part, "skipPart") == "1":
            continue
        yield part
        yield from _parts(part.find("Parts"))


def _types(type_elems) -> list[list]:
    out = []
    for t in type_elems:
        kind = _attr(t, "type")
        if kind:
            subs = [s for s in re.split(r"[,\s]+", _attr(t, "subtypes")) if s]
            out.append([kind, subs])
    return out


def _flags(text: str) -> set[str]:
    return {f.lstrip("$").lower() for f in (text or "").split()}


def _xml_slot(part: ET.Element, port: ET.Element, loc: dict[str, str]) -> dict:
    name = part.get("name") or ""
    flags = _flags(_attr(port, "flags"))
    return {
        "id": name,
        "label": _loc(loc, _attr(port, "display_name"), _humanize(name)),
        "min": _int(_attr(port, "minSize")), "max": _int(_attr(port, "maxSize")),
        "types": _types(port.iter("Type")),
        "locked": "uneditable" in flags, "hidden": "invisible" in flags,
        "tags": _attr(port, "requiredTags").strip(),
    }


def _item_slot(port: dict, loc: dict[str, str]) -> dict:
    flags = _flags(port.get("Flags") or "")
    types = [[t.get("Type") or "", [s for s in t.get("SubTypes") or [] if s]] for t in port.get("Types") or []
             if isinstance(t, dict) and t.get("Type")]
    name = port.get("Name") or ""
    return {
        "id": name,
        "label": _loc(loc, port.get("DisplayName"), _humanize(name)),
        "min": _int(port.get("MinSize")), "max": _int(port.get("MaxSize")),
        "types": types,
        "locked": "uneditable" in flags, "hidden": "invisible" in flags,
        "tags": (port.get("RequiredPortTags") or "").strip(),
    }


def _relevant(slot: dict) -> bool:
    return any(t in TYPES for t, _subs in slot["types"])


def _entry_class(entry: dict) -> str:
    cls = entry.get("entityClassName") or ""
    ref = entry.get("entityClassReference")
    if not cls and isinstance(ref, str) and ref.startswith("@EntityClassDefinition."):
        cls = ref.split(".", 1)[1]
    return cls


def _defaults(loadout: dict | None) -> dict[str, tuple[str, dict | None]]:
    """port name (lower) → (part class, its own nested loadout)."""
    out = {}
    for entry in (loadout or {}).get("entries") or []:
        if isinstance(entry, dict) and entry.get("itemPortName"):
            out[str(entry["itemPortName"]).lower()] = (_entry_class(entry), entry.get("loadout"))
    return out


# -- parts -----------------------------------------------------------------------------------

class _Parts:
    def __init__(self, dc: DataCore, loc: dict[str, str]):
        self.dc, self.loc = dc, loc
        self.base = shipdata._Reader(dc, loc)
        self.items: dict[str, dict] = {}
        self._guids: dict[str, bytes] | None = None
        self._classes: dict[str, str] = {}          # lower → record's own case

    def guid(self, cls: str) -> bytes | None:
        if self._guids is None:
            self._guids = {}
            for name, _si, _ii, guid in self.dc.records():
                if name.startswith("EntityClassDefinition."):
                    own = name.split(".", 1)[1]
                    self._guids[own.lower()] = guid
                    self._classes[own.lower()] = own
        return self._guids.get(cls.lower())

    def own_case(self, cls: str) -> str:
        self.guid(cls)
        return self._classes.get(cls.lower(), cls)

    def part(self, cls: str) -> dict | None:
        """The part's entry (cached), or None for anything that isn't a loadout part."""
        key = cls.lower()
        if key in self.items:
            return self.items[key] or None
        cls = self.own_case(cls)
        info = self.base.item(cls)
        if not info or info["type"] not in TYPES:
            self.items[key] = {}
            return None
        comps = _components(self.dc.record("EntityClassDefinition." + cls, max_depth=10))
        attach = (comps.get("SAttachableComponentParams") or {}).get("AttachDef") or {}
        guid = self.guid(cls)
        out: dict = {
            "name": info["name"], "type": info["type"], "subtype": info["subtype"], "size": info["size"],
            "grade": info["grade"], "class": info["class"], "manufacturer": self._maker(attach.get("Manufacturer")),
            "tags": [t for t in str(attach.get("Tags") or "").split() if t],
            "uuid": entity_uuid(guid) if guid else "",
            "power": {"max": round(info.get("power_use", 0.0), 3), "min": round(info.get("power_min", 0.0), 3)},
        }
        self.items[key] = out                    # before the children: a part can't loop back to itself
        health = (comps.get("SHealthComponentParams") or {}).get("Health")
        if isinstance(health, (int, float)) and health > 0:
            out["health"] = round(float(health), 1)
        t = info["type"]
        if t == "WeaponGun":
            gun = self._gun(comps)
            if gun:
                out["gun"] = gun
        elif t in ("Missile", "Bomb"):
            out["missile"] = self._missile(comps)
        elif t == "Shield":
            shield = comps.get("SCItemShieldGeneratorParams") or {}
            out["shield"] = {"hp": info.get("shield_hp", 0.0), "regen": info.get("shield_regen", 0.0),
                             "damagedDelay": float(shield.get("DamagedRegenDelay") or 0),
                             "downedDelay": float(shield.get("DownedRegenDelay") or 0)}
        elif t == "PowerPlant":
            out["plant"] = {"segments": info.get("power_gen", 0.0)}
        elif t == "Cooler":
            out["cooler"] = {"coolant": info.get("coolant_gen", 0.0)}
        elif t == "QuantumDrive":
            out["quantum"] = {"speed": info.get("qd_speed", 0.0), "cooldown": info.get("qd_cooldown", 0.0)}
        ports = (comps.get("SItemPortContainerComponentParams") or {}).get("Ports") or []
        slots = [_item_slot(p, self.loc) for p in ports if isinstance(p, dict)]
        slots = [s for s in slots if _relevant(s)]
        if slots:
            out["slots"] = slots
            own = _defaults((comps.get("SEntityComponentDefaultLoadoutParams") or {}).get("loadout"))
            fitted = {s["id"]: own[s["id"].lower()][0].lower() for s in slots if own.get(s["id"].lower(), ("",))[0]}
            if fitted:
                out["defaults"] = fitted
                for child in fitted.values():
                    self.part(child)
        return out

    def _maker(self, ref) -> str:
        if not isinstance(ref, str) or not ref.startswith("@"):
            return ""
        rec = self.dc.record(ref[1:], max_depth=2) or {}
        name = _loc(self.loc, (rec.get("Localization") or {}).get("Name"))
        return "" if name.startswith("@") else name

    def _gun(self, comps: dict) -> dict | None:
        hit = crafting.alpha(self.dc, comps)
        if not hit:
            return None
        gun: dict = {"mode": hit.get("mode", ""), "pellets": hit.get("pellets", 1),
                     "alpha": hit.get("perPellet", {}), "rpm": hit.get("rpm")}
        if hit.get("mode") == "beam":
            gun["beamDps"] = hit.get("dps")
        for key in ("chargeTime", "charged"):
            if hit.get(key) is not None:
                gun[key] = hit[key]
        weapon = comps.get("SCItemWeaponComponentParams") or {}
        container = comps.get("SAmmoContainerComponentParams") or {}
        ref = container.get("ammoParamsRecord")
        if isinstance(ref, str) and ref.startswith("@"):
            ammo = self.dc.record(ref[1:], max_depth=3) or {}
            speed, life = ammo.get("speed"), ammo.get("lifetime")
            if isinstance(speed, (int, float)) and isinstance(life, (int, float)):
                gun["speed"] = round(float(speed), 1)
                gun["range"] = round(float(speed) * float(life))
        if container.get("maxAmmoCount"):
            gun["ammo"] = int(container["maxAmmoCount"])
        regen = weapon.get("weaponRegenConsumerParams") or {}
        if regen.get("maxAmmoLoad"):
            gun["capacitor"] = {"shots": float(regen.get("maxAmmoLoad") or 0), "regen": float(regen.get("maxRegenPerSec") or 0),
                                "cooldown": float(regen.get("regenerationCooldown") or 0)}
        return gun

    @staticmethod
    def _missile(comps: dict) -> dict:
        params = comps.get("SCItemMissileParams") or {}
        damage = ((params.get("explosionParams") or {}).get("damage")) or {}
        per = {k.removeprefix("Damage").lower(): round(float(v), 2) for k, v in damage.items()
               if k.startswith("Damage") and isinstance(v, (int, float)) and v > 0}
        target = params.get("targetingParams") or {}
        return {"damage": per, "lockTime": float(target.get("lockTime") or 0),
                "lockRange": float(target.get("lockRangeMax") or 0),
                "speed": float(((params.get("GCSParams") or {}).get("linearSpeed")) or 0),
                "signal": str(target.get("trackingSignalType") or "")}

    def candidates(self, progress) -> None:
        """Every player-fittable part of a loadout type, so the editor can offer them all."""
        names = self.dc.record_names("EntityClassDefinition.")
        for i, rec_name in enumerate(names):
            if i % 5000 == 0:
                progress(f"parts {i}/{len(names)}")
            cls = rec_name.split(".", 1)[1]
            if _SKIP.search(cls):
                continue
            rec = self.dc.record(rec_name, max_depth=4) or {}
            attach = (_components(rec).get("SAttachableComponentParams") or {}).get("AttachDef") or {}
            if attach.get("Type") not in TYPES:
                continue
            name = _loc(self.loc, (attach.get("Localization") or {}).get("Name"))
            if not name or name.startswith("@") or "placeholder" in name.lower():
                continue
            self.part(cls)


# -- ships -----------------------------------------------------------------------------------

class _Ships:
    def __init__(self, dc: DataCore, loc: dict[str, str], parts: _Parts, files: dict[str, ET.Element]):
        self.dc, self.loc, self.parts, self.files = dc, loc, parts, files

    def ship(self, cls: str) -> dict | None:
        comps = _components(self.dc.record("EntityClassDefinition." + cls, max_depth=24))
        vehicle = comps.get("VehicleComponentParams") or {}
        root = resolve_vehicle(self.files, str(vehicle.get("vehicleDefinition") or ""), str(vehicle.get("modification") or ""))
        if root is None:
            return None
        defaults = _defaults((comps.get("SEntityComponentDefaultLoadoutParams") or {}).get("loadout"))
        slots = []
        for part in _parts(root.find("Parts")):
            port = part.find("ItemPort")
            if port is None:
                continue
            slot = _xml_slot(part, port, self.loc)
            fitted, nested = defaults.get(slot["id"].lower(), ("", None))
            if not _relevant(slot) and not (fitted and self.parts.part(fitted)):
                continue
            self._fill(slot, fitted, nested, 0)
            slots.append(slot)
        hull = _hull(root)
        kept = {s["id"].lower() for s in slots}
        base = {"max": 0.0, "min": 0.0}
        for port, (fitted, nested) in defaults.items():
            if port not in kept:
                self._power(fitted, nested, base, 0)
        return {"hull": round(hull, 1), "slots": slots, "basePower": {k: round(v, 3) for k, v in base.items()}}

    def _power(self, cls: str, nested: dict | None, acc: dict, depth: int) -> None:
        """Adds what a part outside the editable slots (and what it holds) draws from the power plant."""
        info = self.parts.base.item(self.parts.own_case(cls)) if cls else None
        if info and info["type"] != "WeaponGun":
            acc["max"] += info.get("power_use", 0.0)
            acc["min"] += info.get("power_min", 0.0)
        if depth < 6:
            for sub, sub_nested in _defaults(nested).values():
                self._power(sub, sub_nested, acc, depth + 1)

    def _fill(self, slot: dict, fitted: str, nested: dict | None, depth: int) -> None:
        """Puts the default part in the slot, and the slots that part brings (with their defaults)."""
        part = self.parts.part(fitted) if fitted else None
        slot["default"] = fitted.lower() if part else ""
        if not part or depth > 4:
            return
        own = _defaults(nested)
        children = []
        for child in part.get("slots") or []:
            child = dict(child)
            sub, sub_nested = own.get(child["id"].lower(), ("", None))
            if not sub:
                sub = (part.get("defaults") or {}).get(child["id"], "")
            self._fill(child, sub, sub_nested, depth + 1)
            children.append(child)
        if children:
            slot["children"] = children


def _hull(root: ET.Element) -> float:
    """The main body's HP: the part named Body, else the first fitted part that has HP."""
    parts = list(_parts(root.find("Parts")))
    body = next((p for p in parts if (p.get("name") or "").lower() == "body"), None)
    if body is None:
        body = next((p for p in parts if float(_attr(p, "damageMax") or 0) > 0), None)
    return float(_attr(body, "damageMax") or 0) if body is not None else 0.0


def player_ships(dc: DataCore, catalogue_classes: set[str]) -> list[str]:
    """Vehicles a player can own (same rule as app.shipdata)."""
    prefixes = {c.split("_", 1)[0] for c in catalogue_classes}
    wanted = []
    for rec_name in dc.record_names("EntityClassDefinition."):
        cls = rec_name.split(".", 1)[1]
        if cls.lower() in catalogue_classes:
            wanted.append(cls)
        elif cls.split("_", 1)[0].lower() in prefixes and not shipdata._SKIP.search(cls):
            types = {c.get("_type") for c in (dc.record(rec_name, max_depth=1) or {}).get("Components") or []
                     if isinstance(c, dict)}
            if {"VehicleComponentParams", "SEntityComponentDefaultLoadoutParams"} <= types:
                wanted.append(cls)
    return sorted(set(wanted))


def build(game, progress, catalogue_classes: set[str]) -> dict:
    """Slots and parts of every player vehicle, all loadout parts, and the recipes of craftable ones."""
    dc = game.dc
    progress("vehicle definitions")
    files = vehicle_files(game.p4k_path)
    if not files:
        raise LoadoutDataError("No vehicle definitions found in Data.p4k")
    parts = _Parts(dc, game.loc)
    ships_reader = _Ships(dc, game.loc, parts, files)
    ships = {}
    wanted = player_ships(dc, catalogue_classes)
    for i, cls in enumerate(wanted):
        if i % 50 == 0:
            progress(f"ships {i}/{len(wanted)}")
        data = ships_reader.ship(cls)
        if data and data["slots"]:
            ships[cls.lower()] = data
    parts.candidates(progress)
    items = {k: v for k, v in parts.items.items() if v}
    progress("recipes")
    recipes = crafting.recipes(dc, game.loc, set(items))
    props = crafting.properties(dc, game.loc)
    for cls, recipe in recipes.items():
        wanted_props = {m.get("property") for s in recipe["slots"] for m in s.get("modifiers") or [] if m.get("property")}
        info = parts.base.item(parts.own_case(cls))
        recipe["base"] = crafting.base_values(dc, parts.own_case(cls), info, wanted_props, props)
        items[cls]["craftable"] = True
    used = {m.get("property") for r in recipes.values() for s in r["slots"] for m in s.get("modifiers") or []}
    return {"ships": ships, "items": items, "recipes": recipes,
            "properties": {k: v for k, v in props.items() if k in used}}


class LoadoutData:
    def __init__(self, data: dict):
        self.ships: dict[str, dict] = data.get("ships") or {}
        self.items: dict[str, dict] = data.get("items") or {}
        self.recipes: dict[str, dict] = data.get("recipes") or {}
        self.properties: dict[str, dict] = data.get("properties") or {}

    def ship(self, class_id: str) -> dict | None:
        return self.ships.get(class_id.lower()) if class_id else None
