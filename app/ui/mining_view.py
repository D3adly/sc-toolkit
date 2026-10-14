"""Mining Finder: where is it, and how do I spot it on radar? Pick resources
(and a system / mining method) and see every location whose rocks hold all
of them, best chance first: each location's rock types, how often each
spawns, the radar signature (one rock, then groups) and — for the rocks that
carry a picked resource — how much of it they hold and at what quality.

All data is extracted from the game files once per build (app.mining).
"""

from __future__ import annotations

import html

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import channel as channel_mod, datahub, mining, settings
from app.theme import PALETTE, RARITY
from app.ui import kit
from app.ui.kit import Badge, label

WEB_URL = "https://sc-toolbox.com/mining"
KIND_LABELS = {"planet": "Planet", "moon": "Moon", "lagrange": "Lagrange point",
               "belt": "Asteroid belt", "cluster": "Asteroid cluster"}
RARITY_COLORS = RARITY
RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]

HELP = (
    "<b>Bar and %</b>: the chance that a rock spawned here is that type. With ores picked, the card's "
    "green figure is the chance a rock here carries one of them.<br>"
    "<b>RS</b>: the radar signature of one rock; then <b>×2, ×3…</b> the totals for groups of rocks, because "
    "a group scans as the sum. Match these on your scanner to know the rock and group size from afar.<br>"
    "<b>avg %</b>: the average share of the rock that is the resource (range in brackets). Many rocks hold "
    "the same resource twice, a large low-grade share and a small high-grade one: both are listed.<br>"
    "<b>Q</b>: estimated average quality, 0–1000; the little bars show how likely each quality is.<br>"
    "Picking several resources shows places that have all of them, not necessarily in the same rock."
)


def _pct(value: float) -> str:
    return f"{value:.1f}%" if value < 10 else f"{value:.0f}%"


def _chance(p: float) -> str:
    if p >= 10:
        return f"{p:.0f}%"
    if p >= 1:
        return f"{p:.1f}%"
    # Two significant digits for rare outcomes (0.18%, 0.0042%); never a
    # "<" — tooltips are HTML and would swallow it as a tag.
    return f"{p:.2g}%"


def _quality_tip(name: str, q: dict) -> str:
    dist = q["dist"]
    peak = max(p for _, p in dist) or 1
    rows = "".join(
        f"<tr><td align='right'>Q {v}</td><td align='right'>&nbsp;{html.escape(_chance(p))}&nbsp;</td>"
        f"<td><span style='color:{PALETTE['info']}'>"
        f"{'▇' * max(1, round(12 * p / peak)) if p >= 0.05 else '·'}</span></td></tr>"
        for v, p in dist
    )
    tail = []
    for threshold in (700, 900):
        share = sum(p for v, p in dist if v >= threshold)
        if 0 < share < 100:
            tail.append(f"Q ≥ {threshold}: <b>{html.escape(_chance(share))}</b>")
    return (f"<b>{name}</b> — chance of each quality<br>"
            f"<table cellspacing='0' cellpadding='1'>{rows}</table>"
            + ("<br>" + " &nbsp; ".join(tail) if tail else "")
            + "<br><i>Estimated from the game's quality settings.</i>")


class _QualityHist(QWidget):
    """Tiny histogram: one bar per possible quality, height ~ its chance
    (square-root scaled so rare high qualities stay visible); higher
    qualities brighter."""

    def __init__(self, dist: list, parent=None):
        super().__init__(parent)
        self.dist = dist
        self.setFixedSize(max(24, 7 * len(dist)), 16)

    def paintEvent(self, _event):
        if not self.dist:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        peak = max(x for _, x in self.dist) or 1
        low, high = QColor(PALETTE["text_muted"]), QColor(PALETTE["info"])
        for i, (value, chance) in enumerate(self.dist):
            h = max(1.5, (chance / peak) ** 0.5 * self.height()) if chance > 0 else 0
            t = max(0.0, min(1.0, (value - 300) / 700))
            p.setBrush(QColor(
                round(low.red() + (high.red() - low.red()) * t),
                round(low.green() + (high.green() - low.green()) * t),
                round(low.blue() + (high.blue() - low.blue()) * t),
            ))
            p.drawRect(QRectF(i * 7, self.height() - h, 5, h))


