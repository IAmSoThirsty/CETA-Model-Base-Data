from __future__ import annotations

import os
import mmap
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from ceta_desktop.managed_assets import ManagedAssets, ProtectedPath
from ceta_desktop.model_installation import ManagedModels
from ceta_desktop.runtime_installation import RuntimeInstallation, RuntimeInstallError
from test_desktop_model_installation import model_fixture
from test_desktop_runtime_installation import Response, fixture_archive


@unittest.skipUnless(os.name == "nt", "Windows sharing semantics required")
class ManagedAssetsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source, spec = fixture_archive(self.root)
        self.installation = RuntimeInstallation(self.root / "data", spec)
        self.installation.acquire(source=source)
        self.assets = ManagedAssets(self.installation)
        self.addCleanup(self.assets.close)
        self.program = self.installation.destination / "ollama.exe"

    def install_model(self):
        catalog, content = model_fixture()
        models = ManagedModels(self.root / "data", catalog)
        with patch("ceta_desktop.model_installation._open_blob",
                   side_effect=lambda e, layer, h, offset: Response(content[layer["digest"]][offset:])):
            models.acquire("fixture")
        return models

    def test_files_are_locked_before_hash_and_until_release(self):
        original = self.installation.verify
        def verify(**kwargs):
            with self.assertRaises(PermissionError):
                self.program.write_bytes(b"changed")
            return original(**kwargs)
        with patch.object(self.installation, "verify", side_effect=verify):
            self.assets.protect_runtime()
        for target in (self.program, self.program.parent / "lib/backend.dll"):
            with self.subTest(target=target):
                with self.assertRaises(PermissionError):
                    target.write_bytes(b"changed")
                with self.assertRaises(PermissionError):
                    target.rename(target.with_suffix(".moved"))
                with self.assertRaises(PermissionError):
                    target.unlink()
        self.assets.close()
        self.program.write_bytes(b"released")

    def test_directory_rename_is_denied_and_new_entries_invalidate_admission(self):
        self.assets.protect_runtime()
        with self.assertRaises(PermissionError):
            self.program.parent.rename(self.program.parent.with_name("moved"))
        extra = self.program.parent / "unexpected.dll"
        extra.write_bytes(b"preserve")
        with self.assertRaisesRegex(RuntimeInstallError, "contents changed"):
            self.assets.assert_runtime()
        self.assertEqual(extra.read_bytes(), b"preserve")

    def test_new_empty_runtime_directory_is_not_silently_admitted(self):
        self.assets.protect_runtime()
        (self.program.parent / "new-directory").mkdir()
        with self.assertRaisesRegex(RuntimeInstallError, "directories changed"):
            self.assets.assert_runtime()

    def test_existing_writer_refuses_protection_and_releases_partial_handles(self):
        with self.program.open("r+b"):
            with self.assertRaises(PermissionError):
                self.assets.protect_runtime()
        self.assertEqual(self.assets._paths, {})
        self.program.write_bytes(b"writer released")

    def test_existing_writable_mapping_refuses_protection_even_after_stream_close(self):
        with self.program.open("r+b") as stream:
            mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_WRITE)
        try:
            with self.assertRaises(PermissionError):
                self.assets.protect_runtime()
            self.assertEqual(self.assets._paths, {})
        finally:
            mapping.close()
        self.assets.protect_runtime()

    def test_containing_directory_cannot_be_renamed_to_redirect_worker_paths(self):
        self.assets.protect_runtime()
        with self.assertRaises(PermissionError):
            self.root.rename(self.root.with_name(self.root.name + "-moved"))

    def test_unreadable_runtime_tree_is_rejected(self):
        self.assets.protect_runtime()
        def inaccessible(*args, **kwargs):
            kwargs["onerror"](PermissionError("fixture unreadable directory"))
        with patch("ceta_desktop.managed_assets.os.walk", side_effect=inaccessible):
            with self.assertRaisesRegex(PermissionError, "unreadable directory"):
                self.assets.assert_runtime()

    def test_hash_failure_and_cancel_release_partial_handles(self):
        with patch.object(self.installation, "verify", side_effect=RuntimeInstallError("fixture checksum mismatch")):
            with self.assertRaisesRegex(RuntimeInstallError, "checksum mismatch"):
                self.assets.protect_runtime()
        self.assertEqual(self.assets._paths, {})
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(RuntimeInstallError, "cancelled"):
            self.assets.protect_runtime(cancelled=cancelled)
        self.assertEqual(self.assets._paths, {})
        self.program.write_bytes(b"released")

    def test_hard_link_is_rejected_before_verification(self):
        os.link(self.program, self.root / "hard-link.exe")
        with patch.object(self.installation, "verify") as verify:
            with self.assertRaisesRegex(RuntimeInstallError, "multiply linked"):
                self.assets.protect_runtime()
            verify.assert_not_called()
        self.assertEqual(self.assets._paths, {})

    def test_symlink_is_rejected(self):
        link = self.root / "linked.exe"
        try:
            link.symlink_to(self.program)
        except OSError as exc:
            self.skipTest(f"Creating fixture symlinks is unavailable: {exc}")
        with self.assertRaises((RuntimeInstallError, OSError, ValueError)):
            ProtectedPath(link)

    def test_protected_cache_rechecks_without_rehashing_and_cannot_be_reused_after_close(self):
        with patch.object(self.installation, "verify", wraps=self.installation.verify) as verify:
            result = self.assets.protect_runtime()
            self.assertEqual(self.assets.protect_runtime(), result)
            self.assertEqual(self.assets.assert_runtime(str(self.program)), result)
            verify.assert_called_once()
        self.assets.close()
        with self.assertRaisesRegex(RuntimeInstallError, "protection ended"):
            self.assets.assert_runtime()

    def test_wrong_program_or_job_cannot_use_protected_runtime(self):
        self.assets.protect_runtime()
        with self.assertRaisesRegex(RuntimeInstallError, "selected executable"):
            self.assets.assert_runtime("other.exe")
        self.assets.bind_job("fixture-job")
        self.assets.bind_job("fixture-job")
        with self.assertRaisesRegex(RuntimeInstallError, "different runtime"):
            self.assets.bind_job("other-job")

    def test_model_manifest_and_shared_blobs_remain_protected_without_rehashing(self):
        models = self.install_model()
        self.assets.protect_runtime()
        with patch.object(models, "verify", wraps=models.verify) as verify:
            result = self.assets.protect_model(models, "fixture")
            self.assertEqual(self.assets.protect_model(models, "fixture"), result)
            verify.assert_called_once()
        paths = [models._manifest_path(models.entry("fixture")), *models.blobs.iterdir()]
        for path in paths:
            with self.subTest(path=path), self.assertRaises(PermissionError):
                path.write_bytes(b"changed")
        self.assets.close()
        for path in paths:
            path.write_bytes(b"released")

    def test_model_hash_failure_preserves_runtime_protection(self):
        models = self.install_model()
        self.assets.protect_runtime()
        original_paths = set(self.assets._paths)
        with patch.object(models, "verify", side_effect=RuntimeInstallError("bad model")):
            with self.assertRaisesRegex(RuntimeInstallError, "bad model"):
                self.assets.protect_model(models, "fixture")
        self.assertEqual(set(self.assets._paths), original_paths)
        with self.assertRaises(PermissionError):
            self.program.write_bytes(b"changed")
        models._manifest_path(models.entry("fixture")).write_bytes(b"released")

    def test_close_during_hash_is_nonblocking_and_cancels_then_releases(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def verify(*, cancelled, **kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("fixture release missing")
            if cancelled.is_set():
                raise RuntimeInstallError("cancelled fixture hash")
        def protect():
            try:
                self.assets.protect_runtime()
            except Exception as exc:
                errors.append(exc)
        with patch.object(self.installation, "verify", side_effect=verify):
            worker = threading.Thread(target=protect)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                started = time.monotonic()
                self.assets.close()
                self.assertLess(time.monotonic() - started, .5)
                with self.assertRaises(PermissionError):
                    self.program.write_bytes(b"still hashing")
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual([str(e) for e in errors], ["cancelled fixture hash"])
        self.assertEqual(self.assets._paths, {})
        self.program.write_bytes(b"released")


@unittest.skipUnless(os.name == "nt", "Windows owned process required")
class OwnedAssetLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ceta_desktop.owned_process import OwnedModelProcess
        self.process = OwnedModelProcess()
        self.assets = Mock()
        self.process.setManagedAssets(self.assets)
        self.addCleanup(self.process._timer.stop)

    def test_kill_and_unconfirmed_shutdown_keep_assets_until_zero_workers(self):
        from PySide6.QtCore import QProcess
        worker = self.process._process = Mock()
        worker.read.return_value = b""
        worker.poll.side_effect = [None, OSError("cannot query"), 0]
        worker.last_observation = {"active_processes": 0}
        self.process._state = QProcess.Running
        self.process.kill()
        self.process._poll()
        self.process._poll()
        self.assets.close.assert_not_called()
        with self.assertRaisesRegex(ValueError, "shutdown is confirmed"):
            self.process.releaseManagedAssets()
        self.process._poll()
        self.assertEqual(self.process.last_observation, {"active_processes": 0})
        self.assets.close.assert_called_once()
        self.assertIsNone(self.process.managed_assets)

    def test_failed_start_releases_assets(self):
        self.process.setEndpoint("127.0.0.1", 11435)
        with patch("ceta_desktop.owned_process.RuntimeLease", side_effect=OSError("fixture startup failure")):
            self.process.start()
        self.assets.close.assert_called_once()
        self.assertIn("fixture startup failure", self.process.errorString())

    def test_reassigning_same_unused_session_does_not_close_it(self):
        self.process.setManagedAssets(self.assets)
        self.assets.close.assert_not_called()
        self.process.releaseManagedAssets()
        self.assets.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
