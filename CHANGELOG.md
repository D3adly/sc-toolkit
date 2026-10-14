# Changelog

What changed in each SC-Toolbox release (called SC-Toolkit until 0.2.x). The newest version is at the top.

## Unreleased

- **A new look, the same on every tool.** Every tool now has the same layout: a header with what it's
  for and where its data comes from, one filter bar, a result line with the count and your active
  filters (click ✕ on one to remove it, or *Clear filters*), then the results. Explanations that used
  to fill the screen are behind *How to read this*. The colours now mean the same thing everywhere,
  and on the website: amber is the one main button, steel blue is what you've selected, green is the
  best value or something you have. The text is now Inter, bundled with the app, and numbers line
  up in columns.

- **A tool rail on the left replaces Back.** Every tool, the launch screen and Settings are one click
  away from anywhere, and a light at its bottom shows the game's state: Ready, Launcher (the
  RSI Launcher is open) or In game. It follows the running programs, also when you started the game
  without SC-Toolbox or before it, and START says so instead of trying to launch a second copy; signed in, the title bar shows your avatar and name; the window no longer resizes when you switch. Tool pages dim the wallpaper so
  tables are easier to read.

- **Salvage Claims:** one table with a single header row; the best net value is green, and a bar
  shows each ship's value split into components and cargo, so they can be compared at a glance.

- **Mining Finder:** places are sorted by the best chance of finding the ores you picked, with that
  chance on each card. The ore you picked stands out and the other rocks fade back; the single-rock
  radar signature (RS) is bold. The resource list shows each ore's rarity and how many places have it.

- **New: Mission Database** (the Missions tool). Every mission in the game files: search by name,
  contractor or the blueprints it rewards; filter by system, type and contractor, and under *More
  filters* by legal or illegal, events, rewards (blueprints, fixed pay, items) and the work (ship
  or on-foot combat, cargo, repeatable, not part of a chain); sort by most rep, most blueprints,
  quickest, easiest and more. Click a mission for its details: description, rank, rewards, cargo,
  time, difficulty, stages and the blueprints it can give. **Blueprints you don't have** is worked out
  from your own game logs, without signing in. Event missions are hidden until you pick the event,
  as on the website.

- **The launch screen** shows each tool with one line on what it's for and a live line (how many
  missions and locations the game has, your ship count, saved binding profiles…), plus a **Last
  session** card: time played, missions done, blueprints and deaths. The link buttons are now a
  compact group, and *sc-toolbox.com* has its own tile for the Blueprint and Ship databases.

- **Links between tools:** from a mission's details, *Find this ore in the Mining Finder*; from the
  Mining Finder, *Missions with this ore*; from a salvage claim ship, its page in the online Ship
  Database. Every tool's header links to its website version.

- **Overlay, easier at a glance:** the tools are labelled under their icons, with their key (1–5
  while the overlay has the keyboard). A line under the bar always shows whether click-through is on
  and names whatever the pointer is on, so nothing needs a tooltip. Opacity now fades only the
  background, never the text. Opacity, Hide and Settings moved into a ⋯ menu inside the overlay.
  New: **minimise** the overlay to one line with your current objective (it wraps rather than
  widening the overlay), how long you've been on it, and where you are. Mission cards show the current objective first, larger; blueprints received this
  session show which mission they came from.

- **My Ships, Maps, Joystick Bindings, Settings and What's new** have the same header and filter
  bar as the other tools. Settings has a short list of its sections on the left. My Ships shows fleet totals (pledged, in game, in concept, cargo) and your
  filters as removable chips. Joystick Bindings asks before leaving with unsaved changes.

- **My Stats:** new *Last 30 days* and *Last 7 days* periods next to All time and Last session, four
  headline figures at the top, and the longest lists as top-5 bar charts with *Show all*.

## 0.3.0 (2026-10-13)

- **SC-Toolkit is now SC-Toolbox.** Only the name changes: your settings, saved data, sign-in and
  hotkeys stay as they are, updates keep arriving the usual way, and the website is now
  https://sc-toolbox.com.

- **Windows: the .exe now carries its details** (Properties → Details: SC-Toolbox, version,
  description). Files without them are more often flagged by mistake by antivirus programs.

- **Online account (optional):** *Sign in* at the top right (next to ⚙), or Settings → *Online
  account*, signs the launcher in to the SC-Toolbox online service with Discord, in your browser. Once
  signed in, your name shows there instead. The launcher never sees a password: it gets a sign-in
  that's kept in your system's password store (Windows Credential Manager, or KWallet / GNOME Keyring
  on Linux), so you stay signed in after a restart. *Sign out* ends it on the service too. Nothing
  changes if you don't sign in. The service is sc-toolbox.com, built in (no address to set).

- **Fix: ship list refresh failing with "got 298 of 299".** The Star Citizen Wiki's ship pages
  could repeat some ships and skip others, so the download was refused as incomplete. The list is
  now fetched in a stable order.

## 0.2.1 (2026-10-04)

- **Joystick bindings: Logitech / Saitek X56 H.O.T.A.S.** The bindings view now draws the X56 stick
  and throttle (Saitek *X-56 Rhino* and Logitech-branded units), with Logitech's product photos
  (downloaded on first use, not bundled). The X56's button numbers are fixed, so every control
  shows its bindings right away; *Identify the rest* asks only for the few inputs that can differ
  (throttle H/I, SLD, mini-stick click, mode switch). A HOTAS shows as STICK / THROTTLE, throttle
  first.
- **Joystick photos download only when needed:** the view fetches a model's photo the first time a
  device uses that model, instead of every model's photo up front.

## 0.2.0 (2026-10-02)

- **My Ships** (new tool): your hangar as a grid of ship cards. Add the ships you own from a list
  of every ship, including ships still in concept and ones you can only get in game, and mark
  each as pledged (gold outline) or bought in game (blue outline). Filter by role, size, purchase
  and status; give a ship your own name and note its insurance. Ships in concept show their
  loaners, and released ships have an **Erkul** button that opens them on erkul.games. Each card
  shows the ship's cargo; click it for the ship's details: its default loadout (weapons, turrets,
  missiles, systems) and stats (speeds, shields and hull, power and cooling, quantum and fuel),
  read from your game files. Ship list and pictures: Star Citizen Wiki.
- **Game updates handled for you:** SC-Toolkit reads the game files once per game version, in the
  background, for every tool at once (before, each tool read them again the first time you opened
  it). It notices game updates from the RSI Launcher's log (new setting, found automatically): while
  an update installs, the tools and the overlay keep the previous version's data, and as soon as it's
  done they switch to the new one, without a restart.
- **Settings → Refresh data:** reads the game files again and downloads whatever is due, if
  something ever looks wrong.
- **Layout:** the IN-GAME OVERLAY and LIVE LOG switches moved to the left panel (under IN GAME); the
  In-game Overlay tile moved to Settings (with an *Open the overlay* button).
- **Downloads only when needed:** the ship list is refreshed weekly, the salvage spreadsheet and UEX
  prices at most once a day, all at startup. A small line under the launch status shows what
  SC-Toolkit is doing.
- **My Stats → Blueprints:** a clear note that this is a log of the blueprints you received (since your
  oldest game log), not your blueprint collection. Only LIVE counts now: blueprints received on PTU,
  EPTU or Tech Preview were mixed in before. Blueprints are sorted into the right types more reliably
  (names from before or after installing StarStrings or a translation now match), and ones the
  current game no longer knows are sorted by their name instead of landing in Other.
- **Overlay mission cards:** "blueprints owned" only counts blueprints from the server you're playing on.

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
