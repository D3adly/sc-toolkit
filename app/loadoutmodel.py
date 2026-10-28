"""The loadout editor's view of a ship: the parts as the "bus" shows them (one
node per part, paired ports grouped), what can go in each, fitting a part, the
swap tray's cards and the saved shopping list. Pure functions over the
calculator's data (app.loadoutcalc); the Qt views only draw what these return.

A port of the website's loadoutModel.ts (and the list logic of its shopping
page): keep the two in step, the editor must behave the same on both.

Context (Ctx): one ship's catalogue (catalog_for: the ship and every part that
could go anywhere in it, their recipes), the shops selling those parts
(offers_for, cheapest first), mining quality odds (odds_for) and the refining
table, as the website's /api/v1/data/loadouts/{ship} gives them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app import loadoutcalc, refining as refining_mod
from app.loadoutcalc import best_qualities, candidates, fits, fitted, part_stats, totals

# -- the context -----------------------------------------------------------------------------


def catalog_for(data: dict, ship_cls: str) -> dict:
    """The ship plus every part that could go anywhere in it (through mounts, racks and turrets),
    the recipes of those parts."""
    items, ship = data["items"], data["ships"][ship_cls]
    keep: set[str] = set()

    def visit(slot: dict, depth: int) -> None:
        if slot.get("default") in items:
            keep.add(slot["default"])
        for child in slot.get("children") or []:
            visit(child, depth + 1)
        if depth > 4:
            return
        for cls in candidates(slot, items):
            if cls not in keep:
                keep.add(cls)
                for sub in items[cls].get("slots") or []:
                    visit(sub, depth + 1)

    for slot in ship["slots"]:
        visit(slot, 0)
    return {"ship": ship, "items": {k: items[k] for k in sorted(keep)},
            "recipes": {k: data["recipes"][k] for k in sorted(keep) if k in data["recipes"]}}


def offers_for(catalog: dict, prices) -> dict:
    """{uuid: [offer]} cheapest first, for the catalogue's parts (prices: app.uexparts.Prices)."""
    out = {}
    for part in catalog["items"].values():
        rows = prices.offers(part.get("uuid") or "") if prices else []
        if rows:
            out[part["uuid"]] = [{"terminal": o.terminal, "shop": o.shop, "place": o.place, "system": o.system,
                                  "planet": o.planet, "moon": o.moon, "price": o.price, "reported": o.reported}
                                 for o in rows]
    return out


def odds_for(catalog: dict, mining: dict | None) -> dict:
    """{mining resource: {name, systems: {system: [[quality, percent]]}}} for the recipes' materials."""
    quality, names = (mining or {}).get("quality") or {}, (mining or {}).get("resources") or {}
    wanted = set()
    table = refining_mod.table()["materials"]
    for recipe in catalog["recipes"].values():
        for rslot in recipe["slots"]:
            for o in rslot["options"]:
                if o.get("resource"):
                    wanted.add((table.get(o["resource"]) or {}).get("ore") or o["resource"])
                else:
                    wanted.update(k for k, v in names.items() if str(v.get("name") or "").lower() == o["name"].lower())
    out = {}
    for key in sorted(wanted):
        systems = {s: (scales.get("1.0") or {}).get("dist") or [] for s, scales in (quality.get(key) or {}).items()}
        out[key] = {"name": (names.get(key) or {}).get("name") or key, "systems": {s: d for s, d in systems.items() if d}}
    return out


def refining_for() -> dict:
    """{material: {yield, ore}} as the calculator takes it."""
    return {k: {"yield": v.get("yield"), "ore": v.get("ore")} for k, v in refining_mod.table()["materials"].items()}


@dataclass
class Ctx:
    catalog: dict
    offers: dict = field(default_factory=dict)
    odds: dict = field(default_factory=dict)
    refining: dict = field(default_factory=dict)

    @property
    def items(self) -> dict:
        return self.catalog["items"]

    @property
    def recipes(self) -> dict:
        return self.catalog.get("recipes") or {}


