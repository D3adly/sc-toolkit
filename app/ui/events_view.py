"""Events: your orgs' ops from sc-toolbox.com, a calendar, an event's details, and your seat.

The launcher's half of Events: see what's planned and take, change or leave a seat. Planning
events (creating, editing, drafts) is the website's (sc-toolbox.com/app/events); the buttons for it
open the browser. The data and every call are app.events'; this view only shows and asks.
"""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import events, hangar, osutil, portal
from app.theme import PALETTE
from app.ui import kit
from app.ui.kit import Badge, label

GUNNERS_PER_ROW = 4
FILTERS = [("all", "All"), ("mine", "I'm in"), ("room", "Has room")]


def _web(path: str = "") -> str:
    return f"{portal.service_url()}/app/events{path}"


def _has_room(e: dict) -> bool:
    c = events.crew(e.get("groups", []))
    return c["taken"] < c["total"] or c["open_spots"] > 0


def _badges(e: dict) -> list[QLabel]:
    out = []
    if e.get("official"):
        out.append(Badge("Official", "accent"))
    if e.get("status") == "cancelled":
        out.append(Badge("Cancelled", "warning"))
    if e.get("kind") in events.KINDS:
        name, hue = events.KINDS[e["kind"]]
        out.append(Badge(name, hue=hue))
    return out


def _row(*widgets, spacing: int = 6, stretch: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    for w in widgets:
        row.addWidget(w)
    if stretch:
        row.addStretch(1)
    return row


# -- the agenda -------------------------------------------------------------------------------

class _Calendar(QFrame):
    """A month: days with ops marked (green: one you're in). Clicking one opens its first op."""

    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, objectName="Panel")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(6)
        today = date.today()
        self.month = date(today.year, today.month, 1)
        head = QHBoxLayout()
        prev = kit.button("‹", "ghost", lambda: self._shift(-1), tip="Previous month")
        nxt = kit.button("›", "ghost", lambda: self._shift(1), tip="Next month")
        self.title = kit.caps("")
        head.addWidget(prev)
        head.addStretch(1)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(nxt)
        v.addLayout(head)
        self.grid = QGridLayout()
        self.grid.setSpacing(3)
        v.addLayout(self.grid)
        self.events: list[dict] = []
        self._render()

    def set_events(self, items: list[dict]) -> None:
        self.events = items
        self._render()

    def _shift(self, by: int) -> None:
        m = self.month.month - 1 + by
        self.month = date(self.month.year + m // 12, m % 12 + 1, 1)
        self._render()

    def _render(self) -> None:
        kit.clear_layout(self.grid)
        self.title.setText(f"{events.MONTHS[self.month.month - 1]} {self.month.year}".upper())
        for i, d in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            self.grid.addWidget(label(d, "CapsLabel", align=Qt.AlignCenter), 0, i)
        by_day: dict[date, list[dict]] = {}
        for e in self.events:
            if e.get("status") == "published":
                by_day.setdefault(events.parse_time(e["startsAt"]).astimezone().date(), []).append(e)
        first = self.month
        lead = first.weekday()
        days = ((first.replace(day=28) + timedelta(days=4)).replace(day=1) - first).days
        for day in range(1, days + 1):
            d = first.replace(day=day)
            ops = by_day.get(d, [])
            btn = QPushButton(str(day), objectName="CalDay")
            btn.setFixedHeight(28)
            btn.setProperty("kind", "mine" if any(e.get("mySignups") for e in ops) else ("op" if ops else ""))
            btn.setProperty("today", d == date.today())
            if ops:
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip("\n".join(e["title"] for e in ops))
                btn.clicked.connect(lambda _c=False, i=ops[0]["id"]: self.picked.emit(i))
            else:
                btn.setEnabled(False)
            pos = lead + day - 1
            self.grid.addWidget(btn, 1 + pos // 7, pos % 7)


class _EventCard(QFrame):
    """One op in the agenda: date, title and tags, your seat, how full it is."""

    clicked = Signal(str)

    def __init__(self, e: dict, parent=None):
        super().__init__(parent, objectName="MissionCard")
        self.event_id = e["id"]
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 9, 12, 9)
        row.setSpacing(12)
        start = events.parse_time(e["startsAt"]).astimezone()
        when = label(f"<span style='font-size:10px;color:{PALETTE['text_muted']}'>{events.MONTHS[start.month - 1].upper()}"
                     f"</span><br><b style='font-size:18px'>{start.day}</b><br>"
                     f"<span style='font-size:10px'>{start:%H:%M}</span>", "EventDate", rich=True,
                     align=Qt.AlignCenter)
        when.setFixedSize(48, 54)
        row.addWidget(when)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = label(html.escape(e["title"]), "CardTitle", rich=True, wrap=True)
        text.addWidget(title)
        tags = _badges(e)
        seat = events.my_seat(e)
        if seat:
            tags.append(Badge("Backup" if seat.startswith("Backup") else "You're in", "success"))
        if tags:
            text.addLayout(_row(*tags, spacing=4))
        c = events.crew(e.get("groups", []))
        text.addWidget(label(f"{html.escape(e['org']['name'])} · {events.needs(c)}", "MutedText", wrap=True))
        bar = kit.Bar(c["taken"] / c["total"] if c["total"] else 0,
                      PALETTE["success"] if c["taken"] >= c["total"] else PALETTE["accent"], width=0)
        text.addWidget(bar)
        row.addLayout(text, stretch=1)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        kit.repolish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.event_id)
        super().mousePressEvent(event)


