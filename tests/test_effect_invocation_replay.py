from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from authority import AuthorityLedger, Permit, PermitReuseError, PermitStatus, canonical_hash  # noqa: E402
from effects import AdapterAttempt, EffectGateway, GatewayInvocation  # noqa: E402
from tool_adapters import AdapterBindingError, GatewayBoundAdapter  # noqa: E402


class RecordingAdapter(GatewayBoundAdapter):
    def __init__(self, outcome=PermitStatus.COMPLETED, failure=None):
        super().__init__("recording")
        self.outcome = outcome
        self.failure = failure
        self.attempts = 0
        self.invocation = None
        self.context = None

    def perform(self, consequence, invocation):
        self.invocation = invocation
        self.context = copy_context()
        if self.failure == "before_verification":
            raise RuntimeError("adapter failed before verifying the invocation")
        invocation_hash = self.verify_gateway_invocation(consequence, invocation)
        self.attempts += 1
        if self.failure == "after_verification":
            raise RuntimeError("effect outcome is unknown")
        return AdapterAttempt(self.outcome, {"gateway_invocation_hash": invocation_hash})


class EffectInvocationReplayTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.consequence = {
            "ceta_operation": "Execute",
            "adapter_id": "recording",
            "resource": "bounded",
            "mutation": {"value": 1},
        }

    def issue(self, authority, permit_id="P1"):
        permit = Permit(
            permit_id=permit_id,
            nonce="N-" + permit_id,
            policy_epoch="E1",
            subject_scope="bounded",
            operation="Execute",
            consequence_hash=canonical_hash(self.consequence),
            consumer_id="effect_gateway",
            consumer_key_id="gateway-key",
            expires_at_epoch_ms=1000,
            source_refs=("policy:1",),
        )
        authority.issue(permit, consequence=self.consequence, now_ms=1)
        return permit

    def gateway(self, authority, adapter):
        return EffectGateway(
            authority=authority,
            component_id="effect_gateway",
            key_id="gateway-key",
            signing_private_key=self.key,
            adapters={"recording": adapter},
        )

    def test_signed_invocation_cannot_replay_after_any_terminal_result(self):
        for status in (
            PermitStatus.COMPLETED,
            PermitStatus.FAILED_BEFORE_EFFECT,
            PermitStatus.PARTIALLY_APPLIED,
            PermitStatus.INDETERMINATE,
        ):
            with self.subTest(status=status):
                authority = AuthorityLedger()
                self.issue(authority)
                adapter = RecordingAdapter(status)
                receipt = self.gateway(authority, adapter).execute(
                    "P1", consequence=self.consequence, now_ms=2,
                )
                root = authority.current_root
                with self.assertRaises(AdapterBindingError):
                    adapter.perform(self.consequence, adapter.invocation)
                self.assertEqual(adapter.attempts, 1)
                self.assertEqual(receipt.executor_claim_status, status)
                self.assertEqual(authority.current_root, root)

    def test_signature_alone_cannot_authorize_an_adapter_call(self):
        adapter = RecordingAdapter()
        adapter.bind_gateway(
            gateway_id="effect_gateway", key_id="gateway-key", public_key=self.key.public_key(),
        )
        invocation = GatewayInvocation.sign(
            permit_id="never-issued",
            intent_hash="never-prepared",
            consequence_hash=canonical_hash(self.consequence),
            adapter_id="recording",
            gateway_id="effect_gateway",
            key_id="gateway-key",
            private_key=self.key,
        )
        with self.assertRaises(AdapterBindingError):
            adapter.perform(self.consequence, invocation)
        self.assertEqual(adapter.attempts, 0)

    def test_restart_and_fresh_adapter_do_not_resurrect_a_signed_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.jsonl"
            authority = AuthorityLedger(path)
            self.issue(authority)
            original = RecordingAdapter()
            self.gateway(authority, original).execute("P1", consequence=self.consequence, now_ms=2)
            reopened = AuthorityLedger(path)
            replacement = RecordingAdapter()
            gateway = self.gateway(reopened, replacement)
            with self.assertRaises(AdapterBindingError):
                replacement.perform(self.consequence, original.invocation)
            with self.assertRaises(PermitReuseError):
                gateway.execute("P1", consequence=self.consequence, now_ms=3)
            self.assertEqual(replacement.attempts, 0)
            self.assertEqual(reopened.status("P1"), PermitStatus.COMPLETED)

    def test_exception_closes_dispatch_even_in_a_copied_context(self):
        for failure in ("before_verification", "after_verification"):
            with self.subTest(failure=failure):
                authority = AuthorityLedger()
                self.issue(authority)
                adapter = RecordingAdapter(failure=failure)
                receipt = self.gateway(authority, adapter).execute(
                    "P1", consequence=self.consequence, now_ms=2,
                )
                captured_context = adapter.context
                attempts = adapter.attempts
                adapter.failure = None
                with self.assertRaises(AdapterBindingError):
                    captured_context.run(adapter.perform, self.consequence, adapter.invocation)
                self.assertEqual(adapter.attempts, attempts)
                self.assertEqual(receipt.executor_claim_status, PermitStatus.INDETERMINATE)

    def test_concurrent_copied_dispatch_contexts_allow_only_one_attempt(self):
        barrier = Barrier(2)

        class RacingAdapter(RecordingAdapter):
            def perform(adapter, consequence, invocation):
                def attempt():
                    barrier.wait(timeout=5)
                    try:
                        return RecordingAdapter.perform(adapter, consequence, invocation)
                    except AdapterBindingError as error:
                        return error

                contexts = [copy_context(), copy_context()]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(context.run, attempt) for context in contexts]
                    results = [future.result(timeout=10) for future in futures]
                adapter.results = results
                return next(result for result in results if isinstance(result, AdapterAttempt))

        authority = AuthorityLedger()
        self.issue(authority)
        adapter = RacingAdapter()
        receipt = self.gateway(authority, adapter).execute("P1", consequence=self.consequence, now_ms=2)
        self.assertEqual(adapter.attempts, 1)
        self.assertEqual(sum(isinstance(result, AdapterBindingError) for result in adapter.results), 1)
        self.assertEqual(receipt.executor_claim_status, PermitStatus.COMPLETED)

    def test_reentrant_duplicate_is_rejected_while_dispatch_is_still_active(self):
        case = self

        class ReentrantAdapter(RecordingAdapter):
            def perform(adapter, consequence, invocation):
                result = super().perform(consequence, invocation)
                with case.assertRaises(AdapterBindingError):
                    RecordingAdapter.perform(adapter, consequence, invocation)
                return result

        authority = AuthorityLedger()
        self.issue(authority)
        adapter = ReentrantAdapter()
        receipt = self.gateway(authority, adapter).execute("P1", consequence=self.consequence, now_ms=2)
        self.assertEqual(receipt.executor_claim_status, PermitStatus.COMPLETED)
        self.assertEqual(adapter.attempts, 1)

    def test_invalid_signature_and_consequence_do_not_claim_the_live_dispatch(self):
        case = self

        class ValidatingAdapter(RecordingAdapter):
            def perform(adapter, consequence, invocation):
                with case.assertRaises(AdapterBindingError):
                    adapter.verify_gateway_invocation(
                        consequence, replace(invocation, signature_hex="00" * 64),
                    )
                with case.assertRaises(AdapterBindingError):
                    adapter.verify_gateway_invocation({**consequence, "resource": "other"}, invocation)
                return super().perform(consequence, invocation)

        authority = AuthorityLedger()
        self.issue(authority)
        adapter = ValidatingAdapter()
        receipt = self.gateway(authority, adapter).execute("P1", consequence=self.consequence, now_ms=2)
        self.assertEqual(receipt.executor_claim_status, PermitStatus.COMPLETED)
        self.assertEqual(adapter.attempts, 1)

    def test_live_invocation_cannot_be_claimed_by_another_adapter_instance(self):
        case = self
        other = RecordingAdapter()
        other.bind_gateway(
            gateway_id="effect_gateway", key_id="gateway-key", public_key=self.key.public_key(),
        )

        class ExactAdapter(RecordingAdapter):
            def perform(adapter, consequence, invocation):
                with case.assertRaises(AdapterBindingError):
                    other.perform(consequence, invocation)
                return super().perform(consequence, invocation)

        authority = AuthorityLedger()
        self.issue(authority)
        adapter = ExactAdapter()
        receipt = self.gateway(authority, adapter).execute("P1", consequence=self.consequence, now_ms=2)
        self.assertEqual(receipt.executor_claim_status, PermitStatus.COMPLETED)
        self.assertEqual(adapter.attempts, 1)
        self.assertEqual(other.attempts, 0)

    def test_fresh_permit_can_perform_the_same_consequence(self):
        authority = AuthorityLedger()
        self.issue(authority)
        self.issue(authority, "P2")
        adapter = RecordingAdapter()
        gateway = self.gateway(authority, adapter)
        for permit_id in ("P1", "P2"):
            receipt = gateway.execute(permit_id, consequence=self.consequence, now_ms=2)
            self.assertEqual(receipt.executor_claim_status, PermitStatus.COMPLETED)
        self.assertEqual(adapter.attempts, 2)
        self.assertTrue(authority.verify())


if __name__ == "__main__":
    unittest.main()
