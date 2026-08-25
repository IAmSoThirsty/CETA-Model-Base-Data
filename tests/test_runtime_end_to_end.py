from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from authority import AuthorityAssertion, AuthorityLedger, PermitStatus, TrustedAuthorityVerifier
from ceta import ConstitutionalVM, TransitionProposal
from effects import AdapterAttempt, EffectGateway, EffectObservation, EffectVerifier
from evidence_registry import EvidenceRegistry
from history import TransitionLedger
from identity_registry import IdentityAssertion, IdentityRegistry, TrustedIdentityVerifier
from runtime import CetaRuntime
from tool_adapters import GatewayBoundAdapter


OPS = {
    "Observe", "ValidateObservation", "AdmitEvidence", "RejectEvidence", "CreateClaim", "CreateBelief", "Support", "Contradict", "Undercut",
    "Merge", "Split", "NarrowScope", "ExpandScope", "Verify", "Invalidate", "Suspend", "Expire", "Reevaluate", "Adjudicate", "Authorize",
    "RejectAuthorization", "Execute", "Rollback",
}


class FakeAdapter(GatewayBoundAdapter):
    def __init__(self, status=PermitStatus.COMPLETED):
        super().__init__("fake")
        self.status = status

    def perform(self, consequence, invocation):
        invocation_hash = self.verify_gateway_invocation(consequence, invocation)
        return AdapterAttempt(
            self.status,
            {"attempted": True, "resource": consequence.get("resource"), "gateway_invocation_hash": invocation_hash},
        )


