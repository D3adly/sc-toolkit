"""My Ships: the player's hangar as a grid of ship cards (app.hangar), with
an Add / Edit side panel over the ship catalogue (app.ships).

Cards: gold outline = pledged (store), steel-blue = bought in game; ships
still in concept show their loaners. The Erkul button opens Erkul's ship
pop-out for released ships. Clicking a card opens its details page: stats
and default loadout from the game files (app.shipdata).
"""

from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app import channel as channel_mod, config, datahub, hangar, osutil, settings, shipdata, ships
from app.hangar import INGAME, PLEDGE, Entry
from app.theme import PALETTE
from app.ui.widgets import Elided

CARD_WIDTH = 252
CARD_HEIGHT = 280               # every card the same size: long text ends in "…"
IMAGE_HEIGHT = 136
GRID_SPACING = 14
INSURANCE = ["", "LTI", "120 months", "72 months", "24 months", "12 months", "6 months", "3 months"]
SORTS = [("Name", "name"), ("Manufacturer", "manufacturer"), ("Size", "size"), ("Recently added", "added")]
WIKI_URL = "https://starcitizen.tools"
STAT_LABEL_WIDTH = 150
# Item types, as shown next to systems and utility items on the details page.
TYPE_LABELS = {"PowerPlant": "Power plant", "Cooler": "Cooler", "Shield": "Shield", "QuantumDrive": "Quantum drive",
               "JumpDrive": "Jump drive", "Radar": "Radar", "LifeSupportGenerator": "Life support",
               "WeaponMining": "Mining laser", "SalvageHead": "Salvage head", "TractorBeam": "Tractor beam",
               "WeaponDefensive": "Countermeasure", "MissileLauncher": "Rack", "Missile": "Missile"}


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    lbl = QLabel(text, objectName=name)
    lbl.setWordWrap(wrap)
    return lbl


def _mini(text: str, name: str = "MiniButton", checkable: bool = False) -> QPushButton:
    btn = QPushButton(text, objectName=name)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setCheckable(checkable)
    return btn


class _Worker(QObject):
    """Ship pictures, downloaded off the UI thread (once; then cached)."""

    image_ready = Signal(str, str)          # ship key, file

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images: queue.Queue = queue.Queue()
        self._queued: set[str] = set()
        threading.Thread(target=self._image_loop, daemon=True).start()

    def want_image(self, ship: ships.Ship) -> None:
        if ship.key in self._queued or not ship.image:
            return
        self._queued.add(ship.key)
        self._images.put(ship)

    def _image_loop(self) -> None:
        while True:
            ship = self._images.get()
            path = ships.download_image(ship)
            if path is not None:
                self.image_ready.emit(ship.key, str(path))
            else:
                self._queued.discard(ship.key)   # try again next time


class _ShipCard(QFrame):
    edit_requested = Signal(str)            # entry id
    open_requested = Signal(str)            # entry id

    def __init__(self, entry: Entry, ship: ships.Ship | None, parent=None):
        super().__init__(parent)
        self.entry, self.ship = entry, ship
        self.setObjectName("ShipCard")
        self.setProperty("acquired", entry.acquired)
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Open its stats and default loadout")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 10)
        v.setSpacing(4)

        self.image = QLabel(objectName="ShipImage")
        self.image.setFixedSize(CARD_WIDTH - 4, IMAGE_HEIGHT)
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setText(ship.manufacturer if ship else "")
        v.addWidget(self.image, alignment=Qt.AlignHCenter)

        body = QVBoxLayout()
        body.setContentsMargins(12, 4, 12, 0)
        body.setSpacing(3)
        ship_name = ship.name if ship else entry.ship_name
        body.addWidget(Elided(entry.name or ship_name, "ShipName"))
        details = [ship.manufacturer, ship.role, ship.size] if ship else []
        if entry.name:
            details.insert(0, ship_name)
        body.addWidget(Elided("  ·  ".join(d for d in details if d), "InspectorHint"))

        tags = QHBoxLayout()
        tags.setSpacing(6)
        tags.addWidget(_label(hangar.ACQUIRED.get(entry.acquired, entry.acquired).upper(), "AcquiredTag"))
        if ship and ship.concept:
            tags.addWidget(_label("IN CONCEPT", "ConceptTag"))
        if entry.insurance:
            tags.addWidget(Elided(entry.insurance, "InspectorHint"))
        tags.addStretch(1)
        if ship and ship.cargo:
            tags.addWidget(_label(f"{ship.cargo:,} SCU", "CargoTag"))
        body.addLayout(tags)
        # One more line, always there so the cards line up: loaners or notes.
        if ship and ship.concept and ship.loaners:
            extra = Elided("Loaner: " + ", ".join(ship.loaners), "LoanerLine")
        else:
            extra = Elided(entry.notes, "InspectorHint")
        body.addWidget(extra)
        body.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        if ship and ship.erkul_url:
            erkul = _mini("Erkul")
            erkul.setIcon(QIcon(str(config.ICONS_DIR / "erkul.png")))
            erkul.setToolTip("Open this ship on erkul.games")
            erkul.clicked.connect(lambda: osutil.open_url(ship.erkul_url))
            actions.addWidget(erkul)
        actions.addStretch(1)
        edit = _mini("Edit")
        edit.setToolTip("Change how you got it, its name, insurance or notes, or remove it")
        edit.clicked.connect(lambda: self.edit_requested.emit(entry.id))
        actions.addWidget(edit)
        body.addLayout(actions)
        v.addLayout(body)

    def set_image(self, path: str) -> None:
        _cover(self.image, path)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.open_requested.emit(self.entry.id)
        super().mouseReleaseEvent(event)


