"""Read-only startup recovery; never instantiate Store or issue authority here."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QLabel, QListWidget, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget

from ..components import action


class RecoveryWindow(QMainWindow):
    def __init__(self, directory: Path, reason: str):
        super().__init__()
        self.directory = Path(directory).resolve()
        self.pending_update = None
        self.setWindowTitle("CETA · Data recovery")
        self.resize(960, 720)
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        self.summary = QLabel("CETA could not safely open this data folder.\n\n" + reason +
            "\n\nYour data has not been reset and no replacement authority was created. "
            "Keep the entire folder, including SQLite companion files. Inspect backups in a separate folder. "
            "Protected identity requires the original Windows account; copying it to another computer may not work. "
            "Close and reopen CETA after restoring access.\n\nData folder: " + str(self.directory))
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.PlainText)
        layout.addWidget(self.summary)
        layout.addWidget(action("Open data folder", self.open_data_folder))
        layout.addWidget(QLabel("Retained conversation text below is unverified recovery material. "
                                "It grants no authority and cannot be used to execute actions."))
        self.conversations = QListWidget()
        self.conversations.setAccessibleName("Conversations available for recovery")
        layout.addWidget(self.conversations)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Unverified recovered conversation")
        layout.addWidget(self.preview, 1)
        self.export_button = action("Export selected conversation…", self.export_conversation)
        layout.addWidget(self.export_button)
        self._records = []
        self.conversations.currentRowChanged.connect(self.select_conversation)
        self._read_conversations()

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory)))

    def _read_conversations(self):
        database = self.directory / "desktop.sqlite3"
        db = None
        try:
            db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)
            db.execute("PRAGMA query_only=ON")
            self._records = db.execute("SELECT id,title FROM conversations ORDER BY created DESC LIMIT 1000").fetchall()
            for _, title in self._records:
                self.conversations.addItem(str(title))
            self.export_button.setEnabled(bool(self._records))
        except sqlite3.Error:
            self.preview.setPlainText("Conversation text cannot be read from this database. "
                "The original files remain in the data folder; no repair or migration was attempted.")
            self.export_button.setEnabled(False)
        finally:
            if db is not None:
                db.close()

    def _conversation(self, index):
        identifier, title = self._records[index]
        db = sqlite3.connect((self.directory / "desktop.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute("SELECT role,substr(content,1,100000),status FROM messages "
                              "WHERE conversation_id=? ORDER BY sequence LIMIT 1000", (identifier,)).fetchall()
            return {"schema": "ceta.recovery-conversation.v1", "source_directory": str(self.directory),
                    "conversation_id": identifier, "title": title, "verified": False, "grants_authority": False,
                    "limits": "First 1000 messages, each limited to 100000 characters; original files retained.",
                    "messages": [{"role": role, "content": text, "status": status} for role, text, status in rows]}
        finally:
            db.close()

    def select_conversation(self, index):
        if not 0 <= index < len(self._records):
            return
        try:
            self.preview.setPlainText(json.dumps(self._conversation(index), indent=2, ensure_ascii=False))
        except sqlite3.Error as exc:
            self.preview.setPlainText("This conversation could not be read: " + str(exc))

    def export_conversation(self):
        index = self.conversations.currentRow()
        if not 0 <= index < len(self._records):
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export unverified conversation", "ceta-recovery.json", "JSON (*.json)")
        if not path:
            return
        try:
            target = Path(path).resolve()
            if target.is_relative_to(self.directory):
                raise ValueError("Choose a new file outside the preserved data folder.")
            content = self._conversation(index)
            with target.open("x", encoding="utf-8") as handle:
                json.dump(content, handle, indent=2, ensure_ascii=False)
            self.statusBar().showMessage("Exported unverified conversation text to " + str(target))
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.statusBar().showMessage("Export did not complete: " + str(exc))
