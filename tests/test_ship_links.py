"""Ships the game files released ahead of the ship list (4.10.3: Galaxy, Liberator)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import ships


def _ship(key, name, manufacturer, status=ships.FLIGHT_READY, class_id=""):
    return ships.Ship(key=key, name=name, manufacturer=manufacturer, role="Multi-role", focus="", size="Large",
                      status=status, store=True, class_id=class_id)


def _catalogue():
    return ships.Catalogue([
        _ship("sm:1", "Constellation Andromeda", "Roberts Space Industries", class_id="rsi_constellation_andromeda"),
        _ship("sm:244", "Galaxy", "Roberts Space Industries", ships.IN_CONCEPT),
        _ship("sm:256", "Zeus Mk II MR", "Roberts Space Industries", ships.IN_CONCEPT),
        _ship("sm:63", "Javelin", "Aegis Dynamics", ships.IN_CONCEPT, "aegs_javelin"),
        _ship("sm:2", "Gladius", "Aegis Dynamics", class_id="aegs_gladius"),
    ])


VEHICLES = {
    "rsi_galaxy": {"name": "RSI Galaxy", "painted": True},
    "rsi_galaxy_temp_cargo": {"name": "RSI Galaxy", "painted": False},
    "rsi_zeus_cl": {"name": "RSI Zeus Mk II CL", "painted": False},
    "aegs_javelin": {"name": "Aegis Javelin", "painted": False},
}


class LinkGame(unittest.TestCase):
    def test_released_ship_gets_its_base_entity_and_goes_flight_ready(self):
        catalogue = _catalogue()
        changed = ships.link_game(catalogue, VEHICLES)
        self.assertEqual({"sm:244": {"class_id": "rsi_galaxy", "status": ships.FLIGHT_READY}}, changed)
        self.assertFalse(catalogue.get("sm:244").concept)

    def test_no_name_match_and_unpainted_npc_ships_stay_in_concept(self):
        catalogue = _catalogue()
        ships.link_game(catalogue, VEHICLES)
        self.assertEqual(("", ships.IN_CONCEPT), (catalogue.get("sm:256").class_id, catalogue.get("sm:256").status))
        self.assertTrue(catalogue.get("sm:63").concept)

    def test_linked_concept_ship_with_paints_goes_flight_ready(self):
        catalogue = _catalogue()
        ships.link_game(catalogue, {**VEHICLES, "aegs_javelin": {"name": "Aegis Javelin", "painted": True}})
        self.assertFalse(catalogue.get("sm:63").concept)


class SavedLinks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(ships, "LINKS_FILE", Path(tmp.name) / "game_links.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _load(self, catalogue):
        with mock.patch.object(ships, "_read", lambda _path: catalogue):
            return ships.load()

    def test_live_links_apply_on_load(self):
        ships.save_links("LIVE", ships.link_game(_catalogue(), VEHICLES))
        galaxy = self._load(_catalogue()).get("sm:244")
        self.assertEqual(("rsi_galaxy", ships.FLIGHT_READY), (galaxy.class_id, galaxy.status))

    def test_other_channels_dont(self):
        ships.save_links("PTU", ships.link_game(_catalogue(), VEHICLES))
        self.assertTrue(self._load(_catalogue()).get("sm:244").concept)

    def test_the_ship_list_wins_once_it_knows_the_class(self):
        ships.save_links("LIVE", {"sm:244": {"class_id": "rsi_galaxy", "status": ships.FLIGHT_READY}})
        catalogue = _catalogue()
        catalogue.get("sm:244").class_id = "rsi_galaxy_new"
        galaxy = self._load(catalogue).get("sm:244")
        self.assertEqual(("rsi_galaxy_new", ships.IN_CONCEPT), (galaxy.class_id, galaxy.status))

    def test_no_links_file(self):
        self.assertTrue(self._load(_catalogue()).get("sm:244").concept)


if __name__ == "__main__":
    unittest.main()
