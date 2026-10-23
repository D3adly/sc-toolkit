"""app.p4k on a real install (skipped without one): set SCT_GAME to the channel folder (…/StarCitizen/LIVE)."""

import os
import unittest
from pathlib import Path

from app import cryxml, p4k

GAME = Path(os.environ.get("SCT_GAME", "")) if os.environ.get("SCT_GAME") else None
VEHICLE = "Data\\Scripts\\Entities\\Vehicles\\Implementations\\Xml\\AEGS_Gladius.xml"


@unittest.skipUnless(GAME and (GAME / "Data.p4k").is_file(), "needs SCT_GAME pointing at a game channel folder")
class EncryptedEntryTest(unittest.TestCase):
    def test_vehicle_definition_decrypts(self):
        data = p4k.extract(GAME / "Data.p4k", [VEHICLE])[VEHICLE]
        root = cryxml.parse(data)
        self.assertEqual("AEGS_Gladius", root.get("name"))
        nose = next(p for p in root.iter("Part") if p.get("name") == "hardpoint_gun_nose").find("ItemPort")
        self.assertEqual(("3", "3"), (nose.get("minSize"), nose.get("maxSize")))
        self.assertIn("WeaponGun", [t.get("type") for t in nose.iter("Type")])

    def test_plain_entries_still_read(self):
        name = "Data\\Libs\\Config\\defaultProfile.xml"
        self.assertTrue(p4k.extract(GAME / "Data.p4k", [name])[name])


if __name__ == "__main__":
    unittest.main()
