"""Compact layouts of SC-Toolbox's tools for the in-game overlay: the same
data code as the full views (app.maps / app.mining / app.salvage) and the
same components (app.ui.kit, the views' own cards and rows in their compact
mode), only narrower. The overlay has no tooltips, so what the launcher
shows on hover is spelled out here.
"""

from __future__ import annotations

import html
import sys
import threading
import time
import traceback

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, datahub, maps, mining, salvage, settings
from app.theme import PALETTE
from app.ui import kit
from app.ui.kit import Badge, label
from app.ui.maps_view import ZOOM_STEP, ZoomView, _cache_path, _ImageLoader
from app.ui.mining_view import KIND_LABELS, LocationCard, _pct
from app.ui.salvage_view import ShipRowWidget


def _label(text: str, name: str = "SalvageCell", tip: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text, objectName=name)
    lbl.setWordWrap(wrap)
    if tip:
        lbl.setToolTip(tip)
    return lbl


class _InlineCombo(kit.Dropdown):
    """A combo box whose list opens inside the overlay window instead of as a
    popup window. A popup grabs the mouse; over a fullscreen game (XWayland,
    an OSD window) that grab sometimes failed, so the list closed at once and
    the click went to the game."""

    MARGIN = 6

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._list: QListView | None = None

    def showPopup(self) -> None:
        win = self.window()
        if self._list is None:
            lst = QListView(win, objectName="InlineComboList")
            lst.setModel(self.model())
            lst.setEditTriggers(QListView.NoEditTriggers)
            lst.setUniformItemSizes(True)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lst.clicked.connect(self._pick)
            lst.activated.connect(self._pick)
            self._list = lst
        lst = self._list
        lst.setCurrentIndex(self.model().index(self.currentIndex(), self.modelColumn()))
        # Below the combo if the list fits there (or there's more room), else above.
        top = self.mapTo(win, QPoint(0, 0))
        row = lst.sizeHintForRow(0) if self.count() else self.height()
        wanted = min(self.count(), self.maxVisibleItems()) * row + 8
        below = win.height() - (top.y() + self.height()) - self.MARGIN
        above = top.y() - self.MARGIN
        if wanted <= below or below >= above:
            height, y = min(wanted, below), top.y() + self.height() + 2
        else:
            height = min(wanted, above)
            y = top.y() - height - 2
        width = min(max(self.width(), 160), win.width() - 2 * self.MARGIN)
        x = max(self.MARGIN, min(top.x(), win.width() - width - self.MARGIN))
        lst.setGeometry(x, y, width, max(height, row))
        lst.show()
        lst.raise_()
        lst.scrollTo(lst.currentIndex(), QListView.PositionAtCenter)
        lst.setFocus()
        QApplication.instance().installEventFilter(self)

    def hidePopup(self) -> None:
        QApplication.instance().removeEventFilter(self)
        if self._list is not None and self._list.isVisible():
            self._list.hide()
            self.setFocus()

    def _pick(self, index) -> None:
        self.setCurrentIndex(index.row())
        self.hidePopup()
        self.activated.emit(index.row())       # as a real popup does: a pick by the user

    def eventFilter(self, obj, event):
        # While open: a click anywhere else, or Esc, closes the list.
        if self._list is not None and self._list.isVisible():
            if event.type() == QEvent.MouseButtonPress and isinstance(obj, QWidget):
                if obj is not self._list and not self._list.isAncestorOf(obj):
                    self.hidePopup()
                    if obj is self:
                        return True   # clicking the combo again just closes it
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.hidePopup()
                return True
        return False


def _combo(min_width: int = 0, marks: bool = False) -> QComboBox:
    combo = _InlineCombo(marks=marks)
    combo.setMaxVisibleItems(20)
    if min_width:
        combo.setMinimumWidth(min_width)
    combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return combo


def _log(text: str) -> None:
    """To the overlay's log (overlay.log, via the launcher)."""
    print(f"overlay: {text}", file=sys.stderr, flush=True)


