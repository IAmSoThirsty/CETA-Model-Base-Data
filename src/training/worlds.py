from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from ceta import ConstitutionalVM, TransitionProposal, VmDisposition
from history import EpistemicObject, StateDelta, StateProjector

from .model import IllegalTransitionAlternative, TransitionTrainingCase
from transition_policy.actions import CetaActionSpaceGenerator
from transition_policy.encoder import WorldView


@dataclass(frozen=True)
class _AltSpec:
    alternative_id: str
    proposal: TransitionProposal
    failure_tags: tuple[str, ...]


@dataclass(frozen=True)
class _WorldDraft:
    family_id: str
    variant_id: str
    snapshot: Any
    evidence_view: Mapping[str, Any]
    identity_view: Mapping[str, Any]
    authority_view: Mapping[str, Any]
    proposal_context: Mapping[str, Any]
    now_epoch_ms: int | None
    target: TransitionProposal
    alternatives: tuple[_AltSpec, ...]
    required_defeater_refs: tuple[str, ...] = ()
    failure_surface_tags: tuple[str, ...] = ()


class CetaWorldCurriculum:
    """Deterministic abstract CETA world generator.

    The generator emits anonymous epistemic states and executable transition
    targets. Every target is required to be LEGAL under the Constitutional VM;
    every negative is required to be non-LEGAL under the exact same world state.
    No natural-language prompt/answer target exists in this representation.
    """

    OPERATIONS: tuple[str, ...] = (
        "Observe", "ValidateObservation", "AdmitEvidence", "RejectEvidence",
        "CreateClaim", "CreateBelief", "Support", "Contradict", "Undercut",
        "Merge", "Split", "NarrowScope", "ExpandScope", "Verify", "Invalidate",
        "Suspend", "Expire", "Reevaluate", "Adjudicate", "Authorize",
        "RejectAuthorization", "Execute", "Rollback",
    )
    CONSTITUTIONAL_EPOCH = "curriculum-v2"
    CASE_PREFIX = "CETA"

    def __init__(self, *, families_per_operation: int = 10, variants_per_family: int = 3) -> None:
        if families_per_operation < 10:
            raise ValueError("families_per_operation must be at least 10 for leakage-safe stratified splitting")
        if variants_per_family < 1:
            raise ValueError("variants_per_family must be positive")
        self.families_per_operation = families_per_operation
        self.variants_per_family = variants_per_family
        self.vm = ConstitutionalVM()

    def build(self) -> tuple[TransitionTrainingCase, ...]:
        cases: list[TransitionTrainingCase] = []
        for operation in self.OPERATIONS:
            for family_index in range(self.families_per_operation):
                for variant_index in range(self.variants_per_family):
                    draft = self._draft(operation, family_index, variant_index)
                    cases.append(self._materialize(draft))
        self._verify_operation_coverage(cases)
        return tuple(cases)

    def _materialize(self, draft: _WorldDraft) -> TransitionTrainingCase:
        world=WorldView(
            snapshot=draft.snapshot,evidence_view=draft.evidence_view,identity_view=draft.identity_view,
            authority_view=draft.authority_view,proposal_context=draft.proposal_context,now_epoch_ms=draft.now_epoch_ms,
        )
        action_space=CetaActionSpaceGenerator().generate(world)
        intended=[proposal for proposal in action_space if proposal.operation==draft.target.operation]
        legal=[]
        for proposal in intended:
            decision=self.vm.evaluate(
                proposal,projected_snapshot=draft.snapshot,admitted_evidence_view=draft.evidence_view,
                identity_view=draft.identity_view,authority_snapshot=draft.authority_view,
                now_epoch_ms=draft.now_epoch_ms,constitutional_epoch=self.CONSTITUTIONAL_EPOCH,
            )
            if decision.disposition is VmDisposition.LEGAL:
                legal.append((proposal,decision))
        if not legal:
            raise ValueError(f"target-blind action space produced no legal {draft.target.operation} candidate for {draft.family_id}/{draft.variant_id}")
        legal.sort(key=lambda item: repr((item[0].operation,sorted(item[0].operands.items()))))
        target,target_decision=legal[0]

        negatives: list[IllegalTransitionAlternative] = []
        for spec in draft.alternatives:
            decision = self.vm.evaluate(
                spec.proposal,
                projected_snapshot=draft.snapshot,
                admitted_evidence_view=draft.evidence_view,
                identity_view=draft.identity_view,
                authority_snapshot=draft.authority_view,
                now_epoch_ms=draft.now_epoch_ms,
                constitutional_epoch=self.CONSTITUTIONAL_EPOCH,
            )
            if decision.disposition is VmDisposition.LEGAL:
                raise ValueError(
                    f"generated illegal alternative became legal: {draft.family_id}/{draft.variant_id}/"
                    f"{spec.alternative_id}"
                )
            negatives.append(
                IllegalTransitionAlternative.create(
                    alternative_id=spec.alternative_id,
                    proposal=spec.proposal,
                    expected_disposition=decision.disposition.value,
                    expected_reason_code=decision.reason_code,
                    failure_tags=spec.failure_tags,
                )
            )

        return TransitionTrainingCase.create(
            case_id=f"{self.CASE_PREFIX}-{target.operation.upper()}-{draft.family_id.rsplit('/',1)[-1]}-{draft.variant_id}",
            world_family_id=draft.family_id,
            world_variant_id=draft.variant_id,
            snapshot=draft.snapshot,
            evidence_view=draft.evidence_view,
            identity_view=draft.identity_view,
            authority_view=draft.authority_view,
            proposal_context=draft.proposal_context,
            now_epoch_ms=draft.now_epoch_ms,
            target=target,
            illegal_alternatives=tuple(negatives),
            required_defeater_refs=draft.required_defeater_refs,
            failure_surface_tags=tuple(sorted(set(draft.failure_surface_tags + ("replay_fault",)))),
        )

    def _draft(self, operation: str, family_index: int, variant_index: int) -> _WorldDraft:
        token = f"{operation[:3].upper()}{family_index:02d}{variant_index:02d}"
        family_id = f"CETA/{operation}/F{family_index:02d}"
        variant_id = f"V{variant_index:03d}"
        state = StateProjector()
        evidence_view: dict[str, Any] = {}
        identity_view: dict[str, Any] = {}
        authority_view: dict[str, Any] = {}
        proposal_context: dict[str, Any] = {}
        now_ms: int | None = 100_000 + family_index * 100 + variant_index
        required_defeaters: tuple[str, ...] = ()
        failure_tags: tuple[str, ...] = ()

        def oid(kind: str, n: int = 0) -> str:
            return f"{kind}-{token}-{n:02d}"

        def add(*objects: EpistemicObject) -> None:
            if objects:
                state.apply(StateDelta(tuple(objects), ()))

        def obj(kind: str, n: int, content: Mapping[str, Any]) -> EpistemicObject:
            return EpistemicObject.create(object_id=oid(kind, n), object_type=kind, content=dict(content))

        def admitted_evidence(n: int) -> EpistemicObject:
            return obj("EVIDENCE", n, {
                "status": "ADMITTED",
                "evidence_record_id": oid("ER", n),
                "evidence_record_hash": f"RH-{token}-{n}",
                "payload_hash": f"PH-{token}-{n}",
                "provenance_refs": [oid("PR", n)],
                "observation_refs": [],
            })

        scope_base = {"D": [f"S{variant_index}", f"S{variant_index+1}"]}
        proposer = "transition_policy"
        target: TransitionProposal
        scenario_alt: _AltSpec

        if operation == "Observe":
            payload = {"k": f"K{variant_index}", "n": family_index}
            from history import domain_hash
            proposal_context["incoming_observations"]=[{"source_id":oid("SRC",0),"payload":payload,"compiler_id":"observation_compiler"}]
            target = TransitionProposal(state.state_ref, operation, {
                "observation_id": oid("OBS", 0), "source_id": oid("SRC", 0), "payload": payload,
                "compiler_id": "observation_compiler", "payload_hash": domain_hash(payload, domain="CETA/OBSERVATION_PAYLOAD/v1"),
            }, proposer)
            bad = dict(target.operands); bad["payload_hash"] = "sha256:bad"
            scenario_alt = _AltSpec("PAYLOAD_HASH_CORRUPTION", TransitionProposal(state.state_ref, operation, bad, proposer), ("provenance_corruption",))

        elif operation == "ValidateObservation":
            add(obj("OBSERVATION", 0, {"status": "OBSERVED", "source_id": oid("SRC",0), "compiler_id":"observation_compiler", "payload": {"x":1}, "payload_hash": "PH"}))
            target = TransitionProposal(state.state_ref, operation, {
                "observation_ref": oid("OBSERVATION",0), "replacement_id": oid("OBSERVATION",1),
                "validator_id": "observation_validator", "validation_code": "STRUCTURE_VALID", "evidence_refs": [],
            }, proposer)
            bad = dict(target.operands); bad["observation_ref"] = oid("OBSERVATION",99)
            scenario_alt = _AltSpec("INACTIVE_OBSERVATION", TransitionProposal(state.state_ref, operation, bad, proposer), ("pathway_failure",))

        elif operation == "AdmitEvidence":
            record_id = oid("ER",0)
            evidence_view[record_id] = {"status":"VALIDATED", "record_hash":f"RH-{token}", "payload_hash":f"PH-{token}", "provenance_refs":[oid("PR",0)]}
            target = TransitionProposal(state.state_ref, operation, {"evidence_id":oid("EVIDENCE",0), "evidence_record_id":record_id, "observation_refs":[]}, proposer)
            alt = TransitionProposal(state.state_ref, "RejectEvidence", {"evidence_id":oid("EVIDENCE",1), "evidence_record_id":record_id, "reason_code":"PROVENANCE_REJECT"}, proposer)
            scenario_alt = _AltSpec("REJECT_VALIDATED_EVIDENCE", alt, ("provenance_corruption",))

        elif operation == "RejectEvidence":
            record_id = oid("ER",0)
            evidence_view[record_id] = {"status":"REJECTED", "record_hash":f"RH-{token}", "payload_hash":f"PH-{token}", "provenance_refs":[oid("PR",0)]}
            target = TransitionProposal(state.state_ref, operation, {"evidence_id":oid("EVIDENCE",0), "evidence_record_id":record_id, "reason_code":"PROVENANCE_INVALID"}, proposer)
            alt = TransitionProposal(state.state_ref, "AdmitEvidence", {"evidence_id":oid("EVIDENCE",1), "evidence_record_id":record_id, "observation_refs":[]}, proposer)
            scenario_alt = _AltSpec("ADMIT_REJECTED_EVIDENCE", alt, ("provenance_corruption",))
            failure_tags = ("provenance_corruption",)

        elif operation == "CreateClaim":
            proposal_context["claim_material"]=[{"proposition":{"s":oid("SYM",0),"p":oid("REL",0),"v":oid("VAL",0)},"scope":scope_base}]
            target = TransitionProposal(state.state_ref, operation, {"claim_id":oid("CLAIM",0), "proposition":{"s":oid("SYM",0),"p":oid("REL",0),"v":oid("VAL",0)}, "scope":scope_base}, proposer)
            bad = dict(target.operands); bad["proposition"] = {}
            scenario_alt = _AltSpec("EMPTY_PROPOSITION", TransitionProposal(state.state_ref, operation, bad, proposer), ("semantic_competence_failure",))

        elif operation == "CreateBelief":
            add(obj("CLAIM",0,{"status":"ACTIVE","verification_status":"UNVERIFIED","proposition":{"s":oid("SYM",0)},"scope":scope_base}))
            target = TransitionProposal(state.state_ref, operation, {"belief_id":oid("BELIEF",0), "claim_ref":oid("CLAIM",0)}, proposer)
            bad = dict(target.operands); bad["claim_ref"] = oid("CLAIM",99)
            scenario_alt = _AltSpec("MISSING_CLAIM", TransitionProposal(state.state_ref, operation, bad, proposer), ("pathway_failure",))

        elif operation in {"Support", "Contradict", "Undercut"}:
            e = admitted_evidence(0)
            b = obj("BELIEF",0,{"status":"ACTIVE","verification_status":"UNVERIFIED","claim_ref":oid("CLAIM",0),"scope":scope_base,"support_refs":[],"contradiction_refs":[],"undercut_refs":[],"epistemic_status":"OPEN"})
            add(b,e)
            target = TransitionProposal(state.state_ref, operation, {"belief_ref":b.object_id,"evidence_ref":e.object_id,"replacement_id":oid("BELIEF",1)}, proposer)
            bad = dict(target.operands); bad["evidence_ref"] = oid("EVIDENCE",99)
            scenario_alt = _AltSpec("MISSING_EVIDENCE_RELATION_SOURCE", TransitionProposal(state.state_ref, operation, bad, proposer), ("provenance_loss",))

        elif operation == "Merge":
            a=obj("RULE",0,{"status":"ACTIVE","scope":{"D":["A"]},"tags":[f"T{variant_index}"]})
            b=obj("RULE",1,{"status":"ACTIVE","scope":{"D":["A"]},"tags":[f"U{variant_index}"]})
            c=obj("CLAIM",0,{"status":"ACTIVE","scope":{"D":["A"]},"proposition":{"s":"Q"},"verification_status":"UNVERIFIED"})
            add(a,b,c)
            target=TransitionProposal(state.state_ref,operation,{"object_refs":[a.object_id,b.object_id],"merged_id":oid("RULE",2),"strategy":"IDENTICAL_OR_SET_UNION"},proposer)
            bad=dict(target.operands); bad["object_refs"]=[a.object_id,c.object_id]
            scenario_alt=_AltSpec("MERGE_TYPE_CONFLICT",TransitionProposal(state.state_ref,operation,bad,proposer),("invariant_violation",))

        elif operation == "Split":
            source=obj("RULE",0,{"status":"ACTIVE","scope":{"D":["A"]},"predicate":{"r":"R"},"priority":family_index})
            add(source)
            keys=sorted(source.content)
            target=TransitionProposal(state.state_ref,operation,{"object_ref":source.object_id,"partitions":[{"object_id":oid("RULE",1),"keys":keys[:2]},{"object_id":oid("RULE",2),"keys":keys[2:]}]},proposer)
            bad=dict(target.operands); bad["partitions"]=[{"object_id":oid("RULE",3),"keys":[keys[0],keys[1]]},{"object_id":oid("RULE",4),"keys":[keys[1],keys[2],keys[3]]}]
            scenario_alt=_AltSpec("SPLIT_OVERLAP",TransitionProposal(state.state_ref,operation,bad,proposer),("invariant_violation",))

        elif operation in {"NarrowScope", "ExpandScope"}:
            old_scope={"D":["A","B"]} if operation=="NarrowScope" else {"D":["A"]}
            claim=obj("CLAIM",0,{"status":"ACTIVE","verification_status":"UNVERIFIED","proposition":{"s":"Q"},"scope":old_scope})
            add(claim)
            new_scope={"D":["A"]} if operation=="NarrowScope" else {"D":["A","B"]}
            if operation=="ExpandScope":
                authority_view["authorized_capabilities"]=["scope_expand"]
                proposal_context["scope_expansions"]=[{"target_ref":claim.object_id,"scope":new_scope}]
            target=TransitionProposal(state.state_ref,operation,{"target_ref":claim.object_id,"replacement_id":oid("CLAIM",1),"scope":new_scope},proposer)
            bad=dict(target.operands); bad["scope"]=old_scope
            scenario_alt=_AltSpec("NON_STRICT_SCOPE_CHANGE",TransitionProposal(state.state_ref,operation,bad,proposer),("improper_scope",))
            failure_tags=("improper_scope",)

        elif operation == "Verify":
            e=admitted_evidence(0)
            b=obj("BELIEF",0,{"status":"ACTIVE","verification_status":"UNVERIFIED","claim_ref":oid("CLAIM",0),"scope":scope_base,"support_refs":[e.object_id],"contradiction_refs":[],"undercut_refs":[],"epistemic_status":"SUPPORTED"})
            add(b,e)
            target=TransitionProposal(state.state_ref,operation,{"target_ref":b.object_id,"replacement_id":oid("BELIEF",1),"evidence_refs":[e.object_id],"verification_code":"SUPPORTED_NO_DEFEATER"},proposer)
            bad=dict(target.operands); bad["evidence_refs"]=[]
            scenario_alt=_AltSpec("VERIFY_WITHOUT_EVIDENCE",TransitionProposal(state.state_ref,operation,bad,proposer),("provenance_loss",))

        elif operation == "Invalidate":
            e=admitted_evidence(0); c=obj("CLAIM",0,{"status":"ACTIVE","verification_status":"VERIFIED","proposition":{"s":"Q"},"scope":scope_base})
            add(c,e)
            target=TransitionProposal(state.state_ref,operation,{"target_ref":c.object_id,"replacement_id":oid("CLAIM",1),"reason_code":"DEFEATED","evidence_refs":[e.object_id]},proposer)
            bad=dict(target.operands); bad["evidence_refs"]=[oid("EVIDENCE",99)]
            scenario_alt=_AltSpec("INVALIDATE_WITH_MISSING_EVIDENCE",TransitionProposal(state.state_ref,operation,bad,proposer),("provenance_loss",))

        elif operation == "Suspend":
            es=admitted_evidence(0); ec=admitted_evidence(1)
            b=obj("BELIEF",0,{"status":"ACTIVE","verification_status":"UNVERIFIED","claim_ref":oid("CLAIM",0),"scope":scope_base,"support_refs":[es.object_id],"contradiction_refs":[ec.object_id],"undercut_refs":[],"epistemic_status":"CONTESTED"})
            add(b,es,ec)
            target=TransitionProposal(state.state_ref,operation,{"target_ref":b.object_id,"replacement_id":oid("BELIEF",1),"reason_code":"ACTIVE_DEFEATER","evidence_refs":[ec.object_id]},proposer)
            alt=TransitionProposal(state.state_ref,"Verify",{"target_ref":b.object_id,"replacement_id":oid("BELIEF",2),"evidence_refs":[es.object_id],"verification_code":"IGNORE_DEFEATER"},proposer)
            scenario_alt=_AltSpec("VERIFY_DESPITE_DEFEATER",alt,("missing_defeaters","belief_corruption"))
            required_defeaters=(ec.object_id,)
            failure_tags=("missing_defeaters","belief_corruption")

        elif operation == "Expire":
            goal=obj("GOAL",0,{"status":"ACTIVE","scope":scope_base,"expires_at_epoch_ms":now_ms-1})
            add(goal)
            time_ref=oid("TIME",0)
            evidence_view[time_ref]={"status":"VALIDATED","payload":{"kind":"trusted_time","epoch_ms":now_ms}}
            target=TransitionProposal(state.state_ref,operation,{"target_ref":goal.object_id,"replacement_id":oid("GOAL",1),"trusted_time_evidence_ref":time_ref},proposer)
            bad=dict(target.operands); bad["trusted_time_evidence_ref"]=oid("TIME",99)
            scenario_alt=_AltSpec("UNVALIDATED_TIME",TransitionProposal(state.state_ref,operation,bad,proposer),("provenance_corruption","replay_fault"))

        elif operation == "Reevaluate":
            e=admitted_evidence(0); goal=obj("GOAL",0,{"status":"SUSPENDED","scope":scope_base,"verification_status":"UNVERIFIED"}); locked=obj("GOAL",1,{"status":"LOCKED","scope":scope_base})
            add(goal,locked,e)
            target=TransitionProposal(state.state_ref,operation,{"target_ref":goal.object_id,"replacement_id":oid("GOAL",2),"trigger_evidence_refs":[e.object_id]},proposer)
            bad=dict(target.operands); bad["target_ref"]=locked.object_id; bad["replacement_id"]=oid("GOAL",3)
            scenario_alt=_AltSpec("NON_REEVALUATABLE_TARGET",TransitionProposal(state.state_ref,operation,bad,proposer),("pathway_failure",))

        elif operation == "Adjudicate":
            e=admitted_evidence(0); c=obj("CLAIM",0,{"status":"ACTIVE","verification_status":"UNVERIFIED","proposition":{"s":"Q"},"scope":scope_base})
            add(c,e); authority_view["authorized_capabilities"]=["adjudicate"]
            target=TransitionProposal(state.state_ref,operation,{"target_ref":c.object_id,"replacement_id":oid("CLAIM",1),"outcome":"SUSPENDED","evidence_refs":[e.object_id],"adjudication_code":"CONFLICT_BOUND"},proposer)
            bad=dict(target.operands); bad["outcome"]="VERIFIED"
            scenario_alt=_AltSpec("UNBOUNDED_ADJUDICATION_OUTCOME",TransitionProposal(state.state_ref,operation,bad,proposer),("illegal_authorization",))

        elif operation == "Authorize":
            authority_view["authorized_capabilities"]=["authorize"]
            subject=oid("SUBJECT",0); identity_view[subject]={"status":"VERIFIED","record_hash":f"IRH-{token}"}
            consequence={"adapter_id":"reference","action":"mutate","resource":oid("RES",0),"value":variant_index}
            proposal_context["authorization_requests"]=[{"subject_id":subject,"subject_scope":"BOUND","operation":"Execute","consequence":consequence,"consumer_id":"effect_gateway","consumer_key_id":"GW-K1","expires_at_epoch_ms":now_ms+10_000,"source_refs":[oid("SRC",0)]}]
            target=TransitionProposal(state.state_ref,operation,{
                "authorization_id":oid("AUTHORITY",0),"permit_id":oid("PERMIT",0),"nonce":oid("NONCE",0),"subject_id":subject,
                "subject_scope":"BOUND","operation":"Execute","consequence":consequence,"consumer_id":"effect_gateway","consumer_key_id":"GW-K1",
                "expires_at_epoch_ms":now_ms+10_000,"source_refs":[oid("SRC",0)],
            },proposer)
            bad=dict(target.operands); bad["expires_at_epoch_ms"]=now_ms
            scenario_alt=_AltSpec("EXPIRED_AUTHORIZATION",TransitionProposal(state.state_ref,operation,bad,proposer),("illegal_authorization",))

        elif operation == "RejectAuthorization":
            subject=oid("SUBJECT",0)
            proposal_context["authorization_rejections"]=[{"subject_id":subject,"operation":"Execute","reason_code":"NO_AUTHORITY","source_refs":[oid("SRC",0)]}]
            target=TransitionProposal(state.state_ref,operation,{"authorization_id":oid("AUTHORITY",0),"subject_id":subject,"operation":"Execute","reason_code":"NO_AUTHORITY","source_refs":[oid("SRC",0)]},proposer)
            consequence={"adapter_id":"reference","action":"mutate","resource":oid("RES",0)}
            alt=TransitionProposal(state.state_ref,"Authorize",{
                "authorization_id":oid("AUTHORITY",1),"permit_id":oid("PERMIT",0),"nonce":oid("NONCE",0),"subject_id":subject,
                "subject_scope":"BOUND","operation":"Execute","consequence":consequence,"consumer_id":"effect_gateway","consumer_key_id":"GW-K1",
                "expires_at_epoch_ms":now_ms+10_000,"source_refs":[oid("SRC",0)],
            },proposer)
            scenario_alt=_AltSpec("AUTHORIZE_WITHOUT_AUTHORITY",alt,("illegal_authorization","authority_failure"))
            failure_tags=("illegal_authorization","authority_failure")

        elif operation in {"Execute", "Rollback"}:
            consequence={"adapter_id":"reference","action":"mutate" if operation=="Execute" else "restore","resource":oid("RES",0),"value":variant_index}
            consequence_hash=_consequence_hash(consequence)
            permit_id=oid("PERMIT",0)
            auth=obj("AUTHORITY",0,{"status":"AUTHORIZED","permit_id":permit_id,"nonce":oid("NONCE",0),"subject_id":oid("SUBJECT",0),"subject_scope":"BOUND","operation":operation,
                "consequence":consequence,"consequence_hash":consequence_hash,"consumer_id":"effect_gateway","consumer_key_id":"GW-K1","expires_at_epoch_ms":now_ms+10_000,"source_refs":[oid("SRC",0)],"identity_record_hash":f"IRH-{token}"})
            add(auth)
            authority_view["permits"]={permit_id:{"status":"ISSUED","operation":operation,"consequence_hash":consequence_hash,"consumer_id":"effect_gateway","consumer_key_id":"GW-K1","expires_at_epoch_ms":now_ms+10_000}}
            target=TransitionProposal(state.state_ref,operation,{"action_id":oid("ACTION",0),"authorization_ref":auth.object_id,"consequence":consequence},proposer)
            bad_consequence=dict(consequence); bad_consequence["value"]=variant_index+999
            bad=dict(target.operands); bad["consequence"]=bad_consequence
            scenario_alt=_AltSpec("CONSEQUENCE_SUBSTITUTION",TransitionProposal(state.state_ref,operation,bad,proposer),("illegal_authorization","objective_substitution_failure"))

        else:
            raise ValueError(f"unsupported operation template: {operation}")

        # Variant anchor makes identity-renamed variants produce distinct state
        # references while preserving identical topology inside one family.
        add(obj("UNIVERSE", 900, {"status": "ACTIVE", "variant_symbol": f"V{variant_index}"}))

        # Add family-specific irrelevant state only after the target world is
        # constructed. The target state reference is rebound below. This makes
        # F00..F09 topologically distinct without changing the intended law.
        for i in range(family_index):
            distractor=obj("GOAL",100+i,{"status":"ACTIVE","scope":{"D":[f"Z{i%3}"]},"goal_class":"DISTRACTOR","ordinal":i})
            add(distractor)

        # Rebind proposals to the final state reference after distractors.
        target = TransitionProposal(state.state_ref, target.operation, target.operands, target.proposer_id)
        scenario_alt = _AltSpec(
            scenario_alt.alternative_id,
            TransitionProposal(state.state_ref, scenario_alt.proposal.operation, scenario_alt.proposal.operands, scenario_alt.proposal.proposer_id),
            scenario_alt.failure_tags,
        )

        # Universal negatives exercise replay integrity and exact operand shape.
        stale = _AltSpec(
            "STALE_STATE_REFERENCE",
            TransitionProposal(f"sha256:stale-{token}", target.operation, target.operands, proposer),
            ("replay_fault",),
        )
        missing_operands = dict(target.operands)
        first_key = sorted(missing_operands)[0]
        del missing_operands[first_key]
        malformed = _AltSpec(
            "MISSING_REQUIRED_OPERAND",
            TransitionProposal(state.state_ref, target.operation, missing_operands, proposer),
            ("structural_output_failure",),
        )
        unknown = _AltSpec(
            "UNKNOWN_OPCODE",
            TransitionProposal(state.state_ref, "UnknownTransitionOpcode", {}, proposer),
            ("structural_output_failure",),
        )

        return _WorldDraft(
            family_id=family_id,
            variant_id=variant_id,
            snapshot=state.snapshot(),
            evidence_view=evidence_view,
            identity_view=identity_view,
            authority_view=authority_view,
            proposal_context=proposal_context,
            now_epoch_ms=now_ms,
            target=target,
            alternatives=(stale, malformed, unknown, scenario_alt),
            required_defeater_refs=required_defeaters,
            failure_surface_tags=failure_tags,
        )

    def _verify_operation_coverage(self, cases: list[TransitionTrainingCase]) -> None:
        present = {case.target_proposal.operation for case in cases}
        missing = set(self.OPERATIONS) - present
        if missing:
            raise ValueError(f"curriculum missing CETA operations: {sorted(missing)}")


def _consequence_hash(consequence: Mapping[str, Any]) -> str:
    import json
    raw=json.dumps(dict(consequence),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
