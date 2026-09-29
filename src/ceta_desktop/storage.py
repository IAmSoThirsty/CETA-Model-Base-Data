from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid

from runtime.journal import Journal


def application_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    directory = base / "CETA"
    # The same application's pre-release name used this folder. Keep its data
    # accessible in place; never move, copy, or merge conversations implicitly.
    legacy = base / "ThirstyAI"
    if not directory.exists() and (legacy / "desktop.sqlite3").is_file():
        return legacy
    return directory


class Store:
    """Local durable application records. Each UI thread owns its connection."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = Journal(self.directory / "desktop.sqlite3")
        self.db = self.journal.db
        with self.journal.transaction():
            # Only legacy rows are recovered here. Governed task recovery is
            # explicit at desktop startup, never on a worker connection.
            self.db.execute("UPDATE workloads SET status='interrupted' WHERE status='running' AND id NOT IN (SELECT workload_id FROM workload_scopes)")
            self.db.execute("UPDATE messages SET status='interrupted' WHERE status='generating' AND conversation_id NOT IN (SELECT conversation_id FROM conversation_scopes)")

    def setting(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        with self.journal.transaction():
            self.journal.register_project("application", None, {"scope": "application"})
            self.journal.append("application", "setting.changed", {"key": key, "value": value})
            self.db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, json.dumps(value)))

    def new_conversation(self, title: str = "New conversation") -> str:
        identifier = uuid.uuid4().hex
        with self.journal.transaction():
            self.db.execute("INSERT INTO conversations VALUES (?,?,?)", (identifier, title, time.time()))
        return identifier

    def conversations(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM conversations WHERE id NOT IN (SELECT conversation_id FROM conversation_scopes WHERE archived=1) ORDER BY created DESC")]

    def delete_conversation(self, identifier: str) -> None:
        with self.journal.transaction():
            if self.conversation_scope(identifier):
                raise ValueError("This conversation belongs to retained project history. Archive it instead.")
            self.db.execute("DELETE FROM messages WHERE conversation_id=?", (identifier,))
            self.db.execute("DELETE FROM conversations WHERE id=?", (identifier,))
            self._delete_setting("chat_draft:" + identifier)
            self._delete_setting("attachments:chat_draft:" + identifier)
            self._delete_setting("request_retry:" + identifier)
            if self.setting("active_conversation") == identifier:
                self._delete_setting("active_conversation")

    def rename_conversation(self, identifier: str, title: str) -> None:
        with self.journal.transaction():
            self.db.execute("UPDATE conversations SET title=? WHERE id=?", (title, identifier))
            scope = self.conversation_scope(identifier)
            if scope:
                self.journal.append(scope["project_id"], "conversation.renamed",
                    {"conversation_id": identifier, "title": title}, task_id=scope["task_id"])

    def messages(self, identifier: str, *, include_sequence=False) -> list[dict]:
        return self.journal.conversation_messages(identifier, include_sequence=include_sequence)

    def add_message(self, identifier: str, role: str, content: str, status: str = "complete") -> int:
        with self.journal.transaction():
            cursor = self.db.execute("INSERT INTO messages(conversation_id,role,content,status,created) VALUES (?,?,?,?,?)",
                            (identifier, role, content, status, time.time()))
            if role == "user":
                self.db.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                                (content[:70].replace("\n", " "), identifier))
            sequence = cursor.lastrowid
            self._message_event(identifier, sequence, role, content, status)
            return sequence

    def update_response(self, sequence: int, content: str, status: str) -> None:
        with self.journal.transaction():
            cursor = self.db.execute("UPDATE messages SET content=?,status=? WHERE sequence=? AND role='assistant' AND status='generating'",
                                    (content, status, sequence))
            if cursor.rowcount != 1:
                raise ValueError("The active response could not be found. It has not been replaced.")
            row = self.db.execute("SELECT conversation_id,role FROM messages WHERE sequence=?", (sequence,)).fetchone()
            self._message_event(row["conversation_id"], sequence, row["role"], content, status)

    def start_workload(self, workspace: Path, command: str) -> str:
        identifier = uuid.uuid4().hex
        with self.journal.transaction():
            self.db.execute("INSERT INTO workloads VALUES (?,?,?,?,?,?,?)",
                            (identifier, str(workspace), command, "running", None, "", time.time()))
        return identifier

    def finish_workload(self, identifier: str, status: str, code: int | None, output: str) -> None:
        with self.journal.transaction():
            self.db.execute("UPDATE workloads SET status=?,exit_code=?,output=? WHERE id=?",
                            (status, code, output, identifier))
            scope = self.db.execute("SELECT * FROM workload_scopes WHERE workload_id=?", (identifier,)).fetchone()
            if scope:
                self.journal.append(scope["project_id"], "workload.updated",
                    {"workload_id": identifier, "status": status, "exit_code": code, "output": output},
                    task_id=scope["task_id"])

    def workloads(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM workloads ORDER BY created DESC LIMIT 100")]

    def _message_event(self, identifier, sequence, role, content, status):
        scope = self.conversation_scope(identifier)
        if scope:
            self.journal.append(scope["project_id"], "conversation.message",
                {"conversation_id": identifier, "sequence": sequence, "role": role,
                 "content": content, "status": status,
                 "created": self.db.execute("SELECT created FROM messages WHERE sequence=?", (sequence,)).fetchone()[0]},
                task_id=scope["task_id"], actor_id="user" if role == "user" else "runtime:provider")

    def conversation_scope(self, identifier):
        return self.journal.conversation_scope(identifier)

    def _delete_setting(self, key):
        self.journal.register_project("application", None, {"scope": "application"})
        self.journal.append("application", "setting.deleted", {"key": key})

    def bind_conversation(self, identifier, project_id, task_id):
        with self.journal.transaction():
            task = self.journal.task(task_id)
            if task["project_id"] != project_id:
                raise ValueError("The task belongs to another project.")
            current = self.conversation_scope(identifier)
            if current:
                if current["project_id"] != project_id or current["task_id"] != task_id:
                    raise ValueError("A governed conversation cannot be rebound to a different project or task.")
                return current
            conversation = self.db.execute("SELECT * FROM conversations WHERE id=?", (identifier,)).fetchone()
            if conversation is None:
                raise ValueError("Unknown conversation.")
            historical = [dict(row) for row in self.db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY sequence", (identifier,))]
            self.journal.append(project_id, "conversation.bound",
                {"conversation_id": identifier, "conversation": dict(conversation),
                 "legacy_messages": historical,
                 "provenance": "User explicitly attached an existing local transcript; prior messages are historical text, not newly verified evidence."},
                task_id=task_id)
            return self.conversation_scope(identifier)

    def archive_conversation(self, identifier):
        with self.journal.transaction():
            scope = self.conversation_scope(identifier)
            if not scope:
                raise ValueError("Only a governed conversation has a retained archive.")
            if not scope["archived"]:
                self.journal.append(scope["project_id"], "conversation.archived",
                                    {"conversation_id": identifier}, task_id=scope["task_id"])
            self._delete_setting("chat_draft:" + identifier)
            if self.setting("active_conversation") == identifier:
                self._delete_setting("active_conversation")

    def bind_workload(self, identifier, project_id, task_id):
        with self.journal.transaction():
            task = self.journal.task(task_id)
            if task["project_id"] != project_id:
                raise ValueError("Workload task is in another project.")
            workload = self.db.execute("SELECT * FROM workloads WHERE id=?", (identifier,)).fetchone()
            if workload is None:
                raise ValueError("Unknown workload.")
            self.journal.append(project_id, "workload.bound",
                {"workload_id": identifier, "workload": dict(workload)}, task_id=task_id)

    def close(self):
        self.journal.close()
