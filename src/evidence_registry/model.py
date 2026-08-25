from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, Mapping

from history import domain_hash


class EvidenceRegistryError(ValueError):
    pass


class EvidenceRecordStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable source-material record.

    This establishes identity, provenance and payload integrity. It does not
    establish semantic truth. Admission into epistemic state remains a CETA
    transition owned by the VM/ledger path.
    """

    record_id: str
    revision: int
    source_id: str
    payload_json: str
    provenance_refs: tuple[str, ...]
    status: EvidenceRecordStatus
    validator_id: str | None
    validation_code: str | None
    supersedes_hash: str | None
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        record_id: str,
        source_id: str,
        payload: Mapping[str, Any],
        provenance_refs: tuple[str, ...] = (),
        revision: int = 1,
        status: EvidenceRecordStatus = EvidenceRecordStatus.CANDIDATE,
        validator_id: str | None = None,
        validation_code: str | None = None,
        supersedes_hash: str | None = None,
    ) -> "EvidenceRecord":
        if not isinstance(record_id, str) or not record_id.strip() or not isinstance(source_id, str) or not source_id.strip():
            raise EvidenceRegistryError("record_id and source_id must be explicit")
        if revision < 1:
            raise EvidenceRegistryError("revision must be >= 1")
        if not isinstance(payload, Mapping):
            raise EvidenceRegistryError("evidence payload must be a structured mapping")
        if len(set(provenance_refs)) != len(provenance_refs) or any(not isinstance(x, str) or not x.strip() for x in provenance_refs):
            raise EvidenceRegistryError("provenance refs must be unique non-empty strings")
        if status is EvidenceRecordStatus.CANDIDATE and (validator_id or validation_code):
            raise EvidenceRegistryError("candidate evidence cannot claim validation")
        if status is not EvidenceRecordStatus.CANDIDATE and (not validator_id or not validation_code):
            raise EvidenceRegistryError("validated/rejected evidence requires validator_id and validation_code")
        payload_copy = dict(payload)
        payload_json = json.dumps(payload_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        body = {
            "record_id": record_id,
            "revision": revision,
            "source_id": source_id,
            "payload": payload_copy,
            "provenance_refs": list(provenance_refs),
            "status": status.value,
            "validator_id": validator_id,
            "validation_code": validation_code,
            "supersedes_hash": supersedes_hash,
        }
        return cls(
            record_id=record_id,
            revision=revision,
            source_id=source_id,
            payload_json=payload_json,
            provenance_refs=tuple(provenance_refs),
            status=status,
            validator_id=validator_id,
            validation_code=validation_code,
            supersedes_hash=supersedes_hash,
            record_hash=domain_hash(body, domain="CETA/EVIDENCE_RECORD/v1"),
        )

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "revision": self.revision,
            "source_id": self.source_id,
            "payload": self.payload,
            "provenance_refs": list(self.provenance_refs),
            "status": self.status.value,
            "validator_id": self.validator_id,
            "validation_code": self.validation_code,
            "supersedes_hash": self.supersedes_hash,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EvidenceRecord":
        required = {
            "record_id", "revision", "source_id", "payload", "provenance_refs", "status",
            "validator_id", "validation_code", "supersedes_hash", "record_hash",
        }
        if set(raw) != required:
            raise EvidenceRegistryError("evidence record field set mismatch")
        record = cls.create(
            record_id=str(raw["record_id"]),
            revision=int(raw["revision"]),
            source_id=str(raw["source_id"]),
            payload=raw["payload"],
            provenance_refs=tuple(str(x) for x in raw["provenance_refs"]),
            status=EvidenceRecordStatus(str(raw["status"])),
            validator_id=None if raw["validator_id"] is None else str(raw["validator_id"]),
            validation_code=None if raw["validation_code"] is None else str(raw["validation_code"]),
            supersedes_hash=None if raw["supersedes_hash"] is None else str(raw["supersedes_hash"]),
        )
        if record.record_hash != raw["record_hash"]:
            raise EvidenceRegistryError("evidence record hash mismatch")
        return record

    def to_view(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "revision": self.revision,
            "source_id": self.source_id,
            "payload": self.payload,
            "payload_hash": domain_hash(self.payload, domain="CETA/EVIDENCE_PAYLOAD/v1"),
            "provenance_refs": list(self.provenance_refs),
            "status": self.status.value,
            "validator_id": self.validator_id,
            "validation_code": self.validation_code,
            "record_hash": self.record_hash,
        }