def _signature_line(rock: dict, item: dict, method: str, strong: bool = True) -> tuple[str, str]:
    """('RS 3825  ×2 7650  ×3 11475 …', tooltip) — the scanner shows a
    group of rocks as the sum of their signatures.
    """
    sig = rock.get("signature") or 0
    if not sig:
        return "", ""
    muted = PALETTE["text_muted"]
    clus = item.get("cluster") or {}
    sizes = clus.get("sizes") or []
    top = max((n for n, _ in sizes), default=1)
    text = (f"<span style='color:{PALETTE['text_primary']}'><b>RS {sig}</b></span>" if strong
            else f"<span style='color:{PALETTE['text_muted']}'>RS {sig}</span>")
    if method == "ship":
        text += "".join(f"&nbsp;&nbsp;<span style='color:{muted}'>×{n}</span>&nbsp;{sig * n}"
                        for n in range(2, top + 1))
    tip = f"Radar signature of one {rock['name']} rock: {sig}."
    if sizes:
        spread = ", ".join(f"{p:.0f}% ×{n}" for n, p in sizes)
        chance = clus.get("chance", 100)
        tip += (f"\nSpawns in groups of {sizes[0][0]}–{top} ({spread})"
                + (f"; {chance:.0f}% of spawns are groups, the rest single rocks" if chance < 100 else "")
                + ".\nA group scans as the sum of its rocks, so these multiples identify the "
                  "rock type and group size from a distance.")
    return text, tip


def resource_rarity(data: dict) -> dict[str, str]:
    """Each resource's rarity: that of the rock where it makes up the largest share."""
    best: dict[str, tuple[float, str]] = {}
    for rock in data["rocks"].values():
        for part in rock["parts"]:
            if rock.get("rarity") and part["avg"] > best.get(part["res"], (-1, ""))[0]:
                best[part["res"]] = (part["avg"], rock["rarity"])
    return {res: rarity for res, (_avg, rarity) in best.items()}


# -- one location --------------------------------------------------------------

