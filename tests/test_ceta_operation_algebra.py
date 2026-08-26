from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ceta import ConstitutionalVM, TransitionProposal, VmDisposition
from evidence_registry import EvidenceRegistry
from history import EpistemicObject, StateDelta, StateProjector
from identity_registry import IdentityAssertion, IdentityRegistry, TrustedIdentityVerifier
from observation_compiler import StructuredObservationCompiler
from reasoning import DefeaterEngine


class CetaOperationAlgebraTests(unittest.TestCase):
    def setUp(self):
        self.vm=ConstitutionalVM()
        self.state=StateProjector()
        self.evidence=EvidenceRegistry()
        self.identity_key=Ed25519PrivateKey.generate()
        self.identity=IdentityRegistry(trusted_verifier=TrustedIdentityVerifier({'idv':('idv-key',self.identity_key.public_key())}))
        self.authority={'authorized_capabilities':[]}
        self.now=100

    def verify_identity(self, identity_id: str, assertion_id: str = 'IDV-1'):
        prior=self.identity.latest(identity_id)
        assertion=IdentityAssertion.sign(
            assertion_id=assertion_id, identity_id=identity_id, prior_record_hash=prior.record_hash,
            target_status='VERIFIED', verifier_id='idv', verifier_key_id='idv-key', verification_code='KEY_BOUND',
            issued_at_epoch_ms=90, expires_at_epoch_ms=200, private_key=self.identity_key,
        )
        return self.identity.verify(identity_id, assertion=assertion, now_epoch_ms=100)

    def propose(self, operation, operands, proposer='transition_policy_model'):
        return TransitionProposal(self.state.state_ref,operation,operands,proposer)

    def decide(self, operation, operands, *, authority=None, now=None):
        return self.vm.evaluate(
            self.propose(operation,operands),
            projected_snapshot=self.state.snapshot(),
            admitted_evidence_view=self.evidence.view(),
            identity_view=self.identity.view(),
            authority_snapshot=self.authority if authority is None else authority,
            now_epoch_ms=self.now if now is None else now,
            constitutional_epoch='epoch-1',
        )

    def apply_legal(self, operation, operands, **kw):
        d=self.decide(operation,operands,**kw)
        self.assertEqual(d.disposition,VmDisposition.LEGAL,(operation,d.reason_code))
        self.assertTrue(d.contract_hash)
        self.assertTrue(d.decision_hash)
        self.state.apply(d.state_delta)
        return d

    def add_observation_evidence(self, suffix='1', payload=None):
        payload=payload or {'kind':'measurement','value':suffix}
        compiler=StructuredObservationCompiler()
        candidate=compiler.compile(observation_id=f'O{suffix}',source_id=f'sensor-{suffix}',payload=payload)
        self.apply_legal('Observe',candidate.as_observe_operands())
        self.apply_legal('ValidateObservation',{
            'observation_ref':f'O{suffix}','replacement_id':f'O{suffix}V','validator_id':'obs-validator',
            'validation_code':'STRUCTURE_OK','evidence_refs':[]})
        self.evidence.register(record_id=f'ER{suffix}',source_id=f'sensor-{suffix}',payload=payload,provenance_refs=(f'raw:{suffix}',))
        self.evidence.validate(f'ER{suffix}',validator_id='evidence-validator',validation_code='INTEGRITY_OK')
        self.apply_legal('AdmitEvidence',{'evidence_id':f'E{suffix}','evidence_record_id':f'ER{suffix}','observation_refs':[f'O{suffix}V']})
        return f'E{suffix}'

    def materialized_permit_view(self, permit_id, nonce, operation, consequence, *, expires=1000):
        from authority import canonical_hash
        return {
            "permit_id": permit_id,
            "nonce": nonce,
            "policy_epoch": "epoch-1",
            "subject_scope": "R1",
            "operation": operation,
            "consequence_hash": canonical_hash(consequence),
            "consumer_id": "effect_gateway",
            "consumer_key_id": "gw-key",
            "expires_at_epoch_ms": expires,
            "source_refs": ["policy:1"],
            "status": "ISSUED",
            "intent_hash": None,
        }

    def test_observe_validate_admit_claim_belief_support_verify_chain(self):
        e1=self.add_observation_evidence('1')
        self.apply_legal('CreateClaim',{'claim_id':'C1','proposition':{'subject':'X1','predicate':'P1','value':'V1'},'scope':{'site':['A'],'temperature':['*']}})
        self.apply_legal('CreateBelief',{'belief_id':'B1','claim_ref':'C1'})
        self.apply_legal('Support',{'belief_ref':'B1','evidence_ref':e1,'replacement_id':'B2'})
        d=self.apply_legal('Verify',{'target_ref':'B2','replacement_id':'B3','evidence_refs':[e1],'verification_code':'SUPPORTED_NO_DEFEATERS'})
        b3={x.object_id:x for x in self.state.snapshot().active_objects}['B3']
        self.assertEqual(b3.content['verification_status'],'VERIFIED')
        self.assertIn('SEMANTIC_VERIFICATION_EVIDENCE_BINDING',d.proof_obligations)

    def test_contradiction_dominates_verified_state_and_defeater_proposes_suspend(self):
        e1=self.add_observation_evidence('1')
        e2=self.add_observation_evidence('2')
        self.apply_legal('CreateClaim',{'claim_id':'C1','proposition':{'subject':'X','predicate':'P','value':1},'scope':{'site':['A']}})
        self.apply_legal('CreateBelief',{'belief_id':'B1','claim_ref':'C1'})
        self.apply_legal('Support',{'belief_ref':'B1','evidence_ref':e1,'replacement_id':'B2'})
        self.apply_legal('Verify',{'target_ref':'B2','replacement_id':'B3','evidence_refs':[e1],'verification_code':'OK'})
        self.apply_legal('Contradict',{'belief_ref':'B3','evidence_ref':e2,'replacement_id':'B4'})
        b4={x.object_id:x for x in self.state.snapshot().active_objects}['B4']
        self.assertEqual(b4.content['epistemic_status'],'CONTESTED')
        self.assertEqual(b4.content['verification_status'],'UNVERIFIED')
        findings=DefeaterEngine().scan(self.state.snapshot())
        self.assertEqual(findings[0].target_ref,'B4')
        self.assertEqual(findings[0].proposed_transition.operation,'Suspend')

    def test_rejected_evidence_cannot_be_admitted(self):
        self.evidence.register(record_id='ERX',source_id='s',payload={'x':1})
        self.evidence.reject('ERX',validator_id='v',validation_code='BAD')
        d=self.decide('AdmitEvidence',{'evidence_id':'EX','evidence_record_id':'ERX','observation_refs':[]})
        self.assertEqual(d.disposition,VmDisposition.DENY)
        self.assertEqual(d.reason_code,'EVIDENCE_RECORD_NOT_VALIDATED')
        self.apply_legal('RejectEvidence',{'evidence_id':'EXR','evidence_record_id':'ERX','reason_code':'BAD'})
        ex={x.object_id:x for x in self.state.snapshot().active_objects}['EXR']
        self.assertEqual(ex.content['status'],'REJECTED')

    def test_scope_narrow_and_expand_requires_authority(self):
        self.apply_legal('CreateClaim',{'claim_id':'C1','proposition':{'x':1},'scope':{'site':['A'],'temperature':['*']}})
        self.apply_legal('NarrowScope',{'target_ref':'C1','replacement_id':'C2','scope':{'site':['A'],'temperature':['cold']}})
        denied=self.decide('ExpandScope',{'target_ref':'C2','replacement_id':'C3','scope':{'site':['A'],'temperature':['*']}})
        self.assertEqual(denied.disposition,VmDisposition.DENY)
        self.assertIn('scope_expand',denied.reason_code)
        self.apply_legal('ExpandScope',{'target_ref':'C2','replacement_id':'C3','scope':{'site':['A'],'temperature':['*']}},authority={'authorized_capabilities':['scope_expand']})

    def test_merge_conflict_escalates_and_split_preserves_fields(self):
        a=EpistemicObject.create(object_id='R1',object_type='RULE',content={'a':1,'tags':['x']})
        b=EpistemicObject.create(object_id='R2',object_type='RULE',content={'a':1,'tags':['y']})
        self.state.apply(StateDelta((a,b),()))
        self.apply_legal('Merge',{'object_refs':['R1','R2'],'merged_id':'R3','strategy':'IDENTICAL_OR_SET_UNION'})
        merged={x.object_id:x for x in self.state.snapshot().active_objects}['R3']
        self.assertEqual(set(merged.content['tags']),{'x','y'})
        split=self.apply_legal('Split',{'object_ref':'R3','partitions':[{'object_id':'R4','keys':['a','tags']},{'object_id':'R5','keys':['merged_from']}]})
        self.assertEqual(len(split.state_delta.creates),2)
        self.assertEqual(len(split.state_delta.supersedes),2)

    def test_merge_scalar_conflict_escalates(self):
        a=EpistemicObject.create(object_id='R1',object_type='RULE',content={'a':1})
        b=EpistemicObject.create(object_id='R2',object_type='RULE',content={'a':2})
        self.state.apply(StateDelta((a,b),()))
        d=self.decide('Merge',{'object_refs':['R1','R2'],'merged_id':'R3','strategy':'IDENTICAL_OR_SET_UNION'})
        self.assertEqual(d.disposition,VmDisposition.ESCALATE)
        self.assertEqual(d.reason_code,'MERGE_CONFLICT_REQUIRES_ADJUDICATION')

    def test_suspend_invalidate_reevaluate_and_adjudicate(self):
        e1=self.add_observation_evidence('1')
        self.apply_legal('CreateClaim',{'claim_id':'C1','proposition':{'x':1},'scope':{'site':['A']}})
        self.apply_legal('Suspend',{'target_ref':'C1','replacement_id':'C2','reason_code':'WAIT','evidence_refs':[e1]})
        self.apply_legal('Reevaluate',{'target_ref':'C2','replacement_id':'C3','trigger_evidence_refs':[e1]})
        self.apply_legal('Invalidate',{'target_ref':'C3','replacement_id':'C4','reason_code':'DEFEATED','evidence_refs':[e1]})
        d=self.decide('Adjudicate',{'target_ref':'C4','replacement_id':'C5','outcome':'ACTIVE','evidence_refs':[e1],'adjudication_code':'REOPEN'})
        self.assertEqual(d.disposition,VmDisposition.DENY)
        self.apply_legal('Adjudicate',{'target_ref':'C4','replacement_id':'C5','outcome':'ACTIVE','evidence_refs':[e1],'adjudication_code':'REOPEN'},authority={'authorized_capabilities':['adjudicate']})

    def test_expire_requires_validated_trusted_time_evidence(self):
        expiring=EpistemicObject.create(object_id='C1',object_type='CLAIM',content={'status':'ACTIVE','scope':{},'expires_at_epoch_ms':500})
        self.state.apply(StateDelta((expiring,),()))
        self.evidence.register(record_id='TIME1',source_id='trusted-clock',payload={'kind':'trusted_time','epoch_ms':600})
        self.evidence.validate('TIME1',validator_id='time-verifier',validation_code='SIGNED_TIME_OK')
        self.apply_legal('Expire',{'target_ref':'C1','replacement_id':'C2','trusted_time_evidence_ref':'TIME1'})
        self.assertEqual({x.object_id:x for x in self.state.snapshot().active_objects}['C2'].content['status'],'EXPIRED')

    def test_authorize_execute_and_rollback_are_exactly_bound(self):
        self.identity.declare(identity_id='operator-1',declaration={'kind':'human_operator'},source_ref='decl:1')
        self.verify_identity('operator-1')
        consequence={'adapter_id':'fake','ceta_operation':'Execute','resource':'R1','mutation':{'value':1}}
        auth_caps={'authorized_capabilities':['authorize']}
        self.apply_legal('Authorize',{
            'authorization_id':'A1','permit_id':'P1','nonce':'N1','subject_id':'operator-1','subject_scope':'R1',
            'operation':'Execute','consequence':consequence,'consumer_id':'effect_gateway','consumer_key_id':'gw-key',
            'expires_at_epoch_ms':1000,'source_refs':['policy:1']},authority=auth_caps)
        self.authority={"authorized_capabilities":[],"permits":{"P1":self.materialized_permit_view("P1","N1","Execute",consequence)}}
        self.apply_legal('Execute',{'action_id':'X1','authorization_ref':'A1','consequence':consequence})
        wrong=dict(consequence); wrong['resource']='R2'
        denied=self.decide('Execute',{'action_id':'X2','authorization_ref':'A1','consequence':wrong})
        self.assertEqual(denied.disposition,VmDisposition.DENY)
        self.assertEqual(denied.reason_code,'EFFECT_CONSEQUENCE_DIFFERS_FROM_AUTHORIZATION')

        rollback={'adapter_id':'fake','ceta_operation':'Rollback','resource':'R1','mutation':{'value':0}}
        self.apply_legal('Authorize',{
            'authorization_id':'A2','permit_id':'P2','nonce':'N2','subject_id':'operator-1','subject_scope':'R1',
            'operation':'Rollback','consequence':rollback,'consumer_id':'effect_gateway','consumer_key_id':'gw-key',
            'expires_at_epoch_ms':1000,'source_refs':['policy:1']},authority=auth_caps)
        self.authority={"authorized_capabilities":[],"permits":{"P2":self.materialized_permit_view("P2","N2","Rollback",rollback)}}
        self.apply_legal('Rollback',{'action_id':'X2','authorization_ref':'A2','consequence':rollback})

    def test_reject_authorization_does_not_require_positive_authority(self):
        self.apply_legal('RejectAuthorization',{'authorization_id':'AR','subject_id':'s','operation':'Execute','reason_code':'NO_AUTHORITY','source_refs':[]})
        a={x.object_id:x for x in self.state.snapshot().active_objects}['AR']
        self.assertEqual(a.content['status'],'REJECTED')

if __name__=='__main__': unittest.main()
