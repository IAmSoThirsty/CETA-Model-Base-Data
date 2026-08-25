from __future__ import annotations

from itertools import combinations
import hashlib
import json
from typing import Any, Mapping

from ceta import TransitionProposal
from history import domain_hash
from .encoder import WorldView


class CetaActionSpaceGenerator:
    """Deterministic, target-blind CETA proposal enumerator.

    This component never receives a training target or an answer label. It
    enumerates structurally possible TransitionProposal objects from the
    currently projected state plus explicit external proposal context. The
    Constitutional VM remains the legality authority; this generator performs
    no legality certification.
    """

    proposer_id = "ceta_neural_transition_policy"

    def generate(self, world: WorldView) -> tuple[TransitionProposal, ...]:
        state_ref = world.snapshot.state_ref
        objects = tuple(sorted(world.snapshot.active_objects, key=lambda x: x.object_id))
        by_type: dict[str, list[Any]] = {}
        for obj in objects:
            by_type.setdefault(obj.object_type, []).append(obj)
        candidates: list[TransitionProposal] = []

        def add(operation: str, operands: Mapping[str, Any]) -> None:
            candidates.append(TransitionProposal(state_ref, operation, dict(operands), self.proposer_id))

        context = world.proposal_context if isinstance(world.proposal_context, Mapping) else {}

        # Exogenous material: these values exist outside canonical state before
        # the corresponding transition and therefore must be explicitly bound as
        # input rather than inferred from a hidden training label.
        for i, item in enumerate(context.get("incoming_observations", ()) or ()):
            if not isinstance(item, Mapping):
                continue
            payload = dict(item.get("payload", {})) if isinstance(item.get("payload"), Mapping) else {}
            add("Observe", {
                "observation_id": self._fresh_id(world, "Observe", "observation_id", i),
                "source_id": str(item.get("source_id", "")),
                "payload": payload,
                "compiler_id": str(item.get("compiler_id", "observation_compiler")),
                "payload_hash": domain_hash(payload, domain="CETA/OBSERVATION_PAYLOAD/v1"),
            })

        for i, item in enumerate(context.get("claim_material", ()) or ()):
            if not isinstance(item, Mapping):
                continue
            proposition = dict(item.get("proposition", {})) if isinstance(item.get("proposition"), Mapping) else {}
            scope = dict(item.get("scope", {})) if isinstance(item.get("scope"), Mapping) else {}
            add("CreateClaim", {
                "claim_id": self._fresh_id(world, "CreateClaim", "claim_id", i),
                "proposition": proposition,
                "scope": scope,
            })

        # Observation validation and evidence admission/rejection.
        admitted_state_evidence = [o for o in by_type.get("EVIDENCE", ()) if o.content.get("status") == "ADMITTED"]
        validated_observations = [o.object_id for o in by_type.get("OBSERVATION", ()) if o.content.get("status") == "VALIDATED"]
        for i, obs in enumerate(by_type.get("OBSERVATION", ())):
            if obs.content.get("status") == "OBSERVED":
                add("ValidateObservation", {
                    "observation_ref": obs.object_id,
                    "replacement_id": self._fresh_id(world, "ValidateObservation", "replacement_id", i),
                    "validator_id": "observation_validator",
                    "validation_code": "STRUCTURE_VALID",
                    "evidence_refs": [],
                })

        for i, (record_id, record) in enumerate(sorted(world.evidence_view.items(), key=lambda x: str(x[0]))):
            if not isinstance(record, Mapping):
                continue
            if record.get("status") == "VALIDATED":
                refs = list(record.get("observation_refs", ())) if isinstance(record.get("observation_refs", ()), list) else []
                refs = [r for r in refs if r in validated_observations]
                add("AdmitEvidence", {
                    "evidence_id": self._fresh_id(world, "AdmitEvidence", "evidence_id", i),
                    "evidence_record_id": str(record_id),
                    "observation_refs": refs,
                })
            elif record.get("status") == "REJECTED":
                add("RejectEvidence", {
                    "evidence_id": self._fresh_id(world, "RejectEvidence", "evidence_id", i),
                    "evidence_record_id": str(record_id),
                    "reason_code": str(record.get("reason_code", "PROVENANCE_INVALID")),
                })

        # Internal epistemic transitions derived only from current state.
        for i, claim in enumerate(by_type.get("CLAIM", ())):
            if claim.content.get("status") == "ACTIVE":
                add("CreateBelief", {
                    "belief_id": self._fresh_id(world, "CreateBelief", "belief_id", i),
                    "claim_ref": claim.object_id,
                })

        for bi, belief in enumerate(by_type.get("BELIEF", ())):
            if belief.content.get("status") != "ACTIVE":
                continue
            for ei, evidence in enumerate(admitted_state_evidence):
                ordinal = bi * max(1, len(admitted_state_evidence)) + ei
                for operation in ("Support", "Contradict", "Undercut"):
                    add(operation, {
                        "belief_ref": belief.object_id,
                        "evidence_ref": evidence.object_id,
                        "replacement_id": self._fresh_id(world, operation, "replacement_id", ordinal),
                    })

        # Merge and split are intentionally bounded to RULE objects in the
        # reference action space. The VM supports broader same-type objects; the
        # neural reference policy does not claim exhaustive search yet.
        rules = [o for o in by_type.get("RULE", ()) if o.content.get("status") == "ACTIVE"]
        for i, pair in enumerate(combinations(rules, 2)):
            add("Merge", {
                "object_refs": [pair[0].object_id, pair[1].object_id],
                "merged_id": self._fresh_id(world, "Merge", "merged_id", i),
                "strategy": "IDENTICAL_OR_SET_UNION",
            })
        for i, source in enumerate(rules):
            keys = sorted(source.content)
            if len(keys) >= 2:
                cut = max(1, len(keys) // 2)
                if cut < len(keys):
                    add("Split", {
                        "object_ref": source.object_id,
                        "partitions": [
                            {"object_id": self._fresh_id(world, "Split", "partition_a", i), "keys": keys[:cut]},
                            {"object_id": self._fresh_id(world, "Split", "partition_b", i), "keys": keys[cut:]},
                        ],
                    })

        scoped_types = {"CLAIM", "BELIEF", "RULE", "GOAL"}
        for i, obj in enumerate(objects):
            if obj.object_type not in scoped_types:
                continue
            scope = obj.content.get("scope")
            narrower = self._narrower_scope(scope)
            if narrower is not None:
                add("NarrowScope", {
                    "target_ref": obj.object_id,
                    "replacement_id": self._fresh_id(world, "NarrowScope", "replacement_id", i),
                    "scope": narrower,
                })

        for i, item in enumerate(context.get("scope_expansions", ()) or ()):
            if not isinstance(item, Mapping):
                continue
            add("ExpandScope", {
                "target_ref": str(item.get("target_ref", "")),
                "replacement_id": self._fresh_id(world, "ExpandScope", "replacement_id", i),
                "scope": dict(item.get("scope", {})) if isinstance(item.get("scope"), Mapping) else {},
            })

        evidence_ids = [e.object_id for e in admitted_state_evidence]
        for i, obj in enumerate(objects):
            content = obj.content
            if obj.object_type == "BELIEF" and content.get("status") == "ACTIVE":
                supports = [r for r in content.get("support_refs", ()) if r in evidence_ids]
                if supports and not content.get("contradiction_refs") and not content.get("undercut_refs"):
                    add("Verify", {
                        "target_ref": obj.object_id,
                        "replacement_id": self._fresh_id(world, "Verify", "replacement_id", i),
                        "evidence_refs": supports,
                        "verification_code": "SUPPORTED_NO_DEFEATER",
                    })
            if content.get("verification_status") == "VERIFIED":
                add("Invalidate", {
                    "target_ref": obj.object_id,
                    "replacement_id": self._fresh_id(world, "Invalidate", "replacement_id", i),
                    "reason_code": "DEFEATED",
                    "evidence_refs": evidence_ids[:1],
                })
            if obj.object_type == "BELIEF" and content.get("status") == "ACTIVE" and content.get("epistemic_status") in {"CONTESTED", "UNDERCUT"}:
                defeaters = [r for r in list(content.get("contradiction_refs", ())) + list(content.get("undercut_refs", ())) if r in evidence_ids]
                add("Suspend", {
                    "target_ref": obj.object_id,
                    "replacement_id": self._fresh_id(world, "Suspend", "replacement_id", i),
                    "reason_code": "ACTIVE_DEFEATER",
                    "evidence_refs": defeaters,
                })
            expiry = content.get("expires_at_epoch_ms")
            if isinstance(expiry, int):
                for j, (record_id, record) in enumerate(sorted(world.evidence_view.items(), key=lambda x: str(x[0]))):
                    if not isinstance(record, Mapping) or record.get("status") != "VALIDATED":
                        continue
                    payload = record.get("payload")
                    if isinstance(payload, Mapping) and payload.get("kind") == "trusted_time" and isinstance(payload.get("epoch_ms"), int) and payload["epoch_ms"] >= expiry:
                        add("Expire", {
                            "target_ref": obj.object_id,
                            "replacement_id": self._fresh_id(world, "Expire", "replacement_id", i * 100 + j),
                            "trusted_time_evidence_ref": str(record_id),
                        })
            if content.get("status") in {"SUSPENDED", "INVALIDATED", "EXPIRED"} or content.get("epistemic_status") in {"CONTESTED", "UNDERCUT"}:
                if evidence_ids:
                    add("Reevaluate", {
                        "target_ref": obj.object_id,
                        "replacement_id": self._fresh_id(world, "Reevaluate", "replacement_id", i),
                        "trigger_evidence_refs": evidence_ids[:1],
                    })

        caps = set(world.authority_view.get("authorized_capabilities", ()) if isinstance(world.authority_view, Mapping) else ())
        if "adjudicate" in caps and evidence_ids:
            adjudicable = [o for o in objects if o.object_type in {"CLAIM", "BELIEF"} and o.content.get("status") == "ACTIVE"]
            for i, obj in enumerate(adjudicable):
                add("Adjudicate", {
                    "target_ref": obj.object_id,
                    "replacement_id": self._fresh_id(world, "Adjudicate", "replacement_id", i),
                    "outcome": "SUSPENDED",
                    "evidence_refs": evidence_ids[:1],
                    "adjudication_code": "CONFLICT_BOUND",
                })

        for i, item in enumerate(context.get("authorization_requests", ()) or ()):
            if not isinstance(item, Mapping):
                continue
            add("Authorize", {
                "authorization_id": self._fresh_id(world, "Authorize", "authorization_id", i),
                "permit_id": self._fresh_id(world, "Authorize", "permit_id", i),
                "nonce": self._fresh_id(world, "Authorize", "nonce", i),
                "subject_id": str(item.get("subject_id", "")),
                "subject_scope": str(item.get("subject_scope", "BOUND")),
                "operation": str(item.get("operation", "")),
                "consequence": dict(item.get("consequence", {})) if isinstance(item.get("consequence"), Mapping) else {},
                "consumer_id": str(item.get("consumer_id", "effect_gateway")),
                "consumer_key_id": str(item.get("consumer_key_id", "")),
                "expires_at_epoch_ms": int(item.get("expires_at_epoch_ms", 0)),
                "source_refs": list(item.get("source_refs", ())) if isinstance(item.get("source_refs", ()), list) else [],
            })

        for i, item in enumerate(context.get("authorization_rejections", ()) or ()):
            if not isinstance(item, Mapping):
                continue
            add("RejectAuthorization", {
                "authorization_id": self._fresh_id(world, "RejectAuthorization", "authorization_id", i),
                "subject_id": str(item.get("subject_id", "")),
                "operation": str(item.get("operation", "")),
                "reason_code": str(item.get("reason_code", "NO_AUTHORITY")),
                "source_refs": list(item.get("source_refs", ())) if isinstance(item.get("source_refs", ()), list) else [],
            })

        permits = world.authority_view.get("permits", {}) if isinstance(world.authority_view, Mapping) else {}
        for i, auth in enumerate(by_type.get("AUTHORITY", ())):
            content = auth.content
            permit = permits.get(content.get("permit_id")) if isinstance(permits, Mapping) else None
            if content.get("status") != "AUTHORIZED" or not isinstance(permit, Mapping) or permit.get("status") != "ISSUED":
                continue
            operation = content.get("operation")
            if operation in {"Execute", "Rollback"}:
                add(str(operation), {
                    "action_id": self._fresh_id(world, str(operation), "action_id", i),
                    "authorization_ref": auth.object_id,
                    "consequence": dict(content.get("consequence", {})) if isinstance(content.get("consequence"), Mapping) else {},
                })

        # Exact semantic duplicates add no choice and can distort loss weighting.
        unique: dict[str, TransitionProposal] = {}
        for proposal in candidates:
            key = json.dumps({"operation": proposal.operation, "operands": dict(proposal.operands)}, sort_keys=True, separators=(",", ":"))
            unique.setdefault(key, proposal)
        return tuple(unique[k] for k in sorted(unique))

    @staticmethod
    def _narrower_scope(scope: Any) -> dict[str, list[Any]] | None:
        if not isinstance(scope, Mapping) or not scope:
            return None
        normalized: dict[str, list[Any]] = {}
        changed = False
        for key in sorted(scope):
            value = scope[key]
            if not isinstance(value, list) or not value:
                return None
            values = list(value)
            if not changed and len(values) > 1:
                values = values[:-1]
                changed = True
            normalized[str(key)] = values
        return normalized if changed else None

    @staticmethod
    def _fresh_id(world: WorldView, operation: str, role: str, ordinal: int) -> str:
        material = f"CETA/ACTION_SPACE/v1\n{world.snapshot.state_ref}\n{operation}\n{role}\n{ordinal}".encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()[:20]
        return f"CETA-{role.upper()}-{digest}"
