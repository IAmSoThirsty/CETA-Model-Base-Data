from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ceta_desktop.app import MainWindow
    from ceta_desktop.pages.recovery import RecoveryWindow
    from runtime.runtime_keys import RecoveryRequired


@unittest.skipUnless(HAS_QT, "Desktop extra is required for native UI tests")
class DesktopRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ceta-recovery-ui-")
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.window = MainWindow(self.data)
        self.addCleanup(self.close_window)
        self.window._ensure_task()

    def close_window(self):
        if self.window is not None:
            self.window.close()
            self.window = None

    def test_expired_send_keeps_draft_and_explicit_resume_uses_same_task(self):
        task_id = self.window.task_id
        grant = self.window.task_runtime.task_access_status(task_id)
        self.window.prompt.setPlainText("Retain my unsent draft")
        self.window.model_combo.setCurrentText("test-local")
        before = self.window.store.conversations()
        with patch("runtime.tasks._now", return_value=grant["expires_at_epoch_ms"] + 1):
            self.window.send_message()
            self.assertEqual(self.window.prompt.toPlainText(), "Retain my unsent draft")
            self.assertEqual(self.window.store.conversations(), before)
            self.assertIsNone(self.window.chat_task)
            self.assertFalse(self.window.chat_resume_button.isHidden())
            self.window.chat_resume_button.click()
            self.assertEqual(self.window.task_id, task_id)
            self.assertEqual(self.window.task_runtime.task_access_status(task_id)["status"], "active")
            self.assertEqual(self.window.prompt.toPlainText(), "Retain my unsent draft")

    def test_revocation_after_button_display_cannot_be_treated_as_renewal(self):
        task_id = self.window.task_id
        grant = self.window.task_runtime.task_access_status(task_id)
        with patch("runtime.tasks._now", return_value=grant["expires_at_epoch_ms"] + 1):
            self.window._refresh_task_panel()
            self.window.task_runtime.revoke_task(task_id)
            self.window.chat_resume_button.click()
            self.assertEqual(self.window.task_runtime.task_access_status(task_id)["status"], "revoked")
            self.assertEqual(self.window.chat_resume_button.text(), "Reauthorize task")
            self.window.chat_resume_button.click()
            self.assertEqual(self.window.task_runtime.task_access_status(task_id)["status"], "active")

    def test_next_day_window_restart_keeps_task_until_explicit_resume(self):
        project = Path(self.temp.name) / "project"
        project.mkdir()
        self.window._set_workspace(project)
        task_id = self.window.task_id
        grant = self.window.task_runtime.task_access_status(task_id)
        history = self.window.task_runtime.timeline(task_id)
        self.close_window()
        with patch("runtime.tasks._now", return_value=grant["expires_at_epoch_ms"] + 1):
            self.window = MainWindow(self.data)
            self.assertEqual(self.window.task_id, task_id)
            self.assertEqual(self.window.task_runtime.timeline(task_id), history)
            self.assertEqual(self.window.task_runtime.task_access_status(task_id)["status"], "expired")
            self.window.task_panel.resume_button.click()
            self.assertEqual(self.window.task_runtime.task_access_status(task_id)["status"], "active")

    def test_missing_keys_are_detected_before_store_changes(self):
        self.window.prompt.setPlainText("Recovery draft")
        self.close_window()
        (self.data / "runtime-identity.json").unlink()
        before = (self.data / "desktop.sqlite3").read_bytes()
        with self.assertRaises(RecoveryRequired), patch("ceta_desktop.app.Store") as store:
            MainWindow(self.data)
        store.assert_not_called()
        self.assertEqual((self.data / "desktop.sqlite3").read_bytes(), before)

    def test_recovery_reads_and_exports_without_replacing_or_activating_data(self):
        conversation = self.window.store.new_conversation("Retained")
        self.window.store.add_message(conversation, "user", "saved text")
        self.close_window()
        before = (self.data / "desktop.sqlite3").read_bytes()
        recovery = RecoveryWindow(self.data, "Runtime identity missing")
        self.addCleanup(recovery.close)
        recovery.conversations.setCurrentRow(0)
        self.assertIn("saved text", recovery.preview.toPlainText())
        target = Path(self.temp.name) / "export.json"
        with patch("ceta_desktop.pages.recovery.QFileDialog.getSaveFileName", return_value=(str(target), "JSON")):
            recovery.export_conversation()
            first = target.read_bytes()
            recovery.export_conversation()
        self.assertEqual(target.read_bytes(), first)
        self.assertFalse(json.loads(first)["grants_authority"])
        self.assertEqual((self.data / "desktop.sqlite3").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
