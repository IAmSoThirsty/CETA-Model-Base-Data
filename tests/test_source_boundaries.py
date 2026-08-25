from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from evidence_registry import EvidenceRecordStatus, EvidenceRegistry, EvidenceRegistryError
from identity_registry import IdentityAssertion, IdentityRegistry, IdentityRegistryError, IdentityStatus, TrustedIdentityVerifier
from observation_compiler import ObservationCompileError, StructuredObservationCompiler


class SourceBoundaryTests(unittest.TestCase):
    def identity_registry(self, path=None):
        key=Ed25519PrivateKey.generate()
        verifier=TrustedIdentityVerifier({'identity-verifier':('id-key',key.public_key())})
        return IdentityRegistry(path, trusted_verifier=verifier), key

    def identity_assertion(self, r, key, identity_id, target_status, assertion_id):
        prior=r.latest(identity_id)
        return IdentityAssertion.sign(
            assertion_id=assertion_id, identity_id=identity_id, prior_record_hash=prior.record_hash,
            target_status=target_status, verifier_id='identity-verifier', verifier_key_id='id-key',
            verification_code=target_status+'_PROOF', issued_at_epoch_ms=10, expires_at_epoch_ms=1000, private_key=key,
        )
    def test_evidence_validation_is_append_only_and_does_not_claim_truth(self):
        r=EvidenceRegistry()
        candidate=r.register(record_id='ER1',source_id='sensor-1',payload={'reading':7},provenance_refs=('raw:1',))
        validated=r.validate('ER1',validator_id='validator-1',validation_code='INTEGRITY_OK')
        self.assertEqual(candidate.status,EvidenceRecordStatus.CANDIDATE)
        self.assertEqual(validated.status,EvidenceRecordStatus.VALIDATED)
        self.assertEqual(validated.supersedes_hash,candidate.record_hash)
        self.assertNotIn('truth',r.view()['ER1'])
        r.verify()

    def test_evidence_identity_cannot_be_reused_as_new_candidate(self):
        r=EvidenceRegistry(); r.register(record_id='ER1',source_id='s',payload={'x':1})
        with self.assertRaises(EvidenceRegistryError):
            r.register(record_id='ER1',source_id='s',payload={'x':2})

    def test_rejected_evidence_has_distinct_status(self):
        r=EvidenceRegistry(); r.register(record_id='ER1',source_id='s',payload={'x':1})
        rejected=r.reject('ER1',validator_id='v',validation_code='MALFORMED')
        self.assertEqual(rejected.status,EvidenceRecordStatus.REJECTED)
        self.assertNotEqual(rejected.status,EvidenceRecordStatus.VALIDATED)

    def test_identity_declaration_is_not_verification(self):
        r,key=self.identity_registry(); declared=r.declare(identity_id='human-1',declaration={'role':'operator'},source_ref='declaration:1')
        self.assertEqual(declared.status,IdentityStatus.DECLARED)
        assertion=self.identity_assertion(r,key,'human-1','VERIFIED','IV-1')
        verified=r.verify('human-1',assertion=assertion,now_epoch_ms=20)
        self.assertEqual(verified.status,IdentityStatus.VERIFIED)
        self.assertEqual(verified.supersedes_hash,declared.record_hash)

    def test_identity_revoke_is_monotonic_revision(self):
        r,key=self.identity_registry(); r.declare(identity_id='human-1',declaration={'role':'operator'},source_ref='d1')
        r.verify('human-1',assertion=self.identity_assertion(r,key,'human-1','VERIFIED','IV-2'),now_epoch_ms=20)
        revoked=r.revoke('human-1',assertion=self.identity_assertion(r,key,'human-1','REVOKED','IV-3'),now_epoch_ms=30)
        self.assertEqual(revoked.revision,3)
        self.assertEqual(revoked.status,IdentityStatus.REVOKED)


    def test_evidence_registry_persists_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'evidence.jsonl'
            r=EvidenceRegistry(path); r.register(record_id='ER1',source_id='s',payload={'x':1}); r.validate('ER1',validator_id='v',validation_code='OK')
            reopened=EvidenceRegistry(path); self.assertTrue(reopened.verify()); self.assertEqual(reopened.latest('ER1').status,EvidenceRecordStatus.VALIDATED)
            text=path.read_text(); path.write_text(text.replace('\"x\":1','\"x\":2',1))
            with self.assertRaises(EvidenceRegistryError): EvidenceRegistry(path)

    def test_identity_registry_persists_signed_verification_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'identity.jsonl'
            key=Ed25519PrivateKey.generate(); verifier=TrustedIdentityVerifier({'identity-verifier':('id-key',key.public_key())})
            r=IdentityRegistry(path,trusted_verifier=verifier); r.declare(identity_id='h',declaration={'role':'operator'},source_ref='d')
            r.verify('h',assertion=self.identity_assertion(r,key,'h','VERIFIED','IV-P'),now_epoch_ms=20)
            reopened=IdentityRegistry(path,trusted_verifier=verifier); self.assertTrue(reopened.verify_integrity()); self.assertEqual(reopened.latest('h').status,IdentityStatus.VERIFIED)
            text=path.read_text(); path.write_text(text.replace('KEY_BOUND','BROKEN',1) if 'KEY_BOUND' in text else text.replace('VERIFIED_PROOF','BROKEN',1))
            with self.assertRaises(IdentityRegistryError): IdentityRegistry(path,trusted_verifier=verifier)

    def test_observation_compiler_accepts_only_structured_payload(self):
        compiler=StructuredObservationCompiler()
        with self.assertRaises(ObservationCompileError):
            compiler.compile(observation_id='O1',source_id='u',payload={})
        c=compiler.compile(observation_id='O1',source_id='u',payload={'subject':'B1','reading':7})
        self.assertEqual(c.as_observe_operands()['payload'],{'subject':'B1','reading':7})
        self.assertTrue(c.payload_hash.startswith('sha256:'))

if __name__=='__main__': unittest.main()