def context(data: dict, ship_cls: str, prices=None, mining: dict | None = None) -> Ctx:
    catalog = catalog_for(data, ship_cls)
    return Ctx(catalog, offers_for(catalog, prices), odds_for(catalog, mining), refining_for())


# -- kinds -----------------------------------------------------------------------------------

KIND_OF_TYPE = {"WeaponGun": "gun", "MissileLauncher": "rack", "BombLauncher": "rack", "Missile": "missile",
                "Shield": "shield", "PowerPlant": "power", "Cooler": "cooler", "QuantumDrive": "quantum",
                "Radar": "radar"}
KIND_ORDER = ["gun", "rack", "missile", "shield", "power", "cooler", "quantum", "radar", "other"]
KIND_LABEL = {"gun": ("Gun", "Guns"), "rack": ("Missile rack", "Missile racks"), "missile": ("Missile", "Missiles"),
              "shield": ("Shield", "Shields"), "power": ("Power plant", "Power plants"),
              "cooler": ("Cooler", "Coolers"), "quantum": ("Quantum drive", "Quantum drives"),
              "radar": ("Radar", "Radars"), "other": ("Part", "Parts")}
# What a node's big number is, and its unit (long, short).
KIND_STAT = {"gun": ("burst DPS", "DPS"), "rack": ("missile slots", "slots"), "missile": ("damage", "dmg"),
             "shield": ("shield HP", "HP"), "power": ("power segments", "segments"), "cooler": ("coolant", "cool"),
             "quantum": ("Mm/s quantum speed", "Mm/s"), "radar": ("m aim assist range", "m aim"),
             "other": ("power draw", "draw")}
# Weapons hang above the power bus, systems below.
WEAPON_KINDS = ("gun", "rack", "missile")


def lower_is_better(kind: str) -> bool:
    """Parts with nothing to show but their power draw: less is better."""
    return kind == "other"


def stat_of(kind: str, ctx: Ctx, item: str, source: str = "buy", qualities: list | None = None) -> float:
    """A part's number on its node (crafted qualities applied when it's crafted)."""
    part = ctx.items.get(item)
    if not part:
        return 0.0
    crafted = source == "craft"
    s = part_stats(part, ctx.recipes.get(item) if crafted else None, qualities if crafted else None)
    if kind == "gun":
        return sum((s.get("dps") or {}).values())
    if kind == "rack":
        return float(len(part.get("slots") or []))
    if kind == "missile":
        return s.get("missile", 0.0)
    if kind == "shield":
        return s.get("shield", 0.0)
    if kind == "power":
        return s.get("segments", 0.0)
    if kind == "cooler":
        return s.get("coolant", 0.0)
    if kind == "quantum":
        return s.get("qspeed", 0.0) / 1e6
    if kind == "radar":
        return float((part.get("radar") or {}).get("aimMax") or 0)
    return s.get("pmax", 0.0)


def _kind_of(row: dict, part: dict | None) -> str:
    types = row["slot"].get("types") or []
    t = (part or {}).get("type") or (types[0][0] if types else "")
    return KIND_OF_TYPE.get(t, "other")


def _is_mount(part: dict | None) -> bool:
    return bool(part) and part.get("type") == "Turret" and any(
        t == "WeaponGun" for s in part.get("slots") or [] for t, _ in s.get("types") or [])


# A side joined to a position in a port name: the M80's "weapon_rearleft".
JOINED_SIDE = re.compile(r"(front|rear|top|bottom|upper|lower|inner|outer|mid|nose|tail|wing)(left|right)(?=[_/]|$)")
_NOISE = {"hardpoint", "left", "right", "weapon", "gun", "generator", "shield", "cooler", "power", "plant", "quantum",
          "drive", "radar", "missilerack", "missile", "rack", "cm", "launcher"}


