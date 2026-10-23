"""app.loadoutdata: variant resolution and uuids (no game files), and real ships with SCT_GAME."""

import os
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from app import loadoutdata

BASE = """<Vehicle name="TEST_Ship">
  <Parts id="xmlParts">
    <Part name="Body" damageMax="1000">
      <Parts>
        <Part name="hardpoint_gun" damageMax="50">
          <ItemPort id="modGun" minSize="3" maxSize="3" flags="editable" display_name="port_NameGun">
            <Types><Type type="WeaponGun" subtypes="Gun"/><Type type="Turret" subtypes="Gun,GunTurret"/></Types>
          </ItemPort>
        </Part>
        <Part name="hardpoint_extra" skipPart="1" id="modExtra">
          <ItemPort minSize="1" maxSize="1" flags="uneditable"><Types><Type type="PowerPlant"/></Types></ItemPort>
        </Part>
      </Parts>
    </Part>
  </Parts>
  <Modifications>
    <Modification name="Big">
      <Elems>
        <Elem idRef="modGun" name="minsize" value="4"/>
        <Elem idRef="modGun" name="maxSize" value="4"/>
        <Elem idRef="modExtra" name="skipPart" value="0"/>
      </Elems>
    </Modification>
    <Modification name="Swap" patchFile="Modifications/TEST_Swap"><Elems/></Modification>
  </Modifications>
</Vehicle>"""
PATCH = """<Modifications><Parts id="xmlParts"><Part name="Body" damageMax="2000"><Parts>
  <Part name="hardpoint_shield"><ItemPort minSize="1" maxSize="1" flags="$editable"><Types><Type type="Shield"/></Types></ItemPort></Part>
</Parts></Part></Parts></Modifications>"""


def _files():
    return {"test_ship.xml": ET.fromstring(BASE), "modifications/test_swap.xml": ET.fromstring(PATCH)}


def _ports(root):
    return {p.get("name"): p.find("ItemPort") for p in loadoutdata._parts(root.find("Parts")) if p.find("ItemPort") is not None}


class VariantTest(unittest.TestCase):
    def test_base_skips_skipped_parts(self):
        root = loadoutdata.resolve_vehicle(_files(), "Scripts/Entities/Vehicles/Implementations/Xml/TEST_Ship.xml")
        self.assertEqual(["hardpoint_gun"], list(_ports(root)))
        self.assertEqual(1000.0, loadoutdata._hull(root))

    def test_elems_edit_attributes_case_insensitively(self):
        root = loadoutdata.resolve_vehicle(_files(), "scripts/entities/vehicles/implementations/xml/test_ship.xml", "big")
        ports = _ports(root)
        self.assertEqual({"hardpoint_gun", "hardpoint_extra"}, set(ports))
        slot = loadoutdata._xml_slot(next(p for p in loadoutdata._parts(root.find("Parts")) if p.get("name") == "hardpoint_gun"),
                                     ports["hardpoint_gun"], {})
        self.assertEqual((4, 4), (slot["min"], slot["max"]))
        self.assertEqual([["WeaponGun", ["Gun"]], ["Turret", ["Gun", "GunTurret"]]], slot["types"])
        self.assertEqual("Gun", slot["label"])

    def test_patch_file_replaces_elements_by_id(self):
        root = loadoutdata.resolve_vehicle(_files(), "Scripts/Entities/Vehicles/Implementations/Xml/TEST_Ship.xml", "Swap")
        self.assertEqual(["hardpoint_shield"], list(_ports(root)))
        self.assertEqual(2000.0, loadoutdata._hull(root))

    def test_base_file_is_not_changed(self):
        files = _files()
        loadoutdata.resolve_vehicle(files, "test_ship.xml", "Big")
        self.assertEqual("3", files["test_ship.xml"].find(".//ItemPort").get("minSize"))

    def test_unknown_definition(self):
        self.assertIsNone(loadoutdata.resolve_vehicle(_files(), "nope.xml"))


class UuidTest(unittest.TestCase):
    def test_guid_byte_order(self):
        want = uuid.UUID("4a8d0265-7476-401a-a50f-5780cd212656")
        raw = want.bytes[7::-1] + want.bytes[:7:-1]        # how DataCore stores it
        self.assertEqual(str(want), loadoutdata.entity_uuid(raw))


GAME = Path(os.environ["SCT_GAME"]) if os.environ.get("SCT_GAME") else None


@unittest.skipUnless(GAME and (GAME / "Data.p4k").is_file(), "needs SCT_GAME pointing at a game channel folder")
class GameTest(unittest.TestCase):
    data: dict = {}

    @classmethod
    def setUpClass(cls):
        from app import datahub
        game = datahub.GameFiles(GAME)
        cls.data = loadoutdata.build(game, lambda _m: None, {"aegs_gladius", "anvl_hornet_f7a_mk2", "anvl_hornet_f7c_mk2"})

    def slot(self, ship, sid):
        return next(s for s in self.data["ships"][ship]["slots"] if s["id"].lower() == sid)

    def test_gladius(self):
        items = self.data["items"]
        ship = self.data["ships"]["aegs_gladius"]
        self.assertEqual(2350.0, ship["hull"])
        nose = self.slot("aegs_gladius", "hardpoint_gun_nose")
        self.assertEqual("mount_gimbal_s3", nose["default"])
        self.assertEqual("gats_ballisticgatling_s3", nose["children"][0]["default"])
        # Stock burst DPS: 2 × CF-337 + Mantis ≈ 1,945; shields 2 × 3,168.
        def dps(cls):
            g = items[cls]["gun"]
            return sum(g["alpha"].values()) * g["pellets"] * g["rpm"] / 60
        guns = [self.slot("aegs_gladius", s)["children"][0]["default"] for s in ("hardpoint_gun_left_wing", "hardpoint_gun_right_wing", "hardpoint_gun_nose")]
        self.assertAlmostEqual(1945, sum(dps(c) for c in guns), delta=1)
        shields = [self.slot("aegs_gladius", s)["default"] for s in ("hardpoint_shield_generator_left", "hardpoint_shield_generator_right")]
        self.assertEqual(6336.0, sum(items[c]["shield"]["hp"] for c in shields))
        self.assertTrue(self.slot("aegs_gladius", "hardpoint_countermeasure_launcher_left")["locked"])

    def test_variant_gets_its_modification(self):
        a = self.data["ships"]["anvl_hornet_f7a_mk2"]
        c = self.data["ships"]["anvl_hornet_f7c_mk2"]
        plants = lambda ship: sum(1 for s in ship["slots"] if s["types"] and s["types"][0][0] == "PowerPlant")
        self.assertEqual((1, 2), (plants(a), plants(c)))
        self.assertEqual(2850.0, c["hull"])

    def test_recipe(self):
        recipe = self.data["recipes"]["shld_godi_s01_fr66_scitem"]
        self.assertEqual(660, recipe["seconds"])
        self.assertEqual(["Shell", "Field Array", "Frequency Controller"], [s["name"] for s in recipe["slots"]])
        self.assertEqual(3168.0, recipe["base"]["GPP_Shield_MaxHealth"])
        self.assertTrue(self.data["items"]["shld_godi_s01_fr66_scitem"]["craftable"])

    def test_candidates_include_unfitted_parts(self):
        self.assertIn("behr_lasercannon_s3", self.data["items"])           # M5A: on no Gladius by default
        self.assertNotIn("klwe_laserrepeater_s3_ai", self.data["items"])


if __name__ == "__main__":
    unittest.main()
