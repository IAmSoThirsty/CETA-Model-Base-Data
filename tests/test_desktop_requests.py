from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from ceta_desktop.request_control import ModelDeadlineError, RequestBudget

HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QTimer
    from ceta_desktop.app import MainWindow
    from runtime.tasks import TaskRuntime
    from test_desktop_merged_tasks import FakeLocalClient


@unittest.skipUnless(HAS_QT, "Desktop extra required")
class DesktopRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ceta-request-ui-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src/AGENTS.md").write_text("Nested instruction: report file paths.", encoding="utf-8")
        self.file = self.project / "src/example.py"
        self.file.write_text("disk = 1", encoding="utf-8")
        self.window = MainWindow(self.root / "data")
        self.window._set_workspace(self.project)
        self.window.model_combo.setCurrentText("fixture-model")
        self.requests = []

    def tearDown(self):
        self.window.stop_chat()
        self.wait_idle()
        self.window.editor.document().setModified(False)
        self.window.close()
        self.temp.cleanup()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 15
        while not predicate():
            if time.monotonic() > deadline:
                self.fail("Request worker did not reach the expected state")
            self.app.processEvents()
            time.sleep(0.01)

    def wait_idle(self):
        self.wait_until(lambda: not self.window.chat_task and not self.window.tasks)

    def attach(self, text="draft = 2"):
        self.window.open_document(self.window.file_model.index(str(self.file)))
        self.window.editor.setPlainText(text)
        self.window.attach_document()
        self.window.prompt.setPlainText("Explain the attached file")

    def send(self):
        with patch("ceta_desktop.app.LocalModelClient", return_value=FakeLocalClient(self.requests)):
            self.window.send_message()
            self.wait_idle()

    def test_attachment_carries_nested_instructions_and_unsaved_snapshot(self):
        self.attach()
        self.send()
        self.assertEqual(len(self.requests), 1)
        messages = self.requests[0]["messages"]
        self.assertIn("Nested instruction", messages[0]["content"])
        self.assertIn("draft = 2", messages[-1]["content"])
        self.assertIn("src/example.py", messages[-1]["content"])
        self.assertEqual(self.file.read_text(), "disk = 1")
        self.assertEqual(self.window.attachments, [])
        self.assertIn("Tokenizer not verified", self.window.request_summary.text())

    def test_changed_attached_editor_draft_requires_reattachment(self):
        self.attach()
        self.window.editor.setPlainText("new draft")
        self.send()
        self.assertEqual(self.requests, [])
        self.assertIn("changed", self.window.chat_status.text())
        self.assertEqual(self.window.prompt.toPlainText(), "Explain the attached file")

    def test_counted_request_preview_identifies_exact_count(self):
        self.window.prompt.setPlainText("中文🙂" * 100)
        with patch("runtime.model_provider.LocalProvider.request_counter", return_value=lambda messages:
                {"input_tokens": 123, "verified": True, "method": "fixture"}):
            self.send()
        self.assertEqual(len(self.requests), 1)
        self.assertIn("Counted input 123", self.window.request_summary.text())
        self.assertIn("context margin 1", self.window.request_summary.text())
        self.assertNotIn("Tokenizer not verified", self.window.request_summary.text())

    def test_tokenizer_failure_keeps_composer_and_transcript(self):
        self.window.prompt.setPlainText("Keep this draft")
        with patch("runtime.model_provider.LocalProvider.request_counter", side_effect=ValueError("Tokenizer worker changed")):
            self.send()
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.window.conversation_id)
        self.assertEqual(self.window.prompt.toPlainText(), "Keep this draft")
        self.assertIn("Tokenizer worker changed", self.window.chat_status.text())

    def test_preparation_failure_preserves_composer_and_transcript(self):
        (self.project / "AGENTS.md").write_text("mandatory " * 500, encoding="utf-8")
        self.window.prompt.setPlainText("Retain this request")
        self.send()
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.window.conversation_id)
        self.assertEqual(self.window.prompt.toPlainText(), "Retain this request")
        self.assertIn("mandatory instructions", self.window.chat_status.text())

    def test_edited_draft_during_worker_preparation_is_not_sent(self):
        entered, release = threading.Event(), threading.Event()
        original = TaskRuntime.prepare_generation
        def delayed(runtime, *args, **kwargs):
            entered.set()
            release.wait(5)
            return original(runtime, *args, **kwargs)
        self.window.prompt.setPlainText("Original request")
        with patch.object(TaskRuntime, "prepare_generation", delayed), \
                patch("ceta_desktop.app.LocalModelClient", return_value=FakeLocalClient(self.requests)):
            try:
                self.window.send_message()
                self.wait_until(entered.is_set)
                self.window.prompt.setPlainText("Edited during preparation")
            finally:
                release.set()
            self.wait_idle()
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.window.conversation_id)
        self.assertEqual(self.window.prompt.toPlainText(), "Edited during preparation")

    def test_cancel_during_preparation_retains_draft(self):
        entered, release = threading.Event(), threading.Event()
        original = TaskRuntime.prepare_generation
        def delayed(runtime, *args, **kwargs):
            entered.set()
            release.wait(5)
            return original(runtime, *args, **kwargs)
        self.window.prompt.setPlainText("Stopped request")
        with patch.object(TaskRuntime, "prepare_generation", delayed), \
                patch("ceta_desktop.app.LocalModelClient", return_value=FakeLocalClient(self.requests)):
            try:
                self.window.send_message()
                self.wait_until(entered.is_set)
                self.window.stop_chat()
            finally:
                release.set()
            self.wait_idle()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.window.prompt.toPlainText(), "Stopped request")

    def test_omitted_file_requires_review_and_decline_preserves_draft(self):
        self.attach("x" * 5000)
        with patch("ceta_desktop.app.QMessageBox.question", return_value=QMessageBox.No) as question:
            self.send()
        question.assert_called_once()
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.window.conversation_id)
        self.assertEqual(len(self.window.attachments), 1)

    def test_preview_modal_can_finish_preparation_before_admitting_request(self):
        self.window.prompt.setPlainText("Preview this request")
        original = QMessageBox.exec
        def accept_preview(box):
            self.assertIn("Preview this request", box.detailedText())
            QTimer.singleShot(100, lambda: box.done(QMessageBox.Ok))
            return original(box)
        with patch("ceta_desktop.app.LocalModelClient", return_value=FakeLocalClient(self.requests)), \
                patch.object(QMessageBox, "exec", accept_preview):
            self.window.send_message(preview=True)
            self.wait_idle()
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.window.send_button.isEnabled())
        self.assertEqual(self.window.store.messages(self.window.conversation_id)[-1]["status"], "complete")

    def test_admission_write_failure_preserves_draft_and_rolls_back_new_conversation(self):
        self.window.prompt.setPlainText("Keep on storage failure")
        original = self.window.store.set_setting
        def fail_retry(key, value):
            if key.startswith("request_retry:"):
                raise OSError("simulated admission failure")
            return original(key, value)
        with patch.object(self.window.store, "set_setting", side_effect=fail_retry):
            self.send()
        self.assertIsNone(self.window.conversation_id)
        self.assertEqual(self.window.store.conversations(), [])
        self.assertEqual(self.requests, [])
        self.assertEqual(self.window.prompt.toPlainText(), "Keep on storage failure")

    def test_expired_preview_retains_draft_before_conversation_admission(self):
        self.window.prompt.setPlainText("Keep after preview expires")
        def budget(seconds, cancelled=None, receipt=None):
            result = RequestBudget(seconds, cancelled, receipt)
            if receipt is not None:
                result.deadline = time.monotonic() - 1
            return result
        with patch("ceta_desktop.app.RequestBudget", side_effect=budget), \
             patch.object(QMessageBox, "exec", return_value=QMessageBox.Ok), \
             patch("ceta_desktop.app.LocalModelClient", return_value=FakeLocalClient(self.requests)):
            self.window.send_message(preview=True)
            self.wait_idle()
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.window.conversation_id)
        self.assertEqual(self.window.prompt.toPlainText(), "Keep after preview expires")
        self.assertIn("time limit", self.window.chat_status.text())

    def test_timeout_retains_partial_output_and_retry_with_distinct_status(self):
        class TimedClient(FakeLocalClient):
            def stream(self, model, messages, **limits):
                yield from super().stream(model, messages, **limits)
                raise ModelDeadlineError("fixture response deadline")
        client = TimedClient(self.requests)
        self.window.prompt.setPlainText("Keep partial response")
        with patch("ceta_desktop.app.LocalModelClient", return_value=client):
            self.window.send_message()
            self.wait_idle()
        rows = self.window.store.messages(self.window.conversation_id)
        self.assertEqual(rows[-1]["status"], "timed_out")
        self.assertEqual(rows[-1]["content"], "Inspected task context.")
        self.assertFalse(client.cancelled.is_set())
        self.assertIn("time limit", self.window.chat_status.text())
        self.window.restore_failed_request()
        self.assertEqual(self.window.prompt.toPlainText(), "Keep partial response")

    def test_dispatch_failure_preserves_retry_and_does_not_duplicate_user_turn(self):
        self.attach()
        original = self.window._generation_prepared
        def changed_source(*args):
            self.file.write_text("external change", encoding="utf-8")
            return original(*args)
        with patch.object(self.window, "_generation_prepared", side_effect=changed_source):
            self.send()
        self.assertEqual(self.requests, [])
        records = self.window.store.messages(self.window.conversation_id)
        self.assertEqual(records[-1]["status"], "failed")
        self.assertEqual(sum(row["role"] == "user" for row in records), 1)
        self.assertTrue(self.window.task_runtime.journal.events(self.window.project_id, kind="provider.not_sent"))
        self.file.write_text("disk = 1", encoding="utf-8")
        self.window.restore_failed_request()
        self.send()
        self.assertEqual(len(self.requests), 1)
        records = self.window.store.messages(self.window.conversation_id)
        self.assertEqual(sum(row["role"] == "user" for row in records), 1)
        self.assertEqual([row["status"] for row in records if row["role"] == "assistant"], ["failed", "complete"])


if __name__ == "__main__":
    unittest.main()
