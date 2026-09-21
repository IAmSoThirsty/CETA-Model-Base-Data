from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from xml.etree import ElementTree as ET

from ceta_desktop.merger_self_test import verify_sandbox_fixture
from runtime.journal import Journal

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_desktop_sandbox", ROOT / "scripts" / "prepare_desktop_sandbox.py")
preparer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparer)


class DesktopSandboxPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installer = self.root / "current-installer.exe"
        self.installer.write_bytes(b"Synthetic inert installer fixture; never execute.")
        self.output = self.root / "validation"

    def test_network_disabled_payload_has_exact_hashes_and_no_user_data(self):
        source = self.installer.read_bytes()
        target = preparer.prepare(self.installer, self.output)
        self.assertEqual(self.installer.read_bytes(), source)
        self.assertEqual(target, self.output / "CETA-validation.wsb")
        config = ET.parse(target).getroot()
        self.assertEqual(config.findtext("Networking"), "Disable")
        self.assertEqual(config.findtext("ClipboardRedirection"), "Disable")
        folders = config.findall("MappedFolders/MappedFolder")
        self.assertEqual([(row.findtext("SandboxFolder"), row.findtext("ReadOnly")) for row in folders],
                         [("C:\\Payload", "true"), ("C:\\Results", "false")])
        manifest = json.loads((self.output / "payload" / "payload-manifest.json").read_text())
        self.assertTrue(manifest["synthetic"])
        self.assertIsNone(manifest["previous_installer"])
        for entry in manifest["files"]:
            self.assertEqual(hashlib.sha256((self.output / "payload" / entry["name"]).read_bytes()).hexdigest(), entry["sha256"])
        lifecycle = (self.output / "payload" / "validate-lifecycle.ps1").read_text()
        self.assertIn("'--smoke-test', '--merger-self-test', '--data-dir'", lifecycle)
        self.assertIn("$report.status -ne 'passed'", lifecycle)
        self.assertIn("$migration.backup_sha256 -ne $fixture.expected_backup_sha256", lifecycle)
        self.assertIn("Invoke-Probe 'restart' 1", lifecycle)
        self.assertIn("Invoke-Probe 'updated' 2", lifecycle)
        self.assertIn("Uninstall changed retained synthetic application data", lifecycle)
        self.assertNotIn("$LASTEXITCODE", lifecycle)

    def test_optional_previous_installer_is_explicit_and_bytes_are_preserved(self):
        previous = self.root / "CETA-Setup-0.3.3.exe"
        previous.write_bytes(b"Synthetic inert prior installer; never execute.")
        preparer.prepare(self.installer, self.output, previous)
        payload = self.output / "payload"
        self.assertEqual((payload / "previous-setup.exe").read_bytes(), previous.read_bytes())
        manifest = json.loads((payload / "payload-manifest.json").read_text())
        self.assertEqual(manifest["previous_installer"], previous.name)
        self.assertIn("'C:\\CETA-PreviousStartup'", preparer.LIFECYCLE_VALIDATION)
        self.assertIn('update_wait_timeout', preparer.LIFECYCLE_VALIDATION)
        self.assertIn('unrecognized_file_preserved', preparer.LIFECYCLE_VALIDATION)

    def test_existing_output_and_repository_output_are_refused_without_change(self):
        self.output.mkdir()
        unknown = self.output / "unknown.bin"
        unknown.write_bytes(bytes(range(16)))
        with self.assertRaisesRegex(ValueError, "new external"):
            preparer.prepare(self.installer, self.output)
        self.assertEqual(list(self.output.iterdir()), [unknown])
        self.assertEqual(unknown.read_bytes(), bytes(range(16)))
        with self.assertRaisesRegex(ValueError, "new external"):
            preparer.prepare(self.installer, ROOT / "new-sandbox-fixture-test")
        self.assertFalse((ROOT / "new-sandbox-fixture-test").exists())

    def test_generated_powershell_parses_without_executing_installers(self):
        if os.name != "nt":
            self.skipTest("Windows PowerShell parser unavailable on this OS")
        preparer.prepare(self.installer, self.output)
        shell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        for name in ("validate-lifecycle.ps1", "validate-update.ps1"):
            script_path = self.output / "payload" / name
            command = ("$parseTokens=$null; $parseErrors=$null; "
                       "[System.Management.Automation.Language.Parser]::ParseFile('"
                       + str(script_path).replace("'", "''")
                       + "',[ref]$parseTokens,[ref]$parseErrors) | Out-Null; "
                       "if($parseErrors.Count){$parseErrors | ForEach-Object {$_.Message}; exit 1}")
            result = subprocess.run([str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DesktopSandboxMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        payload = self.root / "payload"
        payload.mkdir()
        self.fixture = preparer.create_synthetic_fixture(payload)
        self.data = self.root / "data"
        self.data.mkdir()
        shutil.copyfile(payload / "schema1-fixture.sqlite3", self.data / "desktop.sqlite3")
        shutil.copyfile(payload / "sandbox-fixture.json", self.data / "sandbox-fixture.json")
        self.journal = Journal(self.data / "desktop.sqlite3")
        self.addCleanup(lambda: self.journal.close())

    def test_real_synthetic_migration_backup_and_unknown_rows_are_verified(self):
        report = verify_sandbox_fixture(self.data, self.journal)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["backup_sha256"], self.fixture["expected_backup_sha256"])
        self.assertNotEqual(self.fixture["source_sha256"], report["backup_sha256"])
        self.assertEqual(report["schema_after"], 2)
        self.assertEqual(report["backup_schema"], 1)
        self.assertTrue(report["unknown_rows_preserved"])
        self.assertTrue(report["legacy_rows_preserved"])
        print("SYNTHETIC_SANDBOX_MIGRATION_EVIDENCE " + json.dumps({
            "source_sha256": self.fixture["source_sha256"], "backup_sha256": report["backup_sha256"],
            "schema_before": 1, "schema_after": 2, "user_data": False}))

    def test_second_executable_report_checks_retained_project_checkpoints(self):
        self.journal.register_project("application", None)
        self.journal.append("application", "task.created", {"objective": "synthetic first launch"}, task_id="first-task")
        report = {"status": "passed", "migration": verify_sandbox_fixture(self.data, self.journal)}
        (self.data / "merger-self-test-first.json").write_text(json.dumps(report), encoding="utf-8")
        self.journal.close()
        self.journal = Journal(self.data / "desktop.sqlite3")
        restarted = verify_sandbox_fixture(self.data, self.journal)
        self.assertEqual(restarted["prior_successful_launches_verified"], 1)
        self.assertEqual(self.journal.task("first-task")["objective"], "synthetic first launch")
        report["migration"]["project_checkpoints"][0]["head"] = "0" * 64
        (self.data / "merger-self-test-first.json").write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "lost or rewrote"):
            verify_sandbox_fixture(self.data, self.journal)

    def test_unknown_row_tampering_fails_the_packaged_gate(self):
        self.journal.db.execute("UPDATE unknown_user_data SET data=X'FFFF' WHERE name='retain'")
        with self.assertRaisesRegex(RuntimeError, "unknown rows changed"):
            verify_sandbox_fixture(self.data, self.journal)

    def test_legacy_transcript_tampering_fails_the_packaged_gate(self):
        self.journal.db.execute("UPDATE messages SET content='changed' WHERE sequence=1")
        with self.assertRaisesRegex(RuntimeError, "legacy or unknown rows changed"):
            verify_sandbox_fixture(self.data, self.journal)

    def test_backup_tampering_fails_before_a_pass_report(self):
        backup = Path(self.journal.migration_backup["path"])
        with backup.open("ab") as handle:
            handle.write(b"corrupt synthetic backup")
        with self.assertRaisesRegex(RuntimeError, "backup differs"):
            verify_sandbox_fixture(self.data, self.journal)

    def test_marker_is_optional_for_normal_explicit_selftest(self):
        self.assertEqual(verify_sandbox_fixture(self.root / "no-marker", self.journal), {"status": "not_requested"})


if __name__ == "__main__":
    unittest.main()
