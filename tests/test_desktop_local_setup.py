from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ceta_desktop.hardware import GIB, HardwareProfile
from ceta_desktop.model_installation import ManagedModels, bundled_models, model_name
from ceta_desktop.runtime_installation import RuntimeInstallation
from test_desktop_model_installation import model_fixture
from test_desktop_runtime_installation import Response, fixture_archive

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QApplication
from ceta_desktop.app import MainWindow
from ceta_desktop.pages.local_setup import setup_candidates


class LocalSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data = self.root / "data"
        self.catalog, self.content = model_fixture()
        self.entry = self.catalog["entries"][0]
        self.archive, self.spec = fixture_archive(self.root)
        self.hardware = self.enterContext(patch("ceta_desktop.app.inspect_hardware", return_value=HardwareProfile(16*GIB,12*GIB,4)))
        self.enterContext(patch("ceta_desktop.pages.model_setup.bundled_models", return_value=self.catalog))
        self.enterContext(patch("ceta_desktop.pages.runtime_setup.bundled_runtime", return_value=self.spec))
        self.runtime = RuntimeInstallation(self.data, self.spec)
        self.models = ManagedModels(self.data, self.catalog)
        self.enterContext(patch("ceta_desktop.pages.local_setup.RuntimeInstallation", return_value=self.runtime))
        self.enterContext(patch("ceta_desktop.pages.local_setup.ManagedModels", return_value=self.models))
        self.enterContext(patch("ceta_desktop.app.ManagedModels", return_value=self.models))
        self.enterContext(patch("ceta_desktop.pages.local_setup.require_supported_platform"))
        self.enterContext(patch("ceta_desktop.runtime_installation.require_supported_platform"))
        self.window = MainWindow(self.data)
        self.panel = self.window.guided_setup
        self.running = False

    def spin(self, condition, seconds=6):
        deadline = time.monotonic()+seconds
        while not condition() and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.005)
        self.app.processEvents()
        self.assertTrue(condition(), self.panel.status.text())

    def finish(self):
        # Repeated full governed journeys revalidate the growing audit history;
        # observed completion is seven seconds on this test volume.
        self.spin(lambda: not self.window.tasks and not self.panel.busy, seconds=15)

    def tearDown(self):
        if self.panel.busy:
            self.panel.pause()
        for task in self.window.tasks:
            task.cancelled.set()
        self.finish()
        self.window.editor.document().setModified(False)
        self.assertTrue(self.window.close())
        self.window.deleteLater(); self.app.processEvents()

    def inspect(self):
        self.panel.inspect(); self.finish()
        self.assertEqual(self.panel.choice.currentData(), self.entry["id"])

    def transports(self):
        runtime = self.enterContext(patch("ceta_desktop.runtime_installation._open_release", side_effect=lambda *a: Response(self.archive.read_bytes())))
        model = self.enterContext(patch("ceta_desktop.model_installation._open_blob", side_effect=lambda e,l,h,o: Response(self.content[l["digest"]][o:])))
        return runtime, model

    def launch(self, executable, *, managed, assets):
        assets.bind_job("fixture-job")
        self.window.model_process.setManagedAssets(assets)
        self.running = True
        self.window.owned_runtime_run = "guided-fixture-run"
        self.window.owned_runtime_recipe = {"backend":"ollama", "program":executable, "managed":managed,
                                            "endpoint":"http://127.0.0.1:11435/v1"}
        self.window.model_process.containment = {"job_name":"fixture-job"}
        self.window.endpoint.setText("http://127.0.0.1:11435/v1")
        QTimer.singleShot(0, lambda: self.window.runtime_health_changed.emit({"run":"guided-fixture-run", "result":{"health":{"version":self.spec["version"]}}}))
        return True

    def fake_service(self, probe=None):
        self.enterContext(patch.object(self.window.model_process,"state",side_effect=lambda: QProcess.Running if self.running else QProcess.NotRunning))
        launch = self.enterContext(patch.object(self.window,"_launch_ollama",side_effect=self.launch))
        self.enterContext(patch.object(self.window,"_begin_owned_health",side_effect=lambda run: QTimer.singleShot(0,lambda: self.window.runtime_health_changed.emit({"run":run,"result":{}}))))
        client = self.enterContext(patch("ceta_desktop.app.LocalModelClient"))
        client.return_value.request_profile.return_value = {"backend":"ollama","locality":"local","digest":self.entry["sha256"]}
        response = self.enterContext(patch("ceta_desktop.app.TaskRuntime.probe_model",side_effect=probe or (lambda c,m,**k:{"model":m,"response":"fixture","elapsed_seconds":.2})))
        self.enterContext(patch.object(self.window,"stop_local_model",side_effect=self.stop))
        return launch, response

    def stop(self):
        self.running = False
        self.window.model_process.releaseManagedAssets()
        return True

    def test_fresh_launch_and_skip_never_download_start_or_probe(self):
        with patch("ceta_desktop.runtime_installation._open_release") as net, patch.object(self.window,"_launch_ollama") as launch, patch.object(self.window,"probe_model") as probe:
            self.assertFalse(self.window.setup_entry.isHidden())
            self.assertIsNone(self.panel.profile)
            self.panel.skip()
            self.assertTrue(self.window.setup_entry.isHidden())
            self.assertEqual(self.window.navigation.currentRow(),0)
            self.assertEqual(self.window.store.setting("local_setup_entry_dismissed"),"yes")
            net.assert_not_called(); launch.assert_not_called(); probe.assert_not_called()

    def test_inspection_uses_live_hardware_and_keeps_only_choices_across_restart(self):
        self.inspect()
        self.assertIn("Saved under",self.panel.details.text())
        self.assertIn("4096",self.panel.details.text())
        self.window.store.set_setting("managed_model_id",self.entry["id"])
        self.window.store.set_setting("local_setup_entry_dismissed","yes")
        self.assertTrue(self.window.close()); self.window.deleteLater(); self.app.processEvents()
        self.hardware.return_value = HardwareProfile(4*GIB,GIB,2)
        self.window=MainWindow(self.data); self.panel=self.window.guided_setup
        self.assertIsNone(self.panel.profile)
        self.assertIsNone(self.panel.tested_selection)
        self.assertTrue(self.window.setup_entry.isHidden())
        self.inspect()
        self.assertFalse(self.panel.install_button.isEnabled())
        self.assertIn("insufficient",self.panel.details.text().lower())

    def test_three_candidate_limit_and_saved_choice_never_make_unknown_memory_fit(self):
        entries = bundled_models()["entries"]
        choices, preferred = setup_candidates(entries,HardwareProfile(64*GIB,48*GIB,16))
        self.assertLessEqual(len(choices),3)
        self.assertEqual(preferred,"qwen3-4b")
        choices, _ = setup_candidates(entries,HardwareProfile(None,None,1),"qwen3-17b")
        self.assertLessEqual(len(choices),3)
        self.assertIn("qwen3-17b",[e["id"] for e in choices])

    def test_install_and_test_uses_verified_assets_then_governed_probe(self):
        self.inspect(); network, blobs = self.transports(); launch, probe = self.fake_service()
        self.panel.install_button.click(); self.finish()
        self.assertEqual(self.panel.stage,"tested")
        self.assertIn("quality",self.panel.status.text())
        launch.assert_called_once(); probe.assert_called_once()
        self.assertTrue(network.called and blobs.called)
        self.assertEqual(self.window.model_combo.currentText(),model_name(self.entry))
        self.assertEqual(self.models.verify(self.entry["id"])["sha256"],self.entry["sha256"])
        self.assertIsNotNone(self.panel.tested_selection)
        operations = [e["payload"]["kind"] for e in self.window.task_runtime.journal.events("application",kind="operation.intent")]
        for kind in ("runtime.install","model.download","runtime.inspect","model.inspect"):
            self.assertIn(kind,operations)
        self.window.model_combo.setCurrentText("changed")
        self.assertIsNone(self.panel.tested_selection)
        self.assertIn("earlier response test",self.panel.status.text())

    def test_offline_import_then_recheck_uses_no_download_transport(self):
        source = ManagedModels(self.root/"source",self.catalog)
        with patch("ceta_desktop.model_installation._open_blob",side_effect=lambda e,l,h,o: Response(self.content[l["digest"]])):
            source.acquire(self.entry["id"])
        archive = self.root/"model.zip"
        source.export(self.entry["id"],archive)
        self.inspect(); self.fake_service()
        with patch("ceta_desktop.runtime_installation._open_release",side_effect=AssertionError("unexpected runtime download")), patch("ceta_desktop.model_installation._open_blob",side_effect=AssertionError("unexpected model download")):
            self.panel.begin("import",self.archive,archive); self.finish()
            self.assertEqual(self.panel.stage,"tested")
            self.panel.recheck_button.click(); self.finish()
            self.assertEqual(self.panel.stage,"tested")

    def test_interrupted_download_preserves_runtime_and_retry_rechecks_it(self):
        self.inspect(); self.transports(); launch, _ = self.fake_service()
        with patch.object(self.models,"acquire",side_effect=OSError("fixture connection interrupted")):
            self.panel.begin("download"); self.finish()
        self.assertEqual(self.panel.stage,"attention")
        launch.assert_not_called()
        self.assertTrue(self.runtime.destination.exists())
        self.panel.begin("download"); self.finish()
        self.assertEqual(self.panel.stage,"tested")

    def test_pause_during_acquisition_prevents_late_launch_and_preserves_files(self):
        self.inspect(); self.transports(); launch, _ = self.fake_service()
        entered, release = threading.Event(), threading.Event()
        original = self.models.acquire
        def delayed(*args,**kwargs):
            result=original(*args,**kwargs)
            entered.set(); release.wait(3)
            return result
        with patch.object(self.models,"acquire",side_effect=delayed):
            self.panel.begin("download")
            self.spin(entered.is_set)
            self.panel.pause(); release.set(); self.finish()
        launch.assert_not_called()
        self.assertEqual(self.panel.stage,"paused")
        self.assertEqual(self.models.verify(self.entry["id"])["sha256"],self.entry["sha256"])

    def test_pause_during_probe_stops_only_this_owned_runtime_and_never_marks_tested(self):
        self.inspect(); self.transports()
        entered = threading.Event()
        def probe(client,model,*,cancelled):
            entered.set()
            self.assertTrue(cancelled.wait(3))
            raise ValueError("cancelled fixture probe")
        self.fake_service(probe)
        self.panel.begin("download"); self.spin(entered.is_set)
        self.panel.pause(); self.finish()
        self.assertFalse(self.running)
        self.assertEqual(self.panel.stage,"paused")
        self.assertIsNone(self.panel.tested_selection)

    def test_stale_health_cannot_start_a_probe(self):
        self.inspect()
        with patch.object(self.window,"use_managed_model") as use:
            self.panel._health({"run":"old-run","result":{}})
            self.assertTrue(self.panel._busy("starting"))
            self.panel.owned_run="new-run"
            self.panel._health({"run":"old-run","result":{}})
            use.assert_not_called()
            self.panel.pause(); self.finish()

    def test_active_setup_preserves_chat_draft_without_dispatch(self):
        self.inspect()
        self.assertTrue(self.panel._busy("acquiring"))
        self.window.prompt.setPlainText("keep this draft")
        with patch.object(self.window,"_configured_model_client") as client:
            self.window.send_message()
            client.assert_not_called()
        self.assertEqual(self.window.prompt.toPlainText(),"keep this draft")
        self.assertIn("draft",self.window.chat_status.text())
        self.panel.pause(); self.finish()

    def test_existing_runtime_discovery_and_test_do_not_install_or_restart(self):
        with patch("ceta_desktop.pages.local_setup.LocalModelClient") as client, patch.object(self.window,"_launch_ollama") as launch, patch.object(self.runtime,"acquire") as acquire:
            client.return_value.available_models.return_value=["existing-local"]
            self.panel.discover(); self.finish()
            self.assertEqual(self.panel.choice.currentData(),"existing-local")
            self.assertIn("privacy settings",self.panel.details.text())
            self.fake_service()
            self.panel.test_button.click(); self.finish()
            self.assertEqual(self.panel.stage,"tested")
            launch.assert_not_called(); acquire.assert_not_called()

    def test_unknown_ram_never_acquires_and_failed_discovery_remains_usable(self):
        self.hardware.return_value=HardwareProfile(None,None,1)
        self.inspect()
        with patch.object(self.runtime,"acquire") as acquire:
            self.panel.begin("download"); acquire.assert_not_called()
        with patch("ceta_desktop.pages.local_setup.LocalModelClient",side_effect=ValueError("fixture unavailable")):
            self.panel.discover(); self.finish()
        self.assertIn("unavailable",self.panel.status.text())
        self.assertTrue(self.panel.skip_button.isEnabled())

    def test_failed_hardware_refresh_clears_stale_summary_and_choices(self):
        self.inspect()
        self.assertIn("RAM:", self.panel.summary.text())
        self.panel.set_hardware(None)
        self.assertNotIn("RAM:", self.panel.summary.text())
        self.assertIn("unavailable", self.panel.summary.text())
        self.assertEqual(self.panel.choice.count(), 0)
        self.assertFalse(self.panel.install_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
