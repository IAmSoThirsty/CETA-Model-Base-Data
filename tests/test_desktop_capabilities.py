from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ceta_desktop.capabilities import (
    SESSION, configuration, fixture_passed, format_report, hardware_identity,
    measure_configuration, response_metrics, summarize,
)
from ceta_desktop.hardware import GIB, GPUInfo, HardwareProfile
from runtime.tasks import TaskRuntime
from test_desktop_model_readiness import model_service

HARDWARE = HardwareProfile(16 * GIB, 12 * GIB, 8, (GPUInfo("fixture GPU", 4 * GIB, 3 * GIB, "fixture"),))
WORKER = {"asset_session": "assets", "job": "job", "runner": {"owner": {"pid": 123}}, "context_length": 4096}


class FixtureClient:
    def __init__(self):
        self.cancelled = threading.Event()
        self.managed_directory = Path("fixture")
        self.expected_job = "job"
        self.managed_assets = SimpleNamespace(session_id="assets", job_name="job",
            assert_runtime=lambda: {"version": "fixture", "archive_sha256": "b" * 64})
        self.requests = []
        self.last_generation_metrics = None

    def request_profile(self, _):
        return {"backend": "ollama", "locality": "local", "digest": "a" * 64, "template_sha256": "c" * 64}

    def resident_snapshot(self):
        return {"models": []}

    def cancel(self):
        self.cancelled.set()

    def stream(self, model, messages, **kwargs):
        kwargs["before_dispatch"]()
        self.requests.append(messages)
        prompt = messages[-1]["content"]
        if "Reply with exactly" in prompt:
            response = re.search(r"CETA_[0-9a-f]+", prompt)[0]
        elif "integer result" in prompt:
            response = '{"answer":7}'
        elif "attached sample.txt" in prompt:
            selected = json.loads(prompt.split("Selected source data (drafts are not saved files):\n", 1)[1])
            response = json.dumps({"ticket": re.search(r"ticket: ([0-9a-f]+)", selected[0]["text"])[1], "source": selected[0]["path"]})
        else:
            response = " ".join(str(n) for n in range(1, 61))
        yield response
        self.last_generation_metrics = {"eval_count": 60, "eval_duration": 2_000_000_000, "load_duration": 10_000_000}


