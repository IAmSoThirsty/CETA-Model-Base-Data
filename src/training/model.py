from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from ceta import TransitionProposal
from history import ProjectionSnapshot, domain_hash


def _enc(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class IllegalTransitionAlternative:
    """A proposal that must not be accepted for the same world state.

    Alternatives are executable negatives: the Constitutional VM is the oracle.
    They are not prose critiques and they do not carry runtime-owned output.
    """

    alternative_id: str
    proposal_json: str
    expected_disposition: str
    expected_reason_code: str
    failure_tags: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        alternative_id: str,
        proposal: TransitionProposal,
        expected_disposition: str,
        expected_reason_code: str,
        failure_tags: tuple[str, ...] = (),
    ) -> "IllegalTransitionAlternative":
        if expected_disposition == "LEGAL":
            raise ValueError("illegal alternative cannot expect LEGAL disposition")
        body = {
            "input_state_ref": proposal.input_state_ref,
            "operation": proposal.operation,
            "operands": dict(proposal.operands),
            "proposer_id": proposal.proposer_id,
        }
        return cls(
            alternative_id=alternative_id,
            proposal_json=_enc(body),
            expected_disposition=expected_disposition,
            expected_reason_code=expected_reason_code,
            failure_tags=tuple(sorted(set(failure_tags))),
        )

    @property
    def proposal(self) -> TransitionProposal:
        return TransitionProposal.from_mapping(json.loads(self.proposal_json))

    def to_record(self) -> dict[str, Any]:
        return {
            "alternative_id": self.alternative_id,
            "proposal": json.loads(self.proposal_json),
            "expected_disposition": self.expected_disposition,
            "expected_reason_code": self.expected_reason_code,
            "failure_tags": list(self.failure_tags),
        }


@dataclass(frozen=True)
class TransitionTrainingCase:
    case_id: str
    world_family_id: str
    world_variant_id: str
    structural_fingerprint: str
    state_ref: str
    state_json: str
    evidence_view_json: str
    identity_view_json: str
    authority_view_json: str
    proposal_context_json: str
    now_epoch_ms: int | None
    target_proposal_json: str
    illegal_alternatives_json: str = "[]"
    required_defeater_refs: tuple[str, ...] = ()
    failure_surface_tags: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        case_id: str,
        snapshot: ProjectionSnapshot,
        evidence_view: Mapping[str, Any],
        identity_view: Mapping[str, Any],
        authority_view: Mapping[str, Any],
        proposal_context: Mapping[str, Any] | None = None,
        now_epoch_ms: int | None = None,
        target: TransitionProposal,
        illegal_alternatives: tuple[IllegalTransitionAlternative, ...] = (),
        required_defeater_refs: tuple[str, ...] = (),
        failure_surface_tags: tuple[str, ...] = (),
        world_family_id: str | None = None,
        world_variant_id: str = "V000",
        structural_fingerprint: str | None = None,
    ) -> "TransitionTrainingCase":
        state = {
            "state_ref": snapshot.state_ref,
            "active_objects": [obj.to_dict() for obj in snapshot.active_objects],
            "supersessions": [edge.to_dict() for edge in snapshot.supersessions],
        }
        target_map = {
            "input_state_ref": target.input_state_ref,
            "operation": target.operation,
            "operands": dict(target.operands),
            "proposer_id": target.proposer_id,
        }
        family = world_family_id or f"LEGACY/{target.operation}"
        fingerprint = structural_fingerprint or structural_world_fingerprint(
            state=state,
            evidence_view=evidence_view,
            identity_view=identity_view,
            authority_view=authority_view,
            proposal_context=proposal_context or {},
            target_transition=target_map,
            required_defeater_count=len(required_defeater_refs),
        )
        return cls(
            case_id=case_id,
            world_family_id=family,
            world_variant_id=world_variant_id,
            structural_fingerprint=fingerprint,
            state_ref=snapshot.state_ref,
            state_json=_enc(state),
            evidence_view_json=_enc(dict(evidence_view)),
            identity_view_json=_enc(dict(identity_view)),
            authority_view_json=_enc(dict(authority_view)),
            proposal_context_json=_enc(dict(proposal_context or {})),
            now_epoch_ms=now_epoch_ms,
            target_proposal_json=_enc(target_map),
            illegal_alternatives_json=_enc([x.to_record() for x in illegal_alternatives]),
            required_defeater_refs=tuple(required_defeater_refs),
            failure_surface_tags=tuple(sorted(set(failure_surface_tags))),
        )

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "TransitionTrainingCase":
        required = {
            "case_id", "world_family_id", "world_variant_id", "structural_fingerprint",
            "state", "evidence_view", "identity_view", "authority_view", "proposal_context", "now_epoch_ms",
            "target_transition", "illegal_alternatives", "required_defeater_refs", "failure_surface_tags",
        }
        if set(record) != required:
            raise ValueError(f"training record field mismatch: missing={sorted(required-set(record))} extra={sorted(set(record)-required)}")
        state=dict(record["state"])
        return cls(
            case_id=str(record["case_id"]),
            world_family_id=str(record["world_family_id"]),
            world_variant_id=str(record["world_variant_id"]),
            structural_fingerprint=str(record["structural_fingerprint"]),
            state_ref=str(state["state_ref"]),
            state_json=_enc(state),
            evidence_view_json=_enc(record["evidence_view"]),
            identity_view_json=_enc(record["identity_view"]),
            authority_view_json=_enc(record["authority_view"]),
            proposal_context_json=_enc(record["proposal_context"]),
            now_epoch_ms=record["now_epoch_ms"],
            target_proposal_json=_enc(record["target_transition"]),
            illegal_alternatives_json=_enc(record["illegal_alternatives"]),
            required_defeater_refs=tuple(record["required_defeater_refs"]),
            failure_surface_tags=tuple(record["failure_surface_tags"]),
        )

    @property
    def target_proposal(self) -> TransitionProposal:
        return TransitionProposal.from_mapping(json.loads(self.target_proposal_json))

    @property
    def illegal_alternatives(self) -> tuple[IllegalTransitionAlternative, ...]:
        result = []
        for raw in json.loads(self.illegal_alternatives_json):
            result.append(
                IllegalTransitionAlternative(
                    alternative_id=raw["alternative_id"],
                    proposal_json=_enc(raw["proposal"]),
                    expected_disposition=raw["expected_disposition"],
                    expected_reason_code=raw["expected_reason_code"],
                    failure_tags=tuple(raw.get("failure_tags", ())),
                )
            )
        return tuple(result)

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "world_family_id": self.world_family_id,
            "world_variant_id": self.world_variant_id,
            "structural_fingerprint": self.structural_fingerprint,
            "state": json.loads(self.state_json),
            "evidence_view": json.loads(self.evidence_view_json),
            "identity_view": json.loads(self.identity_view_json),
            "authority_view": json.loads(self.authority_view_json),
            "proposal_context": json.loads(self.proposal_context_json),
            "now_epoch_ms": self.now_epoch_ms,
            "target_transition": json.loads(self.target_proposal_json),
            "illegal_alternatives": json.loads(self.illegal_alternatives_json),
            "required_defeater_refs": list(self.required_defeater_refs),
            "failure_surface_tags": list(self.failure_surface_tags),
        }


