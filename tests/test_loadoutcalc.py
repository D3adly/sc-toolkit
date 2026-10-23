"""app.loadoutcalc: the golden fixtures (shared with the website's TypeScript calculator), the
numbers checked by hand against the game files, and the rules underneath."""

import json
import unittest
from pathlib import Path

from app import loadoutcalc as lc

FIXTURES = Path(__file__).parent / "fixtures" / "loadouts"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _run(fx: dict, case: dict) -> dict:
    return lc.calculate(fx["catalog"], case["loadout"], fx["offers"], fx["odds"], fx["refining"], case["route"])


class GoldenTest(unittest.TestCase):
    def test_every_fixture_case(self):
        files = sorted(FIXTURES.glob("*.json"))
        self.assertTrue(files)
        for path in files:
            fx = json.loads(path.read_text(encoding="utf-8"))
            for case in fx["cases"]:
                with self.subTest(fixture=path.stem, case=case["name"]):
                    # Through JSON, as the TypeScript side sees it.
                    self.assertEqual(case["expect"], json.loads(json.dumps(_run(fx, case))))


class HandCheckedTest(unittest.TestCase):
    """Numbers worked out by hand from the game files (build 4.10.2) before the calculator existed."""

    @classmethod
    def setUpClass(cls):
        cls.fx = _fixture("aegs_gladius")
        cls.cases = {c["name"]: _run(cls.fx, c) for c in cls.fx["cases"]}

    def test_stock(self):
        t = self.cases["stock"]["totals"]
        self.assertEqual(1944.58, t["dps"])          # 2 × 43.65 × 750/60 + 32 × 1600/60
        self.assertEqual(119.3, t["alpha"])
        self.assertEqual((6336.0, 1204.0), (t["shieldHp"], t["shieldRegen"]))
        self.assertEqual((16.0, 11.0, 25.0), (t["segments"], t["powerMin"], t["powerMax"]))
        self.assertEqual((6, 12160.0), (t["missiles"], t["missileDamage"]))
        self.assertEqual(2350.0, self.cases["stock"]["hull"])

    def test_brawler(self):
        r = self.cases["brawler"]
        self.assertEqual(2220.61, r["totals"]["dps"])   # M5A 410.184 × 100/60 each
        self.assertEqual(7290.84, r["totals"]["shieldHp"])  # FR-66: 3,168 × (1 + .0747 + .0760) each
        self.assertEqual(1, len(r["shopping"]["stops"]))
        self.assertEqual("HUR-L5 High Course Station", r["shopping"]["stops"][0]["place"])
        self.assertEqual(234290.0, r["shopping"]["total"])
        stileron = next(m for m in r["crafting"]["materials"] if m["key"] == "Stileron")
        self.assertEqual((0.78, 874, 1.7333), (stileron["amount"], stileron["quality"], stileron["oreScu"]))
        feyn = next(m for m in r["crafting"]["materials"] if m["name"] == "Feynmaline")
        self.assertEqual((40.0, 880, 3.75), (feyn["amount"], feyn["quality"], feyn["odds"]["stanton"]))

    def test_flags(self):
        flags = {p["path"]: p for p in self.cases["mixed-sides-obsolete-and-overrides"]["parts"]}
        self.assertTrue(flags["hardpoint_radar"]["obsolete"])
        self.assertTrue(flags["hardpoint_missilerack_left_wing_outer"]["unobtainable"])
        self.assertEqual("buy", flags["hardpoint_gun_left_wing/hardpoint_class_2"]["source"])
        self.assertEqual("craft", flags["hardpoint_gun_right_wing/hardpoint_class_2"]["source"])


class RulesTest(unittest.TestCase):
    def test_rounding_is_half_away_from_zero(self):
        self.assertEqual((2.68, -2.68, 0.13), (lc.rnd(2.675), lc.rnd(-2.675), lc.rnd(0.125)))

    def test_piecewise_quality(self):
        ranges = [{"from": 0, "to": 500, "start": 0.9, "end": 1.0, "kind": "factor"},
                  {"from": 501, "to": 1000, "start": 1.0, "end": 1.1, "kind": "factor"}]
        self.assertAlmostEqual(1 + 0.1 * 373 / 499, lc.modifier_value(ranges, 874)[0])
        self.assertEqual(0.9, lc.modifier_value(ranges, 0)[0])
        add = [{"from": 0, "to": 1000, "start": 0, "end": 3, "kind": "add"}]
        self.assertEqual((2.0, "add"), lc.modifier_value(add, 600))

    def test_fits(self):
        slot = {"min": 1, "max": 1, "types": [["QuantumDrive", ["QDrive"]]], "tags": ""}
        self.assertTrue(lc.fits(slot, {"type": "QuantumDrive", "subtype": "UNDEFINED", "size": 1}))
        self.assertFalse(lc.fits(slot, {"type": "QuantumDrive", "subtype": "UNDEFINED", "size": 2}))
        stale = {"min": 1, "max": 2, "types": [["Cooler", ["$editable"]]], "tags": ""}
        self.assertTrue(lc.fits(stale, {"type": "Cooler", "subtype": "UNDEFINED", "size": 2}))
        tagged = {"min": 3, "max": 3, "types": [["WeaponGun", ["Gun"]]], "tags": "$Special"}
        self.assertFalse(lc.fits(tagged, {"type": "WeaponGun", "subtype": "Gun", "size": 3, "tags": []}))
        self.assertTrue(lc.fits(tagged, {"type": "WeaponGun", "subtype": "Gun", "size": 3, "tags": ["Special"]}))


if __name__ == "__main__":
    unittest.main()
