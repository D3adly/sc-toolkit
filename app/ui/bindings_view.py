"""Joystick bindings view: a manual-style diagram of one stick with callouts
showing the Star Citizen actions bound to each control, plus an inspector
for identifying controls, rebinding, and saving the result as a named
launch profile.

The game's live actionmaps.xml is never written — edits are only ever saved
as profiles under the backup root, which the main view can restore before
launching.
"""

from __future__ import annotations

import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import backup, bindings, channel as channel_mod, settings, stick_photos
from app.backup import BackupInfo
from app.bindings import ActionDef, BindingProfile, GameData
from app.joyinput import AXIS_MAX, JoystickInput
from app.joystick_templates import TEMPLATES, Control, DeviceSetup, InputSlot, SetupStore
from app.theme import PALETTE

# Scene geometry: callout column | drawing | callout column.
COL_W = 300
GAP = 30
DRAW_X = COL_W + GAP
DRAW_Y = 10
MIN_SCENE_H = 780
CALLOUT_GAP = 8

AXIS_IDENTIFY_THRESHOLD = AXIS_MAX // 2

C_TEXT = QColor(PALETTE["text_primary"])
C_TEXT_2 = QColor(PALETTE["text_secondary"])
C_MUTED = QColor(PALETTE["text_muted"])
C_CYAN = QColor(PALETTE["accent_cyan"])
C_AMBER = QColor(PALETTE["accent_amber"])


def input_code(inp: str) -> str:
    """Compact label for an SC input: button12 -> B12, hat1_up -> H1↑, rotz -> RZ."""
    if not inp:
        return ""
    m = re.fullmatch(r"button(\d+)", inp)
    if m:
        return f"B{m.group(1)}"
    m = re.fullmatch(r"hat(\d+)_(up|down|left|right)", inp)
    if m:
        return f"H{m.group(1)}" + {"up": "↑", "down": "↓", "left": "←", "right": "→"}[m.group(2)]
    m = re.fullmatch(r"slider(\d+)", inp)
    if m:
        return f"S{m.group(1)}"
    return {"rotx": "RX", "roty": "RY", "rotz": "RZ"}.get(inp, inp.upper())


def _natural_key(inp: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", inp)]


# -- scene items -----------------------------------------------------------

class _Row:
    def __init__(self, tag: str, text: str, code: str, dim: bool, inp: str):
        self.tag, self.text, self.code, self.dim, self.inp = tag, text, code, dim, inp


class CalloutItem(QGraphicsObject):
    clicked = Signal(str)

    PAD = 8
    TITLE_H = 17
    ROW_H = 19

    def __init__(self, control: Control, rows: list[_Row]):
        super().__init__()
        self.control = control
        self.rows = rows
        self.selected = False
        self.target = False
        self.flash_inputs: set[str] = set()
        self.height = self.PAD * 2 + self.TITLE_H + self.ROW_H * max(1, len(rows))
        self.title_font = QFont()
        self.title_font.setPixelSize(11)
        self.title_font.setBold(True)
        self.title_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        self.row_font = QFont()
        self.row_font.setPixelSize(14)
        self.code_font = QFont()
        self.code_font.setPixelSize(10)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptedMouseButtons(Qt.LeftButton)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, COL_W, self.height)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.boundingRect().adjusted(1, 1, -1, -1)
        border = C_AMBER if (self.selected or self.target) else QColor(255, 255, 255, 34)
        if self.flash_inputs:
            border = C_CYAN
        painter.setPen(QPen(border, 1.6))
        painter.setBrush(QColor(13, 15, 18, 215))
        painter.drawRoundedRect(rect, 6, 6)

        x0 = self.PAD + 2
        painter.setFont(self.title_font)
        painter.setPen(C_AMBER if self.target else C_TEXT_2)
        painter.drawText(QRectF(x0, self.PAD, COL_W - 2 * x0, self.TITLE_H),
                         Qt.AlignLeft | Qt.AlignVCenter, self.control.label.upper())

        fm = QFontMetrics(self.row_font)
        y = self.PAD + self.TITLE_H
        for row in self.rows:
            row_rect = QRectF(4, y, COL_W - 8, self.ROW_H)
            if row.inp and row.inp in self.flash_inputs:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(95, 212, 232, 60))
                painter.drawRoundedRect(row_rect, 3, 3)
            text_x = x0
            if row.tag:
                painter.setFont(self.row_font)
                painter.setPen(C_CYAN)
                painter.drawText(QRectF(x0, y, 18, self.ROW_H), Qt.AlignLeft | Qt.AlignVCenter, row.tag)
                text_x = x0 + 20
            code_w = 34 if row.code else 0
            if row.code:
                painter.setFont(self.code_font)
                painter.setPen(C_MUTED)
                painter.drawText(QRectF(COL_W - x0 - code_w, y, code_w, self.ROW_H),
                                 Qt.AlignRight | Qt.AlignVCenter, row.code)
            painter.setFont(self.row_font)
            painter.setPen(C_MUTED if row.dim else C_TEXT)
            avail = COL_W - text_x - x0 - code_w - 4
            painter.drawText(QRectF(text_x, y, avail, self.ROW_H), Qt.AlignLeft | Qt.AlignVCenter,
                             fm.elidedText(row.text, Qt.ElideRight, int(avail)))
            y += self.ROW_H

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.control.id)
        event.accept()


