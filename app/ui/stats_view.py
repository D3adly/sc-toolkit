"""My Stats: the player's statistics from every Game.log on disk (app.stats):
all time, the last 30 or 7 days, or the last play session. Headline figures
first, then a card per topic. Read on opening and on Refresh; nothing is
stored.
"""

from __future__ import annotations

import re
import threading
import traceback

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, config, datahub, settings, stats
from app.theme import PALETTE
from app.ui import kit

TILE_COLUMNS = 4
COLUMN_MIN_WIDTH = 260   # a column of a multi-column list
COLUMN_MIN_ROWS = 4      # don't spread a short list into one-row columns
GLYPHS = config.ASSETS_DIR / "icons" / "glyphs"


def _label(text: str, name: str, tip: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text, objectName=name)
    lbl.setWordWrap(wrap)
    if tip:
        lbl.setToolTip(tip)
    return lbl


class _Loader(QObject):
    loaded = Signal(object)
    progress = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.without_contracts = False      # the last load had no mission database

    def run(self) -> None:
        def work():
            try:
                root = settings.current().game_root
                ch = channel_mod.pick_default_channel(root)
                lookup = None
                if ch:
                    # Mission details are a bonus: stats work without them. The
                    # database is built by app.datahub (once per patch); if it
                    # isn't there yet, ask for it and reload when it is.
                    channel_root = channel_mod.resolve_channel_paths(root, ch).channel_root
                    try:
                        lookup = datahub.read_game("contracts", channel_root)
                    except Exception:
                        traceback.print_exc()
                    if lookup is None:
                        datahub.hub().ensure_game(["contracts"], channel_root)
                self.without_contracts = lookup is None
                self.progress.emit("Reading your game logs…")
                self.loaded.emit(stats.load(
                    root, lookup,
                    progress=lambda done, total: self.progress.emit(f"Reading your game logs… {done}/{total}")))
            except Exception as exc:
                traceback.print_exc()
                self.failed.emit(str(exc))
        threading.Thread(target=work, daemon=True).start()


def _glyph_icon(name: str) -> QIcon:
    """A white glyph PNG, tinted muted (off) and bright (selected)."""
    icon = QIcon()
    source = QPixmap(str(GLYPHS / f"{name}.png"))
    if source.isNull():
        return icon
    for colour, state in ((PALETTE["text_muted"], QIcon.Off), (PALETTE["text_primary"], QIcon.On)):
        pix = QPixmap(source.size())
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.drawPixmap(0, 0, source)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(pix.rect(), QColor(colour))
        p.end()
        icon.addPixmap(pix, QIcon.Normal, state)
    return icon


