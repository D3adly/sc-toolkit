"""My Stats: the player's statistics from every Game.log on disk (app.stats),
all time or for the last play session. Read on opening and on Refresh;
nothing is stored.
"""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, Qt, Signal
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

from app import channel as channel_mod, contracts, settings, stats

TILE_COLUMNS = 4


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
        if lists:
            row = QHBoxLayout()
            row.setSpacing(18)
            for lst in lists:
                col = QVBoxLayout()
                col.setSpacing(3)
                col.addWidget(_label(lst["title"].upper(), "ConfigLabel"))
                grid = QGridLayout()
                grid.setHorizontalSpacing(10)
                grid.setVerticalSpacing(2)
                for r, (name, value) in enumerate(lst["rows"]):
                    left = _label(name, "StatRowName", name)
                    left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                    grid.addWidget(left, r, 0)
                    right = _label(value, "StatRowValue")
                    right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    grid.addWidget(right, r, 1)
                grid.setColumnStretch(0, 1)
                col.addLayout(grid)
                if lst.get("more"):
                    col.addWidget(_label(f"…and {lst['more']} more", "InspectorHint"))
                col.addStretch(1)
                row.addLayout(col, stretch=1)
            v.addLayout(row)
        if section.get("note"):
            v.addWidget(_label(section["note"], "InspectorHint", wrap=True))


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
            rows = max([len(lst["rows"]) for lst in section.get("lists", [])] + [0])
            heights[col] += 3 + (len(section["tiles"]) + TILE_COLUMNS - 1) // TILE_COLUMNS * 2 + rows
            layouts[col].addWidget(_SectionCard(section))
        for lay in layouts:
            lay.addStretch(1)
        v.addLayout(cols)
        v.addStretch(1)
