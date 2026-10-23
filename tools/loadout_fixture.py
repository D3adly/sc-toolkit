"""Writes a golden fixture for the loadout calculator (app.loadoutcalc): one ship's catalog cut from
the cached loadout data, frozen UEX offers, mining odds and refining rows, plus cases (a loadout and a
route) with the calculator's output. The website's TypeScript calculator must reproduce every case.

    .venv/bin/python -m tools.loadout_fixture "/path/to/StarCitizen/LIVE" aegs_gladius cases.json

cases.json: [{"name", "loadout": {"parts": {…}}, "route": "stops" | "price"}, …]
Fixtures are written to tests/fixtures/loadouts/<ship>.json. Re-generate after changing the
calculator on purpose, and check the numbers before committing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app import datahub, loadoutcalc, refining, uexparts

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "loadouts"


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
        for cls in loadoutcalc.candidates(slot, items):
            if cls not in keep:
                keep.add(cls)
                for sub in items[cls].get("slots") or []:
                    visit(sub, depth + 1)

    for slot in ship["slots"]:
        visit(slot, 0)
    return {"ship": ship, "items": {k: items[k] for k in sorted(keep)},
            "recipes": {k: data["recipes"][k] for k in sorted(keep) if k in data["recipes"]}}


def offers_for(catalog: dict, prices: uexparts.Prices | None) -> dict:
    out = {}
    for part in catalog["items"].values():
        rows = prices.offers(part.get("uuid") or "") if prices else []
        if rows:
            out[part["uuid"]] = [{"terminal": o.terminal, "shop": o.shop, "place": o.place, "system": o.system,
                                  "planet": o.planet, "moon": o.moon, "price": o.price, "reported": o.reported}
                                 for o in rows]
    return out


def odds_for(catalog: dict, mining: dict | None) -> dict:
    quality, names = (mining or {}).get("quality") or {}, (mining or {}).get("resources") or {}
    wanted = set()
    table = refining.table()["materials"]
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


def main(channel_root: str, ship_cls: str, cases_path: str) -> None:
    root = Path(channel_root)
    data = datahub.GAME_SOURCES["loadoutdata"].read(root)
    if data is None:
        sys.exit("No loadout data for this build yet: start the launcher once so it reads the game files.")
    catalog = catalog_for({"ships": data.ships, "items": data.items, "recipes": data.recipes}, ship_cls)
    offers = offers_for(catalog, uexparts.load())
    mining = datahub.read_game("mining", root)
    odds = odds_for(catalog, mining)
    table = refining.table()["materials"]
    refine = {k: {"yield": v["yield"], "ore": v["ore"]} for k, v in table.items()}
    cases = []
    for case in json.loads(Path(cases_path).read_text(encoding="utf-8")):
        route = case.get("route", "stops")
        cases.append({**case, "route": route,
                      "expect": loadoutcalc.calculate(catalog, case["loadout"], offers, odds, refine, route)})
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{ship_cls}.json"
    target.write_text(json.dumps({"catalog": catalog, "offers": offers, "odds": odds, "refining": refine,
                                  "cases": cases}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{target}: {len(catalog['items'])} parts, {len(cases)} cases, {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(*sys.argv[1:4])
