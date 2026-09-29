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
- [ ] After **Save**, the main window shows `CONFIG (LIVE)` and START is enabled.

## Launching
- [ ] **START** opens the RSI Launcher.
- [ ] While it runs, the button says **CLOSE**. Pressing it closes the RSI Launcher.
- [ ] After the RSI Launcher closes (by CLOSE or by closing it yourself), the status
      says a backup was saved, or "No config changes since last backup".
- [ ] Start the game from the RSI Launcher and play briefly. When you quit everything,
      does SC-Toolkit notice (does the CLOSE button go back to START)?
- [ ] Pick a backup in the CONFIG dropdown and START: the restore happens without errors.

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
- [ ] Links (Account, SCMDB, SC Maps…) open in your browser.
- [ ] GameGlass (if you use it): set the path in Settings, then the button starts it.

## General
- [ ] Window moves by dragging the title bar; minimise and close work.
- [ ] Settings survive closing and reopening the app
      (`%LOCALAPPDATA%\sc-toolkit\` exists).
