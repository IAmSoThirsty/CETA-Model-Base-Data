"""Exercise personal CETA verification with disposable, deterministic key fixtures."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from create_desktop_verification import (
    IDENTITY, checked_path, create_bundle, public_fingerprint, verify_bundle,
)


class DesktopVerificationTests(unittest.TestCase):

    """No test creates publisher credentials or executes an installer."""

    def setUp(self):
        self.root = Path(self.enterContext(
            tempfile.TemporaryDirectory(prefix="ceta-verification-")))
        self.key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        raw = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.public = base64.b64encode(raw).decode("ascii")
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        self.installer = self.root / "CETA-0.3.1-setup.exe"
        self.installer.write_bytes(b"CETA test-only installer fixture; never execute.")
        manifest = {
            "schema_version": 1, "product": "CETA", "version": "0.3.1",
            "platform": "windows-x64",
            "url": IDENTITY["repository"] + "/releases/download/v0.3.1/" + self.installer.name,
            "sha256": hashlib.sha256(self.installer.read_bytes()).hexdigest(),
            "size": self.installer.stat().st_size,
        }
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True).encode("utf-8")
        signature = base64.b64encode(self.key.sign(b"CETA/UPDATE/v1\n" + canonical)).decode()
        self.envelope = {"manifest": manifest, "signature": signature}
        self.manifest = self.root / "signed-update.json"
        self.original = (json.dumps(self.envelope, indent=3) + "\r\n").encode("utf-8")
        self.manifest.write_bytes(self.original)
        self.output = self.root / "verification"

    def create(self, output=None):
        """Build verification material from the existing signed fixture."""
        return create_bundle(self.manifest, self.public, self.installer, output or self.output)

    def run_verifier(self, fingerprint=None):
        """Run the emitted standalone source as a recipient would, offline."""
        return subprocess.run(
            [sys.executable, "-B", str(self.output / "verify_ceta.py"),
             "--installer", str(self.installer),
             "--trusted-fingerprint", fingerprint or self.fingerprint],
            capture_output=True, text=True, check=False, timeout=30,
        )

    def test_bundle_preserves_signed_bytes_and_uses_exact_public_identity(self):
        """Personal identity and fingerprint bind an unchanged signed release."""
        result = self.create()
        self.assertEqual((self.output / "CETA-UPDATE.json").read_bytes(), self.original)
        self.assertEqual(self.manifest.read_bytes(), self.original)
        publisher = json.loads((self.output / "CETA-PUBLISHER.json").read_text())
        self.assertEqual(publisher, {**IDENTITY, "public_key": self.public,
                                     "public_key_sha256": self.fingerprint})
        self.assertEqual(result["public_key_sha256"], self.fingerprint)
        self.assertEqual(verify_bundle(self.output, self.installer, self.fingerprint),
                         self.envelope["manifest"])
        readme = (self.output / "README.txt").read_text()
        self.assertIn(self.envelope["manifest"]["sha256"], readme)
        command = "Get-FileHash -LiteralPath '.\\CETA-0.3.1-setup.exe' -Algorithm SHA256"
        self.assertIn(command, readme)
        self.assertIn("Receive the public-key fingerprint independently", readme)
        self.assertIn("does not provide Windows CA", readme)
        self.assertEqual((self.output / "requirements.txt").read_text(), "cryptography>=42\n")

    def test_zip_is_deterministic_and_has_only_fixed_public_members(self):
        """Archive bytes depend on verified contents, never local build paths or time."""
        first = Path(self.create()["archive"])
        second = Path(self.create(self.root / "second-bundle")["archive"])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), [
                "CETA-PUBLISHER.json", "CETA-UPDATE.json", "README.txt",
                "requirements.txt", "verify_ceta.py",
            ])
            for item in archive.infolist():
                self.assertEqual(archive.read(item.filename),
                                 (self.output / item.filename).read_bytes())
                self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))

    def test_standalone_verifier_succeeds_and_requires_independently_trusted_fingerprint(self):
        """The real standalone CLI verifies a fixture and rejects another fingerprint."""
        self.create()
        good = self.run_verifier()
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn("VERIFIED: CETA 0.3.1", good.stdout)
        bad = self.run_verifier("0" * 64)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("independently received fingerprint", bad.stderr)

    def test_bundle_creation_cli_accepts_only_public_release_inputs(self):
        """The public CLI produces a bundle that its emitted verifier accepts."""
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/create_desktop_verification.py"),
             "--manifest", str(self.manifest), "--public-key", self.public,
             "--installer", str(self.installer), "--output", str(self.output)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["public_key_sha256"], self.fingerprint)
        self.assertEqual(self.run_verifier().returncode, 0)

    def test_changed_installer_or_manifest_is_rejected_by_standalone_verifier(self):
        """Recipient checks fail after same-size byte changes or altered signed metadata."""
        self.create()
        original_installer = self.installer.read_bytes()
        self.installer.write_bytes(b"X" + original_installer[1:])
        rejected = self.run_verifier()
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("signed size and SHA-256", rejected.stderr)
        self.installer.write_bytes(original_installer)
        altered = {**self.envelope, "manifest": {**self.envelope["manifest"], "version": "0.3.2"}}
        (self.output / "CETA-UPDATE.json").write_text(json.dumps(altered))
        rejected = self.run_verifier()
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("signature does not match", rejected.stderr)

    def test_publisher_substitution_and_false_identity_are_rejected(self):
        """Neither another key nor misleading project metadata inherits user trust."""
        self.create()
        path = self.output / "CETA-PUBLISHER.json"
        original = json.loads(path.read_text())
        other = Ed25519PrivateKey.from_private_bytes(b"x" * 32).public_key()
        public = base64.b64encode(other.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        cases = (
            {**original, "publisher": "someone-else"},
            {**original, "website": "https://example.invalid/ceta"},
            {**original, "schema_version": True},
            {**original, "public_key": public, "public_key_sha256": public_fingerprint(public)},
        )
        for altered in cases:
            path.write_text(json.dumps(altered))
            with self.subTest(changed=altered), self.assertRaises(ValueError):
                verify_bundle(self.output, self.installer, self.fingerprint)

    def test_invalid_signature_key_or_installer_creates_no_output(self):
        """Validate release binding before creating any bundle directory."""
        for field, value in (("signature", "AAAA"), ("manifest", {})):
            self.manifest.write_text(json.dumps({**self.envelope, field: value}))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.create()
            self.assertFalse(self.output.exists())
        self.manifest.write_bytes(self.original)
        with self.assertRaises(ValueError):
            create_bundle(self.manifest, base64.b64encode(b"x" * 32).decode(),
                          self.installer, self.output)
        self.assertFalse(self.output.exists())
        self.installer.write_bytes(b"Changed installer")
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse(self.output.exists())

    def test_refuses_overwrite_traversal_and_symlink_paths(self):
        """Existing outputs survive and filesystem aliases cannot cross boundaries."""
        self.output.mkdir()
        sentinel = self.output / "user-note.txt"
        sentinel.write_text("Keep this existing work.")
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(sentinel.read_text(), "Keep this existing work.")
        with self.assertRaisesRegex(ValueError, "traversal"):
            self.create(self.root / "nested" / ".." / "redirected")
        with self.assertRaisesRegex(ValueError, "existing parent"):
            self.create(self.root / "missing" / "child")
        link = SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        with patch.object(Path, "lstat", return_value=link):
            with self.assertRaisesRegex(ValueError, "Symlinks"):
                checked_path(self.manifest)
        junction = SimpleNamespace(st_mode=stat.S_IFDIR,
                                   st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with patch.object(Path, "lstat", return_value=junction):
            with self.assertRaisesRegex(ValueError, "reparse points"):
                checked_path(self.output)

    def test_duplicate_json_fields_and_version_filename_mismatch_fail_closed(self):
        """Ambiguous metadata and a differently named executable are never packaged."""
        self.manifest.write_bytes(self.original.replace(
            b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1', 1))
        with self.assertRaisesRegex(ValueError, "Duplicate field"):
            self.create()
        self.assertFalse(self.output.exists())
        self.manifest.write_bytes(self.original)
        different = self.root / "CETA-0.3.2-setup.exe"
        different.write_bytes(self.installer.read_bytes())
        with self.assertRaisesRegex(ValueError, "filename"):
            create_bundle(self.manifest, self.public, different, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
