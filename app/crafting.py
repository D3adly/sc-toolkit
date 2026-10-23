"""What crafting changes, as the game shows it, and what it costs (recipes).

Per crafting property (CraftingGameplayPropertyDef: "GPP_Weapon_FireRate"…): its display unit and how
the game turns the modifier into what it shows (a value, a percent change, a negated percent change,
a scaled value). Per crafted item: the base value of every property the game shows as a value, in
the units it shows (scale applied), so a quality's factor or addition gives the crafted item's figure.

Which item field a property changes isn't in the game data (the game's code knows); the map below
is ours, checked against item records. Properties the game shows as a percent only have no base value,
except a ship gun's Impact Force (damage), whose base is its alpha.

Recipes (recipes()): per crafted item, the first tier's craft time and slots: each slot's options (a
resource in SCU or a number of items, with a minimum quality and the quality steps the game rounds to)
and the stats its quality changes (ranges of quality → factor or addition). The publishing tool keeps
a copy of this module; keep the two in step.
"""

from __future__ import annotations

import re

from app.datacore import DataCore

# How the game shows a property: value (base × factor, or + addition), percent (factor − 1), or
# negated percent (1 − factor: a smaller value reads as an improvement).
_DISPLAY = {
    None: "value",
    "CraftingDisplayTransformation_Scale": "value",
    "CraftingDisplayTransformation_ConvertFactorToPercentChange": "percent",
    "CraftingDisplayTransformation_ConvertFactorToNegatedPercentChange": "negpercent",
    "CraftingDisplayTransformation_Sequence": "percent",
}


def _loc(table: dict[str, str], key) -> str:
    if isinstance(key, str) and key.startswith("@"):
        return table.get(key[1:].lower(), "")
    return ""


def properties(dc: DataCore, loc: dict[str, str]) -> dict[str, dict]:
    """GPP id → {unit, display, scale}: unit is the game's format with the number taken out
    ("RPM", "ºC", "Mm/s"…), signed when the game prints a sign (temperatures)."""
    out = {}
    for name in dc.record_names("CraftingGameplayPropertyDef."):
        rec = dc.record(name, max_depth=4) or {}
        transform = rec.get("displayTransformation") or {}
        fmt = _loc(loc, rec.get("unitFormat"))
        unit = re.sub(r"%[-+ 0#]*\d*(?:\.\d+)?f", "", fmt).replace("%%", "%").strip()
        out[name.split(".", 1)[1]] = {
            "unit": "" if unit == "%" else unit,
            "signed": "%+" in fmt,
            "display": _DISPLAY.get(transform.get("_type"), "percent"),
            "scale": float(transform["scale"]) if isinstance(transform.get("scale"), (int, float)) else 1.0,
        }
    # Our base for damage mitigation is the share of damage taken away, in percent.
    if "GPP_Armor_DamageMitigation" in out:
        out["GPP_Armor_DamageMitigation"]["unit"] = "%"
    return out


