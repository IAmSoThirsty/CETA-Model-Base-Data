from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from ceta_desktop.hardware import GIB, HardwareProfile
from ceta_desktop.model_installation import ManagedModels, model_name
from test_desktop_model_installation import model_fixture
from test_desktop_runtime_installation import Response

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    from ceta_desktop.app import MainWindow
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT and os.name == "nt", "Windows native desktop extra required")
class ManagedModelUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.catalog, self.content = model_fixture()
        self.entry = self.catalog["entries"][0]
        self.enterContext(patch("ceta_desktop.pages.model_setup.bundled_models", return_value=self.catalog))
        self.window = MainWindow(self.root / "data")
        self.panel = self.window.model_setup_panel
        self.installer = ManagedModels(self.root / "data", self.catalog)
        self.enterContext(patch("ceta_desktop.pages.model_setup.ManagedModels", return_value=self.installer))
        self.enterContext(patch("ceta_desktop.app.ManagedModels", return_value=self.installer))
        self.hardware = self.enterContext(patch("ceta_desktop.app.inspect_hardware", return_value=HardwareProfile(16*GIB,12*GIB,4)))

    def finish(self):
        deadline = time.monotonic()+6
        while self.window.tasks and time.monotonic()<deadline:
            self.application.processEvents(); time.sleep(.005)
        self.application.processEvents()
        self.assertEqual(self.window.tasks, [])

    def tearDown(self):
        for task in self.window.tasks:
            task.cancelled.set()
        self.finish()
        self.window.editor.document().setModified(False)
        self.assertTrue(self.window.close())
        self.window.deleteLater(); self.application.processEvents()

    def download(self):
        self.panel.choice.setCurrentIndex(1)
        def response(entry, layer, hosts, offset):
            self.assertEqual(offset, 0)
            return Response(self.content[layer["digest"]])
        with patch("ceta_desktop.model_installation._open_blob", side_effect=response):
            self.panel.download_button.click()
            self.finish()

    def owned(self):
        self.window.owned_runtime_recipe = {"backend":"ollama", "managed":{"version":"0.34.3"},
                                           "endpoint":self.window.endpoint.text()}
        self.window.owned_runtime_run = "fixture-run"
        self.window.model_process.containment = {"job_name":"fixture-job"}
        self.window.model_process.managed_assets = Mock(closed=False, job_name="fixture-job")
        self.window.model_process.managed_assets.protect_model.side_effect = (
            lambda models, identifier, **kwargs: models.verify(identifier, **kwargs))

    def test_no_implicit_acquisition_or_persisted_hardware_readiness(self):
        self.assertIsNone(self.panel.profile)
        self.assertIsNone(self.panel.task)
        self.assertFalse(self.panel.download_button.isEnabled())
        self.assertIsNone(self.panel.choice.currentData())
        self.assertIn("No model has been tested", self.panel.status.text())

    def test_download_records_governed_action_without_starting_or_selecting(self):
        self.window.model_combo.setCurrentText("keep-choice")
        with patch.object(self.window.model_process, "start") as start, patch.object(self.window,"probe_model") as probe:
            self.download()
            start.assert_not_called(); probe.assert_not_called()
        self.assertIn("4 files verified", self.panel.status.text())
        self.assertEqual(self.window.model_combo.currentText(), "keep-choice")
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertTrue(any(row["payload"]["kind"]=="model.download" for row in events))

    def test_use_requires_owned_managed_runtime_and_does_not_start_external_service(self):
        self.panel.choice.setCurrentIndex(1)
        with patch.object(self.window.model_process,"start") as start, patch("ceta_desktop.app.LocalModelClient") as client:
            self.panel.use_button.click()
            start.assert_not_called(); client.assert_not_called()
        self.assertIn("Start the CETA-managed runtime", self.panel.status.text())

    def test_use_verifies_digest_before_model_selection_and_explicit_probe(self):
        self.download(); self.owned()
        with patch.object(self.window.model_process,"state",return_value=QProcess.Running), \
                patch("ceta_desktop.app.LocalModelClient") as client, patch.object(self.window,"probe_model") as probe:
            client.return_value.request_profile.return_value={"backend":"ollama","locality":"local","digest":self.entry["sha256"]}
            self.panel.use_button.click(); self.finish()
            probe.assert_called_once_with()
            self.assertEqual(client.return_value.expected_job,"fixture-job")
        self.assertEqual(self.window.model_combo.currentText(),model_name(self.entry))
        self.assertEqual(self.window.store.setting("managed_model_id"),"fixture")
        self.assertEqual(self.panel.profile.available_ram_bytes,12*GIB)

    def test_wrong_runtime_digest_retains_manual_choice_without_probe(self):
        self.download(); self.owned()
        self.window.model_combo.setCurrentText("keep-choice")
        with patch.object(self.window.model_process,"state",return_value=QProcess.Running), \
                patch("ceta_desktop.app.LocalModelClient") as client, patch.object(self.window,"probe_model") as probe:
            client.return_value.request_profile.return_value={"backend":"ollama","locality":"local","digest":"wrong"}
            self.panel.use_button.click(); self.finish()
            probe.assert_not_called()
        self.assertEqual(self.window.model_combo.currentText(),"keep-choice")
        self.assertIn("does not match",self.panel.status.text())

    def test_probe_handoff_remains_cancellable_and_updates_setup_result(self):
        self.download(); self.owned()
        entered, finish = threading.Event(), threading.Event()
        def probe(instance, model, *, cancelled):
            entered.set()
            if not finish.wait(3):
                raise TimeoutError("fixture not released")
            self.assertFalse(cancelled.is_set())
            return {"model":model,"response":"fixture","elapsed_seconds":.1,"runtime":None}
        with patch.object(self.window.model_process,"state",return_value=QProcess.Running), \
                patch("ceta_desktop.app.LocalModelClient") as client, patch("ceta_desktop.app.TaskRuntime.probe_model",side_effect=probe):
            client.return_value.request_profile.return_value={"backend":"ollama","locality":"local","digest":self.entry["sha256"]}
            self.panel.use_button.click()
            deadline=time.monotonic()+3
            while not entered.is_set() and time.monotonic()<deadline:
                self.application.processEvents(); time.sleep(.005)
            self.assertTrue(entered.is_set())
            self.assertIsNotNone(self.panel.task)
            self.assertTrue(self.panel.pause_button.isEnabled())
            finish.set(); self.finish()
        self.assertIn("Response completed",self.panel.status.text())
        self.assertIsNone(self.panel.task)
        self.assertFalse(self.panel.pause_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
