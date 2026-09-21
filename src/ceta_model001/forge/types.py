from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4
from ..validation import text, timestamp, digest, unique_strings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class QuestionPlane(str, Enum):
    HAPPENED = "HAPPENED"
    JUSTIFIED = "JUSTIFIED"
    SHOULD_BE_LEGAL = "SHOULD_BE_LEGAL"
    MAY_ASSIST = "MAY_ASSIST"


class EvidenceMethod(str, Enum):
    DIRECT_OBSERVATION = "direct_observation"
    INSTRUMENT = "instrument"
    DOCUMENT = "document"
    TESTIMONY = "testimony"
    REPLICATION = "replication"
    INFERENCE_RECORD = "inference_record"
    MEASUREMENT = "measurement"


class EvidenceRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXTUALIZES = "CONTEXTUALIZES"
    DOES_NOT_RESOLVE = "DOES_NOT_RESOLVE"


class ScopeFit(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class BasisClass(str, Enum):
    NONE = "NONE"
    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    INFERRED = "INFERRED"
    MIXED = "MIXED"


class Verdict(str, Enum):
    UNKNOWN = "UNKNOWN"
    UNVERIFIED = "UNVERIFIED"
    SUPPORTED = "SUPPORTED"
    DISPUTED = "DISPUTED"
    CONTRADICTED = "CONTRADICTED"
    REFUTED = "REFUTED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class Evidence:
    source: str
    method: EvidenceMethod
    artifact: str
    limitations: str
    timestamp: str = field(default_factory=now_iso)
    identity_relevant: bool = False
    identity_relevance_reason: str | None = None
    identity_relevance_evidence_refs: tuple[str, ...] = ()
    artifact_hash: str | None = None
    evidence_id: str = field(default_factory=lambda: f"ev_{uuid4().hex[:16]}")

    def validate(self) -> None:
        for name in ('source', 'artifact', 'evidence_id'):
            text(getattr(self, name), name)
        if not isinstance(self.method, EvidenceMethod): raise ValueError('Invalid evidence method')
        if not isinstance(self.limitations, str): raise ValueError('limitations must be text')
        timestamp(self.timestamp)
        if type(self.identity_relevant) is not bool: raise ValueError('identity_relevant must be boolean')
        if self.artifact_hash is not None: digest(self.artifact_hash, 'artifact_hash')
        unique_strings(self.identity_relevance_evidence_refs, 'identity relevance evidence refs')
        if self.identity_relevant:
            text(self.identity_relevance_reason, 'identity relevance reason')
            if not self.identity_relevance_evidence_refs:
                raise ValueError('Identity relevance requires evidence references')
        elif self.identity_relevance_reason is not None and not isinstance(self.identity_relevance_reason, str):
            raise ValueError('Identity relevance reason must be text or null')

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "method": self.method.value,
            "artifact": self.artifact,
            "artifact_hash": self.artifact_hash,
            "limitations": self.limitations,
            "timestamp": self.timestamp,
            "identity_relevant": self.identity_relevant,
            "identity_relevance_reason": self.identity_relevance_reason,
            "identity_relevance_evidence_refs": list(self.identity_relevance_evidence_refs),
        }


@dataclass(frozen=True)
class EvidenceLink:
    claim_id: str
    evidence_id: str
    relation: EvidenceRelation
    scope_fit: ScopeFit
    submitted_by: str
    submitted_at: str = field(default_factory=now_iso)
    notes: str | None = None
    operation_id: str = field(default_factory=lambda: f"op_{uuid4().hex[:16]}")

    def validate(self) -> None:
        for name in ('claim_id', 'evidence_id', 'submitted_by', 'operation_id'):
            text(getattr(self, name), name)
        if not isinstance(self.relation, EvidenceRelation) or not isinstance(self.scope_fit, ScopeFit):
            raise ValueError('Invalid evidence relation or scope')
        timestamp(self.submitted_at, 'submitted_at')
        if self.notes is not None and not isinstance(self.notes, str): raise ValueError('notes must be text or null')

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "relation": self.relation.value,
            "scope_fit": self.scope_fit.value,
            "submitted_by": self.submitted_by,
            "submitted_at": self.submitted_at,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Proposal:
    actor_id: str
    role_class: str
    text: str
    about_claim: str | None = None
    submitted_at: str = field(default_factory=now_iso)
    proposal_id: str = field(default_factory=lambda: f"pr_{uuid4().hex[:16]}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "actor_id": self.actor_id,
            "role_class": self.role_class,
            "text": self.text,
            "about_claim": self.about_claim,
            "submitted_at": self.submitted_at,
        }


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    proposition: str
    question_plane: QuestionPlane
    created_at: str
    created_by: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimState:
    claim_id: str
    proposition: str
    question_plane: QuestionPlane
    basis: BasisClass
    verdict: Verdict
    version: int
    created_at: str
    updated_at: str
    evidence_refs: tuple[str, ...] = ()
    counterevidence_refs: tuple[str, ...] = ()
    contextual_evidence_refs: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    predecessor: str | None = None
    supersession_reason: str | None = None
    adjudicator_version: str = "forge-adjudicator-0.1"
    confidence: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "proposition": self.proposition,
            "question_plane": self.question_plane.value,
            "basis": self.basis.value,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "version": self.version,
            "predecessor": self.predecessor,
            "supersession_reason": self.supersession_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "evidence_refs": list(self.evidence_refs),
            "counterevidence_refs": list(self.counterevidence_refs),
            "contextual_evidence_refs": list(self.contextual_evidence_refs),
            "dependencies": list(self.dependencies),
            "adjudicator_version": self.adjudicator_version,
        }


@dataclass(frozen=True)
class PolicyRule:
    policy_id: str
    version: str
    allowed_verdicts: tuple[Verdict, ...]
    require_human_acceptance: bool = False
    deny_on_unknown: bool = True
    deny_on_unresolved: bool = True
    require_decision_record: bool = False

    def validate(self) -> None:
        text(self.policy_id, 'policy_id'); text(self.version, 'policy version')
        if not isinstance(self.allowed_verdicts, tuple) or not self.allowed_verdicts:
            raise ValueError('allowed_verdicts must be a nonempty tuple')
        if any(not isinstance(v, Verdict) for v in self.allowed_verdicts) or len(set(self.allowed_verdicts)) != len(self.allowed_verdicts):
            raise ValueError('Invalid or duplicate allowed verdicts')
        for name in ('require_human_acceptance', 'deny_on_unknown', 'deny_on_unresolved', 'require_decision_record'):
            if type(getattr(self, name)) is not bool: raise ValueError(f'{name} must be boolean')


@dataclass(frozen=True)
class ContextReceipt:
    receipt_id: str
    actor_id: str
    task_id: str
    state_fingerprint: str
    claim_versions: dict[str, int]
    policy_id: str
    policy_version: str
    issued_at: str
    expires_at: str
    receipt_hash: str


@dataclass(frozen=True)
class Permit:
    permit_id: str
    actor_id: str
    action: str
    allowed: bool
    reason: str
    state_fingerprint: str
    claim_versions: dict[str, int]
    policy_id: str
    policy_version: str
    context_receipt_hash: str
    issued_at: str
    expires_at: str
