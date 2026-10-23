"""The loadout calculator: a ship's slots and parts in, its numbers, shopping
route and craft list out. The website has the same calculator in TypeScript;
the golden fixtures in tests/fixtures/loadouts keep the two equal (every
output is plain JSON with numbers rounded the same way: round() below, half
away from zero, 2 decimals unless noted).

Inputs (plain dicts, as app.loadoutdata, app.uexparts, app.mining and
app.refining hold them):
- catalog: {"ship": {"hull", "slots"}, "items": {cls: part}, "recipes": {cls: recipe}}
- loadout: {"parts": {slot path: {"item", "source", "qualities", "shop"}}}. A slot
  path joins slot ids with "/" ("hardpoint_gun_nose/hardpoint_class_2"). Slots not
  in "parts" hold their stock part; a changed part brings its own default children.
  source: "buy" | "craft" | "stock"; qualities: per recipe slot, the material quality
  chosen (a quality step) or null for none chosen yet (uncrafted values).
- offers: {uuid: [{"terminal", "shop", "place", "system", "planet", "moon", "price", "reported"}]}
  cheapest first; odds (mining): {mining resource id: {"name", "systems": {system: [[quality,
  percent], …]}}}; refining: {resource: {"yield", "ore"}}. A refined material's odds are its
  ore's; a mined item's (gems) are the mining resource of the same name.

What's calculated (values the game decides while flying are left out):
- firepower: burst DPS (damage per shot × pellets × rate) and alpha (one shot of
  every gun), by damage type; beams count their damage per second as DPS.
- missiles: count and total damage; shields: HP and regen summed; hull: body HP.
- power: segments made (power plants) and needed (every part except guns,
  which run on their own weapon pool, plus the ship's basePower: parts outside
  the editable slots): minimum and maximum draw.
- coolant made; quantum drive speed and cooldown.
- ceilings: the best each total can be on this ship (every slot holding its best
  compatible part; craftable parts at their best quality).
- crafted parts: each recipe slot's chosen quality moves its stats along the
  recipe's ranges; several slots on one stat add up (1 + Σ(factor − 1)).
- shopping: bought parts grouped into stops (a stop is a place: station, city,
  outpost). "stops": fewest stops (greedy: the place that has most of what's left,
  ties → cheaper, then name), each part at its cheapest offer there; "price": each
  part at its cheapest offer. A part's own "shop" choice wins.
- craft list: per material the amount (SCU or units) × parts, the highest quality
  any part needs, the ore to mine for refined materials (refined ÷ yield) and the
  share of finds per system that reach that quality.
"""

from __future__ import annotations

import math

STAT_PROPS = {
    "GPP_Weapon_Damage": "damage", "GPP_Weapon_FireRate": "rate", "GPP_Shield_MaxHealth": "shield",
    "GPP_ItemResource_PowerGeneration": "power", "GPP_ItemResource_CoolantGeneration": "coolant",
    "GPP_Quantum_Speed": "quantum", "GPP_Health_MaxHealth": "health",
}


def rnd(value: float, digits: int = 2) -> float:
    """Half away from zero (JavaScript's Math.round goes half up; both sides use this rule)."""
    scale = 10 ** digits
    x = abs(value) * scale
    out = math.floor(x + 0.5 + 1e-9) / scale
    return -out if value < 0 else out


# -- fitting ---------------------------------------------------------------------------------

def _tags(text) -> set[str]:
    if isinstance(text, list):
        return {t.lstrip("$") for t in text if t}
    return {t.lstrip("$") for t in str(text or "").split() if t}


def fits(slot: dict, part: dict) -> bool:
    """Size in range, an accepted type (and subtype when the slot names some; a part whose subtype is
    UNDEFINED fits any, and "$…" subtypes on slots are leftovers that don't count), and the slot's
    required tags."""
    if not (slot["min"] <= (part.get("size") or 0) <= slot["max"]):
        return False
    sub = part.get("subtype") or ""
    for t, subs in slot["types"]:
        named = [x for x in subs if not x.startswith("$")]
        if t == part.get("type") and (not named or sub in named or sub in ("", "UNDEFINED")):
            break
    else:
        return False
    return _tags(slot.get("tags")) <= _tags(part.get("tags"))