class _RowList(QWidget):
    """Name / value rows. Shows `limit` rows and a "…and n more" button that
    expands the list in place; with `columns`, the rows flow into as many
    columns as the width allows (top to bottom, then across)."""

    def __init__(self, rows: list, limit: int | None, columns: bool, parent=None):
        super().__init__(parent)
        self._limit = limit if limit and len(rows) > limit else None
        self._columns = columns
        self._expanded = False
        self._ncols = 0
        self._cells = []
        for name, value in rows:
            left = _label(name, "RankName", name)
            left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            right = _label(value, "RankValue")
            right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._cells.append((left, right))
        self._v = v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self._grid_box = None   # rebuilt on each layout: a grid keeps its old rows/columns
        self._more = None
        if self._limit:
            self._more = QPushButton(objectName="MoreButton")
            self._more.setCursor(Qt.PointingHandCursor)
            self._more.clicked.connect(self._toggle)
            v.addWidget(self._more, alignment=Qt.AlignLeft)
        self._layout_rows(self._wanted_columns(self.width()))

    def _shown(self) -> int:
        return len(self._cells) if self._expanded or not self._limit else self._limit

    def _wanted_columns(self, width: int) -> int:
        if not self._columns:
            return 1
        return max(1, min(width // COLUMN_MIN_WIDTH, -(-self._shown() // COLUMN_MIN_ROWS)))

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._layout_rows(self._wanted_columns(self.width()))

    def _layout_rows(self, ncols: int) -> None:
        self._ncols = ncols
        shown = self._shown()
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        per_col = max(1, -(-shown // ncols))
        for i, (left, right) in enumerate(self._cells):
            visible = i < shown
            if visible:
                r, c = i % per_col, i // per_col
                grid.addWidget(left, r, c * 3)
                grid.addWidget(right, r, c * 3 + 1)
            else:
                left.setParent(box)
            left.setVisible(visible)
            right.setVisible(visible)
        for c in range(ncols):
            grid.setColumnStretch(c * 3, 1)
            if c:
                grid.setColumnMinimumWidth(c * 3 - 1, 14)   # gap between columns
        for _left, right in self._cells[shown:]:
            right.setParent(box)
        if self._grid_box is not None:
            self._grid_box.deleteLater()
        self._grid_box = box
        self._v.insertWidget(0, box)
        if self._more is not None:
            self._more.setText("Show less" if self._expanded
                               else f"…and {len(self._cells) - self._limit} more")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wanted = self._wanted_columns(event.size().width())
        if wanted != self._ncols:
            self._layout_rows(wanted)


_NUM_RE = re.compile(r"^(?:(\d+)h)?\s*(?:(\d+)m)?$")


def _number(value: str) -> float | None:
    """A row value as a number for its bar: '1,204' → 1204, '11h 48m' → 708
    (minutes); None if it isn't a plain count or duration."""
    text = value.strip()
    plain = text.replace(",", "")
    if plain.isdigit():
        return float(plain)
    m = _NUM_RE.match(text)
    if m and (m.group(1) or m.group(2)):
        return float(int(m.group(1) or 0) * 60 + int(m.group(2) or 0))
    return None


class _SectionCard(kit.Section):
    """One stats section: its figures, then its lists (bars where the values
    are counts), the blueprint section with its type filter."""

    def __init__(self, section: dict, parent=None):
        super().__init__(section["title"], parent)
        if section.get("notice"):
            note = kit.label(section["notice"], "MutedText", wrap=True)
            self.add(note)

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(14)
        tiles.setVerticalSpacing(10)
        for i, (name, value, hint) in enumerate(section["tiles"]):
            tiles.addWidget(kit.Stat(value, name, tip=hint, size="md"), i // TILE_COLUMNS, i % TILE_COLUMNS)
        for c in range(TILE_COLUMNS):
            tiles.setColumnStretch(c, 1)
        self.v.addLayout(tiles)

        lists = [lst for lst in section.get("lists", []) if lst["rows"]]
        if section.get("filter") and lists:
            self._add_filtered(lists)
        else:
            for lst in lists:
                self.add(self._list_block(lst))
        if section.get("note"):
            self.add(kit.label(section["note"], "MutedText", wrap=True))

    @staticmethod
    def _list_block(lst: dict, count: bool = False) -> QWidget:
        block = QWidget()
        col = QVBoxLayout(block)
        col.setContentsMargins(0, 2, 0, 0)
        col.setSpacing(6)
        title = lst["title"] + (f"  ·  {len(lst['rows'])}" if count else "")
        col.addWidget(kit.caps(title))
        numbers = [_number(v) for _n, v in lst["rows"]]
        if lst.get("columns") or any(n is None for n in numbers):
            col.addWidget(_RowList(lst["rows"], lst.get("limit"), bool(lst.get("columns"))))
        else:
            col.addWidget(kit.RankList([(n, num, v) for (n, v), num in zip(lst["rows"], numbers)],
                                       limit=min(5, lst.get("limit") or 5)))
        return block

    def _add_filtered(self, lists: list[dict]) -> None:
        """A glyph button per list (plus All); shows the chosen list, or all."""
        bar = QHBoxLayout()
        bar.setSpacing(6)
        group = QButtonGroup(self)
        blocks = [(lst["key"], self._list_block(lst, count=True)) for lst in lists]

        def show(key: str) -> None:
            for k, block in blocks:
                block.setVisible(key == "all" or k == key)

        total = sum(len(lst["rows"]) for lst in lists)
        for key, title, count in [("all", "All types", total)] + [
                (lst["key"], lst["title"], len(lst["rows"])) for lst in lists]:
            btn = QPushButton(str(count), objectName="GlyphFilter")
            btn.setIcon(_glyph_icon(key))
            btn.setIconSize(QSize(18, 18))
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"{title}: {count}")
            btn.clicked.connect(lambda _c=False, k=key: show(k))
            group.addButton(btn)
            bar.addWidget(btn)
        bar.addStretch(1)
        self.v.addLayout(bar)
        for _key, block in blocks:
            self.add(block)


PERIODS = [("all", "All time"), ("30d", "Last 30 days"), ("7d", "Last 7 days"), ("last", "Last session")]


def _tile(sections: list[dict], section: str, name: str) -> tuple[str, str]:
    for sec in sections:
        if sec["title"] == section:
            for n, value, hint in sec["tiles"]:
                if n == name:
                    return value, hint
    return "—", ""


class StatsView(kit.ToolPage):
    def __init__(self, parent=None):
        super().__init__("stats", "My Stats", "Your play time, missions, blueprints, travel and losses, "
                         "from the game's own logs", parent=parent)
        self.data: dict | None = None
        self.scope = "all"
        self._loading = False
        self._columns = 2
        self._loader = _Loader(self)
        datahub.hub().updated.connect(self._on_hub_updated)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.progress.connect(self.show_message)
        self._loader.failed.connect(lambda msg: self._on_failed(msg))
        self._build_ui()

    def _build_ui(self) -> None:
        self.periods = kit.Segmented(PERIODS, self.scope)
        self.periods.changed.connect(self._set_scope)
        self.filters.add(self.periods, "Period")
        self.refresh_btn = kit.button("Refresh", tip="Read your game logs again")
        self.refresh_btn.clicked.connect(self._load)
        self.filters.add_right(self.refresh_btn)
        self.scroll = kit.scroll_area()
        self.set_content(self.scroll)
        self.result.hide()

    # -- lifecycle ------------------------------------------------------------------
    def activate(self) -> None:
        if self.data is None and not self._loading:
            self._load()

    def _load(self) -> None:
        self._loading = True
        self.refresh_btn.setEnabled(False)
        self.show_message("Reading your game logs…")
        self._loader.run()

    def _on_hub_updated(self, name: str) -> None:
        if name == "contracts" and self.data is not None and self._loader.without_contracts and not self._loading:
            self._load()

    def _on_loaded(self, data: dict) -> None:
        self._loading = False
        self.refresh_btn.setEnabled(True)
        self.data = data
        self._render()

    def _on_failed(self, message: str) -> None:
        self._loading = False
        self.refresh_btn.setEnabled(True)
        self.show_empty("Couldn't read your game logs", message.splitlines()[0] if message else "",
                        "Try again", self._load)

    def _set_scope(self, scope: str | None) -> None:
        if scope is None:
            self.periods.set_value(self.scope)
            return
        self.scope = scope
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wanted = 2 if self.width() >= 960 else 1
        if wanted != self._columns:
            self._columns = wanted
            self._render()

    # -- rendering ----------------------------------------------------------------------
    def _render(self) -> None:
        if self.data is None:
            return
        data = self.data
        if not data["sessions"]:
            self.set_data_chip("")
            self.show_empty("No game logs found",
                            "Check the game folder in Settings. The logs are Game.log and the logbackups "
                            "folder next to it.", "Open Settings", lambda: self.window().show_tool("settings"))
            return
        self.set_data_chip(f"<b>{data['sessions']}</b> sessions · {data['range']}",
                           "Everything the game still keeps: Game.log and the logbackups folder. "
                           "Older logs the game deleted can't be counted.")
        sections = data["scopes"].get(self.scope)
        if not sections:
            label_ = dict(PERIODS)[self.scope].lower()
            self.show_empty(f"No play sessions in the {label_.removeprefix('last ')}",
                            "Your logs have no game session that started in this period.",
                            "Show all time", lambda: (self.periods.set_value("all"), self._set_scope("all")))
            return
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(12)
        if self.scope == "last":
            v.addWidget(kit.label(f"Last session: {data['last_label']}", "ResultCount"))
        elif self.scope in ("30d", "7d"):
            n = data.get("counts", {}).get(self.scope, 0)
            v.addWidget(kit.label(f"{n} session{'s' if n != 1 else ''} in the "
                                  f"{dict(PERIODS)[self.scope].lower()}", "ResultCount"))
        headline = [
            (*_tile(sections, "Play time", "Time played"), "time played"),
            (*_tile(sections, "Missions", "Completed"), "missions completed"),
            (*_tile(sections, "Missions", "Success rate"), "success rate"),
            (*_tile(sections, "Blueprints", "Received"), "blueprints received"),
        ]
        v.addWidget(kit.StatStrip([(value, caption, hint) for value, hint, caption in headline]))

        # Cards go into the shorter column (by rough height), top to bottom.
        cols = QHBoxLayout()
        cols.setSpacing(12)
        layouts = []
        for _ in range(self._columns):
            lay = QVBoxLayout()
            lay.setSpacing(12)
            layouts.append(lay)
            cols.addLayout(lay, stretch=1)
        heights = [0] * self._columns
        for section in sections:
            col = heights.index(min(heights))
            rows = self._rough_rows(section)
            heights[col] += 3 + (len(section["tiles"]) + TILE_COLUMNS - 1) // TILE_COLUMNS * 2 + rows
            layouts[col].addWidget(_SectionCard(section))
        for lay in layouts:
            lay.addStretch(1)
        v.addLayout(cols)
        v.addStretch(1)
        keep = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(page)
        self.scroll.verticalScrollBar().setValue(keep)
        self.show_content()

    @staticmethod
    def _rough_rows(section: dict) -> int:
        """Rough height of a card's lists, in rows, for placing the cards."""
        heights = []
        for lst in section.get("lists", []):
            n = len(lst["rows"])
            n = min(n, 6) if not lst.get("columns") else min(n, (lst.get("limit") or n) + 1) // 2 + 1
            heights.append(n + 1)
        if not heights:
            return 0
        return sum(heights)
