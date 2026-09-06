from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


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
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.db = sqlite3.connect(directory / "desktop.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            self.db.close()
            raise ValueError("This data was created by a newer CETA. Install that version to open it.")
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS messages (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS workloads (
                id TEXT PRIMARY KEY, workspace TEXT NOT NULL, command TEXT NOT NULL,
                status TEXT NOT NULL, exit_code INTEGER, output TEXT NOT NULL,
                created REAL NOT NULL)""")
            self.db.execute("PRAGMA user_version=1")
            self.db.execute("UPDATE workloads SET status='interrupted' WHERE status='running'")
            self.db.execute("UPDATE messages SET status='interrupted' WHERE status='generating'")
            self.db.execute("CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, sequence)")

    def setting(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        with self.db:
            self.db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, json.dumps(value)))

    def new_conversation(self, title: str = "New conversation") -> str:
        identifier = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO conversations VALUES (?,?,?)", (identifier, title, time.time()))
        return identifier

    def conversations(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM conversations ORDER BY created DESC")]

    def messages(self, identifier: str) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT role,content,status FROM messages WHERE conversation_id=? ORDER BY sequence", (identifier,))]

    def add_message(self, identifier: str, role: str, content: str, status: str = "complete") -> int:
        with self.db:
            cursor = self.db.execute("INSERT INTO messages(conversation_id,role,content,status,created) VALUES (?,?,?,?,?)",
                            (identifier, role, content, status, time.time()))
            if role == "user":
                self.db.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                                (content[:70].replace("\n", " "), identifier))
            return cursor.lastrowid

    def update_response(self, sequence: int, content: str, status: str) -> None:
        with self.db:
            cursor = self.db.execute("UPDATE messages SET content=?,status=? WHERE sequence=? AND role='assistant' AND status='generating'",
                                    (content, status, sequence))
            if cursor.rowcount != 1:
                raise ValueError("The active response could not be found. It has not been replaced.")

    def start_workload(self, workspace: Path, command: str) -> str:
        identifier = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO workloads VALUES (?,?,?,?,?,?,?)",
                            (identifier, str(workspace), command, "running", None, "", time.time()))
        return identifier

    def finish_workload(self, identifier: str, status: str, code: int | None, output: str) -> None:
        with self.db:
            self.db.execute("UPDATE workloads SET status=?,exit_code=?,output=? WHERE id=?",
                            (status, code, output, identifier))

    def workloads(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM workloads ORDER BY created DESC LIMIT 100")]

    def close(self):
        self.db.close()
