from __future__ import annotations

import json
from typing import Any

from ceta import ConstitutionalVM, TransitionProposal, VmDisposition
from history import EpistemicObject, ProjectionSnapshot, Supersession
from .model import TransitionLoss, TransitionTrainingCase


class ExecutableTransitionEvaluator:
    """Scores a predicted transition by executing legality, not by text similarity."""

    def __init__(self, vm: ConstitutionalVM) -> None:
        self.vm=vm

    def score(self, case: TransitionTrainingCase, prediction: TransitionProposal) -> TransitionLoss:
        snapshot=_snapshot_from_json(case.state_json)
        evidence=json.loads(case.evidence_view_json)
        identity=json.loads(case.identity_view_json)
        authority=json.loads(case.authority_view_json)
        decision=self.vm.evaluate(
            prediction,
            projected_snapshot=snapshot,
            admitted_evidence_view=evidence,
            identity_view=identity,
            authority_snapshot=authority,
            now_epoch_ms=case.now_epoch_ms,
            constitutional_epoch="training",
        )
        target=case.target_proposal
        fields={
            'illegal_transition': int(decision.disposition is not VmDisposition.LEGAL),
            'missing_transition': int((prediction.operation,dict(prediction.operands)) != (target.operation,dict(target.operands))),
            'invariant_violation': int(decision.disposition is VmDisposition.HALT),
            'provenance_loss': int('EVIDENCE' in decision.reason_code or 'PROVENANCE' in decision.reason_code),
            'missing_defeaters': 0,
            'improper_scope': int('SCOPE' in decision.reason_code),
            'illegal_authorization': int('AUTHORITY' in decision.reason_code or 'AUTHORIZATION' in decision.reason_code),
            'belief_corruption': 0,
            'replay_mismatch': int(decision.reason_code=='INPUT_STATE_REFERENCE_MISMATCH'),
        }
        if case.required_defeater_refs and prediction.operation=='Verify':
            fields['missing_defeaters']=1
        if decision.disposition is VmDisposition.LEGAL and prediction.operation in {'Support','Contradict','Undercut','Verify'}:
            # The VM already checks relationship legality. A mismatch against the
            # target on these operations is separately counted as belief corruption.
            fields['belief_corruption']=fields['missing_transition']
        return TransitionLoss(**fields)


def _snapshot_from_json(raw: str) -> ProjectionSnapshot:
    data=json.loads(raw)
    objects=tuple(EpistemicObject.from_dict(x) for x in data['active_objects'])
    supersessions=tuple(Supersession(**x) for x in data['supersessions'])
    snap=ProjectionSnapshot(data['state_ref'],objects,supersessions)
    # State ref is not blindly trusted. Recompute from the active object/hash and
    # supersession topology using the same domain as StateProjector.snapshot().
    from history import domain_hash
    payload={
        'active_objects':[{'object_id':o.object_id,'object_type':o.object_type,'object_hash':o.object_hash} for o in sorted(objects,key=lambda x:x.object_id)],
        'supersessions':[x.to_dict() for x in sorted(supersessions,key=lambda x:(x.old_object_id,x.new_object_id))],
    }
    expected=domain_hash(payload,domain='CETA/STATE_PROJECTION/v1')
    if expected != snap.state_ref:
        raise ValueError('training state replay/reference mismatch')
    return snap
