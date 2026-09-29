"""Salvage claim browser data: which ships an Adagio salvage claim can
spawn at each difficulty, what they carry, and what that is worth.

Three sources, each stored locally so rendering never touches the network
or the 157 GB archive:

- **Game data** (Data.p4k → Game2.dcb): the claim tiers and their ship
  pools, and each ship's default loadout. Claims pick a ship by tag — every
  tier's spawn option lists a size tag (a distinct Tag record per tier)
  plus AvailableToSalvage; the matching entities are the dedicated
  `*_Unmanned_Salvage` ship variants. Re-extracted automatically once per
  game build (keyed like bindings' p4k cache).
- **Community spreadsheet** (Google Sheets, public CSV export): which
  components come off which ship, their sell/dismantle prices, the claim
  fee per ship, and the cargo observed aboard. Refreshed on demand.
- **UEX** (api.uexcorp.space): average commodity sell prices, used to
  price that cargo. Refreshed on demand.

Item and ship names come from the *vanilla* global.ini in Data.p4k: a
loose StarStrings copy prefixes item names ("Ind/1/C Thermax"), which
would also break matching against the spreadsheet.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from app import bindings, config, p4k
from app.datacore import DataCore

GAME2_ENTRY = "Data\\Game2.dcb"
GENERATOR_RECORD = "ContractGenerator.Adagio_Generator"
CLAIM_TEMPLATE_PREFIX = "@ContractTemplate.Salvage_Lawful"
SALVAGE_VARIANT_SUFFIX = "_Unmanned_Salvage"
SALVAGE_TAG_NAME = "AvailableToSalvage"

SHEET_ID = "1UyZsa8HPKdwbofoFD3Ve1RhRAtGiG_CZaOUXtM-vEbU"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
SHEET_TABS = {"components": "0", "materials": "1365608942"}
UEX_URL = "https://api.uexcorp.space/2.0/commodities"
TIMEOUT = 20

CACHE = config.CACHE_DIR / "salvage"
GAME_FORMAT = 1  # bump when the extracted game-data shape changes

TIER_ORDER = ["Intro", "VeryEasy", "Easy", "Medium", "Hard"]
TIER_LABELS = {"VeryEasy": "Very Easy"}

# Item types worth listing (containers like turrets and racks are walked
# through but not shown themselves).
ITEM_TYPES = {
    "PowerPlant": "Power Plant",
    "Cooler": "Cooler",
    "Shield": "Shield",
    "QuantumDrive": "Quantum Drive",
    "JumpDrive": "Jump Drive",
    "Radar": "Radar",
    "LifeSupportGenerator": "Life Support",
    "WeaponGun": "Weapon",
    "WeaponMining": "Mining Laser",
    "SalvageHead": "Salvage Head",
    "Missile": "Missile",
    "Bomb": "Bomb",
    "EMP": "EMP",
    "QuantumInterdictionGenerator": "QED",
}
TYPE_ORDER = list(ITEM_TYPES.values())
# Only these carry a meaningful grade; weapons and ordnance all read "A".
GRADED_TYPES = {"PowerPlant", "Cooler", "Shield", "QuantumDrive", "JumpDrive", "Radar",
                "LifeSupportGenerator"}
_GRADES = {1: "A", 2: "B", 3: "C", 4: "D"}

# Spreadsheet ship nicknames → salvage-variant class stem.
SHIP_ALIASES = {
    "cutter": "DRAK_Cutter",
    "ion": "CRUS_Starfighter_Ion",
    "inferno": "CRUS_Starfighter_Inferno",
    "315p": "ORIG_315p",
    "325a": "ORIG_325a",
    "350r": "ORIG_350r",
    "400i": "ORIG_400i",
    "890j": "ORIG_890Jump",
    "sabre": "AEGS_Sabre",
    "terrapin": "ANVL_Terrapin",
    "santokiai": "XNAA_SanTokYai",
    "nomad": "CNOU_Nomad",
    "antares": "RSI_Scorpius_Antares",
    "scorpius": "RSI_Scorpius",
    "zeus": "RSI_Zeus_ES",
    "zeus es": "RSI_Zeus_ES",
    "taurus": "RSI_Constellation_Taurus",
    "sentinel": "AEGS_Vanguard_Sentinel",
    "vanguard sentinel": "AEGS_Vanguard_Sentinel",
    "hoplite": "AEGS_Vanguard_Hoplite",
    "vanguard hoplite": "AEGS_Vanguard_Hoplite",
    "harbinger": "AEGS_Vanguard_Harbinger",
    "vanguard harbinger": "AEGS_Vanguard_Harbinger",
    "warden": "AEGS_Vanguard",
    "vanguard warden": "AEGS_Vanguard",
    "redeemer": "AEGS_Redeemer",
    "retaliator": "AEGS_Retaliator",
    "hh": "AEGS_Hammerhead_GS",
    "prowler": "ESPR_Prowler",
    "tali": "ESPR_Talon",
    "talon": "ESPR_Talon",
    "vulture": "DRAK_Vulture",
    "corsair": "DRAK_Corsair",
    "raft": "ARGO_RAFT",
    "mole": "ARGO_MOLE",
    "c1": "CRUS_Spirit_C1",
    "a1": "CRUS_Spirit_A1",
    "msr": "CRUS_Star_Runner",
    "a2": "CRUS_Starlifter_A2",
    "c2": "CRUS_Starlifter_C2",
    "m2": "CRUS_Starlifter_M2",
}

# Spreadsheet cargo shorthand ("1 cop, 4 nit, 1 all the other") → UEX name.
MATERIALS = {
    "cop": "Copper",
    "alu": "Aluminum",
    "waste": "Waste",
    "tin": "Tin",
    "iron": "Iron",
    "carb": "Carbon",
    "pot": "Potassium",
    "tit": "Titanium",
    "it": "Titanium",  # typo in the sheet ("2 it")
    "nit": "Nitrogen",
}
BASE_MATERIALS = list(dict.fromkeys(MATERIALS.values()))
_OTHERS_RE = re.compile(r"^(of\s+)?(all\s+)?(the\s+)?others?$")

# Game item type → the spreadsheet's Type/Comp wording, so a short sheet
# name like "HEX" only ever matches an item of the right kind.
_SHEET_KIND = {
    "PowerPlant": ("power plant",),
    "Cooler": ("cooler",),
    "Shield": ("shield",),
    "QuantumDrive": ("qd",),
    "WeaponMining": ("mining head",),
    "Bomb": ("ordinance",),
}
_NAME_ALIASES = {"arbhor": "arbor"}


class SalvageError(Exception):
    pass


# -- local storage ------------------------------------------------------------

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


# -- game data ----------------------------------------------------------------

def _find(obj, type_name: str):
    """Depth-first search for the first dict of the given DataCore type."""
    if isinstance(obj, dict):
        if obj.get("_type") == type_name:
            return obj
        values = obj.values()
    elif isinstance(obj, list):
        values = obj
    else:
        return None
    for v in values:
        found = _find(v, type_name)
        if found is not None:
            return found
    return None


def _tier_options(generator: dict) -> dict[str, list[dict]]:
    """{tier: [spawn option]} for every lawful salvage claim contract."""
    tiers: dict[str, list[dict]] = {}
    for handler in generator.get("generators") or []:
        for contract in (handler.get("contracts") or []) + (handler.get("introContracts") or []):
            if not str(contract.get("template") or "").startswith(CLAIM_TEMPLATE_PREFIX):
                continue
            tier = contract["debugName"].rsplit("_", 1)[-1]
            for prop in contract["paramOverrides"]["propertyOverrides"]:
                value = prop.get("value") or {}
                if value.get("_type") != "MissionPropertyValue_ShipSpawnDescriptions":
                    continue
                for desc in value.get("spawnDescriptions") or []:
                    for ships in desc.get("ships") or []:
                        for option in ships.get("options") or []:
                            opt = {
                                "tags": sorted(option["tags"]["tags"]),
                                "neg": sorted(option["negativeTags"]["tags"]),
                            }
                            if opt not in tiers.setdefault(tier, []):
                                tiers[tier].append(opt)
    return tiers


def _loc(table: dict[str, str], key: str | None, fallback: str) -> str:
    if key and key.startswith("@"):
        text = table.get(key[1:].lower())
        if text:
            return text
    return fallback


def _item_info(dc: DataCore, loc: dict[str, str], cls: str, memo: dict) -> dict | None:
    if cls in memo:
        return memo[cls]
    info = None
    rec = dc.record("EntityClassDefinition." + cls, max_depth=4)
    attach = _find(rec, "SAttachableComponentParams") if rec else None
    if attach:
        a = attach["AttachDef"]
        name_key = (a.get("Localization") or {}).get("Name")
        desc = _loc(loc, (a.get("Localization") or {}).get("Description"), "")
        family = re.search(r"Class:\s*([^\\\n]+)", desc)
        info = {
            "type": a.get("Type"),
            "name": _loc(loc, name_key, cls),
            "size": a.get("Size"),
            "grade": _GRADES.get(a.get("Grade"), ""),
            "family": family.group(1).strip() if family else "",
        }
    memo[cls] = info
    return info


def _walk_loadout(dc, loc, loadout, memo, counts: dict[str, int], depth=0) -> None:
    if not isinstance(loadout, dict) or depth > 8:
        return
    for entry in loadout.get("entries") or []:
        cls = entry.get("entityClassName") or ""
        ref = entry.get("entityClassReference")
        if not cls and isinstance(ref, str) and ref.startswith("@EntityClassDefinition."):
            cls = ref.split(".", 1)[1]
        if cls:
            info = _item_info(dc, loc, cls, memo)
            if info and info["type"] in ITEM_TYPES:
                counts[cls] = counts.get(cls, 0) + 1
        _walk_loadout(dc, loc, entry.get("loadout"), memo, counts, depth + 1)


def _extract_game_data(channel_root: Path, progress) -> dict:
    progress("Reading Star Citizen game data (once per patch)…")
    raw = p4k.extract(channel_root / "Data.p4k", [GAME2_ENTRY]).get(GAME2_ENTRY)
    if raw is None:
        raise SalvageError("Game2.dcb not found in Data.p4k")
    dc = DataCore(raw)
    del raw

    loc_raw = bindings._load_from_p4k_cached(channel_root, bindings.GLOBAL_INI_ENTRY, "global.ini")
    loc = bindings._parse_ini(loc_raw) if loc_raw else {}

    progress("Finding salvage claim ship pools…")
    generator = dc.record(GENERATOR_RECORD)
    if generator is None:
        raise SalvageError(f"{GENERATOR_RECORD} not found in game data")
    tier_options = _tier_options(generator)

    entity_tags: dict[str, set[str]] = {}
    for name in dc.record_names("EntityClassDefinition."):
        tags = dc.tag_refs(name)
        if tags:
            entity_tags[name.split(".", 1)[1]] = set(tags)

    def tag_name(tag: str) -> str:
        return (dc.record(tag[1:], max_depth=0) or {}).get("tagName", "")

    option_tags = {t for opts in tier_options.values() for o in opts for t in o["tags"]}
    salvage_tag = next((t for t in option_tags if tag_name(t) == SALVAGE_TAG_NAME), None)
    if salvage_tag is None:
        raise SalvageError("Salvage claims no longer use the AvailableToSalvage tag")
    # Only tags carried by salvageable entities select ships; the rest
    # (PoweredOff, Full Cargo, IgnoreHostility…) describe the spawned wreck.
    selecting = set().union(*(t for t in entity_tags.values() if salvage_tag in t))

    tiers = []
    pool_all: set[str] = set()
    for tier in sorted(tier_options, key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 99):
        ships: set[str] = set()
        size_tags: set[str] = set()
        for opt in tier_options[tier]:
            required = set(opt["tags"]) & selecting
            negative = set(opt["neg"])
            size_tags |= required - {salvage_tag}
            for cls, tags in entity_tags.items():
                if required <= tags and not (negative & tags) and "Template" not in cls:
                    ships.add(cls)
        tag_names = sorted(filter(None, map(tag_name, size_tags)))
        stems = sorted({c.removesuffix(SALVAGE_VARIANT_SUFFIX) for c in ships})
        pool_all |= ships
        tiers.append({
            "id": tier,
            "label": TIER_LABELS.get(tier, tier),
            "size": ", ".join(tag_names),
            "ships": stems,
        })

    progress("Reading ship loadouts…")
    memo: dict[str, dict | None] = {}
    ships_out = {}
    for cls in sorted(pool_all):
        rec = dc.record("EntityClassDefinition." + cls) or {}
        attach = _find(rec, "SAttachableComponentParams")
        loc_params = (attach or {}).get("AttachDef", {}).get("Localization") or {}
        stem = cls.removesuffix(SALVAGE_VARIANT_SUFFIX)
        counts: dict[str, int] = {}
        loadout = _find(rec, "SEntityComponentDefaultLoadoutParams")
        _walk_loadout(dc, loc, (loadout or {}).get("loadout"), memo, counts)
        comps = []
        for item_cls, qty in counts.items():
            info = memo[item_cls]
            comps.append({"cls": item_cls, "qty": qty, **info, "type": ITEM_TYPES[info["type"]],
                          "game_type": info["type"]})
        comps.sort(key=lambda c: (TYPE_ORDER.index(c["type"]), -(c["size"] or 0), c["name"]))
        ships_out[stem] = {
            "cls": cls,
            "name": _loc(loc, loc_params.get("Name"), stem),
            "short": _loc(loc, loc_params.get("ShortName"), ""),
            "components": comps,
        }
    return {"format": GAME_FORMAT, "tiers": tiers, "ships": ships_out}


def load_game_data(channel_root: Path, progress=lambda _msg: None) -> dict:
    """Slow the first time after a game patch (decodes Game2.dcb, ~1 min);
    read from the local cache afterwards. Call off the UI thread.
    """
    p4k_path = channel_root / "Data.p4k"
    if not p4k_path.is_file():
        raise SalvageError(f"Data.p4k not found in {channel_root}")
    cache_file = CACHE / f"game-{bindings._cache_key(p4k_path)}.json"
    cached = _read_json(cache_file)
    if cached and cached.get("format") == GAME_FORMAT:
        return cached
    data = _extract_game_data(channel_root, progress)
    for stale in CACHE.glob("game-*.json"):
        stale.unlink(missing_ok=True)
    _write_json(cache_file, data)
    return data


# -- spreadsheet ------------------------------------------------------------------

def refresh_sheet() -> None:
    """Downloads both spreadsheet tabs into the local cache. On failure the
    previous copy is left untouched.
    """
    tabs = {}
    for name, gid in SHEET_TABS.items():
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
        try:
            data = _http_get(url)
        except OSError as exc:
            raise SalvageError(f"Could not download the spreadsheet:\n{exc}") from exc
        if data.lstrip().startswith(b"<"):
            raise SalvageError("The spreadsheet is no longer publicly readable.")
        tabs[name] = data.decode("utf-8", "replace")
    _write_json(CACHE / "sheet.json", {"fetched": time.time(), "tabs": tabs})


def refresh_uex() -> None:
    try:
        payload = json.loads(_http_get(UEX_URL))
    except (OSError, json.JSONDecodeError) as exc:
        raise SalvageError(f"Could not fetch UEX prices:\n{exc}") from exc
    if payload.get("status") != "ok":
        raise SalvageError(f"UEX returned an error: {payload.get('status')}")
    prices = {
        c["name"]: {"sell": c.get("price_sell") or 0, "buy": c.get("price_buy") or 0}
        for c in payload.get("data") or []
    }
    _write_json(CACHE / "uex.json", {"fetched": time.time(), "prices": prices})


def _num(text: str) -> float | None:
    """Sheet numbers use '.' for thousands and ',' for decimals."""
    text = (text or "").strip()
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9]", "", text.lower())
    for old, new in _NAME_ALIASES.items():
        text = text.replace(old, new)
    return text


def _ship_list(text: str) -> tuple[set[str], list[str]]:
    stems, unknown = set(), []
    for part in re.split(r"[/,]", text or ""):
        part = part.strip().lower()
        if not part:
            continue
        stem = SHIP_ALIASES.get(part)
        if stem:
            stems.add(stem)
        else:
            unknown.append(part)
    return stems, unknown


def parse_cargo(note: str) -> dict[str, int]:
    """'4 tin, 2 alu, 1 of the others' → {'Tin': 4, 'Aluminum': 2, …}.
    Tokens that aren't cargo ("QD stuck", "no components") are skipped.
    """
    cargo: dict[str, int] = {}
    others: int | None = None
    carry: int | None = None
    for token in (note or "").lower().split(","):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():  # "1, alu"
            carry = int(token)
            continue
        m = re.match(r"(\d+)\s*(.*)", token)
        if m:
            count, rest = int(m.group(1)), m.group(2).strip()
        elif carry is not None:
            count, rest = carry, token
        else:
            continue
        carry = None
        if _OTHERS_RE.match(rest):
            others = count
            continue
        word = rest.split()[0] if rest else ""
        material = MATERIALS.get(word) or next(
            (m for k, m in MATERIALS.items() if len(k) > 2 and word.startswith(k)), None
        )
        if material:
            cargo[material] = cargo.get(material, 0) + count
    if others is not None:
        for material in BASE_MATERIALS:
            cargo.setdefault(material, others)
    return cargo


@dataclass
class SheetComponent:
    name: str
    kind: str      # Comp column: Component / Weapon / Utility
    type: str      # Type column: Cooler, Power Plant, QD, Laser cannon, …
    family: str
    grade: str
    sell: float | None
    dismantle: float | None
    ships: set[str]
    materials: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class SheetShip:
    label: str
    fee: float | None
    note: str
    cargo: dict[str, int]


@dataclass
class Sheet:
    fetched: float
    components: list[SheetComponent]
    ships: dict[str, SheetShip]           # by class stem
    where_to_sell: list[tuple[str, str]]
    unmatched: list[str]                  # sheet ship names we couldn't place


def load_sheet() -> Sheet | None:
    stored = _read_json(CACHE / "sheet.json")
    if not stored:
        return None
    rows = list(csv.reader(io.StringIO(stored["tabs"]["components"])))
    components, ships, sell_info, unmatched = [], {}, [], []
    for row in rows[1:]:
        row += [""] * (19 - len(row))
        name = row[0].strip()
        if name:
            stems, unknown = _ship_list(row[9])
            unmatched += unknown
            components.append(SheetComponent(
                name=name, kind=row[1].strip(), type=row[2].strip(), family=row[4].strip(),
                grade=row[5].strip(), sell=_num(row[7]), dismantle=_num(row[8]), ships=stems,
            ))
        label = row[11].strip()
        if not label:
            continue
        fee = _num(row[12])
        stem = SHIP_ALIASES.get(label.lower())
        if fee is None and stem is None:
            if row[12].strip():
                sell_info.append((label, row[12].strip()))
            continue
        if stem is None:
            unmatched.append(label.lower())
            continue
        ships[stem] = SheetShip(label=label, fee=fee, note=row[16].strip(),
                                cargo=parse_cargo(row[16]))

    by_prefix = {_norm(c.name): c for c in components}
    for row in list(csv.reader(io.StringIO(stored["tabs"]["materials"])))[1:]:
        row += [""] * (10 - len(row))
        key = _norm(row[0])
        if not key:
            continue
        comp = by_prefix.get(key) or next(
            (c for n, c in by_prefix.items() if n.startswith(key)), None
        )
        if comp is None:
            continue
        for i in (1, 4, 7):
            mat, mult = row[i].strip(), _num(row[i + 1])
            if mat and mat.lower() != "null":
                comp.materials.append((mat.title(), mult or 0.0))
    return Sheet(
        fetched=stored.get("fetched", 0), components=components, ships=ships,
        where_to_sell=sell_info, unmatched=sorted(set(unmatched)),
    )


def load_uex() -> tuple[float, dict[str, dict]] | None:
    stored = _read_json(CACHE / "uex.json")
    if not stored:
        return None
    return stored.get("fetched", 0), stored.get("prices", {})


# -- combining it all ------------------------------------------------------------

@dataclass
class ComponentRow:
    name: str
    type: str
    size: int | None
    grade: str
    family: str
    qty: int
    salvageable: str        # "yes" | "unlisted" (known item, not recorded on this ship) | "unknown"
    sell: float | None
    dismantle: float | None
    materials: list[tuple[str, float]]

    @property
    def best(self) -> float:
        return max(self.sell or 0, self.dismantle or 0)

    def materials_text(self) -> str:
        # Fractions are SCU of refined material; whole numbers are gem counts.
        return ", ".join(
            f"{mat} ×{amount:g}" if amount >= 1 else f"{mat} {amount:g} SCU"
            for mat, amount in self.materials
        )


@dataclass
class CargoRow:
    material: str
    scu: int
    price: float | None

    @property
    def value(self) -> float:
        return self.scu * (self.price or 0)


@dataclass
class ShipRow:
    stem: str
    name: str
    in_sheet: bool
    fee: float | None
    note: str
    components: list[ComponentRow]
    cargo: list[CargoRow]

    @property
    def components_value(self) -> float:
        return sum(c.best * c.qty for c in self.components if c.salvageable == "yes")

    @property
    def unconfirmed_value(self) -> float:
        """Parts the sheet prices but hasn't recorded coming off this ship."""
        return sum(c.best * c.qty for c in self.components if c.salvageable == "unlisted")

    @property
    def cargo_value(self) -> float:
        return sum(c.value for c in self.cargo)

    @property
    def net(self) -> float:
        return self.components_value + self.cargo_value - (self.fee or 0)


