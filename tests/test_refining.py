"""app.refining and assets/refining.json."""

import json
import os
import unittest
from pathlib import Path

from app import refining


class RefiningTest(unittest.TestCase):
    def test_ore_needed(self):
        self.assertAlmostEqual(0.78 / 0.45, refining.ore_needed("Stileron", 0.78), places=6)

    def test_not_refined(self):
        self.assertIsNone(refining.ore_needed("Hadanite", 1))

    def test_every_row_is_complete(self):
        for material, row in refining.table()["materials"].items():
            self.assertTrue(0 < row["yield"] <= 1, material)
            self.assertTrue(row["ore"] and row["name"] and row["source"], material)
            self.assertIsInstance(row["confirmed"], bool)


CACHE = os.environ.get("SCT_LOADOUTDATA")   # a built loadoutdata JSON, to check recipe coverage


@unittest.skipUnless(CACHE and Path(CACHE).is_file(), "needs SCT_LOADOUTDATA pointing at a built loadoutdata file")
class CoverageTest(unittest.TestCase):
    def test_every_recipe_resource_has_a_row(self):
        data = json.loads(Path(CACHE).read_text(encoding="utf-8"))
        used = {o["resource"] for r in data["recipes"].values() for s in r["slots"] for o in s["options"] if o.get("resource")}
        self.assertEqual(set(), used - set(refining.table()["materials"]))


if __name__ == "__main__":
    unittest.main()
