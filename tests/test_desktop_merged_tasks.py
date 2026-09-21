from __future__ import annotations

import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ceta_desktop.app import MainWindow
    from ceta_desktop.hardware import HardwareProfile


class FakeLocalClient:
    def __init__(self, requests, failure=None):
        self.cancelled = threading.Event()
        self.requests = requests
        self.failure = failure

    def stream(self, model, messages, **limits):
        self.requests.append({"model": model, "messages": messages, "limits": limits})
        if self.failure:
            raise ValueError(self.failure)
        yield "Inspected task context."

    def cancel(self):
        self.cancelled.set()


@unittest.skipUnless(HAS_QT, "Desktop extra is required for native UI tests")
class MergedTaskGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.project = self.root / "project-one"
        self.project.mkdir()
        self.file = self.project / "example.py"
        self.file.write_text("original = 1\n", encoding="utf-8")
        self.enterContext(patch("ceta_desktop.app.inspect_hardware", return_value=HardwareProfile(16 * 1024**3, 12 * 1024**3, 8)))
        self.window = MainWindow(self.data)
        self.window.show()
        QTest.qWait(30)

    def tearDown(self):
        self.window.stop_chat()
        self.window.stop_workload()
        self.wait_idle()
        self.window.editor.document().setModified(False)
        self.assertTrue(self.window.close())
        QTest.qWait(20)
        self.temp.cleanup()

    def wait_idle(self, seconds=45):
        deadline = time.monotonic() + seconds
        while self.window.chat_task or self.window.workload_task or self.window.tasks:
            if time.monotonic() >= deadline:
                self.fail("Native task work did not finish within its test deadline")
            self.app.processEvents()
            time.sleep(0.01)

    def open_file(self):
        self.window._set_workspace(self.project)
        QTest.qWait(50)
        self.window.open_document(self.window.file_model.index(str(self.file)))
        self.assertIsNotNone(self.window.document)

    def send_fake(self, text, requests, failure=None):
        self.window.model_combo.setCurrentText("offline-fixture")
        self.window.prompt.setPlainText(text)
        client = FakeLocalClient(requests, failure)
        with patch("ceta_desktop.app.LocalModelClient", return_value=client):
            self.window.send_message()
            self.wait_idle()

    def test_project_task_resumes_after_window_restart(self):
        self.window._set_workspace(self.project)
        first = (self.window.project_id, self.window.task_id)
        self.window.inspect_project_task()
        history = self.window.task_runtime.timeline(self.window.task_id)
        self.assertTrue(history)
        self.assertEqual(json.loads(self.window.task_panel.results.toPlainText())["root"], str(self.project))
        self.assertTrue(self.window.close())
        self.window = MainWindow(self.data)
        self.assertEqual((self.window.project_id, self.window.task_id), first)
        self.assertGreaterEqual(len(self.window.task_runtime.timeline(self.window.task_id)), len(history))

    def test_search_is_project_scoped_and_recorded(self):
        outside = self.root / "outside.py"
        outside.write_text("original = 99\n", encoding="utf-8")
        self.window._set_workspace(self.project)
        self.window.task_panel.search.setText("original")
        self.window.search_project_task()
        report = self.window.task_panel.results.toPlainText()
        self.assertIn("example.py", report)
        self.assertNotIn("outside.py", report)
        self.assertTrue(self.window.task_runtime.timeline(self.window.task_id))

    def test_review_does_not_write_and_apply_records_actual_edit(self):
        self.open_file()
        self.window.editor.setPlainText("changed = 2\n")
        self.window.review_editor_edit()
        self.assertEqual(self.file.read_text(), "original = 1\n")
        self.assertIn("+changed = 2", self.window.task_panel.results.toPlainText())
        self.assertTrue(self.window.task_panel.apply_button.isEnabled())
        self.window.apply_reviewed_edit()
        self.assertEqual(self.file.read_text(), "changed = 2\n")
        self.assertFalse(self.window.task_panel.apply_button.isEnabled())
        self.assertFalse(self.window.editor.document().isModified())
        self.assertIn("changed", json.dumps(self.window.task_runtime.timeline(self.window.task_id)))

    def test_uncertain_save_retains_dirty_editor_and_recovery_draft(self):
        self.open_file()
        self.window.editor.setPlainText("retain = 2\n")
        self.window.editor.document().setModified(True)
        with patch.object(self.window.task_runtime, "save_document", return_value={"status": "needs_reconciliation"}):
            self.assertFalse(self.window.save_document())
        self.assertTrue(self.window.editor.document().isModified())
        self.assertEqual(self.window.store.setting("editor_draft")["text"], "retain = 2\n")
        self.assertEqual(self.file.read_text(), "original = 1\n")

    def test_uncertain_apply_retains_dirty_editor_and_recovery_draft(self):
        self.open_file()
        self.window.editor.setPlainText("retain = 2\n")
        self.window.editor.document().setModified(True)
        self.window.review_editor_edit()
        with patch.object(self.window.task_runtime, "apply_edit", return_value={"status": "needs_reconciliation"}):
            self.window.apply_reviewed_edit()
        self.assertTrue(self.window.editor.document().isModified())
        self.assertEqual(self.window.store.setting("editor_draft")["text"], "retain = 2\n")
        self.assertFalse(self.window.task_panel.apply_button.isEnabled())

    def test_switching_project_clears_previous_task_evidence(self):
        self.window._set_workspace(self.project)
        self.window.task_panel.show_result("Private evidence", {"text": "PROJECT_ONE_EVIDENCE"})
        other = self.root / "project-two"
        other.mkdir()
        self.window._set_workspace(other)
        self.assertNotIn("PROJECT_ONE_EVIDENCE", self.window.task_panel.results.toPlainText())

    def test_stale_review_refuses_to_replace_external_change(self):
        self.open_file()
        self.window.editor.setPlainText("changed = 2\n")
        self.window.review_editor_edit()
        self.file.write_text("external = 3\n", encoding="utf-8")
        self.window.apply_reviewed_edit()
        self.assertEqual(self.file.read_text(), "external = 3\n")
        self.assertEqual(self.window.task_panel.result_title.text(), "Action did not complete")

    def test_editor_change_invalidates_review(self):
        self.open_file()
        self.window.editor.setPlainText("first = 2\n")
        self.window.review_editor_edit()
        self.window.editor.setPlainText("second = 3\n")
        self.assertIsNone(self.window.pending_edit)
        self.assertFalse(self.window.task_panel.apply_button.isEnabled())
        self.window.apply_reviewed_edit()
        self.assertEqual(self.file.read_text(), "original = 1\n")

    def test_switching_projects_does_not_send_previous_conversation_or_draft(self):
        self.window._set_workspace(self.project)
        first_requests = []
        self.send_fake("PRIVATE_PROJECT_ONE_MARKER", first_requests)
        first_conversation = self.window.conversation_id
        first_scope = self.window.store.conversation_scope(first_conversation)
        self.window.prompt.setPlainText("UNSENT_PROJECT_ONE_MARKER")
        other = self.root / "project-two"
        other.mkdir()
        self.window._set_workspace(other)
        self.assertEqual(self.window.prompt.toPlainText(), "")
        second_requests = []
        self.send_fake("PROJECT_TWO_REQUEST", second_requests)
        self.assertTrue(second_requests)
        transmitted = json.dumps(second_requests)
        self.assertNotIn("PRIVATE_PROJECT_ONE_MARKER", transmitted)
        self.assertNotIn("UNSENT_PROJECT_ONE_MARKER", transmitted)
        second_scope = self.window.store.conversation_scope(self.window.conversation_id)
        self.assertNotEqual(first_scope["project_id"], second_scope["project_id"])
        self.window._set_workspace(self.project)
        self.assertEqual(self.window.conversation_id, first_conversation)
        self.assertEqual(self.window.prompt.toPlainText(), "UNSENT_PROJECT_ONE_MARKER")

    def test_legacy_conversation_requires_explicit_task_assignment(self):
        legacy = self.window.store.new_conversation("Legacy")
        self.window.store.add_message(legacy, "user", "Legacy material")
        self.window._switch_conversation(legacy)
        self.window._set_workspace(self.project)
        requests = []
        self.send_fake("Continue", requests)
        self.assertEqual(requests, [])
        self.assertIn("unassigned", self.window.chat_status.text())
        self.window.bind_current_conversation()
        self.send_fake("Continue", requests)
        self.assertTrue(requests)
        self.assertEqual(self.window.store.conversation_scope(legacy)["task_id"], self.window.task_id)

    def test_bound_conversation_archive_is_named_and_retains_history(self):
        self.window._set_workspace(self.project)
        self.send_fake("Retain in project history", [])
        conversation = self.window.conversation_id
        self.assertEqual(self.window.delete_conversation_button.text(), "Archive conversation")
        history = self.window.task_runtime.timeline(self.window.task_id)
        with patch("ceta_desktop.app.QMessageBox.question", return_value=QMessageBox.Yes) as question:
            self.window.delete_conversation()
        self.assertEqual(question.call_args.args[1], "Archive conversation")
        self.assertNotIn(conversation, [row["id"] for row in self.window.store.conversations()])
        self.assertTrue(self.window.store.messages(conversation))
        self.assertGreaterEqual(len(self.window.task_runtime.timeline(self.window.task_id)), len(history))

    def test_command_uses_runtime_without_starting_legacy_process(self):
        self.window._set_workspace(self.project)
        self.window.command.setText("Write-Output 'MERGED_COMMAND_OK'" if os.name == "nt" else "printf MERGED_COMMAND_OK")
        with patch.object(self.window.process, "start") as direct_start:
            self.window.run_workload()
            self.wait_idle()
        direct_start.assert_not_called()
        self.assertIn("MERGED_COMMAND_OK", self.window.output.toPlainText())
        row = self.window.store.workloads()[0]
        self.assertEqual((row["status"], row["exit_code"]), ("complete", 0))
        self.assertIn("MERGED_COMMAND_OK", json.dumps(self.window.task_runtime.timeline(self.window.task_id)))

    def test_failed_provider_does_not_become_completed_response(self):
        self.window._set_workspace(self.project)
        self.send_fake("Keep failed request", [], failure="fixture transport failed")
        messages = self.window.store.messages(self.window.conversation_id)
        self.assertEqual(messages[-1]["status"], "failed")
        self.assertIn("fixture transport failed", self.window.chat_status.text())

    def test_model_start_uses_application_authority(self):
        with patch("ceta_desktop.app.shutil.which", return_value="ollama"), patch.object(self.window.model_process, "start") as start:
            self.window.start_ollama()
        start.assert_called_once_with()
        self.assertIsNotNone(self.window.model_action_id)
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertEqual(events[-1]["payload"]["kind"], "model.start")
        with patch.object(self.window.model_process, "processId", return_value=12345):
            self.window._model_started()
        observed = self.window.task_runtime.journal.events("application", kind="application.observed")
        self.assertEqual(observed[-1]["payload"]["observation"]["readiness"], "not_yet_tested")

    def test_immediate_model_start_error_is_retained_as_observation(self):
        def reject_start():
            self.window._model_error(None)
        with patch("ceta_desktop.app.shutil.which", return_value="ollama"), patch.object(self.window.model_process, "start", side_effect=reject_start):
            self.window.start_ollama()
        observed = self.window.task_runtime.journal.events("application", kind="application.observed")
        self.assertEqual(observed[-1]["payload"]["observation"]["phase"], "process_error")
        self.assertNotIn("Starting Ollama", self.window.model_status.text())

    def test_maintenance_denial_does_not_start_process(self):
        with patch("ceta_desktop.app.shutil.which", return_value="ollama"), patch.object(self.window.model_process, "start") as start:
            with patch("ceta_desktop.app.TaskRuntime.application_action", side_effect=ValueError("Denied test operation")):
                self.window.start_ollama()
        start.assert_not_called()
        self.assertIn("Denied test operation", self.window.model_status.text())

    def test_conversation_export_uses_application_authority(self):
        conversation = self.window.store.new_conversation("Export fixture")
        self.window.store.add_message(conversation, "user", "Exported fixture text")
        destination = self.root / "export.json"
        with patch("ceta_desktop.app.QFileDialog.getSaveFileName", return_value=(str(destination), "JSON")):
            self.window._export_conversation_id(conversation)
        self.assertEqual(json.loads(destination.read_text())[0]["content"], "Exported fixture text")
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertEqual(events[-1]["payload"]["kind"], "conversation.export")

    def test_notice_open_uses_application_authority_without_starting_external_ui(self):
        with patch("ceta_desktop.pages.updates.QDesktopServices.openUrl", return_value=True) as opened:
            self.window.open_dependency_notices()
        opened.assert_called_once()
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertEqual(events[-1]["payload"]["kind"], "notice.open")

    def test_readiness_probe_uses_application_provider_history(self):
        self.window._set_workspace(self.project)
        scope = (self.window.project_id, self.window.task_id)
        self.window.model_combo.setCurrentText("offline-readiness-fixture")
        client = FakeLocalClient([])
        record = {"status": "verified", "model": "offline-readiness-fixture", "response": "Synthetic readiness response",
                  "elapsed_seconds": 0.5, "runtime": {"size_vram": 0}}
        with patch.object(client, "probe_local_model", create=True, return_value=record) as probe:
            with patch("ceta_desktop.app.LocalModelClient", return_value=client):
                self.window.probe_model()
                self.wait_idle()
            probe.assert_called_once_with("offline-readiness-fixture", max_tokens=32, context_length=4096)
        self.assertEqual((self.window.project_id, self.window.task_id), scope)
        self.assertIn("Synthetic readiness response", self.window.model_log.toPlainText())
        history = self.window.task_runtime.journal.events("application")
        self.assertTrue(any(event["kind"] == "provider.intent" for event in history))
        result = [event for event in history if event["kind"] == "provider.result"][-1]
        self.assertEqual(result["payload"]["status"], "completed")

    def test_merger_self_test_requires_explicit_isolated_cli_scope(self):
        from ceta_desktop.app import main
        for arguments in (["--merger-self-test"], ["--merger-self-test", "--smoke-test"],
                          ["--merger-self-test", "--data-dir", str(self.root / "not-created")]):
            with self.subTest(arguments=arguments), patch("sys.argv", ["ceta", *arguments]), patch("sys.stderr", new=io.StringIO()):
                with patch("ceta_desktop.app.QApplication") as application:
                    with self.assertRaises(SystemExit) as failure:
                        main()
                    self.assertEqual(failure.exception.code, 2)
                    application.assert_not_called()
        self.assertFalse((self.root / "not-created").exists())

    def _historical_fixture(self):
        from evidence_registry.registry import EvidenceRegistry
        record = EvidenceRegistry().register(record_id="historic-1", source_id="old-ceta", payload={"note": "synthetic"})
        source = self.root / "selected-history.jsonl"
        source.write_bytes((json.dumps(record.to_dict()) + "\n").encode("utf-8"))
        return source

    def _select_historical_fixture(self, source):
        self.enterContext(patch("ceta_desktop.app.QFileDialog.getOpenFileName", return_value=(str(source), "JSON Lines")))
        self.enterContext(patch("ceta_desktop.app.QInputDialog.getItem", return_value=("evidence", True)))
        self.enterContext(patch("ceta_desktop.app.QInputDialog.getText", return_value=("Selected old CETA evidence for this test project", True)))

    def test_historical_import_needs_review_and_keeps_exact_source_hash(self):
        self.window._set_workspace(self.project)
        source = self._historical_fixture()
        original = source.read_bytes()
        expected_hash = hashlib.sha256(original).hexdigest()
        self._select_historical_fixture(source)
        with patch("ceta_desktop.app.QMessageBox.question", return_value=QMessageBox.No):
            self.window.import_historical_log()
        self.assertFalse(self.window.task_runtime.journal.events(self.window.project_id, kind="legacy.history.imported"))
        with patch("ceta_desktop.app.QMessageBox.question", return_value=QMessageBox.Yes) as reviewed:
            self.window.import_historical_log()
        self.assertIn(expected_hash, reviewed.call_args.args[2])
        self.assertIn(str(self.project), reviewed.call_args.args[2])
        self.assertEqual(reviewed.call_args.args[-1], QMessageBox.No)
        report = json.loads(self.window.task_panel.results.toPlainText())
        self.assertEqual(report["source_sha256"], expected_hash)
        self.assertEqual(report["disposition"], "historical_only")
        self.assertEqual(report["record_count"], 1)
        self.assertEqual(source.read_bytes(), original)
        events = self.window.task_runtime.timeline(self.window.task_id)
        self.assertEqual(len([event for event in events if event["kind"] == "legacy.history.imported"]), 1)
        self.assertFalse(any(event["kind"] == "operation.intent" for event in events))

    def test_historical_import_rejects_source_changed_after_review(self):
        self.window._set_workspace(self.project)
        source = self._historical_fixture()
        self._select_historical_fixture(source)
        def change_during_confirmation(*_):
            source.write_bytes(b"changed after digest review\n")
            return QMessageBox.Yes
        with patch("ceta_desktop.app.QMessageBox.question", side_effect=change_during_confirmation):
            self.window.import_historical_log()
        self.assertEqual(self.window.task_panel.result_title.text(), "Action did not complete")
        self.assertFalse(self.window.task_runtime.journal.events(self.window.project_id, kind="legacy.history.imported"))

    def test_optional_roles_use_current_task_and_record_proposals(self):
        self.window._set_workspace(self.project)
        task_id = self.window.task_id
        for role in ("reviewer", "specialist"):
            self.window.chat_role_combo.setCurrentIndex(self.window.chat_role_combo.findData(role))
            requests = []
            self.send_fake("Review the current task", requests)
            self.assertEqual(self.window.task_id, task_id)
            self.assertIn("Selected role: " + role, requests[0]["messages"][0]["content"])
            events = self.window.task_runtime.timeline(task_id)
            proposal = [event for event in events if event["kind"] == "role.proposed"][-1]["payload"]
            self.assertFalse(proposal["grants_authority"])
            self.assertFalse(proposal["independent_evidence"])
            self.assertTrue(self.window.chat_role_combo.isEnabled())
        self.assertEqual(self.file.read_text(), "original = 1\n")

    def test_application_chat_also_has_task_and_provider_evidence(self):
        requests = []
        self.send_fake("Application conversation", requests)
        self.assertTrue(requests)
        scope = self.window.store.conversation_scope(self.window.conversation_id)
        self.assertEqual(scope["project_id"], "application")
        self.assertTrue(self.window.task_runtime.timeline(scope["task_id"]))
        self.assertEqual(requests[0]["limits"]["context_length"], 4096)


if __name__ == "__main__":
    unittest.main()
