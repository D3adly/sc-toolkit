"""My Stats: the player's statistics from every Game.log on disk (app.stats),
all time or for the last play session. Read on opening and on Refresh;
nothing is stored.
"""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, config, contracts, settings, stats
from app.theme import PALETTE

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

    def run(self) -> None:
        def work():
            try:
                root = settings.current().game_root
                ch = channel_mod.pick_default_channel(root)
                lookup = None
                if ch:
                    try:   # mission details are a bonus; stats work without them
                        lookup = contracts.load(channel_mod.resolve_channel_paths(root, ch).channel_root,
                                                self.progress.emit)
                    except Exception:
                        traceback.print_exc()
                self.progress.emit("Reading your game logs…")
                self.loaded.emit(stats.load(
                    root, lookup,
                    progress=lambda done, total: self.progress.emit(f"Reading your game logs… {done}/{total}")))
            except Exception as exc:
                traceback.print_exc()
                self.failed.emit(str(exc))
        threading.Thread(target=work, daemon=True).start()


def _glyph_icon(name: str) -> QIcon:
    """A white glyph PNG, tinted muted (off) and gold (selected)."""
    icon = QIcon()
    source = QPixmap(str(GLYPHS / f"{name}.png"))
    if source.isNull():
        return icon
    for colour, state in ((PALETTE["text_muted"], QIcon.Off), (PALETTE["accent"], QIcon.On)):
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
            left = _label(name, "StatRowName", name)
            left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            right = _label(value, "StatRowValue")
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


class _SectionCard(QFrame):
    def __init__(self, section: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SidePanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)
        v.addWidget(_label(section["title"].upper(), "SectionLabel"))

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(14)
        tiles.setVerticalSpacing(10)
        for i, (name, value, hint) in enumerate(section["tiles"]):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(_label(value, "StatValue", hint))
            box.addWidget(_label(name, "StatLabel", hint, wrap=True))
            tiles.addLayout(box, i // TILE_COLUMNS, i % TILE_COLUMNS)
        for c in range(TILE_COLUMNS):
            tiles.setColumnStretch(c, 1)
        v.addLayout(tiles)

        lists = [lst for lst in section.get("lists", []) if lst["rows"]]
        if section.get("filter") and lists:
            self._add_filtered(v, lists)
        elif lists:
            side = [lst for lst in lists if not lst.get("columns")]
            if side:
                row = QHBoxLayout()
                row.setSpacing(18)
                for lst in side:
                    row.addWidget(self._list_block(lst), stretch=1, alignment=Qt.AlignTop)
                v.addLayout(row)
            for lst in lists:
                if lst.get("columns"):
                    v.addWidget(self._list_block(lst))
        if section.get("note"):
            v.addWidget(_label(section["note"], "InspectorHint", wrap=True))

    @staticmethod
    def _list_block(lst: dict, count: bool = False) -> QWidget:
        block = QWidget()
        col = QVBoxLayout(block)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        title = lst["title"].upper() + (f"  ·  {len(lst['rows'])}" if count else "")
        col.addWidget(_label(title, "ConfigLabel"))
        col.addWidget(_RowList(lst["rows"], lst.get("limit"), bool(lst.get("columns"))))
        return block

    def _add_filtered(self, v: QVBoxLayout, lists: list[dict]) -> None:
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
        v.addLayout(bar)
        for _key, block in blocks:
            v.addWidget(block)


class StatsView(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: dict | None = None
        self.scope = "all"
        self._loading = False
        self._columns = 2
        self._loader = _Loader(self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.progress.connect(self._message)
        self._loader.failed.connect(lambda msg: self._on_failed(f"Couldn't read your game logs:\n\n{msg}"))
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 20)
        outer.setSpacing(10)

        bar_frame = QFrame(objectName="ToolBar")
        bar = QHBoxLayout(bar_frame)
        bar.setContentsMargins(10, 8, 10, 8)
        bar.setSpacing(8)
        back = QPushButton("←  Back", objectName="ToolButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        bar.addWidget(back)
        bar.addSpacing(10)
        bar.addWidget(QLabel("SHOW", objectName="ConfigLabel"))
        self.scope_group = QButtonGroup(self)
        for i, (key, text) in enumerate((("all", "ALL TIME"), ("last", "LAST SESSION"))):
            btn = QPushButton(text, objectName="Segment")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("pos", "first" if i == 0 else "last")
            btn.setChecked(key == self.scope)
            btn.clicked.connect(lambda _c=False, k=key: self._set_scope(k))
            self.scope_group.addButton(btn)
            bar.addWidget(btn)
        bar.addStretch(1)
        self.summary = QLabel("", objectName="InspectorHint")
        self.summary.setMinimumWidth(80)
        self.summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar.addWidget(self.summary, stretch=2)
        self.refresh_btn = QPushButton("Refresh", objectName="ToolButton")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._load)
        bar.addWidget(self.refresh_btn)
        outer.addWidget(bar_frame)

        self.scroll = QScrollArea(objectName="InspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll, stretch=1)

    # -- lifecycle ------------------------------------------------------------------
    def activate(self) -> None:
        if self.data is None and not self._loading:
            self._load()

    def _load(self) -> None:
        self._loading = True
        self.refresh_btn.setEnabled(False)
        self._message("Reading your game logs…")
        self._loader.run()

    def _on_loaded(self, data: dict) -> None:
        self._loading = False
        self.refresh_btn.setEnabled(True)
        self.data = data
        self._render()

    def _on_failed(self, text: str) -> None:
        self._loading = False
        self.refresh_btn.setEnabled(True)
        self._message(text)

    def _set_scope(self, scope: str) -> None:
        self.scope = scope
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wanted = 2 if self.scroll.viewport().width() >= 900 else 1
        if wanted != self._columns:
            self._columns = wanted
            self._render()

    # -- rendering ----------------------------------------------------------------------
    def _page(self) -> QVBoxLayout:
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        page = QWidget(objectName="Inspector")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(12)
        self.scroll.setWidget(page)
        return v

    def _message(self, text: str) -> None:
        v = self._page()
        lbl = _label(text, "InspectorHint", wrap=True)
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl, stretch=1)

    @staticmethod
    def _rough_rows(section: dict) -> int:
        """Rough height of a card's lists, in rows, for placing the cards."""
        heights = []
        for lst in section.get("lists", []):
            n = len(lst["rows"])
            if lst.get("limit"):
                n = min(n, lst["limit"] + 1)
            if lst.get("columns"):
                n = -(-n // 2)
            heights.append(n + 1)
        if not heights:
            return 0
        return sum(heights) if section.get("filter") else max(heights)

    def _render(self) -> None:
        if self.data is None:
            return
        data = self.data
        if not data["sessions"]:
            self.summary.setText("")
            self._message("No game logs found. Check the game folder in Settings; the logs are "
                          "Game.log and the logbackups folder next to it.")
            return
        if self.scope == "last":
            self.summary.setText(f"Last session: {data['last_label']}")
        else:
            self.summary.setText(f"{data['sessions']} sessions · {data['range']}")
            self.summary.setToolTip("Everything the game still keeps: Game.log and the logbackups folder. "
                                    "Older logs the game deleted can't be counted.")
        sections = data["scopes"].get(self.scope) or []
        v = self._page()
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
