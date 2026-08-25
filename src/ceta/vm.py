from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Iterable

from history import EpistemicObject, ProjectionSnapshot, StateDelta, Supersession, domain_hash
from .model import TransitionProposal, VmDecision, VmDisposition

ROOT = Path(__file__).resolve().parents[2]


class ConstitutionalVM:
    """Deterministic CETA legality engine.

    The VM receives an immutable state projection plus explicit evidence,
    identity and authority views. It never executes external effects and never
    commits state. For legal transitions it computes the exact StateDelta and
    proof/verification obligations that the runtime must satisfy before the
    TransitionLedger can commit anything.
    """

    def __init__(self, contract_path: Path | None = None) -> None:
        path = contract_path or ROOT / "registry" / "operation_contracts.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._contracts = {x["operation"]: x for x in raw["contracts"]}
        self._handlers = {
            "Observe": self._observe,
            "ValidateObservation": self._validate_observation,
            "AdmitEvidence": self._admit_evidence,
            "RejectEvidence": self._reject_evidence,
            "CreateClaim": self._create_claim,
            "CreateBelief": self._create_belief,
            "Support": self._support,
            "Contradict": self._contradict,
            "Undercut": self._undercut,
            "Merge": self._merge,
            "Split": self._split,
            "NarrowScope": self._narrow_scope,
            "ExpandScope": self._expand_scope,
            "Verify": self._verify,
            "Invalidate": self._invalidate,
            "Suspend": self._suspend,
            "Expire": self._expire,
            "Reevaluate": self._reevaluate,
            "Adjudicate": self._adjudicate,
            "Authorize": self._authorize,
            "RejectAuthorization": self._reject_authorization,
            "Execute": self._execute,
            "Rollback": self._rollback,
        }

    def evaluate(
        self,
        proposal: TransitionProposal,
        *,
        projected_snapshot: ProjectionSnapshot | None = None,
        projected_state_ref: str | None = None,
        admitted_evidence_view: Mapping[str, Any] | None = None,
        authority_snapshot: Mapping[str, Any] | None = None,
        identity_view: Mapping[str, Any] | None = None,
        now_epoch_ms: int | None = None,
        constitutional_epoch: str = "",
    ) -> VmDecision:
        state_ref = projected_snapshot.state_ref if projected_snapshot is not None else projected_state_ref
        if not state_ref:
            return self._halt(proposal, "PROJECTED_STATE_REQUIRED", "")
        if proposal.input_state_ref != state_ref:
            return self._halt(proposal, "INPUT_STATE_REFERENCE_MISMATCH", "")
        contract = self._contracts.get(proposal.operation)
        if contract is None:
            return self._halt(proposal, "UNKNOWN_CETA_OPCODE", "")
        contract_hash = domain_hash(contract, domain="CETA/OPERATION_CONTRACT/v1")
        if contract.get("status") != "BOUND":
            return self._halt(proposal, "CETA_OPERATION_CONTRACT_UNBOUND", contract_hash)
        if projected_snapshot is None:
            return self._halt(proposal, "PROJECTED_STATE_SNAPSHOT_REQUIRED", contract_hash)
        handler = self._handlers.get(proposal.operation)
        if handler is None:
            return self._halt(proposal, "BOUND_CONTRACT_HANDLER_NOT_IMPLEMENTED", contract_hash)
        context = {
            "snapshot": projected_snapshot,
            "objects": {obj.object_id: obj for obj in projected_snapshot.active_objects},
            "evidence": dict(admitted_evidence_view or {}),
            "authority": dict(authority_snapshot or {}),
            "identity": dict(identity_view or {}),
            "now_epoch_ms": now_epoch_ms,
            "constitutional_epoch": constitutional_epoch,
            "contract": contract,
            "contract_hash": contract_hash,
        }
        try:
            return handler(proposal, context).with_hash()
        except _Deny as exc:
            return self._decision(proposal, context, VmDisposition.DENY, exc.code).with_hash()
        except _Escalate as exc:
            return self._decision(proposal, context, VmDisposition.ESCALATE, exc.code).with_hash()
        except _Halt as exc:
            return self._decision(proposal, context, VmDisposition.HALT, exc.code).with_hash()
        except (KeyError, TypeError, ValueError) as exc:
            return self._decision(proposal, context, VmDisposition.HALT, f"OPERAND_BINDING_ERROR:{type(exc).__name__}").with_hash()

    # ---------- CETA operations ----------

    def _observe(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"observation_id", "source_id", "payload", "compiler_id", "payload_hash"})
        self._new_id(o["observation_id"], c)
        payload = self._mapping(o["payload"], "payload")
        expected = domain_hash(payload, domain="CETA/OBSERVATION_PAYLOAD/v1")
        if o["payload_hash"] != expected:
            raise _Halt("OBSERVATION_PAYLOAD_HASH_MISMATCH")
        obj = EpistemicObject.create(
            object_id=self._string(o["observation_id"], "observation_id"),
            object_type="OBSERVATION",
            content={
                "status": "OBSERVED",
                "source_id": self._string(o["source_id"], "source_id"),
                "compiler_id": self._string(o["compiler_id"], "compiler_id"),
                "payload": payload,
                "payload_hash": expected,
            },
        )
        return self._legal(p, c, StateDelta((obj,), ()), ("SOURCE_BINDING", "PAYLOAD_HASH_BINDING"))

    def _validate_observation(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"observation_ref", "replacement_id", "validator_id", "validation_code", "evidence_refs"})
        old = self._active(o["observation_ref"], c, "OBSERVATION")
        if old.content.get("status") != "OBSERVED":
            raise _Deny("OBSERVATION_NOT_IN_RAW_STATE")
        evidence_refs = self._admitted_state_evidence_refs(o["evidence_refs"], c, allow_empty=True)
        new = self._replacement(
            old,
            o["replacement_id"],
            {
                "status": "VALIDATED",
                "validation": {
                    "validator_id": self._string(o["validator_id"], "validator_id"),
                    "validation_code": self._string(o["validation_code"], "validation_code"),
                    "evidence_refs": list(evidence_refs),
                },
            },
            c,
        )
        return self._legal(p, c, StateDelta((new,), (Supersession(old.object_id, new.object_id),)), ("VALIDATOR_BINDING",))

    def _admit_evidence(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"evidence_id", "evidence_record_id", "observation_refs"})
        self._new_id(o["evidence_id"], c)
        record_id = self._string(o["evidence_record_id"], "evidence_record_id")
        try:
            record = dict(c["evidence"][record_id])
        except KeyError as exc:
            raise _Halt("EVIDENCE_RECORD_NOT_IN_BOUND_VIEW") from exc
        if record.get("status") != "VALIDATED":
            raise _Deny("EVIDENCE_RECORD_NOT_VALIDATED")
        observations = tuple(self._active(ref, c, "OBSERVATION") for ref in self._string_list(o["observation_refs"], "observation_refs", allow_empty=True))
        for obs in observations:
            if obs.content.get("status") != "VALIDATED":
                raise _Deny("EVIDENCE_OBSERVATION_NOT_VALIDATED")
        obj = EpistemicObject.create(
            object_id=o["evidence_id"],
            object_type="EVIDENCE",
            content={
                "status": "ADMITTED",
                "evidence_record_id": record_id,
                "evidence_record_hash": record.get("record_hash"),
                "payload_hash": record.get("payload_hash"),
                "provenance_refs": list(record.get("provenance_refs", [])),
                "observation_refs": [x.object_id for x in observations],
            },
        )
        return self._legal(p, c, StateDelta((obj,), ()), ("EVIDENCE_RECORD_HASH_BINDING", "PROVENANCE_BINDING"))

    def _reject_evidence(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"evidence_id", "evidence_record_id", "reason_code"})
        self._new_id(o["evidence_id"], c)
        record_id = self._string(o["evidence_record_id"], "evidence_record_id")
        try:
            record = dict(c["evidence"][record_id])
        except KeyError as exc:
            raise _Halt("EVIDENCE_RECORD_NOT_IN_BOUND_VIEW") from exc
        if record.get("status") != "REJECTED":
            raise _Deny("EVIDENCE_RECORD_NOT_REJECTED")
        obj = EpistemicObject.create(
            object_id=o["evidence_id"],
            object_type="EVIDENCE",
            content={
                "status": "REJECTED",
                "reason_code": self._string(o["reason_code"], "reason_code"),
                "evidence_record_id": record_id,
                "evidence_record_hash": record.get("record_hash"),
                "payload_hash": record.get("payload_hash"),
                "provenance_refs": list(record.get("provenance_refs", [])),
            },
        )
        return self._legal(p, c, StateDelta((obj,), ()), ("EVIDENCE_REJECTION_BINDING",))

    def _create_claim(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"claim_id", "proposition", "scope"})
        self._new_id(o["claim_id"], c)
        proposition = self._mapping(o["proposition"], "proposition")
        if not proposition:
            raise _Deny("EMPTY_STRUCTURED_PROPOSITION")
        scope = self._normalize_scope(o["scope"])
        obj = EpistemicObject.create(
            object_id=o["claim_id"],
            object_type="CLAIM",
            content={"status": "ACTIVE", "verification_status": "UNVERIFIED", "proposition": proposition, "scope": scope},
        )
        return self._legal(p, c, StateDelta((obj,), ()), ("STRUCTURED_PROPOSITION_BINDING", "SCOPE_BINDING"))

    def _create_belief(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"belief_id", "claim_ref"})
        self._new_id(o["belief_id"], c)
        claim = self._active(o["claim_ref"], c, "CLAIM")
        if claim.content.get("status") != "ACTIVE":
            raise _Deny("CLAIM_NOT_ACTIVE")
        obj = EpistemicObject.create(
            object_id=o["belief_id"],
            object_type="BELIEF",
            content={
                "status": "ACTIVE",
                "verification_status": "UNVERIFIED",
                "claim_ref": claim.object_id,
                "scope": claim.content.get("scope", {}),
                "support_refs": [],
                "contradiction_refs": [],
                "undercut_refs": [],
                "epistemic_status": "OPEN",
            },
        )
        return self._legal(p, c, StateDelta((obj,), ()), ("CLAIM_BINDING",))

    def _support(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        return self._relate_belief(p, c, relation="support_refs", status="SUPPORTED")

    def _contradict(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        return self._relate_belief(p, c, relation="contradiction_refs", status="CONTESTED")

    def _undercut(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        return self._relate_belief(p, c, relation="undercut_refs", status="UNDERCUT")

    def _merge(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"object_refs", "merged_id", "strategy"})
        refs = self._string_list(o["object_refs"], "object_refs")
        if len(refs) < 2 or len(set(refs)) != len(refs):
            raise _Deny("MERGE_REQUIRES_DISTINCT_MULTIPLE_OBJECTS")
        objects = [self._active(ref, c) for ref in refs]
        types = {obj.object_type for obj in objects}
        if len(types) != 1:
            raise _Deny("MERGE_TYPE_MISMATCH")
        if o["strategy"] != "IDENTICAL_OR_SET_UNION":
            raise _Deny("UNSUPPORTED_MERGE_STRATEGY")
        merged: dict[str, Any] = {}
        for obj in objects:
            for key, value in obj.content.items():
                if key not in merged:
                    merged[key] = value
                elif merged[key] == value:
                    continue
                elif isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = sorted({json.dumps(x, sort_keys=True) for x in merged[key] + value})
                    merged[key] = [json.loads(x) for x in merged[key]]
                else:
                    raise _Escalate("MERGE_CONFLICT_REQUIRES_ADJUDICATION")
        merged["merged_from"] = list(refs)
        new = EpistemicObject.create(object_id=self._new_id(o["merged_id"], c), object_type=objects[0].object_type, content=merged)
        edges = tuple(Supersession(obj.object_id, new.object_id) for obj in objects)
        return self._legal(p, c, StateDelta((new,), edges), ("MERGE_INPUT_BINDING", "NO_SCALAR_CONFLICT"))

    def _split(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"object_ref", "partitions"})
        source = self._active(o["object_ref"], c)
        partitions = o["partitions"]
        if not isinstance(partitions, list) or len(partitions) < 2:
            raise _Deny("SPLIT_REQUIRES_MULTIPLE_PARTITIONS")
        source_keys = set(source.content)
        used: set[str] = set()
        created = []
        edges = []
        for part in partitions:
            if not isinstance(part, Mapping) or set(part) != {"object_id", "keys"}:
                raise _Halt("SPLIT_PARTITION_SHAPE_INVALID")
            keys = set(self._string_list(part["keys"], "partition.keys"))
            if not keys or not keys.issubset(source_keys) or used.intersection(keys):
                raise _Deny("SPLIT_PARTITION_KEYS_INVALID")
            used.update(keys)
            content = {key: source.content[key] for key in sorted(keys)}
            content["split_from"] = source.object_id
            obj = EpistemicObject.create(object_id=self._new_id(part["object_id"], c), object_type=source.object_type, content=content)
            created.append(obj)
            edges.append(Supersession(source.object_id, obj.object_id))
        if used != source_keys:
            raise _Deny("SPLIT_MUST_PRESERVE_ALL_SOURCE_FIELDS")
        return self._legal(p, c, StateDelta(tuple(created), tuple(edges)), ("SPLIT_PARTITION_CONSERVATION",))

    def _narrow_scope(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        return self._scope_change(p, c, narrow=True)

    def _expand_scope(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        self._require_capability(c, "scope_expand")
        return self._scope_change(p, c, narrow=False, required_authority=("scope_expand",))

    def _verify(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"target_ref", "replacement_id", "evidence_refs", "verification_code"})
        target = self._active(o["target_ref"], c)
        if target.object_type not in {"CLAIM", "BELIEF", "ACTION"}:
            raise _Deny("OBJECT_TYPE_NOT_VERIFIABLE_BY_CETA_VERIFY")
        evidence_refs = self._admitted_state_evidence_refs(o["evidence_refs"], c)
        if target.object_type == "BELIEF":
            content = target.content
            if content.get("contradiction_refs") or content.get("undercut_refs"):
                raise _Deny("BELIEF_HAS_ACTIVE_DEFEATERS")
            if not set(evidence_refs).intersection(content.get("support_refs", [])):
                raise _Deny("VERIFICATION_EVIDENCE_NOT_BOUND_AS_SUPPORT")
        new = self._replacement(
            target,
            o["replacement_id"],
            {
                "verification_status": "VERIFIED",
                "verification_code": self._string(o["verification_code"], "verification_code"),
                "verification_evidence_refs": list(evidence_refs),
            },
            c,
        )
        return self._legal(p, c, StateDelta((new,), (Supersession(target.object_id, new.object_id),)), ("SEMANTIC_VERIFICATION_EVIDENCE_BINDING",))

    def _invalidate(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"target_ref", "replacement_id", "reason_code", "evidence_refs"})
        target = self._active(o["target_ref"], c)
        evidence_refs = self._admitted_state_evidence_refs(o["evidence_refs"], c, allow_empty=True)
        new = self._replacement(target, o["replacement_id"], {
            "status": "INVALIDATED",
            "verification_status": "INVALID",
            "invalidation_reason_code": self._string(o["reason_code"], "reason_code"),
            "invalidation_evidence_refs": list(evidence_refs),
        }, c)
        return self._legal(p, c, StateDelta((new,), (Supersession(target.object_id, new.object_id),)), ("INVALIDATION_REASON_BINDING",))

    def _suspend(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"target_ref", "replacement_id", "reason_code", "evidence_refs"})
        target = self._active(o["target_ref"], c)
        evidence_refs = self._admitted_state_evidence_refs(o["evidence_refs"], c, allow_empty=True)
        new = self._replacement(target, o["replacement_id"], {
            "status": "SUSPENDED",
            "suspension_reason_code": self._string(o["reason_code"], "reason_code"),
            "suspension_evidence_refs": list(evidence_refs),
        }, c)
        return self._legal(p, c, StateDelta((new,), (Supersession(target.object_id, new.object_id),)), ("SUSPENSION_REASON_BINDING",))

    def _expire(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"target_ref", "replacement_id", "trusted_time_evidence_ref"})
        target = self._active(o["target_ref"], c)
        expiry = target.content.get("expires_at_epoch_ms")
        if not isinstance(expiry, int):
            raise _Deny("TARGET_HAS_NO_MACHINE_EXPIRY")
        time_ref = self._string(o["trusted_time_evidence_ref"], "trusted_time_evidence_ref")
        record = c["evidence"].get(time_ref)
        if not isinstance(record, Mapping) or record.get("status") != "VALIDATED":
            raise _Halt("TRUSTED_TIME_EVIDENCE_NOT_VALIDATED")
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or payload.get("kind") != "trusted_time" or not isinstance(payload.get("epoch_ms"), int):
            raise _Halt("TRUSTED_TIME_EVIDENCE_SHAPE_INVALID")
        if payload["epoch_ms"] < expiry:
            raise _Deny("TARGET_NOT_EXPIRED")
        new = self._replacement(target, o["replacement_id"], {
            "status": "EXPIRED",
            "expired_at_epoch_ms": payload["epoch_ms"],
            "trusted_time_evidence_ref": time_ref,
        }, c)
        return self._legal(p, c, StateDelta((new,), (Supersession(target.object_id, new.object_id),)), ("TRUSTED_TIME_BINDING",))

    def _reevaluate(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"target_ref", "replacement_id", "trigger_evidence_refs"})
        target = self._active(o["target_ref"], c)
        if target.content.get("status") not in {"SUSPENDED", "INVALIDATED", "EXPIRED", "ACTIVE"} and target.content.get("epistemic_status") not in {"CONTESTED", "UNDERCUT"}:
            raise _Deny("TARGET_NOT_IN_REEVALUATABLE_STATE")
        evidence_refs = self._admitted_state_evidence_refs(o["trigger_evidence_refs"], c)
        updates = {
            "status": "ACTIVE",
            "verification_status": "UNVERIFIED",
            "reevaluation_trigger_refs": list(evidence_refs),
        }
        if target.object_type == "BELIEF":
            tc = target.content
            if tc.get("undercut_refs"):
                updates["epistemic_status"] = "UNDERCUT"
            elif tc.get("contradiction_refs"):
                updates["epistemic_status"] = "CONTESTED"
            elif tc.get("support_refs"):
                updates["epistemic_status"] = "SUPPORTED"
            else:
                updates["epistemic_status"] = "OPEN"
        new = self._replacement(target, o["replacement_id"], updates, c)
        return self._legal(p, c, StateDelta((new,), (Supersession(target.object_id, new.object_id),)), ("REEVALUATION_TRIGGER_BINDING",))

    def _adjudicate(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        self._require_capability(c, "adjudicate")
        o = self._exact_operands(p, {"target_ref", "replacement_id", "outcome", "evidence_refs", "adjudication_code"})
        target = self._active(o["target_ref"], c)
        outcome = self._string(o["outcome"], "outcome")
        allowed = {"ACTIVE", "SUSPENDED", "INVALIDATED"}
        if outcome not in allowed:
            raise _Deny("ADJUDICATION_OUTCOME_NOT_ALLOWED")
        evidence_refs = self._admitted_state_evidence_refs(o["evidence_refs"], c)
        new = self._replacement(target, o["replacement_id"], {
            "status": outcome,
            "adjudication_code": self._string(o["adjudication_code"], "adjudication_code"),
            "adjudication_evidence_refs": list(evidence_refs),
        }, c)
        return self._legal(p, c, StateDelta((new,), (Supersession(target.object_id, new.object_id),)), ("ADJUDICATION_AUTHORITY", "ADJUDICATION_EVIDENCE_BINDING"), required_authority=("adjudicate",))

    def _authorize(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        self._require_capability(c, "authorize")
        required = {
            "authorization_id", "permit_id", "nonce", "subject_id", "subject_scope", "operation",
            "consequence", "consumer_id", "consumer_key_id", "expires_at_epoch_ms", "source_refs",
        }
        o = self._exact_operands(p, required)
        self._new_id(o["authorization_id"], c)
        subject_id = self._string(o["subject_id"], "subject_id")
        identity = c["identity"].get(subject_id)
        if not isinstance(identity, Mapping) or identity.get("status") != "VERIFIED":
            raise _Deny("AUTHORIZATION_SUBJECT_IDENTITY_NOT_VERIFIED")
        operation = self._string(o["operation"], "operation")
        if operation not in {"Execute", "Rollback"}:
            raise _Deny("AUTHORIZATION_OPERATION_NOT_EFFECTFUL")
        consequence = self._mapping(o["consequence"], "consequence")
        consequence_hash = _canonical_consequence_hash(consequence)
        expiry = o["expires_at_epoch_ms"]
        if not isinstance(expiry, int) or c["now_epoch_ms"] is None or expiry <= c["now_epoch_ms"]:
            raise _Deny("AUTHORIZATION_EXPIRY_INVALID")
        source_refs = self._string_list(o["source_refs"], "source_refs")
        obj = EpistemicObject.create(
            object_id=o["authorization_id"],
            object_type="AUTHORITY",
            content={
                "status": "AUTHORIZED",
                "permit_id": self._string(o["permit_id"], "permit_id"),
                "nonce": self._string(o["nonce"], "nonce"),
                "subject_id": subject_id,
                "subject_scope": self._string(o["subject_scope"], "subject_scope"),
                "operation": operation,
                "consequence": consequence,
                "consequence_hash": consequence_hash,
                "consumer_id": self._string(o["consumer_id"], "consumer_id"),
                "consumer_key_id": self._string(o["consumer_key_id"], "consumer_key_id"),
                "expires_at_epoch_ms": expiry,
                "source_refs": list(source_refs),
                "identity_record_hash": identity.get("record_hash"),
            },
        )
        return self._legal(p, c, StateDelta((obj,), ()), ("AUTHORIZATION_AUTHORITY", "VERIFIED_IDENTITY_BINDING", "EXACT_CONSEQUENCE_BINDING"), required_authority=("authorize",))

    def _reject_authorization(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        o = self._exact_operands(p, {"authorization_id", "subject_id", "operation", "reason_code", "source_refs"})
        self._new_id(o["authorization_id"], c)
        obj = EpistemicObject.create(
            object_id=o["authorization_id"],
            object_type="AUTHORITY",
            content={
                "status": "REJECTED",
                "subject_id": self._string(o["subject_id"], "subject_id"),
                "operation": self._string(o["operation"], "operation"),
                "reason_code": self._string(o["reason_code"], "reason_code"),
                "source_refs": list(self._string_list(o["source_refs"], "source_refs", allow_empty=True)),
            },
        )
        return self._legal(p, c, StateDelta((obj,), ()), ("AUTHORIZATION_REJECTION_REASON_BINDING",))

    def _execute(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        return self._effect_request(p, c, expected_operation="Execute", status="EXECUTION_REQUESTED")

    def _rollback(self, p: TransitionProposal, c: dict[str, Any]) -> VmDecision:
        return self._effect_request(p, c, expected_operation="Rollback", status="ROLLBACK_REQUESTED")

    # ---------- reusable semantics ----------

    def _relate_belief(self, p: TransitionProposal, c: dict[str, Any], *, relation: str, status: str) -> VmDecision:
        o = self._exact_operands(p, {"belief_ref", "evidence_ref", "replacement_id"})
        belief = self._active(o["belief_ref"], c, "BELIEF")
        evidence = self._active(o["evidence_ref"], c, "EVIDENCE")
        if evidence.content.get("status") != "ADMITTED":
            raise _Deny("RELATION_REQUIRES_ADMITTED_EVIDENCE")
        content = belief.content
        refs = list(content.get(relation, []))
        if evidence.object_id in refs:
            raise _Deny("DUPLICATE_EVIDENCE_RELATION")
        refs.append(evidence.object_id)
        updates: dict[str, Any] = {relation: sorted(refs), "epistemic_status": status}
        if relation in {"contradiction_refs", "undercut_refs"}:
            updates["verification_status"] = "UNVERIFIED"
        if relation == "support_refs" and (content.get("contradiction_refs") or content.get("undercut_refs")):
            updates["epistemic_status"] = "CONTESTED"
        new = self._replacement(belief, o["replacement_id"], updates, c)
        return self._legal(p, c, StateDelta((new,), (Supersession(belief.object_id, new.object_id),)), ("EXACT_EVIDENCE_RELATION_BINDING",))

    def _scope_change(self, p: TransitionProposal, c: dict[str, Any], *, narrow: bool, required_authority: tuple[str, ...] = ()) -> VmDecision:
        o = self._exact_operands(p, {"target_ref", "replacement_id", "scope"})
        target = self._active(o["target_ref"], c)
        if target.object_type not in {"CLAIM", "BELIEF", "RULE", "GOAL"}:
            raise _Deny("OBJECT_TYPE_HAS_NO_CETA_SCOPE")
        old_scope = self._normalize_scope(target.content.get("scope", {}))
        new_scope = self._normalize_scope(o["scope"])
        if narrow:
            if not _is_strict_narrower(new_scope, old_scope):
                raise _Deny("SCOPE_IS_NOT_STRICTLY_NARROWER")
            proof = ("SCOPE_SUBSET_PROOF",)
        else:
            if not _is_strict_broader(new_scope, old_scope):
                raise _Deny("SCOPE_IS_NOT_STRICTLY_BROADER")
            proof = ("SCOPE_SUPERSET_PROOF", "SCOPE_EXPANSION_AUTHORITY")
        new = self._replacement(target, o["replacement_id"], {"scope": new_scope}, c)
        return self._legal(p, c, StateDelta((new,), (Supersession(target.object_id, new.object_id),)), proof, required_authority=required_authority)

    def _effect_request(self, p: TransitionProposal, c: dict[str, Any], *, expected_operation: str, status: str) -> VmDecision:
        o = self._exact_operands(p, {"action_id", "authorization_ref", "consequence"})
        self._new_id(o["action_id"], c)
        auth = self._active(o["authorization_ref"], c, "AUTHORITY")
        ac = auth.content
        if ac.get("status") != "AUTHORIZED" or ac.get("operation") != expected_operation:
            raise _Deny("AUTHORIZATION_NOT_VALID_FOR_EFFECT_OPERATION")
        consequence = self._mapping(o["consequence"], "consequence")
        if _canonical_consequence_hash(consequence) != ac.get("consequence_hash"):
            raise _Deny("EFFECT_CONSEQUENCE_DIFFERS_FROM_AUTHORIZATION")
        permit_id = ac.get("permit_id")
        permit_view = c["authority"].get("permits", {}).get(permit_id)
        if not isinstance(permit_view, Mapping):
            raise _Deny("OPERATIONAL_PERMIT_NOT_MATERIALIZED")
        if permit_view.get("status") != "ISSUED":
            raise _Deny("OPERATIONAL_PERMIT_NOT_AVAILABLE")
        if permit_view.get("operation") != expected_operation or permit_view.get("consequence_hash") != ac.get("consequence_hash"):
            raise _Halt("OPERATIONAL_PERMIT_BINDING_MISMATCH")
        if permit_view.get("consumer_id") != ac.get("consumer_id") or permit_view.get("consumer_key_id") != ac.get("consumer_key_id"):
            raise _Halt("OPERATIONAL_PERMIT_CONSUMER_BINDING_MISMATCH")
        now_ms = c.get("now_epoch_ms")
        if not isinstance(now_ms, int):
            raise _Halt("TRUSTED_EVALUATION_TIME_REQUIRED_FOR_EFFECT")
        expiry = permit_view.get("expires_at_epoch_ms")
        if not isinstance(expiry, int) or now_ms >= expiry:
            raise _Deny("OPERATIONAL_PERMIT_EXPIRED")
        action = EpistemicObject.create(
            object_id=o["action_id"],
            object_type="ACTION",
            content={
                "status": status,
                "authorization_ref": auth.object_id,
                "permit_id": ac.get("permit_id"),
                "operation": expected_operation,
                "consequence": consequence,
                "consequence_hash": ac.get("consequence_hash"),
                "verification_status": "PENDING_EXTERNAL_VERIFICATION",
            },
        )
        verification = {
            "kind": "EXTERNAL_EFFECT",
            "action_ref": action.object_id,
            "permit_id": ac.get("permit_id"),
            "consequence_hash": ac.get("consequence_hash"),
            "required_verifier_owner": "effect_verifier",
        }
        return self._legal(
            p,
            c,
            StateDelta((action,), ()),
            ("EXACT_AUTHORIZATION_BINDING", "PERMIT_CONSUMPTION_RECEIPT", "INDEPENDENT_EFFECT_VERIFICATION"),
            required_authority=(f"permit:{ac.get('permit_id')}",),
            verification_plan=verification,
        )

    # ---------- helpers ----------

    def _legal(
        self,
        p: TransitionProposal,
        c: dict[str, Any],
        delta: StateDelta,
        proof_obligations: tuple[str, ...],
        *,
        required_authority: tuple[str, ...] = (),
        verification_plan: Mapping[str, Any] | None = None,
    ) -> VmDecision:
        return self._decision(
            p,
            c,
            VmDisposition.LEGAL,
            "LEGAL",
            delta=delta,
            proof_obligations=proof_obligations,
            required_authority=required_authority,
            verification_plan=verification_plan,
        )

    def _decision(
        self,
        p: TransitionProposal,
        c: dict[str, Any],
        disposition: VmDisposition,
        reason_code: str,
        *,
        delta: StateDelta = StateDelta(),
        proof_obligations: tuple[str, ...] = (),
        required_authority: tuple[str, ...] = (),
        verification_plan: Mapping[str, Any] | None = None,
    ) -> VmDecision:
        return VmDecision(
            disposition=disposition,
            reason_code=reason_code,
            operation=p.operation,
            input_state_ref=p.input_state_ref,
            proof_obligations=proof_obligations,
            required_authority=required_authority,
            state_delta=delta,
            verification_plan=verification_plan,
            replay_plan={"operation": p.operation, "input_state_ref": p.input_state_ref},
            contract_hash=c.get("contract_hash", ""),
        )

    def _halt(self, p: TransitionProposal, code: str, contract_hash: str) -> VmDecision:
        return VmDecision(VmDisposition.HALT, code, p.operation, p.input_state_ref, contract_hash=contract_hash).with_hash()

    @staticmethod
    def _exact_operands(p: TransitionProposal, fields: set[str]) -> dict[str, Any]:
        actual = set(p.operands)
        if actual != fields:
            missing = sorted(fields - actual)
            extra = sorted(actual - fields)
            raise _Halt(f"OPERAND_SET_MISMATCH:missing={missing}:extra={extra}")
        return dict(p.operands)

    @staticmethod
    def _string(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise _Halt(f"{name.upper()}_MUST_BE_NONEMPTY_STRING")
        return value

    @staticmethod
    def _mapping(value: Any, name: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise _Halt(f"{name.upper()}_MUST_BE_MAPPING")
        return dict(value)

    @classmethod
    def _string_list(cls, value: Any, name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
        if not isinstance(value, list):
            raise _Halt(f"{name.upper()}_MUST_BE_LIST")
        refs = tuple(cls._string(x, name) for x in value)
        if not allow_empty and not refs:
            raise _Deny(f"{name.upper()}_MUST_NOT_BE_EMPTY")
        if len(set(refs)) != len(refs):
            raise _Deny(f"{name.upper()}_CONTAINS_DUPLICATES")
        return refs

    @staticmethod
    def _active(ref: Any, c: dict[str, Any], expected_type: str | None = None) -> EpistemicObject:
        if not isinstance(ref, str) or not ref.strip():
            raise _Halt("OBJECT_REFERENCE_MUST_BE_NONEMPTY_STRING")
        try:
            obj = c["objects"][ref]
        except KeyError as exc:
            raise _Deny("OBJECT_REFERENCE_NOT_ACTIVE") from exc
        if expected_type is not None and obj.object_type != expected_type:
            raise _Deny(f"OBJECT_TYPE_MISMATCH_EXPECTED_{expected_type}")
        return obj

    @staticmethod
    def _new_id(value: Any, c: dict[str, Any]) -> str:
        if not isinstance(value, str) or not value.strip():
            raise _Halt("NEW_OBJECT_ID_MUST_BE_NONEMPTY_STRING")
        if value in c["objects"]:
            raise _Deny("NEW_OBJECT_ID_ALREADY_ACTIVE")
        return value

    def _replacement(self, old: EpistemicObject, replacement_id: Any, updates: Mapping[str, Any], c: dict[str, Any]) -> EpistemicObject:
        rid = self._new_id(replacement_id, c)
        content = old.content
        content.update(dict(updates))
        content["supersedes_ref"] = old.object_id
        return EpistemicObject.create(object_id=rid, object_type=old.object_type, content=content)

    def _admitted_state_evidence_refs(self, value: Any, c: dict[str, Any], *, allow_empty: bool = False) -> tuple[str, ...]:
        refs = self._string_list(value, "evidence_refs", allow_empty=allow_empty)
        for ref in refs:
            evidence = self._active(ref, c, "EVIDENCE")
            if evidence.content.get("status") != "ADMITTED":
                raise _Deny("EVIDENCE_REFERENCE_NOT_ADMITTED")
        return refs

    @staticmethod
    def _normalize_scope(value: Any) -> dict[str, list[Any]]:
        if not isinstance(value, Mapping):
            raise _Halt("SCOPE_MUST_BE_MAPPING")
        result: dict[str, list[Any]] = {}
        for key, raw in value.items():
            if not isinstance(key, str) or not key.strip():
                raise _Halt("SCOPE_DIMENSION_MUST_BE_NONEMPTY_STRING")
            vals = raw if isinstance(raw, list) else [raw]
            if not vals:
                raise _Deny("SCOPE_DIMENSION_CANNOT_BE_EMPTY")
            for item in vals:
                if isinstance(item, (dict, list)):
                    raise _Halt("SCOPE_VALUES_MUST_BE_SCALARS")
            encoded = {json.dumps(item, sort_keys=True, separators=(",", ":")) for item in vals}
            result[key] = [json.loads(item) for item in sorted(encoded)]
        return dict(sorted(result.items()))

    @staticmethod
    def _require_capability(c: dict[str, Any], capability: str) -> None:
        caps = c["authority"].get("authorized_capabilities", [])
        if capability not in caps:
            raise _Deny(f"MISSING_REQUIRED_AUTHORITY:{capability}")


class _VmControl(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Deny(_VmControl):
    pass


class _Escalate(_VmControl):
    pass


class _Halt(_VmControl):
    pass


def _scope_sets(scope: Mapping[str, list[Any]]) -> dict[str, set[str]]:
    return {key: {json.dumps(x, sort_keys=True, separators=(",", ":")) for x in vals} for key, vals in scope.items()}


def _is_strict_narrower(new: Mapping[str, list[Any]], old: Mapping[str, list[Any]]) -> bool:
    if new == old:
        return False
    ns, os = _scope_sets(new), _scope_sets(old)
    for dim, old_vals in os.items():
        if dim not in ns:
            return False
        if "\"*\"" not in old_vals and not ns[dim].issubset(old_vals):
            return False
    return True


def _is_strict_broader(new: Mapping[str, list[Any]], old: Mapping[str, list[Any]]) -> bool:
    if new == old:
        return False
    ns, os = _scope_sets(new), _scope_sets(old)
    for dim, new_vals in ns.items():
        if dim not in os:
            return False
        if "\"*\"" not in new_vals and not os[dim].issubset(new_vals):
            return False
    return True


def _canonical_consequence_hash(consequence: Mapping[str, Any]) -> str:
    import hashlib
    raw = json.dumps(dict(consequence), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
