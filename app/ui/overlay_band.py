"""The overlay's horizontal layout, the band (#74): each tool's view made for
a wide, short strip (direction D, "Columns Band", in the mockups).

Every column is glanceable and never scrolls: a title and the few lines that
fit the band's height (more lines at the tall preset). What doesn't fit opens
below the band on demand ("all ▾", "Details ▾", a ship's breakdown), and
Maps' guide is a drawer that pulls out under it. The data and following
logic is the vertical panels' (overlay_live, overlay_panels): each band
view subclasses its panel and only builds its own widgets.
"""

from __future__ import annotations

import html
import time

from PySide6.QtCore import QEasingCurve, QRect, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import mining
from app.stats import pretty
from app.theme import PALETTE
from app.ui import kit, overlay_live as live
from app.ui.kit import Badge
from app.ui.mining_view import _pct
from app.ui.overlay_panels import MapsPanel, MiningPanel, SalvagePanel, _combo, _overlay_of
from app.ui.salvage_view import ShipRowWidget

COL_MIN = 170            # a column's least width; below the sum of these, columns step aside
ROW_H = 19               # one line in a column
TITLE_H = 16             # a column's title line
COMBO_H = 30             # a list's button in a column
DROP_WIDTH = 420         # a list or details dropped below the band
DROP_MAX_H = 380
DRAWER_SHARE = 0.62      # Maps' drawer: this much of the screen's height
DRAWER_MS = 170          # how long it takes to pull out


# -- small parts ------------------------------------------------------------------------
class Line(QLabel):
    """One line that never wraps: what doesn't fit ends in "…"."""

    def __init__(self, text: str = "", name: str = "BandLine", parent=None):
        super().__init__(parent, objectName=name)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(ROW_H)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        super().setText(text)
        self.update()

    def text(self) -> str:
        return self._full

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(self.font()).elidedText(self._full, Qt.ElideRight, r.width()))


class Clickable(QFrame):
    clicked = Signal()

    def __init__(self, name: str = "BandRow"):
        super().__init__(objectName=name)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        hit = event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint())
        super().mouseReleaseEvent(event)
        if hit:
            QTimer.singleShot(0, self.clicked.emit)     # after the click: it may rebuild this row


def _fixed(text: str, name: str) -> QLabel:
    lbl = QLabel(text, objectName=name)
    lbl.setFixedHeight(ROW_H)
    return lbl


def _row(*parts, name: str = "BandRow", click=None, selected: bool = False, height: int = ROW_H) -> QFrame:
    """A row of parts; (text, style) pairs become labels, the first one an
    eliding line that takes the room."""
    row = Clickable(name) if click else QFrame(objectName=name)
    if click:
        row.clicked.connect(click)
    row.setProperty("selected", selected)
    row.setFixedHeight(height)
    h = QHBoxLayout(row)
    h.setContentsMargins(4 if click else 0, 0, 4 if click else 0, 0)
    h.setSpacing(7)
    line_done = False
    for part in parts:
        if part is None:
            continue
        stretch = 0
        if isinstance(part, tuple):        # the first text takes the room and ends in "…" if it must
            if line_done:
                part = _fixed(part[0], part[1])
            else:
                part, line_done, stretch = Line(part[0], part[1]), True, 1
        h.addWidget(part, stretch=stretch)
    return row


def _bar(share: float, colour: str, width: int = 0) -> QWidget:
    bar = kit.Bar(max(0.0, min(1.0, share)), colour, width or 60, 5)
    if not width:
        bar.setMinimumWidth(30)
        bar.setMaximumWidth(16777215)
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return bar


