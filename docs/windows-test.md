# Windows test checklist

Thanks for testing SC-Toolkit on Windows! Please go through the list, tick what
works, and note anything odd. Report the results as a
[GitHub issue](https://github.com/D3adly/sc-toolkit/issues/new/choose), with
screenshots if something looks wrong.

Build: `SC-Toolkit-windows.exe` from the release (or workflow artifact) you were given.

## Start-up
- [ ] The exe starts. (SmartScreen may warn: **More info → Run anyway**.)
- [ ] It opens in **Settings** on first run.
- [ ] **Auto-detect** fills in the LIVE folder and `RSI Launcher.exe`. If not, write down
      where your game is installed.
- [ ] After **Save**, the main window shows `LAUNCH WITH (LIVE)` and START is enabled.

## Launching
- [ ] **START** opens the RSI Launcher; the button then says **CLOSE**.
- [ ] Start the game from the RSI Launcher: the button switches to **IN GAME** (greyed out,
      so it can't close the game by accident).
- [ ] Quit the game (leave the RSI Launcher open): within a few seconds the status says a
      backup was saved, or "No keybind changes since the last backup", and the button
      is back to **CLOSE**.
- [ ] Start the game a second time from the same launcher: it's tracked again (IN GAME).
- [ ] **CLOSE** (with the game not running) closes the RSI Launcher, and the button goes
      back to **START**.
- [ ] Closing the RSI Launcher yourself while the game runs: SC-Toolkit keeps waiting, and
      backs up when the game exits.
- [ ] Pick a backup in the LAUNCH WITH dropdown and START: the restore happens without errors.

## Tools
- [ ] **Mining Finder** loads (first time can take ~10 s) and shows locations.
- [ ] **Salvage Claims** loads; **Refresh sheet** and **Refresh prices** work.
- [ ] **Joystick Bindings** opens and shows your bindings.
- [ ] With a supported stick (VKB Gladiator EVO SCE Standard) plugged in, the view says
      **Live input: connected**, and pressing a button highlights its callout.
- [ ] **Button numbering check:** in Star Citizen's own keybinding screen, bind any action
      and press a button — note the `jsX_buttonN` it shows. Press the same button in
      SC-Toolkit's bindings view: it must highlight the callout for that same buttonN.
      Try a few buttons, the hat and the twist axis. Please report the pairs you checked.
- [ ] **Update Star Strings** installs the translation (check the game's
      `Data\Localization\english\global.ini` exists afterwards).
- [ ] Links (Account, SCMDB, Erkul…) open in your browser.
- [ ] **SC Maps** opens inside the launcher: pick a guide (and page), zoom with the wheel,
      drag to pan, double-click to fit; **Original post ↗** opens the browser.
- [ ] GameGlass (if you use it): set the path in Settings, then the button starts it.

## General
- [ ] Window moves by dragging the title bar; minimise and close work.
- [ ] Settings survive closing and reopening the app
      (`%LOCALAPPDATA%\sc-toolkit\` exists).
