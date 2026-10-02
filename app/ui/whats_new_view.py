"""What's new: the changelog, plus the available update (if any) with its
notes and the Install button. Opened from the version in the title bar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from app import __version__, changelog, osutil, updater
from app.theme import PALETTE


def _markdown_view(object_name: str) -> QTextBrowser:
    view = QTextBrowser(objectName=object_name)
    view.setOpenLinks(False)
    view.anchorClicked.connect(lambda url: osutil.open_url(url.toString()))
    view.setFrameShape(QFrame.NoFrame)
    return view


def _set_markdown(view: QTextBrowser, text: str) -> None:
    """Markdown with readable links (the importer colours them with the
    application palette's dark blue)."""
    view.setMarkdown(text)
    link = QTextCharFormat()
    link.setForeground(QBrush(QColor(PALETTE["info"])))
    block = view.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.charFormat().isAnchor():
                cursor = QTextCursor(view.document())
                cursor.setPosition(fragment.position())
                cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.KeepAnchor)
                cursor.mergeCharFormat(link)
            it += 1
        block = block.next()


class WhatsNewView(QWidget):
    back_requested = Signal()
    check_requested = Signal()
    install_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 20)
        outer.setSpacing(10)

        bar_frame = QFrame(objectName="ToolBar")
        bar = QHBoxLayout(bar_frame)
        bar.setContentsMargins(10, 8, 10, 8)
        bar.setSpacing(8)
        back = QPushButton("←  Back", objectName="ToolButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        bar.addWidget(back)
        bar.addSpacing(8)
        bar.addWidget(QLabel("WHAT'S NEW", objectName="ConfigLabel"))
        bar.addStretch(1)
        self.check_status = QLabel("", objectName="InspectorHint")
        bar.addWidget(self.check_status)
        self.check_btn = QPushButton("Check for updates", objectName="MiniButton")
        self.check_btn.setCursor(Qt.PointingHandCursor)
        self.check_btn.clicked.connect(self._on_check)
        bar.addWidget(self.check_btn)
        outer.addWidget(bar_frame)

        # The available update: its notes, Install (or the release page).
        self.update_panel = QFrame(objectName="SidePanel")
        upd = QVBoxLayout(self.update_panel)
        upd.setContentsMargins(20, 16, 20, 16)
        upd.setSpacing(8)
        head = QHBoxLayout()
        self.update_title = QLabel("", objectName="SectionLabel")
        head.addWidget(self.update_title)
        head.addStretch(1)
        self.page_btn = QPushButton("Release page", objectName="MiniButton")
        self.page_btn.setCursor(Qt.PointingHandCursor)
        head.addWidget(self.page_btn)
        self.install_btn = QPushButton("Install and restart", objectName="StartButtonSmall")
        self.install_btn.setCursor(Qt.PointingHandCursor)
        self.install_btn.clicked.connect(self.install_requested.emit)
        head.addWidget(self.install_btn)
        upd.addLayout(head)
        self.update_notes = _markdown_view("ChangelogText")
        self.update_notes.setMaximumHeight(170)
        upd.addWidget(self.update_notes)
        self.progress = QProgressBar(objectName="UpdateProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        upd.addWidget(self.progress)
        self.update_status = QLabel("", objectName="InspectorNote")
        self.update_status.setWordWrap(True)
        upd.addWidget(self.update_status)
        self.update_panel.hide()
        outer.addWidget(self.update_panel)

        log_panel = QFrame(objectName="SidePanel")
        log = QVBoxLayout(log_panel)
        log.setContentsMargins(20, 12, 8, 12)
        self.changelog = _markdown_view("ChangelogText")
        _set_markdown(self.changelog, changelog.display_markdown() or "The changelog is missing from this build.")
        log.addWidget(self.changelog)
        outer.addWidget(log_panel, stretch=1)

        about = QLabel(f"You have SC-Toolkit v{__version__}", objectName="AboutLabel")
        outer.addWidget(about, alignment=Qt.AlignRight)
        self._page_url = updater.RELEASES_PAGE
        self.page_btn.clicked.connect(lambda: osutil.open_url(self._page_url))

    # -- called by the main window ------------------------------------------------
    def show_release(self, release: updater.Release | None) -> None:
        self.update_panel.setVisible(release is not None)
        if release is None:
            return
        beta = "  (beta)" if release.prerelease else ""
        self.update_title.setText(f"SC-TOOLKIT {release.version} IS AVAILABLE{beta}")
        _set_markdown(self.update_notes, release.notes or "No release notes.")
        self._page_url = release.page_url
        can_install = updater.install_target() is not None and bool(release.asset_url)
        self.install_btn.setVisible(can_install)
        self.page_btn.setText("Release page" if can_install else "Download from the release page")
        self.progress.hide()
        self.update_status.setText(
            "" if can_install else
            "This copy can't update itself (it runs from source or from a folder it can't write to).")

    def set_checking(self, checking: bool) -> None:
        self.check_btn.setEnabled(not checking)
        if checking:
            self.check_status.setText("Checking…")

    def show_check_result(self, text: str) -> None:
        self.check_btn.setEnabled(True)
        self.check_status.setText(text)

    def set_install_state(self, text: str, busy: bool) -> None:
        self.install_btn.setEnabled(not busy)
        self.check_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
        self.update_status.setText(text)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.update_status.setText(f"Downloading… {done / 1e6:.0f} of {total / 1e6:.0f} MB")

    def _on_check(self) -> None:
        self.set_checking(True)
        self.check_requested.emit()