def fire(action: dict | None) -> dict:
    """A fire mode's cadence: {mode, rpm, pellets}, plus chargeTime and chargedMultiplier for charged
    modes (no steady rate: damage grows with the charge). A sequence's rate is its entries' delays
    (RPM or seconds) over the shots they fire, not its inner action's own fireRate."""
    if not isinstance(action, dict):
        return {}
    kind = str(action.get("_type") or "")
    if kind == "SWeaponActionDynamicConditionParams":
        return fire(action.get("defaultWeaponAction"))
    if kind == "SWeaponActionParallelParams":
        parts = [fire(a) for a in action.get("weaponActions") or [] if isinstance(a, dict)]
        rates = [p["rpm"] for p in parts if p.get("rpm")]
        return {"mode": parts[0]["mode"] if parts else "parallel", "rpm": min(rates) if rates else None,
                "pellets": sum(int(p.get("pellets") or 1) for p in parts) or 1}
    if kind == "SWeaponActionFireBeamParams":
        dps = action.get("damagePerSecond") or {}
        per = {k.removeprefix("Damage").lower(): float(v) for k, v in dps.items()
               if k.startswith("Damage") and isinstance(v, (int, float)) and v > 0}
        return {"mode": "beam", "rpm": None, "pellets": 1, "beam": per}
    if kind == "SWeaponActionSequenceParams":
        shots, seconds, pellets = 0, 0.0, 1
        for entry in action.get("sequenceEntries") or []:
            if not isinstance(entry, dict):
                continue
            reps = int(entry.get("repetitions") or 1)
            delay = float(entry.get("delay") or 0)
            interval = (60 / delay if delay else 0) if entry.get("unit") == "RPM" else delay
            shots += reps
            seconds += interval * reps
            inner = entry.get("weaponAction") or {}
            pellets = max(pellets, int(((inner.get("launchParams") or {}).get("pelletCount")) or 1))
        return {"mode": "sequence", "rpm": round(60 * shots / seconds, 2) if seconds else None, "pellets": pellets}
    if kind == "SWeaponActionFireChargedParams":
        inner = action.get("weaponAction") or {}
        mult = (action.get("maxChargeModifier") or {}).get("damageMultiplier")
        rate = inner.get("fireRate")
        return {"mode": "charged", "rpm": None, "pellets": int(((inner.get("launchParams") or {}).get("pelletCount")) or 1),
                # The shot's own rate (how fast it can fire again), what Fire Rate changes on a charged gun.
                "shotRpm": float(rate) if isinstance(rate, (int, float)) and rate > 0 else None,
                "chargeTime": action.get("chargeTime"), "chargedMultiplier": float(mult) if isinstance(mult, (int, float)) else None}
    rate = action.get("fireRate")
    mode = kind.removeprefix("SWeaponActionFire").removesuffix("Params").lower() or "single"
    if kind == "SWeaponActionFireBurstParams" and isinstance(rate, (int, float)) and rate > 0:
        # Sustained: the burst's shots over the time they take plus the pause after it.
        shots = int(action.get("shotCount") or 1)
        cycle = shots * 60 / rate + float(action.get("cooldownTime") or 0)
        return {"mode": "burst", "rpm": round(60 * shots / cycle, 2), "burstRpm": float(rate), "shots": shots,
                "pellets": int(((action.get("launchParams") or {}).get("pelletCount")) or 1)}
    return {"mode": mode, "rpm": float(rate) if isinstance(rate, (int, float)) and rate > 0 else None,
            "pellets": int(((action.get("launchParams") or {}).get("pelletCount")) or 1)}


def alpha(dc: DataCore, comps: dict[str, dict]) -> dict | None:
    """A gun's damage per trigger pull in its primary fire mode: its ammo's damage per projectile (by
    type) times the projectiles one shot launches, with the mode's rate and so its DPS. Ship guns hold
    their ammo; personal weapons take it from their magazine."""
    weapon = comps.get("SCItemWeaponComponentParams") or {}
    container = comps.get("SAmmoContainerComponentParams") or {}
    if not container.get("ammoParamsRecord") and isinstance(weapon.get("ammoContainerRecord"), str):
        mag = _components(dc.record(weapon["ammoContainerRecord"].lstrip("@"), max_depth=4))
        container = mag.get("SAmmoContainerComponentParams") or {}
    mode = fire((weapon.get("fireActions") or [None])[0])
    if mode.get("mode") == "beam":
        # A beam deals damage per second as long as it's held: no shots.
        beam = mode.get("beam") or {}
        return {"mode": "beam", "pellets": 1, "perPellet": {k: round(v, 4) for k, v in beam.items()}, "total": None,
                "rpm": None, "dps": round(sum(beam.values()), 2)} if beam else None
    ref = container.get("ammoParamsRecord")
    if not isinstance(ref, str) or not ref.startswith("@"):
        return None
    ammo = dc.record(ref[1:], max_depth=8) or {}
    projectile = ammo.get("projectileParams") or {}
    # A hit's damage, plus its detonation's (distortion guns do theirs as an explosion).
    explosion = ((projectile.get("detonationParams") or {}).get("explosionParams") or {}).get("damage") or {}
    per: dict[str, float] = {}
    for damage in (projectile.get("damage") or {}, explosion):
        for k, v in damage.items():
            if k.startswith("Damage") and isinstance(v, (int, float)) and v >= 0.01:
                key = k.removeprefix("Damage").lower()
                per[key] = per.get(key, 0.0) + float(v)
    if not per:
        return None
    pellets = int(mode.get("pellets") or 1)
    total = round(sum(per.values()) * pellets, 4)
    out = {"pellets": pellets, "perPellet": {k: round(v, 4) for k, v in per.items()}, "total": total,
           "mode": mode.get("mode", ""), "rpm": mode.get("rpm")}
    if mode.get("rpm"):
        out["dps"] = round(total * mode["rpm"] / 60, 2)
    if mode.get("mode") == "charged":
        out["chargeTime"] = mode.get("chargeTime")
        if mode.get("chargedMultiplier"):
            out["charged"] = round(total * mode["chargedMultiplier"], 4)
    return out