def _where(path: str, rows: dict[str, dict], items: dict) -> str:
    """Words naming where a slot is ("Wing", "Nose", "Pylon 3"), from its top-level port id. A turret's
    guns name their turret, sides kept: a ship can have several ("Turret side right")."""
    top = path.split("/")[0]
    top_part = items.get((rows.get(top) or {}).get("item") or "")
    turret = "/" in path and (top_part or {}).get("type") == "TurretBase"
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", top).lower()
    text = JOINED_SIDE.sub(r"\1", text)
    words = [str(int(w)) if w.isdigit() else w for w in re.split(r"[_\s]+", text)
             if w and (w not in _NOISE or (turret and w in ("left", "right")))]
    if turret and (not words or words[0] != "turret"):
        words.insert(0, "turret")
    out = " ".join(words)
    return out[:1].upper() + out[1:] if out else ""


def _family(path: str) -> str:
    """A left/right pair's shared key: the path with its sides taken out."""
    p = JOINED_SIDE.sub(r"\1", path.lower())
    return re.sub(r"(^|[_/])(left|right)(?=[_/]|$)", r"\1", p)


@dataclass
class BusNode:
    id: str                     # the first slot path: stable while the group's parts stay the same
    kind: str
    label: str                  # "Guns · Wing"
    size: str                   # "S3"
    paths: list[str]            # every slot this node stands for (×2 for a pair)
    missile_paths: list[str]    # a rack's missile slots, per rack
    item: str
    part: dict | None
    name: str
    source: str
    qualities: list | None
    obsolete: bool
    value: float                # the node's number for one of its parts; a rack's: its missiles' damage
    unit: str
    draw: float = 0.0           # power segments the group draws at most
    missiles: list[tuple[str, int]] = field(default_factory=list)   # (name, count) on one rack
    locked: bool = False        # built into the ship: a locked rack only changes its missiles


def bus_nodes(ctx: Ctx, rows: list[dict]) -> list[BusNode]:
    """The ship's parts as bus nodes, paired ports grouped while they hold the same part."""
    items = ctx.items
    by_path = {r["path"]: r for r in rows}

    def parent_of(path: str) -> dict | None:
        return by_path.get(path[:path.rfind("/")]) if "/" in path else None

    groups: dict[str, BusNode] = {}
    for row in rows:
        part = items.get(row["item"]) if row["item"] and not row["obsolete"] else None
        if part and (_is_mount(part) or part.get("type") == "TurretBase"):
            continue                       # their guns stand for them
        parent = parent_of(row["path"])
        parent_part = items.get(parent["item"]) if parent else None
        if parent_part and KIND_OF_TYPE.get(parent_part.get("type")) == "rack":
            continue                       # missiles: on their rack's node
        kind = _kind_of(row, part)
        # A locked part stays off the bus, except guns (their mount is what's locked) and racks
        # built into the ship (the M80's): the rack stays, its missiles can change.
        locked = bool(row["slot"].get("locked"))
        if locked and not row["changed"] and kind not in ("gun", "rack"):
            continue
        if kind == "other" and not row["changed"] and len(candidates(row["slot"], items)) < 2:
            continue
        # A turret's guns group by turret; they sit two deep (turret / mount / gun), wing guns one.
        fam = row["path"].split("/")[0].lower() if kind == "gun" and row["path"].count("/") >= 2 \
            else _family(row["path"])
        kids = [r for r in rows if parent_of(r["path"]) is row] if kind == "rack" else []
        key = "|".join([
            kind, fam,
            # Racks built into the ship are each their own item (the Polaris's "_lt", "_rt"); the
            # same rack by name with the same missiles is a pair.
            ((part or {}).get("name") or row["item"]) if locked and kind == "rack" else row["item"],
            row["source"], json.dumps(row.get("qualities")), str(locked),
            ",".join(f"{r['item']}:{r['source']}" for r in kids),
        ])
        node = groups.get(key)
        if node is None:
            at = _where(row["path"], by_path, items)
            one = KIND_LABEL[kind][0]
            types = row["slot"].get("types") or []
            if kind == "other":
                label = (part or {}).get("type") or (types[0][0] if types else one)
            else:
                label = f"{one} · {at}" if at else one
            node = BusNode(id=row["path"], kind=kind, label=label, size=f"S{row['slot']['max']}", paths=[],
                           missile_paths=[], item=row["item"], part=part,
                           name=(part or {}).get("name") or (row["item"] if row["obsolete"] else "Empty"),
                           source=row["source"], qualities=row.get("qualities"), obsolete=row["obsolete"],
                           value=stat_of(kind, ctx, row["item"], row["source"], row.get("qualities")),
                           unit="dmg" if kind == "rack" else KIND_STAT[kind][1], locked=locked)
            groups[key] = node
        node.paths.append(row["path"])
        node.draw += ((part.get("power") or {}).get("max") or 0) if part and part.get("type") != "WeaponGun" else 0
        if kind == "rack":
            node.missile_paths.extend(r["path"] for r in kids)
            if len(node.paths) == 1:
                count: dict[str, int] = {}
                for r in kids:
                    name = (items.get(r["item"]) or {}).get("name") or (r["item"] or "Empty")
                    count[name] = count.get(name, 0) + 1
                node.missiles = list(count.items())
                node.value = sum(part_stats(items.get(r["item"]) or {}).get("missile", 0.0) for r in kids)
    nodes = list(groups.values())
    for n in nodes:
        if len(n.paths) > 1:
            n.label = n.label.replace(KIND_LABEL[n.kind][0], KIND_LABEL[n.kind][1], 1)
        n.draw = round(n.draw)
    return sorted(nodes, key=lambda n: KIND_ORDER.index(n.kind))


