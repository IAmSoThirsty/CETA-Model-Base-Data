from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any, Mapping

from history import domain_hash
from .assertion import IdentityAssertion, IdentityAssertionError, TrustedIdentityVerifier


class IdentityRegistryError(ValueError):
    pass


class IdentityStatus(StrEnum):
    DECLARED = "DECLARED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class IdentityRecord:
    identity_id: str
    revision: int
    declaration_json: str
    source_ref: str
    status: IdentityStatus
    verifier_id: str | None
    verification_code: str | None
    supersedes_hash: str | None
    assertion_json: str | None
    record_hash: str

    @property
    def declaration(self) -> dict[str, Any]:
        return json.loads(self.declaration_json)

    @property
    def assertion(self) -> IdentityAssertion | None:
        if self.assertion_json is None:
            return None
        return IdentityAssertion(**json.loads(self.assertion_json))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_id": self.identity_id,
            "revision": self.revision,
            "declaration": self.declaration,
            "source_ref": self.source_ref,
            "status": self.status.value,
            "verifier_id": self.verifier_id,
            "verification_code": self.verification_code,
            "supersedes_hash": self.supersedes_hash,
            "assertion": None if self.assertion is None else {**self.assertion.unsigned_body(), "signature_hex": self.assertion.signature_hex},
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IdentityRecord":
        required = {
            "identity_id", "revision", "declaration", "source_ref", "status", "verifier_id",
            "verification_code", "supersedes_hash", "assertion", "record_hash",
        }
        if set(raw) != required:
            raise IdentityRegistryError("identity record field set mismatch")
        assertion = None if raw["assertion"] is None else IdentityAssertion(**raw["assertion"])
        record = _make_record(
            identity_id=str(raw["identity_id"]),
            revision=int(raw["revision"]),
            declaration=raw["declaration"],
            source_ref=str(raw["source_ref"]),
            status=IdentityStatus(str(raw["status"])),
            supersedes_hash=None if raw["supersedes_hash"] is None else str(raw["supersedes_hash"]),
            assertion=assertion,
        )
        if record.record_hash != raw["record_hash"]:
            raise IdentityRegistryError("identity record hash mismatch")
        if record.verifier_id != raw["verifier_id"] or record.verification_code != raw["verification_code"]:
            raise IdentityRegistryError("identity assertion metadata mismatch")
        return record


