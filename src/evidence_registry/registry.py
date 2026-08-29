from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .model import EvidenceRecord, EvidenceRecordStatus, EvidenceRegistryError


class EvidenceRegistry:
    """Append-only evidence source registry with optional durable replay."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._revisions: dict[str, list[EvidenceRecord]] = {}
        self._hashes: set[str] = set()
        if self.path is not None and self.path.exists():
            self._load()

    def register(
        self,
        *,
        record_id: str,
        source_id: str,
        payload: Mapping[str, Any],
        provenance_refs: tuple[str, ...] = (),
    ) -> EvidenceRecord:
        if record_id in self._revisions:
            raise EvidenceRegistryError("evidence record identity already exists; validate/reject by revision")
        record = EvidenceRecord.create(record_id=record_id, source_id=source_id, payload=payload, provenance_refs=provenance_refs)
        self._append(record)
        return record

    def validate(self, record_id: str, *, validator_id: str, validation_code: str) -> EvidenceRecord:
        prior = self.latest(record_id)
        if prior.status is not EvidenceRecordStatus.CANDIDATE:
            raise EvidenceRegistryError("only candidate evidence may be validated")
        record = EvidenceRecord.create(
            record_id=prior.record_id,
            source_id=prior.source_id,
            payload=prior.payload,
            provenance_refs=prior.provenance_refs,
            revision=prior.revision + 1,
            status=EvidenceRecordStatus.VALIDATED,
            validator_id=validator_id,
            validation_code=validation_code,
            supersedes_hash=prior.record_hash,
        )
        self._append(record)
        return record

    def reject(self, record_id: str, *, validator_id: str, validation_code: str) -> EvidenceRecord:
        prior = self.latest(record_id)
        if prior.status is not EvidenceRecordStatus.CANDIDATE:
            raise EvidenceRegistryError("only candidate evidence may be rejected")
        record = EvidenceRecord.create(
            record_id=prior.record_id,
            source_id=prior.source_id,
            payload=prior.payload,
            provenance_refs=prior.provenance_refs,
            revision=prior.revision + 1,
            status=EvidenceRecordStatus.REJECTED,
            validator_id=validator_id,
            validation_code=validation_code,
            supersedes_hash=prior.record_hash,
        )
        self._append(record)
        return record

    def latest(self, record_id: str) -> EvidenceRecord:
        try:
            return self._revisions[record_id][-1]
        except (KeyError, IndexError) as exc:
            raise EvidenceRegistryError(f"unknown evidence record: {record_id}") from exc

    def view(self) -> dict[str, dict[str, Any]]:
        return {record_id: revisions[-1].to_view() for record_id, revisions in sorted(self._revisions.items())}

    def history(self, record_id: str) -> tuple[EvidenceRecord, ...]:
        try:
            return tuple(self._revisions[record_id])
        except KeyError as exc:
            raise EvidenceRegistryError(f"unknown evidence record: {record_id}") from exc

    def verify(self) -> bool:
        seen_hashes: set[str] = set()
        for record_id, revisions in sorted(self._revisions.items()):
            self._verify_revision_chain(record_id, revisions, seen_hashes)
        return True

    @staticmethod
    def _verify_revision_chain(record_id: str, revisions: list[EvidenceRecord], seen_hashes: set[str]) -> None:
        prior_hash = None
        for expected_revision, record in enumerate(revisions, 1):
            reconstructed = EvidenceRecord.from_dict(record.to_dict())
            if reconstructed.record_hash != record.record_hash:
                raise EvidenceRegistryError("evidence record does not reconstruct")
            if record.record_id != record_id:
                raise EvidenceRegistryError("record identity changed within revision chain")
            if record.revision != expected_revision:
                raise EvidenceRegistryError("evidence revision sequence mismatch")
            if record.supersedes_hash != prior_hash:
                raise EvidenceRegistryError("evidence supersession hash mismatch")
            if record.record_hash in seen_hashes:
                raise EvidenceRegistryError("duplicate evidence revision hash")
            seen_hashes.add(record.record_hash)
            prior_hash = record.record_hash

    def _append(self, record: EvidenceRecord, *, write: bool = True) -> None:
        if record.record_hash in self._hashes:
            raise EvidenceRegistryError("duplicate evidence revision hash")
        expected_revision = len(self._revisions.get(record.record_id, ())) + 1
        expected_prior = self._revisions.get(record.record_id, [None])[-1]
        expected_prior_hash = None if expected_prior is None else expected_prior.record_hash
        if record.revision != expected_revision or record.supersedes_hash != expected_prior_hash:
            raise EvidenceRegistryError("evidence append revision/supersession mismatch")
        if write and self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        self._revisions.setdefault(record.record_id, []).append(record)
        self._hashes.add(record.record_hash)

    def _load(self) -> None:
        with self.path.open(encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    record = EvidenceRecord.from_dict(raw)
                    self._append(record, write=False)
                except Exception as exc:
                    raise EvidenceRegistryError(f"invalid evidence registry line {lineno}: {exc}") from exc
        self.verify()