# Position words in port names: a short label, and its row (upper/front first).
POSITION = {"top": ("Top", 0), "upper": ("Up", 0), "front": ("Front", 0), "outer": ("Out", 0),
            "bottom": ("Bot", 1), "lower": ("Low", 1), "rear": ("Rear", 1), "inner": ("In", 1)}


def slot_names(paths: list[str]) -> list[tuple[str, str]]:
    """A short name for each slot of a group, as (path, name): Left/Right, Up L/Low R… from the ports
    that tell them apart, else 1, 2, 3… (upper row first when named)."""
    segs = [p.lower().split("/") for p in paths]

    def at(s: list[str], i: int) -> str | None:
        return s[i] if i < len(s) else None

    def same(i: int) -> bool:
        return all(at(s, i) == at(segs[0], i) for s in segs)

    def words_of(s: list[str]) -> list[str]:
        text = "_".join(x for i, x in enumerate(s) if not same(i))
        text = JOINED_SIDE.sub(r"\1_\2", text)
        return [w for w in re.split(r"[_\s]+", text) if w and not w.isdigit()]

    every = [words_of(s) for s in segs]

    def shared(w: str) -> bool:
        return all(w in ws for ws in every)

    named = []
    for i, path in enumerate(paths):
        words = [w for w in every[i] if not shared(w)]
        side = next((w for w in words if w in ("left", "right")), None)
        pos = next((w for w in words if w in POSITION), None)
        if pos:
            name = POSITION[pos][0] + (f" {'L' if side == 'left' else 'R'}" if side else "")
        else:
            name = side.capitalize() if side else ""
        rank = (POSITION[pos][1] * 2 if pos else 0) + (1 if side == "right" else 0)
        named.append((path, name, rank, i))
    unique = len({n[1] for n in named}) == len(named) and all(n[1] for n in named)
    if unique:
        return [(p, n) for p, n, _r, _i in sorted(named, key=lambda n: n[2])]
    return [(p, str(i + 1)) for p, _n, _r, i in named]


def slot_of(rows: list[dict], path: str) -> dict | None:
    return next((r["slot"] for r in rows if r["path"] == path), None)


