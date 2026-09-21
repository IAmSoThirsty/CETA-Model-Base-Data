"""Explicit, immutable import of selected CETA JSONL as historical artifacts.

Imported rows never enter live authority, identity, evidence, or transition owners.
The caller supplies the user's project binding; an old unscoped file cannot prove
that binding. Hash/replay checks establish structural integrity, not signature
trust, current permissions, semantic truth, or a fresh validation of old results.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import stat

from authority.ledger import AuthorityEvent, AuthorityLedger, GENESIS_AUTHORITY_HASH, _event_hash, canonical_hash
from ceta_model001.validation import strict_loads
from evidence_registry.model import EvidenceRecord
from evidence_registry.registry import EvidenceRegistry
from history.ledger import LedgerEntry, TransitionLedger
from identity_registry.registry import IdentityRecord, IdentityRegistry

from .journal import JournalError, canonical, digest

KINDS = ("transition", "authority", "evidence", "identity")
MAX_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 20_000
MAX_LINE_BYTES = 1024 * 1024


class LegacyHistoryError(JournalError):
    pass


def _read_selected(path):
    selected = Path(path).absolute()
    if selected.suffix.lower() != ".jsonl":
        raise LegacyHistoryError("Select one CETA .jsonl history file")
    info = selected.lstat()
    if (not stat.S_ISREG(info.st_mode) or selected.is_symlink()
            or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise LegacyHistoryError("Historical source must be a regular file, not a link")
    resolved = selected.resolve(strict=True)
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if before.st_size > MAX_BYTES:
            raise LegacyHistoryError("Historical source exceeds the 16 MiB import limit")
        raw = handle.read(MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
    latest = selected.stat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(info) != identity(before) or identity(before) != identity(after) or identity(after) != identity(latest):
        raise LegacyHistoryError("Historical source changed while it was read; select and confirm it again")
    if not raw or len(raw) > MAX_BYTES:
        raise LegacyHistoryError("Historical source is empty or exceeds the 16 MiB import limit")
    if not raw.endswith(b"\n"):
        raise LegacyHistoryError("Historical source has an incomplete final JSONL line")
    return resolved, raw


def _parse(raw):
    lines = raw.splitlines(keepends=True)
    if len(lines) > MAX_RECORDS:
        raise LegacyHistoryError("Historical source exceeds the 20000 record import limit")
    records, offset = [], 0
    for number, line in enumerate(lines, 1):
        if len(line) > MAX_LINE_BYTES:
            raise LegacyHistoryError(f"Historical line {number} exceeds the 1 MiB import limit")
        try:
            text = line.decode("utf-8-sig" if number == 1 else "utf-8")
            record = strict_loads(text)
            if not isinstance(record, dict):
                raise ValueError("expected a JSON object")
            canonical(record).encode("utf-8")
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LegacyHistoryError(f"Invalid historical JSONL line {number}: {str(exc)[:240]}") from exc
        records.append({"line_number": number, "byte_offset": offset,
                        "byte_length": len(line), "line_sha256": hashlib.sha256(line).hexdigest(),
                        "record": record})
        offset += len(line)
    return records


def _unchanged(original, reconstructed):
    if canonical(original) != canonical(reconstructed):
        raise LegacyHistoryError("Historical record has noncanonical field types or unsupported fields")


def _verify_records(kind, rows):
    records = [row["record"] for row in rows]
    try:
        if kind == "transition":
            entries = [LedgerEntry.from_dict(record) for record in records]
            for original, entry in zip(records, entries):
                _unchanged(original, entry.to_dict())
            TransitionLedger()._replay_and_validate(entries)
        elif kind == "authority":
            replay, previous = AuthorityLedger(), GENESIS_AUTHORITY_HASH
            for sequence, record in enumerate(records, 1):
                event = AuthorityEvent(**record)
                if (type(event.sequence) is not int or event.sequence != sequence
                        or event.previous_hash != previous or not isinstance(event.payload, dict)
                        or _event_hash(event.body()) != event.event_hash):
                    raise LegacyHistoryError("Historical authority sequence or hash chain does not reconstruct")
                if event.event_type == "ISSUE" and event.permit_id != event.payload["permit"]["permit_id"]:
                    raise LegacyHistoryError("Historical authority issue has a different permit identity")
                if event.event_type == "PREPARE":
                    material = {"permit_id": event.permit_id, "consumer_id": event.payload["consumer_id"],
                                "consumer_key_id": event.payload["consumer_key_id"],
                                "consequence_hash": event.payload["consequence_hash"]}
                    if canonical_hash(material) != event.payload["intent_hash"]:
                        raise LegacyHistoryError("Historical authority intent binding does not reconstruct")
                replay._apply_event(event)
                replay._events.append(event)
                previous = event.event_hash
            replay.verify()
        elif kind == "evidence":
            replay = EvidenceRegistry()
            for original in records:
                record = EvidenceRecord.from_dict(original)
                _unchanged(original, record.to_dict())
                replay._append(record, write=False)
            replay.verify()
        else:
            replay = IdentityRegistry()
            for original in records:
                record = IdentityRecord.from_dict(original)
                _unchanged(original, record.to_dict())
                replay._append(record, write=False)
            # No source verifier keys were supplied. Preserve signed assertions
            # and their bindings without authenticating or trusting the signer.
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
        if isinstance(exc, LegacyHistoryError):
            raise
        raise LegacyHistoryError(f"Historical {kind} integrity check failed: {str(exc)[:240]}") from exc


def _scope(journal, project_id, task_id):
    project = journal.project(project_id)
    task = journal.task(task_id)
    if project is None or task is None or task["project_id"] != project_id:
        raise LegacyHistoryError("Select an existing task in the destination project")


def import_legacy_history(journal, project_id, source_path, *, expected_sha256,
                          kind, provenance, task_id, actor_id="user"):
    """Import exactly one confirmed file, atomically and idempotently.

    ``provenance`` requires source_application="CETA", the destination project_id,
    and a nonempty scope_statement describing the user's explicit binding of this
    historical file to that project. Repeating the same artifact/project/kind must
    retain that declaration. Authorization belongs to the enclosing task runtime.
    """
    if kind not in KINDS:
        raise LegacyHistoryError("Unsupported CETA history kind")
    if not isinstance(expected_sha256, str) or not re.fullmatch("[0-9a-f]{64}", expected_sha256):
        raise LegacyHistoryError("Confirm the selected file's lowercase SHA-256 before importing")
    if (not isinstance(provenance, dict) or set(provenance) != {"source_application", "project_id", "scope_statement"}
            or provenance.get("source_application") != "CETA" or provenance.get("project_id") != project_id
            or not isinstance(provenance.get("scope_statement"), str) or not provenance["scope_statement"].strip()):
        raise LegacyHistoryError("Explicit CETA source and destination project provenance is required")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise LegacyHistoryError("Historical import requires an explicit actor")
    provenance = strict_loads(canonical(provenance))
    _scope(journal, project_id, task_id)
    try:
        source, raw = _read_selected(source_path)
    except OSError as exc:
        raise LegacyHistoryError(f"Cannot read selected historical file: {str(exc)[:240]}") from exc
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if source_sha256 != expected_sha256:
        raise LegacyHistoryError("Historical source SHA-256 differs from the confirmed file")
    rows = _parse(raw)
    _verify_records(kind, rows)
    import_id = digest({"domain": "CETA/LEGACY_HISTORY_IMPORT/v1", "project_id": project_id,
                        "kind": kind, "source_sha256": source_sha256})
    with journal.transaction():
        _scope(journal, project_id, task_id)
        prior = [event for event in journal.events(project_id, kind="legacy.history.imported")
                 if event["payload"].get("import_id") == import_id]
        if prior:
            if len(prior) != 1 or prior[0]["payload"]["provenance"] != provenance:
                raise LegacyHistoryError("This artifact already has a different recorded project declaration")
            event, duplicate = prior[0], True
        else:
            payload = {"schema": "ceta.legacy-history-import.v1", "import_id": import_id,
                       "source_path": str(source), "source_sha256": source_sha256,
                       "source_byte_length": len(raw), "source_encoding": "utf-8",
                       "artifact_encoding": "base64", "artifact": base64.b64encode(raw).decode("ascii"),
                       "kind": kind, "record_count": len(rows), "records": rows,
                       "provenance": provenance, "provenance_basis": "user_declared_project_binding",
                       "disposition": "historical_only", "current_authority": False,
                       "structural_integrity": "record_hashes_and_order_verified",
                       "signature_authentication": "not_performed_no_trusted_source_keys",
                       "fresh_validation_of_historical_results": False}
            event = journal.append(project_id, "legacy.history.imported", payload,
                                   task_id=task_id, actor_id=actor_id)
            duplicate = False
    return {"import_id": import_id, "event_id": event["id"], "source_sha256": source_sha256,
            "record_count": len(rows), "kind": kind, "disposition": "historical_only",
            "already_imported": duplicate}
