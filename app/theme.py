"""Colour palette, type and stylesheet, derived from the background wallpaper
(Fankit SC_26, the Corsair): dark umber ground, slate sky, warm sand light
and the gold stripes on the hull.

The colour roles are the website's (sc-toolbox.com, assets/styles/tokens.css),
so a colour means the same thing in the launcher, the overlay and the site:
  accent   amber: the brand and the ONE primary action of a view (START, Add
           ships, Save), and "new" (an update, unseen changes). Nothing else.
  info     steel: selection and focus (active filter, rail item, checked box,
           switch on), links, neutral data bars.
  success  you, a match, the best value: owned, completed, the best claim.
  warning  needs attention but isn't broken (game update in progress).
  danger   errors, failed missions, destructive actions.
  text*    primary → secondary → muted; muted never carries a fact alone.
  hue_*    categories (star systems, mission kinds), shown outlined so they
           never read as a status.
Hierarchy comes from size and weight, not colour.
"""

from pathlib import Path

PALETTE = {
    "bg_panel": "rgba(20, 24, 28, 0.82)",
    "bg_panel_strong": "rgba(16, 19, 23, 0.92)",
    "bg_panel_solid": "#15181c",
    "bg_hover": "rgba(255, 255, 255, 0.07)",
    "bg_input": "rgba(255, 255, 255, 0.06)",
    "border": "rgba(218, 197, 164, 0.16)",
    "border_strong": "rgba(218, 197, 164, 0.30)",
    "border_hover": "rgba(218, 197, 164, 0.45)",
    "accent": "#e3a33b",
    "accent_dim": "#8a6524",
    "accent_soft": "rgba(227, 163, 59, 0.18)",
    "info": "#8db4cf",
    "info_dim": "#4d6a80",
    "info_soft": "rgba(141, 180, 207, 0.14)",
    "text_primary": "#f3ede2",
    "text_secondary": "#cfc6b6",
    "text_muted": "#a39a8a",
    "danger": "#e26a55",
    "danger_soft": "rgba(226, 106, 85, 0.14)",
    "success": "#9cc48c",
    "success_soft": "rgba(156, 196, 140, 0.16)",
    "warning": "#e0954f",
    "warning_soft": "rgba(224, 149, 79, 0.14)",
    # categories (outlined badges)
    "hue_stanton": "#79c3d6",
    "hue_pyro": "#ef9a6a",
    "hue_nyx": "#b9a3f0",
    "hue_combat": "#ea8a9a",
    "hue_hauling": "#8fd0a8",
    "hue_industry": "#d9c27a",
    "hue_search": "#a9b8f5",
    "hue_racing": "#f0a3d6",
    "hue_trade": "#c3d98a",
    "hue_event": "#e6a0e6",
}
# Older names, still used by some views.
PALETTE["ok"] = PALETTE["success"]
PALETTE["selected_soft"] = PALETTE["info_soft"]

RARITY = {"Common": "#9a958c", "Uncommon": "#7cc47f", "Rare": "#5fa8e8",
          "Epic": "#b98ae8", "Legendary": "#e8935a"}
SYSTEM_HUES = {"stanton": "hue_stanton", "pyro": "hue_pyro", "nyx": "hue_nyx"}

# Type scale (px) and spacing steps: the website's.
FS = {"2xs": 11, "xs": 12, "sm": 13, "md": 14, "lg": 15, "xl": 16, "2xl": 18, "3xl": 20, "4xl": 24}
SPACE = (4, 8, 12, 16, 24, 32)
FONT_FAMILY = "Inter"
FONT_WEIGHTS = ("Regular", "Medium", "SemiBold", "Bold", "ExtraBold")
# Display numbers (the loadout editor's totals, part stats): Rajdhani (SIL OFL), as on the website.
NUM_FAMILY = "Rajdhani"
NUM_WEIGHTS = ("Medium", "SemiBold", "Bold")


def hue(name: str | None) -> str:
    """A category's colour by star system or hue name; muted when unknown."""
    key = SYSTEM_HUES.get((name or "").lower(), f"hue_{(name or '').lower()}")
    return PALETTE.get(key, PALETTE["text_muted"])


_fonts_installed = False


