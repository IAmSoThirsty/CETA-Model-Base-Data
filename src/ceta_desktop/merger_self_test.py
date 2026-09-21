"""Explicit packaged-application probe using newly created synthetic local files."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
import time
from uuid import uuid4

from PySide6.QtWidgets import QApplication

from runtime.tasks import TaskRuntime


def verify_sandbox_fixture(directory, journal):
    """Verify only the explicit generated Sandbox fixture, without modifying it."""
    directory = Path(directory).resolve()
    marker = directory / "sandbox-fixture.json"
    if not marker.exists():
        return {"status": "not_requested"}
    fixture = json.loads(marker.read_text(encoding="utf-8"))
    if fixture.get("schema") != "ceta.sandbox-fixture.v1" or fixture.get("synthetic") is not True:
        raise RuntimeError("Invalid synthetic Sandbox migration marker")
    for field in ("source_sha256", "expected_backup_sha256"):
        if not isinstance(fixture.get(field), str) or not re.fullmatch("[0-9a-f]{64}", fixture[field]):
            raise RuntimeError("Invalid synthetic Sandbox fixture digest")
    expected = fixture["expected_rows"]

    def check_rows(db):
        checks = {
            "conversation": [list(row) for row in db.execute(
                "SELECT id,title,created FROM conversations WHERE id='legacy-sandbox'")],
            "message": [list(row) for row in db.execute(
                "SELECT sequence,conversation_id,role,content,status,created FROM messages WHERE sequence=1")],
            "setting": [list(row) for row in db.execute(
                "SELECT key,value FROM settings WHERE key='sandbox_fixture'")],
            "unknown": [list(row) for row in db.execute(
                "SELECT name,hex(data) FROM unknown_user_data ORDER BY name")],
        }
        if checks != expected:
            raise RuntimeError("Synthetic legacy or unknown rows changed during migration/restart")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Synthetic migration database integrity check failed")

    schema = journal.db.execute("PRAGMA user_version").fetchone()[0]
    if schema != 2:
        raise RuntimeError("Synthetic legacy database did not migrate to schema 2")
    check_rows(journal.db)
    backups = list(directory.glob("desktop.sqlite3.schema-1-backup-*.sqlite3"))
    if len(backups) != 1:
        raise RuntimeError("Expected exactly one retained schema-1 migration backup")
    backup = backups[0]
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    if backup_hash != fixture["expected_backup_sha256"]:
        raise RuntimeError("Synthetic migration backup differs from its expected online-backup hash")
    db = sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)
    try:
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise RuntimeError("Retained migration backup does not contain schema 1")
        check_rows(db)
    finally:
        db.close()
    # A second executable launch must retain each prior report's canonical
    # checkpoint. Recomputed hashes alone would not detect a removed old task.
    prior_count = 0
    for previous_path in directory.glob("merger-self-test-*.json"):
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        migration = previous.get("migration", {})
        if previous.get("status") != "passed" or migration.get("status") != "passed":
            continue
        for checkpoint in migration.get("project_checkpoints", []):
            events = journal.events(checkpoint["project_id"])
            sequence = checkpoint["sequence"]
            if len(events) < sequence or events[sequence - 1]["event_hash"] != checkpoint["head"]:
                raise RuntimeError("Synthetic restart lost or rewrote previously verified project history")
        prior_count += 1
    checkpoints = [{"project_id": row["project_id"], "sequence": row["sequence"], "head": row["head"]}
                   for row in journal.db.execute("SELECT project_id,sequence,head FROM project_streams ORDER BY project_id")]
    return {"status": "passed", "synthetic": True, "schema_before": 1, "schema_after": schema,
            "fixture_source_sha256": fixture["source_sha256"], "backup_sha256": backup_hash,
            "backup_schema": 1, "backup_integrity": "ok", "unknown_rows_preserved": True,
            "legacy_rows_preserved": True, "prior_successful_launches_verified": prior_count,
            "project_checkpoints": checkpoints}


def run_merger_self_test(window):
    """Invoked only by the opt-in CLI with an explicit test data directory."""
    fixture_id = uuid4().hex
    project = Path(window.store.directory) / ("merger-synthetic-project-" + fixture_id)
    project.mkdir(exist_ok=False)
    source = project / "example.py"
    before, after = b"answer = 1\r\n", b"answer = 2\r\n"
    source.write_bytes(before)
    (project / "AGENTS.md").write_text("Synthetic verification project. Preserve unrelated files.\n", encoding="utf-8")
    sentinel = project / "keep.txt"
    sentinel.write_bytes(b"Synthetic unrelated bytes must survive.\n")
    sentinel_hash = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    window._set_workspace(project)
    window.task_panel.objective.setText("Synthetic packaged CETA merger verification")
    window.start_project_task()
    window.inspect_project_task()
    window.task_panel.search.setText("answer")
    window.search_project_task()
    if "example.py" not in window.task_panel.results.toPlainText():
        raise RuntimeError("Packaged GUI search did not return the synthetic source")
    window.open_document(window.file_model.index(str(source)))
    if window.document is None or window.document.path != source:
        raise RuntimeError("Packaged GUI could not open the synthetic document")
    window.editor.setPlainText("answer = 2\n")
    window.review_editor_edit()
    if not window.pending_edit or "answer = 2" not in window.task_panel.results.toPlainText():
        raise RuntimeError("Packaged GUI did not create the reviewable diff")
    window.apply_reviewed_edit()
    if source.read_bytes() != after or window.editor.document().isModified():
        raise RuntimeError("Packaged GUI edit did not produce the reviewed CRLF bytes")
    window.command.setText("echo CETA_MERGER_PACKAGED_PROBE")
    window.run_workload()
    deadline = time.monotonic() + 90
    while window.workload_task is not None or window.workload_id is not None:
        QApplication.processEvents()
        time.sleep(0.01)
        if time.monotonic() > deadline:
            window.stop_workload()
            raise RuntimeError("Packaged command did not complete within the self-test bound")
    events = window.task_runtime.timeline(window.task_id)
    edits = [e for e in events if e["kind"] == "operation.result" and e["payload"]["kind"] == "edit"]
    commands = [e for e in events if e["kind"] == "operation.result" and e["payload"]["kind"] == "command"]
    if len(edits) != 1 or edits[0]["payload"]["verification"]["status"] != "VERIFIED":
        raise RuntimeError("Packaged edit lacks its independently verified CETA observation")
    if len(commands) != 1 or commands[0]["payload"]["result"].get("exit_code") != 0:
        raise RuntimeError("Packaged command did not record a successful process exit")
    if "CETA_MERGER_PACKAGED_PROBE" not in window.output.toPlainText():
        raise RuntimeError("Packaged command output did not reach the GUI")
    if hashlib.sha256(sentinel.read_bytes()).hexdigest() != sentinel_hash:
        raise RuntimeError("Synthetic unrelated file was altered")
    transcript = window.store.new_conversation("Synthetic merger verification")
    window.store.bind_conversation(transcript, window.project_id, window.task_id)
    window.store.add_message(transcript, "user", "Synthetic retained transcript; no model inference.")
    window.show_task_timeline()
    if "operation.result" not in window.task_panel.results.toPlainText():
        raise RuntimeError("Packaged timeline did not expose the recorded operation")
    window.task_runtime.journal.verify()
    reopened = TaskRuntime(window.store.directory)
    try:
        restored = reopened.task(window.task_id)
        if restored["project_id"] != window.project_id or not reopened.journal.verify():
            raise RuntimeError("Reopened packaged journal did not restore the same task")
        if reopened.journal.conversation_messages(transcript)[0]["role"] != "user":
            raise RuntimeError("Reopened packaged journal did not retain the bound transcript")
    finally:
        reopened.close()
    return {"status": "passed", "schema": "ceta.merged-packaged-self-test.v1",
        "synthetic": True, "model_inference": False, "project": str(project),
        "migration": verify_sandbox_fixture(window.store.directory, window.task_runtime.journal),
        "project_id": window.project_id, "task_id": window.task_id,
        "source_before_sha256": hashlib.sha256(before).hexdigest(),
        "source_after_sha256": hashlib.sha256(after).hexdigest(),
        "checks": ["native_project_open", "native_inspection_search", "native_diff_review_apply",
                   "verified_file_observation", "native_command_output", "history_reopen",
                   "bound_transcript", "unrelated_bytes_preserved"],
        "command_effect_verification": commands[0]["payload"]["verification"]["status"],
        "limits": "Trusted local command; no filesystem/network sandbox or model-quality claim."}
