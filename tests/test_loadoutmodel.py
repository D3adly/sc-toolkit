"""app.loadoutmodel (the website's loadout editor model, ported): the bus, the slot names, fitting
parts and how they're got, and the saved shopping list."""

import json
import unittest
from pathlib import Path

from app import loadoutcalc, loadoutmodel as m

FIXTURES = Path(__file__).parent / "fixtures" / "loadouts"


def _ctx(name: str) -> m.Ctx:
    fx = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return m.Ctx(fx["catalog"], fx["offers"], fx["odds"], fx["refining"])


class BusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _ctx("aegs_gladius")
        cls.view = m.view_of(cls.ctx, {})

    def test_weapons_first_then_systems_in_kind_order(self):
        kinds = [n.kind for n in self.view["nodes"]]
        self.assertEqual(kinds, ["gun", "gun", "rack", "rack", "shield", "power", "cooler", "quantum", "radar"])

    def test_paired_ports_are_one_node(self):
        wing = self.view["nodes"][0]
        self.assertEqual((wing.label, wing.size, len(wing.paths)), ("Guns · Wing", "S3", 2))
        self.assertEqual(wing.source, "stock")

    def test_slot_names(self):
        self.assertEqual(m.slot_names(["a/hardpoint_weapon_left", "a/hardpoint_weapon_right"]),
                         [("a/hardpoint_weapon_left", "Left"), ("a/hardpoint_weapon_right", "Right")])

    def test_only_other_kinds_are_better_lower(self):
        self.assertTrue(m.lower_is_better("other"))
        self.assertFalse(any(m.lower_is_better(k) for k in m.KIND_ORDER if k != "other"))


class FittingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _ctx("aegs_gladius")
        cls.view = m.view_of(cls.ctx, {})
        cls.wing = cls.view["nodes"][0]
        cls.choices = m.choices_for(cls.ctx, cls.view["rows"], cls.wing.paths)

    def test_craft_only_parts_cannot_be_bought(self):
        item = next(c for c in self.choices if m.availability(self.ctx, c).can_craft
                    and not m.availability(self.ctx, c).can_buy)
        self.assertEqual(m.default_source(self.ctx, item), "craft")

    def test_fitting_a_pair_fits_both_and_the_totals_follow(self):
        item = next(c for c in self.choices if c != self.wing.item and m.availability(self.ctx, c).can_buy)
        parts = m.fit_part(self.ctx, {}, self.wing.paths, item, "buy")
        self.assertEqual({p: parts[p]["item"] for p in self.wing.paths}, {p: item for p in self.wing.paths})
        self.assertTrue(all(parts[p]["source"] == "buy" for p in self.wing.paths))
        rows = loadoutcalc.fitted(self.ctx.catalog["ship"], self.ctx.items, parts)
        expect = loadoutcalc.totals(rows, self.ctx.items, self.ctx.recipes, self.ctx.catalog["ship"].get("basePower"))
        self.assertEqual(m.totals_with(self.ctx, parts)["dps"], expect["dps"])
        self.assertNotEqual(m.totals_with(self.ctx, parts)["dps"], self.view["totals"]["dps"])

    def test_putting_the_stock_part_back_is_stock(self):
        other = next(c for c in self.choices if c != self.wing.item and m.availability(self.ctx, c).can_buy)
        parts = m.fit_part(self.ctx, {}, self.wing.paths, other, "buy")
        back = m.fit_part(self.ctx, parts, self.wing.paths, self.wing.item)
        self.assertTrue(all(back.get(p, {"source": "stock"})["source"] == "stock" for p in self.wing.paths))


class BasketTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _ctx("aegs_gladius")
        view = m.view_of(cls.ctx, {})
        wing = view["nodes"][0]
        item = next(c for c in m.choices_for(cls.ctx, view["rows"], wing.paths)
                    if c != wing.item and m.availability(cls.ctx, c).can_buy)
        cls.parts = m.fit_part(cls.ctx, {}, wing.paths, item, "buy")
        cls.item = item

    def test_saved_list_has_the_buy_ticks(self):
        view = m.view_of(self.ctx, self.parts)
        basket = m.snapshot(view, "stops")
        self.assertEqual(basket["route"], "stops")
        keys = m.keys_of(basket["stops"], view["crafting"])
        self.assertIn(f"buy:{self.item}", keys)

    def test_drift_only_after_the_loadout_changes(self):
        view = m.view_of(self.ctx, self.parts)
        basket = m.snapshot(view, "stops")
        self.assertFalse(m.drifted(basket, view))
        self.assertTrue(m.drifted(basket, m.view_of(self.ctx, {})))
        self.assertFalse(m.drifted(None, view))


if __name__ == "__main__":
    unittest.main()