# -- an event's details -----------------------------------------------------------------------

def _seat_button(text: str, state: str, slot=None, tip: str = "") -> QPushButton:
    """A seat: "free" (click to take), "taken" (someone), "mine" (you; click for your options)."""
    btn = QPushButton(text, objectName="SeatButton")
    btn.setProperty("state", state)
    if tip:
        btn.setToolTip(tip)
    if slot is not None:
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
    elif state == "taken":
        btn.setFocusPolicy(Qt.NoFocus)
    return btn


class EventsView(kit.ToolPage):
    def __init__(self, parent=None):
        super().__init__("events", "Events",
                         "Your orgs' ops: take a seat here; plan new ones on sc-toolbox.com.",
                         web_url=_web(), parent=parent)
        self.ctl = events.controller()
        self.add_action(kit.button("Plan an event ↗", "primary", lambda: osutil.open_url(_web("/new")),
                                   tip="Planning events happens on sc-toolbox.com"))
        self.filter = kit.Segmented(FILTERS, "all", compact=True)
        self.filter.changed.connect(lambda _k: self._render_list())
        self.filters.add(self.filter, "Show")
        self.filters.add_stretch()
        self.selected: str | None = None
        self.detail: dict | None = None
        self._pending: tuple[str, dict] | None = None   # the last sign-up, for "move here?"

        content = QWidget()
        cols = QHBoxLayout(content)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.calendar = _Calendar()
        self.calendar.picked.connect(self.focus_on)
        left.addWidget(self.calendar)
        self.list_area = kit.scroll_area()
        self.list_box = QWidget()
        self.list_layout = QVBoxLayout(self.list_box)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(8)
        self.list_area.setWidget(self.list_box)
        left.addWidget(self.list_area, stretch=1)
        side = QWidget()
        side.setLayout(left)
        side.setFixedWidth(370)
        cols.addWidget(side)
        self.detail_area = kit.scroll_area()
        self.detail_box = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_box)
        self.detail_layout.setContentsMargins(0, 0, 8, 0)
        self.detail_layout.setSpacing(12)
        self.detail_area.setWidget(self.detail_box)
        cols.addWidget(self.detail_area, stretch=1)
        self.set_content(content)

        self._tick = QTimer(self, interval=1000, timeout=self._update_countdown)
        self.countdown: QLabel | None = None
        self.ctl.listed.connect(self._on_list)
        self.ctl.loaded.connect(self._on_detail)
        self.ctl.failed.connect(self._on_failed)
        self.ctl.state.connect(lambda _s: self._on_list(self.ctl.events))
        self._on_list(self.ctl.events)

    # -- page ---------------------------------------------------------------------------
    def activate(self) -> None:
        self.ctl.refresh()
        if self.selected:
            self.ctl.load(self.selected)
        self._tick.start()

    def deactivate(self) -> None:
        self._tick.stop()

    def focus_on(self, event_id) -> None:
        """Opens one event (the overlay's reminder and the calendar link here)."""
        self.selected = str(event_id)
        self._mark_selected()
        self.ctl.load(self.selected)

    # -- the agenda -----------------------------------------------------------------------
    def _on_list(self, items: list) -> None:
        status = self.ctl.status
        if status == "signed_out":
            from app.account_controller import controller as account_controller

            self.show_empty("Sign in to see your orgs' ops",
                            "Events come from sc-toolbox.com: your orgs (from your verified RSI account) and their ops.",
                            "Sign in", account_controller().sign_in, "primary")
            return
        if status == "loading" and not items:
            self.show_message("Loading your orgs' ops…")
            return
        if not items:
            self.show_empty("No ops planned", "Your orgs have nothing planned yet. Plan the first one on the website.",
                            "Plan an event ↗", lambda: osutil.open_url(_web("/new")), "primary")
            return
        self.show_content()
        self.calendar.set_events(items)
        if status == "offline":
            self.notice.show_text("Couldn't reach sc-toolbox.com: showing the ops from the last check.", "warning")
        else:
            self.notice.hide()
        self._render_list()
        if self.selected is None or not any(e["id"] == self.selected for e in items):
            first = next((e for e in items if e.get("mySignups")), items[0])
            self.focus_on(first["id"])

    def _render_list(self) -> None:
        kit.clear_layout(self.list_layout)
        test = {"all": lambda e: True, "mine": lambda e: bool(e.get("mySignups")), "room": _has_room}[self.filter.value() or "all"]
        shown = [e for e in self.ctl.events if test(e)]
        self.cards: dict[str, _EventCard] = {}
        for e in shown:
            card = _EventCard(e)
            card.clicked.connect(self.focus_on)
            self.cards[e["id"]] = card
            self.list_layout.addWidget(card)
        if not shown:
            self.list_layout.addWidget(label("Nothing matches.", "MutedText"))
        self.list_layout.addStretch(1)
        total = len(self.ctl.events)
        mine = sum(1 for e in self.ctl.events if e.get("mySignups"))
        text = f"{total} op{'s' if total != 1 else ''} · you're in {mine}"
        self.result.set_count(f"Showing {len(shown)} of {text}" if len(shown) != total else text)
        self._mark_selected()

    def _mark_selected(self) -> None:
        for event_id, card in getattr(self, "cards", {}).items():
            card.set_selected(event_id == self.selected)

    # -- the event --------------------------------------------------------------------------
    def _on_detail(self, e: dict) -> None:
        if e.get("id") != self.selected:
            return
        self.detail = e
        kit.clear_layout(self.detail_layout)
        add = self.detail_layout.addWidget
        cancelled = e.get("status") == "cancelled"

        hero = kit.panel()
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(16, 14, 16, 14)
        hv.setSpacing(6)
        tags = _badges(e)
        by = e.get("creator") or {}
        tags.append(label(f"by {'you' if by.get('me') else html.escape(by.get('displayName', 'a former member'))}"
                          f" · {html.escape(e['org']['name'])}", "MutedText"))
        hv.addLayout(_row(*tags, spacing=6))
        hv.addWidget(label(html.escape(e["title"]), "DetailTitle", wrap=True, rich=True))
        self.countdown = label("", "Countdown")
        when = events.local_time(e["startsAt"])
        if e.get("durationMinutes"):
            when += f" · {e['durationMinutes'] // 60} h" + (f" {e['durationMinutes'] % 60} min" if e["durationMinutes"] % 60 else "")
        hv.addLayout(_row(self.countdown, label(when, "StrongText"), spacing=14))
        self._update_countdown()
        hv.addWidget(self._crew(e))
        add(hero)

        if cancelled:
            self.notice.show_text("This op was cancelled.", "warning", dismissible=False)
        else:
            add(self._join(e))
        for g in e.get("groups", []):
            add(self._group(e, g, open_=not cancelled))
        if e.get("musterPoint") or e.get("comms") or e.get("description"):
            brief = kit.Section("Briefing")
            for name, value in (("Muster", e.get("musterPoint")), ("Comms", e.get("comms"))):
                if value:
                    brief.v.addLayout(_row(label(name, "MutedText"), label(html.escape(value), "BodyText", rich=True)))
            if e.get("description"):
                brief.add(label(html.escape(e["description"]).replace("\n", "<br>"), "BodyText", wrap=True, rich=True))
            add(brief)
        links = _row(kit.button("Open on sc-toolbox.com ↗", "ghost", lambda: osutil.open_url(_web(f"/{e['id']}"))))
        if e.get("canManage"):
            links.insertWidget(1, kit.button("Edit on the website ↗", "ghost",
                                             lambda: osutil.open_url(_web(f"/{e['id']}/edit"))))
        self.detail_layout.addLayout(links)
        self.detail_layout.addStretch(1)

    def _update_countdown(self) -> None:
        if self.countdown is not None and self.detail is not None:
            try:
                self.countdown.setText(events.countdown(self.detail["startsAt"], self.detail.get("durationMinutes")))
            except RuntimeError:
                self.countdown = None   # the label went with a re-render

    def _crew(self, e: dict) -> QWidget:
        c = events.crew(e.get("groups", []))
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        r = 0
        for key, name, colour in (("pilot", "Pilots", PALETTE["info"]), ("gunner", "Gunners", PALETTE["hue_nyx"]),
                                  ("infantry", "Ground", PALETTE["hue_pyro"])):
            taken, total = c[key]
            if not total:
                continue
            grid.addWidget(label(name, "MutedText"), r, 0)
            grid.addWidget(kit.Bar(taken / total, colour, width=160), r, 1)
            grid.addWidget(label(f"{taken}/{total}", "StrongText"), r, 2)
            r += 1
        grid.setColumnStretch(3, 1)
        note = f"{c['taken']}/{c['total']}{'+' if c['open_spots'] else ''} crew"
        grid.addWidget(label(note, "StatSmall"), 0, 3, alignment=Qt.AlignRight | Qt.AlignTop)
        return box

    def _join(self, e: dict) -> QWidget:
        """Join by role (the service picks the seat), or where you are and how to leave."""
        box = kit.Section("You're in" if e.get("mySignups") else "Join this op")
        if e.get("mySignups"):
            for s in e["mySignups"]:
                one = dict(e, mySignups=[s])
                leave = kit.button("Leave", "ghost", lambda _c=False, gid=s["groupId"]: self._leave(gid))
                box.v.addLayout(_row(label(html.escape(events.my_seat(one) or ""), "StrongText", rich=True), leave))
            box.add(label("To move, click a free seat below.", "MutedText"))
            return box
        c = events.crew(e.get("groups", []))
        free = {k: c[k][1] - c[k][0] for k in ("pilot", "gunner", "infantry")}
        fly = kit.button(f"Fly a ship ({free['pilot']})", "secondary")
        fly.setEnabled(free["pilot"] > 0)
        fly.clicked.connect(lambda: self._fly_menu(fly))
        gun = kit.button(f"Crew a turret ({free['gunner']})", "secondary", lambda: self._sign_up({"role": "gunner"}))
        gun.setEnabled(free["gunner"] > 0)
        ground = kit.button(f"Ground team ({free['infantry']})", "secondary", lambda: self._sign_up({"role": "infantry"}))
        ground.setEnabled(free["infantry"] > 0)
        backup = kit.button("Backup", "ghost", self._backup_anywhere,
                            tip="No seat: the organizer can call on you if one opens")
        box.v.addLayout(_row(fly, gun, ground, backup))
        box.add(label("Pick what you want to do and the seat is found for you, or click a free seat below.", "MutedText"))
        return box

    def _group(self, e: dict, g: dict, open_: bool) -> QWidget:
        signups = [s for s in e.get("signups", []) if s["groupId"] == g["id"]]
        held = [s for s in signups if not s.get("backup")]
        if g["type"] == "infantry":
            taken, total = g.get("taken", 0), g.get("slots", 0)
        else:
            taken = sum(int(bool(v["pilotTaken"])) + v["gunnersTaken"] for v in g["vehicles"])
            total = sum(1 + v["gunners"] for v in g["vehicles"])
        sec = kit.Section(g["name"])
        kind = "Ground team" if g["type"] == "infantry" else events.CATEGORIES.get(g.get("category") or "", "Ships")
        sec.head_right.addWidget(Badge(kind, "info"))
        sec.head_right.addWidget(label(f"{taken}/{total}", "StrongText"))

        def person(s: dict, what: str) -> QPushButton:
            if s.get("mine"):
                return _seat_button("You", "mine", lambda: self._mine(g, s), tip=f"Your seat: {what}")
            u = s["user"]
            tip = f"{u['displayName']} · {what}" + (f" · RSI {u['rsiHandle']}" if u.get("rsiHandle") else "")
            return _seat_button(u["displayName"], "taken", tip=tip)

        if g["type"] == "infantry":
            grid = QGridLayout()
            grid.setSpacing(6)
            spots = [person(s, "ground team") for s in held if s.get("seat") == "infantry"]
            spots += [_seat_button("+ Free spot", "free", (lambda: self._sign_up({"groupId": g["id"]})) if open_ else None)
                      for _ in range(max(0, total - len(spots)))]
            for i, w in enumerate(spots):
                grid.addWidget(w, i // 3, i % 3)
            sec.v.addLayout(grid)
        for v in g.get("vehicles", []):
            on = [s for s in held if s.get("vehicleId") == v["id"]]
            pilot = next((s for s in on if s.get("seat") == "pilot"), None)
            ship = v.get("shipName") or (pilot or {}).get("shipName")
            row = QHBoxLayout()
            row.setSpacing(6)
            name = label(f"<b style='color:{PALETTE['info']}'>{html.escape(ship)}</b>" if ship else "Open spot",
                         "BodyText" if ship else "MutedText", rich=True)
            name.setFixedWidth(170)
            row.addWidget(name)
            if pilot:
                row.addWidget(person(pilot, "pilot"))
            elif v.get("ship"):
                row.addWidget(_seat_button("+ Pilot", "free", (lambda _c=False, vid=v["id"]: self._sign_up(
                    {"groupId": g["id"], "vehicleId": vid, "seat": "pilot"})) if open_ else None))
            else:
                bring = _seat_button("+ Bring a ship", "free")
                if open_:
                    bring.setCursor(Qt.PointingHandCursor)
                    bring.clicked.connect(lambda _c=False, b=bring, vid=v["id"]: self._bring_menu(b, g, vid))
                row.addWidget(bring)
            row.addStretch(1)
            sec.v.addLayout(row)
            gunners = [person(s, "gunner") for s in on if s.get("seat") == "gunner"]
            gunners += [_seat_button("+ Gunner", "free", (lambda _c=False, vid=v["id"]: self._sign_up(
                {"groupId": g["id"], "vehicleId": vid, "seat": "gunner"})) if open_ else None)
                for _ in range(max(0, v["gunners"] - v["gunnersTaken"]))]
            if gunners:
                grid = QGridLayout()
                grid.setContentsMargins(176, 0, 0, 4)
                grid.setSpacing(6)
                for i, w in enumerate(gunners):
                    grid.addWidget(w, i // GUNNERS_PER_ROW, i % GUNNERS_PER_ROW)
                grid.setColumnStretch(GUNNERS_PER_ROW, 1)
                sec.v.addLayout(grid)
        backups = [("you" if s.get("mine") else s["user"]["displayName"]) for s in signups if s.get("backup")]
        foot = [label(f"Backup: {', '.join(backups)}" if backups else "No backups", "MutedText")]
        mine = next((s for s in signups if s.get("mine")), None)
        if open_ and (mine is None or mine.get("backup")):
            if mine:
                foot.append(kit.button("Leave backup", "ghost", lambda: self._leave(g["id"])))
            else:
                foot.append(kit.button("Join as backup", "ghost",
                                       lambda: self._sign_up({"groupId": g["id"], "backup": True})))
        sec.v.addLayout(_row(*foot))
        return sec

    # -- choosing a ship --------------------------------------------------------------------
    def _hangar_ships(self) -> list[tuple[str, str]]:
        seen, out = set(), []
        for entry in hangar.load():
            if entry.ship and entry.ship not in seen:
                seen.add(entry.ship)
                out.append((entry.ship, entry.ship_name or entry.ship))
        return sorted(out, key=lambda x: x[1])

    def _fly_menu(self, anchor: QWidget) -> None:
        """"Fly a ship": the organizer's free ships, then yours from My Ships (the service puts
        yours where it fits: the organizer's same ship first, else an open spot)."""
        e = self.detail or {}
        menu = QMenu(self)
        fixed = [(g, v) for g in e.get("groups", []) for v in g.get("vehicles", []) if v.get("ship") and not v["pilotTaken"]]
        if fixed:
            menu.addSection("The organizer's ships")
            for g, v in fixed:
                menu.addAction(f"{v.get('shipName') or v['ship']}  ·  {g['name']}",
                               lambda gid=g["id"], vid=v["id"]: self._sign_up({"groupId": gid, "vehicleId": vid, "seat": "pilot"}))
        if any(not v.get("ship") and not v["pilotTaken"] for g in e.get("groups", []) for v in g.get("vehicles", [])):
            menu.addSection("Bring one of yours")
            ships = self._hangar_ships()
            for key, name in ships:
                menu.addAction(name, lambda k=key: self._sign_up({"role": "pilot", "ship": k}))
            if not ships:
                act = menu.addAction("Add your ships in My Ships to bring one")
                act.setEnabled(False)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _bring_menu(self, anchor: QWidget, g: dict, vehicle_id: str) -> None:
        menu = QMenu(self)
        menu.addSection(f"Bring a {events.CATEGORIES.get(g.get('category') or '', '').lower()} ship")
        ships = self._hangar_ships()
        for key, name in ships:
            menu.addAction(name, lambda k=key: self._sign_up({"groupId": g["id"], "vehicleId": vehicle_id, "seat": "pilot", "ship": k}))
        if not ships:
            act = menu.addAction("Add your ships in My Ships to bring one")
            act.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Pick another ship on sc-toolbox.com ↗", lambda: osutil.open_url(_web(f"/{self.selected}")))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    # -- signing up ----------------------------------------------------------------------------
    def _sign_up(self, body: dict) -> None:
        if self.selected:
            self._pending = (self.selected, body)
            self.ctl.sign_up(self.selected, body)

    def _leave(self, group_id: str) -> None:
        if self.selected:
            self.ctl.leave(self.selected, group_id)

    def _backup_anywhere(self) -> None:
        """Backup without picking a group: the first full one (where a spot may open), else the first."""
        groups = (self.detail or {}).get("groups", [])
        if not groups:
            return
        full = next((g for g in groups if _has_room({"groups": [g]}) is False), groups[0])
        self._sign_up({"groupId": full["id"], "backup": True})

    def _mine(self, g: dict, s: dict) -> None:
        menu = QMenu(self)
        v = next((x for x in g.get("vehicles", []) if x["id"] == s.get("vehicleId")), None)
        if s.get("seat") == "pilot" and v is not None and not v.get("ship"):
            for key, name in self._hangar_ships():
                menu.addAction(f"Fly my {name} instead", lambda k=key: self._sign_up(
                    {"groupId": g["id"], "vehicleId": v["id"], "seat": "pilot", "ship": k}))
            menu.addSeparator()
        menu.addAction("Leave this seat", lambda: self._leave(g["id"]))
        menu.exec(self.cursor().pos())

    def _on_failed(self, message: str, code: str, data: dict) -> None:
        if code == "seat_conflict" and self._pending:
            event_id, body = self._pending
            held = data.get("held") or {}
            group = next((g["name"] for g in (self.detail or {}).get("groups", []) if g["id"] == held.get("groupId")), "another group")
            seat = "ground team" if held.get("seat") == "infantry" else held.get("seat", "a seat")
            answer = QMessageBox.question(self, "Move to this seat?",
                                          f"You're already signed up as {seat} in {group}. Taking this seat gives that one up.",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.ctl.sign_up(event_id, dict(body, move=True))
            return
        if code == "no_free_seat" and data.get("openSpotCategories"):
            message += " Use “Fly a ship” to bring one of yours."
        self.notice.show_text(html.escape(message), "danger")
