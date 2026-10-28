import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import hangar, loadouts, sync


class LoadoutStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(loadouts.config, "DATA_DIR", root),
                        mock.patch.object(loadouts, "LOADOUTS_FILE", root / "loadouts.json")]
        for p in self.patches:
            p.start()
        hangar.set_active("acc1")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        hangar.set_active(None)
        self.tmp.cleanup()

    def test_save_stamps_only_changes(self):
        lo = loadouts.save(loadouts.Loadout(hangar_id="h1", ship="sm:60", name="Brawler"))
        self.assertGreater(lo.updated_at, 0)
        again = loadouts.save(lo)
        self.assertEqual(again.updated_at, lo.updated_at)
        lo.ticks = ["buy:x"]
        changed = loadouts.save(lo)
        self.assertGreater(changed.updated_at, lo.updated_at)
        self.assertEqual([x.name for x in loadouts.for_ship("h1")], ["Brawler"])

    def test_remove_and_cascade_leave_tombstones(self):
        a = loadouts.save(loadouts.Loadout(hangar_id="h1", ship="sm:60", name="A"))
        loadouts.save(loadouts.Loadout(hangar_id="h2", ship="sm:56", name="B"))
        loadouts.remove(a.id)
        loadouts.cascade({"h2"})
        store = loadouts.read("acc1")
        self.assertEqual(store.live(), [])
        self.assertEqual(len(store.loadouts), 2)
        self.assertTrue(all(lo.deleted for lo in store.loadouts))

    def test_signed_out_removal_needs_no_tombstone(self):
        hangar.set_active(None)
        a = loadouts.save(loadouts.Loadout(hangar_id="h1", ship="sm:60", name="A"))
        loadouts.remove(a.id)
        self.assertEqual(loadouts.read(None).loadouts, [])

    def test_limit_per_ship(self):
        for i in range(loadouts.MAX_PER_SHIP):
            loadouts.save(loadouts.Loadout(hangar_id="h1", ship="sm:60", name=f"L{i}"))
        with self.assertRaises(loadouts.LimitReached):
            loadouts.check_room("h1")
        loadouts.check_room("h2")


class LoadoutSyncPartsTest(unittest.TestCase):
    def remote(self, **kw):
        base = {"id": "l1", "hangarId": "h1", "ship": "sm:60", "name": "Online", "parts": {}, "ticks": [],
                "basket": None, "updatedAt": "2026-10-28T10:00:00.000+00:00", "deleted": False, "share": None}
        return {**base, **kw}

    def test_round_trip(self):
        lo = loadouts.Loadout(hangar_id="h1", ship="sm:60", name="X",
                              parts={"hardpoint_shield_left": {"item": "shld_x", "source": "craft",
                                                                "qualities": [800, None]}},
                              ticks=["buy:shld_x"], basket={"savedAt": "2026-10-28T10:00:00+00:00", "route": "stops",
                                                            "stops": [], "unsold": [], "craft": []},
                              updated_at=1_761_645_600_000)
        back = sync.loadout_from_remote(sync.loadout_to_input(lo))
        self.assertEqual(back.content(), lo.content())
        self.assertEqual(back.updated_at, lo.updated_at)

    def test_newer_local_edit_wins_but_share_comes_from_online(self):
        store = loadouts.Store(Path("x"), [loadouts.Loadout(hangar_id="h1", ship="sm:60", name="Local", id="l1",
                                                            updated_at=1_861_645_600_000)])
        share = {"token": "t" * 22, "url": "https://x/l/t", "sharedAt": "2026-10-28T10:00:00+00:00"}
        sync.apply_remote_loadouts(store, [self.remote(share=share)])
        self.assertEqual(store.loadouts[0].name, "Local")
        self.assertEqual(store.loadouts[0].share, share)

    def test_remote_edit_and_deletion(self):
        store = loadouts.Store(Path("x"), [loadouts.Loadout(hangar_id="h1", ship="sm:60", name="Old", id="l1",
                                                            updated_at=1)])
        sync.apply_remote_loadouts(store, [self.remote(), self.remote(id="l2", name="New")])
        self.assertEqual([lo.name for lo in store.loadouts], ["Online", "New"])
        sync.apply_remote_loadouts(store, [self.remote(deleted=True, updatedAt="2026-10-28T11:00:00+00:00")])
        self.assertEqual([lo.id for lo in store.loadouts], ["l2"])


if __name__ == "__main__":
    unittest.main()
