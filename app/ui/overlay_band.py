"""The overlay's horizontal layout, the band (#74): each tool's view made for
a wide, short strip (direction D, "Columns Band", in the mockups).

Every column is glanceable and never scrolls: a title and the few lines that
fit the band's height (more lines at the tall preset), the ones you act on
first. Drops are only for extras you check and close: when a list is cut,
"+n more ▾" on its title line drops the whole list, the same rows (one rule,
one width, for every tool). Maps' guide is a drawer that pulls out under it. The data and following
logic is the vertical panels' (overlay_live, overlay_panels): each band
view subclasses its panel and only builds its own widgets.
"""

from __future__ import annotations

import html
import time

from PySide6.QtCore import QEasingCurve, QRect, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QFontMetrics, QPainter
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

COL_MIN = 170            # a column's least width; below the sum of these, columns step aside
ROW_H = 19               # one line in a column
TITLE_H = 16             # a column's title line
COMBO_H = 30             # a list's button in a column
DROP_WIDTH = 520         # anything dropped below the band (one width for all)
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
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.title = QLabel(title, objectName="BandColLabel")
        self.title.setFixedHeight(TITLE_H - 4)
        self.title.setVisible(bool(title))
        top.addWidget(self.title, stretch=1)
        # "+n more ▾": on the title line, so it never takes a line of the list.
        self.more = Clickable("BandMore")
        self.more.setFixedHeight(TITLE_H - 4)
        mh = QHBoxLayout(self.more)
        mh.setContentsMargins(4, 0, 0, 0)
        self._more_text = QLabel("", objectName="BandLink")
        mh.addWidget(self._more_text)
        self.more.hide()
        self._more_cb = None
        self.more.clicked.connect(self._open_more)
        top.addWidget(self.more)
        v.addLayout(top)
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

    def set_more(self, text: str = "", callback=None) -> None:
        """The title line's link to the rest; no text: none."""
        self._more_text.setText(text)
        self._more_cb = callback
        self.more.setVisible(bool(text))

    def _open_more(self) -> None:
        if self._more_cb is not None:
            self._more_cb()

    def body(self) -> QVBoxLayout:
        self.set_more()
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


def _drop(anchor: QWidget, drop: QWidget, height: int) -> None:
    win = _overlay_of(anchor)
    if win is not None:
        win.show_drop(drop, height, anchor=anchor, width=DROP_WIDTH)


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


# -- one rule for lists ---------------------------------------------------------------------
def fill(col: BandColumn, rows: list, title: str, empty: str = "", reserve: int = 0) -> QVBoxLayout:
    """Puts `rows` (callables making a row) in `col`, as many as fit. If they
    don't all fit, "+n more ▾" on the column's title line drops every row,
    the same rows, nothing else. `reserve`: lines kept free for what the
    caller adds after them."""
    v = col.body()
    fit = max(1, col.rows() - reserve)
    if not rows and empty:
        v.addWidget(_row((empty, "BandMuted")))
    shown = rows[:fit]
    for make in shown:
        v.addWidget(make())
    if len(shown) < len(rows):
        col.set_more(f"+{len(rows) - len(shown)} more ▾", lambda: list_drop(col, rows, title))
    return v


def list_drop(col: BandColumn, rows: list, title: str) -> None:
    drop = DropList(title)
    for make in rows:
        drop.rows.addWidget(make())
    drop.rows.addStretch(1)
    _drop(col, drop, drop.want_height())


def _pair(name: str, value: str, style: str = "BandLine"):
    """A fact: its name muted, then the value (eliding)."""
    def make():
        row = QFrame(objectName="BandRow")
        row.setFixedHeight(ROW_H)
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lead = _fixed(name, "BandMuted")
        lead.setFixedWidth(64)
        h.addWidget(lead)
        h.addWidget(Line(value, style), stretch=1)
        return row
    return make


