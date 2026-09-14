"""Updates page: signed update verification, download, and installer handoff."""

from __future__ import annotations

from importlib.resources import files
import json
import os
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QScrollArea, QVBoxLayout, QWidget,
)

from .. import __version__
from ..components import action, card
from ..theme import ScenePage
from ..updates import check_update, download_update


class UpdatesPage(ScenePage):
    """Check signed update channel, verify publisher receipt, and stage update."""

    install_requested = Signal(object, dict)

    def __init__(
        self,
        background_runner: Callable,
        active_work_check: Callable[[], bool],
        install_handler: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(scene="updates", parent=parent)
        self.background_runner = background_runner
        self.active_work_check = active_work_check
        self.install_handler = install_handler

        self.update_manifest: dict | None = None
        self.downloaded_update: tuple[Path, dict] | None = None
        self.update_task = None
        self.pending_update = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("pageContent")
        content.setAutoFillBackground(False)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        heading = QLabel("Updates")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)

        description = QLabel("Keep your workspace moving forward. Updates happen when you choose.")
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(description)

        release, release_layout = card(f"CETA {__version__}", "Windows native desktop · Personal publisher verification")
        self.update_status = QLabel("No public update channel is configured for this development build.")
        self.update_status.setWordWrap(True)
        self.update_status.setObjectName("muted")
        self.update_channel = json.loads(files("ceta_desktop").joinpath("release_channel.json").read_text(encoding="utf-8"))
        if self.update_channel.get("url") and self.update_channel.get("public_key"):
            self.update_status.setText("Ready to check the publisher's signed update channel.")
        release_layout.addWidget(self.update_status)

        row = QHBoxLayout()
        self.check_update_button = action("Check for updates", self.check_for_updates, "refresh", primary=True)
        self.check_update_button.setEnabled(bool(self.update_channel.get("url") and self.update_channel.get("public_key")))
        row.addWidget(self.check_update_button)
        self.download_update_button = action("Download verified update…", self.save_update, "updates")
        self.download_update_button.setEnabled(False)
        row.addWidget(self.download_update_button)
        row.addStretch()
        release_layout.addLayout(row)

        install_row = QHBoxLayout()
        self.cancel_update_button = action("Cancel download", self.cancel_update_download)
        self.cancel_update_button.setEnabled(False)
        install_row.addWidget(self.cancel_update_button)
        self.install_update_button = action("Install update and close CETA…", self.install_handler or self.install_update, "updates", primary=True)
        self.install_update_button.setEnabled(False)
        install_row.addWidget(self.install_update_button)
        install_row.addStretch()
        release_layout.addLayout(install_row)
        layout.addWidget(release)

        security, security_layout = card(
            "A signature you can verify",
            "CETA verifies the publisher's signed update receipt and the installer's exact bytes before offering installation. "
            "Application updates are separate from model packs."
        )
        note = QLabel(
            "This release uses a personal Ed25519 publisher key. Windows may show an unrecognized-publisher warning. "
            "Confirm the public-key fingerprint directly with the publisher. No root certificate is installed."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        security_layout.addWidget(note)
        layout.addWidget(security)

        about, about_layout = card(
            "Built for your computer",
            "Conversations, settings, and model packs are retained during updates. Close active work before installing."
        )
        notice = QLabel(
            "Built with Qt, PySide6, and Shiboken under LGPLv3. License texts and matching library sources accompany this release."
        )
        notice.setWordWrap(True)
        notice.setObjectName("muted")
        about_layout.addWidget(notice)

        notices = QHBoxLayout()
        notices.addWidget(action("About Qt", QApplication.aboutQt))
        notices.addWidget(action("Dependency notices", self.open_dependency_notices, "library"))
        notices.addStretch()
        about_layout.addLayout(notices)
        layout.addWidget(about)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def open_dependency_notices(self) -> None:
        directory = Path(sys.executable).parent / "ThirdPartyNotices" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3] / "licenses"
        if not directory.is_dir() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            self.update_status.setText(f"Dependency notices: {directory}")

    def check_for_updates(self) -> None:
        if self.update_task:
            return
        self.update_manifest = None
        self.downloaded_update = None
        self.install_update_button.setEnabled(False)
        self.download_update_button.setEnabled(False)
        self.check_update_button.setEnabled(False)
        self.update_status.setText("Checking the publisher's signed update information…")

        def found(manifest):
            self.update_manifest = manifest
            self.update_status.setText(f"CETA {manifest['version']} is available. Publisher signature verified.")
            self.download_update_button.setEnabled(True)

        task = self.background_runner(
            lambda _: check_update(self.update_channel["url"], self.update_channel["public_key"], __version__),
            found,
            lambda error: self.update_status.setText(str(error)),
        )
        task.finished.connect(lambda: self.check_update_button.setEnabled(True))

    def save_update(self) -> None:
        if not self.update_manifest or self.update_task:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save verified update")
        if not folder:
            return
        self.download_update_button.setEnabled(False)
        self.check_update_button.setEnabled(False)
        self.cancel_update_button.setEnabled(True)
        self.update_status.setText("Downloading and verifying the update…")
        self.downloaded_update = None
        self.install_update_button.setEnabled(False)
        manifest = dict(self.update_manifest)
        task = self.background_runner(
            lambda task: download_update(
                manifest,
                Path(folder),
                task.cancelled,
                lambda count, total: task.token.emit(f"Downloading update · {count / total:.0%}"),
            ),
            lambda path: self._update_saved(path, manifest),
            lambda error: self.update_status.setText(str(error)),
        )
        self.update_task = task
        task.token.connect(self.update_status.setText)
        task.finished.connect(self._update_download_finished)

    def cancel_update_download(self) -> None:
        if self.update_task:
            self.update_task.cancelled.set()
            self.cancel_update_button.setEnabled(False)
            self.update_status.setText("Cancelling update download…")

    def _update_download_finished(self) -> None:
        self.update_task = None
        self.check_update_button.setEnabled(True)
        self.download_update_button.setEnabled(True)
        self.cancel_update_button.setEnabled(False)

    def _update_saved(self, path: Path, manifest: dict) -> None:
        self.downloaded_update = (Path(path), dict(manifest))
        self.install_update_button.setEnabled(os.name == "nt")
        self.update_status.setText(
            f"Verified update saved to {path}. Choose Install update when ready. Your conversations and model packs are retained."
        )

    def install_update(self) -> None:
        if not self.downloaded_update or os.name != "nt":
            return
        if self.active_work_check():
            self.update_status.setText("Stop active conversations, downloads, and workloads before installing the update.")
            return
        answer = QMessageBox.question(
            self,
            "Install CETA update",
            "Close CETA and start the verified installer? Any model service started by CETA will stop. Your saved conversations and model packs will remain.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        path, manifest = self.downloaded_update
        self.install_requested.emit(path, manifest)