def _cover(label: QLabel, path: str) -> None:
    """The picture scaled to fill the label, cropped to its shape."""
    pix = QPixmap(path)
    if pix.isNull():
        return
    size = label.size()
    pix = pix.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (pix.width() - size.width()) // 2, (pix.height() - size.height()) // 2
    label.setPixmap(pix.copy(x, y, size.width(), size.height()))


def _num(value, digits: int = 0) -> str:
    return f"{value:,.{digits}f}" if isinstance(value, (int, float)) else "—"


def _stat_rows(ship: ships.Ship, data: dict | None) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """[(section, [(label, value, tooltip)])] for the details page."""
    st = (data or {}).get("stats") or {}
    sections = []
    fl = st.get("flight") or {}
    if fl:
        sections.append(("FLIGHT", [
            ("SCM speed", f"{_num(fl.get('scm'))} m/s", "Top speed in SCM (combat) mode"),
            ("Max speed", f"{_num(fl.get('max'))} m/s", "Top speed in NAV mode"),
            ("Boost", f"{_num(fl.get('boost_fwd'))} / {_num(fl.get('boost_back'))} m/s", "Boosted, forward / backward"),
            ("Pitch · yaw · roll", f"{_num(fl.get('pitch'))} · {_num(fl.get('yaw'))} · {_num(fl.get('roll'))} °/s", ""),
        ]))
    defence = []
    if st.get("shields"):
        defence += [
            ("Shields", f"{_num(st['shield_hp'])} HP", f"{st['shields']} shield generator(s) together"),
            ("Shield regeneration", f"{_num(st['shield_regen'])} HP/s", ""),
        ]
    if ship.health:
        defence.append(("Hull", f"{_num(ship.health)} HP", "From the Star Citizen Wiki"))
    if defence:
        sections.append(("DEFENCE", defence))
    if st.get("power_gen"):
        gen, low, high = st["power_gen"], st.get("power_min", 0), st.get("power_max", 0)
        if high <= gen:
            balance = "Enough to run everything at full power"
        elif low <= gen:
            balance = f"Enough for every system at minimum, not all at full ({_num(high)} needed)"
        else:
            balance = f"Not enough to run every system even at minimum ({_num(low)} needed)"
        sections.append(("POWER & COOLING", [
            ("Power output", f"{_num(gen)} segments", "From the power plant(s), to assign in game"),
            ("Power demand", f"{_num(low)} – {_num(high)} segments",
             "All systems at minimum – all at full (weapons draw from their own pool)"),
            ("Balance", balance, ""),
            ("Cooling", f"{_num(st.get('coolant_gen'))}", "Coolant from the cooler(s)"),
        ]))
    travel = []
    qd = st.get("quantum") or {}
    if qd.get("speed"):
        travel.append(("Quantum speed", f"{_num(qd['speed'] / 1000)} km/s", ""))
        travel.append(("Quantum cooldown", f"{_num(qd.get('cooldown'), 1)} s", ""))
    if st.get("quantum_scu"):
        travel.append(("Quantum fuel", f"{_num(st['quantum_scu'], 1)} SCU", ""))
    if st.get("hydrogen_scu"):
        travel.append(("Hydrogen fuel", f"{_num(st['hydrogen_scu'], 1)} SCU", ""))
    if travel:
        sections.append(("TRAVEL", travel))
    hull = []
    if ship.cargo:
        hull.append(("Cargo", f"{_num(ship.cargo)} SCU", ""))
    if ship.crew:
        hull.append(("Crew", _num(ship.crew), "Maximum crew"))
    if ship.mass:
        hull.append(("Mass", f"{_num(ship.mass / 1000, 1)} t", "With its default loadout"))
    if hull:
        sections.append(("CARGO & CREW", hull))
    return sections


