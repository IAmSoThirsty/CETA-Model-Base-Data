"""Native, explicit capability measurements; persisted results stay historical."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ..capabilities import format_report, hardware_identity, measure_configuration
from ..components import action, card
from ..hardware import GPUInfo, HardwareProfile
from runtime.tasks import TaskRuntime


class CapabilitiesPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.task, self.report, self.bound = window, None, None, None
        self.history_task = None
        self.locked = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content, layout = card("What this configuration can do", "A completed response is only a liveness check. Measure instructions, selected-file use and response speed separately.")
        outer.addWidget(content)
        self.disclosure = QLabel("Measure uses the active CETA-managed model, unloads its weights for a cold sample, then sends seven synthetic requests at 4096 context / 1024 output tokens. The request budget is 21 minutes; inspection and stopping can add time. No downloads or project content; a small synthetic file and results are retained locally. Other features stay unqualified.")
        self.disclosure.setWordWrap(True)
        layout.addWidget(self.disclosure)
        buttons = QHBoxLayout()
        self.measure_button = action("Measure this configuration", self.measure)
        self.stop_button = action("Stop measurement", self.stop)
        self.history_button = action("Previous measurements", self.history)
        self.stop_button.setEnabled(False)
        for button in (self.measure_button, self.stop_button, self.history_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel("No measurement in this app session. A saved result never restores readiness.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setAccessibleName("Configuration measurement status")
        layout.addWidget(self.status)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMaximumHeight(220)
        self.results.setAccessibleName("Configuration measurement results")
        self.results.setPlaceholderText("Instruction checks, selected-file checks and observed timings appear here.")
        layout.addWidget(self.results)
        window.model_process.finished.connect(lambda *_: self.invalidate())

    def selection(self):
        w = self.window
        assets = getattr(w.model_process, "managed_assets", None)
        return (w.endpoint.text().strip(), w.model_combo.currentText().strip(), w.owned_runtime_run,
                getattr(assets, "session_id", None))

    def invalidate(self):
        if self.task is not None:
            self.task.cancelled.set()
        if self.report is not None:
            self.bound = None
            self.results.setPlainText(format_report(self.report, historical=True))
            self.status.setText("Configuration changed. Earlier measurements are historical; measure this configuration again.")

    def hardware_changed(self, profile):
        if self.report is not None and (profile is None or
                hardware_identity(profile) != (self.report.get("configuration") or {}).get("hardware")):
            self.invalidate()

    def observe_prepared(self, plan):
        if self.bound is not None and self.report is not None:
            actual = plan.get("budget", {}).get("tokenization", {}).get("binding")
            if (actual != self.report.get("worker_binding") or
                    plan.get("profile", {}).get("max_tokens") != self.report["configuration"]["max_tokens"]):
                self.invalidate()

    def measure(self):
        w = self.window
        if (self.task is not None or self.history_task is not None or w.guided_setup.busy or w.chat_task or w.model_probe_running or
                w.model_preparation or w.model_health_task or w.pack_download_client or w.resident_operation_running or
                w.runtime_setup_panel.task or w.model_setup_panel.task):
            self.status.setText("Finish the active model operation before measuring.")
            return
        selected = self.selection()
        if not selected[1] or not selected[3]:
            self.status.setText("Start and test a CETA-managed model first. External runtimes remain unqualified for this measurement suite.")
            return
        try:
            client = w._configured_model_client(selected[0])
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.bound, self.report = None, None
        self.results.clear()
        self.status.setText("Preparing the measurement. Stop retains completed observations.")
        w.model_probe_running = True
        self.measure_button.setEnabled(False)
        self.history_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.locked = [(item, item.isEnabled()) for item in (*w.advanced_model_controls, w.guided_setup, w.chat_model_combo) if item is not self]
        for item, _ in self.locked:
            item.setEnabled(False)
        directory = w.store.directory
        def run(task):
            client.cancelled = task.cancelled
            runtime = TaskRuntime(directory)
            try:
                return measure_configuration(runtime, client, selected[1], cancelled=task.cancelled, progress=task.token.emit)
            finally:
                runtime.close()
        def measured(report):
            fresh = self.selection() == selected and not self.task.cancelled.is_set()
            if fresh and report.get("hardware_observation"):
                observed = dict(report["hardware_observation"])
                observed["gpus"] = tuple(GPUInfo(**gpu) for gpu in observed["gpus"])
                w._hardware_loaded(HardwareProfile(**observed))
            self.report = report
            self.bound = selected if fresh and report["eligible_session_observation"] else None
            self.results.setPlainText(format_report(report, historical=self.bound is None))
            self.status.setText("Measurement finished. These are bounded synthetic results, not a general quality guarantee."
                                if self.bound else "Measurement incomplete or configuration changed. Recorded results are historical.")
        self.task = w._background(run, measured, lambda error: self.status.setText("Measurement needs attention: " + error))
        self.task.token.connect(self.status.setText)
        self.task.finished.connect(self.finished)

    def finished(self):
        self.task = None
        self.window.model_probe_running = False
        for item, enabled in self.locked:
            item.setEnabled(enabled)
        self.locked = []
        self.measure_button.setEnabled(True)
        self.history_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def stop(self):
        if self.task is not None:
            self.task.cancelled.set()
            self.stop_button.setEnabled(False)
            self.status.setText("Stopping measurement; waiting for the request to settle. Uncertain inference still requires runtime recovery.")

    def history(self):
        if self.task is not None or self.history_task is not None:
            return
        directory = self.window.store.directory
        self.history_button.setEnabled(False)
        self.measure_button.setEnabled(False)
        def read(task):
            runtime = TaskRuntime(directory)
            try:
                runtime.application_project()
                return [row["payload"] for row in runtime.journal.events("application", kind="capability.measurement.result")][-5:]
            finally:
                runtime.close()
        def show(reports):
            self.bound = None
            self.results.setPlainText("\n\n".join(format_report(row, historical=True) for row in reports) or "No previous measurements.")
            self.status.setText("Historical measurements only. Retest in this app session before using them for current choices.")
        task = self.window._background(read, show, lambda error: self.status.setText("Measurement history unavailable: " + error))
        self.history_task = task
        def finished():
            self.history_task = None
            self.history_button.setEnabled(True)
            self.measure_button.setEnabled(True)
        task.finished.connect(finished)
