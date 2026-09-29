from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ceta_desktop.hardware import GIB, HardwareProfile
from ceta_desktop.managed_assets import ManagedAssets
from ceta_desktop.runtime_installation import RuntimeInstallation
from test_desktop_runtime_installation import fixture_archive

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ceta_desktop.app import MainWindow
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT and os.name == "nt", "Windows native desktop extra required")
class ManagedRuntimeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source, self.spec = fixture_archive(self.root)
        self.window = MainWindow(self.root / "data")
        self.panel = self.window.runtime_setup_panel
        self.panel.spec = self.spec
        self.installer = RuntimeInstallation(self.root / "data", self.spec)
        self.enterContext(patch("ceta_desktop.pages.runtime_setup.RuntimeInstallation", return_value=self.installer))
        self.enterContext(patch("ceta_desktop.app.RuntimeInstallation", return_value=self.installer))
        self.enterContext(patch("ceta_desktop.app.inspect_hardware", return_value=HardwareProfile(16*GIB, 12*GIB, 4)))

    def finish(self):
        deadline = time.monotonic() + 5
        while self.window.tasks and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(.005)
        self.application.processEvents()
        self.assertEqual(self.window.tasks, [])

    def tearDown(self):
        for task in self.window.tasks:
            task.cancelled.set()
        self.finish()
        self.window.editor.document().setModified(False)
        self.assertTrue(self.window.close())
        self.window.deleteLater()
        self.application.processEvents()

    def test_window_does_not_acquire_or_start_runtime_automatically(self):
        self.assertIsNone(self.panel.task)
        self.assertFalse(self.installer.destination.exists())
        self.assertEqual(self.window.model_process.program(), "")
        self.assertNotIn("installed;", self.panel.status.text())

    def test_explicit_offline_import_records_authority_without_launching(self):
        with patch("ceta_desktop.pages.runtime_setup.QFileDialog.getOpenFileName", return_value=(str(self.source), "")), \
                patch.object(self.window.model_process, "start") as start, \
                patch("ceta_desktop.runtime_installation._open_release") as network:
            self.panel.import_button.click()
            self.assertFalse(self.panel.start_button.isEnabled())
            self.finish()
            network.assert_not_called()
            start.assert_not_called()
        self.assertIn("2 pinned files verified", self.panel.status.text())
        self.assertTrue(self.panel.start_button.isEnabled())
        events = self.window.task_runtime.journal.events("application", kind="operation.intent")
        self.assertTrue(any(row["payload"]["kind"] == "runtime.import" for row in events))

    def test_cancelled_import_picker_and_bad_archive_do_not_start(self):
        with patch("ceta_desktop.pages.runtime_setup.QFileDialog.getOpenFileName", return_value=("", "")):
            self.panel.import_archive()
        self.assertIsNone(self.panel.task)
        self.source.write_bytes(b"wrong")
        with patch.object(self.window.model_process, "start") as start:
            self.panel._acquire(self.source)
            self.finish()
            start.assert_not_called()
        self.assertIn("size does not match", self.panel.status.text())
        self.assertFalse(self.installer.destination.exists())

    def test_managed_start_checks_bytes_hardware_and_preserves_model_choice(self):
        self.installer.acquire(source=self.source)
        self.window.model_combo.setCurrentText("keep-manual-selection")
        with patch.object(self.window, "_launch_ollama") as launch:
            self.window.start_managed_runtime()
            self.finish()
        self.assertEqual(launch.call_args.kwargs["managed"]["files_verified"], 2)
        self.assertEqual(self.window.hardware_profile.available_ram_bytes, 12*GIB)
        self.assertEqual(self.window.model_combo.currentText(), "keep-manual-selection")
        self.assertIsNone(self.window.model_preparation)

    def test_modified_runtime_cannot_start(self):
        self.installer.acquire(source=self.source)
        (self.installer.destination / "lib/backend.dll").write_bytes(b"modified")
        with patch.object(self.window, "_launch_ollama") as launch:
            self.window.start_managed_runtime()
            self.finish()
            launch.assert_not_called()
        self.assertIn("mismatch", self.panel.status.text())

    def test_settings_change_during_verification_cancels_launch(self):
        self.installer.acquire(source=self.source)
        original_verify = self.installer.verify
        arrived, release = threading.Event(), threading.Event()
        def verify(**kwargs):
            arrived.set()
            if not release.wait(3):
                raise TimeoutError("fixture was not released")
            return original_verify(**kwargs)
        with patch.object(self.installer, "verify", side_effect=verify), patch.object(self.window, "_launch_ollama") as launch:
            self.window.start_managed_runtime()
            self.assertTrue(arrived.wait(3))
            self.window.endpoint.setText("http://127.0.0.1:22222/v1")
            release.set()
            self.finish()
            launch.assert_not_called()
        self.assertIn("settings changed", self.panel.status.text())

    def test_managed_launch_uses_private_state_and_restart_reverifies(self):
        self.installer.acquire(source=self.source)
        assets = ManagedAssets(self.installer)
        self.addCleanup(assets.close)
        record = assets.protect_runtime()
        with patch.object(self.window, "_start_owned_model", return_value=True):
            self.assertTrue(self.window._launch_ollama(record["executable"], managed=record, assets=assets))
        environment = self.window.model_process.processEnvironment()
        self.assertEqual(environment.value("OLLAMA_HOST"), "127.0.0.1:11435")
        self.assertTrue(Path(environment.value("OLLAMA_MODELS")).is_relative_to(self.root))
        self.assertEqual(self.window.endpoint.text(), "http://127.0.0.1:11435/v1")
        with patch.object(self.window, "start_managed_runtime") as managed, patch.object(self.window, "start_ollama") as external:
            self.window.restart_local_model()
            self.window._complete_owned_restart()
        managed.assert_called_once_with()
        external.assert_not_called()


if __name__ == "__main__":
    unittest.main()
