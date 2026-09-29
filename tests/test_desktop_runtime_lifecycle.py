from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from ceta_desktop.models import ModelDeadlineError, ModelError
from ceta_desktop.runtime_coordination import RuntimeLease
from test_desktop_model_readiness import model_service, LOCAL_MODEL


class OwnedServiceHealthTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("ceta_desktop.models.connection_owner", return_value={"pid": 1}))
        self.inspect = self.enterContext(patch("ceta_desktop.windows_job.inspect_job",
                                             return_value={"owner_contained": True, "job_name": "fixture-job"}))

    def test_ollama_loading_then_healthy_does_not_send_inference(self):
        calls = []
        def version(_):
            calls.append(True)
            return (503, {}) if len(calls) == 1 else {"version": "fixture-version"}
        with model_service({("GET", "/api/version"): version}) as (client, requests):
            result = client.wait_owned_service("ollama", "fixture-job", timeout=2)
            self.assertEqual(result["status"], "service_healthy")
            self.assertEqual(result["inference"], "not_tested")
            self.assertEqual(result["models"], ["local:4b"])
            self.assertEqual(result["health"]["version"], "fixture-version")
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(path in {"/api/version", "/api/tags", "/api/show"} for _, path, _ in requests))
            self.assertIsNone(client.expected_job)

    def test_llama_health_and_catalog_are_both_required(self):
        with model_service({("GET", "/health"): {"status": "ok"},
                            ("GET", "/v1/models"): {"data": [{"id": "fixture-gguf"}]}}) as (client, requests):
            result = client.wait_owned_service("llama.cpp", "fixture-job", timeout=1)
            self.assertEqual(result["models"], ["fixture-gguf"])
            self.assertEqual([path for _, path, _ in requests], ["/health", "/v1/models"])
        with model_service({("GET", "/health"): {"status": "ok"},
                            ("GET", "/v1/models"): {"data": []}}) as (client, _):
            with self.assertRaisesRegex(ModelError, "loaded model"):
                client.wait_owned_service("llama.cpp", "fixture-job", timeout=1)

    def test_unrelated_listener_receives_no_health_request(self):
        self.inspect.return_value = {"owner_contained": False}
        with model_service({("GET", "/api/version"): {"version": "unrelated"}}) as (client, requests):
            with self.assertRaisesRegex(ModelError, "different runtime"):
                client.wait_owned_service("ollama", "fixture-job", timeout=1)
            self.assertEqual(requests, [])

    def test_health_has_absolute_deadline_and_preserves_cancelled_event(self):
        def stalled(_):
            time.sleep(.3)
            return {"version": "too-late"}
        with model_service({("GET", "/api/version"): stalled}) as (client, _):
            started = time.monotonic()
            with self.assertRaises(ModelDeadlineError):
                client.wait_owned_service("ollama", "fixture-job", timeout=.04)
            self.assertLess(time.monotonic() - started, .8)
        with model_service() as (client, requests):
            client.cancelled.set()
            with self.assertRaisesRegex(ModelError, "stopped"):
                client.wait_owned_service("ollama", "fixture-job", timeout=1)
            self.assertTrue(client.cancelled.is_set())
            self.assertEqual(requests, [])

    def test_invalid_health_does_not_retry_or_claim_ready(self):
        with model_service({("GET", "/api/version"): {"version": 42}}) as (client, requests):
            with self.assertRaisesRegex(ModelError, "valid runtime version"):
                client.wait_owned_service("ollama", "fixture-job", timeout=1)
            self.assertEqual(len(requests), 1)