def candidates(slot: dict, items: dict) -> list[str]:
    return sorted(cls for cls, part in items.items() if fits(slot, part))


def _effects(recipe: dict | None, qualities: list | None) -> dict[str, tuple[float, float]]:
    """stat → (factor, addition) from the chosen qualities (no quality chosen: no change)."""
    out: dict[str, list[float]] = {}
    for i, rslot in enumerate((recipe or {}).get("slots") or []):
        q = (qualities or [None] * (i + 1))[i] if i < len(qualities or []) else None
        if q is None:
            continue
        for mod in rslot.get("modifiers") or []:
            stat = STAT_PROPS.get(mod.get("property") or "")
            if not stat:
                continue
            value, kind = modifier_value(mod["ranges"], q)
            acc = out.setdefault(stat, [0.0, 0.0])
            if kind == "factor":
                acc[0] += value - 1
            else:
                acc[1] += value
    return {k: (1 + v[0], v[1]) for k, v in out.items()}


def modifier_value(ranges: list[dict], q: float) -> tuple[float, str]:
    """A quality's value on a modifier: linear inside its range, the nearest end outside all ranges;
    additive ranges move in whole steps."""
    ranges = sorted(ranges, key=lambda r: r["from"])
    r = next((x for x in ranges if x["from"] <= q <= x["to"]), None)
    if r is None:
        r = ranges[0] if q < ranges[0]["from"] else ranges[-1]
    if q <= r["from"]:
        value = r["start"]
    elif q >= r["to"]:
        value = r["end"]
    else:
        value = r["start"] + (r["end"] - r["start"]) * (q - r["from"]) / (r["to"] - r["from"])
    if r["kind"] == "add":
        value = float(round(value))
    return value, r["kind"]


def _apply(value: float, effect: tuple[float, float] | None) -> float:
    return value * effect[0] + effect[1] if effect else value


def best_qualities(recipe: dict | None) -> list | None:
    """The highest quality step of each recipe slot's first option (what the ceilings assume)."""
    if not recipe:
        return None
    out = []
    for rslot in recipe.get("slots") or []:
        steps = ((rslot.get("options") or [{}])[0]).get("steps") or [1000]
        out.append(max(steps))
    return out


def part_stats(part: dict, recipe: dict | None = None, qualities: list | None = None) -> dict:
    """The numbers one part adds (crafted qualities applied)."""
    fx = _effects(recipe, qualities) if recipe and qualities else {}
    out: dict = {}
    gun = part.get("gun")
    if gun:
        dmg = fx.get("damage")
        per = {k: _apply(v, dmg) for k, v in (gun.get("alpha") or {}).items()}
        pellets = gun.get("pellets") or 1
        alpha = {k: v * pellets for k, v in per.items()}
        if gun.get("mode") == "beam":
            dps = {k: _apply(v, dmg) for k, v in (gun.get("alpha") or {}).items()}
            alpha = {}
        else:
            rate = _apply(gun.get("rpm") or 0, fx.get("rate"))
            dps = {k: v * rate / 60 for k, v in alpha.items()}
        out["alpha"], out["dps"] = alpha, dps
    missile = part.get("missile")
    if missile:
        out["missile"] = sum((missile.get("damage") or {}).values())
    if part.get("shield"):
        out["shield"] = _apply(part["shield"].get("hp") or 0, fx.get("shield"))
        out["regen"] = part["shield"].get("regen") or 0
    if part.get("plant"):
        out["segments"] = _apply(part["plant"].get("segments") or 0, fx.get("power"))
    if part.get("cooler"):
        out["coolant"] = _apply(part["cooler"].get("coolant") or 0, fx.get("coolant"))
    if part.get("quantum"):
        out["qspeed"] = _apply(part["quantum"].get("speed") or 0, fx.get("quantum"))
        out["qcooldown"] = part["quantum"].get("cooldown") or 0
    if part.get("type") != "WeaponGun":
        out["pmax"] = (part.get("power") or {}).get("max") or 0
        out["pmin"] = (part.get("power") or {}).get("min") or 0
    return out


