"""app.uexparts with a fake UEX (no network)."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import uexparts

TERMINALS = {"status": "ok", "data": [
    {"id": 1, "type": "item", "name": "Platinum Bay - HUR-L5", "star_system_name": "Stanton", "planet_name": "Hurston",
     "space_station_name": "HUR-L5 High Course Station"},
    {"id": 2, "type": "item", "name": "Ship Weapons - HUR-L5", "star_system_name": "Stanton", "planet_name": "Hurston",
     "space_station_name": "HUR-L5 High Course Station"},
    {"id": 3, "type": "commodity", "name": "Admin - ARC-L1"},
]}
NOW = time.time()
PRICES = {"status": "ok", "data": [
    {"id_terminal": 2, "item_uuid": "m5a", "price_buy": 75145, "date_modified": NOW - 41 * 86400},
    {"id_terminal": 1, "item_uuid": "m5a", "price_buy": 78000, "date_modified": NOW - 3 * 86400},
    {"id_terminal": 1, "item_uuid": "atlas", "price_buy": 84000, "date_modified": NOW - 60 * 86400},
    {"id_terminal": 3, "item_uuid": "ice", "price_buy": 5, "date_modified": NOW},
    {"id_terminal": 1, "item_uuid": "sold-only", "price_buy": 0, "price_sell": 10, "date_modified": NOW},
]}


def fake_get(url: str) -> bytes:
    return json.dumps(TERMINALS if url.endswith("terminals") else PRICES).encode()


class UexPartsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cache = Path(self.dir.name) / "uexparts.json"
        patcher = mock.patch.object(uexparts, "CACHE", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.dir.cleanup)

    def test_refresh_and_offers(self):
        with mock.patch.object(uexparts, "_http_get", fake_get):
            uexparts.refresh()
        prices = uexparts.load(self.cache)
        offers = prices.offers("m5a")
        self.assertEqual([75145, 78000], [o.price for o in offers], "cheapest first")
        self.assertEqual(("Ship Weapons", "HUR-L5 High Course Station", "Stanton", "Hurston"),
                         (offers[0].shop, offers[0].place, offers[0].system, offers[0].planet))
        self.assertEqual(["ageing", "fresh"], [o.freshness(NOW) for o in offers])
        self.assertEqual("stale", prices.cheapest("atlas").freshness(NOW))
        self.assertEqual([], prices.offers("ice"), "commodity terminals aren't part shops")
        self.assertEqual([], prices.offers("sold-only"), "only buy prices count")

    def test_failed_fetch_keeps_the_cache(self):
        with mock.patch.object(uexparts, "_http_get", fake_get):
            uexparts.refresh()
        before = self.cache.read_text()
        with mock.patch.object(uexparts, "_http_get", side_effect=OSError("offline")):
            with self.assertRaises(uexparts.UexError):
                uexparts.refresh()
        self.assertEqual(before, self.cache.read_text())

    def test_no_cache(self):
        self.assertIsNone(uexparts.load(Path(self.dir.name) / "missing.json"))


if __name__ == "__main__":
    unittest.main()