def structural_world_fingerprint(
    *,
    state: Mapping[str, Any],
    evidence_view: Mapping[str, Any],
    identity_view: Mapping[str, Any],
    authority_view: Mapping[str, Any],
    proposal_context: Mapping[str, Any],
    target_transition: Mapping[str, Any],
    required_defeater_count: int,
) -> str:
    """Fingerprint world topology without using concrete object identities.

    The purpose is leakage detection, not semantic identity. It intentionally
    records object/content shapes, status topology, scope cardinalities,
    external-view shape, target opcode, and operand shape while omitting
    arbitrary symbolic IDs and payload values.
    """

    def scalar_kind(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        return type(value).__name__

    def shape(value: Any, *, key: str = "") -> Any:
        if isinstance(value, Mapping):
            if key == "scope":
                return {
                    "scope_dims": len(value),
                    "scope_cardinalities": sorted(len(v) if isinstance(v, list) else 1 for v in value.values()),
                }
            return {str(k): shape(v, key=str(k)) for k, v in sorted(value.items(), key=lambda item: str(item[0])) if k not in {"object_id", "object_hash", "state_ref", "input_state_ref", "proposer_id"}}
        if isinstance(value, list):
            return {"list_len": len(value), "item_shapes": sorted({_enc(shape(v, key=key)) for v in value})}
        return scalar_kind(value)

    object_shapes = []
    for obj in state.get("active_objects", []):
        content = obj.get("content", {})
        object_shapes.append({
            "type": obj.get("object_type"),
            "content": shape(content),
            "status": content.get("status"),
            "verification_status": content.get("verification_status"),
            "epistemic_status": content.get("epistemic_status"),
        })
    object_shapes.sort(key=_enc)

    external_evidence_shapes = []
    for record in evidence_view.values():
        if isinstance(record, Mapping):
            external_evidence_shapes.append({
                "status": record.get("status"),
                "payload_kind": record.get("payload", {}).get("kind") if isinstance(record.get("payload"), Mapping) else None,
                "shape": shape(record),
            })
        else:
            external_evidence_shapes.append({"shape": shape(record)})
    external_evidence_shapes.sort(key=_enc)

    identity_shapes = sorted(
        [
            ({"status": v.get("status"), "shape": shape(v)} if isinstance(v, Mapping) else {"shape": shape(v)})
            for v in identity_view.values()
        ],
        key=_enc,
    )

    permits = authority_view.get("permits", {}) if isinstance(authority_view, Mapping) else {}
    permit_shapes = sorted(
        [
            ({"status": v.get("status"), "operation": v.get("operation"), "shape": shape(v)} if isinstance(v, Mapping) else {"shape": shape(v)})
            for v in permits.values()
        ],
        key=_enc,
    )

    payload = {
        "active_object_shapes": object_shapes,
        "supersession_count": len(state.get("supersessions", [])),
        "external_evidence_shapes": external_evidence_shapes,
        "identity_shapes": identity_shapes,
        "authority_capabilities": sorted(authority_view.get("authorized_capabilities", [])) if isinstance(authority_view, Mapping) else [],
        "permit_shapes": permit_shapes,
        "proposal_context_shape": shape(proposal_context),
        "target_operation": target_transition.get("operation"),
        "target_operands_shape": shape(target_transition.get("operands", {})),
        "required_defeater_count": required_defeater_count,
    }
    return domain_hash(payload, domain="CETA/TRAINING_WORLD_STRUCTURE/v1")


@dataclass(frozen=True)
class TransitionLoss:
    illegal_transition: int = 0
    missing_transition: int = 0
    invariant_violation: int = 0
    provenance_loss: int = 0
    missing_defeaters: int = 0
    improper_scope: int = 0
    illegal_authorization: int = 0
    belief_corruption: int = 0
    replay_mismatch: int = 0

    @property
    def total(self) -> int:
        return sum(self.__dict__.values())