def choices_for(ctx: Ctx, rows: list[dict], paths: list[str]) -> list[str]:
    """What could go in a node: every part that fits all its slots."""
    slots = [s for s in (slot_of(rows, p) for p in paths) if s]
    if not slots:
        return []
    return [c for c in candidates(slots[0], ctx.items) if all(fits(s, ctx.items[c]) for s in slots)]


@dataclass
class Availability:
    can_buy: bool
    can_craft: bool
    cheapest: dict | None
    shops: int


def availability(ctx: Ctx, item: str) -> Availability:
    offers = ctx.offers.get((ctx.items.get(item) or {}).get("uuid") or "") or []
    return Availability(bool(offers), item in ctx.recipes, offers[0] if offers else None,
                        len({o["terminal"] for o in offers}))


def obtainable(ctx: Ctx, item: str) -> bool:
    a = availability(ctx, item)
    return a.can_buy or a.can_craft


def default_source(ctx: Ctx, item: str) -> str:
    """The source a newly fitted part gets: bought when someone sells it, else crafted when it can be."""
    a = availability(ctx, item)
    return "buy" if a.can_buy or not a.can_craft else "craft"


def fit_part(ctx: Ctx, parts: dict, paths: list[str], item: str, source: str | None = None) -> dict:
    """The loadout's parts with `item` fitted in every one of `paths`. A path that holds its stock part
    again drops its choice. A swapped mount or rack keeps what it held (the gun, the missiles) where
    that still fits; anything under it that no longer fits is dropped."""
    ship, items = ctx.catalog["ship"], ctx.items
    before = fitted(ship, items, parts)
    stock = {r["path"]: r["item"] for r in fitted(ship, items, {})}
    out = dict(parts)
    src = source or default_source(ctx, item)
    for path in paths:
        held = [r for r in before if r["path"].startswith(path + "/")]
        # Stock only where everything above it is stock too: a changed mount brings no default gun.
        stock_here = stock.get(path) == item and not any(path.startswith(k + "/") for k in out)
        if stock_here and source != "craft":
            out.pop(path, None)            # back to stock, unless crafting it is asked for
        else:
            out[path] = {"item": item, "source": src}
        for key in [k for k in out if k.startswith(path + "/")]:
            del out[key]
        if stock_here:
            continue                       # the stock part brings its stock contents
        direct = [r for r in held if "/" not in r["path"][len(path) + 1:]]
        for i, slot in enumerate((items.get(item) or {}).get("slots") or []):
            keep = next((r for r in held if r["path"] == f"{path}/{slot['id']}"), None) \
                or (direct[i] if i < len(direct) else None)
            part = items.get(keep["item"]) if keep and keep["item"] else None
            if keep and part and fits(slot, part):
                choice = {"item": keep["item"],
                          "source": default_source(ctx, keep["item"]) if keep["source"] == "stock" else keep["source"]}
                if keep.get("qualities"):
                    choice["qualities"] = keep["qualities"]
                out[f"{path}/{slot['id']}"] = choice
    return out


def with_source(parts: dict, rows: list[dict], paths: list[str], source: str, qualities: list | None = None) -> dict:
    """The parts with these slots' fitted part got another way (buy / craft, crafted qualities)."""
    out = dict(parts)
    by_path = {r["path"]: r for r in rows}
    for path in paths:
        row = by_path.get(path)
        if not row or not row["item"]:
            continue
        choice = {"item": row["item"], "source": source}
        if source == "craft":
            q = qualities if qualities is not None else row.get("qualities")
            if q:
                choice["qualities"] = list(q)
        if (out.get(path) or {}).get("shop") and source == "buy":
            choice["shop"] = out[path]["shop"]
        out[path] = choice
    return out


