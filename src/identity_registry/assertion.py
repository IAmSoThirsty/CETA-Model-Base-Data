from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class IdentityAssertionError(ValueError):
    pass


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _material(body: Mapping[str, Any]) -> bytes:
    return b"CETA/IDENTITY_ASSERTION/v1\n" + _canonical(body)


@dataclass(frozen=True)
class IdentityAssertion:
    assertion_id: str
    identity_id: str
    prior_record_hash: str
    target_status: str
    verifier_id: str
    verifier_key_id: str
    verification_code: str
    issued_at_epoch_ms: int
    expires_at_epoch_ms: int
    signature_hex: str

    def unsigned_body(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "identity_id": self.identity_id,
            "prior_record_hash": self.prior_record_hash,
            "target_status": self.target_status,
            "verifier_id": self.verifier_id,
            "verifier_key_id": self.verifier_key_id,
            "verification_code": self.verification_code,
            "issued_at_epoch_ms": self.issued_at_epoch_ms,
            "expires_at_epoch_ms": self.expires_at_epoch_ms,
        }

    @property
    def assertion_hash(self) -> str:
        body = {**self.unsigned_body(), "signature_hex": self.signature_hex}
        return "sha256:" + hashlib.sha256(b"CETA/IDENTITY_ASSERTION_RECORD/v1\n" + _canonical(body)).hexdigest()

    @classmethod
    def sign(
        cls,
        *,
        assertion_id: str,
        identity_id: str,
        prior_record_hash: str,
        target_status: str,
        verifier_id: str,
        verifier_key_id: str,
        verification_code: str,
        issued_at_epoch_ms: int,
        expires_at_epoch_ms: int,
        private_key: Ed25519PrivateKey,
    ) -> "IdentityAssertion":
        strings = (assertion_id, identity_id, prior_record_hash, target_status, verifier_id, verifier_key_id, verification_code)
        if not all(isinstance(x, str) and x.strip() for x in strings):
            raise IdentityAssertionError("identity assertion fields must be explicit")
        if target_status not in {"VERIFIED", "REJECTED", "REVOKED"}:
            raise IdentityAssertionError("identity assertion target status is not allowed")
        if issued_at_epoch_ms < 0 or expires_at_epoch_ms <= issued_at_epoch_ms:
            raise IdentityAssertionError("identity assertion temporal bounds are invalid")
        body = {
            "assertion_id": assertion_id,
            "identity_id": identity_id,
            "prior_record_hash": prior_record_hash,
            "target_status": target_status,
            "verifier_id": verifier_id,
            "verifier_key_id": verifier_key_id,
            "verification_code": verification_code,
            "issued_at_epoch_ms": issued_at_epoch_ms,
            "expires_at_epoch_ms": expires_at_epoch_ms,
        }
        return cls(**body, signature_hex=private_key.sign(_material(body)).hex())


class TrustedIdentityVerifier:
    def __init__(self, trusted_verifiers: Mapping[str, tuple[str, Ed25519PublicKey]]) -> None:
        if not trusted_verifiers:
            raise IdentityAssertionError("trusted identity verifier set may not be empty")
        self._verifiers = dict(trusted_verifiers)

    def verify_signature_binding(
        self,
        assertion: IdentityAssertion,
        *,
        identity_id: str,
        prior_record_hash: str,
    ) -> None:
        if assertion.identity_id != identity_id or assertion.prior_record_hash != prior_record_hash:
            raise IdentityAssertionError("identity assertion is bound to another identity revision")
        trusted = self._verifiers.get(assertion.verifier_id)
        if trusted is None:
            raise IdentityAssertionError("identity verifier is not trusted")
        expected_key_id, public_key = trusted
        if assertion.verifier_key_id != expected_key_id:
            raise IdentityAssertionError("identity verifier key id mismatch")
        try:
            public_key.verify(bytes.fromhex(assertion.signature_hex), _material(assertion.unsigned_body()))
        except (InvalidSignature, ValueError) as exc:
            raise IdentityAssertionError("identity assertion signature invalid") from exc

    def verify(
        self,
        assertion: IdentityAssertion,
        *,
        identity_id: str,
        prior_record_hash: str,
        now_epoch_ms: int,
    ) -> None:
        self.verify_signature_binding(assertion, identity_id=identity_id, prior_record_hash=prior_record_hash)
        if now_epoch_ms < assertion.issued_at_epoch_ms or now_epoch_ms >= assertion.expires_at_epoch_ms:
            raise IdentityAssertionError("identity assertion is not currently valid")
