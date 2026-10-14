"""The launcher's shared components. Every tool view is built from these, so
the tools look and behave alike; the names follow the website's components
(PageHeader, FilterBar, AppBadge, EmptyState…) so both describe the same
things.

A tool view is a ToolPage: header (icon, title, one line on what it's for,
a data badge, the actions), a FilterBar, a ResultLine (count, active filters
as removable chips, Clear filters, "How to read this"), an optional Notice,
then the body. Selection is steel (info), the one main action amber; see
app.theme for what each colour means.

Density: launcher views use the default ("comfortable"); the overlay passes
compact=True where offered, which tightens spacing but never shrinks text.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import config, osutil
from app.theme import PALETTE, hue as hue_colour


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def icon(name: str) -> QIcon:
    return QIcon(str(config.ICONS_DIR / f"{name}.png"))


def label(text: str = "", name: str = "BodyText", *, wrap: bool = False, tip: str = "",
          align=None, rich: bool = False) -> QLabel:
    lbl = QLabel(text, objectName=name)
    lbl.setWordWrap(wrap)
    if tip:
        lbl.setToolTip(tip)
    if align is not None:
        lbl.setAlignment(align)
    if rich:
        lbl.setTextFormat(Qt.RichText)
    return lbl


def caps(text: str) -> QLabel:
    """A small uppercase field label (FILTER, SORT, column heads)."""
    return label(text.upper(), "CapsLabel")


def button(text: str, kind: str = "secondary", slot=None, *, tip: str = "", checkable: bool = False) -> QPushButton:
    """kind: primary (amber: the view's one main action), secondary, ghost (a text link)."""
    btn = QPushButton(text, objectName="KitButton")
    btn.setProperty("kind", kind)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setCheckable(checkable)
    if tip:
        btn.setToolTip(tip)
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


def panel(name: str = "Panel") -> QFrame:
    """The glass card everything readable sits on."""
    return QFrame(objectName=name)


def scroll_area() -> QScrollArea:
    area = QScrollArea(objectName="KitScroll")
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setFrameShape(QFrame.NoFrame)
    return area


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def short_date(ts: float | None, never: str = "never") -> str:
    """'13 Oct' in English whatever the system locale (the UI is English)."""
    if not ts:
        return never
    import time

    t = time.localtime(ts)
    return f"{t.tm_mday} {MONTHS[t.tm_mon - 1]}"


def drop(widget: QWidget) -> None:
    """Removes a widget now (deleteLater alone leaves it on screen until the
    event loop gets back to it)."""
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            drop(item.widget())
        elif item.layout() is not None:
            clear_layout(item.layout())


# -- small pieces -------------------------------------------------------------------

class Badge(QLabel):
    """A status (variant: neutral, info, success, warning, danger, accent; filled) or a
    category (hue: a star system or hue name; outlined, never a status)."""

    def __init__(self, text: str, variant: str = "neutral", hue: str | None = None, tip: str = "", parent=None):
        super().__init__(text, parent, objectName="Badge")
        self.setProperty("variant", "hue" if hue else variant)
        if hue:
            c = hue_colour(hue)
            self.setStyleSheet(f"color: {c}; border: 1px solid {c};")
        if tip:
            self.setToolTip(tip)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


class Rarity(QLabel):
    """● COMMON / ● LEGENDARY in the rarity's colour."""

    def __init__(self, rarity: str, parent=None):
        from app.theme import RARITY

        super().__init__(f"●  {rarity.upper()}", parent, objectName="Rarity")
        self.setStyleSheet(f"color: {RARITY.get(rarity, PALETTE['text_muted'])};")


class Dot(QWidget):
    def __init__(self, colour: str, size: int = 8, parent=None):
        super().__init__(parent)
        self._colour = QColor(colour)
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._colour)
        p.drawEllipse(QRectF(self.rect()))


class Bar(QWidget):
    """A thin horizontal bar: `value` 0–1 of the track, steel or a colour."""

    def __init__(self, value: float, colour: str | None = None, width: int = 64, height: int = 6, parent=None):
        super().__init__(parent)
        self.value = max(0.0, min(1.0, value))
        self.colour = QColor(colour or PALETTE["info"])
        self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)
        else:
            self.setMinimumWidth(40)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = self.height() / 2
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(self.rect()), r, r)
        if self.value > 0:
            p.setBrush(self.colour)
            p.drawRoundedRect(QRectF(0, 0, max(self.height(), self.width() * self.value), self.height()), r, r)


