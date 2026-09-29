"""Pinned model choices and explicit acquisition for the managed local runtime."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from ..components import action, card
from ..hardware import GIB, assess_model
from ..model_installation import ManagedModels, bundled_models, model_layers, model_option, recommended_entry


class ModelSetupPanel(QWidget):
    def __init__(self, directory, background, application_runner, select_handler, *, preference="", parent=None):
        super().__init__(parent)
        self.directory, self.background, self.application_runner = Path(directory), background, application_runner
        self.catalog, self.task, self.profile = bundled_models(), None, None
        self.manual_choice = bool(preference)
        self.busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content, layout = card("Choose your managed model", (
            "Choose a candidate for this computer, then download it or import a CETA model ZIP. "
            "Start the managed runtime above, then use and test your model. The test sends one short synthetic prompt."
        ))
        outer.addWidget(content)
        self.choice = QComboBox()
        self.choice.setAccessibleName("Managed model candidate")
        self.choice.addItem("Inspect hardware or choose a model", None)
        for entry in self.catalog["entries"]:
            self.choice.addItem(f"{entry['label']} · {model_option(entry).download_bytes / GIB:.2f} GiB", entry["id"])
        index = self.choice.findData(preference)
        self.choice.setCurrentIndex(index if index >= 0 else 0)
        self.choice.currentIndexChanged.connect(self._selected)
        layout.addWidget(self.choice)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.PlainText)
        layout.addWidget(self.details)
        controls = QHBoxLayout()
        self.download_button = action("Download / resume model", self.download, "updates", primary=True)
        self.import_button = action("Import model ZIP…", self.import_archive, "folder")
        self.use_button = action("Use and test model", lambda: select_handler(self.choice.currentData()), "chat")
        self.pause_button = action("Pause", self.pause)
        for button in (self.download_button, self.import_button, self.use_button, self.pause_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        tools = QHBoxLayout()
        self.export_button = action("Export offline model…", self.export_archive)
        self.license_button = action("Model license", self.show_license)
        tools.addWidget(self.export_button); tools.addWidget(self.license_button); tools.addStretch()
        layout.addLayout(tools)
        self.status = QLabel("No model has been tested in this setup session. Hardware fit is an estimate; model quality and GPU acceleration require local checks.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setAccessibleName("Managed model setup status")
        layout.addWidget(self.status)
        self._refresh()

    def entry(self):
        return next((entry for entry in self.catalog["entries"] if entry["id"] == self.choice.currentData()), None)

    def set_hardware(self, profile):
        self.profile = profile
        if profile is not None and not self.manual_choice:
            candidate = recommended_entry(self.catalog["entries"], profile)
            self.choice.blockSignals(True)
            self.choice.setCurrentIndex(self.choice.findData(candidate["id"]) if candidate else 0)
            self.choice.blockSignals(False)
        self._refresh()

    def _selected(self, _):
        self.manual_choice = self.choice.currentData() is not None
        self._refresh()

    def _refresh(self):
        entry = self.entry()
        if entry:
            reason = assess_model(self.profile, model_option(entry)).reason if self.profile else "Hardware has not been inspected in this session."
            self.details.setText(f"{entry['description']}. {reason} Larger models are optional candidates, not a measured quality guarantee.")
        else:
            self.details.setText("No automatic candidate is available until current physical memory is known. Downloads are always explicit.")
        for button in (self.download_button, self.import_button, self.use_button, self.export_button, self.license_button):
            button.setEnabled(entry is not None and not self.busy)
        self.choice.setEnabled(not self.busy)
        self.pause_button.setEnabled(self.busy and self.task is not None)

    def set_busy(self, busy):
        self.busy = busy
        self._refresh()

    def show_license(self):
        entry = self.entry()
        if entry is None:
            return
        notices = [self.catalog["licenses"][layer["digest"]] for layer in model_layers(entry)
                   if layer["mediaType"] == "application/vnd.ollama.image.license"]
        dialog = QMessageBox(self)
        dialog.setWindowTitle(entry["label"] + " license")
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText("The model's pinned upstream license is retained in downloads and offline exports.")
        dialog.setDetailedText("\n\n".join(notices))
        dialog.exec()

    def download(self):
        self._operate("download")

    def import_archive(self):
        name, _ = QFileDialog.getOpenFileName(self, "Import the selected CETA model ZIP", "", "CETA model ZIP (*.zip)")
        if name:
            self._operate("import", Path(name))

    def export_archive(self):
        entry = self.entry()
        if not entry:
            return
        name, _ = QFileDialog.getSaveFileName(self, "Export a new offline model ZIP", entry["id"] + ".zip", "CETA model ZIP (*.zip)")
        if name:
            self._operate("export", Path(name))

    def _operate(self, kind, path=None):
        entry = self.entry()
        if self.task is not None or self.busy or entry is None:
            return
        self.set_busy(True)
        self.status.setText("Checking model files and disk space…")
        def operation(task):
            installer = ManagedModels(self.directory)
            arguments = {"catalog_id": entry["id"], "sha256": entry["sha256"], "managed": True,
                         "path": str(path) if path is not None else None, "inference": False}
            callback = (lambda: installer.export(entry["id"], path, cancelled=task.cancelled, progress=task.token.emit)) if kind == "export" else \
                (lambda: installer.acquire(entry["id"], source=path, cancelled=task.cancelled, progress=task.token.emit))
            return self.application_runner("model." + kind, arguments, callback)
        def completed(result):
            if kind == "export":
                self.status.setText(f"Offline ZIP saved: {result['path']}. Import it on another computer with the same catalog; hardware must be checked there.")
            else:
                self.status.setText(f"{entry['label']} installed; {result['files_verified']} files verified. Start the managed runtime, then use and test this model.")
        self.task = self.background(operation, completed, self.status.setText)
        self.task.token.connect(self.status.setText)
        self.task.finished.connect(self.finished)
        self.pause_button.setEnabled(True)

    def finished(self):
        self.task = None
        self.set_busy(False)

    def pause(self):
        if self.task is not None:
            self.task.cancelled.set()
            self.status.setText("Pausing model setup. Partial files and verified assets will be preserved.")
