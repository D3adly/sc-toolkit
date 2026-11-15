"""The overlay's horizontal layout, the band (#74): switching, folding,
placement, width and height, and the room for lists dropped from it.

Offscreen Qt on a 2560×1440 screen; overlay.STATE_FILE points into a temp
dir, so nothing touches the real overlay.json or the desktop."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="sct-band-"))
_SCREENS = _TMP / "screens.json"
_SCREENS.write_text(json.dumps({"screens": [{"name": "s1", "x": 0, "y": 0, "width": 2560, "height": 1440,
                                             "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

if QApplication.instance() is None:
    os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={_SCREENS}"
    _APP = QApplication([])
else:
    _APP = QApplication.instance()

from app.theme import build_stylesheet  # noqa: E402
from app.ui import overlay  # noqa: E402

_APP.setStyleSheet(build_stylesheet())
SCREEN = _APP.primaryScreen().geometry()


def _fake_band() -> QWidget:
    """A band body with one list in it (the real ones read the game data and the live log)."""
    from app.ui.overlay_panels import _combo

    w = QWidget()
    lay = QVBoxLayout(w)
    w.jump = _combo(180)
    for tool in overlay.TOOLS:
        w.jump.addItem(tool)
    lay.addWidget(w.jump)
    return w


def settle(seconds: float = 0.05) -> None:
    end = time.time() + seconds
    while time.time() < end:
        _APP.processEvents()
        time.sleep(0.005)


class BandTest(unittest.TestCase):
    def setUp(self):
        self._state_file = overlay.STATE_FILE
        overlay.STATE_FILE = _TMP / f"overlay-{self._testMethodName}.json"
        # The vertical tool panels read the game folder and the live log; these tests are about the chrome.
        self._make_panel = overlay.OverlayWindow._make_panel
        overlay.OverlayWindow._make_panel = lambda _self, _tool: QWidget()
        self._make_band = overlay.OverlayWindow._make_band
        overlay.OverlayWindow._make_band = lambda _self, _tool: _fake_band()
        self.windows = []

    def tearDown(self):
        for w in self.windows:
            w._save_timer.stop()
            w.hide()
            w.deleteLater()
        settle()
        overlay.STATE_FILE = self._state_file
        overlay.OverlayWindow._make_panel = self._make_panel
        overlay.OverlayWindow._make_band = self._make_band

    def make(self, state: dict | None = None) -> overlay.OverlayWindow:
        if state is not None:
            overlay.STATE_FILE.write_text(json.dumps(state))
        ov = overlay.OverlayWindow()
        self.windows.append(ov)
        ov.show()
        settle()
        return ov

    def saved(self, ov) -> dict:
        ov._save_state()
        return json.loads(overlay.STATE_FILE.read_text())

    # -- switching ------------------------------------------------------------------------
    def test_vertical_is_the_default(self):
        ov = self.make({})
        self.assertFalse(ov.horizontal)
        self.assertFalse(ov.band.isVisible())
        self.assertTrue(ov.frame.isVisible())

    def test_toggle_persists_and_restores(self):
        ov = self.make({})
        ov.toggle_layout()
        settle()
        self.assertTrue(ov.horizontal)
        self.assertTrue(ov.band.isVisible())
        self.assertFalse(ov.frame.isVisible())
        self.assertEqual("horizontal", self.saved(ov)["layout"])
        again = self.make()
        self.assertTrue(again.horizontal)
        self.assertTrue(again.band.isVisible())

    def test_switching_keeps_the_open_tool(self):
        ov = self.make({})
        ov.select_tool("salvage")
        ov.set_layout("horizontal")
        settle()
        self.assertEqual("salvage", ov.tool)
        self.assertFalse(ov.band_folded)
        self.assertTrue(ov.band_stack.isVisible())
        ov.select_tool("maps", force=True)
        ov.set_layout("vertical")
        settle()
        self.assertEqual("maps", ov.tool)
        self.assertTrue(ov.stack.isVisible())

    def test_the_width_does_not_follow_the_tool(self):
        ov = self.make({"layout": "horizontal"})
        widths = set()
        for tool in overlay.TOOLS:
            ov.select_tool(tool, force=True)
            settle()
            widths.add(ov.band.width())
        self.assertEqual(1, len(widths))

    def test_vertical_has_one_size_for_every_tool(self):
        ov = self.make({})
        ov.select_tool("mining")
        settle()
        first = ov.size()
        self.assertGreaterEqual(first.height(), int(SCREEN.height() * overlay.PANEL_HEIGHT_SHARE) - 2)
        ov.resize(first.width() + 60, first.height() - 100)       # the user resizes it in one tool
        settle()
        for tool in overlay.TOOLS:
            ov.select_tool(tool, force=True)
            settle()
            self.assertEqual((first.width() + 60, first.height() - 100), (ov.width(), ov.height()), tool)
        ov.collapse()
        settle()
        self.assertEqual(first.width() + 60, ov.width())          # the bar keeps the panel's width
        ov2 = self.make(self.saved(ov))
        ov2.select_tool("session")
        settle()
        self.assertEqual((first.width() + 60, first.height() - 100), (ov2.width(), ov2.height()))

    def test_band_width_is_the_screen_share_before_the_surface_is_sized(self):
        ov = self.make({"layout": "horizontal"})
        self.assertEqual(min(overlay.BAND_WIDTH, int(SCREEN.width() * overlay.BAND_MAX_SHARE)), ov.width())

    def test_switching_does_not_record_band_sizes(self):
        ov = self.make({"layout": "horizontal"})
        ov.set_layout("vertical")
        ov.set_layout("horizontal")
        ov.set_layout("vertical")
        size = self.saved(ov).get("panel_size")       # only the vertical panel's own
        if size:
            self.assertNotEqual(ov.band_h, size[1])

    def test_minimised_vertical_comes_back_minimised(self):
        ov = self.make({"minimized": True})
        self.assertTrue(ov.minimized)
        ov.set_layout("horizontal")
        self.assertFalse(ov.minimized)
        self.assertTrue(ov.band.isVisible())
        ov.set_layout("vertical")
        self.assertTrue(ov.minimized)
        ov.set_minimized(False)                 # expanding brings back the band's tool
        self.assertEqual(ov.state["band_tool"], ov.tool)

    # -- placement and size ------------------------------------------------------------------
    def test_default_is_top_centre(self):
        ov = self.make({"layout": "horizontal"})
        width = min(overlay.BAND_WIDTH, int(SCREEN.width() * overlay.BAND_MAX_SHARE))
        self.assertEqual(width, ov.width())
        self.assertEqual(overlay.BAND_HEIGHTS["normal"], ov.height())
        self.assertEqual((SCREEN.width() - width) // 2, ov.x())
        self.assertEqual(overlay.EDGE, ov.y())

    def test_each_layout_keeps_its_own_position(self):
        ov = self.make({})
        ov.move_to("bl")
        vertical = ov._home                              # the bar's place (an open panel opens upwards)
        ov.set_layout("horizontal")
        settle()
        self.assertEqual(overlay.EDGE, ov.y())          # the band's own default, not the bar's place
        ov.move_to("bc")
        band = ov.pos()
        self.assertEqual(SCREEN.height() - overlay.EDGE - ov.height(), band.y())
        ov.set_layout("vertical")
        settle()
        self.assertEqual(vertical, ov._home)
        ov.set_layout("horizontal")
        settle()
        self.assertEqual(band, ov.pos())
        self.assertEqual("bottom", self.saved(ov)["band_edge"])

    def test_the_band_is_always_centred(self):
        ov = self.make({"layout": "horizontal", "positions": {"0,0,2560x1440|h": [100, 600]}, "pos_h": [100, 600]})
        self.assertEqual((SCREEN.width() - ov.width()) // 2, ov.x())     # old saved spots don't count
        self.assertEqual(overlay.EDGE, ov.y())
        ov.move_to("tl")                                                  # (not offered, but still centred)
        self.assertEqual((SCREEN.width() - ov.width()) // 2, ov.x())
        ov.set_folded(True)
        self.assertEqual((SCREEN.width() - ov.width()) // 2, ov.x())
        ov.move_to("bc")
        ov.set_folded(False)                                              # at the bottom it stays on the edge
        self.assertEqual(SCREEN.height() - overlay.EDGE, ov.y() + ov.height())
        ov.reset_position()
        self.assertEqual(overlay.EDGE, ov.y())

    def test_height_presets(self):
        ov = self.make({"layout": "horizontal"})
        for preset, height in overlay.BAND_HEIGHTS.items():
            ov.set_band_height(preset)
            self.assertEqual(height, ov.height(), preset)
        self.assertEqual("tall", self.saved(ov)["band_height"])
        self.assertEqual("tall", self.make().band_height)

    def test_edge_resize_keeps_it_centred(self):
        ov = self.make({"layout": "horizontal"})
        ov.resize_band(1000)
        self.assertEqual(1000, ov.width())
        self.assertEqual((SCREEN.width() - 1000) // 2, ov.x())
        ov.band_resized()
        self.assertEqual(1000, self.saved(ov)["band_width"])
        self.assertEqual(1000, self.make().width())

    def test_width_has_a_minimum(self):
        ov = self.make({"layout": "horizontal"})
        ov.resize_band(200)
        self.assertEqual(overlay.BAND_MIN_WIDTH, ov.width())

    # -- fold, keys ---------------------------------------------------------------------
    def test_fold_and_unfold(self):
        ov = self.make({"layout": "horizontal"})
        tool = ov.tool
        ov.select_tool(tool)                    # the open tab again: fold
        self.assertTrue(ov.band_folded)
        self.assertEqual(overlay.BAND_HEADER + 2, ov.height())
        self.assertFalse(ov.band_stack.isVisible())
        ov.select_tool(tool)                    # and again: open
        self.assertFalse(ov.band_folded)
        self.assertEqual(overlay.BAND_HEIGHTS["normal"], ov.height())
        ov.set_folded(True)
        ov.select_tool("mining", force=True)    # a key: always opens
        self.assertFalse(ov.band_folded)
        self.assertEqual("mining", ov.tool)
        ov.select_tool("mining", force=True)    # the open one's key: stays open
        self.assertFalse(ov.band_folded)

    def test_fold_persists(self):
        ov = self.make({"layout": "horizontal"})
        ov.set_folded(True)
        self.assertTrue(self.saved(ov)["band_folded"])
        self.assertTrue(self.make().band_folded)

    def test_minimise_and_collapse_fold_the_band(self):
        ov = self.make({"layout": "horizontal"})
        ov.set_minimized(True)
        self.assertTrue(ov.band_folded)
        self.assertFalse(ov.minimized)
        ov.set_minimized(False)
        self.assertFalse(ov.band_folded)
        ov.collapse()
        self.assertTrue(ov.band_folded)

    def test_escape_order(self):
        ov = self.make({"layout": "horizontal"})
        combo = ov._band_panels[ov.tool].jump
        ov._show_menu(True)
        self.assertTrue(ov.menu.isVisible())
        ov._escape()
        self.assertFalse(ov.menu.isVisible())
        combo.showPopup()
        self.assertTrue(combo._list.isVisible())
        ov._escape()                            # a drop first
        self.assertFalse(combo._list.isVisible())
        ov._escape()                            # then fold
        self.assertTrue(ov.band_folded)

    # -- the drop room ------------------------------------------------------------------
    def test_a_list_gets_room_below_and_gives_it_back(self):
        ov = self.make({"layout": "horizontal"})
        band = ov.height()
        combo = ov._band_panels[ov.tool].jump
        combo.showPopup()
        lst = combo._list
        self.assertGreater(ov.height(), band)
        self.assertEqual(band, ov.band.height())                 # the band itself never grows
        self.assertEqual(0, ov.band.y())
        rows = combo.count() * lst.sizeHintForRow(0)
        self.assertGreaterEqual(lst.height(), rows)              # every entry shows
        self.assertLessEqual(lst.geometry().bottom(), ov.height())
        combo.hidePopup()
        self.assertEqual(band, ov.height())
        self.assertEqual(0, ov._room)

    def test_a_drop_opens_below_the_band_and_a_click_elsewhere_closes_it(self):
        ov = self.make({"layout": "horizontal"})
        anchor = ov._band_panels[ov.tool].jump
        drop = QWidget()
        ov.show_drop(drop, 200, anchor=anchor, width=300)
        self.assertTrue(drop.isVisible())
        self.assertGreaterEqual(drop.y(), ov.band_h)
        self.assertEqual(ov.band_h, ov.band.height())
        ov._drop_click(ov.band_header)            # a click on the band
        settle()
        self.assertFalse(drop.isVisible())
        self.assertEqual(ov.band_h, ov.height())

    def test_a_sticky_drop_stays_until_esc(self):
        ov = self.make({"layout": "horizontal"})
        drawer = QWidget()
        ov.show_drop(drawer, 500, width=ov.width(), sticky=True)
        ov._drop_click(ov.band_header)
        settle()
        self.assertTrue(drawer.isVisible())
        ov._escape()
        self.assertFalse(drawer.isVisible())

    def test_a_low_band_drops_upwards(self):
        ov = self.make({"layout": "horizontal"})
        ov.move_to("bc")
        bottom = ov.y() + ov.height()
        combo = ov._band_panels[ov.tool].jump
        combo.showPopup()
        self.assertEqual(bottom, ov.y() + ov.height())           # the band stays put; room opens above
        self.assertGreater(ov.band.y(), 0)
        self.assertLess(combo._list.geometry().top(), ov.band.y() + combo.mapTo(ov.band, combo.rect().topLeft()).y())
        combo.hidePopup()
        self.assertEqual(0, ov.band.y())
        self.assertEqual(bottom, ov.y() + ov.height())

    def test_one_drop_at_a_time(self):
        ov = self.make({"layout": "horizontal"})
        combo = ov._band_panels[ov.tool].jump
        combo.showPopup()
        ov._show_menu(True)                                     # the menu closes the list
        self.assertFalse(combo._list.isVisible())
        self.assertTrue(ov.menu.isVisible())
        self.assertGreaterEqual(ov.height(), ov.band_h + ov.menu.height())
        combo.showPopup()                                       # and the list the menu
        self.assertFalse(ov.menu.isVisible())
        self.assertTrue(combo._list.isVisible())
        combo.hidePopup()
        self.assertEqual(ov.band_h, ov.height())

    def test_folding_closes_drops(self):
        ov = self.make({"layout": "horizontal"})
        combo = ov._band_panels[ov.tool].jump
        combo.showPopup()
        ov.set_folded(True)
        self.assertFalse(combo._list.isVisible())
        self.assertEqual(ov.band_h, ov.height())

    def test_vertical_lists_are_unchanged(self):
        """Outside the band, a list still fits inside the window (no room asked)."""
        ov = self.make({})
        size = ov.size()
        self.assertEqual(0, ov.drop_room(500).height())
        self.assertEqual(size, ov.size())


class ColumnsTest(unittest.TestCase):
    def test_low_priority_columns_hide_when_narrow(self):
        from app.ui.overlay_band import BandColumn, BandColumns

        cols = [BandColumn("A", 2, 1, 200), BandColumn("B", 3, 1, 200), BandColumn("C", 2, 2, 200),
                BandColumn("D", 2, 3, 200)]
        box = BandColumns(cols)
        box.resize(1200, 120)
        box.show()
        settle()
        self.assertEqual([True] * 4, [c.isVisible() for c in cols])
        box.resize(700, 120)
        settle()
        self.assertEqual([True, True, True, False], [c.isVisible() for c in cols])
        box.resize(450, 120)
        settle()
        self.assertEqual([True, True, False, False], [c.isVisible() for c in cols])
        self.assertTrue(cols[0].property("first"))
        box.hide()

    def test_columns_fit_their_lines_and_never_scroll(self):
        from app.ui.overlay_band import BandColumn

        col = BandColumn("A")
        col.show()
        counts = {}
        for preset, height in overlay.BAND_HEIGHTS.items():
            col.resize(300, height - overlay.BAND_HEADER - 2)
            settle()
            counts[preset] = col.rows()
        self.assertGreaterEqual(counts["compact"], 2)
        self.assertGreaterEqual(counts["normal"], 4)
        self.assertGreater(counts["tall"], counts["normal"])
        self.assertFalse(col.findChildren(__import__("PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea))
        col.hide()

    def test_a_list_shows_all_it_can_and_more_only_when_cut(self):
        """Every row is reachable: "+n more" (on the title line) shows exactly when rows don't fit."""
        from app.ui.overlay_band import BandColumn, Line, _row, fill

        col = BandColumn("A")
        col.resize(300, overlay.BAND_HEIGHTS["normal"] - overlay.BAND_HEADER - 2)
        col.show()
        settle()
        fit = col.rows()

        def texts():
            return [l._full for l in col.findChildren(Line) if l.isVisibleTo(col)]

        for n in (fit - 1, fit):
            fill(col, [(lambda i=i: _row((f"row {i}", "BandLine"))) for i in range(n)], "A")
            settle()
            self.assertEqual([f"row {i}" for i in range(n)], texts())
            self.assertFalse(col.more.isVisibleTo(col))
        fill(col, [(lambda i=i: _row((f"row {i}", "BandLine"))) for i in range(fit + 3)], "A")
        settle()
        self.assertEqual([f"row {i}" for i in range(fit)], texts())     # the list keeps all its lines
        self.assertTrue(col.more.isVisibleTo(col))
        self.assertEqual("+3 more ▾", col._more_text.text())
        col.hide()

if __name__ == "__main__":
    unittest.main()
