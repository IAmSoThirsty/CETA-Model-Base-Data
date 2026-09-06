from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ceta_desktop.app import MainWindow


@unittest.skipUnless(HAS_QT, "Desktop extra is required for native UI tests")
class DesktopGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = MainWindow(self.root / "app-data")
        self.window.show()
        QTest.qWait(30)

    def tearDown(self):
        self.window.editor.document().setModified(False)
        self.window.close()
        QTest.qWait(30)
        self.temp.cleanup()

    def test_navigation_and_offline_chat(self):
        self.assertTrue(self.window.windowTitle().startswith("CETA · "))
        for index in range(self.window.pages.count()):
            self.window.navigation.setCurrentRow(index)
            self.assertEqual(self.window.pages.currentIndex(), index)
        self.window.prompt.setPlainText("Hello")
        self.window.send_message()
        self.assertIn("installed model", self.window.chat_status.text())
        self.assertEqual(self.window.prompt.toPlainText(), "Hello")

    @unittest.skipUnless(os.name == "nt", "Windows installer handoff")
    def test_update_install_requires_explicit_confirmation_and_no_active_work(self):
        self.window._update_saved(self.root / "update.exe", {"version": "0.3.1"})
        self.assertTrue(self.window.install_update_button.isEnabled())
        with patch("ceta_desktop.app.QMessageBox.question", return_value=QMessageBox.No), patch.object(self.window, "close") as close:
            self.window.install_update()
            close.assert_not_called()
            self.assertIsNone(self.window.pending_update)
        with patch.object(self.window.process, "state", return_value=QProcess.Running), patch("ceta_desktop.app.QMessageBox.question") as question:
            self.window.install_update()
            question.assert_not_called()
            self.assertIsNone(self.window.pending_update)
            self.assertIn("Stop active", self.window.update_status.text())

    @unittest.skipUnless(os.name == "nt", "Windows installer handoff")
    def test_update_install_respects_unsaved_editor_cancel(self):
        self.window._update_saved(self.root / "update.exe", {"version": "0.3.1"})
        self.window.editor.setPlainText("keep this work")
        self.window.editor.document().setModified(True)
        with patch("ceta_desktop.app.QMessageBox.question", side_effect=[QMessageBox.Yes, QMessageBox.Cancel]):
            self.window.install_update()
        self.assertIsNone(self.window.pending_update)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.editor.toPlainText(), "keep this work")
        self.assertTrue(self.window.editor.document().isModified())
        self.window.store.set_setting("still_open", True)

    @unittest.skipUnless(os.name == "nt", "Windows installer handoff")
    def test_confirmed_update_is_queued_only_after_successful_close(self):
        self.window._update_saved(self.root / "update.exe", {"version": "0.3.1"})
        with patch("ceta_desktop.app.QMessageBox.question", return_value=QMessageBox.Yes), patch.object(self.window, "close", return_value=True) as close:
            self.window.install_update()
            close.assert_called_once_with()
            self.assertEqual(self.window.pending_update, self.window.downloaded_update)

    def test_main_releases_marker_and_data_lock_before_install_handoff(self):
        from ceta_desktop.app import main
        order = []
        with patch("ceta_desktop.app.QApplication") as application, patch("ceta_desktop.app.MainWindow") as window, patch("ceta_desktop.app.QLockFile") as lock, patch("ceta_desktop.app.open_application_marker", return_value=42), patch("ceta_desktop.app.close_application_marker", side_effect=lambda _: order.append("marker")), patch("ceta_desktop.app.launch_verified_update", side_effect=lambda *_: order.append("installer")), patch.object(sys, "argv", ["ceta", "--data-dir", str(self.root / "handoff")]):
            application.return_value.exec.return_value = 0
            lock.return_value.tryLock.return_value = True
            lock.return_value.unlock.side_effect = lambda: order.append("data_lock")
            window.return_value.pending_update = (self.root / "update.exe", {"version": "0.3.1"})
            self.assertEqual(main(), 0)
        self.assertEqual(order, ["marker", "data_lock", "installer"])

    def test_started_ollama_disables_cloud_without_changing_parent_settings(self):
        model_directory = str(self.root / "existing-models")
        inherited = {"OLLAMA_HOST": "0.0.0.0:9999", "OLLAMA_NO_CLOUD": "0", "OLLAMA_MODELS": model_directory}
        with patch.dict(os.environ, inherited), patch("ceta_desktop.app.shutil.which", return_value="ollama"), patch.object(self.window.model_process, "start") as start:
            self.window.start_ollama()
            start.assert_called_once_with()
            environment = self.window.model_process.processEnvironment()
            self.assertEqual(environment.value("OLLAMA_NO_CLOUD"), "1")
            self.assertEqual(environment.value("OLLAMA_HOST"), "127.0.0.1:11434")
            self.assertEqual(environment.value("OLLAMA_MODELS"), model_directory)
            self.assertEqual(self.window.model_process.program(), "ollama")
            self.assertEqual(self.window.model_process.arguments(), ["serve"])
            self.assertEqual(self.window.endpoint.text(), "http://127.0.0.1:11434/v1")
            for name, value in inherited.items():
                self.assertEqual(os.environ[name], value)

    def test_open_edit_save_and_conflict(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        path = workspace / "hello.py"
        path.write_text("print('hello')\n", encoding="utf-8")
        self.window._set_workspace(workspace)
        QTest.qWait(80)
        self.window.open_document(self.window.file_model.index(str(path)))
        self.assertIn("hello", self.window.editor.toPlainText())
        self.window.editor.setPlainText("print('updated')\n")
        self.assertTrue(self.window.save_document())
        self.assertIn("updated", path.read_text())
        path.write_text("external")
        with patch.object(self.window, "_error") as error:
            self.assertFalse(self.window.save_document())
            error.assert_called_once()
        self.assertEqual(path.read_text(), "external")

    def test_workload_exit_and_persistence(self):
        self.window._set_workspace(self.root)
        self.window.command.setText("Write-Output 'desktop-workload-ok'" if os.name == "nt" else "printf desktop-workload-ok")
        self.window.run_workload()
        for _ in range(150):
            QTest.qWait(50)
            if self.window.process.state() == QProcess.NotRunning:
                break
        self.assertIsNone(self.window.workload_id)
        self.assertIn("desktop-workload-ok", self.window.output.toPlainText())
        row = self.window.store.db.execute("SELECT status,exit_code FROM workloads").fetchone()
        self.assertEqual(tuple(row), ("complete", 0))
        self.assertEqual(self.window.workload_history.count(), 1)

    def test_failed_model_connection_keeps_user_message(self):
        self.window.endpoint.setText("http://127.0.0.1:1/v1")
        self.window.model_combo.setCurrentText("unavailable-test-model")
        self.window.prompt.setPlainText("Keep this message")
        self.window.send_message()
        for _ in range(250):
            QTest.qWait(50)
            if not self.window.chat_task:
                break
        self.assertIsNone(self.window.chat_task)
        messages = self.window.store.messages(self.window.conversation_id)
        self.assertEqual(messages[0]["content"], "Keep this message")
        self.assertEqual(messages[-1]["status"], "failed")
        self.assertTrue(self.window.send_button.isEnabled())

    def test_cancelling_workload_records_cancellation(self):
        self.window._set_workspace(self.root)
        self.window.command.setText("Start-Sleep -Seconds 30" if os.name == "nt" else "sleep 30")
        self.window.run_workload()
        QTest.qWait(400)
        self.window.stop_workload()
        for _ in range(100):
            QTest.qWait(50)
            if self.window.process.state() == QProcess.NotRunning:
                break
        self.assertEqual(self.window.process.state(), QProcess.NotRunning)
        row = self.window.store.db.execute("SELECT status FROM workloads").fetchone()
        self.assertEqual(row[0], "cancelled")

    def test_file_attachment_requires_explicit_action(self):
        path = self.root / "code.txt"
        path.write_text("selected file contents")
        self.window._set_workspace(self.root)
        QTest.qWait(60)
        self.window.open_document(self.window.file_model.index(str(path)))
        self.assertEqual(self.window.prompt.toPlainText(), "")
        self.window.attach_document()
        self.assertIn("selected file contents", self.window.prompt.toPlainText())
        self.assertIn("code.txt", self.window.prompt.toPlainText())

    def test_unsaved_draft_recovery_does_not_modify_original(self):
        path = self.root / "recover.txt"
        path.write_text("original")
        self.window._set_workspace(self.root)
        QTest.qWait(60)
        self.window.open_document(self.window.file_model.index(str(path)))
        self.window.editor.setPlainText("unsaved draft")
        self.window.editor.document().setModified(True)
        self.window._save_editor_draft()
        self.assertEqual(path.read_text(), "original")
        self.window._restore_editor_draft()
        self.assertEqual(self.window.editor.toPlainText(), "unsaved draft")
        self.assertTrue(self.window.editor.document().isModified())
        self.assertEqual(path.read_text(), "original")

    def test_cancelled_file_dialog_retains_editor_recovery_draft(self):
        path = self.root / "retained.txt"
        path.write_text("original")
        self.window._set_workspace(self.root)
        QTest.qWait(60)
        self.window.open_document(self.window.file_model.index(str(path)))
        self.window.editor.setPlainText("keep my edit")
        self.window.editor.document().setModified(True)
        self.window._save_editor_draft()
        with patch("ceta_desktop.app.QMessageBox.question", return_value=QMessageBox.Discard), patch("ceta_desktop.app.QFileDialog.getExistingDirectory", return_value=""):
            self.window.choose_workspace()
        self.assertEqual(self.window.store.setting("editor_draft")["text"], "keep my edit")
        self.assertTrue(self.window.editor.document().isModified())
        self.assertEqual(path.read_text(), "original")

    def test_chat_drafts_follow_their_conversation(self):
        self.window.new_conversation()
        first = self.window.conversation_id
        self.window.prompt.setPlainText("First conversation draft")
        self.window.new_conversation()
        second = self.window.conversation_id
        self.assertNotEqual(first, second)
        self.assertEqual(self.window.prompt.toPlainText(), "")
        self.window.prompt.setPlainText("Second conversation draft")
        self.window._switch_conversation(first)
        self.assertEqual(self.window.prompt.toPlainText(), "First conversation draft")
        self.window._switch_conversation(second)
        self.assertEqual(self.window.prompt.toPlainText(), "Second conversation draft")
        self.assertEqual(self.window.store.setting("active_conversation"), second)

    def test_oversized_history_does_not_consume_draft_or_append_user_message(self):
        self.window.new_conversation()
        self.window.store.add_message(self.window.conversation_id, "assistant", "x" * 512001)
        self.window.model_combo.setCurrentText("test-model")
        self.window.prompt.setPlainText("Keep my draft")
        self.window.send_message()
        self.assertEqual(self.window.prompt.toPlainText(), "Keep my draft")
        self.assertEqual(len(self.window.store.messages(self.window.conversation_id)), 1)
        self.assertIsNone(self.window.chat_task)
        self.assertIn("too long", self.window.chat_status.text())

    def test_restart_restores_both_editor_and_chat_drafts(self):
        from ceta_desktop.storage import Store
        path = self.root / "restart.txt"
        path.write_text("original")
        data = self.root / "restart-data"
        store = Store(data)
        conversation = store.new_conversation("Draft conversation")
        store.set_setting("active_conversation", conversation)
        store.set_setting("chat_draft:" + conversation, "Unsent conversation message")
        store.set_setting("workspace", str(self.root))
        from ceta_desktop.workspace import Workspace
        document = Workspace(self.root).open(path)
        store.set_setting("editor_draft", {"workspace": str(self.root), "path": str(path), "text": "Unsaved code", "digest": document.digest})
        store.close()
        reopened = MainWindow(data)
        try:
            self.assertEqual(reopened.prompt.toPlainText(), "Unsent conversation message")
            self.assertEqual(reopened.editor.toPlainText(), "Unsaved code")
            self.assertTrue(reopened.editor.document().isModified())
            self.assertEqual(path.read_text(), "original")
        finally:
            reopened.editor.document().setModified(False)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