class ResidentSwitchTests(unittest.TestCase):
    def setUp(self):
        self.owner = {"pid": 1, "created_100ns": 123, "source": "fixture"}
        self.observer = self.enterContext(patch("ceta_desktop.models.connection_owner", return_value=self.owner))
        self.enterContext(patch("ceta_desktop.runtime_coordination.connection_owner", return_value=self.owner))
        self.resident = {**LOCAL_MODEL, "size_vram": 0, "context_length": 4096}

    def lease(self, client):
        return RuntimeLease(client.host, client.port, directory=client.coordination_directory, allow_uncertain=True)

    def test_unload_is_scoped_and_completion_requires_residency_observation(self):
        unloaded = []
        def unload(payload):
            unloaded.append(payload)
            return {"model": "local:4b", "done": True, "done_reason": "unload", "response": ""}
        with model_service({("GET", "/api/ps"): lambda _: {"models": [] if unloaded else [self.resident]},
                            ("POST", "/api/generate"): unload}) as (client, requests):
            snapshot = client.resident_snapshot()
            self.assertFalse(unloaded)
            result = client.unload_model(snapshot, "local:4b")
            self.assertEqual(result["status"], "unloaded")
            self.assertEqual(unloaded, [{"model": "local:4b", "prompt": "", "keep_alive": 0, "stream": False}])
            self.assertFalse(any("chat" in path for _, path, _ in requests))
            with self.lease(client) as lease:
                self.assertEqual(lease.record["state"], "idle")
                self.assertEqual(lease.record["operation"], "unload")

    def test_identity_or_owner_change_prevents_unload_transmission(self):
        for changed in ("digest", "owner", "stale"):
            with self.subTest(changed=changed), model_service({("GET", "/api/ps"): {"models": [self.resident]}}) as (client, requests):
                self.observer.return_value = self.owner
                snapshot = client.resident_snapshot()
                if changed == "digest":
                    snapshot["models"][0]["digest"] = "b" * 64
                elif changed == "owner":
                    self.observer.return_value = {**self.owner, "created_100ns": 456}
                else:
                    snapshot["observed_at"] -= 61
                with self.assertRaises(ModelError):
                    client.unload_model(snapshot, "local:4b")
                self.assertFalse(any(path == "/api/generate" for _, path, _ in requests))
                with self.lease(client) as lease:
                    self.assertEqual(lease.record["state"], "idle")

    def test_unconfirmed_or_interrupted_unload_stays_uncertain(self):
        for reply in ({"model": "local:4b", "done": True},
                      {"model": "wrong", "done": True, "done_reason": "unload"}):
            with self.subTest(reply=reply), model_service({("GET", "/api/ps"): {"models": [self.resident]},
                    ("POST", "/api/generate"): reply}) as (client, _):
                snapshot = client.resident_snapshot()
                with self.assertRaisesRegex(ModelError, "did not confirm"):
                    client.unload_model(snapshot, "local:4b")
                with self.lease(client) as lease:
                    self.assertEqual(lease.record["state"], "uncertain")
                with self.assertRaisesRegex(ModelError, "uncertain"):
                    client.unload_model(snapshot, "local:4b")

    def test_acknowledgment_without_residency_change_does_not_clear_dispatch(self):
        with model_service({("GET", "/api/ps"): {"models": [self.resident]},
                ("POST", "/api/generate"): {"model": "local:4b", "done": True, "done_reason": "unload"}}) as (client, _):
            snapshot = client.resident_snapshot()
            client.timeout_seconds = .06
            with self.assertRaises(ModelDeadlineError):
                client.unload_model(snapshot, "local:4b")
            with self.lease(client) as lease:
                self.assertEqual(lease.record["state"], "uncertain")

    def test_shared_lease_blocks_unload_during_another_ceta_request(self):
        with model_service({("GET", "/api/ps"): {"models": [self.resident]}}) as (client, requests):
            snapshot = client.resident_snapshot()
            with self.lease(client):
                with self.assertRaisesRegex(ModelError, "Another CETA request"):
                    client.unload_model(snapshot, "local:4b")
            self.assertFalse(any(path == "/api/generate" for _, path, _ in requests))


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    from ceta_desktop.app import MainWindow
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT and os.name == "nt", "Windows native desktop extra required")
class NativeRuntimeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.window = MainWindow(self.root)
        self.window.owned_runtime_recipe = {"backend": "ollama", "endpoint": self.window.endpoint.text(), "program": "fixture"}
        self.window.owned_runtime_run = "run-one"
        self.window.model_process.containment = {"job_name": "fixture-job"}

    def tearDown(self):
        self.window.model_restart_pending = None
        self.window.model_health_task = None
        self.window.editor.document().setModified(False)
        self.assertTrue(self.window.close())
        self.window.deleteLater()
        self.application.processEvents()

    def health_callbacks(self):
        captured = {}
        def background(function, result, failed):
            captured.update(function=function, result=result, failed=failed)
            task = MagicMock()
            task.cancelled = threading.Event()
            return task
        with patch.object(self.window, "_background", side_effect=background), \
                patch.object(self.window.model_process, "state", return_value=QProcess.Running):
            self.window._begin_owned_health("run-one")
        return captured

    def test_health_callback_is_bound_to_the_same_run_and_endpoint(self):
        callbacks = self.health_callbacks()
        self.window.model_combo.setCurrentText("keep-user-choice")
        self.window.owned_runtime_run = "run-two"
        with patch.object(self.window.model_process, "state", return_value=QProcess.Running):
            callbacks["result"]({"models": ["old-result"]})
        self.assertEqual(self.window.model_combo.currentText(), "keep-user-choice")
        self.assertNotIn("service healthy", self.window.model_status.text())

    def test_healthy_catalog_keeps_existing_manual_selection(self):
        callbacks = self.health_callbacks()
        self.window.model_combo.setCurrentText("keep-user-choice")
        with patch.object(self.window.model_process, "state", return_value=QProcess.Running):
            callbacks["result"]({"models": ["another-model"]})
        self.assertEqual(self.window.model_combo.currentText(), "keep-user-choice")
        self.assertIn("service healthy", self.window.model_status.text())
        self.assertIn("unverified", self.window.model_status.text())

    def test_restart_waits_for_finished_and_does_not_restart_external_service(self):
        with patch.object(self.window.model_process, "state", return_value=QProcess.Running), \
                patch.object(self.window, "stop_local_model", return_value=True) as stop, \
                patch.object(self.window, "start_ollama") as start:
            self.window.restart_local_model()
            stop.assert_called_once_with(keep_restart=True)
            self.window._complete_owned_restart()
            start.assert_not_called()
        with patch.object(self.window, "start_ollama") as start:
            self.window._complete_owned_restart()
            start.assert_called_once_with()
        self.window.owned_runtime_recipe = None
        with patch.object(self.window, "stop_local_model") as stop:
            self.window.restart_local_model()
            stop.assert_not_called()

    def test_stop_failure_or_endpoint_change_cancels_queued_restart(self):
        with patch.object(self.window.model_process, "state", return_value=QProcess.Running), \
                patch.object(self.window, "stop_local_model", return_value=False):
            self.window.restart_local_model()
            self.assertIsNone(self.window.model_restart_pending)
        with patch.object(self.window.model_process, "state", return_value=QProcess.Running), \
                patch.object(self.window, "stop_local_model", return_value=True):
            self.window.restart_local_model()
        self.window.endpoint.setText("http://127.0.0.1:12345/v1")
        with patch.object(self.window, "start_ollama") as start:
            self.window._complete_owned_restart()
            start.assert_not_called()

    def test_restart_reruns_gguf_preparation_for_the_same_pack(self):
        recipe = {**self.window.owned_runtime_recipe, "backend": "llama.cpp", "pack": "digest", "program": "runtime.exe"}
        self.window.model_restart_pending = {"recipe": recipe, "run": "run-one"}
        with patch.object(self.window, "start_model") as start:
            self.window._complete_owned_restart()
            start.assert_called_once_with(executable="runtime.exe", expected_pack="digest")

    def test_unload_uses_governed_action_and_preserves_model_selection(self):
        snapshot = {"schema": "fixture", "models": [{"name": "resident:4b"}]}
        self.window.resident_snapshot = snapshot
        self.window.resident_endpoint = self.window.endpoint.text()
        self.window.resident_model_combo.addItem("Resident fixture", "resident:4b")
        self.window.model_combo.setCurrentText("next-choice")
        with patch("ceta_desktop.app.LocalModelClient") as client, \
                patch.object(self.window, "_background") as background:
            client.return_value.cancelled = threading.Event()
            self.window.unload_selected_model()
        function, observed, _failed = background.call_args.args
        client.return_value.unload_model.return_value = {"model": "resident:4b", "status": "unloaded"}
        function(None)
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertEqual(events[-1]["payload"]["kind"], "model.unload")
        client.return_value.unload_model.assert_called_once_with(snapshot, "resident:4b")
        with patch.object(self.window, "refresh_hardware") as refresh:
            observed({"model": "resident:4b"})
            refresh.assert_called_once_with()
        self.assertEqual(self.window.model_combo.currentText(), "next-choice")
        self.assertIsNone(self.window.resident_snapshot)


if __name__ == "__main__":
    unittest.main()
