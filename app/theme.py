"""Colour palette and stylesheet, derived from the background wallpaper
(Fankit SC_26, the Corsair): dark umber ground, slate sky, warm sand light
and the gold stripes on the hull.

Tokens are named by role, not hue, so the same palette can drive the
launcher and the in-game overlay:
  panel*   translucent "glass" behind every piece of text
  accent*  gold — primary action, selection, key numbers
  info*    sky steel — links, bars, confirmations, secondary highlights
  text*    warm off-white → muted; muted stays readable on panels
"""

PALETTE = {
    "bg_panel": "rgba(20, 24, 28, 0.80)",
    "bg_panel_strong": "rgba(16, 19, 23, 0.90)",
    "bg_panel_solid": "#15181c",
    "bg_hover": "rgba(255, 255, 255, 0.08)",
    "bg_input": "rgba(255, 255, 255, 0.06)",
    "border": "rgba(218, 197, 164, 0.16)",
    "border_strong": "rgba(218, 197, 164, 0.30)",
    "accent": "#e3a33b",
    "accent_dim": "#8a6524",
    "accent_soft": "rgba(227, 163, 59, 0.18)",
    "info": "#8db4cf",
    "info_dim": "#4d6a80",
    "text_primary": "#f3ede2",
    "text_secondary": "#cfc6b6",
    "text_muted": "#a39a8a",
    "danger": "#e26a55",
    "ok": "#9cc48c",
}

