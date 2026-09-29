from __future__ import annotations

import copy
import hashlib
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request
import zipfile

from ceta_desktop.runtime_installation import (
    RuntimeInstallation, RuntimeInstallCancelled, RuntimeInstallError,
    _ReleaseRedirect, bundled_runtime, managed_environment, validate_runtime_spec,
)


def fixture_archive(root, members=None):
    members = members or {"ollama.exe": b"fixture executable", "lib/backend.dll": b"fixture library"}
    target = root / "runtime.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for name, content in members.items():
            archive.writestr(zipfile.ZipInfo(name), content)
    raw = target.read_bytes()
    spec = {"schema": "ceta.managed-runtime.v1", "backend": "ollama", "version": "1.2.3",
            "platform": "windows-x64", "entrypoint": "ollama.exe",
            "archive": {"url": "https://github.com/ollama/ollama/releases/download/v1.2.3/ollama-windows-amd64.zip",
                        "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            "files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in members.items()}, "license": {"notice": "Fixture only"}}
    return target, spec


class Response(io.BytesIO):
    def __init__(self, content, status=200, headers=None):
        super().__init__(content)
        self.status = status
        self.headers = headers if headers is not None else {"Content-Length": str(len(content))}


class RuntimeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source, self.spec = fixture_archive(self.root)
        self.installer = RuntimeInstallation(self.root / "data", self.spec)
        self.enterContext(patch("ceta_desktop.runtime_installation.require_supported_platform"))

    def test_bundled_catalog_pins_runtime_and_all_libraries(self):
        spec = bundled_runtime()
        self.assertEqual(spec["version"], "0.34.3")
        self.assertEqual(len(spec["files"]), 82)
        self.assertIn("lib/ollama/cuda_v12/ggml-cuda.dll", spec["files"])
        self.assertIn("lib/ollama/LLAMA_CPP_LICENSE", spec["files"])
        self.assertIn("MIT License", spec["license"]["notice"])
        self.assertEqual(spec["qualification"]["inference"], "not_tested")

    def test_managed_child_environment_is_private_and_contains_no_inherited_secrets(self):
        inherited = {"SystemRoot": "C:\\Windows", "Path": "unrelated-tools", "USERPROFILE": "original-profile",
                     "OLLAMA_MODELS": "original-models", "OPENAI_API_KEY": "secret", "CUDA_VISIBLE_DEVICES": "7"}
        original = dict(inherited)
        environment = managed_environment(self.root, self.root / "runtime/ollama.exe", inherited)
        self.assertEqual(inherited, original)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("CUDA_VISIBLE_DEVICES", environment)
        self.assertNotIn("Path", environment)
        self.assertEqual(environment["OLLAMA_HOST"], "127.0.0.1:11435")
        self.assertEqual(environment["OLLAMA_NO_CLOUD"], "1")
        self.assertTrue(Path(environment["OLLAMA_MODELS"]).is_relative_to(self.root))
        self.assertTrue(Path(environment["USERPROFILE"]).is_relative_to(self.root))

    def test_offline_import_is_content_pinned_and_never_runs_or_downloads(self):
        original = self.source.read_bytes()
        with patch("ceta_desktop.runtime_installation._open_release") as network:
            result = self.installer.acquire(source=self.source)
            network.assert_not_called()
        self.assertEqual(result["files_verified"], 2)
        self.assertEqual(result["inference"], "not_tested")
        self.assertEqual(Path(result["executable"]).read_bytes(), b"fixture executable")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.installer.verify()["archive_sha256"], self.spec["archive"]["sha256"])

    def test_import_does_not_overwrite_existing_install_or_unknown_data(self):
        result = self.installer.acquire(source=self.source)
        target = Path(result["executable"])
        target.write_bytes(b"modified executable")
        unknown = target.parent / "unknown.txt"
        unknown.write_text("keep")
        with self.assertRaises(RuntimeInstallError):
            self.installer.acquire(source=self.source)
        self.assertEqual(target.read_bytes(), b"modified executable")
        self.assertEqual(unknown.read_text(), "keep")

    def test_bad_archive_and_mutated_library_fail_closed(self):
        self.source.write_bytes(self.source.read_bytes()[:-1] + b"x")
        with self.assertRaisesRegex(RuntimeInstallError, "checksum"):
            self.installer.acquire(source=self.source)
        self.assertFalse(self.installer.destination.exists())
        self.source, _ = fixture_archive(self.root)
        self.installer.acquire(source=self.source)
        library = self.installer.destination / "lib/backend.dll"
        library.write_bytes(b"X" * library.stat().st_size)
        with self.assertRaisesRegex(RuntimeInstallError, "checksum"):
            self.installer.verify()

    def test_resume_rehashes_complete_archive_before_publication(self):
        raw = self.source.read_bytes()
        partial = self.installer.downloads / (self.spec["archive"]["sha256"] + ".part")
        partial.write_bytes(raw[:17])
        response = Response(raw[17:], 206, {"Content-Range": f"bytes 17-{len(raw)-1}/{len(raw)}",
                                           "Content-Length": str(len(raw)-17)})
        with patch("ceta_desktop.runtime_installation._open_release", return_value=response) as network:
            result = self.installer.acquire()
        self.assertEqual(network.call_args.args[1], 17)
        self.assertEqual(result["files_verified"], 2)
        self.assertEqual(partial.read_bytes(), raw)
        self.assertTrue(response.closed)

    def test_empty_partial_file_can_resume(self):
        partial = self.installer.downloads / (self.spec["archive"]["sha256"] + ".part")
        partial.touch()
        with patch("ceta_desktop.runtime_installation._open_release", return_value=Response(self.source.read_bytes())):
            self.assertEqual(self.installer.acquire()["files_verified"], 2)

    def test_interrupted_download_is_resumable_on_new_instance(self):
        raw = self.source.read_bytes()
        with patch("ceta_desktop.runtime_installation._open_release",
                   return_value=Response(raw[:20], headers={})):
            with self.assertRaisesRegex(RuntimeInstallError, "interrupted"):
                self.installer.acquire()
        resumed = RuntimeInstallation(self.root / "data", self.spec)
        response = Response(raw[20:], 206, {"Content-Range": f"bytes 20-{len(raw)-1}/{len(raw)}"})
        with patch("ceta_desktop.runtime_installation._open_release", return_value=response):
            self.assertEqual(resumed.acquire()["files_verified"], 2)

    def test_resume_rejects_wrong_range_or_full_restart_preserving_partial(self):
        raw = self.source.read_bytes()
        partial = self.installer.downloads / (self.spec["archive"]["sha256"] + ".part")
        partial.write_bytes(raw[:17])
        for response in (Response(raw), Response(raw[17:], 206, {"Content-Range": "bytes 0-1/2"})):
            with self.subTest(status=response.status), patch("ceta_desktop.runtime_installation._open_release", return_value=response):
                with self.assertRaises(RuntimeInstallError):
                    self.installer.acquire()
            self.assertEqual(partial.read_bytes(), raw[:17])

    def test_cancel_preserves_partial_and_never_publishes(self):
        cancelled = threading.Event()
        raw = self.source.read_bytes()
        def progress(_):
            cancelled.set()
        with patch("ceta_desktop.runtime_installation._open_release", return_value=Response(raw)):
            with self.assertRaises(RuntimeInstallCancelled):
                self.installer.acquire(cancelled=cancelled, progress=progress)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(self.installer.destination.exists())
        self.assertTrue(list(self.installer.downloads.glob("*.part")))
        self.assertEqual(self.installer.acquire()["files_verified"], 2)

    def test_catalog_change_does_not_resume_another_digest(self):
        old = self.installer.downloads / ("0" * 64 + ".part")
        old.write_bytes(b"unrelated")
        with patch("ceta_desktop.runtime_installation._open_release", return_value=Response(self.source.read_bytes())) as network:
            self.installer.acquire()
        self.assertEqual(network.call_args.args[1], 0)
        self.assertEqual(old.read_bytes(), b"unrelated")

    def test_wrong_download_length_encoding_and_checksum_never_publish(self):
        raw = self.source.read_bytes()
        cases = [Response(raw, headers={"Content-Length": "1"}),
                 Response(raw, headers={"Content-Encoding": "gzip"}), Response(b"X" * len(raw))]
        for response in cases:
            with self.subTest(headers=response.headers), patch("ceta_desktop.runtime_installation._open_release", return_value=response):
                with self.assertRaises(RuntimeInstallError):
                    self.installer.acquire()
            self.assertFalse(self.installer.destination.exists())

    def test_disk_and_concurrent_lease_checks_precede_network(self):
        with patch("ceta_desktop.runtime_installation.shutil.disk_usage", return_value=type("Disk", (), {"free": 0})()), \
                patch("ceta_desktop.runtime_installation._open_release") as network:
            with self.assertRaisesRegex(RuntimeInstallError, "disk space"):
                self.installer.acquire()
            network.assert_not_called()
        with self.installer._lease():
            other = RuntimeInstallation(self.root / "data", self.spec)
            with self.assertRaisesRegex(RuntimeInstallError, "Another CETA"):
                other.acquire(source=self.source)

    def test_offline_import_budgets_an_extra_copy_even_with_completed_download(self):
        partial = self.installer.downloads / (self.spec["archive"]["sha256"] + ".part")
        partial.write_bytes(self.source.read_bytes())
        space_without_copy = sum(row["size"] for row in self.spec["files"].values()) + 256 * 1024**2
        with patch("ceta_desktop.runtime_installation.shutil.disk_usage", return_value=type("Disk", (), {"free": space_without_copy})()):
            with self.assertRaisesRegex(RuntimeInstallError, "disk space"):
                self.installer.acquire(source=self.source)

    def test_archive_paths_collisions_and_missing_files_are_rejected(self):
        for name in ("../escape", "/absolute", "c:/absolute", "lib\\escape", "lib/CON.txt", "lib/file.", "lib//bad"):
            spec = copy.deepcopy(self.spec)
            spec["files"][name] = dict(spec["files"]["ollama.exe"])
            with self.subTest(name=name), self.assertRaises(RuntimeInstallError):
                RuntimeInstallation(self.root / "data", spec)
        spec = copy.deepcopy(self.spec)
        spec["files"]["OLLAMA.EXE"] = dict(spec["files"]["ollama.exe"])
        with self.assertRaises(RuntimeInstallError):
            validate_runtime_spec(spec)
        spec = copy.deepcopy(self.spec)
        spec["files"]["extra.dll"] = dict(spec["files"]["ollama.exe"])
        installer = RuntimeInstallation(self.root / "data", spec)
        with self.assertRaisesRegex(RuntimeInstallError, "missing pinned"):
            installer.acquire(source=self.source)
        self.assertFalse(installer.destination.exists())

    def test_extra_zip_members_and_symlinks_are_rejected_before_publication(self):
        with zipfile.ZipFile(self.source, "a") as archive:
            archive.writestr("../outside", b"bad")
        raw = self.source.read_bytes()
        self.spec["archive"].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        installer = RuntimeInstallation(self.root / "data", self.spec)
        with self.assertRaisesRegex(RuntimeInstallError, "Unsafe"):
            installer.acquire(source=self.source)
        self.assertFalse(installer.destination.exists())
        self.assertFalse((self.root / "outside").exists())

    def test_pinned_archive_symlink_cannot_be_extracted(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            link = zipfile.ZipInfo("ollama.exe")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            archive.writestr(link, b"fixture executable")
            archive.writestr("lib/backend.dll", b"fixture library")
        raw = self.source.read_bytes()
        self.spec["archive"].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        installer = RuntimeInstallation(self.root / "data", self.spec)
        with self.assertRaisesRegex(RuntimeInstallError, "unsupported member"):
            installer.acquire(source=self.source)
        self.assertFalse(installer.destination.exists())

    def test_installed_unknown_file_and_link_cannot_inherit_verification(self):
        self.installer.acquire(source=self.source)
        extra = self.installer.destination / "injected.dll"
        extra.write_bytes(b"unknown")
        with self.assertRaisesRegex(RuntimeInstallError, "Unexpected"):
            self.installer.verify()
        self.assertEqual(extra.read_bytes(), b"unknown")


class RuntimeRedirectTests(unittest.TestCase):
    def test_only_official_cdn_redirect_and_resume_header(self):
        original = "https://github.com/ollama/ollama/releases/download/v1.2.3/ollama-windows-amd64.zip"
        request = Request(original, headers={"Range": "bytes=17-", "Authorization": "do-not-forward"})
        handler = _ReleaseRedirect(original)
        target = handler.redirect_request(request, None, 302, None, {}, "https://release-assets.githubusercontent.com/release?temporary=token")
        self.assertEqual(target.get_header("Range"), "bytes=17-")
        self.assertIsNone(target.get_header("Authorization"))
        with self.assertRaises(RuntimeInstallError):
            handler.redirect_request(request, None, 302, None, {}, target.full_url)
        for url in ("http://release-assets.githubusercontent.com/a", "https://evil.example/a", "https://user@release-assets.githubusercontent.com/a"):
            with self.subTest(url=url), self.assertRaises(RuntimeInstallError):
                _ReleaseRedirect(original).redirect_request(request, None, 302, None, {}, url)


if __name__ == "__main__":
    unittest.main()