def install_fonts() -> None:
    """Loads the bundled Inter (SIL OFL) and makes it the app font, with
    tabular figures so numbers line up in columns. Needs a QApplication."""
    global _fonts_installed
    if _fonts_installed:
        return
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from app import config

    app = QApplication.instance()
    if app is None:
        return
    _fonts_installed = True
    loaded = False
    for weight in FONT_WEIGHTS:
        path = Path(config.ASSETS_DIR) / "fonts" / f"Inter-{weight}.ttf"
        loaded |= QFontDatabase.addApplicationFont(str(path)) >= 0
    for weight in NUM_WEIGHTS:
        QFontDatabase.addApplicationFont(str(Path(config.ASSETS_DIR) / "fonts" / f"Rajdhani-{weight}.ttf"))
    font = QFont(FONT_FAMILY if loaded else app.font().family())
    font.setPixelSize(FS["sm"])
    font.setFeature(QFont.Tag("tnum"), 1)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)


STYLESHEET = """
QWidget {{
    color: {text_primary};
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
    border: 1px solid {border_hover};
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

#TitleAccount {{
    background: rgba(16, 19, 23, 0.45);
    color: {text_primary};
    border: 1px solid {border_strong};
    border-radius: 13px;
    padding: 3px 12px 3px 8px;
    font-weight: 600;
    font-size: 12px;
}}
#TitleAccount:hover {{
    background: rgba(16, 19, 23, 0.7);
    border: 1px solid {border_hover};
}}
#TitleAccount[signedIn="true"] {{
    color: {text_primary};
    border: 1px solid transparent;
    border-radius: 13px;
    letter-spacing: 0px;
    font-size: 12px;
    font-weight: 600;
    padding: 2px 10px 2px 3px;
}}
#TitleAccount[offline="true"] {{
    color: {text_muted};
}}
#TitleAccountMenu {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {text_secondary};
    font-size: 12px;
}}
#TitleAccountMenu:hover {{
    background: rgba(0, 0, 0, 0.35);
    color: {text_primary};
}}
#TitleAccount[signedIn="true"]:hover {{
    background: {bg_hover};
    border: 1px solid {border};
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
    background: {info_soft};
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
#ConfigCombo:hover, #ConfigCombo:focus {{
    border: 1px solid {border_hover};
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
    selection-background-color: {info_soft};
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
    background: {info_soft};
    color: {text_primary};
}}

#ConfigHelp {{
    color: {text_secondary};
    font-size: 11px;
    padding-top: 2px;
}}
#ConfigHelp[warn="true"] {{
    color: {warning};
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
    border-left: 2px solid {info};
    color: {text_primary};
}}
#ToolButton:checked {{
    background: {info_soft};
    border-left: 2px solid {info};
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
    border-radius: 12px;
}}
#ToolTile:hover {{
    background: {bg_panel_strong};
    border: 1px solid {border_hover};
}}
#ToolTile:disabled {{
    background: {bg_panel};
}}
#TileTitle {{
    color: {text_primary};
    font-size: 15px;
    font-weight: 700;
    background: transparent;
}}
#TileText {{
    color: {text_secondary};
    font-size: 12px;
    background: transparent;
}}
#TileLive {{
    color: {text_muted};
    font-size: 11px;
    background: transparent;
    border-top: 1px solid {border};
    padding-top: 6px;
    margin-top: 6px;
}}
#ToolTile:disabled QLabel {{
    color: {text_muted};
}}
#LinkChip {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 8px;
    color: {text_secondary};
    font-size: 12px;
    padding: 5px 8px;
    text-align: left;
}}
#LinkChip:hover {{
    border: 1px solid {border_hover};
    color: {text_primary};
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
    border-left: none;
    color: {text_secondary};
    font-weight: 600;
    font-size: 12px;
    padding: 6px 12px;
}}
#Segment[pos="first"] {{
    border-left: 1px solid {border};
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
}}
#Segment[pos="last"] {{
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}}
#Segment[pos="only"] {{
    border-left: 1px solid {border};
    border-radius: 8px;
}}
#Segment[compact="true"] {{
    padding: 3px 9px;
    font-size: 11px;
}}
#Segment:hover {{
    background: {bg_hover};
    color: {text_primary};
}}
#Segment:checked {{
    background: {info_soft};
    color: {text_primary};
    border: 1px solid {info_dim};
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
#ShipImage {{
    background: rgba(0, 0, 0, 0.35);
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: {text_muted};
    font-size: 11px;
}}
#AcquiredTag, #ConceptTag {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 3px;
    padding: 1px 6px;
}}
#ShipCard[acquired="pledge"] #AcquiredTag {{
    color: {text_secondary};
    background: {bg_input};
}}
#ShipCard[acquired="ingame"] #AcquiredTag {{
    color: {info};
    background: rgba(141, 180, 207, 0.16);
}}
#ConceptTag {{
    color: {danger};
    background: rgba(226, 106, 85, 0.16);
}}
#LoanerLine {{
    color: {text_secondary};
    font-size: 11px;
    font-style: italic;
}}

#CargoTag {{
    color: {text_secondary};
    font-size: 11px;
    font-weight: 600;
}}
#ShipTitle {{
    color: {text_primary};
    font-size: 22px;
    font-weight: 700;
}}
#StatLine {{
    color: {text_primary};
    font-size: 12px;
}}
#LoadoutGroup {{
    color: {info};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
#LoadoutCount, #LoadoutSize {{
    color: {text_primary};
    font-size: 12px;
    font-weight: 700;
}}
#AcquiredTag[acquired="pledge"] {{
    color: {text_secondary};
    background: {bg_input};
}}
#AcquiredTag[acquired="ingame"] {{
    color: {info};
    background: rgba(141, 180, 207, 0.16);
}}

#StatsNotice {{
    color: {text_primary};
    font-size: 12px;
    background: {info_soft};
    border: 1px solid {info_dim};
    border-radius: 4px;
    padding: 8px 10px;
}}
#InspectorNote {{
    color: {warning};
    font-size: 12px;
}}
#PromptLabel {{
    color: {info};
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
    background: {info_soft};
    border: 1px solid {info_dim};
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
    background: {info_soft};
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

#AboutLabel {{
    color: {text_secondary};
    font-size: 11px;
    background: {bg_panel};
    border-radius: 6px;
    padding: 4px 10px;
}}
#CigNotice {{
    color: {text_secondary};
    font-size: 10px;
    background: transparent;
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
    color: {success};
    font-size: 11px;
}}
#SettingsBad {{
    color: {danger};
    font-size: 11px;
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
    background: {info_soft};
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
    border: 1px solid {border_hover};
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
    background: transparent;
    border: 1px solid {border};
    border-radius: 9px;
}}
#OverlaySwitchLabel {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 700;
}}
#OverlaySwitchHint {{
    color: {text_muted};
    font-size: 11px;
}}

/* -- My Stats ------------------------------------------------------------ */
#StatValue {{
    color: {text_primary};
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
    background: {info_soft};
    border: 1px solid {info_dim};
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
    background: {success_soft};
    border: 1px solid {success};
}}
#LiveCard[state="tracked"] {{
    background: {info_soft};
    border: 1px solid {info_dim};
}}
#LiveCard[state="failed"] {{
    background: rgba(226, 106, 85, 0.10);
    border: 1px solid rgba(226, 106, 85, 0.45);
}}
#LiveCard[flash="true"] {{
    background: rgba(141, 180, 207, 0.32);
    border: 1px solid {info};
}}
#LiveReward {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 800;
}}
#LiveBlueprintOwned {{
    color: {ok};
    font-size: 13px;
}}
#LiveObjective {{
    color: {text_primary};
    font-size: 15px;
}}
#LiveGroup {{
    color: {text_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding-top: 4px;
}}
#LiveTitle {{
    color: {text_primary};
    font-size: 15px;
    font-weight: 600;
}}
#LiveMuted {{
    color: {text_muted};
    font-size: 12px;
}}
#LiveText {{
    color: {text_secondary};
    font-size: 13px;
}}
#LiveGood {{
    color: {ok};
    font-size: 13px;
}}
#LiveBad {{
    color: {danger};
    font-size: 13px;
}}
#LiveValue {{
    color: {text_primary};
    font-size: 16px;
    font-weight: 700;
}}
#LiveChip {{
    background: {bg_input};
    border-radius: 9px;
    color: {text_secondary};
    font-size: 12px;
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
    background: rgba(16, 19, 23, 0.90);
    border: 1px solid {border_strong};
    border-radius: 12px;
}}
#OverlayFrame[clickThrough="true"] {{
    border: 1px dashed {text_muted};
}}
#OverlayHeader, #OverlayMini {{
    background: transparent;
}}
#OverlayGrip {{
    color: {text_muted};
    font-size: 15px;
    padding: 0 4px;
}}
#OverlayTool {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}}
#OverlayTool:hover {{
    background: {bg_hover};
}}
#OverlayTool:checked {{
    background: {info_soft};
    border: 1px solid {info_dim};
}}
#OverlayCaption {{
    color: {text_secondary};
    font-size: 10px;
    font-weight: 600;
    background: transparent;
}}
#OverlayTool:checked #OverlayCaption {{
    color: {text_primary};
}}
#OverlayKey {{
    color: {text_muted};
    font-size: 9px;
    font-weight: 700;
    background: transparent;
}}
#OverlayIcon {{
    background: transparent;
    border: none;
    border-radius: 7px;
    color: {text_secondary};
    font-size: 15px;
}}
#OverlayIcon:hover, #OverlayIcon:checked {{
    background: {bg_hover};
    color: {text_primary};
}}
#OverlayStatus {{
    color: {text_muted};
    font-size: 12px;
    padding: 0 6px 2px 6px;
    background: transparent;
}}
#OverlayMenu {{
    background: rgba(16, 19, 23, 0.98);
    border: 1px solid {border_strong};
    border-radius: 10px;
}}
#OverlayMenuItem {{
    background: transparent;
    border: none;
    border-radius: 7px;
    text-align: left;
}}
#OverlayMenuItem:hover {{
    background: {bg_hover};
}}
#OverlayMenuText {{
    color: {text_primary};
    font-size: 13px;
    background: transparent;
}}
#OverlayMenuKey {{
    color: {text_muted};
    font-size: 11px;
    border: 1px solid {border_strong};
    border-radius: 4px;
    padding: 0 4px;
    max-height: 18px;
    background: transparent;
}}
#OverlayMenuValue {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 700;
}}
#OverlayStep {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 6px;
    color: {text_primary};
    min-width: 24px;
    min-height: 24px;
    font-size: 13px;
}}
#OverlayStep:hover {{
    border: 1px solid {border_hover};
}}
#OverlayMenuSep {{
    background: {border};
    margin: 3px 6px;
}}
#OverlayMiniObjective {{
    color: {text_primary};
    font-size: 14px;
    font-weight: 600;
}}
#OverlayMiniTimer {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 800;
}}
#OverlayMiniPlace {{
    color: {text_muted};
    font-size: 13px;
}}

/* == kit (app.ui.kit) =================================================== */
#ToolPage, #KitScroll, #KitScroll > QWidget > QWidget, #ResultLine,
#LoScroll, #LoScroll > QWidget > QWidget, #LoCards, #LoCards > QWidget > QWidget {{
    background: transparent;
}}
#Panel, #FilterBar {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 12px;
}}
#FilterBar {{
    background: {bg_panel_strong};
}}
#PanelRow {{
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(218, 197, 164, 0.08);
}}
#PanelRow:hover {{
    background: {bg_hover};
}}
#PanelRow[open="true"] {{
    background: rgba(255, 255, 255, 0.03);
    border-bottom: none;
}}
#PanelRow[flagged="true"] {{
    border-left: 2px solid {info};
}}
#FollowLine {{
    background: {info_soft};
    border-radius: 6px;
}}
#FollowText {{
    color: {text_secondary};
    font-size: 12px;
    background: transparent;
}}
#RowDetail {{
    background: rgba(255, 255, 255, 0.03);
    border: none;
    border-bottom: 1px solid rgba(218, 197, 164, 0.08);
}}
#TableHead {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {border};
}}
#PageTitle {{
    color: {text_primary};
    font-size: 20px;
    font-weight: 700;
}}
#PageSubtitle {{
    color: {text_secondary};
    font-size: 12px;
}}
#DataChip {{
    color: {text_muted};
    font-size: 11px;
    border: 1px solid {border};
    border-radius: 10px;
    padding: 3px 10px;
}}
#CapsLabel {{
    color: {text_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
}}
#BodyText {{
    color: {text_secondary};
    font-size: 13px;
}}
#MutedText {{
    color: {text_muted};
    font-size: 12px;
}}
#StrongText {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 600;
}}
#RowName {{
    color: {text_primary};
    font-size: 14px;
    font-weight: 600;
}}
#RowValue {{
    color: {text_secondary};
    font-size: 13px;
}}
#RowValueDim {{
    color: {text_muted};
    font-size: 13px;
}}
#RowKey {{
    color: {text_primary};
    font-size: 15px;
    font-weight: 800;
}}
#RowKey[tone="success"] {{
    color: {success};
}}
#MatchText {{
    color: {info};
    font-size: 12px;
}}
#WarnText {{
    color: {warning};
    font-size: 12px;
}}
#BestText {{
    color: {success};
    font-size: 13px;
    font-weight: 600;
}}
#CardTitle {{
    color: {text_primary};
    font-size: 15px;
    font-weight: 700;
}}
#ChanceText {{
    color: {success};
    font-size: 12px;
}}
#RockPct, #RockName {{
    color: {text_secondary};
    font-size: 12px;
}}
#RockPctHit, #RockNameHit {{
    color: {text_primary};
    font-size: 12px;
    font-weight: 700;
}}
#RockPctDim, #RockNameDim {{
    color: {text_muted};
    font-size: 12px;
}}
#Signature {{
    color: {text_secondary};
    font-size: 11px;
}}
#SignatureDim {{
    color: {text_muted};
    font-size: 11px;
}}
#PickRow {{
    background: transparent;
    border: none;
    border-radius: 6px;
    min-height: 26px;
}}
#PickRow:hover {{
    background: {bg_hover};
}}
#PickRow:checked {{
    background: {info_soft};
}}
#PickBox {{
    border: 1px solid {border_strong};
    border-radius: 3px;
    background: transparent;
}}
#PickBox[on="true"] {{
    background: {info};
    border: 1px solid {info};
}}
#PickName {{
    color: {text_secondary};
    font-size: 12px;
    background: transparent;
}}
#PickName[on="true"] {{
    color: {text_primary};
    font-weight: 600;
}}
#PickCount {{
    color: {text_muted};
    font-size: 11px;
    background: transparent;
}}
#HangarCard {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 12px;
}}
#HangarCard:hover {{
    border: 1px solid {border_hover};
}}
#HangarCard #ShipImage {{
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}}
#MissionCard {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 12px;
}}
#MissionCard:hover {{
    border: 1px solid {border_hover};
}}
#MissionCard[selected="true"] {{
    background: rgba(25, 34, 42, 0.88);
    border: 1px solid {info_dim};
}}
#StatSmall {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 600;
}}
#DetailTitle {{
    color: {text_primary};
    font-size: 17px;
    font-weight: 700;
}}
#ToggleChip {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 13px;
    color: {text_secondary};
    font-size: 12px;
    padding: 4px 11px;
}}
#ToggleChip:hover {{
    border: 1px solid {border_hover};
    color: {text_primary};
}}
#ToggleChip:checked {{
    background: {info_soft};
    border: 1px solid {info_dim};
    color: {text_primary};
}}
#ToggleChip:disabled {{
    color: {text_muted};
}}
#NavItem {{
    background: transparent;
    border: none;
    border-radius: 7px;
    color: {text_secondary};
    font-size: 13px;
    padding: 7px 10px;
    text-align: left;
}}
#NavItem:hover {{
    background: {bg_hover};
    color: {text_primary};
}}
#ResultCount {{
    color: {text_secondary};
    font-size: 12px;
}}
#FilterChip {{
    background: {info_soft};
    border: 1px solid {info_dim};
    border-radius: 10px;
    color: {text_primary};
    font-size: 11px;
    padding: 2px 9px;
}}
#FilterChip:hover {{
    border: 1px solid {info};
}}
#KitButton {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 8px;
    color: {text_secondary};
    font-size: 12px;
    font-weight: 600;
    padding: 6px 12px;
}}
#KitButton:hover {{
    background: {bg_hover};
    border: 1px solid {border_hover};
    color: {text_primary};
}}
#KitButton:checked {{
    background: {info_soft};
    border: 1px solid {info_dim};
    color: {text_primary};
}}
#KitButton:disabled {{
    color: {text_muted};
    background: transparent;
}}
#KitButton[kind="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {accent}, stop:1 #b07c2a);
    border: 1px solid {accent};
    color: #1b1712;
    font-weight: 700;
}}
#KitButton[kind="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #efb453, stop:1 {accent});
    border: 1px solid #f6cf8a;
}}
#KitButton[kind="primary"]:disabled {{
    background: {bg_input};
    border: 1px solid {border};
    color: {text_muted};
}}
#KitButton[kind="ghost"], #HelpToggle {{
    background: transparent;
    border: 1px solid transparent;
    color: {info};
    padding: 3px 6px;
}}
#KitButton[kind="ghost"]:hover, #HelpToggle:hover {{
    color: {text_primary};
    background: transparent;
    border: 1px solid transparent;
    text-decoration: underline;
}}
#HelpToggle {{
    color: {text_muted};
    font-size: 12px;
    font-weight: 500;
}}
#HelpToggle:checked {{
    color: {text_primary};
    background: transparent;
    border: 1px solid transparent;
}}
#ConfigCombo[set="true"] {{
    border: 1px solid {info_dim};
    color: {text_primary};
}}
#SearchField {{
    color: {text_primary};
}}
#SearchField:focus, #ConfigCombo:focus {{
    border: 1px solid {info};
}}
#Badge {{
    border-radius: 9px;
    font-size: 11px;
    font-weight: 700;
    padding: 1px 8px;
    color: {text_secondary};
    background: {bg_input};
}}
#Badge[variant="info"] {{
    color: {info};
    background: {info_soft};
}}
#Badge[variant="success"] {{
    color: {success};
    background: {success_soft};
}}
#Badge[variant="warning"] {{
    color: {warning};
    background: {warning_soft};
}}
#Badge[variant="danger"] {{
    color: {danger};
    background: {danger_soft};
}}
#Badge[variant="accent"] {{
    color: {accent};
    background: {accent_soft};
}}
#Badge[variant="hue"] {{
    background: transparent;
}}
#Rarity {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}
#EmptyState {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 12px;
}}
#EmptyTitle {{
    color: {text_primary};
    font-size: 15px;
    font-weight: 700;
}}
#EmptyText {{
    color: {text_secondary};
    font-size: 13px;
}}
#Notice, #HelpBox {{
    background: {info_soft};
    border: 1px solid {info_dim};
    border-radius: 10px;
}}
#Notice[tone="warning"] {{
    background: {warning_soft};
    border: 1px solid rgba(224, 149, 79, 0.45);
}}
#Notice[tone="danger"] {{
    background: {danger_soft};
    border: 1px solid rgba(226, 106, 85, 0.45);
}}
#Notice[tone="success"] {{
    background: {success_soft};
    border: 1px solid rgba(156, 196, 140, 0.45);
}}
#NoticeText {{
    color: {text_primary};
    font-size: 12px;
    background: transparent;
}}
#NoticeClose {{
    background: transparent;
    border: none;
    color: {text_muted};
    font-size: 12px;
}}
#NoticeClose:hover {{
    color: {text_primary};
}}
#StatBig {{
    color: {text_primary};
    font-size: 24px;
    font-weight: 800;
}}
#StatMid {{
    color: {text_primary};
    font-size: 18px;
    font-weight: 800;
}}
#StatBig[tone="success"], #StatMid[tone="success"] {{
    color: {success};
}}
#StatCaption {{
    color: {text_muted};
    font-size: 11px;
}}
#StatDelta {{
    color: {success};
    font-size: 11px;
}}
#StripCell {{
    background: transparent;
    border: none;
    border-left: 1px solid {border};
}}
#StripCellFirst {{
    background: transparent;
    border: none;
}}
#RankName {{
    color: {text_secondary};
    font-size: 12px;
}}
#RankValue {{
    color: {text_primary};
    font-size: 12px;
    font-weight: 600;
    min-width: 34px;
}}

/* the window: rail, footer */
#ToolRail {{
    background: {bg_panel_strong};
    border: 1px solid {border};
    border-radius: 12px;
}}
#RailItem {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}}
#RailItem:hover {{
    background: {bg_hover};
}}
#RailItem:checked {{
    background: {info_soft};
    border: 1px solid {info_dim};
}}
#RailItem:disabled {{
    background: transparent;
}}
#RailCaption {{
    color: {text_secondary};
    font-size: 10px;
    font-weight: 600;
    background: transparent;
}}
#RailItem:checked #RailCaption {{
    color: {text_primary};
}}
#RailItem:disabled #RailCaption {{
    color: {text_muted};
}}
#RailGame {{
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
    color: {text_muted};
}}
#RailGame[tone="success"] {{
    color: {success};
}}
#RailGame[tone="info"] {{
    color: {info};
}}
#RailGame[tone="warning"] {{
    color: {warning};
}}
/* The overlay's event reminder */
#OverlayReminder {{
    background: {accent_soft};
    border: 1px solid {accent_dim};
    border-radius: 8px;
}}
#OverlayReminderLine {{
    background: transparent;
    border: 0;
    min-height: 24px;
    text-align: left;
}}
#OverlayReminderTitle {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}
#OverlayReminderCount {{
    color: {accent};
    font-family: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}
#OverlayReminderText {{
    color: {text_secondary};
    font-size: 12px;
    background: transparent;
}}
/* Events: the calendar's days, seats, the countdown */
#CalDay {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {text_muted};
    font-size: 12px;
}}
#CalDay[kind="op"] {{
    background: {accent_soft};
    color: {text_primary};
    font-weight: 700;
}}
#CalDay[kind="mine"] {{
    background: {success_soft};
    color: {text_primary};
    font-weight: 700;
}}
#CalDay[kind="op"]:hover, #CalDay[kind="mine"]:hover {{
    border: 1px solid {accent};
}}
#CalDay[today="true"] {{
    border: 1px solid {info};
}}
#EventDate {{
    background: {bg_input};
    border-radius: 8px;
    color: {text_primary};
}}
#Countdown {{
    color: {accent};
    font-family: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
    font-size: 22px;
    font-weight: 700;
}}
#SeatButton {{
    min-height: 30px;
    padding: 0 12px;
    border-radius: 15px;
    font-size: 12px;
    font-weight: 600;
}}
#SeatButton[state="free"] {{
    background: transparent;
    border: 1px dashed {info_dim};
    color: {info};
}}
#SeatButton[state="free"]:hover {{
    background: {info_soft};
    border: 1px solid {info};
}}
#SeatButton[state="free"]:disabled {{
    color: {text_muted};
    border-color: {border};
}}
#SeatButton[state="taken"] {{
    background: {bg_input};
    border: 1px solid {border};
    color: {text_primary};
}}
#SeatButton[state="mine"] {{
    background: {success_soft};
    border: 1px solid {success};
    color: {text_primary};
}}
/* Loadouts (app.ui.loadout_editor): the painted pieces' buttons and the editor's own controls. */
#BusSlot {{
    min-height: 26px;
    padding: 0 6px;
    border: 1px solid rgba(218, 197, 164, 0.22);
    border-radius: 7px;
    background: rgba(11, 13, 16, 0.6);
    color: {text_secondary};
    font-size: 11px;
    font-weight: 700;
}}
#BusSlot:hover {{
    border-color: {info};
}}
#BusSlot:checked {{
    border-color: {info};
    background: {info};
    color: #0b0d10;
}}
#PartGet {{
    min-height: 32px;
    border: 1px solid rgba(218, 197, 164, 0.3);
    border-radius: 10px;
    background: transparent;
    color: {text_primary};
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.7px;
    text-transform: uppercase;
}}
#PartGet:hover {{
    border-color: {info};
}}
#PartGet[pressed="true"] {{
    border-color: {info};
    background: {info};
    color: #0b0d10;
}}
#PartGet:disabled {{
    border: 1px dashed rgba(218, 197, 164, 0.25);
    color: rgba(163, 154, 138, 0.55);
}}
#Toast {{
    background: #1b1f24;
    border: 1px solid {border_strong};
    border-radius: 12px;
}}
#ToastText {{
    color: {text_primary};
    font-size: 13px;
}}
#ToastUndo {{
    min-height: 30px;
    padding: 0 14px;
    border: 1px solid {info_dim};
    border-radius: 8px;
    background: {info_soft};
    color: {text_primary};
    font-weight: 700;
}}
#ToastUndo:hover {{
    border-color: {info};
}}
#LoPill {{
    min-height: 30px;
    padding: 0 12px;
    border: 1px solid rgba(243, 237, 226, 0.28);
    border-radius: 15px;
    background: rgba(11, 13, 16, 0.5);
    color: {text_secondary};
    font-size: 12px;
    font-weight: 600;
}}
#LoPill:hover {{
    border-color: {text_primary};
}}
#LoPill:checked {{
    background: {text_primary};
    border-color: {text_primary};
    color: #0b0d10;
}}
#LoPill[kind="new"] {{
    border-style: dashed;
    color: {info};
}}
#LoCta {{
    min-height: 40px;
    padding: 0 16px;
    border: 1px solid #f6cf8a;
    border-radius: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #efb453, stop:1 #e3a33b);
    color: #1b1712;
    font-size: 14px;
    font-weight: 700;
}}
#LoCta:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f3c06b, stop:1 #e8ac48);
}}
#LoCta:disabled {{
    background: {bg_input};
    border: 1px solid {border};
    color: {text_muted};
}}
#LoBack, #LoLink {{
    border: 0;
    background: transparent;
    color: {text_secondary};
    font-size: 13px;
    font-weight: 600;
    padding: 4px 6px;
}}
#LoLink {{
    color: {info};
}}
#LoBack:hover, #LoLink:hover {{
    color: {text_primary};
    text-decoration: underline;
}}
#LoChip {{
    color: {text_secondary};
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 11px;
    background: rgba(11, 13, 16, 0.6);
}}
#LoSeg {{
    min-height: 30px;
    padding: 0 12px;
    border: 1px solid rgba(218, 197, 164, 0.28);
    background: transparent;
    color: {text_secondary};
    font-size: 12px;
    font-weight: 700;
}}
#LoSeg[pos="first"] {{
    border-top-left-radius: 10px;
    border-bottom-left-radius: 10px;
}}
#LoSeg[pos="last"] {{
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
}}
#LoSeg:checked {{
    background: {info_soft};
    color: {text_primary};
}}
#LoRackTab {{
    min-height: 46px;
    padding: 4px 14px;
    border: 1px solid rgba(218, 197, 164, 0.18);
    border-radius: 12px;
    background: rgba(20, 24, 28, 0.85);
    color: {text_primary};
    text-align: left;
    font-size: 13px;
    font-weight: 700;
}}
#LoRackTab:checked {{
    border-color: {info};
    background: {info_soft};
}}
#LoRackTab:disabled {{
    color: {text_muted};
}}
#LoTrayPort {{
    color: {info};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.6px;
}}
#LoTrayName {{
    font-size: 18px;
    font-weight: 800;
}}
#LoTraySrc, #LoHint {{
    color: {text_secondary};
    font-size: 13px;
}}
#LoHint {{
    color: {text_muted};
    font-size: 12px;
}}
#LoPatch {{
    background: {warning_soft};
    border: 1px solid rgba(224, 149, 79, 0.4);
    border-radius: 12px;
}}
#LoPanel {{
    background: rgba(20, 24, 28, 0.9);
    border: 1px solid rgba(218, 197, 164, 0.14);
    border-radius: 14px;
}}
#KitButton[kind="danger"] {{
    background: {danger_soft};
    border: 1px solid {danger};
    color: {text_primary};
}}
#KitButton[kind="danger"]:hover {{
    background: {danger};
}}
#LoChipBtn {{
    min-height: 28px;
    padding: 0 12px;
    border: 1px solid rgba(218, 197, 164, 0.2);
    border-radius: 14px;
    background: transparent;
    color: {text_secondary};
    font-size: 12px;
    font-weight: 600;
}}
#LoChipBtn:hover {{
    border-color: rgba(218, 197, 164, 0.45);
}}
#LoChipBtn:checked {{
    background: {info_soft};
    border-color: {info};
    color: {text_primary};
}}
#LoPin {{
    border: 1px solid rgba(218, 197, 164, 0.28);
    border-radius: 15px;
    background: rgba(11, 13, 16, 0.6);
    color: {text_secondary};
    font-size: 15px;
    font-weight: 700;
}}
#LoPin:hover {{
    border-color: {info};
}}
#LoPin:checked {{
    background: {info};
    border-color: {info};
    color: #0b0d10;
}}
#LoDock {{
    background: rgba(15, 18, 21, 0.96);
    border: 1px solid rgba(218, 197, 164, 0.14);
    border-radius: 14px;
}}
#LoDialog {{
    background: {bg_panel_solid};
}}
#LoCraftAside {{
    background: rgba(20, 24, 28, 0.9);
    border-right: 1px solid rgba(218, 197, 164, 0.14);
}}
#LoSaveBar {{
    background: rgba(20, 24, 28, 0.9);
    border: 1px solid rgba(218, 197, 164, 0.14);
    border-radius: 14px;
}}
#LoSaveBar[state="saved"] {{
    border-color: rgba(120, 180, 220, 0.35);
}}
#LoSaveBar[state="drift"] {{
    border-color: {warning};
}}
#LoItem, #LoMat {{
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(218, 197, 164, 0.12);
    border-radius: 12px;
}}
#LoItem[done="true"], #LoMat[done="true"] {{
    background: rgba(255, 255, 255, 0.01);
    border-color: {info};
}}
#LoAside {{
    background: transparent;
    border: 1px dashed rgba(218, 197, 164, 0.2);
    border-radius: 12px;
}}
#LoOffer {{
    text-align: left;
    padding: 10px 14px;
    border: 1px solid rgba(218, 197, 164, 0.14);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.02);
    color: {text_primary};
    font-size: 13px;
}}
#LoOffer:hover {{
    border-color: {info};
}}
#LoOffer:checked {{
    background: {info_soft};
    border-color: {info};
}}
#LoRemoveChip {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(218, 197, 164, 0.2);
    border-radius: 12px;
}}
#LoOfflineNote {{
    color: {warning};
    font-size: 13px;
}}
"""


def build_stylesheet() -> str:
    from app import config

    install_fonts()
    # Qt stylesheet urls want forward slashes, on Windows too.
    icons = {"chevron_down": (config.ICONS_DIR / "chevron_down.png").as_posix()}
    return STYLESHEET.format(**PALETTE, **icons)
