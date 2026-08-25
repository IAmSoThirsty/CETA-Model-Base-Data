from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping


EPISTEMIC_OBJECT_TYPES = frozenset({
    "UNIVERSE",
    "BELIEF",
    "EVIDENCE",
    "CLAIM",
    "OBSERVATION",
    "RULE",
    "GOAL",
    "AUTHORITY",
    "ACTION",
})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def domain_hash(value: Any, *, domain: str) -> str:
    payload = (domain + "\n" + canonical_json(value)).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class HistoryBindingError(ValueError):
    pass


@dataclass(frozen=True)
class EpistemicObject:
    """Immutable CETA object value.

    Content is retained as canonical JSON text so callers cannot mutate a
    dictionary after admission and thereby change the object behind its ID.
    """

    object_id: str
    object_type: str
    content_json: str
    object_hash: str

    @classmethod
    def create(cls, *, object_id: str, object_type: str, content: Mapping[str, Any]) -> "EpistemicObject":
        if not isinstance(object_id, str) or not object_id.strip():
            raise HistoryBindingError("object_id must be a non-empty string")
        normalized_type = str(object_type).upper()
        if normalized_type not in EPISTEMIC_OBJECT_TYPES:
            raise HistoryBindingError(f"unknown CETA object type: {object_type}")
        if not isinstance(content, Mapping):
            raise HistoryBindingError("object content must be a mapping")
        content_copy = dict(content)
        content_json = canonical_json(content_copy)
        object_hash = domain_hash(
            {"object_id": object_id, "object_type": normalized_type, "content": content_copy},
            domain="CETA/EPISTEMIC_OBJECT/v1",
        )
        return cls(object_id, normalized_type, content_json, object_hash)

    @property
    def content(self) -> dict[str, Any]:
        return json.loads(self.content_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "content": self.content,
            "object_hash": self.object_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EpistemicObject":
        obj = cls.create(
            object_id=str(data["object_id"]),
            object_type=str(data["object_type"]),
            content=data["content"],
        )
        if data.get("object_hash") != obj.object_hash:
            raise HistoryBindingError(f"object hash mismatch: {obj.object_id}")
        return obj


@dataclass(frozen=True)
class Supersession:
    old_object_id: str
    new_object_id: str

    def __post_init__(self) -> None:
        if not self.old_object_id or not self.new_object_id:
            raise HistoryBindingError("supersession object IDs must be non-empty")
        if self.old_object_id == self.new_object_id:
            raise HistoryBindingError("an object cannot supersede itself")

    def to_dict(self) -> dict[str, str]:
        return {"old_object_id": self.old_object_id, "new_object_id": self.new_object_id}


@dataclass(frozen=True)
class StateDelta:
    creates: tuple[EpistemicObject, ...] = ()
    supersedes: tuple[Supersession, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "creates": [obj.to_dict() for obj in self.creates],
            "supersedes": [edge.to_dict() for edge in self.supersedes],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateDelta":
        if set(data) != {"creates", "supersedes"}:
            raise HistoryBindingError("state delta must contain exactly creates and supersedes")
        return cls(
            creates=tuple(EpistemicObject.from_dict(x) for x in data["creates"]),
            supersedes=tuple(Supersession(**x) for x in data["supersedes"]),
        )


@dataclass(frozen=True)
class CommitCandidate:
    """Complete runtime-owned transition submitted to the canonical ledger.

    This is not a network output. The proposal fields are present for replay,
    while output state, proof, verification, and replay are runtime-owned data.
    """

    transition_id: str
    input_state_ref: str
    operation: str
    operands_json: str
    proposer_id: str
    constitutional_epoch: str
    vm_decision_hash: str
    output_state_ref: str
    state_delta: StateDelta
    proof_json: str
    verification_json: str
    replay_record_json: str

    @classmethod
    def create(
        cls,
        *,
        transition_id: str,
        input_state_ref: str,
        operation: str,
        operands: Mapping[str, Any],
        proposer_id: str,
        constitutional_epoch: str,
        vm_decision_hash: str,
        output_state_ref: str,
        state_delta: StateDelta,
        proof: Mapping[str, Any],
        verification: Mapping[str, Any],
        replay_record: Mapping[str, Any],
    ) -> "CommitCandidate":
        string_fields = {
            "transition_id": transition_id,
            "input_state_ref": input_state_ref,
            "operation": operation,
            "proposer_id": proposer_id,
            "constitutional_epoch": constitutional_epoch,
            "vm_decision_hash": vm_decision_hash,
            "output_state_ref": output_state_ref,
        }
        for name, value in string_fields.items():
            if not isinstance(value, str) or not value.strip():
                raise HistoryBindingError(f"{name} must be a non-empty string")
        for name, value in {
            "operands": operands,
            "proof": proof,
            "verification": verification,
            "replay_record": replay_record,
        }.items():
            if not isinstance(value, Mapping):
                raise HistoryBindingError(f"{name} must be a mapping")
        if not proof or not verification or not replay_record:
            raise HistoryBindingError("proof, verification, and replay record are required")
        return cls(
            transition_id=transition_id,
            input_state_ref=input_state_ref,
            operation=operation,
            operands_json=canonical_json(dict(operands)),
            proposer_id=proposer_id,
            constitutional_epoch=constitutional_epoch,
            vm_decision_hash=vm_decision_hash,
            output_state_ref=output_state_ref,
            state_delta=state_delta,
            proof_json=canonical_json(dict(proof)),
            verification_json=canonical_json(dict(verification)),
            replay_record_json=canonical_json(dict(replay_record)),
        )

    @property
    def operands(self) -> dict[str, Any]:
        return json.loads(self.operands_json)

    @property
    def proof(self) -> dict[str, Any]:
        return json.loads(self.proof_json)

    @property
    def verification(self) -> dict[str, Any]:
        return json.loads(self.verification_json)

    @property
    def replay_record(self) -> dict[str, Any]:
        return json.loads(self.replay_record_json)
