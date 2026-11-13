"""4.10.3: ships whose game entity was replaced or folded into a paint, the version label the
manifest no longer carries, and the wiki's placeholder pictures."""

import json
import tempfile
import unittest
from pathlib import Path

from app import contracts, shipdata
from app.loadoutdata import LoadoutData
from app.ships import _image

KNOWN = {"aegs_hammerhead_gs": {"n": 1}, "rsi_constellation_andromeda_gs": {"n": 2},
         "rsi_constellation_phoenix": {"n": 3}, "rsi_constellation_taurus": {"n": 4}}


class GameClass(unittest.TestCase):
    def test_exact_class_wins(self):
        self.assertEqual(shipdata.game_class("RSI_Constellation_Taurus", KNOWN), "rsi_constellation_taurus")

    def test_gold_standard_replacement(self):
        self.assertEqual(shipdata.game_class("aegs_hammerhead", KNOWN), "aegs_hammerhead_gs")
        self.assertEqual(shipdata.game_class("rsi_constellation_andromeda", KNOWN), "rsi_constellation_andromeda_gs")

    def test_edition_turned_paint(self):
        self.assertEqual(shipdata.game_class("aegs_hammerhead_showdown", KNOWN), "aegs_hammerhead_gs")
        self.assertEqual(shipdata.game_class("rsi_constellation_phoenix_emerald", KNOWN), "rsi_constellation_phoenix")

    def test_never_below_manufacturer_model(self):
        self.assertEqual(shipdata.game_class("rsi_zeus_cl", KNOWN), "rsi_zeus_cl")
        self.assertEqual(shipdata.game_class("", KNOWN), "")

    def test_lookups_use_it(self):
        self.assertEqual(shipdata.ShipData({"ships": KNOWN}).get("aegs_hammerhead"), {"n": 1})
        self.assertEqual(LoadoutData({"ships": KNOWN}).ship("AEGS_Hammerhead_Showdown"), {"n": 1})
        self.assertIsNone(shipdata.ShipData({"ships": KNOWN}).get("rsi_zeus_cl"))


class Placeholder(unittest.TestCase):
    def test_placeholder_is_no_image(self):
        ph = "https://cdn.star-citizen.wiki/images/thumb/7/7f/Platzhalter.webp/600px-Platzhalter.webp.png"
        self.assertEqual(_image({"images": [{"thumbnail_url": ph}]}), "")
        self.assertEqual(_image({"images": [{"thumbnail_url": ph}, {"original_url": "https://x/real.jpg"}]}),
                         "https://x/real.jpg")


LOG = (
    '{ "t":"2026-10-23 23:42:52.579", "[main][info] ": "[PatcherPhase] Delta update completed (SC LIVE 4.10.2-live.12913470) in C:\\\\x"  },\n'
    '{ "t":"2026-11-12 23:27:16.550", "[main][info] ": "[PatcherPhase] Delta update completed (SC LIVE 4.10.3-live.13165946) in C:\\\\x"  },\n'
    '{ "t":"2026-11-12 23:30:00.000", "[main][info] ": "[Pipeline] Verifying Star Citizen PTU 4.11.0-ptu.13200000 at C:\\\\x"  },\n'
)


class GameVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name) / "LIVE"
        self.live.mkdir()
        self.log = Path(self.tmp.name) / "log.log"
        self.log.write_text(LOG)

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, branch, build):
        (self.live / "build_manifest.id").write_text(json.dumps(
            {"Data": {"Branch": branch, "RequestedP4ChangeNum": build}}))

    def test_launcher_log_names_the_patch(self):
        self.manifest("sc-alpha-4.10.0", "13165946")
        self.assertEqual(contracts.game_version(self.live, self.log), "4.10.3 LIVE")

    def test_falls_back_to_branch(self):
        self.manifest("sc-alpha-4.10.2", "12881860")
        self.assertEqual(contracts.game_version(self.live, self.log), "4.10.2 LIVE")

    def test_channel_must_match(self):
        self.assertEqual(contracts.launcher_release(self.log, "LIVE", "13200000"), "")
        self.assertEqual(contracts.launcher_release(self.log, "PTU", "13200000"), "4.11.0")

    def test_no_manifest(self):
        self.assertEqual(contracts.game_version(self.live, self.log), "")


if __name__ == "__main__":
    unittest.main()
