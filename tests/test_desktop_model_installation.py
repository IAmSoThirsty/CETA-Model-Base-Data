from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request
import zipfile

from ceta_desktop.hardware import GIB, HardwareProfile
from ceta_desktop.model_installation import (
    ManagedModels, ModelInstallError, _BlobRedirect, bundled_models, model_layers,
    model_name, recommended_entry, validate_model_catalog,
)
from ceta_desktop.runtime_installation import RuntimeInstallCancelled, asset_lock
from test_desktop_runtime_installation import Response


def model_fixture():
    contents = [b'{"model_format":"gguf"}', b"fixture model bytes", b"fixture license", b"fixture template"]
    kinds = ["application/vnd.docker.container.image.v1+json", "application/vnd.ollama.image.model",
             "application/vnd.ollama.image.license", "application/vnd.ollama.image.template"]
    layers = [{"mediaType": kind, "digest": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data)}
              for kind, data in zip(kinds, contents)]
    raw = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                      "config": layers[0], "layers": layers[1:]}, separators=(",", ":"))
    entry = {"id": "fixture", "label": "Fixture model", "description": "Synthetic test fixture",
             "repository": "library/qwen3", "runtime_version": "0.34.3", "manifest": raw,
             "sha256": hashlib.sha256(raw.encode()).hexdigest()}
    catalog = {"schema": "ceta.managed-model-catalog.v1", "entries": [entry],
               "licenses": {layers[2]["digest"]: contents[2].decode()},
               "registry_blob_redirect_hosts": ["0" * 32 + ".r2.cloudflarestorage.com"]}
    return catalog, {layer["digest"]: data for layer, data in zip(layers, contents)}


class ModelInstallationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.catalog, self.content = model_fixture()
        self.entry = self.catalog["entries"][0]
        self.installer = ManagedModels(self.root / "data", self.catalog)

    def response(self, entry, layer, hosts, offset):
        raw = self.content[layer["digest"]]
        return Response(raw[offset:], 206 if offset else 200,
                        {"Content-Range": f"bytes {offset}-{len(raw)-1}/{len(raw)}", "Content-Length": str(len(raw)-offset)})

    def install(self):
        with patch("ceta_desktop.model_installation._open_blob", side_effect=self.response):
            return self.installer.acquire("fixture")

    def test_official_catalog_pins_licenses_and_balanced_candidate_is_not_largest(self):
        catalog = bundled_models()
        self.assertEqual(len(catalog["entries"]), 6)
        profile = HardwareProfile(128*GIB, 100*GIB, 32)
        self.assertEqual(recommended_entry(catalog["entries"], profile)["id"], "qwen3-4b")
        self.assertIsNone(recommended_entry(catalog["entries"], HardwareProfile(None, None, 2)))
        self.assertEqual(recommended_entry(catalog["entries"], HardwareProfile(4*GIB, 3*GIB, 4))["id"], "qwen3-06b")

    def test_manifest_published_last_and_download_never_uses_mutable_tag(self):
        def inspect(entry, layer, hosts, offset):
            self.assertFalse(self.installer._manifest_path(entry).exists())
            return self.response(entry, layer, hosts, offset)
        with patch("ceta_desktop.model_installation._open_blob", side_effect=inspect) as network:
            result = self.installer.acquire("fixture")
        self.assertEqual(network.call_count, 4)
        self.assertEqual(result["inference"], "not_tested")
        self.assertEqual(result["model"], model_name(self.entry))
        self.assertEqual(self.installer._manifest_path(self.entry).read_text(), self.entry["manifest"])
        self.assertEqual(self.installer.verify("fixture")["sha256"], self.entry["sha256"])

    def test_export_import_roundtrip_is_offline_and_reverifies_content(self):
        self.install()
        destination = self.root / "offline.zip"
        self.installer.export("fixture", destination)
        target = ManagedModels(self.root / "other", self.catalog)
        with patch("ceta_desktop.model_installation._open_blob") as network:
            result = target.acquire("fixture", source=destination)
            network.assert_not_called()
        self.assertEqual(result["files_verified"], 4)
        with self.assertRaises(FileExistsError):
            self.installer.export("fixture", destination)

    def test_corrupt_download_never_publishes_model_and_preserves_failed_bytes(self):
        def corrupt(entry, layer, hosts, offset):
            raw = self.content[layer["digest"]]
            return Response(b"X" * len(raw))
        with patch("ceta_desktop.model_installation._open_blob", side_effect=corrupt):
            with self.assertRaisesRegex(ModelInstallError, "checksum"):
                self.installer.acquire("fixture")
        self.assertFalse(self.installer._manifest_path(self.entry).exists())
        self.assertTrue(list(self.installer.downloads.glob("*.part")))

    def test_interruption_resumes_exact_blob_on_new_instance(self):
        first = model_layers(self.entry)[0]
        partial = self.installer.downloads / (first["digest"][7:] + ".part")
        partial.write_bytes(self.content[first["digest"]][:3])
        with patch("ceta_desktop.model_installation._open_blob", side_effect=self.response) as network:
            result = ManagedModels(self.root / "data", self.catalog).acquire("fixture")
        self.assertEqual(network.call_args_list[0].args[-1], 3)
        self.assertEqual(result["files_verified"], 4)

    def test_resume_disk_budget_uses_remaining_bytes(self):
        missing = 0
        for layer in model_layers(self.entry):
            raw = self.content[layer["digest"]]
            (self.installer.downloads / (layer["digest"][7:] + ".part")).write_bytes(raw[:-1])
            missing += 1
        available = missing + 128*1024**2
        with patch("ceta_desktop.model_installation.shutil.disk_usage", return_value=type("Disk", (), {"free": available})()), \
                patch("ceta_desktop.model_installation._open_blob", side_effect=self.response):
            self.assertEqual(self.installer.acquire("fixture")["files_verified"], 4)

    def test_pause_keeps_caller_event_and_does_not_publish(self):
        event = threading.Event()
        with patch("ceta_desktop.model_installation._open_blob", side_effect=self.response):
            with self.assertRaises(RuntimeInstallCancelled):
                self.installer.acquire("fixture", cancelled=event, progress=lambda _: event.set())
        self.assertTrue(event.is_set())
        self.assertFalse(self.installer._manifest_path(self.entry).exists())
        self.install()

    def test_changed_installed_blob_or_manifest_is_not_repaired_silently(self):
        self.install()
        manifest = self.installer._manifest_path(self.entry)
        manifest.write_text("changed")
        with self.assertRaisesRegex(ModelInstallError, "manifest"):
            self.installer.verify("fixture")
        self.assertEqual(manifest.read_text(), "changed")
        layer = model_layers(self.entry)[0]
        blob = self.installer.blobs / layer["digest"].replace(":", "-")
        blob.write_bytes(b"X" * layer["size"])
        with self.assertRaisesRegex(ModelInstallError, "checksum"):
            self.installer.acquire("fixture")
        self.assertEqual(blob.read_bytes(), b"X" * layer["size"])

    def test_unknown_files_survive_and_other_process_lock_blocks_writes(self):
        extra = self.installer.blobs / "user-file"
        extra.write_text("preserve")
        with asset_lock(self.installer.root):
            with self.assertRaisesRegex(ValueError, "Another CETA"):
                self.installer.acquire("fixture")
        self.install()
        self.assertEqual(extra.read_text(), "preserve")

    def test_wrong_range_or_registry_failure_does_not_append(self):
        layer = model_layers(self.entry)[0]
        partial = self.installer.downloads / (layer["digest"][7:] + ".part")
        partial.write_bytes(b"{")
        with patch("ceta_desktop.model_installation._open_blob", return_value=Response(self.content[layer["digest"]])):
            with self.assertRaisesRegex(ModelInstallError, "range"):
                self.installer.acquire("fixture")
        self.assertEqual(partial.read_bytes(), b"{")

    def test_catalog_tamper_foreign_source_or_missing_license_is_rejected(self):
        for mutate in (lambda c: c["entries"][0].update(manifest="{}"),
                       lambda c: c["entries"][0].update(repository="other/project"),
                       lambda c: c.update(licenses={}),
                       lambda c: c["entries"].append(c["entries"][0])):
            catalog = copy.deepcopy(self.catalog)
            mutate(catalog)
            with self.assertRaises(ModelInstallError):
                validate_model_catalog(catalog)

    def test_malicious_or_different_model_zip_is_rejected_without_network(self):
        self.install()
        archive = self.root / "bad.zip"
        self.installer.export("fixture", archive)
        with zipfile.ZipFile(archive, "a") as writer:
            writer.writestr("../escape", b"no")
        target = ManagedModels(self.root / "other", self.catalog)
        with patch("ceta_desktop.model_installation._open_blob") as network:
            with self.assertRaises(ModelInstallError):
                target.acquire("fixture", source=archive)
            network.assert_not_called()
        self.assertFalse((self.root / "escape").exists())
        self.assertFalse(target._manifest_path(self.entry).exists())

    def test_archive_directory_allocation_is_bounded_before_zip_parser(self):
        archive = self.root / "oversized.zip"
        archive.write_bytes(b"padding" + struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 1, 1, 1000000000, 0, 0))
        with patch("ceta_desktop.model_installation.zipfile.ZipFile") as parser:
            with self.assertRaisesRegex(ModelInstallError, "bounds"):
                self.installer.acquire("fixture", source=archive)
            parser.assert_not_called()


class ModelRedirectTests(unittest.TestCase):
    def test_exact_approved_host_and_blob_path_only_preserve_range(self):
        digest = "1" * 64
        original = "https://registry.ollama.ai/v2/library/qwen3/blobs/sha256:" + digest
        host = "0" * 32 + ".r2.cloudflarestorage.com"
        url = f"https://{host}/ollama/docker/registry/v2/blobs/sha256/11/{digest}/data?signature=temporary"
        request = Request(original, headers={"Range": "bytes=3-", "Authorization": "never-forward"})
        handler = _BlobRedirect(original, digest, [host])
        target = handler.redirect_request(request, None, 307, None, {}, url)
        self.assertEqual(target.get_header("Range"), "bytes=3-")
        self.assertIsNone(target.get_header("Authorization"))
        for bad in (url.replace(host, "other.example"), url.replace("/11/", "/22/"), url.replace("https:", "http:")):
            with self.subTest(url=bad), self.assertRaises(ModelInstallError):
                _BlobRedirect(original, digest, [host]).redirect_request(request, None, 307, None, {}, bad)


if __name__ == "__main__":
    unittest.main()
