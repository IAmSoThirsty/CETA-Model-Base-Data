from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.desktop_signing import (
    SigningConfig, authenticode_statuses, portable_executable_files, uninstaller_finalize,
)
from scripts.build_desktop import installer_script
sys.path.insert(0, str(ROOT / "src"))
from ceta_desktop.instance import MUTEX_NAME


class DesktopSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tool = self.root / "signtool.exe"
        self.tool.write_bytes(b"tool fixture; never executed")
        self.config = self.root / "publisher.json"
        self.data = {"signtool": str(self.tool), "certificate_thumbprint": "a" * 40,
                     "timestamp_url": "https://timestamp.example.invalid"}
        self.config.write_text(json.dumps(self.data))
        self.target = self.root / "application with spaces.exe"
        self.target.write_bytes(b"application fixture; never executed")

    def tearDown(self):
        self.temp.cleanup()

    def pe_file(self, path: Path) -> Path:
        """Create a header fixture, never an executable program."""
        path.parent.mkdir(parents=True, exist_ok=True)
        content = bytearray(256)
        content[:2] = b"MZ"
        content[60:64] = (128).to_bytes(4, "little")
        content[128:132] = b"PE\0\0"
        path.write_bytes(content)
        return path.resolve()

    def test_payload_detection_covers_extensions_and_renamed_pe_files(self):
        """Every PE is included, including one with a nonstandard extension."""
        payload = self.root / "payload"
        expected = [self.pe_file(payload / name) for name in (
            "CETA.exe", "runtime.dll", "nested/module.pyd", "nested/extension.bin",
        )]
        (payload / "readme.txt").write_text("Non-executable notices.")
        self.assertEqual(portable_executable_files(payload), sorted(expected))

    def test_payload_detection_rejects_missing_and_malformed_headers(self):
        """An executable filename or malformed DOS header cannot evade the gate."""
        payload = self.root / "payload"
        payload.mkdir()
        for content in (b"not a PE", b"MZ", b"MZ" + b"\0" * 254):
            (payload / "broken.dll").write_bytes(content)
            with self.subTest(content=content[:8]), self.assertRaisesRegex(ValueError, "PE header"):
                portable_executable_files(payload)

    def test_payload_detection_rejects_empty_payload_and_links(self):
        """An empty or externally linked payload cannot pass signing validation."""
        payload = self.root / "payload"
        payload.mkdir()
        with self.assertRaisesRegex(ValueError, "no PE files"):
            portable_executable_files(payload)
        self.pe_file(payload / "runtime.dll")
        with patch.object(Path, "is_junction", return_value=True):
            with self.assertRaisesRegex(ValueError, "Payload links"):
                portable_executable_files(payload)

    def test_windows_signature_query_uses_literal_paths_over_stdin(self):
        """Filename characters stay data instead of becoming shell source."""
        target = self.root / "library [1] $publisher.dll"
        response = [{"path": str(target), "status": "Valid"}]
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(response))
        with patch("scripts.desktop_signing.subprocess.run", return_value=result) as run:
            self.assertEqual(authenticode_statuses([target]), {str(target): "Valid"})
        args = run.call_args.args[0]
        self.assertNotIn(str(target), args[-1])
        self.assertIn("Get-AuthenticodeSignature -LiteralPath $path", args[-1])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), [str(target)])
        self.assertEqual(run.call_args.kwargs["env"]["PSModulePath"],
                         str(Path(args[0]).parent / "Modules"))
        self.assertTrue(run.call_args.kwargs["check"])

    @unittest.skipUnless(os.name == "nt", "Windows Authenticode integration")
    def test_real_windows_signature_query_reads_unsigned_file_without_execution(self):
        """Exercise the real PowerShell protocol without any signing credential."""
        target = self.root / "unsigned [1] $publisher.ps1"
        target.write_text("throw 'This fixture must never execute.'", encoding="utf-8")
        self.assertEqual(authenticode_statuses([target]), {str(target): "NotSigned"})

    def test_windows_signature_query_rejects_incomplete_or_duplicate_results(self):
        """Only complete, uniquely associated signature results are accepted."""
        paths = [self.root / "first.dll", self.root / "second.pyd"]
        first = {"path": str(paths[0]), "status": "Valid"}
        second = {"path": str(paths[1]), "status": "NotSigned"}
        for response in ([], [first], [first, first], [first, {**second, "status": None}],
                         [first, {**second, "path": "another-project.dll"}], first):
            result = subprocess.CompletedProcess([], 0, stdout=json.dumps(response))
            with self.subTest(response=response), patch(
                    "scripts.desktop_signing.subprocess.run", return_value=result):
                with self.assertRaisesRegex(ValueError, "payload signature statuses"):
                    authenticode_statuses(paths)

    def test_payload_signing_preserves_verified_vendor_files_and_covers_unsigned_pes(self):
        """Vendor files retain their bytes while all unsigned PEs reach the signer."""
        config = SigningConfig.read(self.config)
        payload = self.root / "payload"
        vendor = self.pe_file(payload / "vendor.dll")
        original = vendor.read_bytes()
        unsigned = [self.pe_file(payload / name) for name in (
            "CETA.exe", "runtime.dll", "nested/module.pyd", "nested/extension.bin",
        )]
        statuses = {str(path): "NotSigned" for path in unsigned}
        statuses[str(vendor)] = "Valid"
        with patch("scripts.desktop_signing.authenticode_statuses", return_value=statuses), \
                patch.object(SigningConfig, "verify") as verify, \
                patch.object(SigningConfig, "sign") as sign:
            self.assertEqual(config.sign_payload(payload), 5)
        verify.assert_called_once_with(vendor)
        self.assertEqual([call.args[0] for call in sign.call_args_list], sorted(unsigned))
        self.assertEqual(vendor.read_bytes(), original)

    def test_invalid_signature_blocks_payload_before_any_signing(self):
        """Never replace a broken or untrusted signature to make a release pass."""
        config = SigningConfig.read(self.config)
        payload = self.root / "payload"
        unsigned = self.pe_file(payload / "CETA.exe")
        vendor = self.pe_file(payload / "vendor.dll")
        for status in ("HashMismatch", "NotTrusted", "UnknownError", "NotSupported", ""):
            statuses = {str(unsigned): "NotSigned", str(vendor): status}
            with self.subTest(status=status), patch(
                    "scripts.desktop_signing.authenticode_statuses", return_value=statuses), \
                    patch.object(SigningConfig, "verify") as verify, \
                    patch.object(SigningConfig, "sign") as sign:
                with self.assertRaisesRegex(ValueError, "invalid signature"):
                    config.sign_payload(payload)
                verify.assert_not_called()
                sign.assert_not_called()

    def test_vendor_verification_failure_blocks_signing_without_replacing_signature(self):
        """An incomplete trust or timestamp check blocks all subsequent signing."""
        config = SigningConfig.read(self.config)
        payload = self.root / "payload"
        unsigned = self.pe_file(payload / "CETA.exe")
        vendor = self.pe_file(payload / "vendor.dll")
        statuses = {str(unsigned): "NotSigned", str(vendor): "Valid"}
        failure = subprocess.CalledProcessError(2, "missing timestamp fixture")
        with patch("scripts.desktop_signing.authenticode_statuses", return_value=statuses), \
                patch.object(SigningConfig, "verify", side_effect=failure), \
                patch.object(SigningConfig, "sign") as sign:
            with self.assertRaises(subprocess.CalledProcessError):
                config.sign_payload(payload)
            sign.assert_not_called()

    def test_payload_signing_propagates_publisher_failure(self):
        """A failed publisher operation cannot return a verified payload count."""
        config = SigningConfig.read(self.config)
        payload = self.root / "payload"
        target = self.pe_file(payload / "runtime.dll")
        statuses = {str(target): "NotSigned"}
        failure = subprocess.CalledProcessError(1, "fixture")
        with patch("scripts.desktop_signing.authenticode_statuses", return_value=statuses), \
                patch.object(SigningConfig, "sign", side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError):
                config.sign_payload(payload)

    def test_signing_uses_selected_certificate_then_verifies_trust_and_timestamp(self):
        config = SigningConfig.read(self.config)
        with patch("scripts.desktop_signing.subprocess.run") as run:
            config.sign(self.target)
            sign, verify = [call.args[0] for call in run.call_args_list]
            self.assertEqual(sign[sign.index("/sha1") + 1], "A" * 40)
            self.assertEqual(sign[sign.index("/fd") + 1], "SHA256")
            self.assertEqual(sign[sign.index("/td") + 1], "SHA256")
            self.assertEqual(sign[-1], str(self.target))
            self.assertEqual(verify[1:6], ["verify", "/pa", "/all", "/tw", "/v"])
            self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))

    def test_any_sign_or_verification_failure_blocks_the_build(self):
        config = SigningConfig.read(self.config)
        for failed_step in (0, 1):
            effects = [None] * failed_step + [subprocess.CalledProcessError(1, "signtool fixture")]
            with self.subTest(step=failed_step), patch("scripts.desktop_signing.subprocess.run", side_effect=effects) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    config.sign(self.target)
                self.assertEqual(run.call_count, failed_step + 1)

    def test_configuration_requires_explicit_valid_publisher_details(self):
        for field, value in (("signtool", "signtool.exe"), ("certificate_thumbprint", "choose automatically"),
                             ("timestamp_url", "http://timestamp.example.invalid"),
                             ("timestamp_url", "https://user:secret@example.invalid")):
            data = {**self.data, field: value}
            self.config.write_text(json.dumps(data))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                SigningConfig.read(self.config)

    def test_uninstaller_signing_is_checked_and_path_expansion_is_rejected(self):
        finalizer = uninstaller_finalize(self.config)
        self.assertTrue(finalizer.startswith("!uninstfinalize "))
        self.assertTrue(finalizer.endswith(" = 0"))
        self.assertIn("%1", finalizer)
        script = installer_script(self.root, self.root / "setup.exe", "0.3.0", finalizer)
        self.assertIn(finalizer, script)
        self.assertNotIn("!uninstfinalize", installer_script(self.root, self.root / "setup.exe", "0.3.0"))
        with self.assertRaises(ValueError):
            uninstaller_finalize(self.root / "%VARIABLE%" / "config.json")

    def test_installer_uses_ceta_identity_and_the_application_mutex(self):
        payload = self.root / "payload"
        payload.mkdir()
        (payload / "CETA.exe").write_bytes(b"executable fixture; never executed")
        script = installer_script(payload, self.root / "CETA-0.3.0-setup.exe", "0.3.0")
        self.assertIn('Name "CETA"', script)
        self.assertIn('InstallDir "$LOCALAPPDATA\\Programs\\CETA"', script)
        self.assertIn('CreateShortcut "$SMPROGRAMS\\CETA.lnk" "$INSTDIR\\CETA.exe"', script)
        self.assertEqual(script.count(f'w "{MUTEX_NAME}"'), 2)
        self.assertIn('Delete "$INSTDIR\\CETA.exe"', script)
        self.assertNotIn("RMDir /r", script)


if __name__ == "__main__":
    unittest.main()