class LocationCard(QWidget):
    def __init__(self, loc: dict, method: str, data: dict, picked: list[str], show_system: bool, parent=None):
        super().__init__(parent)
        rocks, resources = data["rocks"], data["resources"]
        quality = data["quality"]
        items = loc["groups"].get(method, [])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = kit.panel()
        outer.addWidget(frame)
        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 11, 14, 12)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label(loc["name"], "CardTitle"))
        kind = KIND_LABELS.get(loc["kind"], loc["kind"].title())
        if loc["parent"] and loc["kind"] in ("moon", "lagrange"):
            kind += f" · {loc['parent']}"
        head.addWidget(Badge(kind))
        if show_system:
            head.addWidget(Badge(loc["system"].title(), hue=loc["system"]))
        head.addStretch(1)
        if picked:
            # How likely a random rock here is to carry one of the picked resources.
            share = sum(i["chance"] for i in items
                        if any(p["res"] in picked for p in rocks[i["rock"]]["parts"]))
            chance = label(f"<b>{_pct(share)}</b> of rocks", "ChanceText", rich=True,
                           tip="Chance that a rock spawned here carries " +
                               " or ".join(resources[r]["name"] for r in picked))
            head.addWidget(chance)
        v.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        row = 0
        for item in items:
            rock = rocks[item["rock"]]
            hits = [p for p in rock["parts"] if p["res"] in picked]
            dim = bool(picked) and not hits
            colour = PALETTE["success"] if hits else (PALETTE["text_muted"] if dim else PALETTE["text_secondary"])
            bar = kit.Bar(item["chance"] / 100, colour, 54, 5)
            grid.addWidget(bar, row, 0, Qt.AlignVCenter)
            grid.addWidget(label(_pct(item["chance"]), "RockPctHit" if hits else ("RockPctDim" if dim else "RockPct"),
                                 tip="Chance that a rock spawned here is this type",
                                 align=Qt.AlignRight | Qt.AlignVCenter), row, 1)
            name = rock["name"] + (" asteroid" if rock["asteroid"] else "")
            grid.addWidget(label(name, "RockNameHit" if hits else ("RockNameDim" if dim else "RockName"),
                                 tip=self._composition_tip(rock, resources)), row, 2)
            if rock["rarity"]:
                rarity = kit.Rarity(rock["rarity"])
                if dim:
                    rarity.setStyleSheet(f"color: {PALETTE['text_muted']};")
                grid.addWidget(rarity, row, 3, Qt.AlignRight | Qt.AlignVCenter)
            row += 1

            sig_text, sig_tip = _signature_line(rock, item, method, strong=not dim)
            if sig_text:
                sig = label(sig_text, "SignatureDim" if dim else "Signature", tip=sig_tip, rich=True)
                grid.addWidget(sig, row, 2, 1, 2)
                row += 1

            for part in hits:
                q = quality.get(part["res"], {}).get(loc["system"], {}).get(str(part["scale"]))
                rng = f"{part['min']:g}–{part['max']:g}%"
                if part["prob"] < 1:
                    rng += f", in {part['prob'] * 100:.0f}% of rocks"
                detail = QHBoxLayout()
                detail.setSpacing(8)
                detail.addWidget(label(f"↳ {resources[part['res']]['name']}", "MatchText"))
                detail.addWidget(label(f"avg {_pct(part['avg'])}", "StrongText",
                                       tip="Average share of the rock's mass"))
                detail.addWidget(label(f"({rng})", "MutedText"))
                if q is not None:
                    tip = _quality_tip(resources[part["res"]]["name"], q)
                    detail.addWidget(label(f"Q ≈ {q['avg']}", "StrongText", tip=tip))
                    hist = _QualityHist(q["dist"])
                    hist.setToolTip(tip)
                    detail.addWidget(hist)
                detail.addStretch(1)
                grid.addLayout(detail, row, 2, 1, 2)
                row += 1
        grid.setColumnStretch(2, 1)
        v.addLayout(grid)

    @staticmethod
    def _composition_tip(rock: dict, resources: dict) -> str:
        lines = ["Composition:"]
        for p in rock["parts"]:
            lines.append(f"  {resources.get(p['res'], {}).get('name', p['res'])}: "
                         f"{p['min']:g}–{p['max']:g}% (avg {p['avg']:g}%)")
        return "\n".join(lines)


# -- the resource picker --------------------------------------------------------------

