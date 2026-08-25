from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authority import AuthorityAssertion, AuthorityAssertionError, TrustedAuthorityVerifier
from identity_registry import (
    IdentityAssertion,
    IdentityRegistry,
    IdentityRegistryError,
    IdentityStatus,
    TrustedIdentityVerifier,
)


class IdentityAuthorityTrustTests(unittest.TestCase):
    def test_identity_status_cannot_change_without_trusted_verifier(self):
        key = Ed25519PrivateKey.generate()
        r = IdentityRegistry()
        declared = r.declare(identity_id="human-1", declaration={"role": "operator"}, source_ref="decl:1")
        assertion = IdentityAssertion.sign(
            assertion_id="IV-1", identity_id="human-1", prior_record_hash=declared.record_hash,
            target_status="VERIFIED", verifier_id="idv", verifier_key_id="id-key",
            verification_code="BOUND_KEY", issued_at_epoch_ms=10, expires_at_epoch_ms=100,
            private_key=key,
        )
        with self.assertRaises(IdentityRegistryError):
            r.verify("human-1", assertion=assertion, now_epoch_ms=20)
        self.assertEqual(r.latest("human-1").status, IdentityStatus.DECLARED)

    def test_forged_identity_verification_is_rejected(self):
        trusted = Ed25519PrivateKey.generate()
        attacker = Ed25519PrivateKey.generate()
        r = IdentityRegistry(trusted_verifier=TrustedIdentityVerifier({"idv": ("id-key", trusted.public_key())}))
        declared = r.declare(identity_id="human-1", declaration={"role": "operator"}, source_ref="decl:1")
        forged = IdentityAssertion.sign(
            assertion_id="IV-BAD", identity_id="human-1", prior_record_hash=declared.record_hash,
            target_status="VERIFIED", verifier_id="idv", verifier_key_id="id-key",
            verification_code="BOUND_KEY", issued_at_epoch_ms=10, expires_at_epoch_ms=100,
            private_key=attacker,
        )
        with self.assertRaises(IdentityRegistryError):
            r.verify("human-1", assertion=forged, now_epoch_ms=20)

    def test_identity_assertion_is_revision_bound(self):
        key = Ed25519PrivateKey.generate()
        verifier = TrustedIdentityVerifier({"idv": ("id-key", key.public_key())})
        r = IdentityRegistry(trusted_verifier=verifier)
        declared = r.declare(identity_id="human-1", declaration={"role": "operator"}, source_ref="decl:1")
        first = IdentityAssertion.sign(
            assertion_id="IV-1", identity_id="human-1", prior_record_hash=declared.record_hash,
            target_status="VERIFIED", verifier_id="idv", verifier_key_id="id-key",
            verification_code="BOUND_KEY", issued_at_epoch_ms=10, expires_at_epoch_ms=100,
            private_key=key,
        )
        r.verify("human-1", assertion=first, now_epoch_ms=20)
        with self.assertRaises(IdentityRegistryError):
            r.verify("human-1", assertion=first, now_epoch_ms=30)

    def test_verified_identity_reloads_only_with_matching_trust_root(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identity.jsonl"
            key = Ed25519PrivateKey.generate()
            verifier = TrustedIdentityVerifier({"idv": ("id-key", key.public_key())})
            r = IdentityRegistry(path, trusted_verifier=verifier)
            declared = r.declare(identity_id="human-1", declaration={"role": "operator"}, source_ref="decl:1")
            assertion = IdentityAssertion.sign(
                assertion_id="IV-1", identity_id="human-1", prior_record_hash=declared.record_hash,
                target_status="VERIFIED", verifier_id="idv", verifier_key_id="id-key",
                verification_code="BOUND_KEY", issued_at_epoch_ms=10, expires_at_epoch_ms=100,
                private_key=key,
            )
            r.verify("human-1", assertion=assertion, now_epoch_ms=20)
            self.assertTrue(IdentityRegistry(path, trusted_verifier=verifier).verify_integrity())
            wrong = Ed25519PrivateKey.generate()
            with self.assertRaises(IdentityRegistryError):
                IdentityRegistry(path, trusted_verifier=TrustedIdentityVerifier({"idv": ("id-key", wrong.public_key())}))

    def test_authority_assertion_is_bound_to_state_operation_and_time(self):
        key = Ed25519PrivateKey.generate()
        verifier = TrustedAuthorityVerifier({"root": key.public_key()})
        assertion = AuthorityAssertion.sign(
            assertion_id="AA-1", principal_id="owner", root_key_id="root", input_state_ref="state-A",
            allowed_operations=("Authorize",), capabilities=("authorize",),
            issued_at_epoch_ms=10, expires_at_epoch_ms=100, private_key=key,
        )
        accepted = verifier.verify_for(assertion, input_state_ref="state-A", operation="Authorize", now_epoch_ms=20)
        self.assertEqual(accepted["authorized_capabilities"], ["authorize"])
        with self.assertRaises(AuthorityAssertionError):
            verifier.verify_for(assertion, input_state_ref="state-B", operation="Authorize", now_epoch_ms=20)
        with self.assertRaises(AuthorityAssertionError):
            verifier.verify_for(assertion, input_state_ref="state-A", operation="Execute", now_epoch_ms=20)
        with self.assertRaises(AuthorityAssertionError):
            verifier.verify_for(assertion, input_state_ref="state-A", operation="Authorize", now_epoch_ms=100)

    def test_forged_authority_assertion_is_rejected(self):
        trusted = Ed25519PrivateKey.generate()
        attacker = Ed25519PrivateKey.generate()
        verifier = TrustedAuthorityVerifier({"root": trusted.public_key()})
        assertion = AuthorityAssertion.sign(
            assertion_id="AA-BAD", principal_id="owner", root_key_id="root", input_state_ref="state-A",
            allowed_operations=("Authorize",), capabilities=("authorize",),
            issued_at_epoch_ms=10, expires_at_epoch_ms=100, private_key=attacker,
        )
        with self.assertRaises(AuthorityAssertionError):
            verifier.verify_for(assertion, input_state_ref="state-A", operation="Authorize", now_epoch_ms=20)


if __name__ == "__main__":
    unittest.main()
