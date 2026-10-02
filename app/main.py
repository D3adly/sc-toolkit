import os
import sys

# Commands for an already running SC-Toolkit (e.g. bound to desktop
# shortcuts): forwarded over IPC, no window is opened.
COMMANDS = {
    "--toggle-overlay": "toggle-overlay",
    "--toggle-clickthrough": "toggle-clickthrough",
    "--show": "show",
}


def _arg_value(name: str) -> str | None:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def _run_overlay() -> int:
    layer_shell = "--layer-shell" in sys.argv
    if layer_shell:
        # With the system Python (overlay_host._layer_shell_mode "system"), its
        # PySide6 comes first and the app's other libraries after it.
        extra = os.environ.get("SCT_EXTRA_SITE", "")
        sys.path.extend(p for p in extra.split(os.pathsep) if p and p not in sys.path)
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        os.environ["QT_WAYLAND_SHELL_INTEGRATION"] = "layer-shell"
    elif sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")   # see app.overlay_host
    if sys.stderr is None:
        # Windowed Windows build: no stdout/stderr at all, so prints and
        # tracebacks would vanish. Write them to the overlay's log instead.
        from app import overlay_host

        try:
            overlay_host.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            sys.stdout = sys.stderr = open(overlay_host.LOG_FILE, "a", buffering=1, encoding="utf-8")
        except OSError:
            pass
    from app.ui import overlay

    pid = _arg_value("--parent-pid")
    return overlay.run(int(pid) if pid and pid.isdigit() else None, layer_shell=layer_shell)


def _forward_command(command: str) -> int:
    from PySide6.QtCore import QCoreApplication

    from app import ipc

    _app = QCoreApplication(sys.argv)
    if ipc.send(ipc.MAIN, command):
        return 0
    # Launcher not running: the overlay may still be (it's its own process).
    if command != "show" and ipc.send(ipc.OVERLAY, command):
        return 0
    print("SC-Toolkit isn't running.", file=sys.stderr)
    return 1


def main():
    if "--overlay" in sys.argv:
        sys.exit(_run_overlay())
    for flag, command in COMMANDS.items():
        if flag in sys.argv:
            sys.exit(_forward_command(command))

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from app import backup, config, ipc, settings
    from app.theme import build_stylesheet

    from app import updater

    smoke_test = "--smoke-test" in sys.argv
    updater.after_update(sys.argv)     # started by an update: let the old version exit first
    app = QApplication(sys.argv)

    # Single instance: a second launch brings the running one forward.
    server = None
    if not smoke_test:
        if ipc.send(ipc.MAIN, "show"):
            sys.exit(0)
        server = ipc.CommandServer(ipc.MAIN)
        server.listen()

    config.migrate_legacy_dirs()
    updater.clean_leftovers()
    backup.cleanup_backups(settings.current().backup_root)

    from app.ui.main_window import MainWindow

    app.setApplicationName(config.DISPLAY_NAME)
    # Matches the .desktop file's basename so Wayland/X11 associate this
    # running window with that entry (correct taskbar icon/grouping).
    app.setDesktopFileName("starcitizen-wrapper")
    app.setWindowIcon(QIcon(str(config.APP_ICON)))
    app.setStyleSheet(build_stylesheet())

    window = MainWindow(start_overlay=not smoke_test)
    window.show()
    if server is not None:
        server.command.connect(window.handle_command)

    if smoke_test:
        # CI check that a built executable starts: build the UI, load every
        # tool view's code (they're imported lazily), then quit.
        import importlib

        from PySide6.QtCore import QTimer

        for view in ("bindings_view", "maps_view", "mining_view", "salvage_view", "settings_view",
                     "overlay", "overlay_panels", "overlay_live", "stats_view", "whats_new_view"):
            importlib.import_module(f"app.ui.{view}")
        for module in ("mining", "salvage", "datacore", "socpak", "joyinput", "hotkeys", "gamelog",
                       "contracts", "tracker", "stats"):
            importlib.import_module(f"app.{module}")
        from app import changelog

        if not changelog.sections():
            sys.exit("smoke test: CHANGELOG.md is missing or empty")
        from app.joyinput import JoystickInput

        if not JoystickInput.supported():
            sys.exit("smoke test: joystick input (SDL) failed to load")
        # The overlay window and its compact panels build without game data.
        from app.ui.overlay import OverlayWindow

        probe = OverlayWindow()
        for tool in ("maps", "mining", "salvage", "missions", "session"):
            probe._make_panel(tool)
        QTimer.singleShot(1500, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
