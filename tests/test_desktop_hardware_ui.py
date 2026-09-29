from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import ANY, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QListWidgetItem, QScrollArea
    from ceta_desktop.app import MainWindow
    from ceta_desktop.hardware import HardwareProfile, recommended_model


@unittest.skipUnless(HAS_QT, "Desktop extra is required for native hardware UI tests")
class DesktopHardwareUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        if os.name == "nt" and not QFontDatabase.families():
            font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font))
            if font_id < 0:
                raise RuntimeError("The native Windows UI font is required for layout validation")
            cls.addClassCleanup(QFontDatabase.removeApplicationFont, font_id)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.profile = HardwareProfile(16 * 1024**3, 12 * 1024**3, 8)
        self.inspect = self.enterContext(patch("ceta_desktop.app.inspect_hardware", return_value=self.profile))
        self.window = MainWindow(self.root / "data")

    def tearDown(self):
        self._finish_tasks()
        self.window.editor.document().setModified(False)
        self.assertTrue(self.window.close())
        self.window.deleteLater()
        self.application.processEvents()

    def _finish_tasks(self):
        for _ in range(1000):
            self.application.processEvents()
            time.sleep(0.01)
            if not self.window.tasks:
                break
        self.assertEqual(self.window.tasks, [])

    def test_models_visit_inspects_hardware_without_download_or_changing_manual_name(self):
        self.window.pack_name.setText("custom:my-choice")
        self.window.model_combo.setCurrentText("existing-choice")
        self.inspect.assert_not_called()
        with patch("ceta_desktop.app.LocalModelClient") as client, patch.object(self.window.model_process, "start") as start:
            self.window.navigation.setCurrentRow(3)
            self._finish_tasks()
            self.inspect.assert_called_once_with(cancelled=ANY)
            self.assertIsInstance(self.inspect.call_args.kwargs["cancelled"], threading.Event)
            client.assert_not_called()
            start.assert_not_called()
            self.assertEqual(self.window.pack_name.text(), "custom:my-choice")
            self.assertEqual(self.window.model_combo.currentText(), "existing-choice")
            selected = self.window.hardware_model_combo.currentData()
            self.assertEqual(selected.model.tag, recommended_model(self.profile).model.tag)
            self.window.use_suggested_model()
            self.assertEqual(self.window.pack_name.text(), selected.model.tag)
            client.assert_not_called()

    def test_models_controls_remain_reachable_at_minimum_window_size(self):
        # Qt's offscreen Windows platform has no system-font discovery. Load the
        # installed UI font for the same measurements used by the native app.
        if os.name == "nt" and not QFontDatabase.families():
            font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font))
            self.assertGreaterEqual(font_id, 0, "The native Windows UI font is required for layout validation")
            self.addCleanup(QFontDatabase.removeApplicationFont, font_id)
        self.window._hardware_loaded(self.profile)
        self.window.resize(1100, 720)
        self.window.navigation.setCurrentRow(3)
        self.window.show()
        QTest.qWait(40)
        scroll = self.window.pages.widget(3).findChild(QScrollArea)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        for size in ((1100, 720), (1440, 1080)):
            self.window.resize(*size)
            QTest.qWait(40)
            for label in (self.window.hardware_summary, self.window.hardware_model_detail):
                with self.subTest(size=size, text=label.text()):
                    self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()),
                                            "Hardware limitations must remain fully readable")
        for control in (self.window.use_suggested_button, self.window.probe_model_button,
                        self.window.pull_button, self.window.import_button, self.window.model_status):
            with self.subTest(control=control.objectName()):
                scroll.ensureWidgetVisible(control)
                self.application.processEvents()
                center = control.mapTo(scroll.viewport(), QPoint(control.width() // 2, control.height() // 2))
                self.assertTrue(scroll.viewport().rect().contains(center))

    def test_download_rechecks_memory_and_blocks_insufficient_known_model(self):
        self.window._hardware_loaded(self.profile)
        self.inspect.return_value = HardwareProfile(16 * 1024**3, 1 * 1024**3, 8)
        self.window.pack_name.setText("qwen3:14b-q4_K_M")
        with patch("ceta_desktop.app.LocalModelClient") as client:
            client.return_value.cancelled = threading.Event()
            self.window.download_model_pack()
            self._finish_tasks()
            self.inspect.assert_called_once_with(cancelled=ANY)
            self.assertIsInstance(self.inspect.call_args.kwargs["cancelled"], threading.Event)
            client.return_value.pull_ollama_model.assert_not_called()
        self.assertIn("does not fit", self.window.model_status.text())
        self.assertIsNone(self.window.pack_download_client)
        self.assertTrue(self.window.pull_button.isEnabled())

    def test_failed_hardware_refresh_clears_stale_suggestions(self):
        self.window._hardware_loaded(self.profile)
        self.assertTrue(self.window.use_suggested_button.isEnabled())
        self.window.pack_name.setText("manual:keep")
        self.inspect.side_effect = OSError("inventory unavailable")

        self.window.refresh_hardware()
        self.assertFalse(self.window.use_suggested_button.isEnabled())
        self._finish_tasks()

        self.assertIsNone(self.window.hardware_profile)
        self.assertEqual(self.window.hardware_model_combo.count(), 0)
        self.assertFalse(self.window.use_suggested_button.isEnabled())
        self.assertEqual(self.window.pack_name.text(), "manual:keep")
        self.assertIn("unavailable", self.window.hardware_summary.text())

    def test_reopening_saved_data_on_different_hardware_reassesses_without_old_readiness(self):
        first_computer = HardwareProfile(64 * 1024**3, 48 * 1024**3, 16)
        second_computer = HardwareProfile(8 * 1024**3, 3 * 1024**3, 4)
        self.inspect.return_value = first_computer
        self.window.navigation.setCurrentRow(3)
        self._finish_tasks()
        first_choice = self.window.hardware_model_combo.currentData().model.tag
        self.window.model_combo.setCurrentText(first_choice)
        self.window.store.set_setting("model", first_choice)
        conversation = self.window.store.new_conversation("Retained conversation")
        self.window.store.add_message(conversation, "user", "Keep this saved work")
        with patch("ceta_desktop.app.LocalModelClient") as client:
            client.return_value.cancelled = threading.Event()
            client.return_value.request_profile.return_value = {"backend": "ollama", "model": first_choice}
            client.return_value.probe_local_model.return_value = {
                "status": "verified", "model": first_choice, "response": "Fixture response",
                "elapsed_seconds": 0.5, "runtime": None,
            }
            self.window.probe_model()
            self._finish_tasks()
        self.assertIn("Response completed", self.window.model_status.text())
        self.assertTrue(self.window.close())
        self.window.deleteLater()
        self.application.processEvents()

        self.inspect.return_value = second_computer
        self.window = MainWindow(self.root / "data")
        self.assertIsNone(self.window.hardware_profile)
        self.assertEqual(self.window.hardware_model_combo.count(), 0)
        self.assertFalse(self.window.use_suggested_button.isEnabled())
        self.assertFalse(self.window.model_probe_running)
        self.assertNotIn("Response completed", self.window.model_status.text())
        self.assertEqual(self.window.model_log.toPlainText(), "")
        self.assertEqual(self.window.model_combo.currentText(), first_choice)
        self.assertEqual(self.window.store.messages(conversation)[0]["content"], "Keep this saved work")

        with patch("ceta_desktop.app.LocalModelClient") as client:
            self.window.navigation.setCurrentRow(3)
            self._finish_tasks()
            client.assert_not_called()
        self.assertEqual(self.inspect.call_count, 2)
        self.assertEqual(self.window.hardware_profile, second_computer)
        second_choice = self.window.hardware_model_combo.currentData().model.tag
        self.assertEqual(second_choice, recommended_model(second_computer).model.tag)
        self.assertNotEqual(second_choice, first_choice)
        self.assertEqual(self.window.model_combo.currentText(), first_choice)
        self.assertTrue(self.window.use_suggested_button.isEnabled())

    def test_sending_during_local_probe_retains_draft_without_starting_second_request(self):
        self.window.model_combo.setCurrentText("fixture:local")
        self.window.prompt.setPlainText("Keep this question")
        with patch.object(self.window, "model_probe_running", True), patch("ceta_desktop.app.LocalModelClient") as client:
            self.window.send_message()
            client.assert_not_called()
        self.assertEqual(self.window.prompt.toPlainText(), "Keep this question")
        self.assertEqual(self.window.store.conversations(), [])
        self.assertIn("test to finish", self.window.chat_status.text())

    def test_discovery_from_previous_endpoint_cannot_replace_current_model_or_locality(self):
        original_endpoint = self.window.endpoint.text().strip()
        self.window.store.set_setting("endpoint", original_endpoint)
        self.window.model_combo.setCurrentText("current-manual-choice")
        pending = []
        with patch("ceta_desktop.app.LocalModelClient") as client, patch.object(
            self.window, "_background", side_effect=lambda operation, loaded, failed: pending.append((operation, loaded, failed)),
        ):
            client.return_value.available_models.return_value = ["old-endpoint-model"]
            client.return_value.backend = "ollama"
            client.return_value.skipped_models = []
            self.window.refresh_models()
            self.window.endpoint.setText("http://127.0.0.1:8081/v1")
            operation, loaded, failed = pending.pop()
            loaded(operation(None))

        self.assertEqual(self.window.model_combo.currentText(), "current-manual-choice")
        self.assertEqual(self.window.model_combo.count(), 0)
        self.assertEqual(self.window.store.setting("endpoint"), original_endpoint)
        self.assertNotIn("runtime-reported local", self.window.model_status.text())
        self.assertIn("current endpoint", self.window.model_status.text())
        failed("Old endpoint connection failure")
        self.assertNotIn("Old endpoint connection failure", self.window.model_status.text())

    def test_custom_model_keeps_explicit_download_without_inventing_fit(self):
        self.inspect.return_value = HardwareProfile(None, None, 8)
        self.window.pack_name.setText("custom:explicit-choice")
        with patch("ceta_desktop.app.LocalModelClient") as client, patch.object(self.window, "refresh_models"):
            client.return_value.cancelled = threading.Event()
            client.return_value.pull_ollama_model.return_value = iter(["success"])
            self.window.download_model_pack()
            self._finish_tasks()
            client.return_value.pull_ollama_model.assert_called_once_with("custom:explicit-choice")
        self.assertIn("installed", self.window.model_status.text())
        self.assertIn("could not be measured", self.window.hardware_model_detail.text())

    def test_gguf_start_uses_fresh_memory_assessment_and_bounded_cpu_context(self):
        from test_desktop_backend_admission import runtime_fixture, write_gguf
        inspection = runtime_fixture(self.root / "llama-server.exe")
        write_gguf(self.root / "model.gguf")
        record = {"name": "fixture", "size": 100 * 1024**2, "sha256": "a" * 64, "path": str(self.root / "model.gguf")}
        item = QListWidgetItem("fixture")
        item.setData(Qt.UserRole, record)
        self.window.pack_list.addItem(item)
        self.window.pack_list.setCurrentItem(item)
        with patch("ceta_desktop.app.QFileDialog.getOpenFileName", return_value=(inspection["path"], "")), \
                patch("ceta_desktop.app.inspect_llama_runtime", return_value=inspection), \
                patch.object(self.window.packs, "verify_installed", return_value=record) as verify, \
                patch.object(self.window.model_process, "start") as start:
            self.window.start_model()
            self._finish_tasks()
            self.inspect.assert_called_once_with(cancelled=ANY)
            self.assertIsInstance(self.inspect.call_args.kwargs["cancelled"], threading.Event)
            verify.assert_called_once()
            start.assert_called_once_with()
        arguments = self.window.model_process.arguments()
        self.assertEqual(arguments[arguments.index("--ctx-size") + 1], "4096")
        self.assertEqual(arguments[arguments.index("--n-gpu-layers") + 1], "0")
        self.assertEqual(arguments[arguments.index("--parallel") + 1], "1")
        self.assertEqual(arguments[arguments.index("--device") + 1], "none")
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertEqual([event["payload"]["kind"] for event in events], ["model.inspect", "model.start"])
        self.assertEqual(events[-1]["payload"]["consequence"]["arguments"]["launch_plan"]["runtime_sha256"], inspection["sha256"])

    def test_gguf_unknown_memory_and_cpu_backend_gpu_mismatch_never_launch(self):
        from test_desktop_backend_admission import runtime_fixture, write_gguf
        from ceta_desktop.hardware import GIB, GPUInfo
        inspection = runtime_fixture(self.root / "llama-server.exe")
        write_gguf(self.root / "model.gguf")
        record = {"name": "fixture", "size": 5 * GIB, "sha256": "a" * 64, "path": str(self.root / "model.gguf")}
        item = QListWidgetItem("fixture")
        item.setData(Qt.UserRole, record)
        self.window.pack_list.addItem(item)
        self.window.pack_list.setCurrentItem(item)
        for profile in (HardwareProfile(None, None, 8), HardwareProfile(16 * GIB, 3 * GIB, 8,
                        (GPUInfo("Unusable GPU", 24 * GIB, 20 * GIB, "nvidia-smi"),))):
            with self.subTest(profile=profile), \
                    patch("ceta_desktop.app.QFileDialog.getOpenFileName", return_value=(inspection["path"], "")), \
                    patch("ceta_desktop.app.inspect_llama_runtime", return_value=inspection), \
                    patch.object(self.window.packs, "verify_installed", return_value=record), \
                    patch.object(self.window.model_process, "start") as start:
                self.inspect.return_value = profile
                self.window.start_model()
                self._finish_tasks()
                start.assert_not_called()
                self.assertIsNone(self.window.model_launch_plan)
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertNotIn("model.start", [event["payload"]["kind"] for event in events])

    def test_native_gpu_plan_and_changed_endpoint_before_launch(self):
        from test_desktop_backend_admission import runtime_fixture, write_gguf
        from ceta_desktop.hardware import GIB, GPUInfo
        inspection = runtime_fixture(self.root / "llama-server.exe", [{"id": "CUDA0", "name": "Fixture GPU",
                                    "total_bytes": 24 * GIB, "free_bytes": 20 * GIB, "source": "synthetic backend"}])
        write_gguf(self.root / "model.gguf")
        record = {"name": "fixture", "size": 5 * GIB, "sha256": "a" * 64, "path": str(self.root / "model.gguf")}
        item = QListWidgetItem("fixture")
        item.setData(Qt.UserRole, record)
        self.window.pack_list.addItem(item)
        self.window.pack_list.setCurrentItem(item)
        self.inspect.return_value = HardwareProfile(16 * GIB, 4 * GIB, 8,
            (GPUInfo("Fixture GPU", 24 * GIB, 20 * GIB, "nvidia-smi"),))
        with patch("ceta_desktop.app.QFileDialog.getOpenFileName", return_value=(inspection["path"], "")), \
                patch("ceta_desktop.app.inspect_llama_runtime", return_value=inspection), \
                patch.object(self.window.packs, "verify_installed", return_value=record), \
                patch.object(self.window.model_process, "start") as start:
            self.window.start_model()
            self._finish_tasks()
            start.assert_called_once()
            self.assertEqual(self.window.model_launch_plan["device"]["id"], "CUDA0")
            self.assertIn("CUDA0", self.window.model_process.arguments())
            start.reset_mock()
            self.window.start_model()
            self.window.endpoint.setText("http://127.0.0.1:9999/v1")
            self._finish_tasks()
            start.assert_not_called()
            self.assertIn("changed during preparation", self.window.model_status.text())

    def test_runtime_recheck_records_observation_without_clearing_worker_uncertainty(self):
        with patch("ceta_desktop.app.LocalModelClient") as client:
            client.return_value.reconcile_runtime.return_value = {
                "state": "uncertain", "reason": "Service ended; separate model worker termination is unverified."}
            self.window.recheck_runtime()
            self._finish_tasks()
        self.assertIn("worker termination is unverified", self.window.model_status.text())
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertEqual(events[-1]["payload"]["kind"], "model.reconcile")

    def test_runtime_recheck_cannot_replace_status_for_a_changed_endpoint(self):
        entered, release = threading.Event(), threading.Event()
        def delayed():
            entered.set()
            release.wait(3)
            return {"state": "idle"}
        with patch("ceta_desktop.app.LocalModelClient") as client:
            client.return_value.reconcile_runtime.side_effect = delayed
            self.window.recheck_runtime()
            self.assertTrue(entered.wait(2))
            self.window.endpoint.setText("http://127.0.0.1:9999/v1")
            release.set()
            self._finish_tasks()
        self.assertIn("unverified", self.window.model_status.text())
        self.assertNotIn("coordination is clear", self.window.model_status.text())

    def test_local_probe_reports_actual_result_separately_from_estimates(self):
        self.window.model_combo.setCurrentText("fixture:local")
        with patch("ceta_desktop.app.LocalModelClient") as client:
            client.return_value.cancelled = threading.Event()
            client.return_value.request_profile.return_value = {"backend": "ollama", "model": "fixture:local"}
            client.return_value.probe_local_model.return_value = {
                "status": "verified", "model": "fixture:local", "response": "Fixture response",
                "elapsed_seconds": 1.25, "runtime": {"size_vram": 1024**3},
            }
            self.window.probe_model()
            self._finish_tasks()
            client.return_value.probe_local_model.assert_called_once()
            args, limits = client.return_value.probe_local_model.call_args
            self.assertEqual(args, ("fixture:local",))
            self.assertEqual(limits["max_tokens"], 32)
            self.assertEqual(limits["context_length"], 4096)
            self.assertEqual(limits["expected_profile"], {"backend": "ollama", "model": "fixture:local"})
            self.assertIn("CETA_READY", limits["messages"][-1]["content"])
            self.assertTrue(callable(limits["before_dispatch"]))
        self.assertIn("Response completed for fixture:local", self.window.model_status.text())
        self.assertIn("runtime reports local inference", self.window.model_status.text())
        self.assertIn("runtime-reported VRAM 1.00 GiB", self.window.model_status.text())
        self.assertIn("Fixture response", self.window.model_log.toPlainText())
        self.assertFalse(self.window.model_probe_running)
        self.window.endpoint.setText("http://127.0.0.1:8081/v1")
        self.assertIn("unverified", self.window.model_status.text())
        self.assertNotIn("Response completed", self.window.model_status.text())


if __name__ == "__main__":
    unittest.main()
