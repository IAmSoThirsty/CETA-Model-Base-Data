"""Explicit managed runtime acquisition controls for the native Models page."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from ..components import action, card
from ..runtime_installation import RuntimeInstallation, bundled_runtime, require_supported_platform


class RuntimeSetupPanel(QWidget):
    def __init__(self, directory, background, application_runner, start_handler, parent=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.background = background
        self.application_runner = application_runner
        self.task = None
        self.spec = bundled_runtime()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        size = self.spec["archive"]["size"] / 1024**3
        total = size + sum(row["size"] for row in self.spec["files"].values()) / 1024**3
        content, layout = card("CETA-managed runtime", (
            f"Ollama {self.spec['version']} for Windows x64 · {size:.2f} GiB download · "
            f"at least {total + .25:.2f} GiB free disk space. Models need additional space. "
            "Install from the official release or import that archive offline. Your existing Ollama installation stays separate."
        ))
        outer.addWidget(content)
        controls = QHBoxLayout()
        self.download_button = action("Download / resume runtime", self.download, "updates", primary=True)
        self.import_button = action("Import runtime ZIP…", self.import_archive, "folder")
        self.start_button = action("Start managed runtime", start_handler, "models")
        self.pause_button = action("Pause", self.pause)
        self.pause_button.setEnabled(False)
        for button in (self.download_button, self.import_button, self.start_button, self.pause_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.status = QLabel("Setup has not checked the installed files. Starting rechecks all pinned runtime files; service health and model inference are separate checks.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setAccessibleName("Managed runtime setup status")
        layout.addWidget(self.status)
        layout.addWidget(action("Runtime licenses", self.show_licenses), 0, Qt.AlignLeft)
        self.supported = True
        try:
            require_supported_platform()
        except ValueError as exc:
            self.supported = False
            self.status.setText(str(exc))
            self.set_busy(False)

    def set_busy(self, busy):
        for control in (self.download_button, self.import_button, self.start_button):
            control.setEnabled(self.supported and not busy)
        self.pause_button.setEnabled(busy and self.task is not None)

    def show_licenses(self):
        license = self.spec["license"]
        text = (license["notice"] + "\n\nUpstream license: " + license["url"] +
                "\n\nThe runtime also includes the following dependency license files, retained and verified during installation:\n" +
                "\n".join(license["bundled_notices"]))
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Managed runtime licenses")
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText("Ollama is provided under the MIT license. Runtime dependencies carry their own notices.")
        dialog.setDetailedText(text)
        dialog.exec()

    def download(self):
        self._acquire()

    def import_archive(self):
        if self.task is not None:
            return
        name, _ = QFileDialog.getOpenFileName(self, "Import the pinned Ollama runtime archive", "", "Runtime ZIP (*.zip)")
        if name:
            self._acquire(Path(name))

    def _acquire(self, source=None):
        if self.task is not None or not self.supported:
            return
        self.set_busy(True)
        self.status.setText("Checking the runtime files and available disk space…")

        def acquire(task):
            installer = RuntimeInstallation(self.directory)
            arguments = {"backend": "ollama", "version": self.spec["version"],
                         "archive_sha256": self.spec["archive"]["sha256"],
                         "source": str(source) if source else self.spec["archive"]["url"],
                         "destination": str(installer.destination), "starts_runtime": False}
            return self.application_runner("runtime.import" if source else "runtime.install", arguments,
                lambda: installer.acquire(source=source, cancelled=task.cancelled, progress=task.token.emit))

        def complete(result):
            self.status.setText(f"Ollama {result['version']} installed; {result['files_verified']} pinned files verified. "
                                "Use Start managed runtime next. No model has been downloaded or tested.")

        self.task = self.background(acquire, complete, self.status.setText)
        self.task.token.connect(self.status.setText)
        self.task.finished.connect(self._finished)
        self.pause_button.setEnabled(True)

    def _finished(self):
        self.task = None
        self.set_busy(False)

    def pause(self):
        if self.task is not None:
            self.task.cancelled.set()
            self.status.setText("Pausing runtime setup. Completed files and partial downloads will remain available.")