def fitted(ship: dict, items: dict, parts: dict) -> list[dict]:
    """Every slot with what's in it: {path, slot, item, source, qualities, shop, stock, changed, obsolete}."""
    out: list[dict] = []

    def walk(slot: dict, prefix: str, stock_item: str, children_stock: bool) -> None:
        path = prefix + slot["id"]
        choice = parts.get(path)
        if choice is None:
            item, source = stock_item, "stock"
        else:
            item = choice.get("item") or ""
            source = choice.get("source") or ("stock" if item == stock_item else "buy")
        obsolete = bool(item) and item not in items
        row = {"path": path, "slot": slot, "item": item, "source": source,
               "qualities": (choice or {}).get("qualities"), "shop": (choice or {}).get("shop") or "",
               "stock": item == stock_item, "changed": item != stock_item, "obsolete": obsolete}
        out.append(row)
        part = items.get(item) if item and not obsolete else None
        if not part:
            return
        same = item == stock_item and children_stock
        if same:
            kids = slot.get("children") or []
            for child in kids:
                walk(child, path + "/", child.get("default") or "", True)
        else:
            defaults = part.get("defaults") or {}
            for child in part.get("slots") or []:
                walk(child, path + "/", defaults.get(child["id"], ""), False)

    for slot in ship.get("slots") or []:
        walk(slot, "", slot.get("default") or "", True)
    return out


# -- totals ----------------------------------------------------------------------------------

def _empty() -> dict:
    return {"dps": 0.0, "dpsByType": {}, "alpha": 0.0, "alphaByType": {}, "missiles": 0, "missileDamage": 0.0,
            "shieldHp": 0.0, "shieldRegen": 0.0, "segments": 0.0, "powerMin": 0.0, "powerMax": 0.0,
            "coolant": 0.0, "quantumSpeed": 0.0, "quantumCooldown": 0.0}


def totals(rows: list[dict], items: dict, recipes: dict, base_power: dict | None = None) -> dict:
    base_power = base_power or {}
    t = _empty()
    for row in rows:
        part = items.get(row["item"]) if row["item"] and not row["obsolete"] else None
        if not part:
            continue
        crafted = row["source"] == "craft"
        s = part_stats(part, recipes.get(row["item"]) if crafted else None, row.get("qualities") if crafted else None)
        for k, v in (s.get("dps") or {}).items():
            t["dpsByType"][k] = t["dpsByType"].get(k, 0.0) + v
        for k, v in (s.get("alpha") or {}).items():
            t["alphaByType"][k] = t["alphaByType"].get(k, 0.0) + v
        if "missile" in s:
            t["missiles"] += 1
            t["missileDamage"] += s["missile"]
        t["shieldHp"] += s.get("shield", 0.0)
        t["shieldRegen"] += s.get("regen", 0.0)
        t["segments"] += s.get("segments", 0.0)
        t["powerMax"] += s.get("pmax", 0.0)
        t["powerMin"] += s.get("pmin", 0.0)
        t["coolant"] += s.get("coolant", 0.0)
        if s.get("qspeed") and not t["quantumSpeed"]:
            t["quantumSpeed"], t["quantumCooldown"] = s["qspeed"], s["qcooldown"]
    t["dps"] = sum(t["dpsByType"].values())
    t["powerMax"] += base_power.get("max", 0.0)
    t["powerMin"] += base_power.get("min", 0.0)
    t["alpha"] = sum(t["alphaByType"].values())
    return _rounded(t)


def _rounded(t: dict) -> dict:
    out = {}
    for k, v in t.items():
        if isinstance(v, dict):
            out[k] = {kk: rnd(vv) for kk, vv in sorted(v.items())}
        elif isinstance(v, float):
            out[k] = rnd(v)
        else:
            out[k] = v
    return out