def totals_with(ctx: Ctx, parts: dict) -> dict:
    """Totals with these parts (for previews), without the costly ceilings."""
    rows = fitted(ctx.catalog["ship"], ctx.items, parts)
    return totals(rows, ctx.items, ctx.recipes, ctx.catalog["ship"].get("basePower"))


def tag_of(ctx: Ctx, item: str, source: str, obsolete: bool, changed: bool) -> str:
    """A fitted part's tag: obsolete, unobtainable (changed, nobody sells it, no recipe), else its source."""
    if obsolete:
        return "obsolete"
    if not item:
        return "stock"
    if changed and not obtainable(ctx, item):
        return "unobtainable"
    return source


# -- the swap tray's cards -------------------------------------------------------------------

def show_stat(v: float) -> str:
    """A node's number as shown: whole numbers from 100 up, one decimal below."""
    if abs(v) >= 100 or float(v).is_integer():
        return f"{loadoutcalc.rnd(v, 0):,.0f}"
    text = f"{loadoutcalc.rnd(v, 1):,.1f}"
    return text[:-2] if text.endswith(".0") else text


def money(v: float) -> str:
    return f"{loadoutcalc.rnd(v, 0):,.0f}"


def _gun_kind(part: dict) -> str:
    tags = part.get("tags") if isinstance(part.get("tags"), list) else str(part.get("tags") or "").split()
    tag = next((t for t in tags if re.search(r"(Cannon|Repeater|Gatling|Scattergun|MassDriver)$", t)), None)
    if not tag:
        return ""
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", tag).lower()
    return words[:1].upper() + words[1:]


def describe(part: dict) -> str:
    """A part's one-line description on its card."""
    if part.get("type") == "WeaponGun":
        alpha = sum((part_stats(part).get("alpha") or {}).values())
        return " · ".join(x for x in (part.get("manufacturer"), _gun_kind(part),
                                      f"{show_stat(alpha)} alpha" if alpha else "") if x)
    if part.get("type") in ("MissileLauncher", "BombLauncher"):
        slots = part.get("slots") or []
        first = f"{len(slots)} × S{slots[0]['max']}" if slots else "no missile slots"
        return " · ".join(x for x in (first, part.get("manufacturer")) if x)
    grade = " ".join(str(x) for x in (part.get("class"), part.get("grade")) if x)
    return " · ".join(x for x in (part.get("manufacturer"), grade) if x)


@dataclass
class Card:
    item: str
    name: str
    sub: str
    tag: str
    value: str
    unit: str
    bar: float                  # 0–1
    delta: str
    tone: str                   # "better" | "worse" | "same"
    src: str
    fitted: bool
    can_buy: bool               # a shop sells it
    can_craft: bool             # a blueprint makes it
    stock: bool                 # the slot's stock part (no need to buy)
    fitted_as: str | None       # how the fitted part is got (None when this isn't the fitted part)
    number: float = 0.0


def card_for(ctx: Ctx, kind: str, item: str, fitted_item: str, fitted_value: float, fitted_source: str,
             stock_item: str, max_value: float, min_value: float = 0.0) -> Card:
    """A candidate part as a card, compared with what's fitted."""
    part = ctx.items[item]
    a = availability(ctx, item)
    value = stat_of(kind, ctx, item)
    best = stat_of(kind, ctx, item, "craft", best_qualities(ctx.recipes.get(item))) if a.can_craft else value
    lower = lower_is_better(kind)
    diff = value - fitted_value
    better = diff < 0 if lower else diff > 0
    is_fitted = item == fitted_item
    if item == stock_item:
        src = "Stock part"
    elif a.cheapest:
        src = f"{money(a.cheapest['price'])} at {a.cheapest['place']}" + (" · or craft" if a.can_craft else "")
    elif a.can_craft:
        src = "Craft · no known seller"
    else:
        src = "No known seller · not craftable"
    if lower:
        bar = (min_value / value if value > 0 else 1.0)
    else:
        bar = value / max_value if max_value > 0 else 0.0
    same = abs(diff) < 1e-6
    return Card(
        item=item, name=part.get("name") or item,
        sub=describe(part) + (f" · up to {show_stat(best)} crafted" if best > value + 1e-6 else ""),
        tag="stock" if item == stock_item else "buy" if a.can_buy else "craft" if a.can_craft else "unobtainable",
        value=show_stat(value), unit=KIND_STAT[kind][1], bar=min(1.0, bar),
        delta="" if is_fitted else "±0" if same else f"{'▲ +' if diff > 0 else '▼ −'}{show_stat(abs(diff))}",
        tone="same" if is_fitted or same else "better" if better else "worse",
        src=src, fitted=is_fitted, can_buy=a.can_buy, can_craft=a.can_craft, stock=item == stock_item,
        fitted_as=fitted_source if is_fitted else None, number=value)


