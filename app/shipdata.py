"""Ship details from the game files (Data.p4k → Game2.dcb): each ship's
default loadout and its stats, for the My Ships details page.

Built once per game build for every player vehicle by app.datahub, which
caches it (read it with datahub.read_game("shipdata", …)). Item names come from the
packed global.ini (no StarStrings prefixes).

Where things are:
- loadout: SEntityComponentDefaultLoadoutParams (nested: guns sit on mounts
  and turrets, missiles in racks);
- speeds: the flight controller's IFCSParams (scmSpeed, maxSpeed, boost,
  angularVelocity = pitch/roll/yaw);
- shields: SCItemShieldGeneratorParams of the shield generators;
- power and cooling: each item's ItemResourceComponentParams "Online" state
  (power plants generate Power segments, coolers Coolant; consumers draw
  segments, at least minimumConsumptionFraction of them when on);
- fuel: the tanks' ResourceContainer capacity (SCU);
- quantum: SCItemQuantumDriveParams.
Hull HP isn't here (it's in the vehicle XML, which the p4k reader can't
open); the details page takes it from the ship catalogue.
"""

from __future__ import annotations

import re

from app import config
from app.datacore import DataCore

CACHE = config.CACHE_DIR / "shipdata"
FORMAT = 3

# Loadout groups shown on the details page, by the item's AttachDef Type.
GROUPS = [
    ("weapons", "Weapons", {"WeaponGun"}),
    ("turrets", "Turrets", set()),               # guns below a crewed or remote turret
    ("missiles", "Missiles", {"Missile", "MissileLauncher"}),
    ("systems", "Systems", {"PowerPlant", "Cooler", "Shield", "QuantumDrive", "JumpDrive", "Radar",
                            "LifeSupportGenerator"}),
    ("utility", "Utility", {"WeaponMining", "SalvageHead", "TractorBeam", "WeaponDefensive",
                            "SalvageModifier", "MiningModifier"}),
]
_GROUP_OF = {t: key for key, _title, types in GROUPS for t in types}
_TURRET_SUBTYPES = {"MannedTurret", "PDCTurret", "RemoteTurret"}
_GRADES = {1: "A", 2: "B", 3: "C", 4: "D"}


class ShipDataError(Exception):
    pass


def _components(rec: dict | None) -> dict[str, dict]:
    return {c.get("_type"): c for c in (rec or {}).get("Components") or [] if isinstance(c, dict)}


def _loc(table: dict[str, str], key, fallback: str) -> str:
    if isinstance(key, str) and key.startswith("@"):
        return table.get(key[1:].lower()) or fallback
    return fallback


def _amount(delta_amount: dict | None) -> float:
    rps = (delta_amount or {}).get("resourceAmountPerSecond") or {}
    value = rps.get("units", rps.get("standardResourceUnits", 0))
    return float(value or 0)