def ceilings(ship: dict, rows: list[dict], items: dict, recipes: dict, offers: dict) -> dict:
    """The best each total can be on this ship: every changeable slot holding the part (and, below a
    mount, rack or turret, the parts) that give the most of that total; craftable parts at their best
    quality; only parts a player can get (sold or craftable) when prices are known. Locked slots keep
    what's in them."""
    keys = {"dps": "dps", "alpha": "alpha", "shieldHp": "shield", "segments": "segments", "coolant": "coolant",
            "quantumSpeed": "qspeed"}
    fitted_at = {row["path"]: row["item"] for row in rows}

    def obtainable(cls: str) -> bool:
        return not offers or cls in recipes or bool(offers.get(items[cls].get("uuid") or ""))

    def value(cls: str, key: str) -> float:
        recipe = recipes.get(cls)
        v = part_stats(items[cls], recipe, best_qualities(recipe)).get(keys[key], 0.0)
        return sum(v.values()) if isinstance(v, dict) else v

    def best(slot: dict, path: str, key: str, depth: int) -> float:
        if slot.get("locked"):
            options = [fitted_at.get(path, "")] if fitted_at.get(path, "") in items else []
        else:
            options = [c for c in candidates(slot, items) if obtainable(c)]
        top = 0.0
        for cls in options:
            v = value(cls, key)
            if depth < 4:
                v += sum(best(child, path + "/" + child["id"], key, depth + 1) for child in items[cls].get("slots") or [])
            top = max(top, v)
        return top

    out = {}
    for key in keys:
        vals = [best(slot, slot["id"], key, 0) for slot in ship.get("slots") or []]
        out[key] = rnd(max(vals) if key == "quantumSpeed" else sum(vals)) if vals else 0.0
    return out


# -- shopping --------------------------------------------------------------------------------

def shopping(rows: list[dict], items: dict, offers: dict, mode: str = "stops") -> dict:
    """Bought parts → stops (places) with shops and items, the total, and parts nobody sells."""
    wanted: dict[str, dict] = {}            # item → {count, shop}
    for row in rows:
        if row["source"] == "buy" and row["item"] and not row["obsolete"]:
            w = wanted.setdefault(row["item"], {"count": 0, "shop": row["shop"]})
            w["count"] += 1
            w["shop"] = w["shop"] or row["shop"]
    unsold, choice = [], {}
    for item, w in sorted(wanted.items()):
        uuid = (items.get(item) or {}).get("uuid") or ""
        offs = offers.get(uuid) or []
        if not offs:
            unsold.append({"item": item, "count": w["count"]})
            continue
        forced = [o for o in offs if o["terminal"] == w["shop"]]
        if forced:
            choice[item] = forced[0]
        elif mode == "price":
            choice[item] = offs[0]
    left = sorted(i for i in wanted if i not in choice and i not in {u["item"] for u in unsold})
    while left:
        places: dict[str, list] = {}
        for item in left:
            uuid = items[item]["uuid"]
            for o in offers.get(uuid) or []:
                places.setdefault(o["place"], []).append((item, o))
        def score(place: str):
            cheapest = {}
            for item, o in places[place]:
                if item not in cheapest or o["price"] < cheapest[item]["price"]:
                    cheapest[item] = o
            cost = sum(o["price"] * wanted[i]["count"] for i, o in cheapest.items())
            return (-len(cheapest), cost, place), cheapest
        place = min(places, key=lambda p: score(p)[0])
        for item, o in score(place)[1].items():
            choice[item] = o
        left = [i for i in left if i not in choice]
    stops: dict[str, dict] = {}
    for item, o in sorted(choice.items()):
        stop = stops.setdefault(o["place"], {"place": o["place"], "system": o["system"], "planet": o["planet"],
                                             "moon": o["moon"], "shops": {}})
        shop = stop["shops"].setdefault(o["terminal"], {"terminal": o["terminal"], "shop": o["shop"], "items": []})
        n = wanted[item]["count"]
        shop["items"].append({"item": item, "count": n, "price": rnd(o["price"]), "total": rnd(o["price"] * n),
                              "reported": o["reported"]})
    out_stops = []
    for place in sorted(stops):
        stop = stops[place]
        stop["shops"] = [stop["shops"][k] for k in sorted(stop["shops"], key=lambda k: stop["shops"][k]["shop"])]
        out_stops.append(stop)
    total = sum(i["total"] for s in out_stops for sh in s["shops"] for i in sh["items"])
    return {"mode": mode, "stops": out_stops, "total": rnd(total), "unsold": unsold}