STYLESHEET = """
QWidget {{
    color: {text_primary};
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
}}

#RootFrame {{
    background: transparent;
}}

#TitleBar {{
    background: transparent;
}}

#TitleBar QLabel {{
    color: {text_primary};
    font-weight: 700;
    letter-spacing: 2px;
    font-size: 12px;
    background: transparent;
}}

#TitleVersion, #TitleUpdate {{
    background: transparent;
    border: none;
    color: {text_secondary};
    font-weight: 600;
    letter-spacing: 1px;
    font-size: 11px;
    padding: 2px 4px;
}}
#TitleVersion:hover {{
    color: {text_primary};
    text-decoration: underline;
}}
#TitleVersion[unseen="true"] {{
    color: {accent};
}}
#TitleUpdate {{
    color: {accent};
    border: 1px solid {accent_dim};
    border-radius: 4px;
    margin-left: 6px;
    padding: 2px 8px;
}}
#TitleUpdate:hover {{
    background: {accent_soft};
    border: 1px solid {accent};
}}

#UpdateProgress {{
    background: {bg_input};
    border: none;
    border-radius: 3px;
}}
#UpdateProgress::chunk {{
    background: {accent};
    border-radius: 3px;
}}

#ChangelogText {{
    background: transparent;
    color: {text_primary};
    font-size: 12px;
    selection-background-color: {accent_soft};
}}

#TitleBarButton {{
    background: transparent;
    border: none;
    border-radius: 4px;
    color: {text_primary};
    font-size: 14px;
}}
#TitleBarButton:hover {{
    background: rgba(0, 0, 0, 0.35);
    color: {text_primary};
}}
#TitleBarButton[kind="close"]:hover {{
    background: {danger};
    color: white;
}}

#DiagramView {{
    background: {bg_panel};
    border-radius: 10px;
    border: 1px solid {border};
}}

#MapFrame {{
    background: {bg_panel_solid};
    border-radius: 10px;
    border: 1px solid {border};
}}

#ToolBar {{
    background: {bg_panel};
    border-radius: 10px;
    border: 1px solid {border};
}}

#SidePanel {{
    background: {bg_panel};
    border-radius: 10px;
    border: 1px solid {border};
}}

#StartButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent}, stop:1 {accent_dim});
    border: 1px solid {accent};
    border-radius: 10px;
    color: #1b1712;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 3px;
    padding: 18px;
}}
#StartButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #efb453, stop:1 {accent});
    border: 1px solid #f6cf8a;
}}
#StartButton:pressed {{
    background: {accent_dim};
}}
#StartButton:disabled {{
    background: {bg_input};
    color: {text_muted};
    border: 1px solid {border};
}}
#StartButton[mode="close"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {danger}, stop:1 #8a3326);
    border: 1px solid {danger};
    color: {text_primary};
}}

#StartButton[mode="ingame"], #StartButton[mode="ingame"]:disabled {{
    background: {accent_soft};
    border: 1px solid {accent_dim};
    color: {accent};
}}

#BusyBar {{
    background: {bg_input};
    border: none;
    border-radius: 3px;
}}
#BusyBar::chunk {{
    background: {accent};
    border-radius: 3px;
}}

QMenu {{
    background: {bg_panel_solid};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px;
    color: {text_primary};
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background: {accent_dim};
    color: {text_primary};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 6px 8px;
}}

#ConfigLabel {{
    color: {text_muted};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}

#ConfigCombo {{
    background: {bg_input};
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 8px 10px;
    color: {text_primary};
}}
#ConfigCombo:hover {{
    border: 1px solid {accent};
}}
#ConfigCombo::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    border-left: 1px solid {border};
}}
#ConfigCombo::down-arrow {{
    image: url({chevron_down});
    width: 12px;
    height: 12px;
}}
#ConfigCombo QAbstractItemView {{
    background: {bg_panel_solid};
    border: 1px solid {border};
    selection-background-color: {accent_dim};
    color: {text_primary};
    outline: none;
}}
/* The overlay's dropdown list, drawn inside the overlay window. */
#InlineComboList {{
    background: {bg_panel_solid};
    border: 1px solid {border_strong};
    border-radius: 6px;
    color: {text_primary};
    outline: none;
    padding: 2px;
}}
#InlineComboList::item {{
    padding: 4px 8px;
    border-radius: 4px;
}}
#InlineComboList::item:hover {{
    background: {bg_hover};
}}
#InlineComboList::item:selected {{
    background: {accent_dim};
    color: {text_primary};
}}

#ConfigHelp {{
    color: {text_secondary};
    font-size: 11px;
    padding-top: 2px;
}}
#ConfigHelp[warn="true"] {{
    color: {accent};
}}

#SectionLabel {{
    color: {text_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    padding-top: 4px;
}}

QFrame#Divider {{
    background: {border};
    max-height: 1px;
    min-height: 1px;
}}

#LinkButton {{
    background: {bg_input};
    border: 1px solid transparent;
    border-left: 2px solid transparent;
    border-radius: 6px;
    color: {text_secondary};
    text-align: left;
    padding: 9px 12px;
    font-size: 12px;
    min-height: 20px;
}}
#LinkButton:hover {{
    background: {bg_hover};
    border-left: 2px solid {info};
    color: {text_primary};
}}

#ToolButton {{
    background: {bg_input};
    border: 1px solid transparent;
    border-left: 2px solid transparent;
    border-radius: 6px;
    color: {text_secondary};
    text-align: left;
    padding: 9px 12px;
    font-size: 12px;
    min-height: 20px;
}}
#ToolButton:hover {{
    background: {bg_hover};
    border-left: 2px solid {accent};
    color: {text_primary};
}}
#ToolButton:checked {{
    background: {accent_soft};
    border-left: 2px solid {accent};
    color: {text_primary};
}}

#ToolsHeading {{
    color: {text_primary};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 12px;
}}
#ToolTile {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 10px;
}}
#ToolTile:hover {{
    background: {accent_soft};
    border: 1px solid {accent};
}}
#ToolTile:disabled {{
    background: {bg_panel};
}}
#TileTitle {{
    color: {text_primary};
    font-size: 16px;
    font-weight: 700;
    background: transparent;
}}
#TileText {{
    color: {text_secondary};
    font-size: 12px;
    background: transparent;
}}
#TileCredit {{
    color: {text_muted};
    font-size: 11px;
    background: transparent;
}}
#ToolTile:disabled QLabel {{
    color: {text_muted};
}}

#StartButtonSmall {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent}, stop:1 {accent_dim});
    border: 1px solid {accent};
    border-radius: 6px;
    color: #1b1712;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 8px 16px;
}}
#StartButtonSmall:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #efb453, stop:1 {accent});
    border: 1px solid #f6cf8a;
}}
#StartButtonSmall:disabled {{
    background: {bg_input};
    border: 1px solid {border};
    color: {text_muted};
}}

#Segment {{
    background: {bg_input};
    border: 1px solid {border};
    color: {text_secondary};
    font-weight: 700;
    letter-spacing: 1px;
    font-size: 11px;
    padding: 8px 16px;
}}
#Segment[pos="first"] {{
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
}}
#Segment[pos="last"] {{
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}}
#Segment[compact="true"] {{
    padding: 3px 9px;
    font-size: 10px;
    letter-spacing: 0.5px;
}}
#Segment:checked {{
    background: {accent_soft};
    color: {text_primary};
    border: 1px solid {accent};
}}

#Inspector, #InspectorScroll, #InspectorScroll > QWidget > QWidget {{
    background: transparent;
}}
#InspectorTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {text_primary};
}}
#InspectorText, #ActionRow {{
    color: {text_primary};
    font-size: 12px;
}}
#InspectorHint {{
    color: {text_secondary};
    font-size: 11px;
}}
#InspectorNote {{
    color: {accent};
    font-size: 12px;
}}
#PromptLabel {{
    color: {accent};
    font-size: 18px;
    font-weight: 600;
    padding: 6px 0;
}}
#SlotTitle {{
    color: {info};
    font-size: 12px;
    font-weight: 600;
}}

#MiniButton, #MiniDanger {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 5px;
    color: {text_secondary};
    font-size: 11px;
    padding: 4px 9px;
}}
#MiniButton:hover {{
    border: 1px solid {info};
    color: {text_primary};
}}
#MiniButton:checked {{
    background: {accent_soft};
    border: 1px solid {accent};
    color: {text_primary};
}}
#MiniDanger:hover {{
    border: 1px solid {danger};
    color: {danger};
}}

#SearchField {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 7px 9px;
}}
#SearchField:focus {{
    border: 1px solid {info_dim};
}}
#ActionList {{
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid {border};
    border-radius: 6px;
    outline: none;
    font-size: 12px;
}}
#ActionList::item {{
    padding: 5px 6px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}}
#ActionList::item:selected, #ActionList::item:hover {{
    background: {accent_dim};
}}

#ShipCard {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 8px;
}}
#ShipHeader {{
    background: transparent;
    border-radius: 8px;
    border-left: 2px solid transparent;
}}
#ShipHeader:hover {{
    background: {bg_input};
    border-left: 2px solid {accent};
}}
#ShipHeader[open="true"] {{
    border-left: 2px solid {info};
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
}}
#ShipDetail, #ShipHeader QWidget {{
    background: transparent;
}}
#ShipArrow {{
    color: {text_secondary};
    font-size: 12px;
}}
#ShipName {{
    font-size: 14px;
    font-weight: 600;
}}
#ShipMuted {{
    color: {text_muted};
    font-size: 11px;
}}
#ShipCaption {{
    color: {text_muted};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
}}
#ShipStat {{
    color: {text_primary};
    font-size: 13px;
}}
#ShipNet {{
    color: {accent};
    font-size: 14px;
    font-weight: 700;
}}
#SalvageHead {{
    color: {text_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}
#SalvageCell {{
    color: {text_primary};
    font-size: 12px;
}}
#SalvageDim {{
    color: {text_secondary};
    font-size: 12px;
}}
#SalvageBest {{
    color: {accent};
    font-size: 12px;
    font-weight: 700;
}}
#SalvageMatch {{
    color: {info};
    font-size: 12px;
    font-weight: 600;
}}
#ShipMatch {{
    color: {info};
    font-size: 11px;
}}
#ShipTier {{
    color: {text_secondary};
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid {border};
    border-radius: 4px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 1px 6px;
}}
#SalvageYes {{
    color: {info};
    font-weight: 700;
}}
#SalvageMaybe {{
    color: {accent};
    font-weight: 700;
}}
#SalvageNo {{
    color: {text_muted};
}}

#AboutLabel {{
    color: {text_secondary};
    font-size: 11px;
    background: {bg_panel};
    border-radius: 6px;
    padding: 4px 10px;
}}
#CigNotice {{
    color: {text_secondary};
    font-size: 9px;
    background: {bg_panel};
    border-radius: 6px;
    padding: 4px 8px;
}}
#ConfirmPanel {{
    background: rgba(224, 90, 79, 0.10);
    border: 1px solid {danger};
    border-radius: 8px;
}}
#ConfirmTitle {{
    color: {danger};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}}
#SettingsOk {{
    color: {info};
    font-size: 11px;
}}
#SettingsBad {{
    color: {danger};
    font-size: 11px;
}}
#MiningChance {{
    color: {info};
    font-size: 12px;
    font-weight: 700;
}}
#MiningRockHit {{
    color: {text_primary};
    font-size: 12px;
    font-weight: 700;
}}
#MiningRarity {{
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
}}
#MiningPart {{
    color: {info};
    font-size: 12px;
    padding-left: 10px;
}}
#MiningSignature {{
    color: {text_secondary};
    font-size: 11px;
}}
#MiningSignatureDim {{
    color: {text_muted};
    font-size: 11px;
}}
#MiningAmount {{
    color: {text_primary};
    font-size: 12px;
    font-weight: 600;
}}
#MiningQuality {{
    color: {accent};
    font-size: 12px;
    font-weight: 700;
}}
#ActionList::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {text_muted};
    border-radius: 3px;
    background: {bg_input};
}}
#ActionList::indicator:checked {{
    background: {info};
    border: 1px solid {info};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.14);
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 0.14);
    border-radius: 3px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0;
    background: transparent;
}}
QAbstractScrollArea::corner {{
    background: transparent;
}}

QMenu {{
    background: {bg_panel_solid};
    border: 1px solid {border_strong};
    padding: 4px;
}}
QMenu::item {{
    color: {text_primary};
    padding: 5px 18px 5px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {accent_soft};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 6px;
}}

QInputDialog, QMessageBox {{
    background: {bg_panel_solid};
}}
QMessageBox QPushButton, QInputDialog QPushButton, QDialogButtonBox QPushButton {{
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid {border};
    border-radius: 6px;
    color: {text_primary};
    padding: 6px 14px;
    min-width: 72px;
}}
QMessageBox QPushButton:hover, QInputDialog QPushButton:hover, QDialogButtonBox QPushButton:hover {{
    border: 1px solid {accent};
}}
QMessageBox QPushButton:default, QInputDialog QPushButton:default, QDialogButtonBox QPushButton:default {{
    border: 1px solid {info};
}}
QInputDialog QLineEdit {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 8px;
}}

#OverlaySwitchBox {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 6px;
}}
#OverlaySwitchLabel {{
    color: {text_primary};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}}
#OverlaySwitchHint {{
    color: {text_muted};
    font-size: 11px;
}}

/* -- My Stats ------------------------------------------------------------ */
#StatValue {{
    color: {accent};
    font-size: 20px;
    font-weight: 700;
}}
#StatLabel {{
    color: {text_muted};
    font-size: 11px;
}}
#StatRowName {{
    color: {text_primary};
    font-size: 12px;
}}
#StatRowValue {{
    color: {text_secondary};
    font-size: 12px;
}}
#MoreButton {{
    background: transparent;
    border: none;
    color: {info};
    font-size: 11px;
    padding: 2px 0;
    text-align: left;
}}
#MoreButton:hover {{
    color: {text_primary};
    text-decoration: underline;
}}
#GlyphFilter {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 6px;
    color: {text_muted};
    font-size: 11px;
    font-weight: 700;
    padding: 5px 9px 5px 7px;
}}
#GlyphFilter:hover {{
    background: {bg_hover};
    color: {text_primary};
}}
#GlyphFilter:checked {{
    background: {accent_soft};
    border: 1px solid {accent};
    color: {text_primary};
}}

/* -- overlay: live missions / session ------------------------------------ */
#LiveCard {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 8px;
}}
#LiveCard[state="done"] {{
    border: 1px solid {info_dim};
}}
#LiveCard[state="reward"] {{
    background: rgba(156, 196, 140, 0.20);
    border: 1px solid {ok};
}}
#LiveCard[state="tracked"] {{
    background: rgba(227, 163, 59, 0.10);
    border: 1px solid {accent_dim};
}}
#LiveCard[state="failed"] {{
    background: rgba(226, 106, 85, 0.10);
    border: 1px solid rgba(226, 106, 85, 0.45);
}}
#LiveCard[flash="true"] {{
    background: rgba(227, 163, 59, 0.32);
    border: 1px solid {accent};
}}
#LiveReward {{
    color: #d7ecc9;
    font-size: 13px;
    font-weight: 600;
}}
#LiveBlueprintOwned {{
    color: {ok};
    font-size: 12px;
}}
#LiveGroup {{
    color: {info};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding-top: 4px;
}}
#LiveTitle {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 600;
}}
#LiveMuted {{
    color: {text_muted};
    font-size: 11px;
}}
#LiveText {{
    color: {text_secondary};
    font-size: 12px;
}}
#LiveGood {{
    color: {ok};
    font-size: 12px;
}}
#LiveBad {{
    color: {danger};
    font-size: 12px;
}}
#LiveValue {{
    color: {accent};
    font-size: 16px;
    font-weight: 700;
}}
#LiveChip {{
    background: {accent_soft};
    border-radius: 4px;
    color: {accent};
    font-size: 11px;
    padding: 1px 6px;
}}
#LiveChip[tone="info"] {{
    background: rgba(141, 180, 207, 0.16);
    color: {info};
}}
#LiveChip[tone="good"] {{
    background: rgba(156, 196, 140, 0.22);
    color: {ok};
}}
#LiveChip[tone="bad"] {{
    background: rgba(226, 106, 85, 0.16);
    color: {danger};
}}

/* -- in-game overlay ------------------------------------------------------ */
#OverlayFrame {{
    background: {bg_panel_strong};
    border: 1px solid {border_strong};
    border-radius: 10px;
}}
#OverlayFrame[clickThrough="true"] {{
    border: 1px dashed {accent_dim};
}}
#OverlayHeader {{
    background: transparent;
}}
#OverlayGrip {{
    color: {text_muted};
    font-size: 15px;
}}
#OverlayTitle {{
    color: {text_secondary};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}}
#OverlayTool {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 5px;
    color: {text_secondary};
    font-size: 12px;
    padding: 3px;
}}
#OverlayTool:hover {{
    border: 1px solid {info};
    color: {text_primary};
}}
#OverlayTool:checked {{
    background: {accent_soft};
    border: 1px solid {accent};
    color: {text_primary};
}}
#OverlayIcon {{
    background: transparent;
    border: none;
    border-radius: 4px;
    color: {text_secondary};
    font-size: 14px;
    min-width: 24px;
    min-height: 24px;
}}
#OverlayIcon:hover {{
    background: {bg_hover};
    color: {text_primary};
}}
#OverlayBanner {{
    background: {accent_soft};
    border-radius: 5px;
    color: {accent};
    font-size: 11px;
    padding: 3px 8px;
}}
#OverlayOpacity::groove:horizontal {{
    background: {bg_input};
    border-radius: 2px;
    height: 4px;
}}
#OverlayOpacity::sub-page:horizontal {{
    background: {accent_dim};
    border-radius: 2px;
}}
#OverlayOpacity::handle:horizontal {{
    background: {accent};
    border-radius: 5px;
    width: 10px;
    margin: -3px 0;
}}
"""


def build_stylesheet() -> str:
    from app import config

    # Qt stylesheet urls want forward slashes, on Windows too.
    icons = {"chevron_down": (config.ICONS_DIR / "chevron_down.png").as_posix()}
    return STYLESHEET.format(**PALETTE, **icons)