class _PickRow(QPushButton):
    def __init__(self, name: str, count: int, rarity: str | None, parent=None):
        super().__init__(parent, objectName="PickRow")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.name = name
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)
        self.box = box = QWidget(objectName="PickBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedSize(13, 13)
        box.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(box)
        self.toggled.connect(self._sync)
        dot = kit.Dot(RARITY.get(rarity or "", PALETTE["text_muted"]), 7)
        dot.setToolTip(rarity or "")
        row.addWidget(dot)
        text = label(name, "PickName")
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(text, stretch=1)
        n = label(str(count), "PickCount")
        n.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(n)
        self.setToolTip(f"{name}: found at {count} location{'s' if count != 1 else ''}"
                        + (f" · {rarity}" if rarity else ""))
        self.text = text

    def _sync(self, on: bool) -> None:
        for w in (self.box, self.text):
            w.setProperty("on", on)
            kit.repolish(w)


# -- the view ------------------------------------------------------------------------

class MiningView(kit.ToolPage):
    def __init__(self, channel: str, parent=None):
        super().__init__("mining", "Mining Finder",
                         "Where each ore spawns, its radar signature and quality odds, from the game files",
                         web_url=WEB_URL, parent=parent)
        self.paths = channel_mod.resolve_channel_paths(settings.current().game_root, channel)
        self.data: dict | None = None
        self.system: str | None = None   # None = all systems
        self.method = "ship"
        self.picked: list[str] = []
        self._rarity: dict[str, str] = {}

        self._loader = datahub.GameDataWaiter("mining", self)
        self._loader.ready.connect(self._on_loaded)
        self._loader.progress.connect(self.show_message)
        self._loader.failed.connect(lambda msg: self.show_empty(
            "Couldn't read the game files", msg.splitlines()[0] if msg else "",
            "Open Settings", lambda: self.window().show_tool("settings")))
        self._columns = 2
        self._build_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wanted = 2 if self.locs_scroll.viewport().width() >= 760 else 1
        if wanted != self._columns:
            self._columns = wanted
            self._render()

    def _build_ui(self) -> None:
        f = self.filters
        self.systems = kit.Segmented([(None, "All")], None)
        self.systems.changed.connect(self._set_system)
        f.add(self.systems, "System")
        f.add_spacing(6)
        self.methods = kit.Segmented(list(mining.METHOD_LABELS.items()), self.method)
        self.methods.changed.connect(self._set_method)
        f.add(self.methods, "Mining")
        f.add_stretch()

        self.result.clear_requested.connect(self._clear)
        self.set_help(HELP)

        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        side = kit.panel()
        side.setFixedWidth(232)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 6, 10)
        sv.setSpacing(8)
        self.search = kit.SearchField("Find a resource…")
        self.filters.search = self.search          # "/" focuses it
        self.search.textChanged.connect(self._filter_list)
        sv.addWidget(self.search)
        self.pick_scroll = kit.scroll_area()
        host = QWidget()
        self.pick_box = QVBoxLayout(host)
        self.pick_box.setContentsMargins(0, 0, 4, 0)
        self.pick_box.setSpacing(1)
        self.pick_scroll.setWidget(host)
        sv.addWidget(self.pick_scroll, stretch=1)
        row.addWidget(side)

        self.locs_scroll = kit.scroll_area()
        self.locs_host = QWidget()
        self.locs_scroll.setWidget(self.locs_host)
        row.addWidget(self.locs_scroll, stretch=1)
        self._body = body
        self.set_content(body)
        self.show_message("Loading mining data…")

    # -- lifecycle -------------------------------------------------------------------
    def activate(self) -> None:
        if self.data is None:
            self._loader.request(self.paths.channel_root)

    def focus_on(self, resource_name: str) -> None:
        """Links from other tools: pick this resource (by its display name)."""
        if self.data is None:
            self._pending = resource_name
            return
        for res, info in self.data["resources"].items():
            if info["name"].lower() == str(resource_name).lower():
                self.picked = [res]
                self._fill_list()
                self._render()
                return

    def _on_loaded(self, data: dict) -> None:
        self.data = data
        self._rarity = resource_rarity(data)
        # Delivered again when a new game version's data is ready: rebuild.
        if self.system is not None and all(s["id"] != self.system for s in data["systems"]):
            self.system = None
        self.systems.set_options([(None, "All")] + [(s["id"], s["name"]) for s in data["systems"]], self.system)
        self._fill_list()
        self._render()
        pending = getattr(self, "_pending", None)
        if pending:
            self._pending = None
            self.focus_on(pending)

    # -- filters ----------------------------------------------------------------------
    def _set_system(self, system: str | None) -> None:
        self.system = system
        self._fill_list()
        self._render()

    def _set_method(self, method: str) -> None:
        if method is None:              # clicking the checked button again
            self.methods.set_value(self.method)
            return
        self.method = method
        self._fill_list()
        self._render()

    def _locations(self) -> list[dict]:
        return [l for l in self.data["locations"]
                if (self.system is None or l["system"] == self.system) and self.method in l["groups"]]

    def _fill_list(self) -> None:
        """Only resources that can actually be found with the current system
        and method, each with how many locations have it.
        """
        counts: dict[str, int] = {}
        for loc in self._locations():
            found = {p["res"] for i in loc["groups"][self.method]
                     for p in self.data["rocks"][i["rock"]]["parts"]}
            for res in found:
                counts[res] = counts.get(res, 0) + 1
        self.picked = [r for r in self.picked if r in counts]
        kit.clear_layout(self.pick_box)
        self._pick_rows: list[tuple[str, _PickRow]] = []
        for res in sorted(counts, key=lambda r: self.data["resources"][r]["name"]):
            row = _PickRow(self.data["resources"][res]["name"], counts[res], self._rarity.get(res))
            row.setChecked(res in self.picked)
            row._sync(res in self.picked)
            row.toggled.connect(lambda on, r=res: self._toggle(r, on))
            self.pick_box.addWidget(row)
            self._pick_rows.append((res, row))
        self.pick_box.addStretch(1)
        self._filter_list(self.search.text())

    def _filter_list(self, text: str) -> None:
        text = text.strip().lower()
        for _res, row in getattr(self, "_pick_rows", []):
            row.setVisible(not text or text in row.name.lower())

    def _toggle(self, res: str, on: bool) -> None:
        if on and res not in self.picked:
            self.picked.append(res)
        elif not on and res in self.picked:
            self.picked.remove(res)
        self._render()

    def _unpick(self, res: str) -> None:
        for r, row in self._pick_rows:
            if r == res:
                row.setChecked(False)

    def _clear(self) -> None:
        self.picked = []
        self._fill_list()
        self._render()

    # -- rendering ------------------------------------------------------------------------
    def _share(self, loc: dict, res: str) -> float:
        rocks = self.data["rocks"]
        return sum(i["chance"] for i in loc["groups"][self.method]
                   if any(p["res"] == res for p in rocks[i["rock"]]["parts"]))

    def _render(self) -> None:
        if self.data is None:
            return
        locs = self._locations()
        total = len(locs)
        names = {r: self.data["resources"][r]["name"] for r in self.picked}
        if self.picked:
            locs = [l for l in locs if all(self._share(l, r) > 0 for r in self.picked)]
            # Best first: the place where the rarest picked resource is most common.
            locs.sort(key=lambda l: -min(self._share(l, r) for r in self.picked))
            self.result.set_count(f"{len(locs)} of {total} places have " + " and ".join(names.values())
                                  + " · best chance first")
        else:
            self.result.set_count(f"{total} locations · pick resources on the left to find where they are")
        self.result.set_chips([(names[r], lambda _c=False, r=r: self._unpick(r)) for r in self.picked])

        self.show_content()
        if not locs:
            # In the results column, so the picker stays.
            self.locs_scroll.setWidget(kit.EmptyState(
                "No place has all of them",
                "These resources never spawn at the same location. Remove one to see the places "
                "that have the others.", "Clear", self._clear))
            return
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        cols = QHBoxLayout(host)
        cols.setContentsMargins(0, 0, 6, 0)
        cols.setSpacing(10)
        columns, heights = [], []
        for _ in range(self._columns):
            col = QVBoxLayout()
            col.setSpacing(10)
            cols.addLayout(col, stretch=1)
            columns.append(col)
            heights.append(0)
        for loc in locs:
            card = LocationCard(loc, self.method, self.data, self.picked, self.system is None)
            i = heights.index(min(heights))  # masonry: shortest column first
            columns[i].addWidget(card)
            heights[i] += card.sizeHint().height() + 10
        for col in columns:
            col.addStretch(1)
        keep = self.locs_scroll.verticalScrollBar().value()
        self.locs_scroll.setWidget(host)
        self.locs_scroll.verticalScrollBar().setValue(keep)
