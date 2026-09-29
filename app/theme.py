"""Color palette and stylesheet for the launcher, derived from the Polaris
background art: warm amber/dust haze with cool cyan ship-light accents.
"""

PALETTE = {
    "bg_panel": "rgba(13, 15, 18, 0.68)",
    "bg_panel_solid": "#0d0f12",
    "bg_titlebar": "rgba(9, 10, 12, 0.85)",
    "border": "rgba(255, 255, 255, 0.08)",
    "accent_cyan": "#5fd4e8",
    "accent_cyan_dim": "#3a8f9e",
    "accent_amber": "#e8935a",
    "accent_amber_dim": "#a8623a",
    "text_primary": "#eae7e0",
    "text_secondary": "#9a958c",
    "text_muted": "#6b675f",
    "danger": "#e05a4f",
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
    background: {bg_titlebar};
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    border-bottom: 1px solid {border};
}}

#TitleBar QLabel {{
    color: {text_secondary};
    font-weight: 600;
    letter-spacing: 2px;
    font-size: 11px;
}}

#TitleBarButton {{
    background: transparent;
    border: none;
    border-radius: 4px;
    color: {text_secondary};
    font-size: 14px;
}}
#TitleBarButton:hover {{
    background: rgba(255, 255, 255, 0.08);
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
        stop:0 {accent_cyan_dim}, stop:1 {accent_amber_dim});
    border: 1px solid {accent_cyan};
    border-radius: 10px;
    color: {text_primary};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 3px;
    padding: 18px;
}}
#StartButton:hover {{
    border: 1px solid {accent_amber};
}}
#StartButton:pressed {{
    background: {accent_cyan_dim};
}}
#StartButton:disabled {{
    color: {text_secondary};
    border: 1px solid {border};
}}
#StartButton[mode="close"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent_amber_dim}, stop:1 {danger});
    border: 1px solid {danger};
}}

#BusyBar {{
    background: rgba(255, 255, 255, 0.06);
    border: none;
    border-radius: 3px;
}}
#BusyBar::chunk {{
    background: {accent_cyan};
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
    background: {accent_cyan_dim};
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
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {border};
    border-radius: 6px;
    padding: 8px 10px;
    color: {text_primary};
}}
#ConfigCombo::drop-down {{
    border: none;
    width: 24px;
}}
#ConfigCombo QAbstractItemView {{
    background: {bg_panel_solid};
    border: 1px solid {border};
    selection-background-color: {accent_cyan_dim};
    color: {text_primary};
    outline: none;
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
    background: rgba(255, 255, 255, 0.03);
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
    background: rgba(255, 255, 255, 0.07);
    border-left: 2px solid {accent_cyan};
    color: {text_primary};
}}

#ToolButton {{
    background: rgba(255, 255, 255, 0.03);
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
    background: rgba(255, 255, 255, 0.07);
    border-left: 2px solid {accent_amber};
    color: {text_primary};
}}
#ToolButton:checked {{
    background: rgba(232, 147, 90, 0.16);
    border-left: 2px solid {accent_amber};
    color: {text_primary};
}}

#StartButtonSmall {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent_cyan_dim}, stop:1 {accent_amber_dim});
    border: 1px solid {accent_cyan};
    border-radius: 6px;
    color: {text_primary};
    font-weight: 700;
    letter-spacing: 1px;
    padding: 8px 16px;
}}
#StartButtonSmall:hover {{
    border: 1px solid {accent_amber};
}}
#StartButtonSmall:disabled {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {border};
    color: {text_muted};
}}

#Segment {{
    background: rgba(255, 255, 255, 0.04);
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
#Segment:checked {{
    background: {accent_cyan_dim};
    color: {text_primary};
    border: 1px solid {accent_cyan};
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
    color: {accent_amber};
    font-size: 12px;
}}
#PromptLabel {{
    color: {accent_amber};
    font-size: 18px;
    font-weight: 600;
    padding: 6px 0;
}}
#SlotTitle {{
    color: {accent_cyan};
    font-size: 12px;
    font-weight: 600;
}}

#MiniButton, #MiniDanger {{
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid {border};
    border-radius: 5px;
    color: {text_secondary};
    font-size: 11px;
    padding: 4px 9px;
}}
#MiniButton:hover {{
    border: 1px solid {accent_cyan};
    color: {text_primary};
}}
#MiniButton:checked {{
    background: rgba(232, 147, 90, 0.18);
    border: 1px solid {accent_amber};
    color: {text_primary};
}}
#MiniDanger:hover {{
    border: 1px solid {danger};
    color: {danger};
}}

#SearchField {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {border};
    border-radius: 6px;
    padding: 7px 9px;
}}
#SearchField:focus {{
    border: 1px solid {accent_cyan_dim};
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
    background: {accent_cyan_dim};
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
    background: rgba(255, 255, 255, 0.05);
    border-left: 2px solid {accent_amber};
}}
#ShipHeader[open="true"] {{
    border-left: 2px solid {accent_cyan};
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
    color: {accent_amber};
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
    color: {accent_amber};
    font-size: 12px;
    font-weight: 700;
}}
#SalvageMatch {{
    color: {accent_cyan};
    font-size: 12px;
    font-weight: 600;
}}
#ShipMatch {{
    color: {accent_cyan};
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
    color: {accent_cyan};
    font-weight: 700;
}}
#SalvageMaybe {{
    color: {accent_amber};
    font-weight: 700;
}}
#SalvageNo {{
    color: {text_muted};
}}

#CigNotice {{
    color: {text_secondary};
    font-size: 9px;
    background: rgba(9, 10, 12, 0.62);
    border-radius: 6px;
    padding: 4px 8px;
}}
#SettingsOk {{
    color: {accent_cyan};
    font-size: 11px;
}}
#SettingsBad {{
    color: {danger};
    font-size: 11px;
}}
#MiningChance {{
    color: {accent_cyan};
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
    color: {accent_cyan};
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
    color: {accent_amber};
    font-size: 12px;
    font-weight: 700;
}}
#ActionList::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {text_muted};
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.04);
}}
#ActionList::indicator:checked {{
    background: {accent_cyan};
    border: 1px solid {accent_cyan};
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

QInputDialog, QMessageBox {{
    background: {bg_panel_solid};
}}
QInputDialog QLineEdit {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 8px;
}}
"""


def build_stylesheet() -> str:
    return STYLESHEET.format(**PALETTE)