# -- crafting --------------------------------------------------------------------------------

def crafting(rows: list[dict], recipes: dict, odds: dict, refining: dict) -> dict:
    """Crafted parts → parts (with count and craft time), materials (amount, quality, ore, odds)."""
    parts: dict[str, dict] = {}
    materials: dict[str, dict] = {}
    for row in rows:
        if row["source"] != "craft" or not row["item"] or row["obsolete"]:
            continue
        recipe = recipes.get(row["item"])
        if not recipe:
            continue
        p = parts.setdefault(row["item"], {"item": row["item"], "count": 0, "seconds": 0.0})
        p["count"] += 1
        p["seconds"] += recipe.get("seconds") or 0
        qualities = row.get("qualities") or []
        for i, rslot in enumerate(recipe.get("slots") or []):
            option = (rslot.get("options") or [None])[0]
            if not option:
                continue
            chosen = qualities[i] if i < len(qualities) else None
            need = max(option.get("minQuality") or 0, chosen or 0)
            key = option.get("resource") or option.get("item")
            m = materials.setdefault(key, {"key": key, "name": option.get("name") or key,
                                           "unit": "scu" if option.get("resource") else "units", "amount": 0.0,
                                           "quality": 0})
            m["amount"] += ((option.get("scu") or 0) * (rslot.get("multiplier") or 1) if option.get("resource")
                            else option.get("qty") or 0)
            m["quality"] = max(m["quality"], need)
    by_name = {str(v.get("name") or "").lower(): k for k, v in odds.items()}
    out = []
    for key in sorted(materials):
        m = materials[key]
        m["amount"] = rnd(m["amount"], 4)
        row = refining.get(key) or {}
        m["oreScu"] = rnd(m["amount"] / row["yield"], 4) if m["unit"] == "scu" and row.get("yield") else None
        source = row.get("ore") if m["unit"] == "scu" else by_name.get(m["name"].lower())
        systems = (odds.get(source or key) or {}).get("systems") or {}
        m["odds"] = {system: rnd(sum(p for q, p in dist if q >= m["quality"])) for system, dist in sorted(systems.items())}
        out.append(m)
    return {"parts": [parts[k] for k in sorted(parts)], "materials": out,
            "seconds": rnd(sum(p["seconds"] for p in parts.values()))}


# -- all of it -------------------------------------------------------------------------------

def calculate(catalog: dict, loadout: dict, offers: dict | None = None, odds: dict | None = None,
              refining: dict | None = None, route: str = "stops") -> dict:
    ship, items, recipes = catalog["ship"], catalog["items"], catalog.get("recipes") or {}
    rows = fitted(ship, items, loadout.get("parts") or {})
    stock_rows = fitted(ship, items, {})
    offers = offers or {}
    flags = []
    for row in rows:
        part = items.get(row["item"]) if row["item"] and not row["obsolete"] else None
        sellable = bool(part and offers.get(part.get("uuid") or ""))
        craftable = bool(part and row["item"] in recipes)
        flags.append({"path": row["path"], "item": row["item"], "source": row["source"], "stock": row["stock"],
                      "changed": row["changed"], "obsolete": row["obsolete"],
                      "unobtainable": bool(part) and row["changed"] and not sellable and not craftable,
                      "canBuy": sellable, "canCraft": craftable})
    return {
        "hull": rnd(ship.get("hull") or 0),
        "parts": flags,
        "totals": totals(rows, items, recipes, ship.get("basePower")),
        "stock": totals(stock_rows, items, recipes, ship.get("basePower")),
        "ceilings": ceilings(ship, rows, items, recipes, offers),
        "shopping": shopping(rows, items, offers, route),
        "crafting": crafting(rows, recipes, odds or {}, refining or {}),
    }
