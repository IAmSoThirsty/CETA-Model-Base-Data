"""Real Windows DPAPI and CLI checks using disposable update-key fixtures."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from desktop_update_keys import (
    generate_protected_key, load_protected_key, public_key_text,
)
from ceta_desktop.updates import UpdateError, verify_manifest


@unittest.skipUnless(os.name == "nt", "Windows DPAPI integration")
class DesktopUpdateKeyTests(unittest.TestCase):
    """Exercise protected keys without creating publisher credentials."""

    def setUp(self):
        self.root = Path(self.enterContext(
            tempfile.TemporaryDirectory(prefix="ceta-test-update-key-")))
        self.path = self.root / "test-only.dpapi.json"

    def command(self, script, *args):
        """Run a real CLI; return captured output without displaying private bytes."""
        return subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / script),
                               *map(str, args)], capture_output=True, text=True, check=False,
                              timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)

    def test_protected_roundtrip_and_cli_manifest_verification(self):
        """A generated Windows key signs a manifest accepted by the actual updater."""
        generated = self.command("desktop_update_keys.py", "--output", self.path)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        metadata = json.loads(generated.stdout)
        self.assertEqual(set(metadata), {"product", "algorithm", "protection", "public_key"})
        key = load_protected_key(self.path)
        raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        self.assertEqual(metadata["public_key"], public_key_text(key))
        self.assertNotIn(raw, self.path.read_bytes())
        self.assertNotIn(base64.b64encode(raw).decode(), generated.stdout)
        self.assertNotIn(raw.hex(), generated.stdout)
        installer = self.root / "CETA-0.3.1-setup.exe"
        installer.write_bytes(b"fixture only; never executed")
        manifest = self.root / "manifest.json"
        signed = self.command(
            "sign_desktop_update.py", "--installer", installer, "--version", "0.3.1",
            "--url", "https://example.invalid/CETA-0.3.1-setup.exe",
            "--protected-private-key", self.path, "--output", manifest,
        )
        self.assertEqual(signed.returncode, 0, signed.stderr)
        envelope = json.loads(manifest.read_text())
        self.assertEqual(verify_manifest(envelope, metadata["public_key"], "0.3.0")["size"],
                         installer.stat().st_size)
        with self.assertRaises(UpdateError):
            verify_manifest(envelope, public_key_text(Ed25519PrivateKey.generate()), "0.3.0")
        self.assertNotIn(base64.b64encode(raw).decode(), signed.stdout + signed.stderr)
        self.assertEqual({p.name for p in self.root.iterdir()},
                         {self.path.name, installer.name, manifest.name})

    def test_refuses_overwrite_without_generating_or_replacing_key(self):
        """Existing key bytes survive direct and CLI attempts to replace them."""
        generate_protected_key(self.path)
        original = self.path.read_bytes()
        with patch("desktop_update_keys.Ed25519PrivateKey.generate") as generate:
            with self.assertRaises(FileExistsError):
                generate_protected_key(self.path)
            generate.assert_not_called()
        rejected = self.command("desktop_update_keys.py", "--output", self.path)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.path.read_bytes(), original)

    def test_refuses_repository_path_and_missing_parent_without_writes(self):
        """No fixture or actual private key is created inside the repository."""
        paths = (ROOT / "never-created-update-key.json",
                 ROOT / ".." / ROOT.name / "never-created-update-key.json",
                 self.root / "missing-directory" / "key.json")
        with patch("desktop_update_keys.Ed25519PrivateKey.generate") as generate:
            for path in paths:
                with self.subTest(path=str(path)), self.assertRaises(ValueError):
                    generate_protected_key(path)
            generate.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_rejects_tampered_ciphertext_and_mismatched_public_key(self):
        """Both DPAPI integrity and derived-public-key binding fail closed."""
        generate_protected_key(self.path)
        record = json.loads(self.path.read_text())
        altered = bytearray(base64.b64decode(record["protected_private_key"]))
        altered[-1] ^= 1
        cases = ({**record, "protected_private_key": base64.b64encode(altered).decode()},
                 {**record, "public_key": public_key_text(Ed25519PrivateKey.generate())})
        for data in cases:
            self.path.write_text(json.dumps(data))
            with self.subTest(public_key=data["public_key"]), self.assertRaises(ValueError):
                load_protected_key(self.path)

    def test_rejects_other_format_scope_and_malformed_encoding(self):
        """A different product, scope, schema, or key encoding is never admitted."""
        generate_protected_key(self.path)
        record = json.loads(self.path.read_text())
        cases = (
            ("schema_version", True), ("schema_version", "1"), ("schema_version", 1.0),
            ("product", "other"),
            ("algorithm", "RSA"), ("protection", "windows-dpapi-local-machine"),
            ("public_key", 1), ("public_key", "!!"), ("public_key", ""),
            ("protected_private_key", ""), ("protected_private_key", "!!"),
        )
        for field, value in cases:
            self.path.write_text(json.dumps({**record, field: value}))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                load_protected_key(self.path)
        for data in ("[]", "{}", "not json", '{"product":"CETA","product":"CETA"}',
                     " " * 65537):
            self.path.write_text(data)
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                load_protected_key(self.path)

    def test_decryption_failure_never_falls_back_to_another_key(self):
        """A lost or unavailable Windows identity blocks signing before output."""
        generate_protected_key(self.path)
        failure = ValueError("Windows DPAPI rejected the fixture identity.")
        with patch("desktop_update_keys._dpapi", side_effect=failure):
            with self.assertRaisesRegex(ValueError, "fixture identity"):
                load_protected_key(self.path)

    def test_rejects_non_ed25519_pem_without_creating_manifest(self):
        """The legacy PEM option still rejects a key for a different algorithm."""
        private = ec.generate_private_key(ec.SECP256R1())
        pem = self.root / "test-only.pem"
        pem.write_bytes(private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        installer = self.root / "CETA-0.3.1-setup.exe"
        installer.write_bytes(b"fixture")
        manifest = self.root / "manifest.json"
        rejected = self.command(
            "sign_desktop_update.py", "--installer", installer, "--version", "0.3.1",
            "--url", "https://example.invalid/CETA-0.3.1-setup.exe",
            "--private-key", pem, "--output", manifest,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("must be Ed25519", rejected.stderr)
        self.assertFalse(manifest.exists())

    def test_signer_module_entry_point_retains_pem_and_protected_options(self):
        """Both direct-script and Python module invocations resolve local helpers."""
        result = subprocess.run(
            [sys.executable, "-B", "-m", "scripts.sign_desktop_update", "--help"],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--private-key", result.stdout)
        self.assertIn("--protected-private-key", result.stdout)


if __name__ == "__main__":
    unittest.main()
