from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from authority import PermitStatus


class EffectBindingError(ValueError):
    pass


class EffectVerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    INDETERMINATE = "INDETERMINATE"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _domain_bytes(domain: str, value: Mapping[str, Any]) -> bytes:
    return (domain + "\n" + canonical_json(dict(value))).encode("utf-8")


def receipt_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_domain_bytes("CETA/EFFECT_EXECUTION_RECEIPT/v1", value)).hexdigest()


@dataclass(frozen=True)
class GatewayInvocation:
    permit_id: str
    intent_hash: str
    consequence_hash: str
    adapter_id: str
    gateway_id: str
    key_id: str
    signature_hex: str

    def unsigned_body(self) -> dict[str, Any]:
        return {
            "permit_id": self.permit_id,
            "intent_hash": self.intent_hash,
            "consequence_hash": self.consequence_hash,
            "adapter_id": self.adapter_id,
            "gateway_id": self.gateway_id,
            "key_id": self.key_id,
        }

    @property
    def invocation_hash(self) -> str:
        body = {**self.unsigned_body(), "signature_hex": self.signature_hex}
        return "sha256:" + hashlib.sha256(_domain_bytes("CETA/GATEWAY_INVOCATION_RECORD/v1", body)).hexdigest()

    @classmethod
    def sign(
        cls,
        *,
        permit_id: str,
        intent_hash: str,
        consequence_hash: str,
        adapter_id: str,
        gateway_id: str,
        key_id: str,
        private_key: Ed25519PrivateKey,
    ) -> "GatewayInvocation":
        body = {
            "permit_id": permit_id,
            "intent_hash": intent_hash,
            "consequence_hash": consequence_hash,
            "adapter_id": adapter_id,
            "gateway_id": gateway_id,
            "key_id": key_id,
        }
        signature = private_key.sign(_domain_bytes("CETA/GATEWAY_INVOCATION/v1", body)).hex()
        return cls(**body, signature_hex=signature)

    def verify(self, public_key: Ed25519PublicKey) -> bool:
        try:
            public_key.verify(
                bytes.fromhex(self.signature_hex),
                _domain_bytes("CETA/GATEWAY_INVOCATION/v1", self.unsigned_body()),
            )
            return True
        except (InvalidSignature, ValueError):
            return False


@dataclass(frozen=True)
class AdapterAttempt:
    """Executor-side claim only; this is not independent reality verification."""

    status: PermitStatus
    claim: Mapping[str, Any]
    actual_consequence_hash: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            PermitStatus.COMPLETED,
            PermitStatus.FAILED_BEFORE_EFFECT,
            PermitStatus.PARTIALLY_APPLIED,
            PermitStatus.INDETERMINATE,
        }:
            raise EffectBindingError(f"invalid adapter terminal status: {self.status}")


@dataclass(frozen=True)
class EffectExecutionReceipt:
    receipt_id: str
    permit_id: str
    permit_nonce: str
    intent_hash: str
    ceta_operation: str
    adapter_id: str
    permitted_consequence_hash: str
    executor_component_id: str
    executor_key_id: str
    gateway_invocation_hash: str
    executor_claim_status: PermitStatus
    executor_claim_json: str
    actual_consequence_hash: str | None
    receipt_hash: str
    gateway_signature_hex: str

    @property
    def executor_claim(self) -> dict[str, Any]:
        return json.loads(self.executor_claim_json)

    def body_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "permit_id": self.permit_id,
            "permit_nonce": self.permit_nonce,
            "intent_hash": self.intent_hash,
            "ceta_operation": self.ceta_operation,
            "adapter_id": self.adapter_id,
            "permitted_consequence_hash": self.permitted_consequence_hash,
            "executor_component_id": self.executor_component_id,
            "executor_key_id": self.executor_key_id,
            "gateway_invocation_hash": self.gateway_invocation_hash,
            "executor_claim_status": self.executor_claim_status.value,
            "executor_claim": self.executor_claim,
            "actual_consequence_hash": self.actual_consequence_hash,
        }

    def verify_integrity(self) -> bool:
        return receipt_hash(self.body_dict()) == self.receipt_hash

    def verify_signature(self, public_key: Ed25519PublicKey) -> bool:
        try:
            public_key.verify(
                bytes.fromhex(self.gateway_signature_hex),
                _domain_bytes("CETA/EFFECT_EXECUTION_RECEIPT_SIGNATURE/v1", self.body_dict()),
            )
            return True
        except (InvalidSignature, ValueError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {**self.body_dict(), "receipt_hash": self.receipt_hash, "gateway_signature_hex": self.gateway_signature_hex}


@dataclass(frozen=True)
class EffectObservation:
    """Independent signed observation supplied to EffectVerifier."""

    observation_id: str
    receipt_hash: str
    observer_id: str
    observer_key_id: str
    observed_status: PermitStatus
    observed_consequence_hash: str | None
    evidence_refs: tuple[str, ...]
    signature_hex: str

    def unsigned_body(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "receipt_hash": self.receipt_hash,
            "observer_id": self.observer_id,
            "observer_key_id": self.observer_key_id,
            "observed_status": self.observed_status.value,
            "observed_consequence_hash": self.observed_consequence_hash,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def sign(
        cls,
        *,
        observation_id: str,
        receipt_hash: str,
        observer_id: str,
        observer_key_id: str,
        observed_status: PermitStatus,
        observed_consequence_hash: str | None,
        private_key: Ed25519PrivateKey,
        evidence_refs: tuple[str, ...] = (),
    ) -> "EffectObservation":
        body = {
            "observation_id": observation_id,
            "receipt_hash": receipt_hash,
            "observer_id": observer_id,
            "observer_key_id": observer_key_id,
            "observed_status": observed_status.value,
            "observed_consequence_hash": observed_consequence_hash,
            "evidence_refs": list(evidence_refs),
        }
        signature = private_key.sign(_domain_bytes("CETA/EFFECT_OBSERVATION/v1", body)).hex()
        return cls(
            observation_id=observation_id,
            receipt_hash=receipt_hash,
            observer_id=observer_id,
            observer_key_id=observer_key_id,
            observed_status=observed_status,
            observed_consequence_hash=observed_consequence_hash,
            evidence_refs=tuple(evidence_refs),
            signature_hex=signature,
        )

    def verify_signature(self, public_key: Ed25519PublicKey) -> bool:
        try:
            public_key.verify(
                bytes.fromhex(self.signature_hex),
                _domain_bytes("CETA/EFFECT_OBSERVATION/v1", self.unsigned_body()),
            )
            return True
        except (InvalidSignature, ValueError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_body(), "signature_hex": self.signature_hex}


@dataclass(frozen=True)
class EffectVerification:
    receipt_hash: str
    observation_id: str
    verifier_id: str
    status: EffectVerificationStatus
    reason_code: str
    expected_consequence_hash: str
    observed_consequence_hash: str | None
