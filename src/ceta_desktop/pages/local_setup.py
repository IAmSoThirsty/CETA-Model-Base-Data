"""Resumable, explicit setup using the existing governed runtime and model paths."""
from __future__ import annotations

from pathlib import Path
import shutil

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..components import action, card
from ..hardware import GIB, assess_model, format_hardware
from ..model_installation import ManagedModels, model_option, recommended_entry
from ..models import LocalModelClient
from ..runtime_installation import RuntimeInstallation, require_supported_platform


def setup_candidates(entries, profile, preference=""):
    """At most three estimated choices, retaining an explicit saved preference."""
    fitting = [e for e in entries if assess_model(profile, model_option(e)).mode in {"cpu", "gpu"}]
    choices = fitting or entries
    balanced = recommended_entry(entries, profile) or choices[0]
    result = list({e["id"]: e for e in (choices[0], balanced, choices[-1])}.values())
    saved = next((e for e in entries if e["id"] == preference), None)
    if saved and saved not in result:
        result = result[:2] + [saved]
    return result, balanced["id"]


class LocalSetupPanel(QWidget):
    def __init__(self, window, inspect_hardware):
        super().__init__(window)
        self.window, self.inspect_hardware = window, inspect_hardware
        self.profile, self.free_disk, self.task = None, None, None
        self.stage, self.mode, self.busy = "uninspected", "managed", False
        self.owned_run, self.stopping, self.cancel_requested = None, False, False
        self.external_endpoint, self.tested_selection = None, None
        self.test_result = None
        self.locked = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content, layout = card("Set up local AI", "Install a local text model, use a local service you already have, or continue without AI. No download starts until you choose Install and test.")
        outer.addWidget(content)
        modes = QHBoxLayout()
        self.inspect_button = action("Inspect this computer", self.inspect, "refresh")
        self.existing_button = action("Find existing local models", self.discover, "models")
        self.skip_button = action("Continue without AI", self.skip)
        for button in (self.inspect_button, self.existing_button, self.skip_button):
            modes.addWidget(button)
        layout.addLayout(modes)
        self.summary = QLabel("Hardware and installed model readiness have not been checked in this session.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.choice = QComboBox()
        self.choice.setAccessibleName("Guided setup model choice")
        self.choice.currentIndexChanged.connect(self.selection_changed)
        layout.addWidget(self.choice)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.PlainText)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.install_button = action("Install and test", lambda: self.begin("download"), "updates", primary=True)
        self.offline_button = action("Import offline archives…", self.import_archives, "folder")
        self.recheck_button = action("Recheck installed setup", lambda: self.begin("verify"))
        self.test_button = action("Test existing model", self.test_existing)
        for button in (self.install_button, self.offline_button, self.recheck_button, self.test_button):
            row.addWidget(button)
        layout.addLayout(row)
        links = QHBoxLayout()
        self.license_button = action("Review selected licenses", self.licenses)
        self.pause_button = action("Pause setup", self.pause)
        self.chat_button = action("Open Chat", self.open_chat, "chat")
        for button in (self.license_button, self.pause_button, self.chat_button):
            links.addWidget(button)
        layout.addLayout(links)
        self.status = QLabel("Choose a setup path. Browsing, editing and saved conversations work without a model.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setAccessibleName("Guided local setup status")
        layout.addWidget(self.status)
        self.poll = QTimer(self)
        self.poll.setInterval(50)
        self.poll.timeout.connect(self._settle)
        window.runtime_health_changed.connect(self._health)
        window.model_process.finished.connect(lambda *_: self.configuration_changed())
        self.refresh_controls()

    def entry(self):
        return next((e for e in self.window.model_setup_panel.catalog["entries"]
                     if e["id"] == self.choice.currentData()), None) if self.mode == "managed" else None

    def set_hardware(self, profile):
        self.profile = profile
        if profile is not None:
            self.summary.setText(format_hardware(profile))
        else:
            self.summary.setText("Hardware inspection is unavailable. Inspect this computer again before choosing a model.")
        if self.mode != "managed" or self.busy:
            return
        preference = self.choice.currentData() or self.window.store.setting("managed_model_id", "")
        choices, preferred = setup_candidates(self.window.model_setup_panel.catalog["entries"], profile, preference) if profile else ([], "")
        self.choice.blockSignals(True)
        self.choice.clear()
        for entry in choices:
            self.choice.addItem(entry["label"], entry["id"])
        index = self.choice.findData(preference or preferred)
        self.choice.setCurrentIndex(max(0, index))
        self.choice.blockSignals(False)
        self.selection_changed()

    def selection_changed(self):
        self.tested_selection = None
        self.test_result = None
        entry = self.entry()
        if entry:
            spec = self.window.runtime_setup_panel.spec
            size = model_option(entry).download_bytes
            footprint = spec["archive"]["size"] + sum(f["size"] for f in spec["files"].values()) + size + .5*GIB
            assessment = assess_model(self.profile, model_option(entry))
            disk = f" Last observed free disk: {self.free_disk/GIB:.2f} GiB." if self.free_disk is not None else " Disk space is checked before acquisition."
            self.details.setText(f"{assessment.reason}\nOllama {spec['version']}: {spec['archive']['size']/GIB:.2f} GiB; {entry['label']}: {size/GIB:.2f} GiB. Fresh setup needs approximately {footprint/GIB:.2f} GiB disk including staging.{disk}\nSaved under {self.window.store.directory}. Source: official Ollama release and library/qwen3 registry; pinned licenses are available below. Context: 4096 tokens. Install and test obtains these assets, starts a CETA-owned local service and sends a short synthetic prompt. Existing assets are reverified; no project content is sent. Quality and GPU acceleration remain unmeasured.")
        elif self.mode == "existing":
            self.details.setText(f"Service: {self.external_endpoint or self.window.endpoint.text().strip()}. This existing service controls its own privacy settings, model files and workers. Testing sends one short synthetic prompt; CETA will not install or restart it. General response quality remains unmeasured.")
        else:
            self.details.setText("Inspect this computer before choosing a candidate. Unknown memory cannot establish estimated fit.")
        self.refresh_controls()

    def refresh_controls(self):
        managed = self.mode == "managed"
        entry = self.entry() if hasattr(self.window, "model_setup_panel") else None
        fit = entry is not None and self.profile is not None and assess_model(self.profile, model_option(entry)).mode in {"cpu", "gpu"}
        supported = getattr(getattr(self.window, "runtime_setup_panel", None), "supported", False)
        for button in (self.inspect_button, self.existing_button, self.skip_button, self.choice):
            button.setEnabled(not self.busy)
        for button in (self.install_button, self.offline_button, self.recheck_button):
            button.setVisible(managed)
            button.setEnabled(not self.busy and fit and supported)
        self.test_button.setVisible(not managed)
        self.test_button.setEnabled(not self.busy and self.choice.currentData() is not None)
        self.license_button.setEnabled(not self.busy and entry is not None)
        self.pause_button.setEnabled(self.busy and not self.cancel_requested)
        self.chat_button.setEnabled(not self.busy)

    def _busy(self, stage):
        if self.busy:
            return False
        w = self.window
        if w.chat_task or w.model_probe_running or w.model_preparation or w.model_health_task or w.pack_download_client or w.resident_operation_running or w.runtime_setup_panel.task or w.model_setup_panel.task:
            self.status.setText("Finish the active model operation, then retry setup.")
            return False
        self.busy, self.stage, self.cancel_requested = True, stage, False
        self.owned_run = None
        self.tested_selection = None
        self.test_result = None
        self.locked = [(item, item.isEnabled()) for item in (*w.advanced_model_controls, w.chat_model_combo)]
        for item, _ in self.locked:
            item.setEnabled(False)
        self.refresh_controls()
        self.poll.start()
        return True

    def _finish(self, text, stage="attention"):
        if self.cancel_requested:
            text = "Setup paused. Verified and partial files are kept. Retry Install and test to resume, or recheck installed setup without downloading."
            stage = "paused"
        self.status.setText(text)
        self.stage = stage
        self.stopping = True
        self._settle()

    def _settle(self):
        w = self.window
        if self.busy and self.cancel_requested and not w.model_preparation and self.owned_run == w.owned_runtime_run and self.owned_run is not None:
            if w.model_process.state() != QProcess.NotRunning:
                w.stop_local_model()
        if not self.stopping:
            if self.busy and self.stage in {"starting", "testing"} and self.owned_run is not None and w.model_process.state() == QProcess.NotRunning:
                self._finish("Setup needs attention: the owned runtime stopped. Recheck installed setup to retry.")
            return
        active = any(task is not None and task in w.tasks for task in (self.task, w.model_setup_panel.task, w.model_preparation, w.model_health_task))
        if active or w.model_probe_running or (self.cancel_requested and self.owned_run is not None and w.model_process.state() != QProcess.NotRunning):
            return
        self.task, self.busy, self.stopping = None, False, False
        self.poll.stop()
        for item, enabled in self.locked:
            item.setEnabled(enabled)
        self.locked = []
        self.refresh_controls()

    def inspect(self):
        if not self._busy("inspecting"):
            return
        self.mode = "managed"
        self.status.setText("Inspecting this computer's physical memory, graphics and destination disk…")
        def inspected(value):
            if self.cancel_requested:
                return
            profile, self.free_disk = value
            self.window._hardware_loaded(profile)
            self.profile = profile
            self._finish("Choose a candidate, review its size and licenses, then install and test. Offline archives and existing services are also supported.", "choice")
            self.set_hardware(profile)
        self.task = self.window._background(lambda task: (self.inspect_hardware(cancelled=task.cancelled), shutil.disk_usage(self.window.store.directory).free), inspected, self._finish)
        self.task.finished.connect(lambda: QTimer.singleShot(0, self._inspection_finished))

    def _inspection_finished(self):
        self._settle()
        if not self.busy and self.mode == "managed":
            self.set_hardware(self.profile)

    def begin(self, kind, runtime_source=None, model_source=None):
        entry = self.entry()
        if entry is None or self.profile is None or assess_model(self.profile, model_option(entry)).mode not in {"cpu", "gpu"}:
            self.status.setText("Inspect hardware and choose a candidate with estimated memory fit first.")
            return
        if kind not in {"download", "import", "verify"} or (kind == "import" and (runtime_source is None or model_source is None)):
            self.status.setText("Offline setup requires both the pinned runtime ZIP and the selected model ZIP.")
            return
        if not self._busy("acquiring"):
            return
        w = self.window
        self.owned_run = None
        w.store.set_setting("managed_model_id", entry["id"])
        w.store.set_setting("local_setup_path", "managed")
        self.status.setText("Checking the selected assets. Completed files and interrupted transfers are preserved.")
        def acquire(task):
            require_supported_platform()
            runtime, models = RuntimeInstallation(w.store.directory), ManagedModels(w.store.directory)
            common = {"cancelled": task.cancelled, "progress": task.token.emit}
            w._application_action("runtime." + {"download":"install", "import":"import", "verify":"inspect"}[kind],
                {"guided_setup": True, "sha256": runtime.spec["archive"]["sha256"], "source": str(runtime_source) if runtime_source else None},
                lambda: runtime.verify(**common) if kind == "verify" else runtime.acquire(source=runtime_source, **common))
            w._application_action("model." + {"download":"download", "import":"import", "verify":"inspect"}[kind],
                {"guided_setup": True, "catalog_id": entry["id"], "sha256": entry["sha256"], "source": str(model_source) if model_source else None},
                lambda: models.verify(entry["id"], **common) if kind == "verify" else models.acquire(entry["id"], source=model_source, **common))
            result, assets = w._protect_managed_runtime(runtime, task, "Protect and reverify runtime after model acquisition")
            try:
                return result, self.inspect_hardware(cancelled=task.cancelled), assets
            except BaseException:
                assets.close()
                raise
        def acquired(value):
            result, profile, assets = value
            try:
                start(result, profile, assets)
            finally:
                if assets is not getattr(w.model_process, "managed_assets", None):
                    assets.close()
        def start(result, profile, assets):
            if self.cancel_requested:
                return
            w._hardware_loaded(profile)
            if assess_model(profile, model_option(entry)).mode not in {"cpu", "gpu"}:
                self._finish("Assets were preserved, but current memory no longer fits this candidate. Inspect hardware or choose a lighter model.")
                return
            self.stage = "starting"
            self.status.setText("Verified assets. Starting the managed service and checking its local health…")
            recipe = w.owned_runtime_recipe
            if w.model_process.state() != QProcess.NotRunning:
                if not recipe or not recipe.get("managed") or recipe.get("program") != result["executable"] or w.endpoint.text().strip() != recipe["endpoint"]:
                    self._finish("Stop the current owned runtime before starting this managed setup. Its configuration was preserved.")
                    return
                self.owned_run = w.owned_runtime_run
                w._begin_owned_health(self.owned_run)
            elif w._launch_ollama(result["executable"], managed=result, assets=assets):
                self.owned_run = w.owned_runtime_run
            else:
                self._finish(w.model_status.text())
        self.task = w._background(acquire, acquired, self._finish)
        self.task.token.connect(lambda text: self.status.setText(text) if not self.cancel_requested else None)

    def _health(self, observation):
        if not self.busy or self.stage != "starting" or self.cancel_requested or observation.get("run") != self.owned_run:
            return
        if observation.get("error"):
            self._finish("Setup needs attention: " + observation["error"])
            return
        self.stage = "testing"
        self.status.setText("Local service responded. Verifying the selected model and testing one short local response…")
        QTimer.singleShot(0, self._test_managed)

    def _test_managed(self):
        if self.cancel_requested or self.stage != "testing":
            return
        w = self.window
        if self.task in w.tasks or w.model_health_task is not None:
            QTimer.singleShot(20, self._test_managed)
            return
        entry = self.entry()
        w.model_setup_panel.choice.setCurrentIndex(w.model_setup_panel.choice.findData(entry["id"]))
        w.use_managed_model(entry["id"], completed=self._tested, failed=self._finish)

    def _tested(self, result):
        if self.cancel_requested:
            return
        self.test_result = dict(result)
        self.tested_selection = (self.window.endpoint.text().strip(), self.window.model_combo.currentText().strip())
        self.window.store.set_setting("local_setup_entry_dismissed", "yes")
        self.window.setup_entry.setVisible(False)
        self._finish(f"Local text response tested: {result['model']} · {result['elapsed_seconds']:.1f}s. This proves a completed short response; instruction quality and GPU acceleration are unqualified. Open Chat to continue.", "tested")

    def discover(self):
        if not self._busy("discovering"):
            return
        self.mode = "existing"
        self.choice.clear()
        self.external_endpoint = self.window.endpoint.text().strip()
        self.selection_changed()
        self.status.setText("Looking for models at the configured local endpoint. No installation or restart is requested…")
        try:
            client = LocalModelClient(self.external_endpoint)
        except ValueError as exc:
            self._finish(str(exc)); return
        def discover(task):
            client.cancelled = task.cancelled
            return self.window._application_action("model.inspect", {"endpoint": self.external_endpoint, "guided_setup": True}, client.available_models)
        def found(models):
            if self.cancel_requested:
                return
            if self.window.endpoint.text().strip() != self.external_endpoint:
                self._finish("Endpoint changed. Find existing local models again."); return
            for name in models:
                self.choice.addItem(name, name)
            self._finish("Choose an installed model and test it. Existing service privacy settings remain its owner's responsibility." if models else "No eligible local models found. Start your existing service, use managed setup, or continue without AI.", "choice")
        self.task = self.window._background(discover, found, lambda error: self._finish(f"Could not inspect that local service: {error}. Start it, choose managed setup, or continue without AI."))

    def test_existing(self):
        name = self.choice.currentData()
        if self.mode != "existing" or not name or self.window.endpoint.text().strip() != self.external_endpoint:
            self.status.setText("Find existing local models again before testing."); return
        if not self._busy("testing"):
            return
        self.owned_run = None
        self.window.model_combo.setCurrentText(name)
        self.window.store.set_setting("model", name)
        self.window.store.set_setting("local_setup_path", "existing")
        self.status.setText("Testing one short response through the governed local model path…")
        self.task = self.window.probe_model(completed=self._tested, failed=self._finish)

    def import_archives(self):
        runtime, _ = QFileDialog.getOpenFileName(self, "Choose the pinned Ollama runtime ZIP", "", "ZIP (*.zip)")
        if not runtime:
            return
        model, _ = QFileDialog.getOpenFileName(self, "Choose the selected CETA model ZIP", "", "ZIP (*.zip)")
        if model:
            self.begin("import", Path(runtime), Path(model))

    def licenses(self):
        entry = self.entry()
        if entry:
            self.window.model_setup_panel.choice.setCurrentIndex(self.window.model_setup_panel.choice.findData(entry["id"]))
            self.window.runtime_setup_panel.show_licenses()
            self.window.model_setup_panel.show_license()

    def pause(self):
        if not self.busy:
            return
        self.cancel_requested = True
        for task in (self.task, self.window.model_setup_panel.task, self.window.model_health_task):
            if task is not None and task in self.window.tasks:
                task.cancelled.set()
        self._finish("Setup paused. Waiting for active work to stop; verified and partial files are kept. Retry Install and test to resume, or recheck installed setup without downloading.", "paused")

    def skip(self):
        if self.busy:
            return
        self.window.store.set_setting("local_setup_entry_dismissed", "yes")
        self.window.setup_entry.setVisible(False)
        self.window.chat_status.setText("Continue without AI: saved conversations and workspace editing remain available. Set up local AI later from Models.")
        self.open_chat()

    def open_chat(self):
        self.window.navigation.setCurrentRow(0)

    def configuration_changed(self):
        if not self.busy and self.tested_selection is not None:
            self.tested_selection = None
            self.test_result = None
            self.status.setText("Model settings or runtime state changed. The earlier response test does not establish current readiness. Recheck and test again.")
