"""The overlay's event reminder: one line under the bar for the next op you're signed up for
(within REMIND_HOURS, or running), with its countdown. Clicking it unfolds the details: when,
your seat, muster point, comms, who's still missing, the briefing. The overlay isn't signed in
itself: the launcher keeps app.events.UPCOMING_FILE up to date and this reads it.
"""

from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app import config, events, ipc

REMIND_HOURS = 72           # an op further away than this isn't worth a line on screen
RELOAD_MS = 30_000          # re-read the launcher's file
BRIEFING_CHARS = 400


class EventReminder(QFrame):
    resized = Signal()          # shown, hidden, unfolded or folded: the overlay fits itself again

    def __init__(self, hint=None, parent=None):
        super().__init__(parent, objectName="OverlayReminder")
        self.op: dict | None = None
        self.open = False
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 5, 6, 5)
        v.setSpacing(4)
        self.line = QPushButton(objectName="OverlayReminderLine")
        self.line.setCursor(Qt.PointingHandCursor)
        self.line.clicked.connect(self.toggle)
        row = QHBoxLayout(self.line)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(QIcon(str(config.ICONS_DIR / "events.png")).pixmap(18, 18))
        icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(icon)
        self.title = QLabel("", objectName="OverlayReminderTitle")
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.title, stretch=1)
        self.count = QLabel("", objectName="OverlayReminderCount")
        self.count.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.count)
        self.chevron = QLabel("▾", objectName="OverlayReminderText")
        self.chevron.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.chevron)
        v.addWidget(self.line)

        self.details = QLabel("", objectName="OverlayReminderText")
        self.details.setTextFormat(Qt.RichText)
        self.details.setWordWrap(True)
        self.details.hide()
        v.addWidget(self.details)
        self.open_btn = QPushButton("Open in SC-Toolbox", objectName="OverlayMenuItem")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(lambda: self.op and ipc.send(ipc.MAIN, f"events:{self.op['id']}"))
        self.open_btn.hide()
        v.addWidget(self.open_btn)
        if hint is not None:
            hint(self.line, "<b>Your next op</b> · click for the details")

        self._reload = QTimer(self, interval=RELOAD_MS, timeout=self.reload)
        self._tick = QTimer(self, interval=1000, timeout=self._update_count)
        self._reload.start()
        self._tick.start()
        self.hide()
        self.reload()

    def reload(self) -> None:
        now = time.time()
        soon = [e for e in events.read_upcoming()
                if events.parse_time(e["startsAt"]).timestamp() - now < REMIND_HOURS * 3600
                and any(not s.get("backup") for s in e.get("mySignups", []))]
        event = soon[0] if soon else None
        changed = (event or {}).get("updatedAt") != (self.op or {}).get("updatedAt") or bool(event) != bool(self.op)
        self.op = event
        if not changed:
            return
        if event is None:
            self.open = False
            self.hide()
        else:
            self.title.setText(html.escape(event["title"]))
            self._render_details()
            self.show()
        self._update_count()
        self.resized.emit()

    def toggle(self) -> None:
        self.open = not self.open
        self._render_details()
        self.resized.emit()

    def _render_details(self) -> None:
        e = self.op
        self.chevron.setText("▴" if self.open else "▾")
        self.details.setVisible(self.open and e is not None)
        self.open_btn.setVisible(self.open and e is not None)
        if not e:
            return
        rows = [("When", events.local_time(e["startsAt"])),
                ("You", events.my_seat(e) or ""),
                ("Muster", e.get("musterPoint") or ""),
                ("Comms", e.get("comms") or ""),
                ("Crew", events.needs(events.crew(e.get("groups", []))))]
        text = "<br>".join(f"<span style='color:#a39a8a'>{k}</span>&nbsp; {html.escape(v)}" for k, v in rows if v)
        briefing = (e.get("description") or "").strip()
        if briefing:
            short = briefing if len(briefing) <= BRIEFING_CHARS else briefing[:BRIEFING_CHARS].rsplit(" ", 1)[0] + "…"
            text += "<br><br>" + html.escape(short).replace("\n", "<br>")
        self.details.setText(text)

    def _update_count(self) -> None:
        if self.op is None or not self.isVisible():
            return
        text = events.countdown(self.op["startsAt"], self.op.get("durationMinutes"))
        if text == "Over":
            self.reload()
            return
        if text != self.count.text():
            self.count.setText(text)
