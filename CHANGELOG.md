# Changelog

What changed in each SC-Toolkit release. The newest version is at the top.

## 0.1.1 (2026-10-02)

- **Updates from inside SC-Toolkit.** It checks GitHub for a new version once a day; when there is
  one, an *Update* button shows next to the version at the top. One click downloads the new version,
  checks it and restarts SC-Toolkit. Turn the check off, or opt into beta versions, in Settings.
- **What's new:** click the version at the top to see this list.
- **Keybind backups:** no more new backup after every game session when nothing changed. The game
  saves the speed limiter's last value with your settings, and that counted as a change.
- **Linux:** the downloadable AppImage now has the layer-shell overlay on KDE Plasma (Wayland), so
  clicking the overlay no longer hands the focus back to the game.

## 0.1.0 (2026-10-01)

The first stable release, the same as 0.1.0-beta.6.

- **START** opens the RSI Launcher and backs up your keybinds every time the game closes. Restore a
  backup or a saved binding profile with *LAUNCH WITH*.
- **Joystick Bindings:** see and edit what every button of your sticks does, save it as a profile.
- **Salvage**, **Mining** and **SC Maps** tools, built from the game's own files.
- **My Stats** from your Game.log: missions, blueprints, ships, refining and play time.
- **In-game overlay** (F7 / F8): Missions, Session, Maps, Mining and Salvage on top of the game,
  without touching the game process.
- StarStrings translation updater, GameGlass shortcut and quick links.

## 0.1.0-beta.6 (2026-10-01)

- **My Stats** (new tool): missions, blueprints by type, ships, refining and play time from your
  Game.log, for all time or the last session.
- **LIVE LOG** switch: SC-Toolkit follows Game.log while you play.
- **Overlay Missions tab:** your active missions with contractor, rewards, combat tags and the next
  objective; the mission that just changed is highlighted. **Session tab:** what happened this session.
- Overlay on KDE Plasma (Wayland): clicks no longer hand the focus back to the game.
- Windows: overlay hotkeys should now work while the game has focus (needs testing).
- HOTFIX channel support.

## 0.1.0-beta.5 (2026-09-30)

- Windows: overlay hotkeys work.
- Overlay: compact Mining and Salvage panels; fixed a crash when opening a mining location; tool
  panels no longer cut off their header buttons.
- Overlay log on Windows (`overlay.log`) for troubleshooting.
- Maximise / restore button for the launcher window.

## 0.1.0-beta.4 (2026-09-29)

- **In-game overlay:** an always-on-top window over the game (Borderless mode) with Maps, Mining and
  Salvage panels, opacity, click-through, and an IN-GAME OVERLAY switch.
- Hotkeys F7 (overlay) and F8 (click-through), changeable in Settings; KDE global shortcuts on Plasma.
- Minimises to the system tray.
- New app and tool icons.

## 0.1.0-beta.3 (2026-09-29)

- New look: gold and slate theme, three-column main screen with tool tiles.
- Keybinds are backed up every time the game closes; CLOSE can't kill a running game.
- SC Maps opens inside SC-Toolkit.
- Joystick Bindings: *Unassign all*.
- Readable dialog buttons.

## 0.1.0-beta.2 (2026-09-29)

- Joystick live input on Windows and Linux (SDL2): press a button to find its binding.

## 0.1.0-beta.1 (2026-09-29)

The first public test version: START with keybind backups and profiles, Joystick Bindings,
Salvage, Mining, StarStrings updater, quick links and Settings, for Linux and Windows.
