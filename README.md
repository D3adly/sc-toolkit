# SC-Toolkit

**A Star Citizen companion launcher and toolkit for Windows and Linux.**

> [!IMPORTANT]
> **Unofficial fan project, not affiliated with Cloud Imperium Games.**
> This project is not affiliated with, endorsed, sponsored or approved by Cloud
> Imperium Games, Roberts Space Industries or any company of the Cloud Imperium
> group. It is a hobby fan project, made for fun and shared for free.
>
> **It is only a wrapper around Star Citizen.** It doesn't include, modify or
> redistribute the game or any of its files. It starts the game through your own
> installed RSI Launcher, backs up your own settings, and reads data from your own
> local installation to display it to you.
>
> Star Citizen®, Squadron 42®, Roberts Space Industries®, Cloud Imperium® and all
> related names, logos, ships, artwork and game data are trademarks and/or
> copyrighted property of **Cloud Imperium Rights LLC** and **Cloud Imperium Rights
> Ltd.** All rights belong to their respective owners.
>
> *This site is not endorsed by or affiliated with the Cloud Imperium or Roberts Space
> Industries group of companies. All game content and materials are copyright Cloud
> Imperium Rights LLC and Cloud Imperium Rights Ltd.. Star Citizen®, Squadron 42®,
> Roberts Space Industries®, and Cloud Imperium® are registered trademarks of Cloud
> Imperium Rights LLC. All rights reserved.*

## Credits: community tools and data

Several features rely on the work of other community members. All credit for their
data and tools goes to them:

| What | Used for | By |
|---|---|---|
| [StarStrings](https://github.com/MrKraken/StarStrings) | The community translation the launcher installs and updates | [MrKraken](https://github.com/MrKraken) |
| [One-page guides & maps](https://mrkraken.space/one-page-guides/) | The **SC Maps** viewer (location and mission maps, shown in the launcher) | [Mr Kraken](https://mrkraken.space/) |
| [Salvaged components spreadsheet](https://docs.google.com/spreadsheets/d/1UyZsa8HPKdwbofoFD3Ve1RhRAtGiG_CZaOUXtM-vEbU) | Salvage Claims: which parts come off each ship, sell/dismantle prices, cargo and fees | [u/PiibaManetta](https://www.reddit.com/user/PiibaManetta/) ([*Salvaged components guide*](https://www.reddit.com/r/starcitizen/comments/1u94sre/salvaged_components_guide/) on r/starcitizen) |
| [UEX Corp](https://uexcorp.space/) | Commodity prices for salvage cargo (via the public UEX API) | The UEX Corp team |
| [LUG Helper](https://github.com/starcitizen-lug/lug-helper) | Its `sc-launch.sh` starts the game on Linux | [Star Citizen Linux Users Group](https://github.com/starcitizen-lug) |
| [VKB-Sim](https://www.vkb-sim.pro/) | Joystick photos in the bindings view (downloaded from VKB, not bundled) | VKB-Sim |

Quick links in the launcher also point to [SCMDB](https://scmdb.net/),
[Erkul](https://erkul.games/), [UEX Corp](https://uexcorp.space/) and
[GameGlass](https://gameglass.gg/), each made by their own creators.

> [!TIP]
> **If you find the data useful, please support the original authors.** Visit their
> sites, star their repositories, and check whether they accept donations or
> Patreon/Ko-fi support. This launcher only shows their work in one place; they do
> the hard part.

---

A companion launcher for Star Citizen on **Linux** and **Windows**. It starts the game
through your normal RSI Launcher. Around that, it keeps your keybinds backed up, and
it adds a few tools that read their data straight from your own game files.

> Windows support is in testing. Linux (Wine / LUG Helper) is the platform it's
> used on daily.

## Features

- **One-click START** with keybind safety. Before launching it can restore a
  backup or a saved binding profile. Every time **the game** closes, it backs up
  your keybinds and control mappings right away (the RSI Launcher can stay open),
  but only when something changed. Old backups are
  pruned automatically.
- **Joystick bindings viewer and editor.** A manual-style picture of your stick
  with every Star Citizen action bound to each button. Rebind by pressing the
  button, and save the result as a named profile to load at launch. The game's own
  files are never edited.
- **Mining Finder.** Pick one or more resources and see every location that has
  them. For each place it shows the rock types, how likely each is to spawn, its
  radar signature (with totals for groups of rocks), how much of your resource it
  holds, and the chance of each quality.
- **Salvage Claims.** For each Adagio salvage-claim difficulty: which ships can
  spawn, their components (and whether they come off), sell vs dismantle prices,
  and cargo aboard priced at UEX averages.
- **StarStrings updater.** Installs the StarStrings community translation, only
  when it matches your game build.
- **SC Maps** viewer: Mr Kraken's community one-page guides and maps, opened inside
  the launcher with zoom and pan (downloaded once, then cached for offline use).
- **In-game overlay:** compact Maps, Mining and Salvage panels on top of the game
  (see [below](#in-game-overlay)).
- **Quick links** to RSI, server status, SCMDB, Erkul and UEX, plus a GameGlass
  shortcut.
- Minimises to the **system tray**, so it keeps running (for the overlay and the
  backup on game exit) without taking space on the taskbar.

Game data (mining, salvage, bindings) is extracted from your installation once
per game patch and cached, so it's always current and works offline.

## In-game overlay

A small always-on-top bar with **Maps**, **Mining** and **Salvage**. Picking one opens
its compact panel underneath; picking it again folds it back to the bar.

Switch it on with **IN-GAME OVERLAY** next to *SC-TOOLKIT TOOLS* in the launcher. While
it's off, nothing runs and the hotkeys do nothing. Then:

| Default key | Action |
|---|---|
| **Ctrl+Shift+O** | Show / hide the overlay |
| **Ctrl+Shift+P** | Click-through: the overlay stays visible, but clicks go to the game |

Change the keys in **Settings → In-game overlay hotkeys** (Ctrl, Alt or Meta plus a
letter, digit or F1–F12). The tray menu has the same actions. Drag the overlay by its
bar, resize it from its bottom-right corner, and set its opacity with the slider; its
position, size and opacity are remembered.

- **Run the game in Borderless mode** (Graphics → Window Mode). Nothing but injected
  overlays can draw over exclusive fullscreen.
- **Anti-cheat safe:** the overlay is an ordinary separate window. It never touches the
  game process (no injection, no hooks), so Easy Anti-Cheat has nothing to object to.
- **Linux:** works on X11 and on Wayland desktops with XWayland (KDE Plasma, GNOME, …):
  the overlay runs through XWayland like the game does, so it can stay on top and see
  the hotkeys. **Steam Deck Game Mode / gamescope is not supported**: gamescope only
  shows the game itself. If the hotkeys don't react, bind a desktop shortcut to
  `SC-Toolkit-linux.AppImage --toggle-overlay` (or `--toggle-clickthrough`).

## Download

Get the latest build for your platform from the
[**Releases page**](../../releases/latest):

| Platform | File |
|---|---|
| Windows 10/11 (64-bit) | [`SC-Toolkit-windows.exe`](../../releases/latest/download/SC-Toolkit-windows.exe) |
| Linux (x86-64) | [`SC-Toolkit-linux.AppImage`](../../releases/latest/download/SC-Toolkit-linux.AppImage) |

Nothing else needs to be installed: Python, Qt and every library are bundled.

### Windows

1. Download `SC-Toolkit-windows.exe` and put it wherever you like.
2. Run it. The exe isn't code-signed, so Windows SmartScreen may say *"Windows
   protected your PC"*. Click **More info → Run anyway** (only the first time).

### Linux

1. Download `SC-Toolkit-linux.AppImage`.
2. Make it executable: right-click → Properties → *Allow executing as program*, or
   `chmod +x SC-Toolkit-linux.AppImage`.
3. Run it. You need a working Star Citizen Wine install, e.g. made with the
   [LUG Helper](https://github.com/starcitizen-lug/lug-helper).

## First-time setup

On first start the launcher opens **Settings** (you can get back there any time
with the ⚙ icon in the title bar). Press **Auto-detect** first; it checks the usual
install locations. Otherwise set:

| Setting | What to pick |
|---|---|
| **Star Citizen LIVE folder** | The `LIVE` folder inside `StarCitizen`, the one containing `Data.p4k`. PTU / EPTU / TECH-PREVIEW next to it are found automatically. On Linux it's inside your Wine prefix: `…/drive_c/Program Files/Roberts Space Industries/StarCitizen/LIVE`. |
| **Launch script** | Windows: `RSI Launcher.exe`. Linux: the script that starts the RSI Launcher, i.e. `sc-launch.sh` in your Wine prefix for LUG Helper installs. |
| **GameGlass** *(optional)* | The GameGlass executable, if you use it. |
| **Backup folder** *(optional)* | Where backups and binding profiles go. The default is the app's data folder. |

Your settings, backups and cached data live in your user profile, not next to the
program, so replacing the exe or AppImage with a newer version keeps everything:

- Windows: `%LOCALAPPDATA%\sc-toolkit\`
- Linux: `~/.config/sc-toolkit/`, `~/.cache/sc-toolkit/`,
  `~/.local/share/sc-toolkit/`

## Supported joysticks

The bindings diagram needs a drawing template for each stick model. Currently
supported:

- **VKB Gladiator EVO SCE (Standard grip)**, left and right

Any other device still works everywhere else in the launcher (backups, profiles,
the game itself); it just has no diagram yet.

**Want your stick supported?**
[Open a joystick profile request](../../issues/new?template=joystick-profile.yml)
on the Issues page. The form asks for the model, grip, and the device name the
launcher shows. A GitHub account is all you need; please don't send requests by
email.

Found a bug or have an idea? [Open an issue](../../issues/new/choose).

## Running from source

Requires **Python 3.14+**.

```bash
git clone https://github.com/D3adly/sc-toolkit.git
cd sc-toolkit
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip install -r requirements.txt
./run.sh                                    # Windows: .venv\Scripts\python -m app.main
```

## Building & releasing

Builds are made by GitHub Actions ([`.github/workflows/build.yml`](.github/workflows/build.yml))
on Windows and Ubuntu 22.04, smoke-tested, and attached to a GitHub Release:

1. Bump `__version__` in [`app/__init__.py`](app/__init__.py) and commit.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.
   Tags with a suffix (e.g. `v0.2.0-beta.1`) become pre-releases.

For a test build without a release, run the workflow manually (**Actions → Build &
release → Run workflow**) and download the files from the run's artifacts.

To build locally: `packaging/build_linux.sh` (AppImage) or
`packaging/build_windows.ps1` (exe), with `pyinstaller` installed next to the
requirements.

## Contact

- **Bugs, ideas, joystick profile requests:** please use
  [GitHub Issues](../../issues/new/choose), so everything is tracked in one place and
  other users can find it.
- **Anything else:** you can reach me on Discord as
  [**Butundux**](https://discord.com/users/144121804582158336). The link opens my
  profile, where you can send a friend request.

## License

The source code is licensed under the **GNU General Public License v3.0**; see
[`LICENSE`](LICENSE).

The GPL covers the code only. Artwork and logos in `assets/` belong to their
respective owners and are **not** covered by it:

- **Background wallpaper** (`assets/background.jpg`):
  official *Star Citizen Fankit* wallpaper (SC_26, the Corsair), © Cloud Imperium Rights LLC and
  Cloud Imperium Rights Ltd., used under the
  [Fankit Agreement](https://robertsspaceindustries.com/en/fankit) for this
  non-commercial fan project, with its watermark kept visible as the agreement requires.
- Other Star Citizen / RSI imagery and logos: © Cloud Imperium Rights LLC.
- Link-button icons are the logos of the linked sites (RSI, SCMDB, Erkul, UEX Corp,
  GameGlass, SC Maps, StarStrings) and belong to those projects.
- Joystick photos are not included: they are the manufacturer's copyrighted product
  photos, so SC-Toolkit downloads them from the manufacturer's site the first time the
  bindings view needs them instead of redistributing them.

## Disclaimer

Figures such as mining quality odds and salvage values are estimates derived from
game data and community sources; always double-check in game. See the notice at the
top of this page for trademark and affiliation details.
