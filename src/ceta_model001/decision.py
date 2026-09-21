from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .validation import digest, text, timestamp, unique_strings


class DecisionRecordError(RuntimeError):
    """Raised when a decision record fails validation or violates invariants."""
    pass


@dataclass(frozen=True)
class KnownFact:
    claim_id: str
    version: int

    def as_dict(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "version": self.version}


@dataclass(frozen=True)
class Uncertainty:
    description: str
    material: bool
    claim_ref: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "material": self.material,
            "claim_ref": self.claim_ref,
        }


@dataclass(frozen=True)
class Alternative:
    alternative_id: str
    description: str
    disposition: str  # SELECTED, REJECTED, DEFERRED
    reason_code: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "alternative_id": self.alternative_id,
            "description": self.description,
            "disposition": self.disposition,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class ChosenAction:
    action_id: str
    description: str
    effect_class: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "description": self.description,
            "effect_class": self.effect_class,
        }


@dataclass(frozen=True)
class AuthorityRef:
    authority_id: str
    capability: str
    scope: tuple[str, ...]
    authority_hash: str
    expires_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "authority_id": self.authority_id,
            "capability": self.capability,
            "scope": list(self.scope),
            "authority_hash": self.authority_hash,
            "expires_at": self.expires_at,
        }
        return res


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    task_id: str
    actor_id: str
    proposal_refs: tuple[str, ...]
    state_fingerprint: str
    context_receipt_id: str
    known_facts: tuple[KnownFact, ...]
    claims_relied_upon: tuple[KnownFact, ...]
    uncertainties: tuple[Uncertainty, ...]
    alternatives_considered: tuple[Alternative, ...]
    chosen_action: ChosenAction
    reason_code: str
    authority: AuthorityRef
    evidence_refs: tuple[str, ...]
    recorded_at: str
    schema_version: str = "0.1"
    public_rationale: str | None = None
    supersedes_decision_id: str | None = None

    def validate(self) -> None:
        text(self.decision_id, "decision_id")
        text(self.task_id, "task_id")
        text(self.actor_id, "actor_id")
        if not self.proposal_refs:
            raise DecisionRecordError("proposal_refs must contain at least one reference")
        unique_strings(self.proposal_refs, "proposal_refs")
        digest(self.state_fingerprint, "state_fingerprint")
        text(self.context_receipt_id, "context_receipt_id")
        timestamp(self.recorded_at, "recorded_at")
        text(self.reason_code, "reason_code")
        digest(self.authority.authority_hash, "authority.authority_hash")
        unique_strings(self.evidence_refs, "evidence_refs")

        # Verify chosen action matches exactly one selected alternative
        selected = [alt for alt in self.alternatives_considered if alt.disposition == "SELECTED"]
        if len(selected) != 1:
            raise DecisionRecordError("Exactly one alternative must have disposition='SELECTED'")

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "decision_id": self.decision_id,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "actor_id": self.actor_id,
            "proposal_refs": list(self.proposal_refs),
            "state_fingerprint": self.state_fingerprint,
            "context_receipt_id": self.context_receipt_id,
            "known_facts": [f.as_dict() for f in self.known_facts],
            "claims_relied_upon": [f.as_dict() for f in self.claims_relied_upon],
            "uncertainties": [u.as_dict() for u in self.uncertainties],
            "alternatives_considered": [a.as_dict() for a in self.alternatives_considered],
            "chosen_action": self.chosen_action.as_dict(),
            "reason_code": self.reason_code,
            "authority": self.authority.as_dict(),
            "evidence_refs": list(self.evidence_refs),
            "recorded_at": self.recorded_at,
        }
        if self.public_rationale is not None:
            data["public_rationale"] = self.public_rationale
        if self.supersedes_decision_id is not None:
            data["supersedes_decision_id"] = self.supersedes_decision_id
        return data


class DecisionEngine:
    """Manages the creation, verification, and ledger recording of DecisionRecords.

    Enforces: NO DecisionRecord -> NO consequential Permit.
    """
    def __init__(self, ledger):
        self.ledger = ledger

    def record_decision(self, decision: DecisionRecord) -> DecisionRecord:
        decision.validate()
        with self.ledger.transaction():
            records = self.ledger.records()
            # Verify no duplicate decision_id
            for rec in records:
                if rec["event_type"] == "DECISION_RECORDED":
                    p = rec["payload"]
                    if p.get("decision_id") == decision.decision_id:
                        raise DecisionRecordError(f"Duplicate decision_id: {decision.decision_id}")

            self.ledger.append(
                event_type="DECISION_RECORDED",
                actor_id=decision.actor_id,
                task_id=decision.task_id,
                payload=decision.as_dict(),
            )
            return decision

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        with self.ledger.transaction():
            for rec in reversed(self.ledger.records()):
                if rec["event_type"] == "DECISION_RECORDED":
                    p = rec["payload"]
                    if p.get("decision_id") == decision_id:
                        return DecisionRecord(
                            decision_id=p["decision_id"],
                            task_id=p["task_id"],
                            actor_id=p["actor_id"],
                            proposal_refs=tuple(p["proposal_refs"]),
                            state_fingerprint=p["state_fingerprint"],
                            context_receipt_id=p["context_receipt_id"],
                            known_facts=tuple(KnownFact(**f) for f in p["known_facts"]),
                            claims_relied_upon=tuple(KnownFact(**f) for f in p["claims_relied_upon"]),
                            uncertainties=tuple(Uncertainty(**u) for u in p["uncertainties"]),
                            alternatives_considered=tuple(Alternative(**a) for a in p["alternatives_considered"]),
                            chosen_action=ChosenAction(**p["chosen_action"]),
                            reason_code=p["reason_code"],
                            authority=AuthorityRef(
                                authority_id=p["authority"]["authority_id"],
                                capability=p["authority"]["capability"],
                                scope=tuple(p["authority"]["scope"]),
                                authority_hash=p["authority"]["authority_hash"],
                                expires_at=p["authority"].get("expires_at"),
                            ),
                            evidence_refs=tuple(p["evidence_refs"]),
                            recorded_at=p["recorded_at"],
                            schema_version=p.get("schema_version", "0.1"),
                            public_rationale=p.get("public_rationale"),
                            supersedes_decision_id=p.get("supersedes_decision_id"),
                        )
            return None
