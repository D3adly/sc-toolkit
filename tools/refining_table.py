"""Adds the ores a game build has to assets/refining.json (app.refining), keeping every existing value.

    .venv/bin/python -m tools.refining_table "/path/to/StarCitizen/LIVE"

New ores get the community default (see the file's "default"), marked unconfirmed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app import datahub, refining


def ores(game) -> dict[str, dict]:
    """Refined resource id → {ore, name} for every ore whose ResourceType names a refined version."""
    out = {}
    for rec_name in game.dc.record_names("ResourceType."):
        rec = game.dc.record(rec_name, max_depth=2) or {}
        refined = rec.get("refinedVersion")
        ore = rec_name.split(".", 1)[1]
        if not isinstance(refined, str) or not refined.startswith("@ResourceType.") or ore.startswith("ConstructionMaterial"):
            continue
        target = game.dc.record(refined[1:], max_depth=1) or {}
        name = game.loc.get(str(target.get("displayName") or "@").lstrip("@").lower(), "") or refined.split(".", 1)[1]
        out[refined.split(".", 1)[1]] = {"ore": ore, "name": name}
    return out


def main(channel_root: str) -> None:
    data = json.loads(refining.TABLE.read_text(encoding="utf-8"))
    default = data["default"]
    added = 0
    for material, info in sorted(ores(datahub.GameFiles(Path(channel_root))).items()):
        if material not in data["materials"]:
            data["materials"][material] = {**info, "yield": default["yield"], "confirmed": False, "source": default["source"]}
            added += 1
    data["materials"] = dict(sorted(data["materials"].items()))
    refining.TABLE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{added} ores added, {len(data['materials'])} in the table")


if __name__ == "__main__":
    main(sys.argv[1])
