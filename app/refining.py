"""Our refining table: how much refined material an ore gives at the best-yield refining method,
refinery bonuses left out (owner's rule: the craft list's ore amount is a guide). The game files only
name the methods (RefiningProcess speed × care) and UEX only rates them, so the values are ours:
prefilled from community measurements, confirmed or corrected after in-game tests. The table lives in
assets/refining.json; tools/refining_table.py adds the ores a patch brings without touching values.

yield = refined SCU out per ore SCU in, so ore needed = refined needed ÷ yield.
"""

from __future__ import annotations

import json
from functools import lru_cache

from app import config

TABLE = config.ASSETS_DIR / "refining.json"


@lru_cache(maxsize=1)
def table() -> dict:
    try:
        return json.loads(TABLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"materials": {}}


def entry(material: str) -> dict | None:
    """The table row for a refined material by its resource id ("Stileron", "Pressurized_Ice")."""
    return (table().get("materials") or {}).get(material)


def ore_needed(material: str, refined_scu: float) -> float | None:
    """Ore SCU to mine for that much refined material; None if the material isn't refined from ore."""
    row = entry(material)
    if not row or not row.get("yield"):
        return None
    return refined_scu / float(row["yield"])