class HotspotItem(QGraphicsEllipseItem):
    R = 7

    def __init__(self, control: Control, on_moved, on_clicked):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R)
        self.control = control
        self._on_moved = on_moved
        self._on_clicked = on_clicked
        self.leader: QGraphicsPathItem | None = None
        self.anchor = QPointF()
        self.set_state(False, False)
        self.setZValue(3)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def set_state(self, highlighted: bool, flashing: bool) -> None:
        color = C_CYAN if flashing else (C_AMBER if highlighted else C_CYAN)
        self.setPen(QPen(color, 2))
        fill = QColor(color)
        fill.setAlpha(200 if (highlighted or flashing) else 70)
        self.setBrush(fill)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.leader is not None:
            self.leader.setPath(_leader_path(self.pos(), self.anchor))
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if not self.flags() & QGraphicsItem.ItemIsMovable:
            self._on_clicked(self.control.id)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self.flags() & QGraphicsItem.ItemIsMovable:
            self._on_moved(self.control, self.pos())


def _leader_path(start: QPointF, end: QPointF) -> QPainterPath:
    path = QPainterPath(start)
    elbow_x = end.x() + (14 if end.x() < start.x() else -14)
    path.lineTo(elbow_x, end.y())
    path.lineTo(end)
    return path


class DiagramView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent;")
        self.setBackgroundBrush(Qt.NoBrush)

    def fit(self) -> None:
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit()


# -- async game-data loading --------------------------------------------------