def _match_component(comp: dict, sheet: Sheet) -> SheetComponent | None:
    game = _norm(comp["name"])
    kinds = _SHEET_KIND.get(comp["game_type"])
    best = None
    for row in sheet.components:
        if kinds is not None and row.type.lower() not in kinds:
            continue
        if kinds is None and comp["game_type"] == "WeaponGun" and row.kind.lower() != "weapon":
            continue
        key = _norm(row.name)
        if key and (game == key or game.startswith(key)) and (best is None or len(key) > len(_norm(best.name))):
            best = row
    return best


def build_rows(game: dict, tier_id: str, sheet: Sheet | None, prices: dict[str, dict]) -> list[ShipRow]:
    tier = next((t for t in game["tiers"] if t["id"] == tier_id), None)
    if tier is None:
        return []
    rows = []
    for stem in tier["ships"]:
        ship = game["ships"].get(stem)
        if ship is None:
            continue
        sheet_ship = sheet.ships.get(stem) if sheet else None
        comps = []
        for c in ship["components"]:
            match = _match_component(c, sheet) if sheet else None
            if match is None:
                state = "unknown"
            else:
                state = "yes" if stem in match.ships else "unlisted"
            comps.append(ComponentRow(
                name=c["name"], type=c["type"], size=c["size"],
                grade=(c["grade"] or (match.grade if match else "")) if c["game_type"] in GRADED_TYPES else "",
                family=c["family"] or (match.family if match else ""), qty=c["qty"], salvageable=state,
                sell=match.sell if match else None, dismantle=match.dismantle if match else None,
                materials=match.materials if match else [],
            ))
        cargo = []
        if sheet_ship:
            for material, scu in sorted(sheet_ship.cargo.items(), key=lambda kv: (-kv[1], kv[0])):
                price = prices.get(material, {}).get("sell") or None
                cargo.append(CargoRow(material, scu, price))
        rows.append(ShipRow(
            stem=stem, name=ship["name"], in_sheet=sheet_ship is not None,
            fee=sheet_ship.fee if sheet_ship else None, note=sheet_ship.note if sheet_ship else "",
            components=comps, cargo=cargo,
        ))
    return rows
