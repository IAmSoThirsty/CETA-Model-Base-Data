"""Daily-use authorization and preserved startup recovery regressions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from runtime.journal import Journal
from runtime.tasks import TaskRuntime
from runtime.runtime_keys import runtime_keys


class RuntimeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ceta-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / "data"
        self.root = self.base / "project"
        self.root.mkdir()
        (self.root / "example.txt").write_text("before", encoding="utf-8")
        self.runtime = TaskRuntime(self.data)
        self.addCleanup(self.runtime.close)
        self.project = self.runtime.open_project(self.root)["project_id"]
        self.task = self.runtime.start_task(self.project, "Continue this project")["task_id"]
        self.grant = self.events("task.grant")[-1]["payload"]

    def events(self, kind):
        return self.runtime.journal.events(self.project, kind=kind, task_id=self.task)

    def test_expiry_inspection_does_not_renew_and_explicit_renewal_preserves_history(self):
        history = self.runtime.timeline(self.task)
        with patch("runtime.tasks._now", return_value=self.grant["expires_at_epoch_ms"] + 1):
            self.assertEqual(self.runtime.task_access_status(self.task)["status"], "expired")
            self.assertEqual(self.runtime.timeline(self.task), history)
            with self.assertRaises(ValueError):
                self.runtime.read(self.task, "example.txt")
            renewed = self.runtime.renew_task_grant(self.task)
            self.assertEqual(renewed["task_id"], self.task)
            self.assertEqual(self.runtime.task_access_status(self.task)["status"], "active")
            self.assertEqual(self.runtime.read(self.task, "example.txt")["text"], "before")
        self.assertEqual(self.runtime.timeline(self.task)[:len(history)], history)
        self.assertEqual(len(self.events("task.grant")), 2)
        self.assertEqual(self.events("task.grant.renewed")[-1]["payload"]["previous_grant_id"], self.grant["assertion_id"])

    def test_revoked_task_needs_distinct_reauthorization(self):
        self.runtime.revoke_task(self.task)
        self.assertEqual(self.runtime.task_access_status(self.task)["status"], "revoked")
        for action in (lambda: self.runtime.renew_task_grant(self.task),
                       lambda: self.runtime.start_task(self.project, "Continue this project", self.task)):
            with self.assertRaisesRegex(ValueError, "reauthoriz"):
                action()
        self.runtime.reauthorize_task(self.task)
        self.assertEqual(self.runtime.task_access_status(self.task)["status"], "active")
        self.assertEqual(len(self.events("task.grant.revoked")), 1)
        self.assertEqual(len(self.events("task.grant.reauthorized")), 1)

    def test_model_actor_cannot_renew_or_reauthorize(self):
        for action in (self.runtime.renew_task_grant, self.runtime.reauthorize_task):
            with self.assertRaisesRegex(ValueError, "user"):
                action(self.task, actor_id="model")
        self.assertEqual(len(self.events("task.grant")), 1)

    def test_clock_rollback_is_not_expiry(self):
        with patch("runtime.tasks._now", return_value=self.grant["issued_at_epoch_ms"] - 1):
            self.assertEqual(self.runtime.task_access_status(self.task)["status"], "not_yet_valid")
            with self.assertRaises(ValueError):
                self.runtime.renew_task_grant(self.task)

    def test_renewal_invalidates_prepared_edit(self):
        proposal = self.runtime.propose_edit(self.task, "example.txt", "after")
        with patch("runtime.tasks._now", return_value=self.grant["expires_at_epoch_ms"] + 1):
            self.runtime.renew_task_grant(self.task)
            with self.assertRaises(ValueError):
                self.runtime.apply_edit(self.task, proposal["proposal_id"])
        self.assertEqual((self.root / "example.txt").read_text(), "before")

    def test_acknowledgment_cannot_clear_uncertain_effect_even_in_another_task(self):
        self.runtime.journal.append(self.project, "operation.intent",
            {"action_id": "unknown-command", "kind": "command"}, task_id=self.task)
        self.runtime.recover_interrupted()
        observed = self.runtime.record_reconciliation(self.task, "unknown-command", note="I saw the interruption")
        self.assertFalse(observed["resolved"])
        self.assertEqual(observed["effect_verification"], "INDETERMINATE")
        other = self.runtime.start_task(self.project, "Another task")["task_id"]
        proposal = self.runtime.propose_edit(other, "example.txt", "after")
        with self.assertRaisesRegex(ValueError, "reconcil"):
            self.runtime.apply_edit(other, proposal["proposal_id"])
        self.assertEqual((self.root / "example.txt").read_text(), "before")

    def test_recheck_edit_observes_current_revision_without_replaying(self):
        proposal = self.runtime.propose_edit(self.task, "example.txt", "after")
        original = self.runtime.journal.append
        def fail_result(project, kind, *args, **kwargs):
            if kind == "operation.result":
                raise OSError("lost result")
            return original(project, kind, *args, **kwargs)
        with patch.object(self.runtime.journal, "append", side_effect=fail_result):
            with self.assertRaises(OSError):
                self.runtime.apply_edit(self.task, proposal["proposal_id"])
        action_id = self.events("operation.intent")[-1]["payload"]["action_id"]
        report = self.runtime.record_reconciliation(self.task, action_id, inspect_resource=True)
        self.assertTrue(report["resolved"])
        self.assertEqual(report["resource_sha256"], hashlib.sha256(b"after").hexdigest())
        self.assertEqual(report["effect_verification"], "INDETERMINATE")
        self.assertEqual(len(self.events("operation.intent")), 1)
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(self.task, proposal["proposal_id"])
        self.assertTrue(self.runtime.journal.verify())

    def test_missing_identity_cannot_create_keys_beside_history(self):
        self.runtime.close()
        identity = self.data / "runtime-identity.json"
        identity.unlink()  # Only this test's temporary fixture.
        database = self.data / "desktop.sqlite3"
        before = database.read_bytes()
        with self.assertRaisesRegex(ValueError, "identity.*missing|missing.*identity"):
            TaskRuntime(self.data)
        self.assertFalse(identity.exists())
        self.assertEqual(database.read_bytes(), before)

    def test_corrupt_identity_preserves_all_persistent_bytes(self):
        self.runtime.close()
        identity = self.data / "runtime-identity.json"
        identity.write_bytes(b"broken identity fixture")
        before = {path.name: path.read_bytes() for path in self.data.iterdir() if path.is_file()}
        with self.assertRaisesRegex(ValueError, "identity"):
            TaskRuntime(self.data)
        for name, content in before.items():
            self.assertEqual((self.data / name).read_bytes(), content)

    def test_valid_but_wrong_identity_cannot_open_existing_authority(self):
        fresh = self.base / "other-installation"
        runtime_keys(fresh)
        self.runtime.close()
        identity = self.data / "runtime-identity.json"
        identity.write_bytes((fresh / identity.name).read_bytes())
        with self.assertRaisesRegex(ValueError, "identity"):
            TaskRuntime(self.data)

    def test_future_schema_is_unchanged_and_no_keys_created(self):
        directory = self.base / "future"
        directory.mkdir()
        database = directory / "desktop.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("PRAGMA user_version=999")
        db.close()
        before = database.read_bytes()
        with self.assertRaisesRegex(ValueError, "newer"):
            TaskRuntime(directory)
        self.assertEqual(database.read_bytes(), before)
        self.assertFalse((directory / "runtime-identity.json").exists())

    def test_corrupt_database_is_unchanged_and_no_keys_created(self):
        directory = self.base / "corrupt"
        directory.mkdir()
        database = directory / "desktop.sqlite3"
        database.write_bytes(b"not a sqlite database")
        with self.assertRaisesRegex(ValueError, "database"):
            TaskRuntime(directory)
        self.assertEqual(database.read_bytes(), b"not a sqlite database")
        self.assertFalse((directory / "runtime-identity.json").exists())

    def test_unknown_database_is_preserved_without_initialization(self):
        directory = self.base / "unknown"
        directory.mkdir()
        database = directory / "desktop.sqlite3"
        db = sqlite3.connect(database)
        db.execute("CREATE TABLE unrelated(value TEXT)")
        db.close()
        before = database.read_bytes()
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            TaskRuntime(directory)
        self.assertEqual(database.read_bytes(), before)
        self.assertFalse((directory / "runtime-identity.json").exists())

    def test_inaccessible_dpapi_preserves_identity_and_database(self):
        if __import__("os").name != "nt":
            self.skipTest("Windows account protection only")
        self.runtime.close()
        before = {path.name: path.read_bytes() for path in self.data.iterdir() if path.is_file()}
        with patch("runtime.runtime_keys._dpapi", side_effect=OSError("wrong account")):
            with self.assertRaisesRegex(ValueError, "identity"):
                TaskRuntime(self.data)
        for name, content in before.items():
            self.assertEqual((self.data / name).read_bytes(), content)

    def test_read_only_journal_verifies_and_refuses_mutation(self):
        journal = Journal(self.data / "desktop.sqlite3", read_only=True)
        self.addCleanup(journal.close)
        self.assertTrue(journal.verify())
        with self.assertRaises((ValueError, sqlite3.OperationalError)):
            journal.append(self.project, "task.status", {"status": "ready"}, task_id=self.task)

    def test_preference_only_data_gets_independent_identity(self):
        from ceta_desktop.storage import Store
        directory = self.base / "preferences-only"
        store = Store(directory)
        store.set_setting("theme", "dark")
        store.close()
        other = TaskRuntime(directory)
        self.addCleanup(other.close)
        self.assertNotEqual(other.keys["authority"].public_key(), self.runtime.keys["authority"].public_key())
        self.assertEqual(json.loads(other.journal.db.execute("SELECT value FROM settings WHERE key='theme'").fetchone()[0]), "dark")


if __name__ == "__main__":
    unittest.main()