# -- Missions -------------------------------------------------------------------------------
class MissionsBand(_LiveBand, live.MissionsPanel):
    """What you need while you run it: which mission and how long you've
    been on it · the current objective, large, and what's next · where,
    cargo and the other facts · what it pays, the new blueprints first."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_mission = BandColumn("MISSION", 3, 1, 230)
        self.c_now = BandColumn("NOW", 4, 1, 260)
        self.c_facts = BandColumn("DETAILS", 3, 2, 210)
        self.c_pays = BandColumn("PAYS", 3, 2, 200)
        self.pick = _combo()
        self.pick.setFixedHeight(COMBO_H)
        self.pick.activated.connect(self._on_pick)
        self.c_mission.head.addWidget(self.pick)
        self._band_setup([self.c_mission, self.c_now, self.c_facts, self.c_pays])
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
        self.c_mission.set_title(f"MISSION · {n_active} ACTIVE"
                                 + (f" · {len(missions) - n_active} FINISHED" if len(missions) > n_active else ""))
        state = ("reward" if m.id in rewards else "tracked" if m is tracked else
                 "" if m.active else "done" if m.outcome == "Complete" else "failed")
        self.c_mission.setProperty("state", state)
        self.c_mission.setProperty("flash", m.id in self._flash_until)
        self.c_mission.style().unpolish(self.c_mission)
        self.c_mission.style().polish(self.c_mission)

        # Mission: who and what, how long you've been on it (and the limit).
        kind = (info or {}).get("type") or ""
        if m.active:
            limit = (info or {}).get("deadline_minutes")
            status = lambda: _row(_fixed(f"on it {live._ago(m.accepted)}", "BandNumAmber"),
                                  (f"· limit {live._minutes(limit)}" if limit else "· no time limit", "BandMuted"))
        elif m.outcome == "Complete":
            status = lambda: _row(live._chip("COMPLETE", "good"), (live._clock(m.ended), "BandMuted"))
        else:
            status = lambda: _row(live._chip(live.OUTCOMES.get(m.outcome, m.outcome).upper(), "bad"),
                                  (live._clock(m.ended), "BandMuted"))
        fill(self.c_mission, [status, lambda: _row((" · ".join(x for x in (kind, live._contractor(m, info)) if x),
                                                    "BandSecondary"))], "MISSION").addStretch(1)

        # Now: the current objective, large (it may take two lines), then what's next.
        objectives = m.visible_objectives
        current = m.current_objective
        done = sum(1 for o in objectives if o.done)
        self.c_now.set_title(f"NOW · STEP {min(done + 1, len(objectives))} OF {len(objectives)}"
                             if objectives and m.active else "OBJECTIVES")

        def objective(o):
            mark = "▶  " if (o is current and m.active) else ("✓  " if o.done else "○  ")
            style = "BandCurrent" if (o is current and m.active) else ("BandMuted" if o.done else "BandLine")
            return lambda: _row((mark + o.text, style))

        v = self.c_now.body()
        if m.active and current is not None:
            big = QLabel(current.text, objectName="BandObjective")
            big.setWordWrap(True)
            big.setMaximumHeight(2 * ROW_H + 8)
            v.addWidget(big)
            after = objectives[objectives.index(current) + 1:] if current in objectives else []
            for o in after[:max(0, self.c_now.rows() - 2)]:
                v.addWidget(objective(o)())
            if len(objectives) > 1:
                self.c_now.set_more(f"{done} done · {len(objectives) - done} to go ▾",
                                    lambda: list_drop(self.c_now, [objective(o) for o in objectives], "ALL OBJECTIVES"))
            v.addStretch(1)
        else:
            fill(self.c_now, [objective(o) for o in objectives], "ALL OBJECTIVES",
                 "No objectives in the log yet").addStretch(1)

        # Details: the facts you act on (where, cargo, rank…), as many as fit; the rest and the brief in "all".
        facts = [_pair(r[0], r[1]) for r in live._detail_rows(info) if r[0] != "Time"]
        if (info or {}).get("description"):
            text = info["description"]

            def brief():
                lbl = QLabel(text[:1500], objectName="BandSecondary")
                lbl.setWordWrap(True)
                return lbl
        else:
            brief = None
        v = fill(self.c_facts, facts, "DETAILS", "Loading contract details…" if f.contracts is None
                 else "No details in the mission database")
        if brief is not None:
            # The brief is reading, not doing: it's a click away (with every fact above it).
            def all_details():
                drop = DropList(live._mission_title(m, info).upper())
                for make in facts:
                    drop.rows.addWidget(make())
                drop.rows.addWidget(brief())
                drop.rows.addStretch(1)
                _drop(self.c_facts, drop, DROP_MAX_H)
            self.c_facts.set_more("all + brief ▾", all_details)
        v.addStretch(1)

        # Pays: reputation large; the blueprints you don't have yet, by name.
        v = self.c_pays.body()
        rep = m.rep if m.rep is not None else (info or {}).get("rep")
        extra = [c.text() for c in live._rewards(m, info) if not c.text().endswith(" rep")]
        v.addWidget(_big(f"+{rep:,}" if rep else "—", "rep" + (" · " + " · ".join(extra) if extra else "")
                         if rep else " · ".join(extra)))
        possible = live._possible_blueprints(info, owned)
        if m.outcome == "Complete":
            got = ", ".join(m.blueprints)
            if got:
                v.addWidget(_row(("Blueprint: " + got, "BandGood")))
            elif rewards.get(m.id, 1e9) < live.BLUEPRINT_WINDOW_SECONDS and (m.blueprint_chance or possible):
                v.addWidget(_row(("Blueprint: checking…", "BandMuted")))
            else:
                v.addWidget(_row(("No blueprint received", "BandMuted")))
        elif possible:
            new = [n for n, have in possible if not have]
            chance = max((pool.get("chance") or 0) for pool in info["blueprints"])
            head = (f"＋ {len(new)} new blueprint{'s' if len(new) != 1 else ''}" if new else
                    f"✓ you have all {len(possible)} blueprints")
            v.addWidget(_row((head + (f" · {chance:.0%} chance" if chance else ""), "BandGood" if new else "BandMuted")))
            rows = [(lambda n=n: _row(("＋ " + n, "BandGood"))) for n in new] + [
                (lambda n=n: _row(("✓ " + n, "BandMuted"))) for n, have in possible if have]
            room = max(0, self.c_pays.rows() - 3)
            for make in rows[:room]:
                v.addWidget(make())
            if room < len(rows):
                self.c_pays.set_more(f"+{len(rows) - room} more ▾",
                                     lambda: list_drop(self.c_pays, rows, "POSSIBLE BLUEPRINTS"))
        elif m.blueprint_chance:
            v.addWidget(_row(("Blueprint chance", "BandMuted")))
        v.addStretch(1)

        waits = []
        for age in rewards.values():
            if age < live.BLUEPRINT_WINDOW_SECONDS:
                waits.append(live.BLUEPRINT_WINDOW_SECONDS - age)
            waits.append(live.REWARD_SECONDS - age)
        waits += [t - time.monotonic() for t in self._flash_until.values()]
        if waits:
            self._expire.start(max(50, int(min(waits) * 1000) + 50))


# -- Session --------------------------------------------------------------------------------
class SessionBand(_LiveBand, live.SessionPanel):
    """Where you are · this session's six numbers · blueprints received · recent moments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_now = BandColumn("NOW", 3, 1, 190)
        self.c_numbers = BandColumn("THIS SESSION", 4, 1, 300)
        self.c_blueprints = BandColumn("BLUEPRINTS", 3, 2, 190)
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
        rows = [lambda: _row((tr.ship or "No ship", "BandStrong")),
                lambda: _row((pretty(tr.location) if tr.location else "Location not known yet", "BandSecondary"))]
        if tr.comm_down:
            rows.append(lambda: _row(live._chip("COMMS DOWN", "bad"), ("comm array offline", "BandMuted")))
        elif tr.monitored is not None:
            rows.append(lambda: _row(live._chip("MONITORED" if tr.monitored else "UNMONITORED",
                                                "info" if tr.monitored else "bad"), ("", "BandMuted")))
        if tr.qt_target:
            rows.append(lambda: _row(("Quantum to " + pretty(tr.qt_target), "BandMuted")))
        fill(self.c_now, rows, "NOW").addStretch(1)

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
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        for i, (value, name, tone) in enumerate(numbers):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            big = QLabel(value, objectName="BandNumber")
            if tone:
                big.setProperty("tone", tone)
            cell.addWidget(big)
            cell.addWidget(QLabel(name, objectName="BandMuted"))
            grid.addLayout(cell, i // 3, i % 3)
        v.addLayout(grid)
        v.addStretch(1)

        self.c_blueprints.set_title(f"BLUEPRINTS · {len(tr.blueprints)}")
        fill(self.c_blueprints, [(lambda n=name, w=when, s=source: _row((n, "BandGood"),
                                                                        (live._clock(w), "BandTime")))
                                 for w_, name, source in reversed(tr.blueprints) for when in (w_,)],
             "BLUEPRINTS THIS SESSION", "None received yet").addStretch(1)
        fill(self.c_recent, [(lambda i=item: _row((i.text, {"good": "BandGood", "bad": "BandBad"}.get(i.kind, "BandLine")),
                                                  (live._clock(i.time), "BandTime")))
                             for item in tr.feed], "RECENT", "Nothing yet").addStretch(1)


# -- Mining ---------------------------------------------------------------------------------
class MiningBand(_BandBody, MiningPanel):
    """Ore, method and system · the best places (near you first; a click picks
    one) · that place's rocks (a click picks one) · the picked rock: its radar
    signature alone and in groups, and what's in it at what quality."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_find = BandColumn("FIND", 2, 1, 190)
        self.c_places = BandColumn("BEST PLACES", 4, 1, 280)
        self.c_rocks = BandColumn("ROCKS", 3, 2, 220)
        self.c_rock = BandColumn("ROCK", 3, 2, 220)
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
        self._band_setup([self.c_find, self.c_places, self.c_rocks, self.c_rock])
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

    def _pick_rock(self, rock: str) -> None:
        self.rock = rock
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
        v = self.c_find.body()
        v.addStretch(1)

        def place(loc):
            def make():
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
                    return _row(name, chip, _bar(share / top if top else 0, PALETTE["success"], 60),
                                (_pct(share), "BandNum"), (f"Q {q}" if q is not None else "", "BandMuted"),
                                click=lambda: self._open(loc["id"]), selected=picked)
                n = len(loc["groups"][self._method])
                return _row(name, chip, (f"{n} rock type{'s' if n != 1 else ''}", "BandMuted"),
                            click=lambda: self._open(loc["id"]), selected=picked)
            return make

        # The picked place stays in sight: first among the rows that fit if it isn't there already.
        order = list(locs)
        fit = self.c_places.rows()
        at = next((i for i, l in enumerate(order) if l["id"] == self.location), 0)
        if at >= fit - 1 and len(order) > fit:
            order.insert(0, order.pop(at))
        fill(self.c_places, [place(l) for l in order], self.c_places.title.text(),
             "Not found with this method here: try All systems or another method").addStretch(1)

        loc = next((l for l in locs if l["id"] == self.location), None)
        rocks_data, resources = self.data["rocks"], self.data["resources"]
        items = sorted((loc or {"groups": {}})["groups"].get(self._method, []),
                       key=lambda i: (not any(p["res"] == res for p in rocks_data[i["rock"]]["parts"]), -i["chance"]))
        if self.rock not in [i["rock"] for i in items]:
            self.rock = items[0]["rock"] if items else None
        self.c_rocks.set_title(f"AT {loc['name'].upper()}" if loc else "ROCKS")

        def rock_row(item):
            def make():
                rock = rocks_data[item["rock"]]
                hit = res is not None and any(p["res"] == res for p in rock["parts"])
                style = "BandCurrent" if hit else ("BandMuted" if res is not None else "BandLine")
                return _row((rock["name"], style), (_pct(item["chance"]), "BandMuted"),
                            (f"RS {rock['signature']:,}" if rock.get("signature") else "", "BandNum"),
                            click=lambda: self._pick_rock(item["rock"]), selected=item["rock"] == self.rock)
            return make

        fill(self.c_rocks, [rock_row(i) for i in items], self.c_rocks.title.text(), "No rocks").addStretch(1)

        # The picked rock: radar first (that's how you find it), then what's in it.
        item = next((i for i in items if i["rock"] == self.rock), None)
        rock = rocks_data.get(self.rock) if self.rock else None
        if rock is None:
            self.c_rock.set_title("ROCK")
            self.c_rock.body().addStretch(1)
            return
        self.c_rock.set_title(rock["name"].upper() + (f" · {rock['rarity'].upper()}" if rock.get("rarity") else ""))
        sig = rock.get("signature") or 0
        sizes = ((item or {}).get("cluster") or {}).get("sizes") or []
        most = max((n for n, _ in sizes), default=1) if self._method == "ship" else 1
        rows = []
        if sig:
            groups = "  ".join(f"×{n} {sig * n:,}" for n in range(2, most + 1))
            rows.append(lambda: _row(_fixed(f"RS {sig:,}", "BandNumAmber"), (groups, "BandMuted")))
        quality = self.data["quality"]
        parts = sorted(rock["parts"], key=lambda p: (p["res"] != res, -p.get("avg", 0)))
        for part in parts:
            def make(part=part):
                q = quality.get(part["res"], {}).get(loc["system"], {}).get(str(part["scale"]))
                name = resources.get(part["res"], {}).get("name", part["res"])
                odds = f" · in {part['prob'] * 100:.0f}%" if part.get("prob", 1) < 1 else ""
                return _row((name, "BandCurrent" if part["res"] == res else "BandLine"),
                            (f"{_pct(part['avg'])}{odds}", "BandMuted"),
                            (f"Q {q['avg']}" if q else "", "BandNum"))
            rows.append(make)
        fill(self.c_rock, rows, self.c_rock.title.text()).addStretch(1)


# -- Salvage --------------------------------------------------------------------------------
class SalvageBand(_BandBody, SalvagePanel):
    """Your ship (the claim you accepted, found by itself, or one you pick) ·
    what it's worth · the components to take off it, the best first · the
    cargo aboard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c_ship = BandColumn("SHIP", 3, 1, 220)
        self.c_value = BandColumn("WORTH", 2, 1, 170)
        self.c_parts = BandColumn("COMPONENTS TO TAKE", 5, 1, 280)
        self.c_cargo = BandColumn("CARGO ABOARD", 3, 2, 190)
        self.tier_box = _combo()
        self.ship_box = _combo()
        pair = QWidget()
        pair.setFixedHeight(COMBO_H)
        ph = QHBoxLayout(pair)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(4)
        ph.addWidget(self.tier_box, stretch=2)
        ph.addWidget(self.ship_box, stretch=5)
        for w in (self.tier_box, self.ship_box):
            w.setFixedHeight(COMBO_H)
        self.tier_box.activated.connect(self._on_tier_box)
        self.ship_box.activated.connect(self._on_ship_box)
        self.c_ship.head.addWidget(pair)
        self._ranked: list = []
        self._band_setup([self.c_ship, self.c_value, self.c_parts, self.c_cargo])
        self.show_message("Loading salvage data…")

    def _on_tier_box(self, i: int) -> None:
        self.tier.set_value(self.tier_box.itemData(i))
        self.opened = None
        self._on_tier(self.tier_box.itemData(i))

    def _on_ship_box(self, i: int) -> None:
        if 0 <= i < len(self._ranked):
            self.opened = self._ranked[i].stem
            self._fill_ships()

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
        row = self._current()
        if row is None:
            return ""
        c = self._claim if self.following() else None
        return html.escape((f"Claim #{c['number']} · " if c else "") + f"{row.name} · worth {_short(row.net)}")

    def _current(self):
        return next((r for r in self._ranked if r.stem == self.opened), self._ranked[0] if self._ranked else None)

    def _fill_ships(self) -> None:
        if self.game is None:
            return
        from app import salvage
        from app.ui.salvage_view import _better_option

        self.show_columns()
        i = self.tier_box.findData(self._tier)
        if i >= 0 and self.tier_box.currentIndex() != i:
            self.tier_box.setCurrentIndex(i)
        rows = salvage.build_rows(self.game, self._tier, self.sheet, self.prices)
        rows.sort(key=lambda r: (not r.in_sheet, -r.net, r.name))
        self._ranked = rows
        self._rows = {}
        claim = self._claim if self.following() else None
        mine = claim.get("stem") if claim is not None and claim["tier"] == self._tier else None
        if self.opened not in [r.stem for r in rows]:
            self.opened = mine or (rows[0].stem if rows else None)
        row = self._current()
        lst = getattr(self.ship_box, "_list", None)
        if lst is None or not lst.isVisible():
            self.ship_box.blockSignals(True)
            self.ship_box.clear()
            for r in rows:
                self.ship_box.addItem(f"{r.name}  ·  {_short(r.net) if r.in_sheet else 'no data'}"
                                      + ("  · your claim" if r.stem == mine else ""))
            if row is not None:
                self.ship_box.setCurrentIndex(rows.index(row))
            self.ship_box.blockSignals(False)

        # Ship: following your claim or picked; how it ranks; how hard it is.
        lines = []
        if self.sheet is None:
            lines.append(lambda: _row(("Prices not downloaded: open Salvage Claims in the launcher", "BandBad")))
        if claim is not None:
            tier_label = next((t["label"] for t in self.game["tiers"] if t["id"] == claim["tier"]), claim["tier"])
            lines.append(lambda: _row(kit.Dot(PALETTE["success"], 7),
                                      (f"Claim #{claim['number']} · {claim['ship']} · {tier_label}", "BandInfo")))
        elif live.feed().state == "disabled":
            lines.append(lambda: _row(("Turn on LIVE LOG to follow your claim", "BandMuted")))
        else:
            lines.append(lambda: _row(("No claim active: pick the ship", "BandMuted")))
        if row is not None:
            rank = rows.index(row) + 1
            lines.append(lambda: _row((f"#{rank} of {len(rows)} by value", "BandMuted")))
            if row.note:
                lines.append(lambda: _row((row.note, "BandMuted")))
        fill(self.c_ship, lines, "SHIP").addStretch(1)
        if row is None:
            for c in (self.c_value, self.c_parts, self.c_cargo):
                c.body().addStretch(1)
            return

        # Worth: net large, then where it comes from.
        if row.in_sheet:
            sums = [lambda: _row(("Components", "BandMuted"), (f"{row.components_value:,.0f}", "BandNum")),
                    lambda: _row(("Cargo", "BandMuted"), (f"{row.cargo_value:,.0f}", "BandNum"))]
            if row.fee:
                sums.insert(0, lambda: _row(("Claim fee", "BandMuted"), (f"−{row.fee:,.0f}", "BandBad")))
        else:
            sums = [lambda: _row(("Not in the price spreadsheet yet", "BandMuted"))]
        # The net, large (two lines' height); what it's made of under it, if there's room.
        if self.c_value.rows() > 2:
            v = fill(self.c_value, sums, f"{row.name.upper()} · WORTH", reserve=2)
        else:
            v = self.c_value.body()
        v.insertWidget(0, _big(_short(row.net) if row.in_sheet else "—", "net", amber=True))
        v.addStretch(1)

        # Components to take: the most valuable first; what to do with each (sell or dismantle).
        parts = sorted(row.components, key=lambda c: (c.salvageable != "yes", -(c.best * c.qty)))
        self.c_parts.set_title(f"COMPONENTS TO TAKE · {sum(1 for c in parts if c.salvageable == 'yes')}")

        def part(c):
            def make():
                better = _better_option(c) or ("sell" if c.sell else "dismantle" if c.dismantle else "")
                value = c.best * c.qty
                ok = c.salvageable == "yes"
                return _row(_fixed(f"{c.qty}×", "BandMuted"), (c.name, "BandLine" if ok else "BandMuted"),
                            (f"{value:,.0f}" if value else "—", "BandNumGood" if ok and value else "BandMuted"),
                            _fixed(better if value else ("?" if c.salvageable == "unlisted" else ""), "BandMuted"))
            return make
        cols2 = self.c_parts.width() >= 520
        if cols2:
            v = self.c_parts.body()
            per = self.c_parts.rows()
            makers = [part(c) for c in parts]
            cells = [m() for m in makers[:per * 2]]
            if len(cells) < len(makers):
                self.c_parts.set_more(f"+{len(makers) - len(cells)} more ▾",
                                      lambda: list_drop(self.c_parts, makers, f"{row.name.upper()} · ALL COMPONENTS"))
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(20)
            grid.setVerticalSpacing(1)
            for k, cell in enumerate(cells):
                grid.addWidget(cell, k % per, k // per)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            v.addLayout(grid)
            v.addStretch(1)
        else:
            fill(self.c_parts, [part(c) for c in parts], f"{row.name.upper()} · ALL COMPONENTS",
                 "No components listed").addStretch(1)

        fill(self.c_cargo, [(lambda c=c: _row((f"{c.scu} SCU {c.material}", "BandLine"),
                                              (f"{c.value:,.0f}" if c.value else "—", "BandNum")))
                            for c in sorted(row.cargo, key=lambda c: -c.value)],
             f"{row.name.upper()} · CARGO", "No cargo aboard").addStretch(1)


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


class MapsBand(_BandBody, MapsPanel):
    """The guide · its pages · guides for what you're doing · Show guide: the
    guide itself pulls out below the band as a drawer (a pick, a page, or L
    opens it)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        frame = self.viewer.parentWidget()
        buttons = [b for b in self.findChildren(QPushButton, "MiniButton") if b.text() in ("−", "Fit", "+", "⤢")]
        self.c_guide = BandColumn("GUIDE", 3, 1, 240)
        self.c_pages = BandColumn("PAGES", 3, 2, 190)
        self.c_for = BandColumn("FOR WHAT YOU'RE DOING", 3, 2, 200)
        self.c_open = BandColumn("", 2, 1, 170)
        self.guide.setFixedHeight(COMBO_H)
        self.c_guide.head.addWidget(self.guide)
        self.guide.show()
        self.guide.activated.connect(lambda _i: QTimer.singleShot(0, self.open_drawer))
        self.page.hide()                     # the pages are a column of their own
        self.open_btn = QPushButton("▾  Show guide", objectName="BandOpen")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.open_btn.setFixedHeight(40)
        self.open_btn.clicked.connect(self.toggle_drawer)
        self.c_open.layout().setContentsMargins(12, 0, 12, 0)
        self.c_open._holder.addStretch(1)
        self.c_open._holder.addWidget(self.open_btn)
        self.c_open._holder.addStretch(1)
        self._band_setup([self.c_guide, self.c_pages, self.c_for, self.c_open])
        self.drawer = MapsDrawer(self, frame, buttons)
        self.drawer.hide()
        self._anim = QVariantAnimation(self, duration=DRAWER_MS, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._drawer_step)
        self._drawer_rect = QRect()
        self._shape_pending = False

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
        self._set_drawer_title()
        if win is None or self.drawer_open():
            return
        height = int(win._area().height() * DRAWER_SHARE)
        win.show_drop(self.drawer, height, width=win.width(), sticky=True)
        self._drawer_rect = self.drawer.geometry()
        self._anim.stop()
        self._anim.setStartValue(1)
        self._anim.setEndValue(self._drawer_rect.height())
        self._anim.start()
        self.open_btn.setText("▲  Push back")
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

    def hideEvent(self, event):
        super().hideEvent(event)

    def _toggle_large(self) -> None:
        self.toggle_drawer()

    def _set_drawer_title(self) -> None:
        self.drawer.title.setText(self.guide.currentText().upper()
                                  + (f" · {self.page.currentText().upper()}" if self.page.count() > 1 else ""))

    def drawer_closed(self) -> None:
        self.open_btn.setText("▾  Show guide")

    # -- following, guides, pages ----------------------------------------------------------
    def _band_render(self) -> None:
        self._render_band()

    def summary(self) -> str:
        return html.escape(self.guide.currentText())

    def _apply_game(self) -> None:
        super()._apply_game()
        self._render_band()

    def _unfollow(self) -> None:
        super()._unfollow()
        self._render_band()

    def _update_follow_line(self) -> None:
        super()._update_follow_line()
        self._render_band()

    def _render_band(self) -> None:
        if not hasattr(self, "c_for"):
            return
        fill(self.c_guide, [lambda: _row(("Community guides by Mr Kraken · all credit to him", "BandMuted"))],
             "GUIDE").addStretch(1)

        n = self.page.count()
        self.c_pages.set_title(f"PAGES · {n}" if n > 1 else "PAGES")

        def page_row(i):
            return lambda: _row((self.page.itemText(i), "BandCurrent" if i == self.page.currentIndex() else "BandLine"),
                                click=lambda: self._go_page(i), selected=i == self.page.currentIndex())
        fill(self.c_pages, [page_row(i) for i in range(n)] if n > 1 else [],
             "PAGES", "One page").addStretch(1)

        current = self.guide.currentText()
        suggested = [t for t in self._suggested if t != current] if self.following() else []

        def guide_row(title):
            short = title.split(" [", 1)[0].replace(" Companion Guide", "").replace(" Guide", "")
            return lambda: _row((short, "BandLink"), ("›", "BandMuted"), click=lambda: self._open_guide(title))
        empty = ("This guide is for what you're doing" if self.following() and current in self._suggested else
                 "No guide for your missions or location" if self.following() else "Not following your game")
        fill(self.c_for, [guide_row(t) for t in suggested], "FOR WHAT YOU'RE DOING", empty).addStretch(1)

    def _go_page(self, i: int) -> None:
        self.page.setCurrentIndex(i)
        self._on_page(i)
        _close_drop(self) if not self.drawer_open() else None
        self.open_drawer()
        self._render_band()

    def _open_guide(self, title: str) -> None:
        super()._open_guide(title)
        self.open_drawer()

    def _on_guide(self, index: int, shape: bool = False) -> None:
        super()._on_guide(index, False)
        self.page.hide()
        self._render_band()

    def _on_page(self, index: int, shape: bool = False) -> None:
        super()._on_page(index, False)
        if hasattr(self, "drawer"):
            self._set_drawer_title()


BANDS = {"missions": MissionsBand, "session": SessionBand, "mining": MiningBand, "salvage": SalvageBand,
         "maps": MapsBand}


def make(tool: str) -> QWidget:
    return BANDS[tool]()