class _DetailsPage(QScrollArea):
    """One ship: picture, facts, stats and default loadout."""

    edit_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InspectorScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.entry: Entry | None = None
        self.ship: ships.Ship | None = None
        self.image: QLabel | None = None

    def show_ship(self, entry: Entry, ship: ships.Ship | None, data: dict | None, note: str) -> None:
        self.entry, self.ship = entry, ship
        page = QWidget(objectName="Inspector")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(12)

        head = QFrame(objectName="SidePanel")
        h = QHBoxLayout(head)
        h.setContentsMargins(14, 14, 18, 14)
        h.setSpacing(18)
        self.image = QLabel(objectName="ShipImage")
        self.image.setFixedSize(440, 248)
        self.image.setAlignment(Qt.AlignCenter)
        h.addWidget(self.image, alignment=Qt.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(6)
        name = entry.name or (ship.name if ship else entry.ship_name)
        info.addWidget(_label(name, "ShipTitle", wrap=True))
        sub = [ship.name] if entry.name and ship else []
        if ship:
            sub += [ship.manufacturer, " · ".join(b for b in (ship.role, ship.focus, ship.size) if b)]
        info.addWidget(_label("  ·  ".join(b for b in sub if b), "InspectorHint", wrap=True))
        tags = QHBoxLayout()
        tags.setSpacing(6)
        tag = _label(hangar.ACQUIRED.get(entry.acquired, entry.acquired).upper(), "AcquiredTag")
        tag.setProperty("acquired", entry.acquired)
        tags.addWidget(tag)
        if ship and ship.concept:
            tags.addWidget(_label("IN CONCEPT", "ConceptTag"))
        elif ship and not ship.store:
            tags.addWidget(_label("IN-GAME ONLY", "InspectorHint"))
        tags.addStretch(1)
        info.addLayout(tags)
        if ship and ship.concept and ship.loaners:
            info.addWidget(_label("Loaner: " + ", ".join(ship.loaners), "LoanerLine", wrap=True))
        facts = [(k, v) for k, v in (("Insurance", entry.insurance), ("Notes", entry.notes)) if v]
        for k, val in facts:
            info.addWidget(_label(f"<b>{k}:</b> {val}", "InspectorText", wrap=True))
        info.addStretch(1)
        buttons = QHBoxLayout()
        if ship and ship.erkul_url:
            erkul = _mini("Open on Erkul")
            erkul.setIcon(QIcon(str(config.ICONS_DIR / "erkul.png")))
            erkul.clicked.connect(lambda: osutil.open_url(ship.erkul_url))
            buttons.addWidget(erkul)
        edit = _mini("Edit")
        edit.clicked.connect(lambda: self.edit_requested.emit(entry.id))
        buttons.addWidget(edit)
        buttons.addStretch(1)
        info.addLayout(buttons)
        h.addLayout(info, stretch=1)
        v.addWidget(head)

        cols = QHBoxLayout()
        cols.setSpacing(12)
        stats_panel = QFrame(objectName="SidePanel")
        sv = QVBoxLayout(stats_panel)
        sv.setContentsMargins(18, 14, 18, 16)
        sv.setSpacing(4)
        sections = _stat_rows(ship, data) if ship else []
        for title, rows in sections:
            sv.addSpacing(6)
            sv.addWidget(_label(title, "SectionLabel"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(3)
            grid.setColumnMinimumWidth(0, STAT_LABEL_WIDTH)      # values line up across sections
            for i, (label, value, tip) in enumerate(rows):
                left, right = _label(label, "InspectorHint"), _label(value, "StatLine", wrap=True)
                left.setToolTip(tip)
                right.setToolTip(tip)
                grid.addWidget(left, i, 0, Qt.AlignTop)
                grid.addWidget(right, i, 1, Qt.AlignTop)
            grid.setColumnStretch(1, 1)
            sv.addLayout(grid)
        if not sections:
            sv.addWidget(_label("STATS", "SectionLabel"))
        sv.addStretch(1)
        cols.addWidget(stats_panel, stretch=1)

        load_panel = QFrame(objectName="SidePanel")
        lv = QVBoxLayout(load_panel)
        lv.setContentsMargins(18, 14, 18, 16)
        lv.setSpacing(4)
        lv.addWidget(_label("DEFAULT LOADOUT", "SectionLabel"))
        rows = (data or {}).get("loadout") or []
        titles = {key: title for key, title, _types in shipdata.GROUPS}
        group = None
        for row in rows:
            if row["group"] != group:
                group = row["group"]
                lv.addSpacing(6)
                lv.addWidget(_label(titles.get(group, group).upper(), "LoadoutGroup"))
            line = QHBoxLayout()
            line.setSpacing(10)
            count = _label(f"{row['count']}×" if row["count"] > 1 else "", "LoadoutCount")
            count.setFixedWidth(32)
            line.addWidget(count)
            size = _label(f"S{row['size']}" if row["size"] else "", "LoadoutSize")
            size.setFixedWidth(30)
            line.addWidget(size)
            kind = TYPE_LABELS.get(row.get("type"), "")
            name = row["name"]
            if "_" in name and " " not in name:      # no display name in the game files: its class id
                name = kind or name
            line.addWidget(Elided(name, "InspectorText"), stretch=1)
            if group in ("systems", "utility") and kind and kind != name:
                type_label = _label(kind, "InspectorHint")
                type_label.setFixedWidth(100)
                line.addWidget(type_label)
            grade = _label(" ".join(b for b in (row.get("class"), row.get("grade")) if b), "InspectorHint")
            grade.setFixedWidth(84)
            grade.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.addWidget(grade)
            lv.addLayout(line)
        lv.addStretch(1)
        cols.addWidget(load_panel, stretch=1)
        v.addLayout(cols)

        if data and note:
            v.addWidget(_label(note, "InspectorHint", wrap=True))   # where the numbers come from
        v.addStretch(1)
        self.setWidget(page)
        if not rows:
            lv.insertWidget(1, _label("No loadout to show." if data or not note else note, "InspectorHint", wrap=True))

    def set_image(self, path: str) -> None:
        if self.image is not None:
            _cover(self.image, path)


class HangarView(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.catalogue = ships.load()
        self.entries = hangar.load()
        self._cards: list[_ShipCard] = []
        self._columns = 0
        self._editing: str | None = None
        self._details: str | None = None     # entry id on the details page
        self.shipdata: shipdata.ShipData | None = None
        self._shipdata_error = ""
        self._worker = _Worker(self)
        self._worker.image_ready.connect(self._on_image)
        # The ship list (weekly) and the ship stats (once per patch) come from
        # app.datahub, which refreshes them at launcher startup.
        datahub.hub().updated.connect(self._on_hub_updated)
        self._stats = datahub.GameDataWaiter("shipdata", self)
        self._stats.ready.connect(self._on_shipdata)
        self._stats.failed.connect(self._on_shipdata_failed)
        self._stats.progress.connect(self._on_shipdata_progress)
        self._build_ui()

    # -- layout ---------------------------------------------------------------
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
        back.setToolTip("Back to your hangar from a ship, else to the launcher")
        back.clicked.connect(self._back)
        bar.addWidget(back)
        bar.addSpacing(6)
        bar.addWidget(QLabel("MY SHIPS", objectName="ConfigLabel"))
        bar.addSpacing(6)
        self.search = QLineEdit(objectName="SearchField")
        self.search.setPlaceholderText("Search your ships")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(150)
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(lambda _t: self._render())
        bar.addWidget(self.search)
        bar.addStretch(1)
        self.sort_label = QLabel("SORT", objectName="ConfigLabel")
        bar.addWidget(self.sort_label)
        self.sort = self._combo(SORTS)
        bar.addWidget(self.sort)
        self.add_btn = QPushButton("Add ships", objectName="StartButtonSmall")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._open_add)
        bar.addWidget(self.add_btn)
        outer.addWidget(bar_frame)

        fbar_frame = self.filter_bar = QFrame(objectName="ToolBar")
        fbar = QHBoxLayout(fbar_frame)
        fbar.setContentsMargins(10, 6, 10, 6)
        fbar.setSpacing(8)
        fbar.addWidget(QLabel("SHOW", objectName="ConfigLabel"))
        self.role_filter = self._combo([("All roles", "")] + [(r, r) for r in ships.ROLES])
        self.size_filter = self._combo([("All sizes", "")] + [(s, s) for s in ships.SIZES])
        self.acquired_filter = self._combo([("Any purchase", ""), ("Pledge", PLEDGE), ("In-game", INGAME)])
        self.status_filter = self._combo([("Any status", ""), ("Flight-ready", ships.FLIGHT_READY),
                                          ("In concept", ships.IN_CONCEPT)])
        for combo in (self.role_filter, self.size_filter, self.acquired_filter, self.status_filter):
            fbar.addWidget(combo)
        fbar.addSpacing(8)
        self.summary = _label("", "InspectorHint")
        fbar.addWidget(self.summary)
        self.status_label = _label("", "InspectorHint")
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fbar.addWidget(self.status_label, stretch=1)
        credit = _label(f"Ship data: <a style='color:{PALETTE['info']}' href='{WIKI_URL}'>Star Citizen Wiki</a>",
                        "InspectorHint")
        credit.setOpenExternalLinks(True)
        fbar.addWidget(credit)
        outer.addWidget(fbar_frame)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.scroll = QScrollArea(objectName="InspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget(objectName="Inspector")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GRID_SPACING)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        body.addWidget(self.scroll, stretch=1)

        self.empty = QFrame(objectName="SidePanel")
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(30, 30, 30, 30)
        ev.addWidget(_label("YOUR HANGAR IS EMPTY", "SectionLabel"), alignment=Qt.AlignHCenter)
        hint = _label("Add the ships you own, pledged on the store or bought in game.\n"
                      "Ships still in concept are listed too, with their loaners.", "InspectorHint")
        hint.setAlignment(Qt.AlignCenter)
        ev.addWidget(hint, alignment=Qt.AlignHCenter)
        ev.addSpacing(6)
        empty_add = QPushButton("Add ships", objectName="StartButtonSmall")
        empty_add.setCursor(Qt.PointingHandCursor)
        empty_add.clicked.connect(self._open_add)
        ev.addWidget(empty_add, alignment=Qt.AlignHCenter)
        ev.addStretch(1)
        body.addWidget(self.empty, stretch=1)

        self.details = _DetailsPage()
        self.details.edit_requested.connect(self._open_edit)
        self.details.hide()
        body.addWidget(self.details, stretch=1)

        self.side = QFrame(objectName="SidePanel")
        self.side.setFixedWidth(340)
        side = QVBoxLayout(self.side)
        side.setContentsMargins(16, 14, 16, 16)
        side.setSpacing(8)
        self._build_add_panel(side)
        self._build_edit_panel(side)
        self.side.hide()
        body.addWidget(self.side)
        outer.addLayout(body, stretch=1)

    def _combo(self, items) -> QComboBox:
        combo = QComboBox(objectName="ConfigCombo")
        combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        for text, data in items:
            combo.addItem(text, data)
        combo.activated.connect(lambda _i: self._render())
        return combo

    def _acquired_buttons(self, layout) -> QButtonGroup:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_label("Bought", "ConfigLabel"))
        group = QButtonGroup(self)
        group.setExclusive(True)
        for value, text in hangar.ACQUIRED.items():
            btn = _mini(text, checkable=True)
            btn.setProperty("value", value)
            btn.setToolTip("Pledged on the RSI store" if value == PLEDGE else "Bought or earned in the game")
            group.addButton(btn)
            row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)
        group.buttons()[0].setChecked(True)
        return group

    @staticmethod
    def _checked(group: QButtonGroup) -> str:
        btn = group.checkedButton()
        return btn.property("value") if btn else PLEDGE

    @staticmethod
    def _check(group: QButtonGroup, value: str) -> None:
        for btn in group.buttons():
            btn.setChecked(btn.property("value") == value)

    def _build_add_panel(self, side) -> None:
        self.add_panel = QWidget()
        v = QVBoxLayout(self.add_panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(_label("ADD SHIPS", "SectionLabel"))
        head.addStretch(1)
        close = _mini("✕")
        close.setToolTip("Close")
        close.clicked.connect(self._close_side)
        head.addWidget(close)
        v.addLayout(head)
        self.pick_search = QLineEdit(objectName="SearchField")
        self.pick_search.setPlaceholderText("Search every ship")
        self.pick_search.setClearButtonEnabled(True)
        self.pick_search.textChanged.connect(lambda _t: self._fill_picker())
        v.addWidget(self.pick_search)
        filters = QHBoxLayout()
        self.pick_role = QComboBox(objectName="ConfigCombo")
        self.pick_size = QComboBox(objectName="ConfigCombo")
        for combo, first, values in ((self.pick_role, "All roles", ships.ROLES),
                                     (self.pick_size, "All sizes", ships.SIZES)):
            combo.addItem(first, "")
            for value in values:
                combo.addItem(value, value)
            combo.activated.connect(lambda _i: self._fill_picker())
            filters.addWidget(combo)
        v.addLayout(filters)
        self.picker = QListWidget(objectName="ActionList")
        self.picker.currentItemChanged.connect(lambda *_: self._on_pick())
        self.picker.itemDoubleClicked.connect(lambda _i: self._add_selected())
        v.addWidget(self.picker, stretch=1)
        self.pick_info = _label("", "InspectorHint", wrap=True)
        v.addWidget(self.pick_info)
        self.add_acquired = self._acquired_buttons(v)
        row = QHBoxLayout()
        self.add_status = _label("", "InspectorNote", wrap=True)
        row.addWidget(self.add_status, stretch=1)
        self.add_selected_btn = QPushButton("Add", objectName="StartButtonSmall")
        self.add_selected_btn.setCursor(Qt.PointingHandCursor)
        self.add_selected_btn.clicked.connect(self._add_selected)
        row.addWidget(self.add_selected_btn)
        v.addLayout(row)
        side.addWidget(self.add_panel)

    def _build_edit_panel(self, side) -> None:
        self.edit_panel = QWidget()
        v = QVBoxLayout(self.edit_panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        self.edit_title = _label("", "SectionLabel", wrap=True)
        head.addWidget(self.edit_title, stretch=1)
        close = _mini("✕")
        close.setToolTip("Close")
        close.clicked.connect(self._close_side)
        head.addWidget(close, alignment=Qt.AlignTop)
        v.addLayout(head)
        self.edit_acquired = self._acquired_buttons(v)
        v.addWidget(_label("Your name for it (optional)", "ConfigLabel"))
        self.edit_name = QLineEdit(objectName="SearchField")
        v.addWidget(self.edit_name)
        v.addWidget(_label("Insurance", "ConfigLabel"))
        self.edit_insurance = QComboBox(objectName="ConfigCombo")
        self.edit_insurance.setEditable(True)
        for value in INSURANCE:
            self.edit_insurance.addItem(value or "Not set", value)
        v.addWidget(self.edit_insurance)
        v.addWidget(_label("Notes", "ConfigLabel"))
        self.edit_notes = QLineEdit(objectName="SearchField")
        v.addWidget(self.edit_notes)
        v.addStretch(1)
        row = QHBoxLayout()
        self.remove_btn = _mini("Remove", "MiniDanger")
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        save = QPushButton("Save", objectName="StartButtonSmall")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save_edit)
        row.addWidget(save)
        v.addLayout(row)
        side.addWidget(self.edit_panel)

    # -- lifecycle --------------------------------------------------------------
    def activate(self) -> None:
        self._render()

    def deactivate(self) -> None:
        self._close_side()
        if self._details is not None:
            self._close_details()

    def _on_hub_updated(self, name: str) -> None:
        if name != "ships":
            return
        self.catalogue = ships.load()
        if self._details is None:
            self._render()
        if self.add_panel.isVisible():
            self._fill_picker()

    # -- grid ---------------------------------------------------------------------
    def _visible(self) -> list[tuple[Entry, ships.Ship | None]]:
        words = self.search.text().lower().split()
        role, size = self.role_filter.currentData(), self.size_filter.currentData()
        acquired, status = self.acquired_filter.currentData(), self.status_filter.currentData()
        out = []
        for e in self.entries:
            s = self.catalogue.get(e.ship)
            text = " ".join([e.name, e.ship_name, e.notes] + ([s.manufacturer, s.focus] if s else [])).lower()
            if words and not all(w in text for w in words):
                continue
            if (role and (not s or s.role != role)) or (size and (not s or s.size != size)):
                continue
            if (acquired and e.acquired != acquired) or (status and (not s or s.status != status)):
                continue
            out.append((e, s))
        key = self.sort.currentData()
        if key == "manufacturer":
            out.sort(key=lambda p: ((p[1].manufacturer if p[1] else ""), p[0].name or p[0].ship_name))
        elif key == "size":
            order = {s: i for i, s in enumerate(ships.SIZES)}
            out.sort(key=lambda p: (-order.get(p[1].size if p[1] else "", -1), p[0].ship_name))
        elif key == "added":
            out.sort(key=lambda p: p[0].added, reverse=True)
        else:
            out.sort(key=lambda p: (p[0].name or p[0].ship_name).lower())
        return out

    def _render(self) -> None:
        for card in self._cards:
            card.hide()                 # deleteLater waits for the event loop
            card.deleteLater()
        self._cards = []
        visible = self._visible()
        for entry, ship in visible:
            card = _ShipCard(entry, ship)
            card.edit_requested.connect(self._open_edit)
            card.open_requested.connect(self._open_details)
            self._cards.append(card)
            if ship is not None:
                if ship.image_file.is_file():
                    card.set_image(str(ship.image_file))
                else:
                    self._worker.want_image(ship)
        self._columns = 0
        self._layout_cards()
        has_ships = bool(self.entries)
        in_details = self._details is not None
        self.scroll.setVisible(has_ships and not in_details)
        self.empty.setVisible(not has_ships and not self.side.isVisible() and not in_details)
        self._update_summary(len(visible))

    def _layout_cards(self) -> None:
        width = self.scroll.viewport().width()
        columns = max(1, (width + GRID_SPACING) // (CARD_WIDTH + GRID_SPACING))
        if columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for i, card in enumerate(self._cards):
            self.grid.addWidget(card, i // columns, i % columns, Qt.AlignTop)

    def _update_summary(self, shown: int) -> None:
        total = len(self.entries)
        pledged = sum(1 for e in self.entries if e.acquired == PLEDGE)
        concept = sum(1 for e in self.entries if (s := self.catalogue.get(e.ship)) and s.concept)
        parts = [f"{total} ship{'s' if total != 1 else ''}", f"{pledged} pledge", f"{total - pledged} in game"]
        if concept:
            parts.append(f"{concept} in concept")
        text = "  ·  ".join(parts) if total else ""
        if total and shown != total:
            text += f"   (showing {shown})"
        self.summary.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._layout_cards)

    def _on_image(self, key: str, path: str) -> None:
        for card in self._cards:
            if card.ship is not None and card.ship.key == key:
                card.set_image(path)
        if self.details.ship is not None and self.details.ship.key == key:
            self.details.set_image(path)

    # -- details page -------------------------------------------------------------
    def _back(self) -> None:
        """A ship's page goes back to the hangar; the hangar to the launcher."""
        if self._details is not None:
            self._close_details()
        else:
            self.back_requested.emit()

    def _set_details_mode(self, on: bool) -> None:
        """Hangar-only controls (search, sort, filters) hide on a ship's page."""
        for widget in (self.search, self.sort_label, self.sort, self.filter_bar):
            widget.setVisible(not on)

    def _open_details(self, entry_id: str) -> None:
        entry = next((e for e in self.entries if e.id == entry_id), None)
        if entry is None:
            return
        self._details = entry_id
        if self.side.isVisible() and self._editing != entry_id:
            self._close_side()
        ship = self.catalogue.get(entry.ship)
        data, note = None, ""
        if ship is None:
            note = "This ship isn't in the ship list any more."
        elif ship.concept:
            note = "Still in concept: there's no game data for it yet."
        elif self.shipdata is not None:
            data = self.shipdata.get(ship.class_id)
            note = ("Stats and default loadout from your game files; hull HP and mass from the Star Citizen Wiki."
                    if data else "This ship isn't in your game files.")
        elif self._shipdata_error:
            note = self._shipdata_error
        else:
            note = "Reading ship data from the game files…"
            root = settings.current().game_root
            channel = channel_mod.pick_default_channel(root)
            self._stats.request(channel_mod.resolve_channel_paths(root, channel).channel_root if channel else None)
        self.details.show_ship(entry, ship, data, note)
        if ship is not None:
            if ship.image_file.is_file():
                self.details.set_image(str(ship.image_file))
            else:
                self._worker.want_image(ship)
        self.scroll.hide()
        self.empty.hide()
        self._set_details_mode(True)
        self.details.show()

    def _close_details(self) -> None:
        self._details = None
        self.details.hide()
        self._set_details_mode(False)
        self._render()

    def _on_shipdata(self, data) -> None:
        self.shipdata = data
        self.status_label.setText("")
        if self._details is not None:
            self._open_details(self._details)

    def _on_shipdata_failed(self, message: str) -> None:
        self._shipdata_error = f"Couldn't read ship data from the game files: {message}"
        self.status_label.setText("")
        if self._details is not None:
            self._open_details(self._details)

    def _on_shipdata_progress(self, text: str) -> None:
        self.status_label.setText(text)

    # -- add / edit ---------------------------------------------------------------
    def _open_add(self) -> None:
        self._editing = None
        self.edit_panel.hide()
        self.add_panel.show()
        self.side.show()
        self.empty.hide()
        self.add_status.setText("")
        self._fill_picker()
        self.pick_search.setFocus()
        QTimer.singleShot(0, self._relayout)

    def _open_edit(self, entry_id: str) -> None:
        entry = next((e for e in self.entries if e.id == entry_id), None)
        if entry is None:
            return
        self._editing = entry_id
        ship = self.catalogue.get(entry.ship)
        self.add_panel.hide()
        self.edit_panel.show()
        self.side.show()
        self.edit_title.setText((ship.name if ship else entry.ship_name).upper())
        self._check(self.edit_acquired, entry.acquired)
        self._limit_acquired(self.edit_acquired, ship)
        self.edit_name.setText(entry.name)
        index = self.edit_insurance.findData(entry.insurance)
        if index >= 0:
            self.edit_insurance.setCurrentIndex(index)
        else:
            self.edit_insurance.setEditText(entry.insurance)
        self.edit_notes.setText(entry.notes)
        self._arm_remove(False)
        QTimer.singleShot(0, self._relayout)

    def _close_side(self) -> None:
        self._editing = None
        self.side.hide()
        self.empty.setVisible(not self.entries)
        QTimer.singleShot(0, self._relayout)

    def _relayout(self) -> None:
        self._columns = 0
        self._layout_cards()

    def _fill_picker(self) -> None:
        current = self.picker.currentItem().data(Qt.UserRole) if self.picker.currentItem() else None
        self.picker.clear()
        found = self.catalogue.search(self.pick_search.text(), self.pick_role.currentData(),
                                      self.pick_size.currentData())
        for ship in found:
            tag = "  ·  in concept" if ship.concept else ("  ·  in-game only" if not ship.store else "")
            item = QListWidgetItem(f"{ship.name}{tag}\n{ship.manufacturer}")
            item.setData(Qt.UserRole, ship.key)
            self.picker.addItem(item)
            if ship.key == current:
                self.picker.setCurrentItem(item)
        if not found:
            self.pick_info.setText("No ship matches." if len(self.catalogue) else
                                   "The ship list isn't loaded yet.")
        self._on_pick()

    def _selected_ship(self) -> ships.Ship | None:
        item = self.picker.currentItem()
        return self.catalogue.get(item.data(Qt.UserRole)) if item else None

    def _on_pick(self) -> None:
        ship = self._selected_ship()
        self.add_selected_btn.setEnabled(ship is not None)
        self._limit_acquired(self.add_acquired, ship)
        if ship is None:
            if self.picker.count():
                self.pick_info.setText("Pick a ship, choose how you got it, then Add (or double-click).")
            return
        bits = [b for b in (ship.role, ship.size, ship.focus) if b]
        text = " · ".join(bits)
        if ship.concept:
            text += ("\nIn concept. Loaner: " + ", ".join(ship.loaners)) if ship.loaners else "\nIn concept."
        elif not ship.store:
            text += "\nOnly obtainable in game."
        self.pick_info.setText(text)

    def _limit_acquired(self, group: QButtonGroup, ship: ships.Ship | None) -> None:
        """Concept ships can only be pledged; game-only ships only bought in game."""
        for btn in group.buttons():
            value = btn.property("value")
            allowed = ship is None or not ((ship.concept and value == INGAME) or (not ship.store and value == PLEDGE))
            btn.setEnabled(allowed)
            if not allowed and btn.isChecked():
                self._check(group, PLEDGE if value == INGAME else INGAME)

    def _add_selected(self) -> None:
        ship = self._selected_ship()
        if ship is None:
            return
        acquired = self._checked(self.add_acquired)
        self.entries.append(Entry(ship=ship.key, ship_name=ship.name, acquired=acquired))
        hangar.save(self.entries)
        self.add_status.setText(f"Added {ship.name} ({hangar.ACQUIRED[acquired].lower()}).")
        self._render()

    def _save_edit(self) -> None:
        entry = next((e for e in self.entries if e.id == self._editing), None)
        if entry is None:
            return
        entry.acquired = self._checked(self.edit_acquired)
        entry.name = self.edit_name.text().strip()
        text = self.edit_insurance.currentText().strip()
        entry.insurance = "" if text == "Not set" else text
        entry.notes = self.edit_notes.text().strip()
        hangar.save(self.entries)
        self._close_side()
        self._render()
        if self._details == entry.id:
            self._open_details(entry.id)

    def _arm_remove(self, armed: bool) -> None:
        self._remove_armed = armed
        self.remove_btn.setText("Click again to remove" if armed else "Remove")

    def _remove(self) -> None:
        if not self._remove_armed:
            self._arm_remove(True)
            return
        removed = self._editing
        self.entries = [e for e in self.entries if e.id != removed]
        hangar.save(self.entries)
        self._close_side()
        if self._details == removed:
            self._close_details()
        self._render()
