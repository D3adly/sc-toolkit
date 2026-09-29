import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import backup, config, settings
from app.theme import build_stylesheet
from app.ui.main_window import MainWindow


def main():
    config.migrate_legacy_dirs()
    backup.cleanup_backups(settings.current().backup_root)

    app = QApplication(sys.argv)
    app.setApplicationName(config.DISPLAY_NAME)
    # Matches the .desktop file's basename so Wayland/X11 associate this
    # running window with that entry (correct taskbar icon/grouping).
    app.setDesktopFileName("starcitizen-wrapper")
    app.setWindowIcon(QIcon(str(config.APP_ICON)))
    app.setStyleSheet(build_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
