from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from history import StateDelta, domain_hash


class VmDisposition(StrEnum):
    LEGAL = "LEGAL"
    DENY = "DENY"
    ESCALATE = "ESCALATE"
    HALT = "HALT"


class ProposalBindingError(ValueError):
    pass


FORBIDDEN_PROPOSAL_FIELDS = frozenset({
    "output_state_ref",
    "output_state",
    "proof",
    "verification",
    "replay_record",
    "committed_transition",
    "authority_grant",
    "effect_result",
    "state_delta",
    "vm_decision_hash",
})


@dataclass(frozen=True)
class TransitionProposal:
    input_state_ref: str
    operation: str
    operands: Mapping[str, Any]
    proposer_id: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TransitionProposal":
        forbidden = FORBIDDEN_PROPOSAL_FIELDS.intersection(data)
        if forbidden:
            raise ProposalBindingError(f"proposal contains VM/runtime-owned fields: {sorted(forbidden)}")
        required = {"input_state_ref", "operation", "operands", "proposer_id"}
        missing = required.difference(data)
        extra = set(data).difference(required)
        if missing:
            raise ProposalBindingError(f"missing proposal fields: {sorted(missing)}")
        if extra:
            raise ProposalBindingError(f"unrecognized proposal fields: {sorted(extra)}")
        if not isinstance(data["operands"], Mapping):
            raise ProposalBindingError("operands must be a mapping")
        for name in ("input_state_ref", "operation", "proposer_id"):
            if not isinstance(data[name], str) or not data[name].strip():
                raise ProposalBindingError(f"{name} must be a non-empty string")
        return cls(
            input_state_ref=data["input_state_ref"],
            operation=data["operation"],
            operands=dict(data["operands"]),
            proposer_id=data["proposer_id"],
        )


@dataclass(frozen=True)
class VmDecision:
    disposition: VmDisposition
    reason_code: str
    operation: str
    input_state_ref: str
    proof_obligations: tuple[str, ...] = ()
    required_authority: tuple[str, ...] = ()
    state_delta: StateDelta = StateDelta()
    verification_plan: Mapping[str, Any] | None = None
    replay_plan: Mapping[str, Any] | None = None
    contract_hash: str = ""
    decision_hash: str = ""

    def with_hash(self) -> "VmDecision":
        body = {
            "disposition": self.disposition.value,
            "reason_code": self.reason_code,
            "operation": self.operation,
            "input_state_ref": self.input_state_ref,
            "proof_obligations": list(self.proof_obligations),
            "required_authority": list(self.required_authority),
            "state_delta": self.state_delta.to_dict(),
            "verification_plan": dict(self.verification_plan or {}),
            "replay_plan": dict(self.replay_plan or {}),
            "contract_hash": self.contract_hash,
        }
        return VmDecision(
            disposition=self.disposition,
            reason_code=self.reason_code,
            operation=self.operation,
            input_state_ref=self.input_state_ref,
            proof_obligations=self.proof_obligations,
            required_authority=self.required_authority,
            state_delta=self.state_delta,
            verification_plan=self.verification_plan,
            replay_plan=self.replay_plan,
            contract_hash=self.contract_hash,
            decision_hash=domain_hash(body, domain="CETA/VM_DECISION/v1"),
        )
