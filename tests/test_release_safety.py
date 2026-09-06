from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_package_manifest, build_release, build_release_zip, verify_package


class ReleaseSafetyTests(unittest.TestCase):
    def test_worktree_git_marker_is_excluded_without_modifying_it(self):
        """A Git worktree marker is metadata, just like a normal .git directory."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / ".git"
            marker_bytes = b"gitdir: ../protected-repository/.git/worktrees/release\n"
            marker.write_bytes(marker_bytes)
            payload = root / "payload.txt"
            payload.write_text("public", encoding="utf-8")
            with patch.object(verify_package, "ROOT", root):
                self.assertEqual(verify_package.visible_files(), {"payload.txt"})
            with patch.object(build_package_manifest, "ROOT", root):
                self.assertEqual(list(build_package_manifest.candidate_files()), [payload])
            with self.assertRaises(ValueError):
                verify_package.safe_package_path(root, ".git")
            self.assertEqual(marker.read_bytes(), marker_bytes)

    def test_rejects_escaping_excluded_and_noncanonical_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "../private", "/private", "C:/private", "data\\private", "./file",
                "data//file", "data/../private", "data/ceta_controlled_evaluation/key.json",
                "data/ceta_curriculum_v3/source_adjudications.jsonl", ".venv/secret",
                ".codacy/codacy.config.json", ".codacy/generated/tool-settings.json",
            ):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    verify_package.safe_package_path(root, name)

    def test_only_registered_files_enter_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payload.txt").write_text("public")
            (root / "unregistered.txt").write_text("private")
            (root / "SHA256SUMS").write_text("")
            (root / "PACKAGE_MANIFEST.json").write_text(json.dumps({"files": [{"path": "payload.txt"}]}))
            paths = build_release_zip.registered_paths(root)
            self.assertEqual([p.name for p in paths], ["PACKAGE_MANIFEST.json", "SHA256SUMS", "payload.txt"])

    def test_legacy_cleanup_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / ".venv" / "__pycache__"
            cache.mkdir(parents=True)
            sentinel = cache / "owned.pyc"
            sentinel.write_bytes(b"preserve")
            with patch.object(build_release, "ROOT", root):
                build_release.remove_transient()
            self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_output_collision_rejected_before_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release.zip"
            output.write_bytes(b"existing")
            with patch.object(sys, "argv", ["build_release", "--output", str(output)]), \
                    patch.object(build_release.subprocess, "run") as run, self.assertRaises(SystemExit):
                build_release.main()
            run.assert_not_called()
            self.assertEqual(output.read_bytes(), b"existing")

    def test_checksum_collision_rejected_before_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release.zip"
            sidecar = output.with_suffix(".zip.sha256")
            sidecar.write_text("existing")
            with patch.object(sys, "argv", ["build_release", "--output", str(output)]), \
                    patch.object(build_release.subprocess, "run") as run, self.assertRaises(SystemExit):
                build_release.main()
            run.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