def tray_choices(ctx: Ctx, rows: list[dict], node: BusNode, paths: list[str], missiles: bool = False) -> list[str]:
    """The parts the tray offers for a node (or its rack's missiles): unobtainable ones left out,
    except the fitted and the stock part."""
    target = node.missile_paths if missiles else paths
    if missiles and node.kind == "rack" and node.missile_paths:
        per_rack = {p.rsplit("/", 1)[0] for p in paths}
        target = [p for p in node.missile_paths if p.rsplit("/", 1)[0] in per_rack]
    stock = {r["path"]: r["item"] for r in fitted(ctx.catalog["ship"], ctx.items, {})}
    keep = {stock.get(target[0]) if target else None,
            next((r["item"] for r in rows if target and r["path"] == target[0]), None)}
    return [c for c in choices_for(ctx, rows, target) if c in keep or obtainable(ctx, c)]


# -- the shopping list -----------------------------------------------------------------------

def view_of(ctx: Ctx, parts: dict, route: str = "stops") -> dict:
    """What the calculator makes of a loadout: rows, nodes, totals, the buy run and the craft list."""
    rows = fitted(ctx.catalog["ship"], ctx.items, parts)
    shop = loadoutcalc.shopping(rows, ctx.items, ctx.offers, route)
    craft = loadoutcalc.crafting(rows, ctx.recipes, ctx.odds, ctx.refining)
    return {"rows": rows, "nodes": bus_nodes(ctx, rows),
            "totals": totals(rows, ctx.items, ctx.recipes, ctx.catalog["ship"].get("basePower")),
            "shopping": shop, "crafting": craft, "cost": shop["total"],
            "craft": sum(p["count"] for p in craft["parts"])}


def snapshot(view: dict, route: str) -> dict:
    """The saved shopping list ("basket"): the buy run as planned now, so it holds still."""
    return {"savedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "route": route,
            "stops": view["shopping"]["stops"], "unsold": view["shopping"]["unsold"],
            "craft": [{"item": p["item"], "count": p["count"]} for p in view["crafting"]["parts"]]}


def keys_of(stops: list[dict], crafting: dict) -> list[str]:
    """Every step on a list: each bought part, each material, each crafted part."""
    return ([f"buy:{i['item']}" for s in stops for sh in s["shops"] for i in sh["items"]]
            + [f"mat:{m['key']}" for m in crafting["materials"]]
            + [f"craft:{p['item']}" for p in crafting["parts"]])


def coverage(basket: dict) -> str:
    """What a list covers, prices aside: which parts, how many, bought or crafted."""
    bought = [i for s in basket.get("stops") or [] for sh in s["shops"] for i in sh["items"]] + list(
        basket.get("unsold") or [])
    return json.dumps([sorted(f"{i['item']}×{i['count']}" for i in bought),
                       sorted(f"{p['item']}×{p['count']}" for p in basket.get("craft") or [])])


def drifted(basket: dict | None, view: dict) -> bool:
    """The loadout changed since the list was saved (a price that moved doesn't count)."""
    return bool(basket) and coverage(basket) != coverage(snapshot(view, basket["route"]))