class RuntimeEndToEndTests(unittest.TestCase):
    def make_runtime(self, adapter=None):
        self.tmp = tempfile.TemporaryDirectory()
        ledger = TransitionLedger(Path(self.tmp.name) / "transitions.jsonl", known_operations=OPS)
        evidence = EvidenceRegistry(Path(self.tmp.name) / 'evidence.jsonl')
        self.identity_key = Ed25519PrivateKey.generate()
        identity = IdentityRegistry(Path(self.tmp.name) / 'identity.jsonl', trusted_verifier=TrustedIdentityVerifier({'idv':('idv-key',self.identity_key.public_key())}))
        authority = AuthorityLedger(Path(self.tmp.name) / "authority.jsonl")
        self.gateway_key = Ed25519PrivateKey.generate()
        self.observer_key = Ed25519PrivateKey.generate()
        self.authority_root_key = Ed25519PrivateKey.generate()
        gateway = EffectGateway(
            authority=authority,
            component_id="effect_gateway",
            key_id="gw-key",
            signing_private_key=self.gateway_key,
            adapters={"fake": adapter or FakeAdapter()},
        )
        verifier = EffectVerifier(
            "effect_verifier",
            trusted_gateway_keys={"gw-key": gateway.public_key},
            trusted_observers={"independent_sensor": ("sensor-key", self.observer_key.public_key())},
        )
        return CetaRuntime(
            ledger=ledger,
            vm=ConstitutionalVM(),
            evidence=evidence,
            identity=identity,
            authority=authority,
            authority_verifier=TrustedAuthorityVerifier({"root-key": self.authority_root_key.public_key()}),
            effect_gateway=gateway,
            effect_verifier=verifier,
        )

    def verify_identity(self, runtime, identity_id='operator-1', assertion_id='IDV-1'):
        prior=runtime.identity.latest(identity_id)
        assertion=IdentityAssertion.sign(
            assertion_id=assertion_id, identity_id=identity_id, prior_record_hash=prior.record_hash,
            target_status='VERIFIED', verifier_id='idv', verifier_key_id='idv-key', verification_code='KEY_BOUND',
            issued_at_epoch_ms=90, expires_at_epoch_ms=200, private_key=self.identity_key,
        )
        return runtime.identity.verify(identity_id, assertion=assertion, now_epoch_ms=100)

    def authorize_action(self, runtime, operation="Execute", permit="P1", nonce="N1", auth="A1", action="X1", value=1):
        runtime.identity.declare(identity_id="operator-1", declaration={"kind": "human_operator"}, source_ref="decl:1")
        self.verify_identity(runtime)
        consequence = {"adapter_id": "fake", "ceta_operation": operation, "resource": "R1", "mutation": {"value": value}}
        p = TransitionProposal(runtime.ledger.current_state_ref, "Authorize", {
            "authorization_id": auth, "permit_id": permit, "nonce": nonce, "subject_id": "operator-1", "subject_scope": "R1", "operation": operation,
            "consequence": consequence, "consumer_id": "effect_gateway", "consumer_key_id": "gw-key", "expires_at_epoch_ms": 1000, "source_refs": ["policy:1"],
        }, "transition_policy_model")
        assertion = AuthorityAssertion.sign(
            assertion_id="ROOT-AUTH-" + auth,
            principal_id="owner",
            root_key_id="root-key",
            input_state_ref=runtime.ledger.current_state_ref,
            allowed_operations=("Authorize",),
            capabilities=("authorize",),
            issued_at_epoch_ms=90,
            expires_at_epoch_ms=200,
            private_key=self.authority_root_key,
        )
        r = runtime.commit(p, transition_id="T-AUTH-" + auth, authority_assertion=assertion, now_epoch_ms=100)
        self.assertIsNotNone(r.entry)
        runtime.materialize_permit(auth, now_ms=100)
        p2 = TransitionProposal(runtime.ledger.current_state_ref, operation, {"action_id": action, "authorization_ref": auth, "consequence": consequence}, "transition_policy_model")
        r2 = runtime.commit(p2, transition_id="T-" + operation + "-" + action, now_epoch_ms=110)
        self.assertIsNotNone(r2.entry)
        return consequence

    def observe(self, receipt, status, consequence_hash, observation_id):
        return EffectObservation.sign(
            observation_id=observation_id,
            receipt_hash=receipt.receipt_hash,
            observer_id="independent_sensor",
            observer_key_id="sensor-key",
            observed_status=status,
            observed_consequence_hash=consequence_hash,
            private_key=self.observer_key,
        )

    def test_execute_verified_reality_settles_action_and_consumes_authority(self):
        runtime = self.make_runtime(); self.authorize_action(runtime)
        settled = runtime.execute_and_settle(
            action_ref="X1",
            observer=lambda receipt: self.observe(receipt, PermitStatus.COMPLETED, receipt.permitted_consequence_hash, "OBS-EFFECT-1"),
            now_ms=120, evidence_transition_id="T-EVID-1", settlement_transition_id="T-SETTLE-1",
            evidence_id="E-EFFECT-1", settled_action_id="X1-VERIFIED",
        )
        self.assertEqual(settled.verification.status.value, "VERIFIED")
        self.assertTrue(runtime.authority.consumed("N1"))
        active = {x.object_id: x for x in runtime.ledger.replay_projection().snapshot().active_objects}
        self.assertNotIn("X1", active)
        self.assertEqual(active["X1-VERIFIED"].content["verification_status"], "VERIFIED")
        runtime.ledger.verify(); self.assertTrue(runtime.authority.verify())
        self.assertEqual(runtime.memory.state_ref, runtime.ledger.current_state_ref)
        self.tmp.cleanup()

    def test_effect_mismatch_invalidates_action_instead_of_accepting_executor_claim(self):
        runtime = self.make_runtime(); self.authorize_action(runtime)
        settled = runtime.execute_and_settle(
            action_ref="X1",
            observer=lambda receipt: self.observe(receipt, PermitStatus.COMPLETED, "wrong-hash", "OBS-EFFECT-2"),
            now_ms=120, evidence_transition_id="T-EVID-2", settlement_transition_id="T-SETTLE-2",
            evidence_id="E-EFFECT-2", settled_action_id="X1-INVALID",
        )
        self.assertEqual(settled.verification.status.value, "MISMATCH")
        active = {x.object_id: x for x in runtime.ledger.replay_projection().snapshot().active_objects}
        self.assertEqual(active["X1-INVALID"].content["status"], "INVALIDATED")
        self.tmp.cleanup()

    def test_indeterminate_effect_suspends_action(self):
        runtime = self.make_runtime(adapter=FakeAdapter(PermitStatus.INDETERMINATE)); self.authorize_action(runtime)
        settled = runtime.execute_and_settle(
            action_ref="X1",
            observer=lambda receipt: self.observe(receipt, PermitStatus.INDETERMINATE, None, "OBS-EFFECT-3"),
            now_ms=120, evidence_transition_id="T-EVID-3", settlement_transition_id="T-SETTLE-3",
            evidence_id="E-EFFECT-3", settled_action_id="X1-SUSPENDED",
        )
        self.assertEqual(settled.verification.status.value, "INDETERMINATE")
        active = {x.object_id: x for x in runtime.ledger.replay_projection().snapshot().active_objects}
        self.assertEqual(active["X1-SUSPENDED"].content["status"], "SUSPENDED")
        self.tmp.cleanup()

    def test_forged_authority_assertion_is_rejected_before_vm_authority(self):
        from runtime import RuntimeBindingError
        runtime=self.make_runtime()
        runtime.identity.declare(identity_id="operator-1",declaration={"kind":"human_operator"},source_ref="decl:1")
        self.verify_identity(runtime, assertion_id='IDV-FORGED-SETUP')
        consequence={"adapter_id":"fake","ceta_operation":"Execute","resource":"R1","mutation":{"value":1}}
        proposal=TransitionProposal(runtime.ledger.current_state_ref,"Authorize",{
            "authorization_id":"A1","permit_id":"P1","nonce":"N1","subject_id":"operator-1","subject_scope":"R1","operation":"Execute",
            "consequence":consequence,"consumer_id":"effect_gateway","consumer_key_id":"gw-key","expires_at_epoch_ms":1000,"source_refs":["policy:1"]},"transition_policy_model")
        attacker=Ed25519PrivateKey.generate()
        forged=AuthorityAssertion.sign(assertion_id="BAD",principal_id="owner",root_key_id="root-key",input_state_ref=runtime.ledger.current_state_ref,allowed_operations=("Authorize",),capabilities=("authorize",),issued_at_epoch_ms=90,expires_at_epoch_ms=200,private_key=attacker)
        with self.assertRaises(RuntimeBindingError):
            runtime.commit(proposal,transition_id="T-BAD",authority_assertion=forged,now_epoch_ms=100)
        self.assertEqual(runtime.ledger.current_state_ref,proposal.input_state_ref)
        self.tmp.cleanup()

    def test_effect_transition_reserves_permit_and_blocks_second_pending_action(self):
        runtime=self.make_runtime(); consequence=self.authorize_action(runtime)
        self.assertEqual(runtime.authority.status("P1"),PermitStatus.PREPARED)
        second=TransitionProposal(runtime.ledger.current_state_ref,"Execute",{"action_id":"X2","authorization_ref":"A1","consequence":consequence},"transition_policy_model")
        result=runtime.commit(second,transition_id="T-EXEC-X2",now_epoch_ms=111)
        self.assertIsNone(result.entry)
        self.assertEqual(result.decision.reason_code,"OPERATIONAL_PERMIT_NOT_AVAILABLE")
        self.tmp.cleanup()

    def test_prepared_effect_survives_restart_and_resumes_exact_intent(self):
        runtime=self.make_runtime(); self.authorize_action(runtime)
        base=Path(self.tmp.name)
        self.assertEqual(runtime.authority.status("P1"),PermitStatus.PREPARED)
        reopened_ledger=TransitionLedger(base/"transitions.jsonl",known_operations=OPS)
        reopened_authority=AuthorityLedger(base/"authority.jsonl")
        adapter=FakeAdapter()
        gateway=EffectGateway(authority=reopened_authority,component_id="effect_gateway",key_id="gw-key",signing_private_key=self.gateway_key,adapters={"fake":adapter})
        verifier=EffectVerifier("effect_verifier",trusted_gateway_keys={"gw-key":gateway.public_key},trusted_observers={"independent_sensor":("sensor-key",self.observer_key.public_key())})
        resumed=CetaRuntime(ledger=reopened_ledger,vm=ConstitutionalVM(),evidence=EvidenceRegistry(base/'evidence.jsonl'),identity=IdentityRegistry(base/'identity.jsonl',trusted_verifier=TrustedIdentityVerifier({'idv':('idv-key',self.identity_key.public_key())})),authority=reopened_authority,effect_gateway=gateway,effect_verifier=verifier)
        settled=resumed.execute_and_settle(action_ref="X1",observer=lambda receipt:self.observe(receipt,PermitStatus.COMPLETED,receipt.permitted_consequence_hash,"OBS-RESUME"),now_ms=120,evidence_transition_id="T-EVID-R",settlement_transition_id="T-SETTLE-R",evidence_id="E-R",settled_action_id="X1-R")
        self.assertEqual(settled.verification.status.value,"VERIFIED")
        self.assertTrue(reopened_authority.consumed("N1"))
        self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
