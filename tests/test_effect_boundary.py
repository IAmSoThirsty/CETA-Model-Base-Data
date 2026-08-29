from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from authority import AuthorityBindingError, AuthorityLedger, Permit, PermitReuseError, PermitStatus, canonical_hash  # noqa: E402
from effects import (  # noqa: E402
    AdapterAttempt,
    EffectBindingError,
    EffectGateway,
    EffectObservation,
    EffectVerificationStatus,
    EffectVerifier,
    GatewayInvocation,
)
from tool_adapters import AdapterBindingError, GatewayBoundAdapter, InMemoryMutationAdapter  # noqa: E402


class FakeAdapter(GatewayBoundAdapter):
    def __init__(self, authority=None, expected_permit="P1", outcome=PermitStatus.COMPLETED, raises=False):
        super().__init__("fake")
        self.authority = authority
        self.expected_permit = expected_permit
        self.outcome = outcome
        self.raises = raises
        self.calls = 0

    def perform(self, consequence, invocation):
        self.calls += 1
        invocation_hash = self.verify_gateway_invocation(consequence, invocation)
        if self.authority is not None:
            assert self.authority.status(self.expected_permit) == PermitStatus.CONSUMED
        if self.raises:
            raise RuntimeError("adapter uncertainty")
        return AdapterAttempt(
            self.outcome,
            {"attempted": True, "gateway_invocation_hash": invocation_hash},
        )


def issue(
    authority,
    *,
    permit_id="P1",
    nonce="N1",
    consequence=None,
    operation="Execute",
    consumer_id="effect_gateway",
    key_id="gateway-key",
):
    consequence = consequence or {
        "ceta_operation": operation,
        "adapter_id": "fake",
        "effect": {"kind": "write", "target": "bounded"},
    }
    permit = Permit(
        permit_id=permit_id,
        nonce=nonce,
        policy_epoch="E1",
        subject_scope="bounded",
        operation=operation,
        consequence_hash=canonical_hash(consequence),
        consumer_id=consumer_id,
        consumer_key_id=key_id,
        expires_at_epoch_ms=1000,
        source_refs=("T1",),
        use_limit=1,
    )
    authority.issue(permit, consequence=consequence, now_ms=1)
    return permit, consequence


class EffectBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.gateway_key = Ed25519PrivateKey.generate()
        self.observer_key = Ed25519PrivateKey.generate()

    def gateway(self, authority, adapters):
        return EffectGateway(
            authority=authority,
            component_id="effect_gateway",
            key_id="gateway-key",
            signing_private_key=self.gateway_key,
            adapters=adapters,
        )

    def verifier(self, gateway):
        return EffectVerifier(
            "effect_verifier",
            trusted_gateway_keys={"gateway-key": gateway.public_key},
            trusted_observers={"independent_sensor": ("sensor-key", self.observer_key.public_key())},
        )

    def observation(self, receipt, status, consequence_hash, *, observer_id="independent_sensor", key=None):
        signing = key or self.observer_key
        return EffectObservation.sign(
            observation_id="O1",
            receipt_hash=receipt.receipt_hash,
            observer_id=observer_id,
            observer_key_id="sensor-key",
            observed_status=status,
            observed_consequence_hash=consequence_hash,
            private_key=signing,
            evidence_refs=("E1",),
        )

    def test_authority_is_consumed_before_adapter_runs(self):
        auth = AuthorityLedger(); _, consequence = issue(auth)
        adapter = FakeAdapter(auth)
        receipt = self.gateway(auth, {"fake": adapter}).execute("P1", consequence=consequence, now_ms=2)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(auth.status("P1"), PermitStatus.COMPLETED)
        self.assertTrue(auth.consumed("N1"))
        self.assertTrue(receipt.verify_integrity())
        self.assertTrue(receipt.verify_signature(self.gateway_key.public_key()))

    def test_unknown_adapter_fails_before_authority_is_consumed(self):
        auth = AuthorityLedger(); _, consequence = issue(auth, consequence={"ceta_operation": "Execute", "adapter_id": "missing", "effect": {}})
        gateway = self.gateway(auth, {})
        with self.assertRaises(EffectBindingError):
            gateway.execute("P1", consequence=consequence, now_ms=2)
        self.assertEqual(auth.status("P1"), PermitStatus.ISSUED)
        self.assertFalse(auth.consumed("N1"))

    def test_gateway_cannot_use_permit_bound_to_other_key(self):
        auth = AuthorityLedger(); _, consequence = issue(auth, key_id="other-key")
        gateway = self.gateway(auth, {"fake": FakeAdapter()})
        with self.assertRaises(AuthorityBindingError):
            gateway.execute("P1", consequence=consequence, now_ms=2)
        self.assertFalse(auth.consumed("N1"))

    def test_adapter_exception_after_consumption_becomes_indeterminate(self):
        auth = AuthorityLedger(); _, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth, raises=True)})
        receipt = gateway.execute("P1", consequence=consequence, now_ms=2)
        self.assertEqual(receipt.executor_claim_status, PermitStatus.INDETERMINATE)
        self.assertEqual(auth.status("P1"), PermitStatus.INDETERMINATE)
        self.assertTrue(auth.consumed("N1"))

    def test_consumed_permit_cannot_execute_twice(self):
        auth = AuthorityLedger(); _, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth)})
        gateway.execute("P1", consequence=consequence, now_ms=2)
        with self.assertRaises(PermitReuseError):
            gateway.execute("P1", consequence=consequence, now_ms=3)

    def test_executor_claim_is_not_effect_verification(self):
        auth = AuthorityLedger(); _, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth)})
        receipt = gateway.execute("P1", consequence=consequence, now_ms=2)
        observation = self.observation(receipt, PermitStatus.COMPLETED, "sha256:not-the-permitted-effect")
        verification = self.verifier(gateway).verify(receipt, observation)
        self.assertEqual(verification.status, EffectVerificationStatus.MISMATCH)
        self.assertEqual(receipt.executor_claim_status, PermitStatus.COMPLETED)
        self.assertEqual(auth.status("P1"), PermitStatus.COMPLETED)

    def test_matching_independent_observation_verifies_completion(self):
        auth = AuthorityLedger(); permit, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth)})
        receipt = gateway.execute("P1", consequence=consequence, now_ms=2)
        verification = self.verifier(gateway).verify(
            receipt,
            self.observation(receipt, PermitStatus.COMPLETED, permit.consequence_hash),
        )
        self.assertEqual(verification.status, EffectVerificationStatus.VERIFIED)

    def test_executor_cannot_be_its_own_observer(self):
        auth = AuthorityLedger(); permit, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth)})
        receipt = gateway.execute("P1", consequence=consequence, now_ms=2)
        observation = EffectObservation.sign(
            observation_id="O1",
            receipt_hash=receipt.receipt_hash,
            observer_id="effect_gateway",
            observer_key_id="sensor-key",
            observed_status=PermitStatus.COMPLETED,
            observed_consequence_hash=permit.consequence_hash,
            private_key=self.observer_key,
        )
        verification = self.verifier(gateway).verify(receipt, observation)
        self.assertEqual(verification.status, EffectVerificationStatus.MISMATCH)
        self.assertEqual(verification.reason_code, "OBSERVER_NOT_INDEPENDENT")

    def test_direct_adapter_call_without_gateway_invocation_is_rejected(self):
        adapter = InMemoryMutationAdapter("memory")
        adapter.bind_gateway(gateway_id="effect_gateway", key_id="gateway-key", public_key=self.gateway_key.public_key())
        consequence = {"ceta_operation": "Execute", "adapter_id": "memory", "resource": "R1", "mutation": {"value": 1}}
        with self.assertRaises(TypeError):
            adapter.perform(consequence)  # type: ignore[call-arg]

    def test_forged_gateway_invocation_is_rejected_by_adapter(self):
        attacker_key = Ed25519PrivateKey.generate()
        adapter = InMemoryMutationAdapter("memory")
        adapter.bind_gateway(gateway_id="effect_gateway", key_id="gateway-key", public_key=self.gateway_key.public_key())
        consequence = {"ceta_operation": "Execute", "adapter_id": "memory", "resource": "R1", "mutation": {"value": 1}}
        forged = GatewayInvocation.sign(
            permit_id="P1",
            intent_hash="sha256:intent",
            consequence_hash=canonical_hash(consequence),
            adapter_id="memory",
            gateway_id="effect_gateway",
            key_id="gateway-key",
            private_key=attacker_key,
        )
        with self.assertRaises(AdapterBindingError):
            adapter.perform(consequence, forged)

    def test_forged_gateway_receipt_signature_is_rejected(self):
        auth = AuthorityLedger(); permit, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth)})
        receipt = gateway.execute("P1", consequence=consequence, now_ms=2)
        forged = replace(receipt, gateway_signature_hex="00" * 64)
        result = self.verifier(gateway).verify(
            forged,
            self.observation(receipt, PermitStatus.COMPLETED, permit.consequence_hash),
        )
        self.assertEqual(result.reason_code, "RECEIPT_SIGNATURE_INVALID")

    def test_forged_observer_signature_is_rejected(self):
        auth = AuthorityLedger(); permit, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth)})
        receipt = gateway.execute("P1", consequence=consequence, now_ms=2)
        forged_observation = self.observation(
            receipt,
            PermitStatus.COMPLETED,
            permit.consequence_hash,
            key=Ed25519PrivateKey.generate(),
        )
        result = self.verifier(gateway).verify(receipt, forged_observation)
        self.assertEqual(result.reason_code, "OBSERVATION_SIGNATURE_INVALID")

    def test_partial_effect_cannot_close_as_verified(self):
        auth = AuthorityLedger(); _, consequence = issue(auth)
        gateway = self.gateway(auth, {"fake": FakeAdapter(auth, outcome=PermitStatus.PARTIALLY_APPLIED)})
        receipt = gateway.execute("P1", consequence=consequence, now_ms=2)
        observation = self.observation(receipt, PermitStatus.PARTIALLY_APPLIED, None)
        verification = self.verifier(gateway).verify(receipt, observation)
        self.assertEqual(verification.status, EffectVerificationStatus.INDETERMINATE)


if __name__ == "__main__":
    unittest.main()
