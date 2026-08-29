from __future__ import annotations

from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from authority import PermitStatus
from .model import (
    EffectExecutionReceipt,
    EffectObservation,
    EffectVerification,
    EffectVerificationStatus,
)


class EffectVerifier:
    """Independent verifier over authenticated executor and observer records."""

    def __init__(
        self,
        verifier_id: str,
        *,
        trusted_gateway_keys: Mapping[str, Ed25519PublicKey],
        trusted_observers: Mapping[str, tuple[str, Ed25519PublicKey]],
    ) -> None:
        if not verifier_id.strip():
            raise ValueError("verifier_id must be explicit")
        if not trusted_gateway_keys:
            raise ValueError("at least one trusted gateway key is required")
        if not trusted_observers:
            raise ValueError("at least one trusted independent observer is required")
        self.verifier_id = verifier_id
        self._trusted_gateway_keys = dict(trusted_gateway_keys)
        self._trusted_observers = dict(trusted_observers)

    def verify(self, receipt: EffectExecutionReceipt, observation: EffectObservation) -> EffectVerification:
        failure = self._precondition_failure(receipt, observation)
        if failure is not None:
            return self._result(receipt, observation, *failure)
        return self._verify_observed_status(receipt, observation)

    def _precondition_failure(self, receipt, observation) -> tuple[EffectVerificationStatus, str] | None:
        gateway_key = self._trusted_gateway_keys.get(receipt.executor_key_id)
        if gateway_key is None:
            return EffectVerificationStatus.MISMATCH, "UNTRUSTED_GATEWAY_KEY"
        if not receipt.verify_integrity():
            return EffectVerificationStatus.MISMATCH, "RECEIPT_INTEGRITY_MISMATCH"
        if not receipt.verify_signature(gateway_key):
            return EffectVerificationStatus.MISMATCH, "RECEIPT_SIGNATURE_INVALID"
        if observation.receipt_hash != receipt.receipt_hash:
            return EffectVerificationStatus.MISMATCH, "OBSERVATION_RECEIPT_BINDING_MISMATCH"
        if not observation.observer_id.strip() or observation.observer_id == receipt.executor_component_id:
            return EffectVerificationStatus.MISMATCH, "OBSERVER_NOT_INDEPENDENT"
        trusted = self._trusted_observers.get(observation.observer_id)
        if trusted is None:
            return EffectVerificationStatus.MISMATCH, "UNTRUSTED_OBSERVER"
        expected_key_id, observer_key = trusted
        if observation.observer_key_id != expected_key_id:
            return EffectVerificationStatus.MISMATCH, "OBSERVER_KEY_ID_MISMATCH"
        if not observation.verify_signature(observer_key):
            return EffectVerificationStatus.MISMATCH, "OBSERVATION_SIGNATURE_INVALID"
        return None

    def _verify_observed_status(self, receipt, observation) -> EffectVerification:
        if observation.observed_status == PermitStatus.INDETERMINATE:
            return self._result(receipt, observation, EffectVerificationStatus.INDETERMINATE, "OBSERVED_STATE_INDETERMINATE")
        if receipt.executor_claim_status == PermitStatus.INDETERMINATE:
            return self._result(receipt, observation, EffectVerificationStatus.INDETERMINATE, "EXECUTOR_CLAIM_INDETERMINATE")
        if observation.observed_status != receipt.executor_claim_status:
            return self._result(receipt, observation, EffectVerificationStatus.MISMATCH, "EXECUTOR_OBSERVER_STATUS_MISMATCH")
        if receipt.executor_claim_status == PermitStatus.COMPLETED:
            if observation.observed_consequence_hash is None:
                return self._result(receipt, observation, EffectVerificationStatus.INDETERMINATE, "MISSING_COMPLETION_OBSERVATION")
            if observation.observed_consequence_hash != receipt.permitted_consequence_hash:
                return self._result(receipt, observation, EffectVerificationStatus.MISMATCH, "OBSERVED_CONSEQUENCE_MISMATCH")
            return self._result(receipt, observation, EffectVerificationStatus.VERIFIED, "EXTERNAL_EFFECT_VERIFIED")
        if receipt.executor_claim_status == PermitStatus.FAILED_BEFORE_EFFECT:
            if observation.observed_consequence_hash is not None:
                return self._result(receipt, observation, EffectVerificationStatus.MISMATCH, "EFFECT_OBSERVED_AFTER_NO_EFFECT_CLAIM")
            return self._result(receipt, observation, EffectVerificationStatus.VERIFIED, "NO_EFFECT_VERIFIED")
        return self._result(receipt, observation, EffectVerificationStatus.INDETERMINATE, "PARTIAL_EFFECT_REQUIRES_RECONCILIATION")

    def _result(self, receipt, observation, status, reason) -> EffectVerification:
        return EffectVerification(
            receipt_hash=receipt.receipt_hash,
            observation_id=observation.observation_id,
            verifier_id=self.verifier_id,
            status=status,
            reason_code=reason,
            expected_consequence_hash=receipt.permitted_consequence_hash,
            observed_consequence_hash=observation.observed_consequence_hash,
        )
