from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import runtime.journal as journal_module
from runtime.journal import Journal, JournalError, SCHEMA_VERSION


def schema_one(path):
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA user_version=1;
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT INTO settings VALUES ('legacy_setting','{"retained":true}');
        CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE messages(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),role TEXT NOT NULL,
            content TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);
        INSERT INTO conversations VALUES ('legacy','Preserve original',12.5);
        INSERT INTO messages VALUES (1,'legacy','user','original bytes','complete',13.5);
        CREATE TABLE unknown_user_data(name TEXT PRIMARY KEY,data BLOB NOT NULL);
        INSERT INTO unknown_user_data VALUES ('retain',X'0001FEFF');
    """)
    db.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "desktop.sqlite3"

    def test_schema_one_backup_is_verified_and_unknown_rows_are_preserved(self):
        schema_one(self.path)
        journal = Journal(self.path)
        self.addCleanup(journal.close)
        backup = journal.migration_backup
        self.assertIsNotNone(backup)
        self.assertEqual(hashlib.sha256(Path(backup["path"]).read_bytes()).hexdigest(), backup["sha256"])
        original = sqlite3.connect(backup["path"])
        self.addCleanup(original.close)
        self.assertEqual(original.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(original.execute("SELECT content FROM messages").fetchone()[0], "original bytes")
        self.assertEqual(journal.db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(journal.db.execute("SELECT data FROM unknown_user_data").fetchone()[0], bytes.fromhex("0001feff"))
        self.assertEqual(journal.db.execute("SELECT content FROM messages").fetchone()[0], "original bytes")
        print("SYNTHETIC_MIGRATION_EVIDENCE " + json.dumps({"schema_before": 1, "schema_after": SCHEMA_VERSION,
            "backup_sha256": backup["sha256"], "backup_integrity": "ok", "user_data": False}))

    def test_migration_failure_rolls_back_schema_and_preserves_backup(self):
        schema_one(self.path)
        original = journal_module.initialize_schema
        def fail_after_schema(db):
            original(db)
            raise RuntimeError("injected migration failure")
        with patch.object(journal_module, "initialize_schema", side_effect=fail_after_schema):
            with self.assertRaisesRegex(RuntimeError, "injected migration"):
                Journal(self.path)
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='task_events'").fetchone())
        self.assertEqual(db.execute("SELECT content FROM messages").fetchone()[0], "original bytes")
        self.assertEqual(len(list(self.path.parent.glob("*.schema-1-backup-*.sqlite3"))), 1)

    def test_future_schema_rejected_without_persistent_mutation(self):
        schema_one(self.path)
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA user_version=99"); db.close()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(JournalError, "newer CETA"):
            Journal(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])

    def test_concurrent_open_performs_one_schema_one_migration(self):
        schema_one(self.path)
        def open_and_close(_):
            journal = Journal(self.path)
            version = journal.db.execute("PRAGMA user_version").fetchone()[0]
            journal.close()
            return version
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(open_and_close, range(2))), [SCHEMA_VERSION] * 2)
        self.assertEqual(len(list(self.path.parent.glob("*.schema-1-backup-*.sqlite3"))), 1)


class ProjectJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.sqlite3"
        self.journal = Journal(self.path)
        self.addCleanup(lambda: self.journal.close())
        self.journal.register_project("application", None)
        self.journal.append("application", "task.created", {"objective": "Preserve work"}, task_id="task")

    def append(self, kind, payload, task_id="task"):
        return self.journal.append("application", kind, payload, task_id=task_id)

    def bind_data(self):
        self.append("conversation.bound", {"conversation_id": "bound", "conversation":
            {"id": "bound", "title": "New conversation", "created": 1.0}, "legacy_messages": [
            {"sequence": 4, "conversation_id": "bound", "role": "user", "content": "legacy", "status": "complete", "created": 2.0}]})
        self.append("conversation.message", {"conversation_id": "bound", "sequence": 5, "role": "assistant",
            "content": "partial", "status": "generating", "created": 3.0})
        self.append("workload.bound", {"workload_id": "work", "workload": {
            "id": "work", "workspace": self.temp.name, "command": "python -V", "status": "running",
            "exit_code": None, "output": "", "created": 4.0}})

    def test_caught_nested_failure_cannot_return_success(self):
        before = self.journal.events("application")
        with self.assertRaisesRegex(JournalError, "nested transaction failed"):
            with self.journal.transaction():
                self.append("test.event", {"step": 1})
                try:
                    with self.journal.transaction():
                        self.append("test.event", {"step": 2})
                        raise ValueError("inner")
                except ValueError:
                    pass
        self.assertEqual(self.journal.events("application"), before)
        self.append("test.event", {"after": True})

    def test_projection_append_failure_rolls_back_event_and_head(self):
        before = self.journal.events("application")
        observed = dict(self.journal._observed)
        with patch.object(self.journal, "_project_event", side_effect=OSError("projection failed")):
            with self.assertRaisesRegex(OSError, "projection failed"):
                self.append("test.event", {})
        self.assertEqual(self.journal.events("application"), before)
        self.assertEqual(self.journal._observed, observed)

    def test_committed_observed_head_detects_coordinated_tail_rollback(self):
        retained = self.journal.events("application")[-1]
        self.append("test.event", {"seen": True})
        self.assertGreater(self.journal._observed["application"][0], retained["sequence"])
        self.journal.db.execute("DROP TRIGGER task_events_no_delete")
        self.journal.db.execute("DELETE FROM task_events WHERE project_id=? AND sequence>?", ("application", retained["sequence"]))
        self.journal.db.execute("UPDATE project_streams SET sequence=?,head=? WHERE project_id=?", (retained["sequence"], retained["event_hash"], "application"))
        with self.assertRaisesRegex(JournalError, "Previously observed history"):
            self.journal.events("application")

    def test_missing_task_projection_cannot_hide_task_or_accept_event(self):
        self.journal.db.execute("DELETE FROM project_tasks WHERE task_id='task'")
        with self.assertRaisesRegex(JournalError, "membership"):
            self.journal.tasks("application")
        with self.assertRaisesRegex(JournalError, "membership"):
            self.append("test.event", {})
        self.journal.rebuild_projections()
        self.assertEqual(self.journal.task("task")["objective"], "Preserve work")

    def test_changed_project_root_and_task_association_are_rejected(self):
        self.journal.db.execute("UPDATE project_streams SET root=? WHERE project_id='application'", (self.temp.name,))
        with self.assertRaisesRegex(JournalError, "root/metadata"):
            self.journal.project("application")
        self.journal.db.execute("UPDATE project_streams SET root=NULL WHERE project_id='application'")
        self.journal.register_project("other", self.temp.name)
        self.journal.db.execute("UPDATE project_tasks SET project_id='other' WHERE task_id='task'")
        with self.assertRaisesRegex(JournalError, "membership"):
            self.journal.task("task")
        self.journal.rebuild_projections()
        self.assertEqual(self.journal.task("task")["project_id"], "application")

    def test_cross_project_event_and_duplicate_task_are_rejected(self):
        self.journal.register_project("other", self.temp.name)
        with self.assertRaisesRegex(JournalError, "another project"):
            self.journal.append("other", "test.event", {}, task_id="task")
        with self.assertRaisesRegex(JournalError, "already belongs"):
            self.journal.append("other", "task.created", {"objective": "take task"}, task_id="task")

    def test_governed_records_require_task_and_string_json_keys(self):
        before = self.journal.events("application")
        with self.assertRaisesRegex(JournalError, "task identity"):
            self.journal.append("application", "conversation.bound", {}, task_id=None)
        with self.assertRaisesRegex(JournalError, "keys must be strings"):
            self.append("test.event", {"nested": {1: "ambiguous", "1": "different"}})
        self.assertEqual(self.journal.events("application"), before)

    def test_concurrent_connections_preserve_every_event(self):
        def write(worker):
            journal = Journal(self.path)
            try:
                for index in range(5):
                    journal.append("application", "worker.event", {"worker": worker, "index": index}, task_id="task")
            finally:
                journal.close()
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(write, range(3)))
        events = self.journal.events("application", kind="worker.event")
        self.assertEqual(len(events), 15)
        self.assertEqual(len({event["event_hash"] for event in events}), 15)
        self.assertTrue(self.journal.verify())

    def test_bound_data_rebuild_preserves_unbound_rows_and_canonical_bytes(self):
        self.bind_data()
        self.journal.db.execute("INSERT INTO conversations VALUES ('unbound','Keep',10)")
        self.journal.db.execute("INSERT INTO messages VALUES (20,'unbound','user','unrelated','complete',11)")
        self.journal.db.execute("INSERT INTO settings VALUES ('unknown_setting','17')")
        self.journal.db.execute("CREATE TABLE unknown_artifact(data TEXT)")
        self.journal.db.execute("INSERT INTO unknown_artifact VALUES ('retain')")
        self.append("conversation.message", {"conversation_id": "bound", "sequence": 5, "role": "assistant",
            "content": "final", "status": "complete", "created": 3.0})
        self.append("conversation.renamed", {"conversation_id": "bound", "title": "Final title"})
        self.append("workload.updated", {"workload_id": "work", "status": "failed", "exit_code": 1, "output": "failure"})
        before = self.journal.events("application")
        self.journal.db.execute("UPDATE messages SET content='corrupt' WHERE sequence=5")
        with self.assertRaisesRegex(JournalError, "messages projection"):
            self.journal.conversation_messages("bound")
        self.journal.rebuild_projections()
        self.assertEqual(self.journal.events("application"), before)
        self.assertEqual(self.journal.conversation_messages("bound")[-1]["content"], "final")
        self.assertEqual(self.journal.db.execute("SELECT title FROM conversations WHERE id='bound'").fetchone()[0], "Final title")
        self.assertEqual(self.journal.db.execute("SELECT output FROM workloads WHERE id='work'").fetchone()[0], "failure")
        self.assertEqual(self.journal.db.execute("SELECT content FROM messages WHERE sequence=20").fetchone()[0], "unrelated")
        self.assertEqual(self.journal.db.execute("SELECT data FROM unknown_artifact").fetchone()[0], "retain")
        self.assertEqual(self.journal.db.execute("SELECT value FROM settings WHERE key='unknown_setting'").fetchone()[0], "17")

    def test_missing_transcript_and_forged_scope_fail_closed(self):
        self.bind_data()
        self.journal.db.execute("DELETE FROM messages WHERE conversation_id='bound'")
        with self.assertRaisesRegex(JournalError, "messages projection"):
            self.journal.conversation_messages("bound")
        self.journal.rebuild_projections()
        self.journal.db.execute("DELETE FROM conversation_scopes WHERE conversation_id='bound'")
        with self.assertRaisesRegex(JournalError, "missing"):
            self.journal.conversation_scope("bound")
        self.journal.rebuild_projections()
        self.journal.append("application", "task.created", {"objective": "Different"}, task_id="different")
        self.journal.db.execute("UPDATE conversation_scopes SET task_id='different' WHERE conversation_id='bound'")
        with self.assertRaisesRegex(JournalError, "canonical project/task"):
            self.journal.conversation_scope("bound")

    def test_restart_projection_and_archive_settings_replay(self):
        self.bind_data()
        self.append("setting.changed", {"key": "active_conversation", "value": "bound"}, task_id=None)
        self.append("setting.changed", {"key": "chat_draft:bound", "value": "draft"}, task_id=None)
        self.append("task.status", {"status": "needs_reconciliation", "reason": "application_restart"})
        self.assertEqual(self.journal.conversation_messages("bound")[-1]["status"], "interrupted")
        self.assertEqual(self.journal.db.execute("SELECT status FROM workloads WHERE id='work'").fetchone()[0], "interrupted")
        self.append("conversation.archived", {"conversation_id": "bound"})
        self.journal.rebuild_projections()
        self.assertIsNone(self.journal.db.execute("SELECT value FROM settings WHERE key='active_conversation'").fetchone())
        self.assertIsNone(self.journal.db.execute("SELECT value FROM settings WHERE key='chat_draft:bound'").fetchone())
        self.assertEqual(self.journal.conversation_scope("bound")["archived"], 1)
        self.journal.close(); self.journal = Journal(self.path)
        self.assertEqual(self.journal.task("task")["status"], "needs_reconciliation")

    def test_failed_rebuild_is_atomic_and_never_changes_history(self):
        self.bind_data()
        before = self.journal.events("application")
        rows = [tuple(row) for row in self.journal.db.execute("SELECT * FROM messages ORDER BY sequence")]
        original = self.journal._project_event
        def fail(event):
            if event["kind"] == "conversation.message":
                raise OSError("injected replay failure")
            return original(event)
        with patch.object(self.journal, "_project_event", side_effect=fail):
            with self.assertRaisesRegex(OSError, "injected replay"):
                self.journal.rebuild_projections()
        self.assertEqual(self.journal.events("application"), before)
        self.assertEqual([tuple(row) for row in self.journal.db.execute("SELECT * FROM messages ORDER BY sequence")], rows)

    def test_rebuild_refuses_unknown_foreign_key_cascade_without_mutating_rows(self):
        self.bind_data()
        self.journal.db.execute("CREATE TABLE user_notes(id INTEGER PRIMARY KEY,conversation_id TEXT REFERENCES ConVersations(ID) ON DELETE CASCADE,note TEXT)")
        self.journal.db.execute("INSERT INTO user_notes VALUES (1,'bound','preserve relationship')")
        before_events = self.journal.events("application")
        before_rows = [tuple(row) for row in self.journal.db.execute("SELECT * FROM user_notes")]
        before_messages = [tuple(row) for row in self.journal.db.execute("SELECT * FROM messages")]
        with self.assertRaisesRegex(JournalError, "custom foreign key"):
            self.journal.rebuild_projections()
        self.assertEqual([tuple(row) for row in self.journal.db.execute("SELECT * FROM user_notes")], before_rows)
        self.assertEqual([tuple(row) for row in self.journal.db.execute("SELECT * FROM messages")], before_messages)
        self.assertEqual(self.journal.events("application"), before_events)

    def test_rebuild_refuses_unknown_trigger_before_trigger_can_mutate_external_rows(self):
        self.bind_data()
        self.journal.db.execute("CREATE TABLE user_archive(note TEXT)")
        self.journal.db.execute("INSERT INTO user_archive VALUES ('must remain')")
        self.journal.db.execute("CREATE TRIGGER custom_archive AFTER DELETE ON messages BEGIN DELETE FROM user_archive; END")
        before = [tuple(row) for row in self.journal.db.execute("SELECT * FROM messages")]
        with self.assertRaisesRegex(JournalError, "custom trigger"):
            self.journal.rebuild_projections()
        self.assertEqual(self.journal.db.execute("SELECT note FROM user_archive").fetchone()[0], "must remain")
        self.assertEqual([tuple(row) for row in self.journal.db.execute("SELECT * FROM messages")], before)

    def test_rebuild_refuses_unknown_owned_columns_without_discarding_values(self):
        self.bind_data()
        self.journal.db.execute("ALTER TABLE messages ADD COLUMN user_note TEXT")
        self.journal.db.execute("UPDATE messages SET user_note='retain' WHERE sequence=5")
        with self.assertRaisesRegex(JournalError, "custom columns"):
            self.journal.rebuild_projections()
        self.assertEqual(self.journal.db.execute("SELECT user_note FROM messages WHERE sequence=5").fetchone()[0], "retain")

    def test_rebuild_refuses_unknown_generated_column_before_mutation(self):
        self.bind_data()
        self.journal.db.execute("ALTER TABLE messages ADD COLUMN user_projection TEXT GENERATED ALWAYS AS (content) VIRTUAL")
        before = [tuple(row) for row in self.journal.db.execute("SELECT * FROM messages")]
        with self.assertRaisesRegex(JournalError, "custom columns"):
            self.journal.rebuild_projections()
        self.assertEqual([tuple(row) for row in self.journal.db.execute("SELECT * FROM messages")], before)

    def test_rebuild_rejects_sequence_collision_with_unbound_legacy_row(self):
        self.bind_data()
        self.journal.db.execute("DELETE FROM messages WHERE sequence=5")
        self.journal.db.execute("INSERT INTO conversations VALUES ('unbound','Keep',20)")
        self.journal.db.execute("INSERT INTO messages VALUES (5,'unbound','user','preserve','complete',21)")
        with self.assertRaisesRegex(JournalError, "unrelated history"):
            self.journal.rebuild_projections()
        self.assertEqual(self.journal.db.execute("SELECT content FROM messages WHERE sequence=5").fetchone()[0], "preserve")


if __name__ == "__main__":
    unittest.main()
