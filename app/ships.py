"""Ship catalogue: every ship and vehicle, including unreleased ones, for
My Ships (and later the event organizer's ship pickers).

Sources (refreshed at most weekly, see refresh()):
- Star Citizen Wiki API, ship matrix (api.star-citizen.wiki/api/shipmatrix/
  vehicles): every ship sold on the store, flight-ready or in concept, with
  role, size and loaners. A mirror of RSI's ship matrix; ids are RSI's.
- Star Citizen Wiki API, vehicles (…/api/v2/vehicles): what's in the game:
  the class name (Erkul's ship id, lower case), an image, and the game-only
  variants (Wikelo specials, PYAM Exec, Best In Show…) you can only get in
  game. Linked to the ship matrix by `shipmatrix_name`.
- RSI's ship matrix (robertsspaceindustries.com/ship-matrix/index): only for
  the store image of ships the wiki has no picture of (concept ships).

Without network, the last download (cache folder) or the snapshot bundled
with the app (assets/ships.json, made by tools/update_ship_snapshot.py) is
used. Ship data © the Star Citizen Wiki community (CC BY-SA 4.0); images
are CIG's, shown under the Fankit terms.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app import config

# Paging: the API wants page[number]/page[size] (it ignores page=) and a sort
# key, else pages overlap.
WIKI_MATRIX = "https://api.star-citizen.wiki/api/shipmatrix/vehicles?page%5Bsize%5D=50&sort=name&page%5Bnumber%5D={page}"
WIKI_VEHICLES = ("https://api.star-citizen.wiki/api/v2/vehicles?page%5Bsize%5D=50&sort=class_name"
                 "&page%5Bnumber%5D={page}")
RSI_MATRIX = "https://robertsspaceindustries.com/ship-matrix/index"
ERKUL_SHIP = "https://erkul.games/ships?ship={id}"

CACHE = config.CACHE_DIR / "ships"
CATALOGUE_FILE = CACHE / "catalogue.json"
IMAGE_DIR = CACHE / "images"
SNAPSHOT_FILE = config.ASSETS_DIR / "ships.json"
FORMAT = 2
TIMEOUT = 60

FLIGHT_READY, IN_CONCEPT = "flight-ready", "in-concept"

# The ship matrix's types and sizes, cleaned up (mixed casing, synonyms).
_ROLES = {"combat": "Combat", "destroyer": "Combat", "transporter": "Transport", "transport": "Transport",
          "exploration": "Exploration", "industrial": "Industrial", "support": "Support",
          "competition": "Racing", "multi": "Multi-role", "multi-role": "Multi-role", "ground": "Ground",
          "starter": "Starter"}
ROLES = ["Combat", "Transport", "Exploration", "Industrial", "Support", "Multi-role", "Racing", "Starter",
         "Ground", "Other"]
_SIZES = {"snub": "Snub", "small": "Small", "medium": "Medium", "large": "Large", "capital": "Capital",
          "vehicle": "Ground"}
SIZES = ["Snub", "Small", "Medium", "Large", "Capital", "Ground"]

# Store ships the wiki doesn't link to a game vehicle (bundles, paint and
# show editions): the game class of the ship they are.
_CLASS_ALIASES = {
    "Retaliator": "AEGS_Retaliator",
    "Carrack w/C8X": "ANVL_Carrack",
    "Carrack Expedition w/C8X": "ANVL_Carrack_Expedition",
    "Valkyrie Liberator Edition": "ANVL_Valkyrie",
    "Argo Mole Carbon Edition": "ARGO_MOLE",
    "Argo Mole Talus Edition": "ARGO_MOLE",
    "Caterpillar Best In Show Edition 2949": "DRAK_Caterpillar",
    "Cutlass Black Best In Show Edition 2949": "DRAK_Cutlass_Black",
    "Hammerhead Best In Show Edition 2949": "AEGS_Hammerhead_Showdown",
}
# Store items and game "vehicles" that aren't ships or vehicles.
_NOT_SHIPS = re.compile(r"\b(module|beacon)\b", re.I)


@dataclass
class Ship:
    key: str                    # "sm:<RSI id>" for store ships, "cls:<class>" for game-only ones
    name: str
    manufacturer: str
    role: str                   # one of ROLES
    focus: str                  # e.g. "Heavy Fighter"
    size: str                   # one of SIZES or ""
    status: str                 # FLIGHT_READY or IN_CONCEPT
    store: bool                 # sold on the RSI store (else only obtainable in game)
    class_id: str = ""          # game class, lower case ("aegs_idris_p"); "" for concept ships
    image: str = ""             # image URL
    loaners: list[str] = field(default_factory=list)
    crew: int = 0
    cargo: int = 0              # SCU
    health: int = 0             # hull HP (from the wiki: it's in the game's vehicle XML)
    mass: int = 0               # kg, with its default loadout

    @property
    def concept(self) -> bool:
        return self.status == IN_CONCEPT

    @property
    def erkul_url(self) -> str:
        return ERKUL_SHIP.format(id=self.class_id) if self.class_id else ""

    @property
    def image_file(self) -> Path:
        ext = Path(self.image.split("?", 1)[0]).suffix or ".jpg"
        return IMAGE_DIR / (re.sub(r"[^A-Za-z0-9_-]+", "_", self.key) + ext)


class Catalogue:
    def __init__(self, ships: list[Ship], fetched: float = 0.0):
        self.ships = sorted(ships, key=lambda s: (s.manufacturer, s.name))
        self.by_key = {s.key: s for s in self.ships}
        self.fetched = fetched

    def __len__(self) -> int:
        return len(self.ships)

    def get(self, key: str) -> Ship | None:
        return self.by_key.get(key)

    def search(self, text: str = "", role: str = "", size: str = "") -> list[Ship]:
        words = text.lower().split()
        return [s for s in self.ships
                if (not role or s.role == role) and (not size or s.size == size)
                and all(w in f"{s.manufacturer} {s.name}".lower() for w in words)]

    def class_ids(self) -> set[str]:
        return {s.class_id for s in self.ships if s.class_id}


# -- loading -------------------------------------------------------------------

def _read(path: Path) -> Catalogue | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT:
            return None
        return Catalogue([Ship(**s) for s in data["ships"]], data.get("fetched", 0.0))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def load() -> Catalogue:
    """The last downloaded catalogue, else the bundled snapshot (stale, so a
    refresh is due). Fast; no network."""
    return _read(CATALOGUE_FILE) or _read(SNAPSHOT_FILE) or Catalogue([])


def save(catalogue: Catalogue, path: Path = CATALOGUE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"format": FORMAT, "fetched": catalogue.fetched,
                               "ships": [asdict(s) for s in catalogue.ships]}, indent=0), encoding="utf-8")
    tmp.replace(path)


def refresh(progress=lambda _msg: None) -> Catalogue:
    """Downloads and saves a fresh catalogue. Slow (about 20 MB); call off
    the UI thread. Raises OSError/ValueError on network or format trouble."""
    catalogue = build(progress)
    if len(catalogue) < 100:
        raise ValueError(f"only {len(catalogue)} ships in the download")
    save(catalogue)
    return catalogue


# -- downloading and merging ----------------------------------------------------

def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def _paged(url: str, progress, label: str, key: str) -> list[dict]:
    """Every item of a paged list, once each (by `key`). Raises ValueError
    if items are missing, so a broken download never replaces a good one."""
    items: dict[str, dict] = {}
    page, last, total = 1, 1, 0
    while page <= last:
        progress(f"Downloading {label} ({page}/{last})…")
        data = _get_json(url.format(page=page))
        for item in data.get("data") or []:
            items.setdefault(str(item.get(key)), item)
        meta = data.get("meta") or {}
        last, total = int(meta.get("last_page") or 1), int(meta.get("total") or 0)
        page += 1
    if len(items) < total:
        raise ValueError(f"{label}: got {len(items)} of {total}")
    return list(items.values())


def _en(value) -> str:
    """The wiki's translated fields ({"en_EN": …}) → English text."""
    if isinstance(value, dict):
        value = value.get("en_EN")
    return value.strip() if isinstance(value, str) else ""


