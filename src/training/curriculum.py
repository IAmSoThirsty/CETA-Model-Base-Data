from __future__ import annotations

from ceta import TransitionProposal
from evidence_registry import EvidenceRegistry
from history import EpistemicObject, StateDelta, StateProjector
from identity_registry import IdentityRegistry
from .model import TransitionTrainingCase


class ReferenceCurriculum:
    """Small deterministic abstract curriculum used to validate the CETA format.

    It intentionally uses anonymous symbols rather than world facts. Production
    curriculum generation can scale the same state/transition representation.
    """

    def build(self) -> tuple[TransitionTrainingCase, ...]:
        cases=[]

        # Case 1: admitted evidence supports an open belief.
        state=StateProjector()
        claim=EpistemicObject.create(object_id='C-A',object_type='CLAIM',content={
            'status':'ACTIVE','verification_status':'UNVERIFIED','proposition':{'s':'S-A','p':'P-A','v':'V-A'},'scope':{'D':['A']}})
        evidence=EpistemicObject.create(object_id='E-A',object_type='EVIDENCE',content={'status':'ADMITTED','evidence_record_id':'ER-A','evidence_record_hash':'H-A','payload_hash':'PH-A','provenance_refs':['PR-A'],'observation_refs':[]})
        belief=EpistemicObject.create(object_id='B-A',object_type='BELIEF',content={'status':'ACTIVE','verification_status':'UNVERIFIED','claim_ref':'C-A','scope':{'D':['A']},'support_refs':[],'contradiction_refs':[],'undercut_refs':[],'epistemic_status':'OPEN'})
        state.apply(StateDelta((claim,evidence,belief),()))
        target=TransitionProposal(state.state_ref,'Support',{'belief_ref':'B-A','evidence_ref':'E-A','replacement_id':'B-A2'},'training_target')
        cases.append(TransitionTrainingCase.create(case_id='CURR-SUPPORT-001',snapshot=state.snapshot(),evidence_view={},identity_view={},authority_view={},now_epoch_ms=0,target=target))

        # Case 2: a contradicted belief should be suspended, not verified.
        state=StateProjector()
        belief=EpistemicObject.create(object_id='B-B',object_type='BELIEF',content={'status':'ACTIVE','verification_status':'UNVERIFIED','claim_ref':'C-B','scope':{},'support_refs':['E-S'],'contradiction_refs':['E-C'],'undercut_refs':[],'epistemic_status':'CONTESTED'})
        es=EpistemicObject.create(object_id='E-S',object_type='EVIDENCE',content={'status':'ADMITTED'})
        ec=EpistemicObject.create(object_id='E-C',object_type='EVIDENCE',content={'status':'ADMITTED'})
        state.apply(StateDelta((belief,es,ec),()))
        target=TransitionProposal(state.state_ref,'Suspend',{'target_ref':'B-B','replacement_id':'B-B2','reason_code':'ACTIVE_CONTRADICTING_EVIDENCE','evidence_refs':['E-C']},'training_target')
        cases.append(TransitionTrainingCase.create(case_id='CURR-DEFEATER-001',snapshot=state.snapshot(),evidence_view={},identity_view={},authority_view={},now_epoch_ms=0,target=target,required_defeater_refs=('E-C',)))

        # Case 3: scope expansion is legal only with explicit authority.
        state=StateProjector()
        claim=EpistemicObject.create(object_id='C-S',object_type='CLAIM',content={'status':'ACTIVE','verification_status':'UNVERIFIED','proposition':{'s':'S'},'scope':{'D':['A']}})
        state.apply(StateDelta((claim,),()))
        target=TransitionProposal(state.state_ref,'ExpandScope',{'target_ref':'C-S','replacement_id':'C-S2','scope':{'D':['*']}},'training_target')
        cases.append(TransitionTrainingCase.create(case_id='CURR-SCOPE-001',snapshot=state.snapshot(),evidence_view={},identity_view={},authority_view={'authorized_capabilities':['scope_expand']},now_epoch_ms=0,target=target))

        return tuple(cases)
