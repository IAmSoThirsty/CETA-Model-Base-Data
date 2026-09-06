"""Native update handoff rejects changed files and retains Windows file locks."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ceta_desktop.installation import launch_verified_update
from ceta_desktop.updates import UpdateError


@unittest.skipUnless(os.name == "nt", "Windows file sharing and installer handoff")
class DesktopInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.installer = Path(self.temp.name) / "CETA-0.3.1-setup.exe"
        self.installer.write_bytes(b"fixture")
        self.manifest = {
            "schema_version": 1, "product": "CETA", "version": "0.3.1",
            "platform": "windows-x64", "url": "https://example.invalid/update.exe",
            "sha256": hashlib.sha256(b"fixture").hexdigest(), "size": 7,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_file_stays_locked_until_native_process_creation(self):
        self.assert_locked_handoff(self.installer)

    def test_short_directory_alias_resolves_before_locked_handoff(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        kernel.GetShortPathNameW.restype = ctypes.c_uint32
        directory = str(self.installer.parent.resolve(strict=True))
        required = kernel.GetShortPathNameW(directory, None, 0)
        if not required:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(required)
        written = kernel.GetShortPathNameW(directory, buffer, len(buffer))
        if not written or written >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        if buffer.value.casefold() == directory.casefold():
            self.skipTest("The temporary volume does not provide a distinct Windows short alias.")
        alias = Path(buffer.value) / self.installer.name
        self.assertTrue(alias.samefile(self.installer))
        self.assert_locked_handoff(alias)

    def assert_locked_handoff(self, installer):
        with patch("ceta_desktop.installation.subprocess.Popen") as start:
            process = start.return_value
            process.pid = 123

            def check_locked(*_args, **_kwargs):
                with self.assertRaises(PermissionError):
                    self.installer.write_bytes(b"changed")
                with self.assertRaises(PermissionError):
                    self.installer.unlink()
                return process

            start.side_effect = check_locked
            self.assertEqual(launch_verified_update(installer, self.manifest), 123)
            self.assertEqual(start.call_args.args[0],
                             [str(installer.resolve(strict=True)), f"/WAITPID={os.getpid()}"])
            self.assertFalse(start.call_args.kwargs.get("shell", False))
            self.assertTrue(start.call_args.kwargs["close_fds"])
        self.installer.write_bytes(b"released")

    def test_changed_or_missing_installer_never_starts(self):
        for data in (b"changed", b"truncated-data", None):
            with self.subTest(data=data):
                if data is None:
                    self.installer.unlink()
                else:
                    self.installer.write_bytes(data)
                with patch("ceta_desktop.installation.subprocess.Popen") as start:
                    with self.assertRaises((UpdateError, OSError)):
                        launch_verified_update(self.installer, self.manifest)
                    start.assert_not_called()

    def test_existing_writer_blocks_handoff(self):
        with self.installer.open("r+b"), patch("ceta_desktop.installation.subprocess.Popen") as start:
            with self.assertRaises(PermissionError):
                launch_verified_update(self.installer, self.manifest)
            start.assert_not_called()

    def test_launch_failure_releases_installer_handle(self):
        with patch("ceta_desktop.installation.subprocess.Popen", side_effect=OSError("launch failed")):
            with self.assertRaisesRegex(OSError, "launch failed"):
                launch_verified_update(self.installer, self.manifest)
        self.installer.write_bytes(b"released")

    def test_name_and_metadata_must_match_before_launch(self):
        with patch("ceta_desktop.installation.subprocess.Popen") as start:
            for field, value in (("version", "0.3.2"), ("product", "other")):
                with self.subTest(field=field), self.assertRaises(UpdateError):
                    launch_verified_update(self.installer, {**self.manifest, field: value})
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