class _Reader:
    def __init__(self, dc: DataCore, loc: dict[str, str]):
        self.dc, self.loc = dc, loc
        self._items: dict[str, dict | None] = {}

    def item(self, cls: str) -> dict | None:
        """What we need of one item: name, type, size, grade, class, and its
        stats-relevant parameters."""
        if cls in self._items:
            return self._items[cls]
        comps = _components(self.dc.record("EntityClassDefinition." + cls, max_depth=7))
        attach = (comps.get("SAttachableComponentParams") or {}).get("AttachDef")
        if not attach:
            self._items[cls] = None
            return None
        localization = attach.get("Localization") or {}
        desc = _loc(self.loc, localization.get("Description"), "")
        family = re.search(r"Class:\s*([^\\\n]+)", desc)
        info = {
            "name": _loc(self.loc, localization.get("Name"), cls),
            "type": attach.get("Type") or "",
            "subtype": attach.get("SubType") or "",
            "size": attach.get("Size") or 0,
            "grade": _GRADES.get(attach.get("Grade"), ""),
            "class": family.group(1).strip() if family else "",
        }
        # Power / coolant / shield deltas while online.
        for state in (comps.get("ItemResourceComponentParams") or {}).get("states") or []:
            if state.get("name") != "Online":
                continue
            for d in state.get("deltas") or []:
                if not isinstance(d, dict):
                    continue
                use, make = d.get("consumption"), d.get("generation")
                if use and use.get("resource") == "Power":
                    info["power_use"] = _amount(use)
                    info["power_min"] = _amount(use) * float(d.get("minimumConsumptionFraction") or 0)
                if make and make.get("resource") == "Power":
                    info["power_gen"] = _amount(make)
                if make and make.get("resource") == "Coolant":
                    info["coolant_gen"] = _amount(make)
        shield = comps.get("SCItemShieldGeneratorParams")
        if shield:
            info["shield_hp"] = float(shield.get("MaxShieldHealth") or 0)
            info["shield_regen"] = float(shield.get("MaxShieldRegen") or 0)
        qd = (comps.get("SCItemQuantumDriveParams") or {}).get("params")
        if qd:
            info["qd_speed"] = float(qd.get("driveSpeed") or 0)
            info["qd_cooldown"] = float(qd.get("cooldownTime") or 0)
        container = comps.get("ResourceContainer")
        if container and info["type"] in ("FuelTank", "QuantumFuelTank"):
            info["fuel_scu"] = float(((container.get("capacity") or {}).get("standardCargoUnits")) or 0)
        ifcs = comps.get("IFCSParams")
        if ifcs:
            ang = (ifcs.get("speedProfile") or {}).get("angularVelocity") or {}
            info["flight"] = {
                "scm": ifcs.get("scmSpeed"), "max": ifcs.get("maxSpeed"),
                "boost_fwd": ifcs.get("boostSpeedForward"), "boost_back": ifcs.get("boostSpeedBackward"),
                "pitch": ang.get("x"), "roll": ang.get("y"), "yaw": ang.get("z"),
            }
        self._items[cls] = info
        return info

    def ship(self, cls: str) -> dict | None:
        # Deep: turrets, mounts and racks nest loadouts several levels down.
        comps = _components(self.dc.record("EntityClassDefinition." + cls, max_depth=24))
        loadout = (comps.get("SEntityComponentDefaultLoadoutParams") or {}).get("loadout")
        if not loadout:
            return None
        rows: dict[tuple, dict] = {}        # (group, name, size, grade) → row with a count
        totals = {"power_gen": 0.0, "power_max": 0.0, "power_min": 0.0, "coolant_gen": 0.0,
                  "shield_hp": 0.0, "shield_regen": 0.0, "shields": 0, "hydrogen_scu": 0.0,
                  "quantum_scu": 0.0}
        stats: dict = {}

        def walk(node, in_turret: bool, depth: int) -> None:
            if not isinstance(node, dict) or depth > 10:
                return
            for entry in node.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                item_cls = entry.get("entityClassName") or ""
                ref = entry.get("entityClassReference")
                if not item_cls and isinstance(ref, str) and ref.startswith("@EntityClassDefinition."):
                    item_cls = ref.split(".", 1)[1]
                info = self.item(item_cls) if item_cls else None
                turret = in_turret
                if info:
                    t = info["type"]
                    turret = in_turret or t == "TurretBase" or (t == "Turret" and info["subtype"] in _TURRET_SUBTYPES)
                    group = _GROUP_OF.get(t)
                    if t == "WeaponDefensive" and "ammo" in info["name"].lower():
                        group = None                # the launchers are listed, not their ammo
                    if group == "weapons" and turret:
                        group = "turrets"
                    if group:
                        key = (group, info["name"], info["size"], info["grade"])
                        row = rows.setdefault(key, {"group": group, "name": info["name"], "size": info["size"],
                                                    "grade": info["grade"], "class": info["class"],
                                                    "type": t, "count": 0})
                        row["count"] += 1
                    if t != "WeaponGun":         # weapons draw from their own pool
                        totals["power_max"] += info.get("power_use", 0)
                        totals["power_min"] += info.get("power_min", 0)
                    totals["power_gen"] += info.get("power_gen", 0)
                    totals["coolant_gen"] += info.get("coolant_gen", 0)
                    if "shield_hp" in info:
                        totals["shield_hp"] += info["shield_hp"]
                        totals["shield_regen"] += info["shield_regen"]
                        totals["shields"] += 1
                    if t == "FuelTank":
                        totals["hydrogen_scu"] += info.get("fuel_scu", 0)
                    elif t == "QuantumFuelTank":
                        totals["quantum_scu"] += info.get("fuel_scu", 0)
                    if "flight" in info and "flight" not in stats:
                        stats["flight"] = info["flight"]
                    if t == "QuantumDrive" and "quantum" not in stats:
                        stats["quantum"] = {"speed": info.get("qd_speed"), "cooldown": info.get("qd_cooldown")}
                walk(entry.get("loadout"), turret, depth + 1)

        walk(loadout, False, 0)
        stats.update({k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()})
        order = {key: i for i, (key, _t, _types) in enumerate(GROUPS)}
        loadout_rows = sorted(rows.values(), key=lambda r: (order[r["group"]], -(r["size"] or 0), r["name"]))
        return {"stats": stats, "loadout": loadout_rows}


# Vehicles a player can own: by manufacturer prefix, minus AI, mission and
# display variants (the ship list's own class ids are always included).
_SKIP = re.compile(r"(_AI_|_PU_|Template|Unmanned|_NPC|_Wreck|_Derelict|Mission|Hijacked|_FW_|_Tutorial|_Test"
                   r"|_Dummy|_Prop|EntitySpawner|vehicle_display|Paint_)", re.I)


def build(game, progress, catalogue_classes: set[str]) -> dict:
    """Stats and default loadouts of every player vehicle in the game files
    (app.datahub.GameFiles); the hub caches them per patch, so ships that
    join the ship list later are covered without reading the files again."""
    dc = game.dc
    reader = _Reader(dc, game.loc)
    prefixes = {c.split("_", 1)[0] for c in catalogue_classes}
    wanted = []
    for rec_name in dc.record_names("EntityClassDefinition."):
        cls = rec_name.split(".", 1)[1]
        if cls.lower() in catalogue_classes:
            wanted.append(cls)
        elif cls.split("_", 1)[0].lower() in prefixes and not _SKIP.search(cls):
            types = {c.get("_type") for c in (dc.record(rec_name, max_depth=1) or {}).get("Components") or []
                     if isinstance(c, dict)}
            if {"VehicleComponentParams", "SEntityComponentDefaultLoadoutParams"} <= types:
                wanted.append(cls)
    ships = {}
    for i, cls in enumerate(sorted(set(wanted))):
        if i % 50 == 0:
            progress(f"{i}/{len(wanted)} ships")
        data = reader.ship(cls)
        if data:
            ships[cls.lower()] = data
    return {"ships": ships}


class ShipData:
    def __init__(self, data: dict):
        self._ships: dict[str, dict] = data.get("ships") or {}

    def get(self, class_id: str) -> dict | None:
        return self._ships.get(class_id.lower()) if class_id else None
