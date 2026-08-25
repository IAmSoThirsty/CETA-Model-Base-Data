from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class AuthorityAssertionError(ValueError):
    pass


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _material(body: Mapping[str, Any]) -> bytes:
    return b"CETA/AUTHORITY_ASSERTION/v1\n" + _canonical(body)


@dataclass(frozen=True)
class AuthorityAssertion:
    assertion_id: str
    principal_id: str
    root_key_id: str
    input_state_ref: str
    allowed_operations: tuple[str, ...]
    capabilities: tuple[str, ...]
    issued_at_epoch_ms: int
    expires_at_epoch_ms: int
    signature_hex: str

    def unsigned_body(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "principal_id": self.principal_id,
            "root_key_id": self.root_key_id,
            "input_state_ref": self.input_state_ref,
            "allowed_operations": list(self.allowed_operations),
            "capabilities": list(self.capabilities),
            "issued_at_epoch_ms": self.issued_at_epoch_ms,
            "expires_at_epoch_ms": self.expires_at_epoch_ms,
        }

    @property
    def assertion_hash(self) -> str:
        body = {**self.unsigned_body(), "signature_hex": self.signature_hex}
        return "sha256:" + hashlib.sha256(b"CETA/AUTHORITY_ASSERTION_RECORD/v1\n" + _canonical(body)).hexdigest()

    @classmethod
    def sign(
        cls,
        *,
        assertion_id: str,
        principal_id: str,
        root_key_id: str,
        input_state_ref: str,
        allowed_operations: tuple[str, ...],
        capabilities: tuple[str, ...],
        issued_at_epoch_ms: int,
        expires_at_epoch_ms: int,
        private_key: Ed25519PrivateKey,
    ) -> "AuthorityAssertion":
        if not all(isinstance(x, str) and x.strip() for x in (assertion_id, principal_id, root_key_id, input_state_ref)):
            raise AuthorityAssertionError("authority assertion identities and state reference must be explicit")
        if not allowed_operations or not capabilities:
            raise AuthorityAssertionError("authority assertion requires bounded operations and capabilities")
        if len(set(allowed_operations)) != len(allowed_operations) or len(set(capabilities)) != len(capabilities):
            raise AuthorityAssertionError("authority assertion contains duplicate bounds")
        if issued_at_epoch_ms < 0 or expires_at_epoch_ms <= issued_at_epoch_ms:
            raise AuthorityAssertionError("authority assertion temporal bounds are invalid")
        body = {
            "assertion_id": assertion_id,
            "principal_id": principal_id,
            "root_key_id": root_key_id,
            "input_state_ref": input_state_ref,
            "allowed_operations": list(allowed_operations),
            "capabilities": list(capabilities),
            "issued_at_epoch_ms": issued_at_epoch_ms,
            "expires_at_epoch_ms": expires_at_epoch_ms,
        }
        return cls(
            assertion_id=assertion_id,
            principal_id=principal_id,
            root_key_id=root_key_id,
            input_state_ref=input_state_ref,
            allowed_operations=tuple(allowed_operations),
            capabilities=tuple(capabilities),
            issued_at_epoch_ms=issued_at_epoch_ms,
            expires_at_epoch_ms=expires_at_epoch_ms,
            signature_hex=private_key.sign(_material(body)).hex(),
        )


class TrustedAuthorityVerifier:
    """Verifies externally issued authority assertions; never mints them."""

    def __init__(self, trusted_root_keys: Mapping[str, Ed25519PublicKey]) -> None:
        if not trusted_root_keys:
            raise AuthorityAssertionError("trusted authority root key set may not be empty")
        self._keys = dict(trusted_root_keys)

    def verify_for(
        self,
        assertion: AuthorityAssertion,
        *,
        input_state_ref: str,
        operation: str,
        now_epoch_ms: int,
    ) -> dict[str, Any]:
        if not isinstance(assertion, AuthorityAssertion):
            raise AuthorityAssertionError("authority context requires a signed AuthorityAssertion")
        key = self._keys.get(assertion.root_key_id)
        if key is None:
            raise AuthorityAssertionError("authority assertion root key is not trusted")
        if assertion.input_state_ref != input_state_ref:
            raise AuthorityAssertionError("authority assertion is bound to another input state")
        if operation not in assertion.allowed_operations:
            raise AuthorityAssertionError("authority assertion does not cover this CETA operation")
        if now_epoch_ms < assertion.issued_at_epoch_ms or now_epoch_ms >= assertion.expires_at_epoch_ms:
            raise AuthorityAssertionError("authority assertion is not currently valid")
        try:
            key.verify(bytes.fromhex(assertion.signature_hex), _material(assertion.unsigned_body()))
        except (InvalidSignature, ValueError) as exc:
            raise AuthorityAssertionError("authority assertion signature invalid") from exc
        return {
            "principal_id": assertion.principal_id,
            "assertion_id": assertion.assertion_id,
            "assertion_hash": assertion.assertion_hash,
            "authorized_capabilities": list(assertion.capabilities),
        }