def _components(rec: dict | None) -> dict[str, dict]:
    return {c.get("_type"): c for c in (rec or {}).get("Components") or [] if isinstance(c, dict)}


def _first(obj, key: str):
    """The first value of `key` anywhere inside obj (depth-first)."""
    if isinstance(obj, dict):
        if isinstance(obj.get(key), (int, float)) and not isinstance(obj.get(key), bool):
            return obj[key]
        for v in obj.values():
            found = _first(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _first(v, key)
            if found is not None:
                return found
    return None


def _first_dict(obj, type_name: str) -> dict | None:
    """The first dict of that _type anywhere inside obj."""
    if isinstance(obj, dict):
        if obj.get("_type") == type_name:
            return obj
        for v in obj.values():
            found = _first_dict(v, type_name)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _first_dict(v, type_name)
            if found is not None:
                return found
    return None


def _ref(obj, prefix: str) -> str | None:
    if isinstance(obj, str):
        return obj if obj.startswith(prefix) else None
    for v in (obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else []):
        found = _ref(v, prefix)
        if found:
            return found
    return None


def base_values(dc: DataCore, entity_class: str, item_info: dict | None, wanted: set[str], props: dict[str, dict]) -> dict[str, float]:
    """The crafted item's value of each wanted property the game shows as a value, in display units."""
    rec = dc.record("EntityClassDefinition." + entity_class, max_depth=9)
    comps = _components(rec)
    info = item_info or {}
    clothing = comps.get("SCItemClothingParams") or {}
    weapon = comps.get("SCItemWeaponComponentParams") or {}
    first_action = (weapon.get("fireActions") or [None])[0]
    qd = comps.get("SCItemQuantumDriveParams") or {}
    # Salvage scrapers are attachments: their stats are the weapon modifier they apply.
    scraper = _first_dict(comps.get("EntityComponentAttachableModifierParams"), "SSalvageModifier")
    raw: dict[str, float | None] = {
        "GPP_Weapon_FireRate": fire(first_action).get("rpm") or fire(first_action).get("shotRpm"),
        "GPP_Health_MaxHealth": (comps.get("SHealthComponentParams") or {}).get("Health"),
        "GPP_Armor_TemperatureMax": (clothing.get("TemperatureResistance") or {}).get("MaxResistance"),
        "GPP_Armor_TemperatureMin": (clothing.get("TemperatureResistance") or {}).get("MinResistance"),
        "GPP_Armor_RadiationCapacity": (clothing.get("RadiationResistance") or {}).get("MaximumRadiationCapacity"),
        "GPP_Armor_RadiationDissipation": (clothing.get("RadiationResistance") or {}).get("RadiationDissipationRate"),
        "GPP_Shield_MaxHealth": (comps.get("SCItemShieldGeneratorParams") or {}).get("MaxShieldHealth"),
        # Already in resource units (shipdata's reading), which is what the game shows.
        "GPP_ItemResource_PowerGeneration": info.get("power_gen"),
        "GPP_ItemResource_CoolantGeneration": info.get("coolant_gen"),
        "GPP_Quantum_Speed": (qd.get("params") or {}).get("driveSpeed"),
        "GPP_Quantum_FuelRequirement": qd.get("quantumFuelRequirement"),
        "GPP_Radar_MinAimAssistDistance": _first(comps.get("SCItemRadarComponentParams"), "distanceMinAssignment"),
        "GPP_Radar_MaxAimAssistDistance": _first(comps.get("SCItemRadarComponentParams"), "distanceMaxAssignment"),
        "GPP_Weapon_Tractor_MaxDist": _first(first_action, "maxDistance"),
        "GPP_Weapon_Tractor_FullStrengthDist": _first(first_action, "fullStrengthDistance"),
        "GPP_Weapon_Tractor_Force": _first(first_action, "maxForce"),
        "GPP_Weapon_Tractor_MaxVolume": _first(first_action, "maxVolume"),
        "GPP_Weapon_HullScraping_Speed": (scraper or {}).get("salvageSpeedMultiplier"),
        "GPP_Weapon_HullScraping_Radius": (scraper or {}).get("radiusMultiplier"),
        "GPP_Weapon_HullScraping_Efficiency": (scraper or {}).get("extractionEfficiency"),
    }
    # Armour: the share of damage its resistance macro takes away (the physical one), in percent.
    if "GPP_Armor_DamageMitigation" in wanted:
        macro = _ref(comps.get("SCItemSuitArmorParams"), "@DamageResistanceMacro.")
        res = (dc.record(macro[1:], max_depth=3) or {}).get("damageResistance") if macro else None
        mult = ((res or {}).get("PhysicalResistance") or {}).get("Multiplier")
        raw["GPP_Armor_DamageMitigation"] = (1 - mult) * 100 if isinstance(mult, (int, float)) else None
    out = {}
    # Ship weapons: Impact Force scales their damage, so its base is the alpha (see alpha()).
    if "GPP_Weapon_Damage" in wanted and info.get("type") in ("WeaponGun", "WeaponPersonal"):
        hit = alpha(dc, comps)
        if hit:
            out["GPP_Weapon_Damage"] = hit["total"] if hit["total"] is not None else hit["dps"]
    for gpp in wanted:
        meta = props.get(gpp) or {}
        value = raw.get(gpp)
        if meta.get("display") != "value" or not isinstance(value, (int, float)):
            continue
        # Resource figures are read in display units already; the game's scale is for its raw units.
        scale = 1.0 if gpp.startswith("GPP_ItemResource_") else meta.get("scale", 1.0)
        out[gpp] = round(float(value) * scale, 4)
    return out


# -- recipes ------------------------------------------------------------------------------------

_QUANTIZATION_ALIASES = {"ice": "RawIce"}


def _words(name: str) -> str:
    """'ItemResourceGathering' / 'Easy_PvE_only_action' → 'Item Resource Gathering' / 'Easy PvE only action'."""
    name = name.replace("_", " ")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip()


def _seconds(time: dict | None) -> float:
    t = time or {}
    return round(((t.get("days") or 0) * 24 + (t.get("hours") or 0)) * 3600 + (t.get("minutes") or 0) * 60
                 + (t.get("seconds") or 0), 2)


class _Recipes:
    def __init__(self, dc: DataCore, loc: dict[str, str]):
        self.dc, self.loc = dc, loc
        self._records: dict[str, dict | None] = {}
        self._steps_by_name: dict[str, list[int]] | None = None

    def record(self, ref, depth: int = 3) -> dict | None:
        if not isinstance(ref, str) or not ref.startswith("@"):
            return None
        if ref not in self._records:
            self._records[ref] = self.dc.record(ref[1:], max_depth=depth)
        return self._records[ref]

    def item_name(self, entity_ref: str) -> str:
        rec = self.dc.record(entity_ref.lstrip("@"), max_depth=4) or {}
        attach = (_components(rec).get("SAttachableComponentParams") or {}).get("AttachDef") or {}
        return _loc(self.loc, (attach.get("Localization") or {}).get("Name")) or entity_ref.split(".", 1)[-1]

    def quality_steps(self, name: str, resource_ref: str | None = None, entity_ref: str | None = None) -> list[int]:
        """The qualities a material comes in: its quantization bands' mapped values (any roll in a band
        becomes that value). Refining keeps the quality, so a refined material has its ore's bands: found
        on its own resource, the resource a harvested item contains, a resource of the same name, or the
        record named after it."""
        own: dict = {}
        if resource_ref:
            own = self.dc.record(resource_ref.lstrip("@"), max_depth=3) or {}
        elif entity_ref:
            ent = self.dc.record(entity_ref.lstrip("@"), max_depth=4) or {}
            for comp in ent.get("Components") or []:
                for entry in (comp.get("defaultComposition") or []) if isinstance(comp, dict) else []:
                    ref = (entry or {}).get("entry")
                    if isinstance(ref, str) and ref.startswith("@ResourceType."):
                        own = self.dc.record(ref[1:], max_depth=3) or {}
        steps = self._steps_of(own)
        if steps:
            return steps
        if self._steps_by_name is None:
            self._steps_by_name = {}
            for rec_name in self.dc.record_names("ResourceType."):
                rec = self.dc.record(rec_name, max_depth=3) or {}
                found = self._steps_of(rec)
                label = _loc(self.loc, rec.get("displayName")).lower()
                if found and label:
                    self._steps_by_name.setdefault(label, found)
        key = name.lower().removeprefix("pressurized ")
        if key in self._steps_by_name:
            return self._steps_by_name[key]
        record = _QUANTIZATION_ALIASES.get(key) or re.sub(r"[^A-Za-z]", "", name)
        return self._bands(self.dc.record("CraftingQualityQuantizationRecord.Quantization_" + record, max_depth=3))

    def _steps_of(self, resource: dict) -> list[int]:
        for prop in resource.get("properties") or []:
            if isinstance(prop, dict) and prop.get("_type") == "ResourceTypeCraftingData":
                ref = (prop.get("qualityQuantization") or {}).get("qualityQuantizationRecord")
                if isinstance(ref, str) and ref.startswith("@"):
                    return self._bands(self.dc.record(ref[1:], max_depth=3))
        return []

    @staticmethod
    def _bands(rec: dict | None) -> list[int]:
        bands = ((rec or {}).get("qualityQuantization") or {}).get("bands") or []
        return sorted({int(b["mappedValue"]) for b in bands if isinstance(b, dict) and isinstance(b.get("mappedValue"), (int, float))})

    def recipe(self, bp: dict) -> dict | None:
        """The first tier: craft time, and each slot's options with the stats the slot's quality changes.
        The top-level select is the list of slots; `choose` < len(slots) means pick that many."""
        tiers = bp.get("tiers") or []
        first = tiers[0] if tiers and isinstance(tiers[0], dict) else {}
        costs = (first.get("recipe") or {}).get("costs")
        if not isinstance(costs, dict):
            return None
        top = costs.get("mandatoryCost") or {}
        slots = [self._slot(o) for o in top.get("options") or [] if isinstance(o, dict)]
        out: dict = {"seconds": _seconds(costs.get("craftTime")), "slots": [s for s in slots if s]}
        if top.get("count") and top["count"] < len(out["slots"]):
            out["choose"] = top["count"]
        optional = [self._slot(o) for o in costs.get("optionalCosts") or [] if isinstance(o, dict)]
        if any(optional):
            out["optional"] = [s for s in optional if s]
        return out

    def _slot(self, cost: dict) -> dict | None:
        if cost.get("_type") != "CraftingCost_Select":
            option = self._option(cost)
            return {"name": option["name"], "count": 1, "options": [option]} if option else None
        info = cost.get("nameInfo") or {}
        name = _loc(self.loc, info.get("displayName")) or _words(str(info.get("debugName") or "").strip(":").title())
        options = [o for o in (self._option(c) for c in cost.get("options") or [] if isinstance(c, dict)) if o]
        if not options:
            return None
        slot: dict = {"name": name, "count": int(cost.get("count") or 1), "options": options}
        for ctx in cost.get("context") or []:
            if not isinstance(ctx, dict):
                continue
            if ctx.get("_type") == "CraftingCostContext_QuantityMultiplier":
                slot["multiplier"] = round(float(ctx.get("multiplier") or 1), 4)
            for mod in (ctx.get("gameplayPropertyModifiers") or {}).get("gameplayPropertyModifiers") or []:
                stat = self._modifier(mod)
                if stat:
                    slot.setdefault("modifiers", []).append(stat)
        return slot

    def _option(self, cost: dict) -> dict | None:
        kind = cost.get("_type")
        min_q = int(cost.get("minQuality") or 0)
        if kind == "CraftingCost_Resource":
            ref = cost.get("resource")
            rec = self.record(ref, depth=1) or {}
            fallback = ref.split(".", 1)[-1] if isinstance(ref, str) else "?"
            scu = ((cost.get("quantity") or {}).get("standardCargoUnits")) or 0
            name = _loc(self.loc, rec.get("displayName")) or fallback
            option = {"resource": fallback, "name": name, "scu": round(float(scu), 4), "minQuality": min_q}
            steps = self.quality_steps(name, resource_ref=ref)
            if steps:
                option["steps"] = steps
            return option
        if kind == "CraftingCost_Item":
            ref = cost.get("entityClass")
            if not isinstance(ref, str):
                return None
            name = self.item_name(ref)
            option = {"item": ref.split(".", 1)[-1].lower(), "name": name, "qty": int(cost.get("quantity") or 1),
                      "minQuality": min_q}
            steps = self.quality_steps(name, entity_ref=ref)
            if steps:
                option["steps"] = steps
            return option
        return None   # nested selects don't occur in 4.10; skip rather than guess

    def _modifier(self, mod: dict) -> dict | None:
        ref = mod.get("gameplayPropertyRecord")
        prop = self.record(ref, depth=2) or {}
        fallback = _words(ref.split(".", 1)[-1].removeprefix("GPP_").replace("_", " ")) if isinstance(ref, str) else "?"
        ranges = []
        for r in mod.get("valueRanges") or []:
            if not isinstance(r, dict):
                continue
            additive = "additiveModifierAtStart" in r
            start = r.get("additiveModifierAtStart" if additive else "modifierAtStart")
            end = r.get("additiveModifierAtEnd" if additive else "modifierAtEnd")
            ranges.append({"from": int(r.get("startQuality") or 0), "to": int(r.get("endQuality") or 0),
                           "start": round(float(start or 0), 4), "end": round(float(end or 0), 4),
                           "kind": "add" if additive else "factor"})
        if not ranges:
            return None
        out = {"stat": _loc(self.loc, prop.get("propertyName")) or fallback, "ranges": ranges}
        if isinstance(ref, str) and ref.startswith("@CraftingGameplayPropertyDef."):
            out["property"] = ref.split(".", 1)[1]
        return out


def recipes(dc: DataCore, loc: dict[str, str], items: set[str]) -> dict[str, dict]:
    """Lower-case item class → {"blueprint": record name, "name", **recipe} for every blueprint that
    crafts one of `items` (lower-case classes)."""
    rx = _Recipes(dc, loc)
    out: dict[str, dict] = {}
    for rec_name in dc.record_names("CraftingBlueprintRecord."):
        bp = (dc.record(rec_name, max_depth=2) or {}).get("blueprint") or {}
        entity = (bp.get("processSpecificData") or {}).get("entityClass")
        if not isinstance(entity, str):
            continue
        cls = entity.split(".", 1)[-1].lower()
        if cls not in items or cls in out:
            continue
        recipe = rx.recipe((dc.record(rec_name, max_depth=12) or {}).get("blueprint") or {})
        if recipe:
            out[cls] = {"blueprint": rec_name.split(".", 1)[1], "name": rx.item_name(entity), **recipe}
    return out