class CapabilityTests(unittest.TestCase):
    def test_exact_and_json_checks_reject_extra_text_wrong_types_and_sources(self):
        self.assertTrue(fixture_passed("instruction_exact", " token\n", "token", "file"))
        self.assertFalse(fixture_passed("instruction_exact", "Here is token", "token", "file"))
        for text in ('{"answer":"7"}', '{"answer":7.0}', '{"answer":7,"extra":1}', '```json\n{"answer":7}\n```'):
            self.assertFalse(fixture_passed("instruction_json", text, "token", "file"))
        self.assertTrue(fixture_passed("selected_file", '{"ticket":"file","source":"sample.txt"}', "token", "file"))
        self.assertFalse(fixture_passed("selected_file", '{"ticket":"file","source":"other.txt"}', "token", "file"))
        self.assertFalse(fixture_passed("warm_1", "No authority or execution can be granted.", "token", "file"))
        self.assertTrue(fixture_passed("warm_1", "  ".join(str(n) for n in range(1, 61)), "token", "file"))

    def test_throughput_requires_real_positive_bounded_counts_and_duration(self):
        valid = {"generation_metrics": {"eval_count": 40, "eval_duration": 2_000_000_000}}
        self.assertEqual(response_metrics(valid, .1, 3)["tokens_per_second"], 20)
        for field, value in (("eval_count", None), ("eval_count", True), ("eval_count", 2000),
                             ("eval_duration", 0), ("eval_duration", -1), ("eval_duration", float("nan"))):
            changed = {**valid["generation_metrics"], field: value}
            self.assertIsNone(response_metrics({"generation_metrics": changed}, .1, 3)["tokens_per_second"])
        self.assertIsNone(response_metrics({"text": "a" * 1000}, .1, 3)["tokens_per_second"])

    def test_speed_requires_three_complete_sufficient_warm_samples(self):
        samples = [{"case": f"warm_{i}", "status": "completed", "matched": True,
                    "metrics": {"first_visible_seconds": 1, "tokens_per_second": 10, "output_tokens": 60}} for i in range(1, 4)]
        self.assertEqual(summarize({"samples": samples[:2]})["warm_speed"], "unmeasured")
        self.assertEqual(summarize({"samples": samples})["warm_speed"], "responsive")
        samples[1]["metrics"]["first_visible_seconds"] = 6
        self.assertEqual(summarize({"samples": samples})["warm_speed"], "slow")
        samples[1]["status"] = "cancelled"
        self.assertEqual(summarize({"samples": samples})["warm_speed"], "unmeasured")
        samples[1]["status"], samples[1]["matched"] = "completed", False
        self.assertEqual(summarize({"samples": samples})["warm_speed"], "unmeasured")

    def test_configuration_binds_session_build_model_runtime_settings_and_hardware(self):
        client = FixtureClient()
        original = configuration(client, "fixture", HARDWARE, {"sha": "first"})
        self.assertEqual(original["session"], SESSION)
        for changed in (replace(HARDWARE, logical_cpus=16), replace(HARDWARE, total_ram_bytes=32 * GIB),
                        replace(HARDWARE, gpus=())):
            self.assertNotEqual(original, configuration(client, "fixture", changed, {"sha": "first"}))
        self.assertEqual(hardware_identity(HARDWARE), hardware_identity(replace(HARDWARE, available_ram_bytes=10 * GIB)))
        self.assertNotEqual(original, configuration(client, "fixture", HARDWARE, {"sha": "new"}))
        self.assertNotEqual(original, configuration(client, "other-model", HARDWARE, {"sha": "first"}))
        client.managed_assets.session_id = "new-session"
        self.assertNotEqual(original, configuration(client, "fixture", HARDWARE, {"sha": "first"}))
        client.managed_assets = None
        with self.assertRaisesRegex(ValueError, "managed"):
            configuration(client, "fixture", HARDWARE, {})

    def test_native_stream_retains_reported_duration_fields(self):
        wire = b'{"message":{"content":"hello"},"done":true,"eval_count":8,"eval_duration":2000000000,"load_duration":10000000}\n'
        with model_service({("POST", "/api/chat"): wire}) as (client, _), \
                patch("ceta_desktop.models.inspect_hardware", return_value=HARDWARE):
            self.assertEqual("".join(client.stream("local:4b", max_tokens=128, messages=[{"role": "user", "content": "hi"}])), "hello")
            self.assertEqual(client.last_generation_metrics["eval_duration"], 2_000_000_000)
            self.assertEqual(client.last_generation_metrics["load_duration"], 10_000_000)

    def run_fixture(self, *, cancel_case=None, mutate_case=None, wrong_answers=False, resident_alias=None, change_file=False, expire_after_samples=False):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        runtime = TaskRuntime(self.directory / "data")
        self.addCleanup(runtime.close)
        client = FixtureClient()
        if expire_after_samples:
            clock, snapshots = [100.0], [0]
            self.enterContext(patch("ceta_desktop.capabilities.time.monotonic", side_effect=lambda: clock[0]))
            def snapshot():
                snapshots[0] += 1
                if snapshots[0] == 3:
                    clock[0] += 1261
                return {"models": []}
            client.resident_snapshot = snapshot
        if resident_alias:
            client.resident_snapshot = lambda: {"models": [{"name": resident_alias, "digest": "a" * 64}]}
        if wrong_answers:
            original = client.stream
            def incorrect(*args, **kwargs):
                for response in original(*args, **kwargs):
                    yield "unsupported answer" if ("exactly" in args[1][-1]["content"]) else response
            client.stream = incorrect
        def counter(messages):
            return {"verified": True, "input_tokens": 100, "method": "synthetic-test-counter", "binding": WORKER}
        def progress(message):
            if cancel_case and cancel_case in message:
                client.cancelled.set()
            if mutate_case and mutate_case in message:
                client.managed_assets.session_id = "changed"
            if change_file and "selected file" in message:
                path = next((runtime.directory / "capability-samples").glob("*/sample.txt"))
                path.write_text("changed synthetic source", encoding="utf-8")
        with patch("ceta_desktop.capabilities.inspect_hardware", return_value=HARDWARE), \
                patch("ceta_desktop.capabilities.build_identity", return_value={"sha": "fixture"}), \
                patch("ceta_desktop.capabilities.check_runner"), \
                patch("runtime.model_provider.LocalProvider.request_counter", return_value=counter):
            report = measure_configuration(runtime, client, "fixture", cancelled=client.cancelled, progress=progress)
        return runtime, client, report

    def test_governed_suite_uses_real_attachment_path_and_retains_journal_observation(self):
        runtime, client, report = self.run_fixture()
        self.assertEqual(report["status"], "completed", report.get("error"))
        self.assertEqual(len(client.requests), 7)
        self.assertEqual(report["summary"]["instruction_smoke"], "passed")
        self.assertEqual(report["summary"]["selected_file_smoke"], "passed")
        file_row = next(row for row in report["samples"] if row["case"] == "selected_file")
        prepared = next(row["payload"] for row in runtime.timeline(file_row["task_id"]) if row["kind"] == "provider.prepared")
        self.assertEqual(prepared["selected_paths"], ["sample.txt"])
        self.assertEqual(prepared["attachments"][0]["base_sha256"], prepared["attachments"][0]["text_sha256"])
        records = runtime.journal.events("application", kind="capability.measurement.result")
        self.assertEqual(records[-1]["payload"], report)
        self.assertIn("Historical", format_report(report, historical=True))
        self.assertIn("GPU placement", report["summary"]["unqualified"])

    def test_mid_suite_cancellation_retains_completed_results_without_qualification(self):
        _, client, report = self.run_fixture(cancel_case="instruction exact")
        self.assertEqual(report["status"], "cancelled")
        self.assertFalse(report["eligible_session_observation"])
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(report["summary"]["instruction_smoke"], "not completed")

    def test_changed_asset_session_never_becomes_eligible(self):
        _, _, report = self.run_fixture(mutate_case="instruction exact")
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["eligible_session_observation"])
        self.assertIn("configuration changed", report["error"])

    def test_quality_failures_remain_specific_and_do_not_abort_other_samples(self):
        _, client, report = self.run_fixture(wrong_answers=True)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(client.requests), 7)
        self.assertEqual(report["summary"]["instruction_smoke"], "failed")
        self.assertEqual(report["summary"]["selected_file_smoke"], "failed")
        self.assertEqual(report["summary"]["local_text"], "passed")

    def test_ambiguous_digest_residency_cannot_claim_a_cold_sample(self):
        _, client, report = self.run_fixture(resident_alias="another-tag")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(client.requests, [])
        self.assertIn("ambiguous residency", report["error"])

    def test_changed_synthetic_file_is_preserved_and_never_sent(self):
        runtime, client, report = self.run_fixture(change_file=True)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(client.requests), 3)
        self.assertIn("sample file changed", report["error"])
        path = next((runtime.directory / "capability-samples").glob("*/sample.txt"))
        self.assertEqual(path.read_text(encoding="utf-8"), "changed synthetic source")

    def test_late_final_inspection_cannot_promote_an_expired_suite(self):
        _, client, report = self.run_fixture(expire_after_samples=True)
        self.assertEqual(len(client.requests), 7)
        self.assertEqual(report["status"], "timed_out")
        self.assertFalse(report["eligible_session_observation"])
        self.assertFalse(client.cancelled.is_set())


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from ceta_desktop.app import MainWindow


class CapabilityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.window = MainWindow(self.root)
        self.panel = self.window.capabilities_panel

    def tearDown(self):
        for task in self.window.tasks:
            task.cancelled.set()
        end = time.monotonic() + 8
        while self.window.tasks and time.monotonic() < end:
            self.app.processEvents(); time.sleep(.01)
        self.assertFalse(self.window.tasks)
        self.window.editor.document().setModified(False)
        self.assertTrue(self.window.close())
        self.window.deleteLater(); self.app.processEvents()

    def test_no_automatic_measurement_and_external_model_is_not_promoted(self):
        self.assertIsNone(self.panel.report)
        self.assertIn("No measurement", self.panel.status.text())
        with patch("ceta_desktop.pages.capabilities.measure_configuration") as run:
            self.panel.measure_button.click()
        run.assert_not_called()
        self.assertIn("managed model first", self.panel.status.text())

    def test_setting_change_invalidates_results_and_cancels_active_measurement(self):
        self.panel.task = SimpleNamespace(cancelled=threading.Event())
        report = {"status": "completed", "elapsed_seconds": 1, "samples": [], "summary": summarize({}),
                  "configuration": {"hardware": hardware_identity(HARDWARE)}}
        self.panel.report, self.panel.bound = report, ("selected",)
        self.window.model_combo.setCurrentText("changed")
        self.assertTrue(self.panel.task.cancelled.is_set())
        self.assertIsNone(self.panel.bound)
        self.assertIn("Historical", self.panel.results.toPlainText())
        self.panel.task = None

    def test_history_never_restores_live_state(self):
        self.window.task_runtime.application_project()
        report = {"status": "completed", "elapsed_seconds": 1, "samples": [], "summary": summarize({})}
        self.window.task_runtime.journal.append("application", "capability.measurement.result", report)
        self.panel.history()
        self.assertFalse(self.panel.measure_button.isEnabled())
        end = time.monotonic() + 8
        while self.window.tasks and time.monotonic() < end:
            self.app.processEvents(); time.sleep(.01)
        self.assertIsNone(self.panel.bound)
        self.assertIsNone(self.panel.report)
        self.assertIn("Historical", self.panel.results.toPlainText())

    def test_worker_change_at_request_preparation_invalidates_measurement(self):
        self.panel.report = {"status": "completed", "elapsed_seconds": 1, "samples": [], "summary": summarize({}),
                             "configuration": {"max_tokens": 1024}, "worker_binding": WORKER}
        self.panel.bound = ("selected",)
        self.panel.observe_prepared({"budget": {"tokenization": {"binding": {**WORKER, "job": "changed"}}}, "profile": {"max_tokens": 1024}})
        self.assertIsNone(self.panel.bound)

    def test_native_measurement_is_explicit_cancellable_and_restores_controls(self):
        entered, release = threading.Event(), threading.Event()
        report = {"status": "cancelled", "elapsed_seconds": .1, "samples": [], "summary": summarize({}),
                  "eligible_session_observation": False}
        def measure(runtime, client, model, *, cancelled, progress):
            entered.set()
            while not cancelled.wait(.01) and not release.is_set():
                pass
            return report
        with patch.object(self.panel, "selection", return_value=("http://127.0.0.1:11434/v1", "fixture", "run", "assets")), \
                patch.object(self.window, "_configured_model_client", return_value=FixtureClient()), \
                patch("ceta_desktop.pages.capabilities.measure_configuration", side_effect=measure) as run:
            run.assert_not_called()
            self.panel.measure_button.click()
            self.assertTrue(entered.wait(3))
            self.assertTrue(self.window.model_probe_running)
            self.assertFalse(self.panel.measure_button.isEnabled())
            self.assertTrue(self.panel.stop_button.isEnabled())
            self.panel.stop_button.click()
            end = time.monotonic() + 5
            while self.window.tasks and time.monotonic() < end:
                self.app.processEvents(); time.sleep(.01)
            release.set()
        self.assertIsNone(self.panel.task)
        self.assertFalse(self.window.model_probe_running)
        self.assertTrue(self.panel.measure_button.isEnabled())
        self.assertFalse(self.panel.stop_button.isEnabled())
        self.assertIn("Historical", self.panel.results.toPlainText())


if __name__ == "__main__":
    unittest.main()