def _short(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 10_000:
        return f"{value / 1000:.0f}k"
    return f"{value:,.0f}"


def _big(value: str, unit: str = "", amber: bool = False) -> QWidget:
    w = QWidget()
    w.setFixedHeight(30)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(5)
    h.addWidget(QLabel(value, objectName="BandBigAmber" if amber else "BandBig"), alignment=Qt.AlignBottom)
    if unit:
        h.addWidget(QLabel(unit, objectName="BandMuted"), alignment=Qt.AlignBottom)
    h.addStretch(1)
    return w


# -- columns ------------------------------------------------------------------------------
class BandColumn(QFrame):
    """A titled column: fixed controls on top (`head`, kept across renders so an
    open list survives one), then a body rebuilt by body(). It never scrolls:
    rows() says how many lines fit."""

    def __init__(self, title: str = "", weight: int = 2, priority: int = 1, min_width: int = COL_MIN):
        super().__init__(objectName="BandColumn")
        self.weight, self.priority, self.min_width = weight, priority, min_width
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 7, 10, 6)
        v.setSpacing(4)
        self.title = QLabel(title, objectName="BandColLabel")
        self.title.setFixedHeight(TITLE_H - 4)
        self.title.setVisible(bool(title))
        v.addWidget(self.title)
        self.head = QVBoxLayout()
        self.head.setSpacing(4)
        v.addLayout(self.head)
        self._holder = QVBoxLayout()
        self._holder.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self._holder, stretch=1)
        self._body: QWidget | None = None

    def set_title(self, text: str) -> None:
        self.title.setText(text)
        self.title.setVisible(bool(text))

    def body(self) -> QVBoxLayout:
        if self._body is not None:
            self._holder.removeWidget(self._body)
            self._body.hide()
            self._body.deleteLater()       # not at once: a click in it may have caused this
        self._body = QWidget(objectName="BandBodyPage")
        v = QVBoxLayout(self._body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self._holder.addWidget(self._body)
        return v

    def finish_init(self) -> None:
        """An empty body that takes the room, so the head sits under the title."""
        self.body().addStretch(1)

    def rows(self) -> int:
        """How many lines fit under the title and the head."""
        head = sum(self.head.itemAt(i).widget().height() + 4 for i in range(self.head.count())
                   if self.head.itemAt(i).widget() is not None and not self.head.itemAt(i).widget().isHidden())
        inner = self.height() - 13 - (TITLE_H if not self.title.isHidden() else 0) - head
        return max(1, inner // (ROW_H + 1))


class BandColumns(QWidget):
    """Columns side by side, sized by weight. Too narrow for all of them at
    their least width: the lowest-priority ones step aside (highest number,
    rightmost first)."""

    def __init__(self, columns: list[BandColumn]):
        super().__init__()
        self.columns = columns
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        for c in columns:
            h.addWidget(c, stretch=c.weight)
            if c._body is None and c._holder.count() == 0:
                c.finish_init()
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        shown = list(self.columns)
        while len(shown) > 1 and sum(c.min_width for c in shown) > max(self.width(), 1):
            shown.remove(max(shown, key=lambda c: (c.priority, self.columns.index(c))))
        first = True
        for c in self.columns:
            c.setVisible(c in shown)
            if c in shown:
                c.setProperty("first", first)
                c.style().unpolish(c)
                c.style().polish(c)
                first = False


class DropList(QFrame):
    """What opens below the band: a title and rows, scrolling inside itself if long."""

    def __init__(self, title: str):
        super().__init__(objectName="BandDrop")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 6, 8)
        v.setSpacing(4)
        v.addWidget(QLabel(title, objectName="BandColLabel"))
        self.scroll = QScrollArea(objectName="InspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget(objectName="Inspector")
        self.rows = QVBoxLayout(page)
        self.rows.setContentsMargins(0, 0, 8, 0)
        self.rows.setSpacing(1)
        self.scroll.setWidget(page)
        v.addWidget(self.scroll, stretch=1)

    def want_height(self) -> int:
        self.rows.activate()
        content = self.scroll.widget().sizeHint().height()
        return min(DROP_MAX_H, content + 16 + TITLE_H + 8)


def _drop(anchor: QWidget, drop: QWidget, height: int, width: int = DROP_WIDTH) -> None:
    win = _overlay_of(anchor)
    if win is not None:
        win.show_drop(drop, height, anchor=anchor, width=width)


def _close_drop(widget: QWidget) -> None:
    win = _overlay_of(widget)
    if win is not None:
        win.close_drop()


class _BandBody:
    """Mixin: swaps a vertical panel's page for the band's columns, plus a
    full-width message (loading, live log off, nothing yet). Renders again
    when the band's size changes (a column shows as many lines as fit)."""

    def _band_setup(self, columns: list[BandColumn]) -> None:
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setObjectName("BandBody")
        self.columns = BandColumns(columns)
        self._msg_box = QWidget()
        mv = QVBoxLayout(self._msg_box)
        mv.setContentsMargins(16, 8, 16, 8)
        mv.addStretch(1)
        self._msg_title = QLabel("", objectName="BandColLabel", alignment=Qt.AlignCenter)
        mv.addWidget(self._msg_title)
        self._msg_text = QLabel("", objectName="BandText", alignment=Qt.AlignCenter)
        self._msg_text.setWordWrap(True)
        mv.addWidget(self._msg_text)
        self._msg_btn = QPushButton("", objectName="MiniButton")
        self._msg_btn.setCursor(Qt.PointingHandCursor)
        self._msg_slot = None
        self._msg_btn.clicked.connect(lambda: self._msg_slot and self._msg_slot())
        mv.addWidget(self._msg_btn, alignment=Qt.AlignHCenter)
        mv.addStretch(1)
        self._band_stack = QStackedWidget()
        self._band_stack.addWidget(self.columns)
        self._band_stack.addWidget(self._msg_box)
        layout.addWidget(self._band_stack)
        self._resize_timer = QTimer(self, singleShot=True, interval=60, timeout=self._band_render)
        self._last_size = None

    def show_message(self, text: str, title: str = "", button: tuple[str, object] | None = None) -> None:
        self._msg_title.setText(title)
        self._msg_title.setVisible(bool(title))
        self._msg_text.setText(text)
        self._msg_btn.setVisible(button is not None)
        if button:
            self._msg_btn.setText(button[0])
            self._msg_slot = button[1]
        self._band_stack.setCurrentWidget(self._msg_box)

    def show_columns(self) -> None:
        self._band_stack.setCurrentWidget(self.columns)

    def _message(self, text: str, title: str = "") -> None:
        if hasattr(self, "_band_stack"):     # (the vertical panel's __init__ calls it before there is one)
            self.show_message(text.replace("\n", " "), title)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_resize_timer") and event.size() != self._last_size:
            self._last_size = event.size()
            self._resize_timer.start()

    def _band_render(self) -> None:
        raise NotImplementedError

    def summary(self) -> str:
        """One line for the folded band's header (rich text)."""
        return ""


# -- live log: what Missions and Session share ----------------------------------------------
class _LiveBand(_BandBody):
    def _render(self) -> None:
        self._build()

    def _band_render(self) -> None:
        if self.isVisible():
            self._build()

    def _state_message(self) -> bool:
        f = live.feed()
        if f.state == "disabled":
            self.show_message("The live log reader is off. Turn on LIVE LOG to follow your missions and "
                              "session here.", button=("Turn on live log", f.request_enable))
            return True
        if f.state in ("off", "waiting") and not f.tracker.session:
            self.show_message("Waiting for Star Citizen… This fills in as soon as the game is running.")
            return True
        self.show_columns()
        return False


# -- Missions -------------------------------------------------------------------------------
class MissionsBand(_LiveBand, live.MissionsPanel):
    """Mission (a list switches it) · objectives (the current one and its
    neighbours) · reward or outcome · possible blueprints, new first · time on
    it, with the details a click away."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_mission = BandColumn("MISSION", 3, 1, 220)
        self.c_objectives = BandColumn("OBJECTIVES", 3, 1, 230)
        self.c_reward = BandColumn("REWARD", 2, 2, 150)
        self.c_blueprints = BandColumn("POSSIBLE BLUEPRINTS", 2, 2, 170)
        self.c_time = BandColumn("ON IT", 2, 3, 140)
        self.pick = _combo()
        self.pick.setFixedHeight(COMBO_H)
        self.pick.activated.connect(self._on_pick)
        self.c_mission.head.addWidget(self.pick)
        self._band_setup([self.c_mission, self.c_objectives, self.c_reward, self.c_blueprints, self.c_time])
        self._ids: list[str] = []
        self._picked: str | None = None
        self._last_tracked: str | None = None

    def _on_pick(self, index: int) -> None:
        if 0 <= index < len(self._ids):
            self._picked = self._ids[index]
            self._build()

    def _missions(self):
        tr = live.feed().tracker
        rewards = {m.id: age for m in tr.missions.values() if (age := live._reward_age(m)) is not None}
        active = tr.active_missions()
        tracked = self._tracked(active)
        shown = [m for m in tr.missions.values() if m.active or m.id in rewards]
        shown.sort(key=lambda m: (m is not tracked, -live._activity(m).timestamp()))
        finished = sorted((m for m in tr.finished_missions() if m.id not in rewards),
                          key=lambda m: m.outcome != "Complete")
        return shown + finished, active, tracked, rewards

    def summary(self) -> str:
        f = live.feed()
        if f.state == "disabled":
            return "Live log off"
        missions, _active, tracked, _r = self._missions()
        m = tracked or next((x for x in missions if x.active), None)
        if m is None:
            return "No active mission"
        cur = m.current_objective
        text = html.escape(cur.text if cur else live._mission_title(m, f.contract(m)))
        return f"<span style='color:{PALETTE['accent']}'>▶</span> {text} · <b>{live._ago(m.accepted)}</b>"

    def _build(self) -> None:
        if self._state_message():
            return
        f = live.feed()
        tr = f.tracker
        owned = ({live.blueprint_key(n) for n in f.owned_for(tr.channel)}
                 | {live.blueprint_key(n) for _t, n, _m in tr.blueprints})
        missions, active, tracked, rewards = self._missions()
        self._update_flash(tracked)
        if not missions:
            self.show_message("Accept a contract and it shows up here.", "NO MISSIONS THIS SESSION")
            return
        if tracked is not None and tracked.id != self._last_tracked:
            self._last_tracked, self._picked = tracked.id, None      # a newly tracked one takes over
        ids = [m.id for m in missions]
        if self._picked not in ids:
            self._picked = None
        m = next(x for x in missions if x.id == (self._picked or ids[0]))
        info = f.contract(m)

        lst = getattr(self.pick, "_list", None)
        if lst is None or not lst.isVisible():
            self.pick.blockSignals(True)
            self.pick.clear()
            for x in missions:
                mark = "▶ " if x is tracked else ("✓ " if x.outcome == "Complete" else "✕ " if not x.active else "")
                self.pick.addItem(mark + live._mission_title(x, f.contract(x)))
            self.pick.setCurrentIndex(ids.index(m.id))
            self.pick.blockSignals(False)
        self._ids = ids
        n_active = len(active)
        self.c_mission.set_title(f"ACTIVE · {n_active}" + (f" · {len(missions) - n_active} FINISHED"
                                                            if len(missions) > n_active else ""))
        state = ("reward" if m.id in rewards else "tracked" if m is tracked else
                 "" if m.active else "done" if m.outcome == "Complete" else "failed")
        self.c_mission.setProperty("state", state)
        self.c_mission.setProperty("flash", m.id in self._flash_until)
        self.c_mission.style().unpolish(self.c_mission)
        self.c_mission.style().polish(self.c_mission)

        # Mission: who, what kind, where.
        v = self.c_mission.body()
        kind = (info or {}).get("type") or ""
        v.addWidget(_row((" · ".join(x for x in (kind, live._contractor(m, info)) if x), "BandSecondary")))
        where = list(dict.fromkeys((info or {}).get("systems", []) + (info or {}).get("locations", [])))
        if where and self.c_mission.rows() > 1:
            v.addWidget(_row((" · ".join(where), "BandMuted")))
        v.addStretch(1)

        # Objectives: the current one, the one before it, and those after, as many as fit.
        objectives = m.visible_objectives
        current = m.current_objective
        done = sum(1 for o in objectives if o.done)
        self.c_objectives.set_title(f"OBJECTIVES · {done}/{len(objectives)}" if objectives else "OBJECTIVES")
        v = self.c_objectives.body()
        fit = self.c_objectives.rows()
        if not objectives:
            v.addWidget(_row(("None in the log yet", "BandMuted")))
        else:
            at = objectives.index(current) if current in objectives else len(objectives) - 1
            start = max(0, min(at - 1, len(objectives) - fit))
            for o in objectives[start:start + fit]:
                if o is current and m.active:
                    v.addWidget(_row(("▶  " + o.text, "BandCurrent")))
                else:
                    v.addWidget(_row((("✓  " if o.done else "○  ") + o.text, "BandMuted" if o.done else "BandLine")))
        v.addStretch(1)

        # Reward: the reputation large, the rest under it; how it ended.
        v = self.c_reward.body()
        rep = m.rep if m.rep is not None else (info or {}).get("rep")
        v.addWidget(_big(f"+{rep:,}" if rep else "—", "rep" if rep else ""))
        extra = [c.text() for c in live._rewards(m, info) if not c.text().endswith(" rep")]
        if m.outcome == "Complete":
            if m.blueprints:
                after = ("Blueprint: " + ", ".join(m.blueprints), "BandGood")
            elif rewards.get(m.id, 1e9) < live.BLUEPRINT_WINDOW_SECONDS and (
                    m.blueprint_chance or (info or {}).get("blueprints")):
                after = ("checking blueprint…", "BandMuted")
            else:
                after = ("no blueprint", "BandMuted")
            v.addWidget(_row(live._chip("COMPLETE", "good"), after))
        elif not m.active:
            v.addWidget(_row(live._chip(live.OUTCOMES.get(m.outcome, m.outcome).upper(), "bad"), ("", "BandMuted")))
        elif extra:
            v.addWidget(_row((" · ".join(extra), "BandSecondary")))
        v.addStretch(1)

        # Possible blueprints: the new ones (what you'd run it for), then how many you have.
        possible = live._possible_blueprints(info, owned)
        v = self.c_blueprints.body()
        if possible:
            new = [n for n, have in possible if not have]
            have = len(possible) - len(new)
            chance = max((pool.get("chance") or 0) for pool in info["blueprints"])
            self.c_blueprints.set_title(f"POSSIBLE BLUEPRINTS · {len(new)} NEW")
            fit = self.c_blueprints.rows()
            shown = new if len(new) <= fit - 1 else new[:fit - 1]
            for name in shown:
                v.addWidget(_row(("＋ " + name, "BandGood")))
            rest = len(new) - len(shown)
            tail = " · ".join(x for x in ((f"+{rest} more" if rest else ""), (f"✓ {have} you have" if have else ""),
                                          (f"{chance:.0%} chance" if chance else "")) if x)
            more = rest or have
            v.addWidget(_row((tail, "BandMuted"), ("all ▾", "BandLink") if more else None,
                             click=(lambda: self._blueprints_drop(possible, chance)) if more else None))
        else:
            self.c_blueprints.set_title("POSSIBLE BLUEPRINTS")
            v.addWidget(_row(("Blueprint chance" if m.blueprint_chance else
                              "None" if info else "Loading…" if f.contracts is None else
                              "Not in the mission database", "BandMuted")))
        v.addStretch(1)

        # Time: on it for…, the limit; the details a click away.
        v = self.c_time.body()
        if m.active:
            self.c_time.set_title("ON IT")
            v.addWidget(_big(live._ago(m.accepted), amber=True))
            limit = (info or {}).get("deadline_minutes")
            v.addWidget(_row((f"limit {live._minutes(limit)}" if limit else "no time limit", "BandMuted")))
        else:
            self.c_time.set_title("ENDED")
            v.addWidget(_big(live._clock(m.ended)))
        if live._detail_rows(info) or (info or {}).get("description"):
            v.addWidget(_row(("Details ▾", "BandLink"), click=lambda: self._details_drop(m, info)))
        v.addStretch(1)

        waits = []
        for age in rewards.values():
            if age < live.BLUEPRINT_WINDOW_SECONDS:
                waits.append(live.BLUEPRINT_WINDOW_SECONDS - age)
            waits.append(live.REWARD_SECONDS - age)
        waits += [t - time.monotonic() for t in self._flash_until.values()]
        if waits:
            self._expire.start(max(50, int(min(waits) * 1000) + 50))

    def _blueprints_drop(self, possible, chance) -> None:
        drop = DropList("POSSIBLE BLUEPRINTS · ONE OF THESE ON COMPLETION"
                        + (f" ({chance:.0%} CHANCE)" if chance else ""))
        for name, have in sorted(possible, key=lambda p: p[1]):
            drop.rows.addWidget(_row(("✓  " + name if have else "＋  " + name, "BandMuted" if have else "BandGood")))
        drop.rows.addStretch(1)
        _drop(self.c_blueprints, drop, drop.want_height())

    def _details_drop(self, m, info) -> None:
        drop = DropList(live._mission_title(m, info).upper())
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        for i, row in enumerate(live._detail_rows(info)):
            grid.addWidget(QLabel(row[0], objectName="BandMuted"), i, 0, alignment=Qt.AlignTop)
            value = QLabel(row[1], objectName="BandText")
            value.setWordWrap(True)
            grid.addWidget(value, i, 1)
        drop.rows.addLayout(grid)
        if (info or {}).get("description"):
            text = QLabel(info["description"][:1500], objectName="BandSecondary")
            text.setWordWrap(True)
            drop.rows.addWidget(text)
        drop.rows.addStretch(1)
        _drop(self.c_time, drop, DROP_MAX_H, width=520)


# -- Session --------------------------------------------------------------------------------
class SessionBand(_LiveBand, live.SessionPanel):
    """Now · six numbers · blueprints · recent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_now = BandColumn("NOW", 2, 1, 170)
        self.c_numbers = BandColumn("", 4, 1, 300)
        self.c_blueprints = BandColumn("BLUEPRINTS", 2, 2, 170)
        self.c_recent = BandColumn("RECENT", 3, 2, 200)
        self._band_setup([self.c_now, self.c_numbers, self.c_blueprints, self.c_recent])

    def summary(self) -> str:
        tr = live.feed().tracker
        parts = [tr.ship or "", pretty(tr.location) if tr.location else ""]
        return html.escape(" · ".join(p for p in parts if p))

    def _build(self) -> None:
        if self._state_message():
            return
        tr = live.feed().tracker
        self.c_now.set_title("NOW" if live.feed().state == "reading" else "LAST SESSION")
        v = self.c_now.body()
        v.addWidget(_row((tr.ship or "No ship", "BandStrong")))
        v.addWidget(_row((pretty(tr.location) if tr.location else "Location not known yet", "BandSecondary")))
        chip = None
        if tr.comm_down:
            chip = live._chip("COMMS DOWN", "bad")
        elif tr.monitored is not None:
            chip = live._chip("MONITORED" if tr.monitored else "UNMONITORED", "info" if tr.monitored else "bad")
        fit = self.c_now.rows()
        if chip is not None and fit >= 3:
            v.addWidget(_row(chip, ("", "BandMuted")))
        if tr.qt_target and fit >= 4:
            v.addWidget(_row((f"QT to {pretty(tr.qt_target)}", "BandMuted")))
        v.addStretch(1)

        v = self.c_numbers.body()
        playing = (tr.last_time - tr.started) if tr.started and tr.last_time else None
        numbers = [
            (f"{int(playing.total_seconds() // 3600)}:{int(playing.total_seconds() // 60 % 60):02d}"
             if playing else "—", "played", ""),
            (f"{tr.completed}" + (f" · {tr.failed}" if tr.failed else ""),
             "missions done" + (" · failed" if tr.failed else ""), ""),
            (f"+{tr.rep_earned:,}" if tr.rep_earned else "0", "rep earned", "good" if tr.rep_earned else ""),
            (str(tr.qt_jumps), "quantum jumps", ""),
            (str(tr.deaths) + (f" · {tr.incapacitated}" if tr.incapacitated else ""),
             "deaths" + (" · downed" if tr.incapacitated else ""), ""),
            (str(tr.refinery_done), "refinery orders", ""),
        ]
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        for i, (value, name, tone) in enumerate(numbers):
            cell = QVBoxLayout()
            cell.setSpacing(1)
            big = QLabel(value, objectName="BandNumber")
            if tone:
                big.setProperty("tone", tone)
            cell.addWidget(big)
            cell.addWidget(QLabel(name, objectName="BandMuted"))
            grid.addLayout(cell, i // 3, i % 3)
        v.addLayout(grid)
        v.addStretch(1)

        self.c_blueprints.set_title(f"BLUEPRINTS · {len(tr.blueprints)}")
        self._timed_list(self.c_blueprints, [(name, when, "BandGood", source)
                                             for when, name, source in reversed(tr.blueprints)],
                         "None received yet", "BLUEPRINTS THIS SESSION")
        self._timed_list(self.c_recent, [(item.text, item.time,
                                          {"good": "BandGood", "bad": "BandBad"}.get(item.kind, "BandLine"), "")
                                         for item in tr.feed], "Nothing yet", "RECENT")

    def _timed_list(self, col: BandColumn, items: list, empty: str, title: str) -> None:
        v = col.body()
        fit = col.rows()
        if not items:
            v.addWidget(_row((empty, "BandMuted")))
        shown = items if len(items) <= fit else items[:fit - 1]
        for text, when, name, _sub in shown:
            v.addWidget(_row((text, name), (live._clock(when), "BandTime")))
        if len(shown) < len(items):
            v.addWidget(_row((f"+{len(items) - len(shown)} more", "BandMuted"), ("all ▾", "BandLink"),
                             click=lambda: self._list_drop(col, items, title)))
        v.addStretch(1)

    def _list_drop(self, col, items, title) -> None:
        drop = DropList(title)
        for text, when, name, sub in items:
            drop.rows.addWidget(_row((text + (f"  ·  from {sub}" if sub else ""), name),
                                     (live._clock(when), "BandTime")))
        drop.rows.addStretch(1)
        _drop(col, drop, drop.want_height())


# -- Mining ---------------------------------------------------------------------------------
class MiningBand(_BandBody, MiningPanel):
    """Ore, method, system · the best places (near you first; a click picks
    one) · that place's rocks (a click picks one) · the picked rock's radar
    signature alone and in groups."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_find = BandColumn("", 2, 1, 190)
        self.c_places = BandColumn("BEST PLACES", 4, 1, 300)
        self.c_rocks = BandColumn("ROCKS", 3, 2, 210)
        self.c_groups = BandColumn("RADAR", 2, 3, 140)
        self.method_box = _combo()
        for key, text in mining.METHOD_LABELS.items():
            self.method_box.addItem(text, key)
        self.method_box.activated.connect(self._on_method_box)
        self.system_box = _combo()
        self.system_box.addItem("All", None)
        self.system_box.activated.connect(self._on_system_box)
        for w in (self.resource, self.method_box, self.system_box):
            w.setFixedHeight(COMBO_H)
            w.show()
        self.c_find.head.addWidget(self.resource)
        pair = QWidget()
        pair.setFixedHeight(COMBO_H)
        ph = QHBoxLayout(pair)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(4)
        ph.addWidget(self.method_box)
        ph.addWidget(self.system_box)
        self.c_find.head.addWidget(pair)
        self.rock: str | None = None
        self._band_setup([self.c_find, self.c_places, self.c_rocks, self.c_groups])
        self.show_message("Loading mining data…")

    def _on_method_box(self, i: int) -> None:
        self.method.set_value(self.method_box.itemData(i))
        self._on_method(self.method_box.itemData(i))

    def _on_system_box(self, i: int) -> None:
        self.system.set_value(self.system_box.itemData(i))
        self._fill_resources()

    def _on_loaded(self, data: dict) -> None:
        self.system_box.blockSignals(True)
        self.system_box.clear()
        self.system_box.addItem("All", None)
        for s in data["systems"]:
            self.system_box.addItem(s["name"], s["id"])
        self.system_box.blockSignals(False)
        self.show_columns()
        super()._on_loaded(data)

    def _band_render(self) -> None:
        self._render()

    def _open(self, loc_id) -> None:
        self.location, self.rock = loc_id, None
        _close_drop(self)
        self._render()

    def _places(self):
        locs = self._locations()
        res = self.resource.currentData()
        if res is not None:
            locs = sorted((l for l in locs if self._share(l, res) > 0), key=lambda l: -self._share(l, res))
        near = {lid: i for i, lid in enumerate(self._near)}
        if near:
            locs.sort(key=lambda l: near.get(l["id"], len(near)))
        return locs, res, near

    def summary(self) -> str:
        if self.data is None:
            return ""
        locs, res, _near = self._places()
        if not locs:
            return ""
        loc = next((l for l in locs if l["id"] == self.location), locs[0])
        ore = self.data["resources"][res]["name"] if res else "Any ore"
        return html.escape(f"{ore} · {loc['name']}" + (f" {_pct(self._share(loc, res))}" if res else ""))

    def _render(self) -> None:
        if self.data is None:
            return
        self.show_columns()
        for box, value in ((self.method_box, self._method), (self.system_box, self.system.value())):
            i = box.findData(value)
            if i >= 0 and box.currentIndex() != i:
                box.setCurrentIndex(i)
        locs, res, near = self._places()
        here = mining.place_from_log(self._here)[1]
        ids = [l["id"] for l in locs]
        if self.location not in ids:
            self.location, self.rock = (ids[0] if ids else None), None
        systems = {s["id"]: s["name"] for s in self.data["systems"]}
        show_system = self.system.value() is None
        top = max((self._share(l, res) for l in locs), default=0) if res is not None else 0
        self.c_places.set_title(f"{'BEST PLACES' if res else 'PLACES'} · {len(locs)}"
                                + (" · NEAR YOU FIRST" if near else "" if res else " · PICK AN ORE"))

        def place_row(loc, wide=False):
            chip = None
            if loc["id"] in near:
                chip = Badge("You're here" if loc["id"] == here else "Near", "info")
            elif show_system and loc["system"] in systems:
                chip = Badge(systems[loc["system"]], hue=loc["system"])
            picked = loc["id"] == self.location
            name = (loc["name"], "BandStrong" if picked else "BandLine")
            if res is not None:
                share = self._share(loc, res)
                q = self._quality(loc, res)
                return _row(name, chip, _bar(share / top if top else 0, PALETTE["success"], 90 if wide else 0),
                            (_pct(share), "BandNum"), (f"Q {q}" if q is not None else "", "BandMuted"),
                            click=lambda lid=loc["id"]: self._open(lid), selected=picked)
            n = len(loc["groups"][self._method])
            return _row(name, chip, (f"{n} rock type{'s' if n != 1 else ''}", "BandMuted"),
                        click=lambda lid=loc["id"]: self._open(lid), selected=picked)

        v = self.c_places.body()
        fit = self.c_places.rows()
        if not locs:
            v.addWidget(_row(("Not found with this method here: try All systems or another method", "BandMuted")))
        shown = locs if len(locs) <= fit else locs[:fit - 1]
        if self.location and self.location not in [l["id"] for l in shown] and len(shown) > 1:
            shown = shown[:-1] + [next(l for l in locs if l["id"] == self.location)]   # the picked one stays in sight
        for loc in shown:
            v.addWidget(place_row(loc))
        if len(shown) < len(locs):
            def all_places():
                drop = DropList(self.c_places.title.text())
                for loc in locs:
                    drop.rows.addWidget(place_row(loc, wide=True))
                drop.rows.addStretch(1)
                _drop(self.c_places, drop, drop.want_height(), width=max(DROP_WIDTH, self.c_places.width()))
            v.addWidget(_row((f"+{len(locs) - len(shown)} more places", "BandMuted"), ("all ▾", "BandLink"),
                             click=all_places))
        v.addStretch(1)
        self._render_rocks(next((l for l in locs if l["id"] == self.location), None), res, show_system)

    def _render_rocks(self, loc, res, show_system) -> None:
        rocks_data, resources = self.data["rocks"], self.data["resources"]
        v = self.c_rocks.body()
        if loc is None:
            self.c_rocks.set_title("ROCKS")
            self.c_groups.body().addStretch(1)
            v.addStretch(1)
            return
        items = sorted(loc["groups"].get(self._method, []),
                       key=lambda i: (not any(p["res"] == res for p in rocks_data[i["rock"]]["parts"]), -i["chance"]))
        self.c_rocks.set_title(f"{loc['name'].upper()} · ROCKS")
        if self.rock not in [i["rock"] for i in items]:
            self.rock = items[0]["rock"] if items else None
        fit = self.c_rocks.rows()

        def rock_row(item):
            rock = rocks_data[item["rock"]]
            hit = res is not None and any(p["res"] == res for p in rock["parts"])
            style = "BandCurrent" if hit else ("BandMuted" if res is not None else "BandLine")
            return _row((rock["name"], style), (_pct(item["chance"]), "BandMuted"),
                        (f"RS {rock['signature']:,}" if rock.get("signature") else "", "BandNum"),
                        click=lambda r=item["rock"]: self._pick_rock(r), selected=item["rock"] == self.rock)

        shown = items if len(items) <= fit else items[:fit - 1]
        for item in shown:
            v.addWidget(rock_row(item))
        if len(shown) < len(items) or items:
            def composition():
                from app.ui.mining_view import LocationCard

                drop = DropList(f"{loc['name'].upper()} · ROCKS, COMPOSITION AND QUALITY")
                drop.rows.addWidget(LocationCard(loc, self._method, self.data, [res] if res else [], show_system,
                                                 compact=True))
                drop.rows.addStretch(1)
                _drop(self.c_rocks, drop, DROP_MAX_H, width=max(460, self.c_rocks.width()))
            more = len(items) - len(shown)
            if more or fit > len(shown):
                v.addWidget(_row(((f"+{more} more · " if more else "") + "what's in them", "BandMuted"),
                                 ("▾", "BandLink"), click=composition))
        v.addStretch(1)

        # The picked rock's radar signature, alone and in groups (a group scans as the sum).
        v = self.c_groups.body()
        item = next((i for i in items if i["rock"] == self.rock), None)
        rock = rocks_data[self.rock] if self.rock else None
        sig = (rock or {}).get("signature") or 0
        if rock is None or not sig:
            self.c_groups.set_title("RADAR")
            v.addWidget(_row(("No radar signature", "BandMuted")))
        else:
            sizes = ((item or {}).get("cluster") or {}).get("sizes") or []
            most = max((n for n, _ in sizes), default=1) if self._method == "ship" else 1
            self.c_groups.set_title(f"{rock['name'].upper()} · RADAR")
            fit = self.c_groups.rows()
            for n in range(1, min(most, fit) + 1):
                v.addWidget(_row((f"×{n}", "BandMuted"), (f"{sig * n:,}", "BandNumAmber" if n == 1 else "BandNum")))
        v.addStretch(1)

    def _pick_rock(self, rock: str) -> None:
        self.rock = rock
        self._render()


# -- Salvage --------------------------------------------------------------------------------
class SalvageBand(_BandBody, SalvagePanel):
    """Claim tier · the ships ranked by value (a click opens one's fee, parts
    and cargo below the band) · the claim you're on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_tier = BandColumn("CLAIM TIER", 2, 1, 180)
        self.c_ships = BandColumn("MOST VALUABLE FIRST", 6, 1, 320)
        self.c_claim = BandColumn("FOLLOWING", 2, 2, 170)
        self.tier_box = _combo()
        self.tier_box.setFixedHeight(COMBO_H)
        self.tier_box.activated.connect(self._on_tier_box)
        self.c_tier.head.addWidget(self.tier_box)
        self._ranked: list = []
        self._band_setup([self.c_tier, self.c_ships, self.c_claim])
        self.show_message("Loading salvage data…")

    def _on_tier_box(self, i: int) -> None:
        self.tier.set_value(self.tier_box.itemData(i))
        self._on_tier(self.tier_box.itemData(i))

    def _on_loaded(self, game: dict) -> None:
        self.tier_box.blockSignals(True)
        self.tier_box.clear()
        for t in game["tiers"]:
            self.tier_box.addItem(t["label"], t["id"])
        self.tier_box.blockSignals(False)
        super()._on_loaded(game)

    def _band_render(self) -> None:
        self._fill_ships()

    def summary(self) -> str:
        if self.game is None or not self._ranked:
            return ""
        c = self._claim if self.following() else None
        if c:
            return html.escape(f"Claim #{c['number']} · {c['ship']}")
        top = self._ranked[0]
        return html.escape(f"{self.tier_box.currentText()} · best: {top.name} {_short(top.net)}")

    def _fill_ships(self) -> None:
        if self.game is None:
            return
        from app import salvage

        self.show_columns()
        i = self.tier_box.findData(self._tier)
        if i >= 0 and self.tier_box.currentIndex() != i:
            self.tier_box.setCurrentIndex(i)
        rows = salvage.build_rows(self.game, self._tier, self.sheet, self.prices)
        rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))
        self._ranked = rows
        self._rows = {}
        tier = next((t for t in self.game["tiers"] if t["id"] == self._tier), None)
        claim = self._claim if self.following() else None
        mine = claim.get("stem") if claim is not None and claim["tier"] == self._tier else None
        top = max((r.net for r in rows if r.in_sheet), default=0)

        v = self.c_tier.body()
        v.addWidget(_row((f"{len(rows)} ships" + (f" · {tier['size'].lower()} hulls" if tier else ""), "BandMuted")))
        if self.sheet is None:
            v.addWidget(_row(("Prices not downloaded: open Salvage Claims in the launcher", "BandBad")))
        v.addStretch(1)

        def ship_row(rank, row, wide=False):
            colour = (PALETTE["accent"] if rank == 1 else PALETTE["info"] if row.stem == mine
                      else PALETTE["text_secondary"])
            name = row.name + (" · your claim" if row.stem == mine else "")
            return _row(_fixed(f"{rank}", "BandRank"),
                        (name, "BandInfo" if row.stem == mine else "BandStrong" if rank == 1 else "BandLine"),
                        _bar(row.net / top if top and row.in_sheet else 0, colour, 90 if wide else 0),
                        (_short(row.net) if row.in_sheet else "no data", "BandNumAmber" if rank == 1 else "BandNum"),
                        click=lambda r=row: self._breakdown(r))

        # Two columns of rows when there's room, as many as fit.
        v = self.c_ships.body()
        per_col = self.c_ships.rows()
        cols = 2 if self.c_ships.width() >= 560 else 1
        room = per_col * cols
        ranked = list(enumerate(rows, 1))
        shown = ranked if len(ranked) <= room else ranked[:room - 1]
        if mine and mine not in [r.stem for _n, r in shown] and len(shown) > 1:
            shown = shown[:-1] + [next(x for x in ranked if x[1].stem == mine)]      # your claim stays in sight
        cells = [ship_row(n, r) for n, r in shown]
        if len(shown) < len(ranked):
            def all_ships():
                drop = DropList(f"ALL {len(rows)} SHIPS · MOST VALUABLE FIRST · CLICK ONE FOR ITS BREAKDOWN")
                for n, r in ranked:
                    drop.rows.addWidget(ship_row(n, r, wide=True))
                drop.rows.addStretch(1)
                _drop(self.c_ships, drop, drop.want_height(), width=max(DROP_WIDTH, self.c_ships.width() // 2))
            cells.append(_row((f"+{len(ranked) - len(shown)} more ships", "BandMuted"), ("all ▾", "BandLink"),
                              click=all_ships))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(1)
        for k, cell in enumerate(cells):
            grid.addWidget(cell, k % per_col, k // per_col)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)
        v.addStretch(1)

        v = self.c_claim.body()
        if live.feed().state == "disabled":
            v.addWidget(_row(("Turn on LIVE LOG to follow your claim", "BandMuted")))
        elif claim is None:
            v.addWidget(_row(("No salvage claim active", "BandMuted")))
        else:
            v.addWidget(_row((f"Claim #{claim['number']}", "BandStrong")))
            tier_label = next((t["label"] for t in self.game["tiers"] if t["id"] == claim["tier"]), claim["tier"])
            v.addWidget(_row((f"{claim['ship']} · {tier_label}", "BandInfo")))
            row = next((r for r in rows if r.stem == claim.get("stem")), None)
            if row is not None:
                v.addWidget(_row(("Breakdown ▾", "BandLink"), click=lambda r=row: self._breakdown(r)))
        v.addStretch(1)

    def _breakdown(self, row) -> None:
        drop = DropList(f"{row.name.upper()} · FEE, PARTS AND CARGO")
        best = max((r.net for r in self._ranked if r.in_sheet), default=None)
        top = max((r.components_value + r.cargo_value for r in self._ranked if r.in_sheet), default=0)
        w = ShipRowWidget(row, True, best=row.in_sheet and row.net == best and row.net > 0, top=top, compact=True)
        w.header.setEnabled(False)          # no folding it away in the drop
        drop.rows.addWidget(w)
        drop.rows.addStretch(1)
        _drop(self.c_ships, drop, DROP_MAX_H, width=480)


# -- Maps -----------------------------------------------------------------------------------
class MapsDrawer(QFrame):
    """The guide, pulled out under the band: zoom, fit, push back."""

    def __init__(self, band: "MapsBand", frame: QWidget, buttons: list[QPushButton]):
        super().__init__(objectName="BandDrawer")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 10)
        v.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.title = QLabel("", objectName="BandColLabel")
        bar.addWidget(self.title, stretch=1)
        bar.addWidget(QLabel("drag to move along it · wheel to zoom · ", objectName="BandMuted"))
        for b in buttons:
            if b.text() == "⤢":
                b.hide()
                continue
            bar.addWidget(b)
            b.show()
        close = QPushButton("▲  Push back  ·  L", objectName="MiniButton")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(band.close_drawer)
        bar.addWidget(close)
        v.addLayout(bar)
        v.addWidget(frame, stretch=1)
        frame.show()


class _Preview(QWidget):
    """The top of the guide, filling the column; a click pulls the drawer out."""

    clicked = Signal()

    def __init__(self):
        super().__init__(objectName="BandPreview")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.pix: QPixmap | None = None
        self.note = "Loading the guide…"

    def set_pixmap(self, pix: QPixmap | None, note: str = "") -> None:
        self.pix, self.note = pix, note
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.rect().adjusted(6, 6, -6, -6)
        if self.pix is not None and not self.pix.isNull() and r.width() > 0:
            scaled = self.pix.scaledToWidth(r.width(), Qt.SmoothTransformation)
            p.drawPixmap(r.topLeft(), scaled, QRect(0, 0, r.width(), r.height()))
        else:
            p.setPen(QColor(PALETTE["text_muted"]))
            p.drawText(r, Qt.AlignCenter, self.note)
        tag = QRect(r.right() - 186, r.bottom() - 26, 182, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(16, 19, 23, 225))
        p.drawRoundedRect(tag, 5, 5)
        p.setPen(QColor(PALETTE["accent"]))
        p.drawText(tag, Qt.AlignCenter, "▾  Pull out the guide  ·  L")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            QTimer.singleShot(0, self.clicked.emit)


class MapsBand(_BandBody, MapsPanel):
    """Guide and page · the top of the guide (a click, or L, pulls it out
    below the band as a drawer) · guides for what you're doing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        frame = self.viewer.parentWidget()
        buttons = [b for b in self.findChildren(QPushButton, "MiniButton") if b.text() in ("−", "Fit", "+", "⤢")]
        self.c_guide = BandColumn("GUIDE", 2, 1, 220)
        self.c_preview = BandColumn("", 5, 1, 260)
        self.c_for = BandColumn("FOR WHAT YOU'RE DOING", 2, 2, 190)
        for w in (self.guide, self.page):
            w.setFixedHeight(COMBO_H)
            self.c_guide.head.addWidget(w)
        self.guide.show()
        self.preview = _Preview()
        self.preview.clicked.connect(self.toggle_drawer)
        self.c_preview.layout().setContentsMargins(0, 0, 0, 0)
        self.c_preview._holder.addWidget(self.preview)
        self._band_setup([self.c_guide, self.c_preview, self.c_for])
        self.drawer = MapsDrawer(self, frame, buttons)
        self.drawer.hide()
        self._anim = QVariantAnimation(self, duration=DRAWER_MS, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._drawer_step)
        self._drawer_rect = QRect()
        self._shape_pending = False
        self.page.setVisible(self.page.count() > 1)

    # -- the drawer ------------------------------------------------------------------------
    def drawer_open(self) -> bool:
        return self.drawer.isVisible()

    def toggle_drawer(self) -> None:
        if self.drawer_open():
            self.close_drawer()
        else:
            self.open_drawer()

    def open_drawer(self) -> None:
        win = _overlay_of(self)
        if win is None or self.drawer_open():
            return
        self._set_drawer_title()
        height = int(win._area().height() * DRAWER_SHARE)
        win.show_drop(self.drawer, height, width=win.width(), sticky=True)
        self._drawer_rect = self.drawer.geometry()
        self._anim.stop()
        self._anim.setStartValue(1)
        self._anim.setEndValue(self._drawer_rect.height())
        self._anim.start()
        QTimer.singleShot(DRAWER_MS + 20, lambda: self.viewer.fit_to("width"))

    def _drawer_step(self, h: int) -> None:
        r = self._drawer_rect
        win = _overlay_of(self)
        if win is not None and win._drop_up():
            self.drawer.setGeometry(r.x(), r.bottom() + 1 - h, r.width(), h)
        else:
            self.drawer.setGeometry(r.x(), r.y(), r.width(), h)

    def close_drawer(self) -> None:
        if self.drawer_open():
            self._anim.stop()
            _close_drop(self)

    def _toggle_large(self) -> None:
        self.toggle_drawer()

    def _set_drawer_title(self) -> None:
        self.drawer.title.setText(self.guide.currentText().upper()
                                  + (f" · {self.page.currentText().upper()}" if self.page.count() > 1 else ""))

    # -- following, guides -----------------------------------------------------------------
    def _band_render(self) -> None:
        self._render_for()

    def summary(self) -> str:
        return html.escape(self.guide.currentText())

    def _apply_game(self) -> None:
        super()._apply_game()
        self._render_for()

    def _unfollow(self) -> None:
        super()._unfollow()
        self._render_for()

    def _update_follow_line(self) -> None:
        super()._update_follow_line()
        self._render_for()

    def _render_for(self) -> None:
        if not hasattr(self, "c_for"):
            return
        v = self.c_for.body()
        suggested = [t for t in self._suggested if t != self.guide.currentText()] if self.following() else []
        fit = self.c_for.rows()
        if self.following() and self._suggested and not suggested:
            v.addWidget(_row(("This guide is for what you're doing", "BandGood")))
        elif not suggested:
            v.addWidget(_row(("No guide for your missions or location" if self.following()
                              else "Not following your game", "BandMuted")))
        for title in suggested[:max(1, fit - 1)]:
            short = title.split(" [", 1)[0].replace(" Companion Guide", "").replace(" Guide", "")
            v.addWidget(_row((short, "BandLink"), ("›", "BandMuted"), click=lambda t=title: self._open_guide(t)))
        v.addStretch(1)
        v.addWidget(_row(("Guides by Mr Kraken · all credit to the author", "BandMuted")))

    def _on_guide(self, index: int, shape: bool = False) -> None:
        super()._on_guide(index, False)
        self.page.setVisible(self.page.count() > 1)
        if hasattr(self, "c_guide"):
            self.c_guide.set_title("GUIDE" if self.page.count() <= 1 else f"GUIDE · {self.page.count()} PAGES")
            self._render_for()

    def _on_page(self, index: int, shape: bool = False) -> None:
        super()._on_page(index, False)
        if hasattr(self, "drawer"):
            self._set_drawer_title()

    def _on_loaded(self, url: str, data: bytes) -> None:
        super()._on_loaded(url, data)
        if url == self._wanted and hasattr(self, "preview"):
            pix = QPixmap()
            if pix.loadFromData(data):
                self.preview.set_pixmap(pix)

    def _msg(self, text: str) -> None:
        super()._msg(text)
        if text and hasattr(self, "preview"):
            self.preview.set_pixmap(None, text.replace("\n", " "))


BANDS = {"missions": MissionsBand, "session": SessionBand, "mining": MiningBand, "salvage": SalvageBand,
         "maps": MapsBand}


def make(tool: str) -> QWidget:
    return BANDS[tool]()
