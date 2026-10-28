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

from app import datahub, loadoutcalc, uexparts
from app.loadoutmodel import catalog_for, odds_for, offers_for, refining_for

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "loadouts"


def main(channel_root: str, ship_cls: str, cases_path: str) -> None:
    root = Path(channel_root)
    data = datahub.GAME_SOURCES["loadoutdata"].read(root)
    if data is None:
        sys.exit("No loadout data for this build yet: start the launcher once so it reads the game files.")
    catalog = catalog_for({"ships": data.ships, "items": data.items, "recipes": data.recipes}, ship_cls)
    offers = offers_for(catalog, uexparts.load())
    mining = datahub.read_game("mining", root)
    odds = odds_for(catalog, mining)
    refine = refining_for()
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