def _role(value) -> str:
    return _ROLES.get(_en(value).lower(), "")


def _size(value) -> str:
    return _SIZES.get(_en(value).lower(), "")


def _focus(foci) -> str:
    return ", ".join(f for f in (_en(x) for x in foci or []) if f)


def _image(vehicle: dict | None) -> str:
    for img in (vehicle or {}).get("images") or []:
        url = img.get("thumbnail_url") or img.get("original_url")
        if url:
            return url
    return ""


def build(progress=lambda _msg: None) -> Catalogue:
    matrix = _paged(WIKI_MATRIX, progress, "the ship list", "id")
    vehicles = _paged(WIKI_VEHICLES, progress, "ship details", "uuid")
    progress("Downloading ship images list…")
    try:
        rsi = {x["id"]: x for x in _get_json(RSI_MATRIX).get("data") or []}
    except (OSError, ValueError):
        rsi = {}                # only the concept ships' pictures come from here

    # Game vehicles per ship-matrix name; the one named exactly like the
    # store ship first (the others are paint/edition variants).
    by_matrix: dict[str, list[dict]] = {}
    for v in vehicles:
        name = (v.get("shipmatrix_name") or "").strip()
        if name and v.get("class_name"):
            by_matrix.setdefault(name, []).append(v)
    for name, group in by_matrix.items():
        group.sort(key=lambda v: ((v.get("name") or "").strip() != name, len(v["class_name"])))

    by_class_name = {v["class_name"]: v for v in vehicles if v.get("class_name")}
    ships: list[Ship] = []
    linked: set[str] = set()
    for m in matrix:
        name = (m.get("name") or "").strip()
        if not name or _NOT_SHIPS.search(name):
            continue
        group = by_matrix.get(name, [])
        if not group and _CLASS_ALIASES.get(name) in by_class_name:
            group = [by_class_name[_CLASS_ALIASES[name]]]
        vehicle = group[0] if group else None
        linked.update(v["class_name"] for v in group)
        image = _image(vehicle)
        if not image:
            media = (rsi.get(m.get("id")) or {}).get("media") or []
            image = ((media[0].get("images") or {}).get("store_small") or "") if media else ""
        crew = (m.get("crew") or {}).get("max") or ((vehicle or {}).get("crew") or {}).get("max") or 0
        role = _role(m.get("type")) or "Other"
        ships.append(Ship(
            key=f"sm:{m.get('id')}", name=name,
            manufacturer=((m.get("manufacturer") or {}).get("name") or "").strip(),
            role=role, focus=_focus(m.get("foci")),
            size=_size(m.get("size")) or ("Ground" if role == "Ground" or (vehicle or {}).get("is_vehicle") else ""),
            status=IN_CONCEPT if _en(m.get("production_status")) == IN_CONCEPT else FLIGHT_READY,
            store=True, class_id=(vehicle or {}).get("class_name", "").lower(), image=image,
            loaners=sorted({(l.get("name") or "").strip() for l in m.get("loaner") or []} - {""}),
            crew=int(crew or 0), cargo=int(m.get("cargo_capacity") or 0),
            health=int((vehicle or {}).get("health") or 0), mass=int((vehicle or {}).get("mass_total") or 0),
        ))

    # Game-only variants (not on the store): Wikelo specials, PYAM Exec, … They
    # take role and size from the store ship whose class theirs extends.
    by_class = {s.class_id: s for s in ships if s.class_id}
    seen_names = {s.name for s in ships}
    for v in vehicles:
        cls, name = v.get("class_name") or "", (v.get("name") or "").strip()
        if not cls or cls in linked or not name or name in seen_names or _NOT_SHIPS.search(name):
            continue
        parent = next((by_class[c] for c in sorted(by_class, key=len, reverse=True)
                       if cls.lower().startswith(c + "_")), None)
        seen_names.add(name)
        ships.append(Ship(
            key=f"cls:{cls}", name=name,
            manufacturer=((v.get("manufacturer") or {}).get("name") or (parent.manufacturer if parent else "")),
            role=_role(v.get("type")) or (parent.role if parent else ("Ground" if v.get("is_vehicle") else "Other")),
            focus=_focus(v.get("foci")) or (parent.focus if parent else ""),
            size=_size(v.get("size")) or (parent.size if parent else ("Ground" if v.get("is_vehicle") else "")),
            status=FLIGHT_READY, store=False, class_id=cls.lower(),
            image=_image(v) or (parent.image if parent else ""),
            crew=int((v.get("crew") or {}).get("max") or 0), cargo=int(v.get("cargo_capacity") or 0),
            health=int(v.get("health") or 0), mass=int(v.get("mass_total") or 0),
        ))
    return Catalogue(ships, time.time())


# -- images --------------------------------------------------------------------

def download_image(ship: Ship) -> Path | None:
    """The ship's picture in the cache folder (downloaded the first time).
    Call off the UI thread."""
    if not ship.image:
        return None
    path = ship.image_file
    if path.is_file():
        return path
    try:
        req = urllib.request.Request(ship.image, headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path
    except OSError:
        return None