def _channel_root():
    root = settings.current().game_root
    ch = channel_mod.pick_default_channel(root)
    found = channel_mod.resolve_channel_paths(root, ch).channel_root if ch else None
    _log(f"game folder {root} → channel {ch} → {found}")
    return found


def _cached_game(name: str, root):
    """Game data from the launcher's cache (app.datahub). After a patch the
    launcher may still be building it: wait for it rather than read the game
    files a second time in this process."""
    for _attempt in range(40):
        data = datahub.read_game(name, root)
        if data is not None:
            return data
        time.sleep(30)
    raise RuntimeError("SC-Toolbox hasn't finished reading the game files yet. Keep it open and try again.")


class _Task(QObject):
    """Runs a function off the GUI thread; emits done(result) / failed(msg)."""

    done = Signal(object)
    failed = Signal(str)

    def run(self, fn, what: str = "data") -> None:
        def work():
            try:
                result = fn()
            except Exception as exc:
                _log(f"loading {what} failed:\n{traceback.format_exc()}")
                self.failed.emit(str(exc))
                return
            _log(f"loaded {what}")
            self.done.emit(result)
        threading.Thread(target=work, daemon=True).start()


class _ScrollPanel(QWidget):
    """Controls on top, a scrollable page below that is rebuilt on each render."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        self.scroll = QScrollArea(objectName="InspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)

    def _add_scroll(self) -> None:
        self.layout_.addWidget(self.scroll, stretch=1)

    def _new_page(self) -> QVBoxLayout:
        # takeWidget + deleteLater, not setWidget(): that deletes the old page
        # at once, and a click on a row in it (which triggered this rebuild)
        # would return into deleted widgets and crash.
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        page = QWidget(objectName="Inspector")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(6)
        self.scroll.setWidget(page)
        return v

    def _message(self, text: str, title: str = "") -> None:
        v = self._new_page()
        v.addWidget(kit.EmptyState(title, text), stretch=1)


# -- following the game ---------------------------------------------------------

class _FollowLine(QFrame):
    """'● Following your game · Claim #72212 …' with Stop, or 'Follow your
    game' to turn it back on. One per data panel; the choice is kept per tool
    (overlay.json)."""

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, objectName="FollowLine")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 4, 3)
        row.setSpacing(6)
        self.dot = kit.Dot(PALETTE["success"], 7)
        row.addWidget(self.dot, alignment=Qt.AlignTop)
        row.setAlignment(Qt.AlignTop)
        self.text = label("", "FollowText", rich=True, wrap=True)
        row.addWidget(self.text, stretch=1)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(4)
        row.addLayout(self.extra)
        self.button = kit.button("", "ghost", lambda: self.toggled.emit(not self.on))
        row.addWidget(self.button)
        self.on = True

    def set_state(self, on: bool, text: str) -> None:
        self.on = on
        self.dot.setVisible(on)
        self.text.setText(text if on else "<span style='color:%s'>Not following your game</span>"
                          % PALETTE["text_muted"])
        self.button.setText("Stop" if on else "Follow your game")
        self._fit_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()

    def _fit_text(self) -> None:
        # A wrapping label in a row doesn't get taller by itself: give it the lines it needs.
        if self.text.width() > 0:
            self.text.setMinimumHeight(max(0, self.text.heightForWidth(self.text.width())))


class _FollowMixin:
    """For panels that follow the game (the live log): Mining opens on your
    system, Salvage on your claim, Maps suggests guides. A change is applied
    only when the game's state changes, and never while the pointer is over
    the panel (it waits until it leaves), so it doesn't jump while you read."""

    FOLLOW_TOOL = ""

    def _init_follow(self, layout: QVBoxLayout, index: int = 0) -> None:
        self.follow_line = _FollowLine()
        self.follow_line.toggled.connect(self._set_follow)
        layout.insertWidget(index, self.follow_line)
        self._follow_pending = False
        self._feed_connected = False

    def _feed(self):
        from app.ui import overlay_live

        return overlay_live.feed()

    def following(self) -> bool:
        win = self.window()
        return win.follows(self.FOLLOW_TOOL) if hasattr(win, "follows") else True

    def _set_follow(self, on: bool) -> None:
        win = self.window()
        if hasattr(win, "set_follows"):
            win.set_follows(self.FOLLOW_TOOL, on)
        self._follow_start()
        self._unfollow() if not on else self._game_changed(force=True)

    def _follow_start(self) -> None:
        """On activate: start the live reader if following."""
        f = self._feed()
        if not self._feed_connected:
            f.changed.connect(self._game_changed)
            self._feed_connected = True
        if self.following():
            f.want()
        self._update_follow_line()

    def _game_changed(self, force: bool = False) -> None:
        if not self.following() or not self.isVisible():
            return
        if self.underMouse() and not force:
            self._follow_pending = True
            self._update_follow_line()
            return
        self._follow_pending = False
        self._apply_game()
        self._update_follow_line()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._follow_pending:
            QTimer.singleShot(0, self._game_changed)

    def _update_follow_line(self) -> None:
        f = self._feed()
        if f.state == "disabled":
            text = f"<span style='color:{PALETTE['text_muted']}'>Turn on LIVE LOG in SC-Toolbox to follow your game</span>"
        elif f.state in ("off", "waiting") and not f.tracker.session:
            text = f"<span style='color:{PALETTE['text_muted']}'>Following your game once Star Citizen runs</span>"
        else:
            text = self._follow_text()
            if self._follow_pending:
                text += f" <span style='color:{PALETTE['text_muted']}'>· updates when the pointer leaves</span>"
        self.follow_line.set_state(self.following(), text)

    def _follow_text(self) -> str:
        return "Following your game"

    def _apply_game(self) -> None:
        raise NotImplementedError

    def _unfollow(self) -> None:
        """Following was turned off: drop what it added."""