class StackedBar(QWidget):
    """Shares of one value side by side: [(amount, colour)], filling `scale`
    (0–1) of the track, so rows can be compared by length too."""

    def __init__(self, parts: list[tuple[float, str]], width: int = 100, height: int = 6, tip: str = "",
                 scale: float = 1.0, parent=None):
        super().__init__(parent)
        self.parts = [(max(0.0, f), QColor(c)) for f, c in parts]
        self.scale = max(0.0, min(1.0, scale))
        self.setFixedSize(width, height)
        if tip:
            self.setToolTip(tip)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = self.height() / 2
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(self.rect()), r, r)
        total = sum(f for f, _ in self.parts) or 1
        x = 0.0
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, self.width() * self.scale, self.height()), r, r)
        p.setClipPath(clip)
        for f, colour in self.parts:
            w = self.width() * self.scale * f / total
            p.setBrush(colour)
            p.drawRect(QRectF(x, 0, w, self.height()))
            x += w


# -- controls -----------------------------------------------------------------------

class Segmented(QWidget):
    """Buttons that pick one option (or several, with multi=True). Emits the
    picked key (multi: the list of keys)."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[object, str]] = (), value=None, *, multi: bool = False,
                 compact: bool = False, parent=None):
        super().__init__(parent)
        self.multi = multi
        self.compact = compact
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(not multi)
        self._keys: list = []
        self.set_options(options, value)

    def set_options(self, options, value=None) -> None:
        for btn in self._group.buttons():
            self._group.removeButton(btn)
            self._row.removeWidget(btn)
            drop(btn)
        self._keys = []
        for i, (key, text) in enumerate(options):
            btn = QPushButton(text, objectName="Segment")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("compact", self.compact)
            if i == 0:
                btn.setProperty("pos", "first")
            if i == len(options) - 1:
                btn.setProperty("pos", "last" if len(options) > 1 else "only")
            btn.clicked.connect(lambda _c=False, k=key: self._clicked(k))
            self._group.addButton(btn)
            self._row.addWidget(btn)
            self._keys.append(key)
        self.set_value(value)

    def set_value(self, value) -> None:
        values = set(value or []) if self.multi else {value}
        for key, btn in zip(self._keys, self._group.buttons()):
            btn.setChecked(key in values)

    def value(self):
        picked = [k for k, b in zip(self._keys, self._group.buttons()) if b.isChecked()]
        return picked if self.multi else (picked[0] if picked else None)

    def _clicked(self, _key) -> None:
        self.changed.emit(self.value())


class Dropdown(QComboBox):
    """A select whose border turns steel while it's set to anything but its
    first ("Any …") option."""

    def __init__(self, items: list[tuple[str, object]] = (), *, min_width: int = 0, tip: str = "",
                 marks: bool = True, parent=None):
        super().__init__(parent, objectName="ConfigCombo")
        self._marks = marks
        for text, data in items:
            self.addItem(text, data)
        if min_width:
            self.setMinimumWidth(min_width)
        if tip:
            self.setToolTip(tip)
        self.currentIndexChanged.connect(self._mark)
        self._mark()

    def _mark(self, *_):
        self.setProperty("set", self._marks and self.currentIndex() > 0)
        repolish(self)


class SearchField(QLineEdit):
    def __init__(self, placeholder: str = "Search…", parent=None):
        super().__init__(parent, objectName="SearchField")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.text():
            self.clear()
            return
        super().keyPressEvent(event)


# -- page structure -------------------------------------------------------------------

class FilterBar(QFrame):
    """Search left, filters in the middle, sort right; wraps nothing (keep it
    to what fits the minimum window width)."""

    def __init__(self, parent=None):
        super().__init__(parent, objectName="FilterBar")
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(10, 7, 10, 7)
        self.row.setSpacing(8)
        self.search: SearchField | None = None
        self._has_stretch = False

    def add_search(self, placeholder: str = "Search…", width: int = 240) -> SearchField:
        self.search = SearchField(placeholder)
        self.search.setMinimumWidth(160)
        self.search.setMaximumWidth(width)
        self.row.addWidget(self.search, stretch=1)
        return self.search

    def add(self, widget: QWidget, caption: str = "") -> QWidget:
        if caption:
            self.row.addWidget(caps(caption))
        self.row.addWidget(widget)
        return widget

    def add_spacing(self, px: int = 8) -> None:
        self.row.addSpacing(px)

    def add_stretch(self) -> None:
        self.row.addStretch(1)
        self._has_stretch = True

    def add_sort(self, combo: QComboBox) -> QComboBox:
        if not self._has_stretch:
            self.add_stretch()
        self.row.addWidget(caps("Sort"))
        self.row.addWidget(combo)
        return combo

    def add_right(self, widget: QWidget) -> QWidget:
        if not self._has_stretch:
            self.add_stretch()
        self.row.addWidget(widget)
        return widget


class _Chip(QPushButton):
    def __init__(self, text: str, on_remove, parent=None):
        super().__init__(f"{text}  ✕", parent, objectName="FilterChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Remove this filter")
        self.clicked.connect(on_remove)


class ResultLine(QWidget):
    """'15 claim ships' · active filters as removable chips · Clear filters ·
    (right) How to read this."""

    clear_requested = Signal()
    help_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, objectName="ResultLine")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(8)
        self.count = label("", "ResultCount")
        self.count.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.count.setMinimumWidth(120)
        row.addWidget(self.count, stretch=0)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        row.addLayout(self._chips)
        self.clear = button("Clear filters", "ghost", self.clear_requested.emit)
        self.clear.hide()
        row.addWidget(self.clear)
        row.addStretch(1)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(10)
        row.addLayout(self.extra)
        self.help = button("?  How to read this", "ghost", checkable=True)
        self.help.setObjectName("HelpToggle")
        self.help.toggled.connect(self.help_toggled.emit)
        self.help.hide()
        row.addWidget(self.help)

    def set_count(self, text: str) -> None:
        self.count.setText(text)
        self.count.setToolTip(text)
        self.count.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_chips(self, chips: list[tuple[str, object]], clearable: bool | None = None) -> None:
        """chips: [(label, remove callback)]; Clear filters shows while any filter is set."""
        clear_layout(self._chips)
        for text, remove in chips:
            self._chips.addWidget(_Chip(text, remove))
        self.clear.setVisible(bool(chips) if clearable is None else clearable)


class EmptyState(QFrame):
    """A headline, one sentence and (optionally) one action: for empty, no
    results, offline, loading and error states."""

    def __init__(self, title: str = "", text: str = "", action: str = "", slot=None, parent=None):
        super().__init__(parent, objectName="EmptyState")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 28, 24, 28)
        v.setSpacing(8)
        v.addStretch(1)
        self.title = label(title, "EmptyTitle", align=Qt.AlignCenter, wrap=True)
        self.text = label(text, "EmptyText", align=Qt.AlignCenter, wrap=True)
        self.text.setMaximumWidth(520)
        v.addWidget(self.title)
        v.addWidget(self.text, alignment=Qt.AlignHCenter)
        self.action = button(action or "", "secondary")
        self.action.setVisible(bool(action))
        self._slot = slot
        self.action.clicked.connect(lambda: self._slot and self._slot())
        v.addSpacing(4)
        v.addWidget(self.action, alignment=Qt.AlignHCenter)
        v.addStretch(2)

    def set(self, title: str, text: str = "", action: str = "", slot=None, kind: str = "secondary") -> "EmptyState":
        self.title.setText(title)
        self.title.setVisible(bool(title))
        self.text.setText(text)
        self.text.setVisible(bool(text))
        self.action.setText(action)
        self.action.setProperty("kind", kind)
        repolish(self.action)
        self.action.setVisible(bool(action))
        self._slot = slot
        return self


class Notice(QFrame):
    """A one-line banner about the data itself (info / warning / danger /
    success), optionally dismissible."""

    def __init__(self, parent=None):
        super().__init__(parent, objectName="Notice")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 7, 8, 7)
        row.setSpacing(10)
        self.text = label("", "NoticeText", wrap=True, rich=True)
        self.text.setOpenExternalLinks(True)
        row.addWidget(self.text, stretch=1)
        self.close_btn = QPushButton("✕", objectName="NoticeClose")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.clicked.connect(self.hide)
        row.addWidget(self.close_btn, alignment=Qt.AlignTop)
        self.hide()

    def show_text(self, text: str, tone: str = "info", dismissible: bool = True) -> None:
        self.text.setText(text)
        self.setProperty("tone", tone)
        repolish(self)
        self.close_btn.setVisible(dismissible)
        self.setVisible(bool(text))


class Stat(QWidget):
    """A big number over a small label (and an optional change line)."""

    def __init__(self, value: str, caption: str, *, tip: str = "", size: str = "lg", tone: str = "",
                 delta: str = "", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self.value = label(value, "StatBig" if size == "lg" else "StatMid", tip=tip)
        if tone:
            self.value.setProperty("tone", tone)
        v.addWidget(self.value)
        cap = QHBoxLayout()
        cap.setSpacing(6)
        cap.addWidget(label(caption, "StatCaption", tip=tip, wrap=True), stretch=1)
        if delta:
            cap.addWidget(label(delta, "StatDelta"))
        v.addLayout(cap)


class StatStrip(QFrame):
    """Up to four headline figures side by side, divided by hairlines."""

    def __init__(self, stats: list[tuple[str, str, str]], parent=None):
        super().__init__(parent, objectName="Panel")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for i, (value, caption, tip) in enumerate(stats):
            cell = QFrame(objectName="StripCell" if i else "StripCellFirst")
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(16, 12, 16, 12)
            cv.addWidget(Stat(value, caption, tip=tip))
            row.addWidget(cell, stretch=1)


class RankList(QWidget):
    """Name · bar · value rows, the top `limit` first with "Show all n" to
    expand in place. rows: [(name, number, shown value)]."""

    def __init__(self, rows: list[tuple[str, float, str]], limit: int = 5, colour: str | None = None,
                 bar_width: int = 110, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.limit = limit
        self.colour = colour
        self.bar_width = bar_width
        self.expanded = False
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(4)
        self._grid_host = None
        self.more = button("", "ghost", self._toggle)
        self._render()

    def _toggle(self):
        self.expanded = not self.expanded
        self._render()

    def _render(self):
        if self._grid_host is not None:
            drop(self._grid_host)
        self._grid_host = QWidget()
        grid = QGridLayout(self._grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        peak = max((n for _, n, _ in self.rows), default=0) or 1
        shown = self.rows if self.expanded or len(self.rows) <= self.limit else self.rows[:self.limit]
        for r, (name, number, value) in enumerate(shown):
            lbl = label(name, "RankName", tip=name)
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            grid.addWidget(lbl, r, 0)
            grid.addWidget(Bar(number / peak, self.colour, self.bar_width), r, 1, Qt.AlignVCenter)
            grid.addWidget(label(value, "RankValue", align=Qt.AlignRight | Qt.AlignVCenter), r, 2)
        grid.setColumnStretch(0, 1)
        self._v.insertWidget(0, self._grid_host)
        extra = len(self.rows) - self.limit
        self.more.setVisible(extra > 0)
        self.more.setText("Show fewer" if self.expanded else f"Show all {len(self.rows)}")
        if self.more.parent() is None or self._v.indexOf(self.more) < 0:
            self._v.addWidget(self.more, alignment=Qt.AlignLeft)


class Section(QFrame):
    """A titled panel: CAPS TITLE (with an optional link on the right), body."""

    def __init__(self, title: str, parent=None, *, padding: tuple = (14, 12, 14, 14)):
        super().__init__(parent, objectName="Panel")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(*padding)
        self.v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = caps(title)
        head.addWidget(self.title)
        head.addStretch(1)
        self.head_right = head
        self.v.addLayout(head)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.v.addWidget(widget, stretch=stretch)
        return widget


# -- the page --------------------------------------------------------------------------

class ToolPage(QWidget):
    """The frame every tool view shares. Subclasses fill self.filters (a
    FilterBar), set self.result (ResultLine) and put their content in the body
    with set_content(); show_empty() / show_message() swap in an EmptyState.

    The main window calls activate() when the page is shown and deactivate()
    when another one is."""

    back_requested = Signal()      # kept for views that still emit it (no Back button any more)

    def __init__(self, icon_name: str, title: str, subtitle: str = "", *, web_url: str = "",
                 filters: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 18, 0)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        ic = QLabel(objectName="PageIcon")
        ic.setPixmap(icon(icon_name).pixmap(40, 40))
        ic.setFixedSize(40, 40)
        head.addWidget(ic)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = label(title, "PageTitle")
        titles.addWidget(self.title)
        self.subtitle = label(subtitle, "PageSubtitle", rich=True)
        self.subtitle.setOpenExternalLinks(True)
        self.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.subtitle.setVisible(bool(subtitle))
        titles.addWidget(self.subtitle)
        head.addLayout(titles, stretch=1)
        self.data_chip = label("", "DataChip", rich=True)
        self.data_chip.hide()
        head.addWidget(self.data_chip, alignment=Qt.AlignVCenter)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        if web_url:
            web = button("sc-toolbox.com ↗", "ghost", lambda: osutil.open_url(web_url),
                         tip="Open this tool on the website")
            self.actions.addWidget(web)
        outer.addLayout(head)

        self.filters = FilterBar()
        self.filters.setVisible(filters)
        outer.addWidget(self.filters)
        self.result = ResultLine()
        outer.addWidget(self.result)
        self.notice = Notice()
        outer.addWidget(self.notice)
        self.help_box = Notice()
        self.help_box.setObjectName("HelpBox")
        self.help_box.close_btn.clicked.connect(lambda: self.result.help.setChecked(False))
        outer.addWidget(self.help_box)
        self.result.help_toggled.connect(self._toggle_help)
        self._help_text = ""

        self.body = QStackedWidget()
        self.empty = EmptyState()
        self.body.addWidget(self.empty)
        outer.addWidget(self.body, stretch=1)
        self._content: QWidget | None = None

        QShortcut(QKeySequence("/"), self, activated=self._focus_search,
                  context=Qt.WidgetWithChildrenShortcut)

    # header
    def set_data_chip(self, html: str, tip: str = "") -> None:
        self.data_chip.setText(html)
        self.data_chip.setToolTip(tip)
        self.data_chip.setVisible(bool(html))

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.insertWidget(max(0, self.actions.count() - 0), widget)
        return widget

    # help
    def set_help(self, html: str, link: str = "How to read this") -> None:
        self._help_text = html
        self.result.help.setText(f"?  {link}")
        self.result.help.setVisible(bool(html))

    def _toggle_help(self, on: bool) -> None:
        if on:
            self.help_box.show_text(self._help_text, "info")
        else:
            self.help_box.hide()

    # body
    def set_content(self, widget: QWidget) -> None:
        if self._content is not None and self._content is not widget:
            self.body.removeWidget(self._content)
            drop(self._content)
        self._content = widget
        if self.body.indexOf(widget) < 0:
            self.body.addWidget(widget)
        self.body.setCurrentWidget(widget)

    def show_content(self) -> None:
        if self._content is not None:
            self.body.setCurrentWidget(self._content)

    def show_empty(self, title: str, text: str = "", action: str = "", slot=None, kind: str = "secondary") -> None:
        self.empty.set(title, text, action, slot, kind)
        self.body.setCurrentWidget(self.empty)

    def show_message(self, text: str) -> None:
        """Loading and progress lines ("Reading the game files… 3/9")."""
        self.show_empty("", text)

    def _focus_search(self) -> None:
        if self.filters.search is not None:
            self.filters.search.setFocus()
            self.filters.search.selectAll()

    def activate(self) -> None:
        pass

    def deactivate(self) -> None:
        pass


# -- the window's tool rail ------------------------------------------------------------

class _RailButton(QPushButton):
    def __init__(self, icon_name: str, caption: str, parent=None):
        super().__init__(parent, objectName="RailItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(64, 54)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 5)
        v.setSpacing(3)
        self.ic = QLabel()
        self.ic.setAlignment(Qt.AlignHCenter)
        self.ic.setPixmap(icon(icon_name).pixmap(26, 26))
        self.ic.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(self.ic)
        self.cap = QLabel(caption, objectName="RailCaption")
        self.cap.setAlignment(Qt.AlignHCenter)
        self.cap.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(self.cap)


class ToolRail(QFrame):
    """The labelled tool list down the left of the window: every tool one
    click away, the game's state at the bottom, then Settings."""

    selected = Signal(str)

    def __init__(self, items: list[tuple[str, str, str]], bottom: list[tuple[str, str, str]], parent=None):
        super().__init__(parent, objectName="ToolRail")
        self.setFixedWidth(74)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(2)
        self._buttons: dict[str, _RailButton] = {}
        group = QButtonGroup(self)
        for key, icon_name, caption in items:
            v.addWidget(self._add(group, key, icon_name, caption), alignment=Qt.AlignHCenter)
        v.addStretch(1)
        self.game = QLabel(objectName="RailGame")
        self.game.setAlignment(Qt.AlignHCenter)
        self.game.setWordWrap(True)
        v.addWidget(self.game)
        v.addSpacing(4)
        for key, icon_name, caption in bottom:
            v.addWidget(self._add(group, key, icon_name, caption), alignment=Qt.AlignHCenter)
        self.set_game_state("", "")

    def _add(self, group, key, icon_name, caption) -> _RailButton:
        btn = _RailButton(icon_name, caption)
        btn.clicked.connect(lambda _c=False, k=key: self.selected.emit(k))
        group.addButton(btn)
        self._buttons[key] = btn
        return btn

    def set_current(self, key: str) -> None:
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)

    def set_enabled(self, key: str, on: bool, tip: str = "") -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.setEnabled(on)
            btn.setToolTip(tip)

    def set_game_state(self, text: str, tone: str) -> None:
        """tone: success (running), warning (busy), "" (idle: shows nothing)."""
        self.game.setText(f"●<br>{text}" if text else "")
        self.game.setProperty("tone", tone)
        repolish(self.game)


QSIZE_ICON = QSize(20, 20)