class _Loader(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    photos_ready = Signal()

    def run(self, channel_root) -> None:
        def work():
            try:
                self.loaded.emit(bindings.load_game_data(channel_root))
            except Exception as exc:  # surfaced in the UI, not fatal
                self.failed.emit(str(exc))
        threading.Thread(target=work, daemon=True).start()

    def fetch_photos(self) -> None:
        def work():
            for template in TEMPLATES.values():
                stick_photos.ensure_photo(template)
            self.photos_ready.emit()
        threading.Thread(target=work, daemon=True).start()


# -- the view --------------------------------------------------------------

class BindingsView(QWidget):
    back_requested = Signal()
    profiles_changed = Signal()

    def __init__(self, channel: str, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.paths = channel_mod.resolve_channel_paths(settings.current().game_root, channel)
        self.store = SetupStore()
        self.game: GameData | None = None
        self.profile: BindingProfile | None = None
        self.source: BackupInfo | None = None  # None = the game's live profile
        self.dirty = False
        self.eff = bindings.Bindings()
        self.instance: int | None = None
        self.product = ""
        self.live_device: str | None = None
        self.setup = DeviceSetup(None, {}, {})
        self.context: str | None = None
        self.selected: str | None = None
        self.adjusting = False
        self.last_input = ""
        self.last_note = ""
        self._picker_input: str | None = None
        self._live_label: QLabel | None = None

        # identify wizard state
        self.id_queue: list[tuple[Control, InputSlot]] = []
        self.id_index = 0
        self.id_used: set[str] = set()
        self.id_baseline: dict[str, int] = {}

        self.callouts: dict[str, CalloutItem] = {}
        self.hotspots: dict[str, HotspotItem] = {}

        self.joy = JoystickInput(self)
        self.joy.pressed.connect(self._on_pressed)
        self.joy.axis.connect(self._on_axis)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._loader = _Loader(self)
        self._loader.loaded.connect(self._on_game_loaded)
        self._loader.failed.connect(self._on_game_failed)
        self._loader.photos_ready.connect(self._on_photos_ready)
        self._photos_fetched = False
        self._photos_done = False

        self._build_ui()

    # -- layout -------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 20)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        back = QPushButton("←  Back")
        back.setObjectName("ToolButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self._on_back)
        bar.addWidget(back)

        self.source_combo = QComboBox(objectName="ConfigCombo")
        self.source_combo.setToolTip("Bindings to show and edit: the game's current ones or a saved profile")
        self.source_combo.setMinimumWidth(170)
        self.source_combo.activated.connect(self._on_source_changed)
        bar.addWidget(self.source_combo)

        bar.addSpacing(6)
        self.stick_bar = QHBoxLayout()
        self.stick_bar.setSpacing(0)
        self.stick_group = QButtonGroup(self)
        self.stick_group.setExclusive(True)
        bar.addLayout(self.stick_bar)

        self.context_combo = QComboBox(objectName="ConfigCombo")
        self.context_combo.setToolTip("Only show actions from this part of the game")
        self.context_combo.setMinimumWidth(150)
        self.context_combo.activated.connect(self._on_context_changed)
        bar.addWidget(self.context_combo)

        bar.addStretch(1)

        self.save_btn = QPushButton("Save profile")
        self.save_btn.setObjectName("StartButtonSmall")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save_clicked)
        bar.addWidget(self.save_btn)
        outer.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.scene = QGraphicsScene(self)
        self.diagram = DiagramView(self.scene)
        self.diagram.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(self.diagram, stretch=1)

        panel = QFrame(objectName="SidePanel")
        panel.setFixedWidth(330)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("InspectorScroll")
        self.inspector = QWidget(objectName="Inspector")
        self.inspector_layout = QVBoxLayout(self.inspector)
        self.inspector_layout.setContentsMargins(16, 16, 16, 16)
        self.inspector_layout.setSpacing(6)
        scroll.setWidget(self.inspector)
        panel_layout.addWidget(scroll)
        body.addWidget(panel)
        outer.addLayout(body, stretch=1)

        self._set_placeholder("Loading bindings…")

    # -- lifecycle ------------------------------------------------------------
    def activate(self) -> None:
        """Called each time the view is shown."""
        self.joy.start()
        self.live_device = self.joy.find_device(self.product)
        if not self._photos_fetched:
            self._photos_fetched = True
            self._loader.fetch_photos()
        if self.game is None:
            self._loader.run(self.paths.channel_root)
        else:
            self._refresh_sources()

    def deactivate(self) -> None:
        self._stop_identify()
        self.joy.stop()

    def _on_game_loaded(self, game: GameData) -> None:
        self.game = game
        self.context_combo.clear()
        self.context_combo.addItem("All contexts", None)
        for cat in game.categories:
            self.context_combo.addItem(cat, cat)
        idx = self.context_combo.findData("Flight")
        self.context_combo.setCurrentIndex(max(idx, 0))
        self.context = self.context_combo.currentData()
        self._refresh_sources()
        self._load_source(None)

    def _on_photos_ready(self) -> None:
        self._photos_done = True
        if self.instance is not None and self.setup.template is not None:
            self._render_scene()

    def _on_game_failed(self, message: str) -> None:
        self._set_placeholder(f"Couldn't load Star Citizen's default bindings:\n\n{message}")

    # -- source (game live profile or a saved profile) ---------------------------
    def _refresh_sources(self) -> None:
        self.source_combo.clear()
        self.source_combo.addItem("Game (current)", None)
        self._profiles = backup.list_profiles(settings.current().backup_root, self.channel)
        for info in self._profiles:
            self.source_combo.addItem(f"★ {info.name}", info.path)
        if self.source is not None:
            idx = self.source_combo.findData(self.source.path)
            self.source_combo.setCurrentIndex(max(idx, 0))

    def _on_source_changed(self, index: int) -> None:
        path = self.source_combo.itemData(index)
        info = next((p for p in self._profiles if p.path == path), None)
        if (info.path if info else None) == (self.source.path if self.source else None):
            return
        if not self._confirm_discard():
            self._refresh_sources()
            return
        self._load_source(info)

    def _load_source(self, info: BackupInfo | None) -> None:
        src = (info.path / "Profile" if info else self.paths.profile_dir) / "actionmaps.xml"
        try:
            self.profile = BindingProfile.load(src)
        except (OSError, ET.ParseError) as exc:
            self._set_placeholder(f"Couldn't read {src}:\n\n{exc}")
            return
        self.source = info
        self.dirty = False
        self._update_save_btn()
        self._recompute()
        self._rebuild_stick_buttons()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", "Discard your unsaved binding changes?",
            QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        return answer == QMessageBox.Discard

    def _on_back(self) -> None:
        if self._confirm_discard():
            if self.dirty:
                self._load_source(self.source)
            self.back_requested.emit()

    # -- sticks ---------------------------------------------------------------
    def _rebuild_stick_buttons(self) -> None:
        for btn in self.stick_group.buttons():
            self.stick_group.removeButton(btn)
            btn.deleteLater()
        products = self.profile.joystick_products() if self.profile else {}
        if not products:
            self.instance = None
            self._set_placeholder(
                "This profile doesn't list any joysticks.\n\n"
                "Start the game once with your sticks plugged in so it records them."
            )
            return
        # Left stick first, matching where it sits on the desk.
        instances = sorted(products, key=lambda i: (not products[i].lower().endswith(" l"), i))
        if self.instance not in products:
            # Prefer showing the left stick first when both are present.
            self.instance = next(
                (i for i in instances if products[i].lower().endswith(" l")), instances[0]
            )
        for pos, inst in enumerate(instances):
            product = products[inst]
            short = product.split()[-1] if product.split()[-1] in ("L", "R") else f"js{inst}"
            btn = QPushButton(f"{'LEFT' if short == 'L' else 'RIGHT' if short == 'R' else short}")
            btn.setObjectName("Segment")
            btn.setProperty("pos", "first" if pos == 0 else "last" if pos == len(instances) - 1 else "mid")
            btn.setCheckable(True)
            btn.setToolTip(f"js{inst} · {product}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(inst == self.instance)
            btn.clicked.connect(lambda _c=False, i=inst: self._select_stick(i))
            self.stick_group.addButton(btn)
            self.stick_bar.addWidget(btn)
        self._select_stick(self.instance)

    def _select_stick(self, instance: int) -> None:
        self._stop_identify()
        self.instance = instance
        self.product = self.profile.joystick_products().get(instance, "")
        for btn in self.stick_group.buttons():
            btn.setChecked(btn.toolTip().startswith(f"js{instance} "))
        self.live_device = self.joy.find_device(self.product)
        self.setup = self.store.get(self.product)
        self.selected = None
        self._render()

    def _save_setup(self) -> None:
        self.store.put(self.product, self.setup)

    # -- bindings -------------------------------------------------------------
    def _recompute(self) -> None:
        if self.game and self.profile:
            self.eff = bindings.effective_bindings(self.game, self.profile)

    def _actions_for(self, inp: str, respect_context: bool = True) -> list[ActionDef]:
        if not inp or self.instance is None:
            return []
        out, seen = [], set()
        for a in self.eff.by_input.get((self.instance, inp), []):
            if not a.listed:
                continue
            if respect_context and self.context and a.category != self.context:
                continue
            if respect_context and a.label in seen:
                continue
            seen.add(a.label)
            out.append(a)
        return out

    def _bind(self, action: ActionDef, inp: str) -> None:
        previous = self.eff.by_action.get(action.key, {}).get(self.instance)
        self.profile.set_input(self.game, action.key, self.instance, inp)
        self._mark_dirty()
        if previous and inp and previous != inp:
            self.last_note = f"“{action.label}” moved from {input_code(previous)} to {input_code(inp)}"
        else:
            self.last_note = ""
        self._render()

    def _unbind(self, action: ActionDef) -> None:
        self.profile.set_input(self.game, action.key, self.instance, "")
        self.last_note = ""
        self._mark_dirty()
        self._render()

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._recompute()
        self._update_save_btn()

    def _update_save_btn(self) -> None:
        self.save_btn.setText("Save profile •" if self.dirty else "Save profile")

    # -- rendering ------------------------------------------------------------
    def _render(self) -> None:
        self._render_scene()
        self._render_inspector()

    @staticmethod
    def _scene_point(x: float, y: float) -> QPointF:
        return QPointF(DRAW_X + x, DRAW_Y + y)

    @staticmethod
    def _template_point(p: QPointF) -> tuple[float, float]:
        return (round(p.x() - DRAW_X, 1), round(p.y() - DRAW_Y, 1))

    def _rows_for(self, control: Control) -> list[_Row]:
        rows: list[_Row] = []
        single = len(control.inputs) == 1
        for slot in control.inputs:
            inp = self.setup.input_for(control, slot)
            tag = "" if single else slot.tag
            if not inp:
                rows.append(_Row(tag, "not identified", "", True, ""))
                continue
            actions = self._actions_for(inp)
            code = input_code(inp)
            if not actions:
                rows.append(_Row(tag, "—", code, True, inp))
            elif single:
                shown = actions[:3]
                for i, a in enumerate(shown):
                    text = a.label
                    if i == len(shown) - 1 and len(actions) > 3:
                        text += f"   +{len(actions) - 3} more"
                    rows.append(_Row("", text, code if i == 0 else "", False, inp))
            else:
                text = " · ".join(a.label for a in actions)
                rows.append(_Row(tag, text, code, False, inp))
        return rows

    def _render_scene(self) -> None:
        self.scene.clear()
        self.callouts.clear()
        self.hotspots.clear()
        template = self.setup.template
        width = DRAW_X * 2 + (template.size[0] if template else 400)
        if template is None:
            self.scene.setSceneRect(0, 0, width, MIN_SCENE_H)
            msg = self.scene.addText("Pick your stick model in the panel on the right →")
            msg.setDefaultTextColor(C_TEXT_2)
            f = QFont()
            f.setPixelSize(18)
            msg.setFont(f)
            msg.setPos(width / 2 - msg.boundingRect().width() / 2, MIN_SCENE_H / 2 - 20)
            self.diagram.fit()
            return

        tw, th = template.size
        # Soft light backdrop so the black stick reads against the dark UI.
        glow = QRadialGradient(QPointF(DRAW_X + tw / 2, DRAW_Y + th * 0.55), max(tw, th) * 0.6)
        glow.setColorAt(0.0, QColor(210, 215, 222, 70))
        glow.setColorAt(1.0, QColor(210, 215, 222, 0))
        backdrop = self.scene.addEllipse(
            DRAW_X + tw / 2 - tw * 0.75, DRAW_Y + th * 0.55 - th * 0.62, tw * 1.5, th * 1.24,
            QPen(Qt.NoPen), glow,
        )
        backdrop.setZValue(-1)
        photo_file = stick_photos.photo_path(template)
        if photo_file.is_file():
            photo = QGraphicsPixmapItem(QPixmap(str(photo_file)))
            photo.setTransformationMode(Qt.SmoothTransformation)
            photo.setPos(DRAW_X, DRAW_Y)
            photo.setZValue(0)
            self.scene.addItem(photo)
        else:
            msg = self.scene.addText(
                "Stick photo unavailable (no connection?)" if self._photos_done else "Downloading the stick photo…"
            )
            msg.setDefaultTextColor(C_MUTED)
            msg.setPos(DRAW_X + tw / 2 - msg.boundingRect().width() / 2, DRAW_Y + th / 2)

        mid_x = DRAW_X + template.size[0] / 2
        sides: dict[str, list[tuple[float, CalloutItem, HotspotItem]]] = {"left": [], "right": []}
        target = self._identify_target()
        for control in template.controls:
            pt = self._scene_point(*self.setup.pos_for(control))
            callout = CalloutItem(control, self._rows_for(control))
            callout.selected = control.id == self.selected
            callout.target = target is not None and target[0].id == control.id
            callout.clicked.connect(self._select_control)
            callout.setZValue(2)
            self.scene.addItem(callout)
            hotspot = HotspotItem(control, self._on_hotspot_moved, self._select_control)
            hotspot.setPos(pt)
            hotspot.set_state(callout.selected or callout.target, False)
            hotspot.setFlag(QGraphicsItem.ItemIsMovable, self.adjusting)
            self.scene.addItem(hotspot)
            self.callouts[control.id] = callout
            self.hotspots[control.id] = hotspot
            sides["left" if pt.x() < mid_x else "right"].append((pt.y(), callout, hotspot))

        scene_h = MIN_SCENE_H
        for side, items in sides.items():
            items.sort(key=lambda t: t[0])
            tops: list[float] = []
            prev_bottom = 4.0
            for anchor_y, callout, _ in items:
                top = max(anchor_y - callout.height / 2, prev_bottom + (CALLOUT_GAP if tops else 0))
                tops.append(top)
                prev_bottom = top + callout.height
            limit = MIN_SCENE_H - 4
            for i in range(len(items) - 1, -1, -1):
                callout = items[i][1]
                tops[i] = max(4.0, min(tops[i], limit - callout.height))
                limit = tops[i] - CALLOUT_GAP
            # If it still doesn't fit, stack downward and let the scene grow.
            for i in range(1, len(items)):
                tops[i] = max(tops[i], tops[i - 1] + items[i - 1][1].height + CALLOUT_GAP)
            x = 0 if side == "left" else width - COL_W
            for (anchor_y, callout, hotspot), top in zip(items, tops):
                callout.setPos(x, top)
                scene_h = max(scene_h, top + callout.height + 4)
                edge_x = x + COL_W if side == "left" else x
                anchor = QPointF(edge_x, min(max(hotspot.pos().y(), top + 14), top + callout.height - 14))
                leader = QGraphicsPathItem(_leader_path(hotspot.pos(), anchor))
                leader.setPen(QPen(QColor(95, 212, 232, 110), 1.3))
                leader.setZValue(1)
                self.scene.addItem(leader)
                hotspot.leader = leader
                hotspot.anchor = anchor

        self.scene.setSceneRect(0, 0, width, scene_h)
        self.diagram.fit()

    # -- inspector ------------------------------------------------------------
    def _clear_inspector(self) -> None:
        while self.inspector_layout.count():
            item = self.inspector_layout.takeAt(0)
            widgets = []
            if item.widget():
                widgets.append(item.widget())
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    w = sub.takeAt(0).widget()
                    if w:
                        widgets.append(w)
            for w in widgets:
                # Hide now: deletion is deferred to the event loop.
                w.hide()
                w.deleteLater()

    def _set_placeholder(self, text: str) -> None:
        self._clear_inspector()
        lbl = QLabel(text, objectName="InspectorText")
        lbl.setWordWrap(True)
        self.inspector_layout.addWidget(lbl)
        self.inspector_layout.addStretch(1)
        self.scene.clear()

    def _section(self, text: str) -> None:
        self.inspector_layout.addWidget(QLabel(text, objectName="SectionLabel"))

    def _text(self, text: str, name: str = "InspectorText") -> QLabel:
        lbl = QLabel(text, objectName=name)
        lbl.setWordWrap(True)
        self.inspector_layout.addWidget(lbl)
        return lbl

    def _small_button(self, text: str, slot, name: str = "MiniButton") -> QPushButton:
        btn = QPushButton(text, objectName=name)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _render_inspector(self) -> None:
        self._clear_inspector()
        lay = self.inspector_layout

        self._section("STICK")
        self._text(f"js{self.instance} · {self.product}", "InspectorTitle")
        model = QComboBox(objectName="ConfigCombo")
        model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        model.setMinimumContentsLength(12)
        model.addItem("No diagram", None)
        for t in TEMPLATES.values():
            model.addItem(t.name, t.id)
        model.setCurrentIndex(max(model.findData(self.setup.template_id), 0))
        model.activated.connect(lambda i, c=model: self._on_model_changed(c.itemData(i)))
        lay.addWidget(model)

        if self.setup.template:
            tools = QHBoxLayout()
            tools.setSpacing(6)
            ident = self._small_button("Identify buttons", lambda: self._start_identify(None))
            ident.setToolTip("Walk through every control and press it, so the diagram knows your button numbers")
            tools.addWidget(ident)
            adjust = self._small_button("Adjust layout", lambda: None)
            adjust.setCheckable(True)
            adjust.setChecked(self.adjusting)
            adjust.setToolTip("Drag the markers onto the right spot on the drawing")
            adjust.toggled.connect(self._on_adjust_toggled)
            tools.addWidget(adjust)
            tools.addWidget(self._small_button("Export PNG", self._export_png))
            tools.addStretch(1)
            lay.addLayout(tools)

        connected = self.live_device is not None
        live = "connected" if connected else ("not detected" if self.joy.supported() else "unsupported on this OS")
        self._live_label = self._text(
            f"Live input: {live}" + (f"   ·   last: {input_code(self.last_input)}" if self.last_input else ""),
            "InspectorHint",
        )

        if self.last_note:
            self._text(self.last_note, "InspectorNote")

        lay.addSpacing(8)
        target = self._identify_target()
        if target is not None:
            self._render_identify(target)
        elif self.selected and self.setup.template and self.setup.template.control(self.selected):
            self._render_control(self.setup.template.control(self.selected))
        else:
            self._render_overview()
        lay.addStretch(1)

    def _render_overview(self) -> None:
        if self.setup.template:
            self._text(
                "Click a callout or marker to see everything bound to that control and to "
                "rebind it. Press buttons on the stick to light up their callouts.",
                "InspectorHint",
            )
            if not any(self.setup.inputs.values()):
                self._text(
                    "This stick's buttons haven't been identified yet, so only the axes can be "
                    "placed on the picture. VKB button numbers depend on the stick's firmware "
                    "profile, so the app learns them from you: it highlights each control in "
                    "turn and you press it (about a minute).",
                    "InspectorNote",
                )
                go = QPushButton("Identify buttons now", objectName="StartButtonSmall")
                go.setCursor(Qt.PointingHandCursor)
                go.clicked.connect(lambda: self._start_identify(None))
                self.inspector_layout.addWidget(go)
        placed = set()
        if self.setup.template:
            for c in self.setup.template.controls:
                for s in c.inputs:
                    placed.add(self.setup.input_for(c, s))
        unplaced = sorted(
            (inp for (inst, inp) in self.eff.by_input if inst == self.instance and inp not in placed),
            key=_natural_key,
        )
        rows = [(inp, self._actions_for(inp)) for inp in unplaced]
        rows = [(inp, acts) for inp, acts in rows if acts]
        self.inspector_layout.addSpacing(6)
        self._section("NOT ON THE DIAGRAM" if self.setup.template else "BOUND INPUTS")
        if not rows:
            self._text("Nothing in this context.", "InspectorHint")
        for inp, acts in rows:
            self._text(f"<b>{input_code(inp)}</b> &nbsp; " + " · ".join(a.label for a in acts), "InspectorText")

    def _render_control(self, control: Control) -> None:
        self._section(control.label.upper())
        for slot in control.inputs:
            inp = self.setup.input_for(control, slot)
            header = QHBoxLayout()
            name = {"s1": "Stage 1", "s2": "Stage 2", "press": "Press", "cw": "Clockwise",
                    "ccw": "Counter-clockwise", "x": "Left / right", "y": "Forward / back"}.get(
                slot.key, slot.key.capitalize())
            title = QLabel(f"{slot.tag}  {name}" + (f"   <span style='color:{PALETTE['text_muted']}'>{input_code(inp)}</span>" if inp else ""),
                           objectName="SlotTitle")
            header.addWidget(title, stretch=1)
            header.addWidget(self._small_button("Identify", lambda _c=False, c=control, s=slot: self._start_identify([(c, s)])))
            self.inspector_layout.addLayout(header)

            if not inp:
                self._text("Not identified yet.", "InspectorHint")
                continue
            actions = self._actions_for(inp, respect_context=False)
            if not actions:
                self._text("Nothing bound.", "InspectorHint")
            for a in actions:
                row = QHBoxLayout()
                lbl = QLabel(f"{a.label}<br><span style='color:{PALETTE['text_muted']}; font-size:10px'>{a.group}</span>",
                             objectName="ActionRow")
                lbl.setWordWrap(True)
                row.addWidget(lbl, stretch=1)
                x = self._small_button("✕", lambda _c=False, act=a: self._unbind(act), "MiniDanger")
                x.setToolTip("Unbind")
                row.addWidget(x, alignment=Qt.AlignTop)
                self.inspector_layout.addLayout(row)
            add = self._small_button("+ Bind action…", lambda _c=False, i=inp: self._open_picker(i), "MiniButton")
            self.inspector_layout.addWidget(add, alignment=Qt.AlignLeft)
            if self._picker_input == inp:
                self._render_picker(inp)
            self.inspector_layout.addSpacing(8)
        self.inspector_layout.addWidget(self._small_button("Close", lambda: self._select_control(None)), alignment=Qt.AlignLeft)

    def _open_picker(self, inp: str) -> None:
        self._picker_input = None if self._picker_input == inp else inp
        self._render_inspector()

    def _render_picker(self, inp: str) -> None:
        search = QLineEdit(objectName="SearchField")
        search.setPlaceholderText("Search actions…" + (f" ({self.context})" if self.context else ""))
        listing = QListWidget(objectName="ActionList")
        listing.setMinimumHeight(240)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        listing.setTextElideMode(Qt.ElideRight)
        candidates = sorted(
            (a for a in self.game.actions.values()
             if a.listed and (not self.context or a.category == self.context)),
            key=lambda a: (a.group, a.label),
        )

        def refill(text: str = "") -> None:
            listing.clear()
            needle = text.lower().strip()
            for a in candidates:
                if needle and needle not in a.label.lower() and needle not in a.group.lower():
                    continue
                current = self.eff.by_action.get(a.key, {}).get(self.instance)
                suffix = f"   [{input_code(current)}]" if current else ""
                item = QListWidgetItem(f"{a.label}{suffix}\n{a.group}")
                item.setData(Qt.UserRole, a.key)
                listing.addItem(item)

        def choose(item: QListWidgetItem) -> None:
            action = self.game.action(item.data(Qt.UserRole))
            self._picker_input = None
            self._bind(action, inp)

        search.textChanged.connect(refill)
        search.returnPressed.connect(lambda: listing.count() and choose(listing.item(0)))
        listing.itemActivated.connect(choose)
        listing.itemDoubleClicked.connect(choose)
        refill()
        self.inspector_layout.addWidget(search)
        self.inspector_layout.addWidget(listing)
        self._text("Double-click to bind. An action holds one input per stick, so binding it here moves it from wherever it was.", "InspectorHint")
        QTimer.singleShot(0, search.setFocus)

    def _select_control(self, control_id: str | None) -> None:
        if self._identify_target() is not None:
            return
        self.selected = None if control_id == self.selected else control_id
        self._picker_input = None
        self.last_note = ""
        # Deferred: this runs inside a scene item's mouse handler, and
        # re-rendering clears the scene (deleting that item).
        QTimer.singleShot(0, self._render)

    def _on_model_changed(self, template_id: str | None) -> None:
        if template_id == self.setup.template_id:
            return
        self.setup = DeviceSetup(template_id, {}, {})
        self._save_setup()
        self.selected = None
        self._render()

    def _on_context_changed(self, index: int) -> None:
        self.context = self.context_combo.itemData(index)
        self._picker_input = None
        self._render()

    def _on_adjust_toggled(self, on: bool) -> None:
        self.adjusting = on
        for h in self.hotspots.values():
            h.setFlag(QGraphicsItem.ItemIsMovable, on)

    def _on_hotspot_moved(self, control: Control, pos: QPointF) -> None:
        self.setup.positions[control.id] = self._template_point(pos)
        self._save_setup()
        QTimer.singleShot(0, self._render_scene)

    # -- live input + identify ------------------------------------------------
    def _identify_target(self) -> tuple[Control, InputSlot] | None:
        if 0 <= self.id_index < len(self.id_queue):
            return self.id_queue[self.id_index]
        return None

    def _start_identify(self, queue: list[tuple[Control, InputSlot]] | None) -> None:
        template = self.setup.template
        if template is None:
            QMessageBox.information(self, "Identify", "Pick a stick model first.")
            return
        if self.live_device is None:
            QMessageBox.warning(
                self, "Identify",
                f"“{self.product}” isn't detected as a live device, so presses can't be read.\n\n"
                "Check it's plugged in, then reopen this view.",
            )
            return
        if queue is None:
            queue = [(c, s) for c in template.controls for s in c.inputs]
            self.id_used = set()
        else:
            in_queue = {(c.id, s.key) for c, s in queue}
            self.id_used = {
                self.setup.input_for(c, s)
                for c in template.controls for s in c.inputs
                if (c.id, s.key) not in in_queue and self.setup.input_for(c, s)
            }
        self.id_queue = queue
        self.id_index = 0
        self.selected = None
        self._begin_slot()

    def _begin_slot(self) -> None:
        self.id_baseline = self.joy.axis_values(self.live_device)
        self._render()

    def _advance(self, step: int = 1) -> None:
        self.id_index += step
        if self.id_index < 0:
            self.id_index = 0
        if self._identify_target() is None:
            self._stop_identify()
            self.last_note = "Identify finished."
            self._render()
            return
        if step < 0:
            c, s = self.id_queue[self.id_index]
            self.id_used.discard(self.setup.input_for(c, s))
        self._begin_slot()

    def _stop_identify(self) -> None:
        self.id_queue = []
        self.id_index = 0

    def _render_identify(self, target: tuple[Control, InputSlot]) -> None:
        control, slot = target
        self._section(f"IDENTIFY  ·  {self.id_index + 1} / {len(self.id_queue)}")
        self._text(control.label, "InspectorTitle")
        self._text(slot.prompt, "PromptLabel")
        current = self.setup.input_for(control, slot)
        self._text(
            ("Move it all the way — waiting for the axis…" if slot.axis else "Waiting for a press…")
            + (f"   (currently {input_code(current)})" if current else ""),
            "InspectorHint",
        )
        row = QHBoxLayout()
        row.addWidget(self._small_button("← Back", lambda: self._advance(-1)))
        row.addWidget(self._small_button("Skip", lambda: self._advance(1)))
        row.addWidget(self._small_button("Unassign", lambda: self._identify_assign("")))
        row.addWidget(self._small_button("Stop", self._cancel_identify, "MiniDanger"))
        self.inspector_layout.addLayout(row)
        self._text("Skip keeps the current mapping. Unassign clears it (for controls your stick doesn't have).", "InspectorHint")

    def _cancel_identify(self) -> None:
        self._stop_identify()
        self._render()

    def _identify_assign(self, inp: str) -> None:
        target = self._identify_target()
        if target is None:
            return
        self.setup.assign(target[0], target[1], inp)
        self._save_setup()
        if inp:
            self.id_used.add(inp)
        self._advance(1)

    def _on_pressed(self, device: str, inp: str) -> None:
        if device != self.live_device or not self.isVisible():
            return
        target = self._identify_target()
        if target is not None:
            if not target[1].axis and inp not in self.id_used:
                self._identify_assign(inp)
            return
        self.last_input = inp
        if self._live_label is not None:
            try:
                self._live_label.setText(f"Live input: connected   ·   last: {input_code(inp)}")
            except RuntimeError:
                pass
        found = self.setup.slot_for_input(inp)
        if found:
            callout = self.callouts.get(found[0].id)
            hotspot = self.hotspots.get(found[0].id)
            if callout:
                callout.flash_inputs.add(inp)
                callout.update()
            if hotspot:
                hotspot.set_state(False, True)
            self._flash_timer.start(450)

    def _clear_flash(self) -> None:
        for cid, callout in self.callouts.items():
            if callout.flash_inputs:
                callout.flash_inputs.clear()
                callout.update()
                hotspot = self.hotspots.get(cid)
                if hotspot:
                    hotspot.set_state(callout.selected or callout.target, False)

    def _on_axis(self, device: str, name: str, value: int) -> None:
        if device != self.live_device or not self.isVisible():
            return
        target = self._identify_target()
        if target is None or not target[1].axis or name in self.id_used:
            return
        base = self.id_baseline.get(name, 0)
        if abs(value - base) >= AXIS_IDENTIFY_THRESHOLD:
            self._identify_assign(name)

    # -- saving / export ------------------------------------------------------
    def _on_save_clicked(self) -> None:
        if self.profile is None:
            return
        menu = QMenu(self)
        if self.source is not None:
            menu.addAction(f"Save “{self.source.name}”").triggered.connect(lambda: self._save(self.source))
        menu.addAction("Save as new profile…").triggered.connect(lambda: self._save(None))
        menu.exec(self.save_btn.mapToGlobal(self.save_btn.rect().bottomLeft()))

    def _save(self, existing: BackupInfo | None) -> None:
        if existing is None:
            name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
            name = name.strip()
            if not ok or not name:
                return
        else:
            name = existing.name
        try:
            info = backup.save_profile(
                settings.current().backup_root, self.channel, name, self.profile.to_bytes(),
                self.paths.profile_dir / "attributes.xml", existing,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Save profile", f"Couldn't save the profile:\n{exc}")
            return
        self.source = info
        self.dirty = False
        self._update_save_btn()
        self._refresh_sources()
        self.last_note = f"Saved “{name}”. Pick it under CONFIG on the main screen to launch with it."
        self._render_inspector()
        self.profiles_changed.emit()

    def _export_png(self) -> None:
        if self.setup.template is None:
            return
        default = Path.home() / f"sc-bindings-{self.product.replace(' ', '_')}-{(self.context or 'all').replace(' ', '_')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Export diagram", str(default), "PNG image (*.png)")
        if not path:
            return
        rect = self.scene.sceneRect()
        scale = 2
        header_h = 40
        image = QImage(int(rect.width() * scale), int((rect.height() + header_h) * scale), QImage.Format_ARGB32)
        image.fill(QColor(PALETTE["bg_panel_solid"]))
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        painter.scale(scale, scale)
        f = QFont()
        f.setPixelSize(16)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(C_TEXT)
        painter.drawText(QRectF(12, 8, rect.width() - 24, 24), Qt.AlignLeft | Qt.AlignVCenter,
                         f"{self.product}  —  {self.context or 'All contexts'}")
        self.scene.render(painter, QRectF(0, header_h, rect.width(), rect.height()), rect)
        painter.end()
        image.save(path)