# -- Maps -----------------------------------------------------------------------

class MapsPanel(_FollowMixin, QWidget):
    """Mr Kraken's one-page guides. A guide fills the panel's width (scroll
    down it); the panel takes the guide's shape when one opens (wide for
    landscape ones), L or ⤢ shows it large (Esc back). Following the game, it
    suggests the guides for your missions and where you are."""

    FOLLOW_TOOL = "maps"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loader = _ImageLoader(self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(lambda url, msg: url == self._wanted and self._msg(f"Couldn't load:\n{msg}"))
        self._wanted: str | None = None
        self._shape_pending = True       # take the next guide's shape
        self._suggested: list[str] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.guide = _combo()
        for title, pages, source in maps.GUIDES:
            self.guide.addItem(title, pages)
        self.guide.activated.connect(lambda i: self._on_guide(i, shape=True))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.guide, stretch=1)
        for text, slot in (("−", lambda: self.viewer.zoom_by(1 / ZOOM_STEP)),
                           ("Fit", lambda: self.viewer.fit_to("page" if self.viewer.fit_mode == "width" else "width")),
                           ("+", lambda: self.viewer.zoom_by(ZOOM_STEP)),
                           ("⤢", self._toggle_large)):
            btn = QPushButton(text, objectName="MiniButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        v.addLayout(row)
        self.page = _combo()   # only shown for guides with several pages
        self.page.activated.connect(lambda i: self._on_page(i, shape=True))
        v.addWidget(self.page)

        frame = QFrame(objectName="MapFrame")
        stack = QStackedLayout(frame)
        stack.setStackingMode(QStackedLayout.StackAll)
        self.viewer = ZoomView()
        self.viewer.fit_mode = "width"
        self.message = QLabel("", objectName="InspectorHint")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setAttribute(Qt.WA_TransparentForMouseEvents)
        stack.addWidget(self.viewer)
        stack.addWidget(self.message)
        stack.setCurrentWidget(self.message)
        v.addWidget(frame, stretch=1)
        v.addWidget(label("Community guides by Mr Kraken, all credit to the author. Fit: whole page or "
                          "width · ⤢ or L: large (Esc back).", "MutedText", wrap=True))
        self._init_follow(v, 0)

    def activate(self) -> None:
        self._follow_start()
        if self._wanted is None:
            self._on_guide(self.guide.currentIndex(), shape=True)
        self._game_changed(force=True)

    def _toggle_large(self) -> None:
        win = self.window()
        if hasattr(win, "toggle_large"):
            win.toggle_large()

    # -- following: suggest guides ---------------------------------------------------
    def _apply_game(self) -> None:
        tr = self._feed().tracker
        texts = [tr.location, tr.qt_target]
        for m in tr.active_missions():
            texts += [m.title, m.contract]
        suggested = maps.suggested_guides(texts)
        if suggested == self._suggested and self.follow_line.extra.count():
            return
        self._suggested = suggested
        kit.clear_layout(self.follow_line.extra)
        current = self.guide.currentText()
        for title in self._suggested[:2]:
            if title == current:
                continue
            short = title.split(" [", 1)[0].replace(" Companion Guide", "").replace(" Guide", "")
            self.follow_line.extra.addWidget(kit.button(f"{short} ›", "ghost", lambda _c=False, t=title: self._open_guide(t)))

    def _unfollow(self) -> None:
        self._suggested = []
        kit.clear_layout(self.follow_line.extra)

    def _follow_text(self) -> str:
        if not self._suggested:
            return "Following your game · no guide for your missions or location"
        if self._suggested == [self.guide.currentText()]:
            return "Following your game · this guide is for what you're doing"
        return "For what you're doing:"

    def _open_guide(self, title: str) -> None:
        i = self.guide.findText(title)
        if i >= 0:
            self.guide.setCurrentIndex(i)
            self._on_guide(i, shape=True)
            self._apply_game()
            self._update_follow_line()

    # -- guides ------------------------------------------------------------------------
    def _on_guide(self, index: int, shape: bool = False) -> None:
        pages = self.guide.itemData(index) or []
        self.page.blockSignals(True)
        self.page.clear()
        for label_, url in pages:
            self.page.addItem(label_, url)
        self.page.blockSignals(False)
        self.page.setVisible(len(pages) > 1)
        self._on_page(0, shape)

    def _on_page(self, index: int, shape: bool = False) -> None:
        url = self.page.itemData(index)
        if url:
            self._wanted = url
            self._shape_pending = self._shape_pending or shape
            self._msg("" if _cache_path(url).is_file() else "Loading…")
            self._loader.load(url)

    def _msg(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _on_loaded(self, url: str, data: bytes) -> None:
        from PySide6.QtGui import QPixmap

        if url != self._wanted:
            return
        pix = QPixmap()
        if not pix.loadFromData(data):
            self._msg("Couldn't read this image.")
            return
        self._msg("")
        if self._shape_pending and pix.height() > 0:
            self._shape_pending = False
            win = self.window()
            if hasattr(win, "fit_aspect"):
                # Once laid out (the viewer's height is what the guide should fill).
                ratio = pix.width() / pix.height()
                QTimer.singleShot(0, lambda: win.fit_aspect("maps", self.viewer, ratio))
        self.viewer.set_pixmap(pix)


# -- Mining ---------------------------------------------------------------------

class _Clickable(QFrame):
    clicked = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        hit = event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint())
        super().mouseReleaseEvent(event)
        if hit:
            # Last: opening a location rebuilds the page and deletes this row.
            self.clicked.emit()


def _rows_panel() -> tuple[QFrame, QVBoxLayout]:
    """The glass panel a list of rows sits in (as in the launcher's tables)."""
    frame = kit.panel()
    rows = QVBoxLayout(frame)
    rows.setContentsMargins(0, 2, 0, 2)
    rows.setSpacing(0)
    return frame, rows


class MiningPanel(_FollowMixin, _ScrollPanel):
    """Pick an ore (or not), a mining method and a system → the places, best
    first for the ore: how many of the rocks there carry it and its best
    average quality. Pick a place → its rock types (the launcher's location
    card, compact): spawn chance, rarity, radar signatures, composition and
    quality odds. Following the game, it opens on your system with where you
    are and the places around it first."""

    FOLLOW_TOOL = "mining"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: dict | None = None
        self.location: str | None = None     # id of the opened location
        self._near: list[str] = []           # following: mining places around you, nearest first
        self._here = ""                      # following: where you are, as the log says it
        self._applied = None                 # the (system, body) last applied
        v = self.layout_
        self.resource = _combo(marks=True)
        self.resource.currentIndexChanged.connect(lambda _i: self._render())
        v.addWidget(self.resource)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.method = kit.Segmented(list(mining.METHOD_LABELS.items()), "ship", compact=True)
        self.method.changed.connect(self._on_method)
        row.addWidget(self.method)
        row.addStretch(1)
        self.system = kit.Segmented([(None, "All")], None, compact=True)
        self.system.changed.connect(lambda _v: self._fill_resources())
        row.addWidget(self.system)
        v.addLayout(row)
        self.count = label("", "ResultCount")
        v.addWidget(self.count)
        self._add_scroll()
        self._task = _Task(self)
        self._task.done.connect(self._on_loaded)
        self._task.failed.connect(lambda msg: self._message(msg, "Couldn't read the game data"))
        self._message("Loading mining data…")
        self._init_follow(v, 0)

    def activate(self) -> None:
        self._follow_start()
        if self.data is None:
            root = _channel_root()
            if root is None:
                self._message("Set up your Star Citizen folder in the launcher first.", "No game folder")
                return
            self._task.run(lambda: _cached_game("mining", root), "mining data")
        else:
            self._game_changed(force=True)

    def _on_loaded(self, data: dict) -> None:
        self.data = data
        self.system.set_options([(None, "All")] + [(s["id"], s["name"]) for s in data["systems"]],
                                self.system.value())
        self._applied = None
        self._fill_resources()
        self._game_changed(force=True)

    # -- following: your system, where you are first ----------------------------------
    def _apply_game(self) -> None:
        if self.data is None:
            return
        tr = self._feed().tracker
        self._here = tr.location or ""
        system, body = mining.place_from_log(self._here)
        if (system, body) == self._applied:
            return
        self._applied = (system, body)
        self._near = mining.nearby(self.data["locations"], body)
        if system and any(s["id"] == system for s in self.data["systems"]):
            self.system.set_value(system)
        self.location = None
        self._fill_resources()
        self.scroll.verticalScrollBar().setValue(0)

    def _unfollow(self) -> None:
        self._near, self._applied = [], None
        self._render()

    def _follow_text(self) -> str:
        from app.stats import pretty

        if not self._here:
            return "Following your game · location not known yet"
        system, body = mining.place_from_log(self._here)
        names = {l["id"]: l["name"] for l in (self.data or {}).get("locations", [])}
        systems = {x["id"]: x["name"] for x in (self.data or {}).get("systems", [])}
        if self._near:
            where = names.get(body) or names.get(self._near[0], "")
            return f"Following your game · around <b>{html.escape(where)}</b> first"
        if system in systems:
            return f"Following your game · in <b>{systems[system]}</b>"
        return f"Following your game · at {html.escape(pretty(self._here))}"

    # -- filters ------------------------------------------------------------------
    def _on_method(self, method) -> None:
        if method is None:             # the checked one clicked again
            self.method.set_value(self._method or "ship")
            return
        self._fill_resources()

    @property
    def _method(self) -> str:
        return self.method.value() or "ship"

    def _locations(self) -> list[dict]:
        method, system = self._method, self.system.value()
        return [l for l in self.data["locations"]
                if method in l["groups"] and (system is None or l["system"] == system)]

    def _fill_resources(self) -> None:
        if self.data is None:
            return
        method = self._method
        found = {p["res"] for l in self._locations() for i in l["groups"][method]
                 for p in self.data["rocks"][i["rock"]]["parts"]}
        current = self.resource.currentData()
        self.resource.blockSignals(True)
        self.resource.clear()
        self.resource.addItem("Any ore", None)
        for res in sorted(found, key=lambda r: self.data["resources"][r]["name"]):
            self.resource.addItem(self.data["resources"][res]["name"], res)
        self.resource.setCurrentIndex(max(self.resource.findData(current), 0))
        self.resource.blockSignals(False)
        self.resource._mark()
        self._render()

    def _share(self, loc: dict, res: str) -> float:
        """% of this method's spawns at loc that are rocks carrying res."""
        rocks = self.data["rocks"]
        return sum(i["chance"] for i in loc["groups"][self._method]
                   if any(p["res"] == res for p in rocks[i["rock"]]["parts"]))

    def _quality(self, loc: dict, res: str) -> int | None:
        """The best average quality res comes in at loc (over its rocks there)."""
        rocks, quality = self.data["rocks"], self.data["quality"]
        best = None
        for i in loc["groups"][self._method]:
            for part in rocks[i["rock"]]["parts"]:
                if part["res"] == res:
                    q = quality.get(res, {}).get(loc["system"], {}).get(str(part["scale"]))
                    if q is not None and (best is None or q["avg"] > best):
                        best = q["avg"]
        return best

    def _render(self) -> None:
        if self.data is None:
            return
        locs = {l["id"]: l for l in self._locations()}
        if self.location in locs:
            self._render_location(locs[self.location])
        else:
            self.location = None
            self._render_list(list(locs.values()))

    def _open(self, loc_id: str | None) -> None:
        self.location = loc_id
        self._render()
        self.scroll.verticalScrollBar().setValue(0)

    # -- page 1: places -----------------------------------------------------------------
    def _render_list(self, locs: list[dict]) -> None:
        res = self.resource.currentData()
        method = self._method
        if res is not None:
            locs = sorted((l for l in locs if self._share(l, res) > 0), key=lambda l: -self._share(l, res))
            name = self.data["resources"][res]["name"]
            self.count.setText(f"{len(locs)} places with {name} · " + ("near you, then " if self._near else "")
                               + "most first")
        else:
            self.count.setText(f"{len(locs)} places · pick an ore for the best ones")
        near = {lid: i for i, lid in enumerate(self._near)}
        here = mining.place_from_log(self._here)[1]
        if near:
            # Following the game: where you are, then the places around it (stable sort).
            locs.sort(key=lambda l: near.get(l["id"], len(near)))
        body = self._new_page()
        if not locs:
            body.addWidget(kit.EmptyState("Not found here", "This ore doesn't spawn in this system with this "
                                          "mining method. Try All systems or another method."), stretch=1)
            return
        systems = {s["id"]: s["name"] for s in self.data["systems"]}
        show_system = self.system.value() is None
        top = max((self._share(l, res) for l in locs), default=0) if res is not None else 0
        frame, rows = _rows_panel()
        for loc in locs:
            row = _Clickable(objectName="PanelRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 10, 6)
            h.setSpacing(8)
            col = QVBoxLayout()
            col.setSpacing(1)
            title = QHBoxLayout()
            title.setSpacing(6)
            title.addWidget(label(loc["name"], "RowName"))
            if loc["id"] in near:
                title.addWidget(Badge("You're here" if loc["id"] == here else "Near you", "info"))
            if show_system and loc["system"] in systems:
                title.addWidget(Badge(systems[loc["system"]], hue=loc["system"]))
            title.addStretch(1)
            col.addLayout(title)
            kind = KIND_LABELS.get(loc["kind"], loc["kind"].title())
            if loc.get("parent") and loc["kind"] in ("moon", "lagrange"):
                kind += f" · {loc['parent']}"
            col.addWidget(label(kind, "MutedText"))
            h.addLayout(col, stretch=1)
            if res is not None:
                share = self._share(loc, res)
                stats = QVBoxLayout()
                stats.setSpacing(1)
                line = QHBoxLayout()
                line.setSpacing(6)
                line.addWidget(kit.Bar(share / top if top else 0, PALETTE["success"], 44, 5), alignment=Qt.AlignVCenter)
                line.addWidget(label(f"<b>{_pct(share)}</b> of rocks", "ChanceText", rich=True))
                stats.addLayout(line)
                q = self._quality(loc, res)
                if q is not None:
                    stats.addWidget(label(f"Q ≈ {q}", "MutedText", align=Qt.AlignRight))
                h.addLayout(stats)
            else:
                n = len(loc["groups"][method])
                h.addWidget(label(f"{n} rock type{'s' if n != 1 else ''}", "MutedText"))
            h.addWidget(label("›", "MutedText"))
            # Next event loop turn: the click handler finishes before the page is replaced.
            row.clicked.connect(lambda lid=loc["id"]: QTimer.singleShot(0, lambda: self._open(lid)))
            rows.addWidget(row)
        body.addWidget(frame)
        body.addStretch(1)

    # -- page 2: one place's rocks ------------------------------------------------------
    def _render_location(self, loc: dict) -> None:
        res = self.resource.currentData()
        method = self._method
        self.count.setText(f"{loc['name']} · {mining.METHOD_LABELS[method]} mining")
        body = self._new_page()
        top = QHBoxLayout()
        top.addWidget(kit.button("‹ All places", "ghost", lambda: QTimer.singleShot(0, lambda: self._open(None))))
        top.addStretch(1)
        body.addLayout(top)
        body.addWidget(LocationCard(loc, method, self.data, [res] if res else [], True, compact=True))
        body.addWidget(label("RS: radar signature of one rock (×2, ×3: a group). Q: average quality, the "
                             "bars its odds (estimated from the game's settings).", "MutedText", wrap=True))
        body.addStretch(1)


# -- Salvage ------------------------------------------------------------------------

class SalvagePanel(_FollowMixin, _ScrollPanel):
    """Pick a claim difficulty → its ships, most valuable first (the
    launcher's rows, compact): click one for its fee, what comes off it and
    the cargo. Following the game, an active salvage claim opens its
    difficulty with its ship open and marked. Uses the prices downloaded by
    the launcher's Salvage Claims view (no network access from the overlay)."""

    FOLLOW_TOOL = "salvage"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game: dict | None = None
        self.opened: str | None = None       # stem of the open ship
        self._rows: dict[str, ShipRowWidget] = {}
        self._claim: dict | None = None      # following: the active claim, with its ship's stem
        self._applied = None                 # the claim number last applied
        v = self.layout_
        self.tier = kit.Segmented([], None, compact=True)
        self.tier.changed.connect(self._on_tier)
        v.addWidget(self.tier, alignment=Qt.AlignLeft)
        self.count = label("", "ResultCount")
        v.addWidget(self.count)
        self._add_scroll()
        self._task = _Task(self)
        self._task.done.connect(self._on_loaded)
        self._task.failed.connect(lambda msg: self._message(msg, "Couldn't read the game data"))
        self._message("Loading salvage data…")
        self._init_follow(v, 0)

    def activate(self) -> None:
        self._follow_start()
        if self.game is None:
            root = _channel_root()
            if root is None:
                self._message("Set up your Star Citizen folder in the launcher first.", "No game folder")
                return
            self._task.run(lambda: _cached_game("salvage", root), "salvage data")
        else:
            self._game_changed(force=True)

    # -- following: the claim you're on ----------------------------------------------
    def _active_claim(self) -> dict | None:
        claims = []
        for m in self._feed().tracker.active_missions():
            claim = salvage.claim_of(m.title, m.contract)
            if claim:
                claims.append((m.accepted.timestamp() if m.accepted else 0, claim))
        return max(claims, key=lambda c: c[0])[1] if claims else None

    def _apply_game(self) -> None:
        if self.game is None:
            return
        claim = self._active_claim()
        if claim is not None:
            if not any(t["id"] == claim["tier"] for t in self.game["tiers"]):
                claim["tier"] = self._tier
            claim["stem"] = salvage.claim_ship(self.game, claim["tier"], claim["ship"])
        key = (claim["number"], claim["stem"], claim["tier"]) if claim else None
        if key == self._applied:
            return                        # nothing new (the log moves on all the time)
        self._claim, self._applied = claim, key
        if claim is None:
            self._fill_ships()            # drop the mark
            return
        self._tier = claim["tier"]
        self.tier.set_value(self._tier)
        self.opened = claim["stem"]
        self._fill_ships()
        item = self._rows.get(self.opened)
        if item is not None:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(item.header, 0, 0))

    def _unfollow(self) -> None:
        self._claim, self._applied = None, None
        self._fill_ships()

    def _follow_text(self) -> str:
        c = self._claim
        if c is None:
            return "Following your game · no salvage claim active"
        tier = next((t["label"] for t in self.game["tiers"] if t["id"] == c["tier"]), c["tier"]) if self.game else ""
        ship = html.escape(c["ship"]) + ("" if c.get("stem") else " (not in this list)")
        return f"Following your game · <b>Claim #{c['number']}</b> · {ship} · {tier}"

    def _on_loaded(self, game: dict) -> None:
        self.game = game
        self.sheet = salvage.load_sheet()
        uex = salvage.load_uex()
        self.prices = uex[1] if uex else {}
        self._tier = "Easy" if any(t["id"] == "Easy" for t in game["tiers"]) else game["tiers"][0]["id"]
        self.tier.set_options([(t["id"], t["label"]) for t in game["tiers"]], self._tier)
        self._applied = None
        self._fill_ships()
        self._game_changed(force=True)

    def _on_tier(self, tier) -> None:
        if tier is None:              # the checked one clicked again
            self.tier.set_value(self._tier)
            return
        self._tier = tier
        self._fill_ships()

    def _fill_ships(self) -> None:
        if self.game is None:
            return
        rows = salvage.build_rows(self.game, self._tier, self.sheet, self.prices)
        rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))
        tier = next((t for t in self.game["tiers"] if t["id"] == self._tier), None)
        count = f"{len(rows)} ship" + ("" if len(rows) == 1 else "s") + " · most valuable first"
        if tier:
            count += f" · {tier['size'].lower()} ships"
        self.count.setText(count)
        body = self._new_page()
        if self.sheet is None:
            notice = kit.Notice()
            notice.show_text("Prices aren't downloaded yet: open Salvage Claims in the launcher once.",
                             "warning", dismissible=False)
            body.addWidget(notice)
        best = max((r.net for r in rows if r.in_sheet), default=None)
        top = max((r.components_value + r.cargo_value for r in rows if r.in_sheet), default=0)
        frame, list_box = _rows_panel()
        self._rows = {}
        for row in rows:
            claim = self._claim if self.following() else None
            mine = claim is not None and claim.get("stem") == row.stem and claim["tier"] == self._tier
            w = ShipRowWidget(row, False, best=row.in_sheet and row.net == best and row.net > 0, top=top,
                              compact=True, flag=f"Your claim #{claim['number']}" if mine else "")
            w.toggled.connect(self._toggled)
            self._rows[row.stem] = w
            list_box.addWidget(w)
        body.addWidget(frame)
        body.addStretch(1)
        if self.opened in self._rows:
            self._rows[self.opened]._set_open(True)
        else:
            self.opened = None

    def _toggled(self, stem: str, on: bool) -> None:
        """Accordion: one ship open at a time."""
        if not on:
            if stem == self.opened:
                self.opened = None
            return
        previous, self.opened = self.opened, stem
        if previous in self._rows and previous != stem:
            self._rows[previous]._set_open(False)
            self.opened = stem
        item = self._rows[stem]
        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(item.header, 0, 0))
