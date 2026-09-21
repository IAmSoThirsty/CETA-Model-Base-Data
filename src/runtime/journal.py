"""Transactional canonical project journal for the CETA application.

Existing JSONL formats are preserved as typed payloads in one project stream.
This is a local integrity boundary, not protection against the account owner
replacing both the database and its retained checkpoints.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

SCHEMA_VERSION = 2
ZERO_HASH = "0" * 64


class JournalError(ValueError):
    pass


def canonical(value):
    def validate(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise JournalError("Canonical object keys must be strings")
            for child in item.values():
                validate(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                validate(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise JournalError("Canonical event contains a non-JSON value")
    validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise JournalError(f"{label} must be a nonempty string")
    return value


def initialize_schema(db):
    """Transactional, additive v1 migration; never imports another project."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise JournalError("This data was created by a newer CETA. Install that version to open it.")
    db.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES conversations(id),
        role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
        content TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS workloads (
        id TEXT PRIMARY KEY, workspace TEXT NOT NULL, command TEXT NOT NULL,
        status TEXT NOT NULL, exit_code INTEGER, output TEXT NOT NULL, created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS project_streams (
        project_id TEXT PRIMARY KEY, root TEXT UNIQUE, sequence INTEGER NOT NULL DEFAULT 0,
        head TEXT NOT NULL, metadata TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS task_events (
        project_id TEXT NOT NULL REFERENCES project_streams(project_id),
        sequence INTEGER NOT NULL, id TEXT NOT NULL UNIQUE, task_id TEXT, actor_id TEXT NOT NULL,
        kind TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL,
        previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
        PRIMARY KEY(project_id,sequence))""")
    db.execute("CREATE INDEX IF NOT EXISTS task_events_task ON task_events(project_id,task_id,sequence)")
    db.execute("""CREATE TABLE IF NOT EXISTS project_tasks (
        project_id TEXT NOT NULL REFERENCES project_streams(project_id),
        task_id TEXT NOT NULL UNIQUE, objective TEXT NOT NULL, status TEXT NOT NULL,
        last_sequence INTEGER NOT NULL, PRIMARY KEY(project_id,task_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS conversation_scopes (
        conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),
        project_id TEXT NOT NULL, task_id TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(project_id,task_id) REFERENCES project_tasks(project_id,task_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS workload_scopes (
        workload_id TEXT PRIMARY KEY REFERENCES workloads(id),
        project_id TEXT NOT NULL, task_id TEXT NOT NULL,
        FOREIGN KEY(project_id,task_id) REFERENCES project_tasks(project_id,task_id))""")
    for name in ("update", "delete"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS task_events_no_{name}
            BEFORE {name.upper()} ON task_events BEGIN
            SELECT RAISE(ABORT, 'canonical history is append-only'); END""")
    db.execute("CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,sequence)")
    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mutex = threading.RLock()
        self._depth = 0
        self._rollback_only = False
        self._observed = {}
        self._pending_heads = {}
        self.migration_backup = None
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            # Reject a future schema before changing persistent pragmas or tables.
            if self.db.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
                raise JournalError("This data was created by a newer CETA. Install that version to open it.")
            self.db.execute("PRAGMA foreign_keys=ON")
            with self.transaction():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if version == 1:
                    self.migration_backup = self._backup_schema_one()
                initialize_schema(self.db)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.verify()
        except BaseException:
            self.db.close()
            raise

    def _backup_schema_one(self):
        """Hold the source writer lock while a read connection snapshots old data."""
        backup = self.path.with_name(self.path.name + ".schema-1-backup-" + uuid4().hex + ".sqlite3")
        with backup.open("xb"):
            pass
        source = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=30)
        target = sqlite3.connect(backup)
        try:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise JournalError("Pre-migration backup failed its integrity check")
            if target.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise JournalError("Pre-migration backup does not contain schema 1")
        finally:
            target.close()
            source.close()
        return {"path": str(backup), "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(), "schema_version": 1}

    @contextmanager
    def transaction(self):
        with self._mutex:
            outer = self._depth == 0
            if outer:
                self.db.execute("BEGIN IMMEDIATE")
                self._rollback_only = False
                self._pending_heads = {}
            self._depth += 1
            propagating = False
            try:
                yield self
            except BaseException:
                propagating = True
                self._rollback_only = True
                raise
            finally:
                self._depth -= 1
                if outer:
                    try:
                        if self._rollback_only:
                            self.db.rollback()
                            if not propagating:
                                raise JournalError("A nested transaction failed; the outer transaction was rolled back")
                        else:
                            self.db.commit()
                            self._observed.update(self._pending_heads)
                    except BaseException:
                        self.db.rollback()
                        raise
                    finally:
                        self._pending_heads = {}

    def register_project(self, project_id, root, metadata=None):
        _text(project_id, "project_id")
        if root is not None:
            root = str(Path(root).resolve(strict=True))
        with self.transaction():
            existing = self.db.execute("SELECT root FROM project_streams WHERE project_id=?", (project_id,)).fetchone()
            if existing is not None:
                self._verify_project(project_id)
                if existing["root"] != root:
                    raise JournalError("Project identity is bound to a different root")
                return
            self.db.execute("INSERT INTO project_streams VALUES (?,?,0,?,?)",
                            (project_id, root, ZERO_HASH, canonical(metadata or {})))
            self.append(project_id, "project.opened", {"root": root, "metadata": metadata or {}})

    def _project_row(self, project_id):
        row = self.db.execute("SELECT * FROM project_streams WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise JournalError("Unknown project")
        result = dict(row)
        result["metadata"] = json.loads(result["metadata"])
        return result

    def project(self, project_id):
        with self.transaction():
            self._verify_project(project_id)
            return self._project_row(project_id)

    def head(self, project_id):
        with self.transaction():
            self._verify_project(project_id)
            return self.project(project_id)["head"]

    def append(self, project_id, kind, payload, task_id=None, actor_id="user", expected_head=None):
        _text(project_id, "project_id")
        _text(kind, "kind")
        _text(actor_id, "actor_id")
        if task_id is not None:
            _text(task_id, "task_id")
        if not isinstance(payload, dict):
            raise JournalError("Event payload must be a mapping")
        payload = json.loads(canonical(payload))
        with self.transaction():
            events = self._verify_project(project_id, allow_empty=kind == "project.opened")
            project = self._project_row(project_id)
            if kind == "project.opened" and events:
                raise JournalError("Project already has its canonical identity")
            if expected_head is not None and project["head"] != expected_head:
                raise JournalError("Stale project journal head")
            if kind.startswith(("task.", "conversation.", "workload.")) and task_id is None:
                raise JournalError("Governed event requires a task identity")
            expected_tasks = self._expected_tasks(events)
            self._check_tasks(project_id, expected_tasks)
            if task_id is not None:
                if kind == "task.created":
                    if self.db.execute("SELECT 1 FROM task_events WHERE task_id=? AND kind='task.created'", (task_id,)).fetchone():
                        raise JournalError("Task identity already belongs to canonical history")
                elif task_id not in expected_tasks:
                    raise JournalError("Event task is unknown or belongs to another project")
            event = dict(schema_version=1, id=uuid4().hex, project_id=project_id,
                         sequence=project["sequence"] + 1, task_id=task_id, actor_id=actor_id,
                         kind=kind, observed_at=datetime.now(timezone.utc).isoformat(),
                         payload=payload, previous_hash=project["head"])
            event["event_hash"] = digest({"domain": "CETA/PROJECT_EVENT/v1", **event})
            self.db.execute("INSERT INTO task_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (project_id, event["sequence"], event["id"], task_id, actor_id, kind,
                             event["observed_at"], canonical(payload), event["previous_hash"], event["event_hash"]))
            self.db.execute("UPDATE project_streams SET sequence=?,head=? WHERE project_id=?",
                            (event["sequence"], event["event_hash"], project_id))
            self._project_event(event)
            self._pending_heads[project_id] = (event["sequence"], event["event_hash"])
            return json.loads(canonical(event))

    @staticmethod
    def _timestamp(value, label):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise JournalError(label + " must be a finite timestamp")
        return value

    def _scope(self, table, identifier_field, identifier, event):
        row = self.db.execute(f"SELECT * FROM {table} WHERE {identifier_field}=?", (identifier,)).fetchone()
        if row is None or row["project_id"] != event["project_id"] or row["task_id"] != event["task_id"]:
            raise JournalError("Object is not bound to this project/task")
        return row

    def _write_message(self, value, conversation_id, observed_at):
        sequence = value.get("sequence")
        if type(sequence) is not int or sequence <= 0:
            raise JournalError("Message sequence must be a positive integer")
        if value.get("conversation_id", conversation_id) != conversation_id:
            raise JournalError("Message belongs to another conversation")
        role = value.get("role")
        if role not in {"user", "assistant", "system"} or not isinstance(value.get("content"), str):
            raise JournalError("Invalid message role/content")
        _text(value.get("status"), "message status")
        existing = self.db.execute("SELECT conversation_id,role,created FROM messages WHERE sequence=?", (sequence,)).fetchone()
        if existing is not None and (existing["conversation_id"] != conversation_id or existing["role"] != role):
            raise JournalError("Message sequence collides with unrelated history")
        created = value.get("created", existing["created"] if existing is not None else datetime.fromisoformat(observed_at).timestamp())
        self._timestamp(created, "message created")
        self.db.execute("""INSERT INTO messages(sequence,conversation_id,role,content,status,created) VALUES (?,?,?,?,?,?)
            ON CONFLICT(sequence) DO UPDATE SET content=excluded.content,status=excluded.status,created=excluded.created""",
            (sequence, conversation_id, role, value["content"], value["status"], created))

    def _project_event(self, event):
        payload, kind = event["payload"], event["kind"]
        if kind == "task.created":
            objective = _text(payload.get("objective"), "objective")
            _text(event.get("task_id"), "task_id")
            self.db.execute("INSERT INTO project_tasks VALUES (?,?,?,?,?)",
                (event["project_id"], event["task_id"], objective, "ready", event["sequence"]))
        elif kind == "task.status":
            status = _text(payload.get("status"), "status")
            cursor = self.db.execute("UPDATE project_tasks SET status=?,last_sequence=? WHERE project_id=? AND task_id=?",
                (status, event["sequence"], event["project_id"], event["task_id"]))
            if cursor.rowcount != 1:
                raise JournalError("Task status has no canonical task projection")
            if payload.get("reason") == "application_restart":
                self.db.execute("""UPDATE messages SET status='interrupted' WHERE status='generating'
                    AND conversation_id IN (SELECT conversation_id FROM conversation_scopes WHERE project_id=? AND task_id=?)""",
                    (event["project_id"], event["task_id"]))
                self.db.execute("""UPDATE workloads SET status='interrupted' WHERE status='running'
                    AND id IN (SELECT workload_id FROM workload_scopes WHERE project_id=? AND task_id=?)""",
                    (event["project_id"], event["task_id"]))
        elif kind == "conversation.bound":
            identifier = _text(payload.get("conversation_id"), "conversation_id")
            conversation = payload.get("conversation")
            if not isinstance(conversation, dict) or conversation.get("id") != identifier or not isinstance(conversation.get("title"), str):
                raise JournalError("Conversation binding requires its exact original row")
            self._timestamp(conversation.get("created"), "conversation created")
            prior = self.db.execute("SELECT * FROM conversation_scopes WHERE conversation_id=?", (identifier,)).fetchone()
            if prior is not None:
                raise JournalError("Conversation is already bound")
            self.db.execute("""INSERT INTO conversations(id,title,created) VALUES (?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,created=excluded.created""",
                (identifier, conversation["title"], conversation["created"]))
            self.db.execute("INSERT INTO conversation_scopes VALUES (?,?,?,0)",
                (identifier, event["project_id"], event["task_id"]))
            historical = payload.get("legacy_messages", [])
            if not isinstance(historical, list):
                raise JournalError("Legacy transcript must be a list")
            for message in historical:
                self._write_message(message, identifier, event["observed_at"])
        elif kind == "conversation.message":
            identifier = _text(payload.get("conversation_id"), "conversation_id")
            self._scope("conversation_scopes", "conversation_id", identifier, event)
            self._write_message(payload, identifier, event["observed_at"])
            if payload["role"] == "user":
                self.db.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                    (payload["content"][:70].replace("\n", " "), identifier))
        elif kind == "conversation.renamed":
            identifier = _text(payload.get("conversation_id"), "conversation_id")
            self._scope("conversation_scopes", "conversation_id", identifier, event)
            if not isinstance(payload.get("title"), str):
                raise JournalError("Conversation title must be text")
            self.db.execute("UPDATE conversations SET title=? WHERE id=?", (payload["title"], identifier))
        elif kind == "conversation.archived":
            identifier = _text(payload.get("conversation_id"), "conversation_id")
            self._scope("conversation_scopes", "conversation_id", identifier, event)
            self.db.execute("UPDATE conversation_scopes SET archived=1 WHERE conversation_id=?", (identifier,))
            self._clear_archived_settings(identifier)
        elif kind == "workload.bound":
            identifier = _text(payload.get("workload_id"), "workload_id")
            workload = payload.get("workload")
            if not isinstance(workload, dict) or workload.get("id") != identifier:
                raise JournalError("Workload binding requires its exact original row")
            self._timestamp(workload.get("created"), "workload created")
            if self.db.execute("SELECT 1 FROM workload_scopes WHERE workload_id=?", (identifier,)).fetchone():
                raise JournalError("Workload is already bound")
            self.db.execute("""INSERT INTO workloads(id,workspace,command,status,exit_code,output,created) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET workspace=excluded.workspace,command=excluded.command,
                status=excluded.status,exit_code=excluded.exit_code,output=excluded.output,created=excluded.created""",
                tuple(workload[key] for key in ("id", "workspace", "command", "status", "exit_code", "output", "created")))
            self.db.execute("INSERT INTO workload_scopes VALUES (?,?,?)", (identifier, event["project_id"], event["task_id"]))
        elif kind == "workload.updated":
            identifier = _text(payload.get("workload_id"), "workload_id")
            self._scope("workload_scopes", "workload_id", identifier, event)
            self.db.execute("UPDATE workloads SET status=?,exit_code=?,output=? WHERE id=?",
                (_text(payload.get("status"), "workload status"), payload.get("exit_code"), payload.get("output", ""), identifier))
        elif kind in {"setting.changed", "setting.deleted"}:
            if event["project_id"] != "application":
                raise JournalError("Application settings belong to the application stream")
            key = _text(payload.get("key"), "setting key")
            if kind == "setting.changed":
                self.db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, canonical(payload["value"])))
            else:
                self.db.execute("DELETE FROM settings WHERE key=?", (key,))

    def _clear_archived_settings(self, identifier):
        self.db.execute("DELETE FROM settings WHERE key=?", ("chat_draft:" + identifier,))
        current = self.db.execute("SELECT value FROM settings WHERE key='active_conversation'").fetchone()
        if current and json.loads(current[0]) == identifier:
            self.db.execute("DELETE FROM settings WHERE key='active_conversation'")

    @staticmethod
    def _event(row):
        result = dict(row)
        result["schema_version"] = 1
        result["payload"] = json.loads(result["payload"])
        return result

    def events(self, project_id, kind=None, task_id=None):
        with self.transaction():
            self._verify_project(project_id)
            query, args = "SELECT * FROM task_events WHERE project_id=?", [project_id]
            if kind is not None:
                query += " AND kind=?"
                args.append(kind)
            if task_id is not None:
                query += " AND task_id=?"
                args.append(task_id)
            return [self._event(row) for row in self.db.execute(query + " ORDER BY sequence", args)]

    def _verify_project(self, project_id, *, allow_empty=False):
        row = self._project_row(project_id)
        prior, sequence = ZERO_HASH, 0
        old_sequence, old_hash = self._observed.get(project_id, (0, ZERO_HASH))
        old_found = old_sequence == 0
        events = []
        tasks = set()
        for stored in self.db.execute("SELECT * FROM task_events WHERE project_id=? ORDER BY sequence", (project_id,)):
            event = self._event(stored)
            sequence += 1
            expected_hash = event["event_hash"]
            body = {key: value for key, value in event.items() if key != "event_hash"}
            if event["sequence"] != sequence or event["previous_hash"] != prior:
                raise JournalError("Project journal sequence or predecessor mismatch")
            if digest({"domain": "CETA/PROJECT_EVENT/v1", **body}) != expected_hash:
                raise JournalError("Project journal content hash mismatch")
            if sequence == 1:
                if event["kind"] != "project.opened" or event["task_id"] is not None:
                    raise JournalError("Project stream lacks its canonical opening event")
                if event["payload"].get("root") != row["root"] or event["payload"].get("metadata", {}) != row["metadata"]:
                    raise JournalError("Project root/metadata projection differs from canonical history")
            elif event["kind"] == "project.opened":
                raise JournalError("Duplicate project identity event")
            if event["kind"].startswith(("task.", "conversation.", "workload.")) and event["task_id"] is None:
                raise JournalError("Canonical governed event lacks its task identity")
            if event["kind"] == "task.created":
                identifier = _text(event["task_id"], "task_id")
                if identifier in tasks:
                    raise JournalError("Duplicate canonical task identity")
                tasks.add(identifier)
            elif event["task_id"] is not None and event["task_id"] not in tasks:
                raise JournalError("Canonical event references an unknown project task")
            events.append(event)
            prior = expected_hash
            if sequence == old_sequence:
                old_found = prior == old_hash
        if not events and not allow_empty:
            raise JournalError("Project identity has no canonical opening event")
        if row["sequence"] != sequence or row["head"] != prior:
            raise JournalError("Project journal checkpoint mismatch")
        if sequence < old_sequence or not old_found:
            raise JournalError("Previously observed history was removed or replaced")
        if self._depth:
            self._pending_heads[project_id] = (sequence, prior)
        else:
            self._observed[project_id] = (sequence, prior)
        return events

    @staticmethod
    def _expected_tasks(events):
        expected = {}
        for event in events:
            identifier = event["task_id"]
            if event["kind"] == "task.created":
                expected[identifier] = {"project_id": event["project_id"], "task_id": identifier,
                    "objective": _text(event["payload"].get("objective"), "objective"),
                    "status": "ready", "last_sequence": event["sequence"]}
            elif event["kind"] == "task.status":
                if identifier not in expected:
                    raise JournalError("Status event references unknown task")
                expected[identifier].update(status=_text(event["payload"].get("status"), "status"), last_sequence=event["sequence"])
        return expected

    def _check_tasks(self, project_id, expected):
        actual = {row["task_id"]: dict(row) for row in self.db.execute("SELECT * FROM project_tasks WHERE project_id=?", (project_id,))}
        if actual != expected:
            raise JournalError("Task projection membership or content differs from canonical history")

    def _history(self):
        identifiers = [row[0] for row in self.db.execute("SELECT project_id FROM project_streams ORDER BY project_id")]
        if set(self._observed) - set(identifiers):
            raise JournalError("Previously observed project history was removed")
        events = []
        task_projects = {}
        for identifier in identifiers:
            stream = self._verify_project(identifier)
            for event in stream:
                if event["kind"] == "task.created":
                    if event["task_id"] in task_projects:
                        raise JournalError("Task identity belongs to multiple project streams")
                    task_projects[event["task_id"]] = identifier
            events.extend(stream)
        return events

    def verify(self):
        with self.transaction():
            events = self._history()
            for project_id in {e["project_id"] for e in events}:
                self._check_tasks(project_id, self._expected_tasks([e for e in events if e["project_id"] == project_id]))
            expected = self._expected_bound_data(events)
            self._check_bound_data(expected, events)
        return True

    def task(self, task_id):
        with self.transaction():
            created = self.db.execute("SELECT project_id FROM task_events WHERE task_id=? AND kind='task.created'", (task_id,)).fetchall()
            if len(created) != 1:
                raise JournalError("Unknown or duplicated canonical task")
            project_id = created[0][0]
            expected = self._expected_tasks(self._verify_project(project_id))
            self._check_tasks(project_id, expected)
            if task_id not in expected:
                raise JournalError("Unknown canonical task")
            return dict(expected[task_id])

    def tasks(self, project_id):
        with self.transaction():
            expected = self._expected_tasks(self._verify_project(project_id))
            self._check_tasks(project_id, expected)
            return list(reversed(list(expected.values())))

    def _expected_bound_data(self, events):
        """Use the same deterministic projector in an isolated in-memory database."""
        replay = object.__new__(Journal)
        replay.db = sqlite3.connect(":memory:")
        replay.db.row_factory = sqlite3.Row
        replay.db.execute("PRAGMA foreign_keys=ON")
        try:
            initialize_schema(replay.db)
            for event in events:
                if event["kind"] == "project.opened":
                    replay.db.execute("INSERT INTO project_streams VALUES (?,?,0,?,?)",
                        (event["project_id"], event["payload"]["root"], ZERO_HASH, canonical(event["payload"].get("metadata", {}))))
                replay._project_event(event)
            for row in replay.db.execute("SELECT conversation_id FROM conversation_scopes WHERE archived=1").fetchall():
                replay._clear_archived_settings(row[0])
            return {table: [dict(row) for row in replay.db.execute("SELECT * FROM " + table)] for table in
                ("conversations", "messages", "conversation_scopes", "workloads", "workload_scopes", "settings")}
        finally:
            replay.db.close()

    def _check_bound_data(self, expected, events, conversation_id=None):
        for table, identifier_key, owner_table, owner_key in (
            ("conversation_scopes", "conversation_id", None, None),
            ("workload_scopes", "workload_id", None, None),
            ("conversations", "id", "conversation_scopes", "conversation_id"),
            ("messages", "sequence", "conversation_scopes", "conversation_id"),
            ("workloads", "id", "workload_scopes", "workload_id"),
        ):
            wanted = expected[table]
            if conversation_id is not None:
                if table not in {"conversation_scopes", "conversations", "messages"}:
                    continue
                wanted = [row for row in wanted if row["id" if table == "conversations" else "conversation_id"] == conversation_id]
            actual = [dict(row) for row in self.db.execute("SELECT * FROM " + table)]
            if owner_table:
                ids = {row[owner_key] for row in expected[owner_table]}
                field = "conversation_id" if table == "messages" else "id"
                actual = [row for row in actual if row[field] in ids]
            if conversation_id is not None:
                actual = [row for row in actual if row["id" if table == "conversations" else "conversation_id"] == conversation_id]
            if {row[identifier_key]: row for row in actual} != {row[identifier_key]: row for row in wanted}:
                raise JournalError(table + " projection differs from canonical bound history")
        if conversation_id is None:
            expected_settings = {row["key"]: json.loads(row["value"]) for row in expected["settings"]}
            governed = {event["payload"]["key"] for event in events if event["kind"] in {"setting.changed", "setting.deleted"}}
            archived = {row["conversation_id"] for row in expected["conversation_scopes"] if row["archived"]}
            governed.update("chat_draft:" + identifier for identifier in archived)
            current = self.db.execute("SELECT value FROM settings WHERE key='active_conversation'").fetchone()
            if current and json.loads(current[0]) in archived:
                governed.add("active_conversation")
            for key in governed:
                row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if key not in expected_settings:
                    if row is not None:
                        raise JournalError("Deleted setting projection differs from canonical history")
                elif row is None or json.loads(row[0]) != expected_settings[key]:
                    raise JournalError("Setting projection differs from canonical history")

    def verify_conversation(self, identifier):
        with self.transaction():
            scope = self.conversation_scope(identifier)
            if scope is None:
                return False
            events = self._history()
            self._check_bound_data(self._expected_bound_data(events), events, conversation_id=identifier)
            return True

    def conversation_messages(self, identifier):
        with self.transaction():
            self.verify_conversation(identifier)
            return [dict(row) for row in self.db.execute(
                "SELECT role,content,status FROM messages WHERE conversation_id=? ORDER BY sequence", (identifier,))]

    def conversation_scope(self, identifier):
        with self.transaction():
            matches = [e for e in self._history() if e["kind"] == "conversation.bound" and e["payload"].get("conversation_id") == identifier]
            row = self.db.execute("SELECT * FROM conversation_scopes WHERE conversation_id=?", (identifier,)).fetchone()
            if not matches:
                if row is not None:
                    raise JournalError("Conversation scope has no canonical binding")
                return None
            if len(matches) != 1 or row is None:
                raise JournalError("Conversation scope projection is missing or duplicated")
            binding = matches[0]
            stream = self._verify_project(binding["project_id"])
            archived = any(e["kind"] == "conversation.archived" and e["payload"].get("conversation_id") == identifier for e in stream)
            expected = {"conversation_id": identifier, "project_id": binding["project_id"], "task_id": binding["task_id"], "archived": int(archived)}
            if dict(row) != expected:
                raise JournalError("Conversation scope differs from its canonical project/task")
            self.task(binding["task_id"])
            return expected

    def _check_rebuild_relationships(self):
        """Refuse custom relationships before rebuilding any owned projection row."""
        columns = {
            "settings": {"key", "value"},
            "conversations": {"id", "title", "created"},
            "messages": {"sequence", "conversation_id", "role", "content", "status", "created"},
            "workloads": {"id", "workspace", "command", "status", "exit_code", "output", "created"},
            "project_tasks": {"project_id", "task_id", "objective", "status", "last_sequence"},
            "conversation_scopes": {"conversation_id", "project_id", "task_id", "archived"},
            "workload_scopes": {"workload_id", "project_id", "task_id"},
        }
        allowed = {
            ("messages", "conversation_id", "conversations", "id"),
            ("project_tasks", "project_id", "project_streams", "project_id"),
            ("conversation_scopes", "conversation_id", "conversations", "id"),
            ("conversation_scopes", "project_id", "project_tasks", "project_id"),
            ("conversation_scopes", "task_id", "project_tasks", "task_id"),
            ("workload_scopes", "workload_id", "workloads", "id"),
            ("workload_scopes", "project_id", "project_tasks", "project_id"),
            ("workload_scopes", "task_id", "project_tasks", "task_id"),
        }
        for trigger in self.db.execute("SELECT name,tbl_name FROM sqlite_master WHERE type='trigger'"):
            if trigger["tbl_name"].casefold() in columns:
                raise JournalError("Projection rebuild requires review of custom trigger: " + trigger["name"])
        for table in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            name = table[0].casefold()
            quoted = '"' + name.replace('"', '""') + '"'
            if name in columns:
                actual = {row["name"].casefold() for row in self.db.execute("PRAGMA table_xinfo(" + quoted + ")")}
                if actual != columns[name]:
                    raise JournalError("Projection rebuild requires review of custom columns in " + name)
            for reference in self.db.execute("PRAGMA foreign_key_list(" + quoted + ")"):
                relationship = (name, reference["from"].casefold(), reference["table"].casefold(),
                                (reference["to"] or "").casefold())
                if name in columns or reference["table"].casefold() in columns:
                    if (relationship not in allowed or reference["on_delete"] != "NO ACTION"
                            or reference["on_update"] != "NO ACTION"):
                        raise JournalError("Projection rebuild requires review of custom foreign key on " + name)

    def rebuild_projections(self):
        """Replay bound data; unfamiliar triggers/FKs/columns fail before mutation."""
        with self.transaction():
            self._check_rebuild_relationships()
            events = self._history()
            conversations = {e["payload"]["conversation_id"] for e in events if e["kind"] == "conversation.bound"}
            workloads = {e["payload"]["workload_id"] for e in events if e["kind"] == "workload.bound"}
            self.db.execute("DELETE FROM conversation_scopes")
            self.db.execute("DELETE FROM workload_scopes")
            self.db.execute("DELETE FROM project_tasks")
            for identifier in conversations:
                self.db.execute("DELETE FROM messages WHERE conversation_id=?", (identifier,))
                self.db.execute("DELETE FROM conversations WHERE id=?", (identifier,))
            for identifier in workloads:
                self.db.execute("DELETE FROM workloads WHERE id=?", (identifier,))
            for event in events:
                self._project_event(event)
            for row in self.db.execute("SELECT conversation_id FROM conversation_scopes WHERE archived=1").fetchall():
                self._clear_archived_settings(row[0])
            self.verify()

    def close(self):
        with self._mutex:
            self.db.close()