class IdentityRegistry:
    """Append-only declared identity registry with signed status changes."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        trusted_verifier: TrustedIdentityVerifier | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.trusted_verifier = trusted_verifier
        self._records: dict[str, list[IdentityRecord]] = {}
        self._hashes: set[str] = set()
        if self.path is not None and self.path.exists():
            self._load()

    def declare(self, *, identity_id: str, declaration: Mapping[str, Any], source_ref: str) -> IdentityRecord:
        if identity_id in self._records:
            raise IdentityRegistryError("identity already declared; supersede by an explicit identity-status assertion")
        record = _make_record(
            identity_id=identity_id,
            revision=1,
            declaration=declaration,
            source_ref=source_ref,
            status=IdentityStatus.DECLARED,
            supersedes_hash=None,
            assertion=None,
        )
        self._append(record)
        return record

    def verify(self, identity_id: str, *, assertion: IdentityAssertion, now_epoch_ms: int) -> IdentityRecord:
        return self._apply_assertion(identity_id, assertion=assertion, expected=IdentityStatus.VERIFIED, now_epoch_ms=now_epoch_ms)

    def reject(self, identity_id: str, *, assertion: IdentityAssertion, now_epoch_ms: int) -> IdentityRecord:
        return self._apply_assertion(identity_id, assertion=assertion, expected=IdentityStatus.REJECTED, now_epoch_ms=now_epoch_ms)

    def revoke(self, identity_id: str, *, assertion: IdentityAssertion, now_epoch_ms: int) -> IdentityRecord:
        return self._apply_assertion(identity_id, assertion=assertion, expected=IdentityStatus.REVOKED, now_epoch_ms=now_epoch_ms)

    def latest(self, identity_id: str) -> IdentityRecord:
        try:
            return self._records[identity_id][-1]
        except (KeyError, IndexError) as exc:
            raise IdentityRegistryError(f"unknown identity: {identity_id}") from exc

    def view(self) -> dict[str, dict[str, Any]]:
        result = {}
        for identity_id, revisions in sorted(self._records.items()):
            record = revisions[-1]
            result[identity_id] = {
                "record_hash": record.record_hash,
                "status": record.status.value,
                "source_ref": record.source_ref,
                "declaration": record.declaration,
                "verifier_id": record.verifier_id,
                "verification_code": record.verification_code,
                "verification_assertion_hash": None if record.assertion is None else record.assertion.assertion_hash,
            }
        return result

    def history(self, identity_id: str) -> tuple[IdentityRecord, ...]:
        try:
            return tuple(self._records[identity_id])
        except KeyError as exc:
            raise IdentityRegistryError(f"unknown identity: {identity_id}") from exc

    def verify_integrity(self) -> bool:
        seen: set[str] = set()
        for identity_id, revisions in sorted(self._records.items()):
            prior_hash = None
            expected_revision = 1
            for record in revisions:
                reconstructed = IdentityRecord.from_dict(record.to_dict())
                if reconstructed.record_hash != record.record_hash:
                    raise IdentityRegistryError("identity record does not reconstruct")
                if record.identity_id != identity_id or record.revision != expected_revision:
                    raise IdentityRegistryError("identity revision sequence mismatch")
                if record.supersedes_hash != prior_hash:
                    raise IdentityRegistryError("identity supersession hash mismatch")
                if record.record_hash in seen:
                    raise IdentityRegistryError("duplicate identity record hash")
                if record.status is not IdentityStatus.DECLARED:
                    if self.trusted_verifier is None or record.assertion is None:
                        raise IdentityRegistryError("verified identity history requires its trusted verifier")
                    try:
                        self.trusted_verifier.verify_signature_binding(
                            record.assertion,
                            identity_id=identity_id,
                            prior_record_hash=prior_hash or "",
                        )
                    except IdentityAssertionError as exc:
                        raise IdentityRegistryError(f"identity assertion proof invalid: {exc}") from exc
                seen.add(record.record_hash)
                prior_hash = record.record_hash
                expected_revision += 1
        return True

    def _apply_assertion(
        self,
        identity_id: str,
        *,
        assertion: IdentityAssertion,
        expected: IdentityStatus,
        now_epoch_ms: int,
    ) -> IdentityRecord:
        prior = self.latest(identity_id)
        if self.trusted_verifier is None:
            raise IdentityRegistryError("identity status change requires a configured trusted verifier")
        if assertion.target_status != expected.value:
            raise IdentityRegistryError("identity assertion targets a different status")
        if expected is IdentityStatus.VERIFIED and prior.status not in {IdentityStatus.DECLARED, IdentityStatus.VERIFIED}:
            raise IdentityRegistryError("identity cannot be verified from current status")
        if expected is IdentityStatus.REJECTED and prior.status is not IdentityStatus.DECLARED:
            raise IdentityRegistryError("only a declared identity may be rejected")
        if expected is IdentityStatus.REVOKED and prior.status is IdentityStatus.REVOKED:
            raise IdentityRegistryError("identity already revoked")
        try:
            self.trusted_verifier.verify(
                assertion,
                identity_id=identity_id,
                prior_record_hash=prior.record_hash,
                now_epoch_ms=now_epoch_ms,
            )
        except IdentityAssertionError as exc:
            raise IdentityRegistryError(f"identity assertion rejected: {exc}") from exc
        record = _make_record(
            identity_id=identity_id,
            revision=prior.revision + 1,
            declaration=prior.declaration,
            source_ref=prior.source_ref,
            status=expected,
            supersedes_hash=prior.record_hash,
            assertion=assertion,
        )
        self._append(record)
        return record

    def _append(self, record: IdentityRecord, *, write: bool = True) -> None:
        if record.record_hash in self._hashes:
            raise IdentityRegistryError("duplicate identity record hash")
        revisions = self._records.get(record.identity_id, [])
        expected_revision = len(revisions) + 1
        expected_prior = revisions[-1].record_hash if revisions else None
        if record.revision != expected_revision or record.supersedes_hash != expected_prior:
            raise IdentityRegistryError("identity append revision/supersession mismatch")
        if write and self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        self._records.setdefault(record.identity_id, []).append(record)
        self._hashes.add(record.record_hash)

    def _load(self) -> None:
        with self.path.open(encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    self._append(IdentityRecord.from_dict(json.loads(line)), write=False)
                except Exception as exc:
                    raise IdentityRegistryError(f"invalid identity registry line {lineno}: {exc}") from exc
        self.verify_integrity()


def _make_record(
    *,
    identity_id: str,
    revision: int,
    declaration: Mapping[str, Any],
    source_ref: str,
    status: IdentityStatus,
    supersedes_hash: str | None,
    assertion: IdentityAssertion | None,
) -> IdentityRecord:
    if not isinstance(identity_id, str) or not identity_id.strip() or not isinstance(source_ref, str) or not source_ref.strip():
        raise IdentityRegistryError("identity_id and source_ref must be explicit")
    if revision < 1:
        raise IdentityRegistryError("identity revision must be >= 1")
    if not isinstance(declaration, Mapping) or not declaration:
        raise IdentityRegistryError("identity declaration must be a non-empty mapping")
    if status is IdentityStatus.DECLARED:
        if assertion is not None or revision != 1 or supersedes_hash is not None:
            raise IdentityRegistryError("declared identity must be an unsigned genesis revision")
        verifier_id = None
        verification_code = None
        assertion_dict = None
    else:
        if assertion is None:
            raise IdentityRegistryError("identity status transition requires a signed assertion")
        if assertion.identity_id != identity_id or assertion.prior_record_hash != supersedes_hash or assertion.target_status != status.value:
            raise IdentityRegistryError("identity assertion binding mismatch")
        verifier_id = assertion.verifier_id
        verification_code = assertion.verification_code
        assertion_dict = {**assertion.unsigned_body(), "signature_hex": assertion.signature_hex}
    declaration_copy = dict(declaration)
    body = {
        "identity_id": identity_id,
        "revision": revision,
        "declaration": declaration_copy,
        "source_ref": source_ref,
        "status": status.value,
        "verifier_id": verifier_id,
        "verification_code": verification_code,
        "supersedes_hash": supersedes_hash,
        "assertion": assertion_dict,
    }
    return IdentityRecord(
        identity_id=identity_id,
        revision=revision,
        declaration_json=json.dumps(declaration_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        source_ref=source_ref,
        status=status,
        verifier_id=verifier_id,
        verification_code=verification_code,
        supersedes_hash=supersedes_hash,
        assertion_json=None if assertion_dict is None else json.dumps(assertion_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        record_hash=domain_hash(body, domain="CETA/IDENTITY_RECORD/v2"),
    )
