from __future__ import annotations

from typing import Mapping, Protocol
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from authority import AuthorityLedger, PermitStatus
from .model import (
    AdapterAttempt,
    EffectBindingError,
    EffectExecutionReceipt,
    GatewayInvocation,
    canonical_json,
    receipt_hash,
)


class EffectAdapter(Protocol):
    adapter_id: str

    def bind_gateway(
        self,
        *,
        gateway_id: str,
        key_id: str,
        public_key: Ed25519PublicKey,
    ) -> None:
        ...

    def perform(
        self,
        consequence: Mapping[str, object],
        invocation: GatewayInvocation,
    ) -> AdapterAttempt:
        ...


class EffectGateway:
    """Single external-effect boundary.

    Routing is validated before authority is touched. The exact permit is
    prepared and consumed before an adapter can observe the request. The adapter
    receives a gateway-signed invocation bound to the consumed intent and exact
    consequence hash. The gateway records only an executor claim and owns no
    authority to verify resulting external reality.
    """

    def __init__(
        self,
        *,
        authority: AuthorityLedger,
        component_id: str,
        key_id: str,
        signing_private_key: Ed25519PrivateKey,
        adapters: Mapping[str, EffectAdapter],
    ) -> None:
        if not component_id.strip() or not key_id.strip():
            raise EffectBindingError("effect gateway identity and key must be explicit")
        if not isinstance(signing_private_key, Ed25519PrivateKey):
            raise EffectBindingError("effect gateway requires an Ed25519 signing private key")
        self._authority = authority
        self.component_id = component_id
        self.key_id = key_id
        self._signing_private_key = signing_private_key
        self._public_key = signing_private_key.public_key()
        self._adapters = dict(adapters)
        for registered_id, adapter in self._adapters.items():
            if getattr(adapter, "adapter_id", None) != registered_id:
                raise EffectBindingError("registered adapter identity mismatch")
            binder = getattr(adapter, "bind_gateway", None)
            if not callable(binder):
                raise EffectBindingError(f"adapter {registered_id} does not enforce gateway binding")
            binder(gateway_id=self.component_id, key_id=self.key_id, public_key=self._public_key)

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._public_key

    def validate_route(self, consequence: Mapping[str, object]) -> EffectAdapter:
        if not isinstance(consequence, Mapping):
            raise EffectBindingError("effect consequence must be a mapping")
        ceta_operation = consequence.get("ceta_operation")
        adapter_id = consequence.get("adapter_id")
        if ceta_operation not in {"Execute", "Rollback"}:
            raise EffectBindingError("effect consequence must bind CETA Execute or Rollback")
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            raise EffectBindingError("effect consequence must bind an adapter_id")
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            raise EffectBindingError(f"unknown effect adapter: {adapter_id}")
        if getattr(adapter, "adapter_id", None) != adapter_id:
            raise EffectBindingError("registered adapter identity mismatch")
        return adapter

    def execute(
        self,
        permit_id: str,
        *,
        consequence: Mapping[str, object],
        now_ms: int,
    ) -> EffectExecutionReceipt:
        adapter = self.validate_route(consequence)
        ceta_operation = consequence.get("ceta_operation")
        adapter_id = consequence.get("adapter_id")

        permit = self._authority.permit(permit_id)
        if permit.operation != ceta_operation:
            raise EffectBindingError("permit operation does not match consequence CETA operation")

        if self._authority.status(permit_id) is PermitStatus.ISSUED:
            intent_hash = self._authority.prepare(
                permit_id,
                consumer_id=self.component_id,
                consumer_key_id=self.key_id,
                consequence=consequence,
                now_ms=now_ms,
            )
        elif self._authority.status(permit_id) is PermitStatus.PREPARED:
            intent_hash = self._authority.resume_prepared(
                permit_id,
                consumer_id=self.component_id,
                consumer_key_id=self.key_id,
                consequence=consequence,
                now_ms=now_ms,
            )
        else:
            from authority import PermitReuseError
            raise PermitReuseError(f"cannot execute permit from {self._authority.status(permit_id)}")
        self._authority.consume(
            permit_id,
            consumer_id=self.component_id,
            consumer_key_id=self.key_id,
            intent_hash=intent_hash,
            now_ms=now_ms,
        )

        invocation = GatewayInvocation.sign(
            permit_id=permit.permit_id,
            intent_hash=intent_hash,
            consequence_hash=permit.consequence_hash,
            adapter_id=adapter_id,
            gateway_id=self.component_id,
            key_id=self.key_id,
            private_key=self._signing_private_key,
        )

        try:
            attempt = adapter.perform(dict(consequence), invocation)
        except Exception as exc:  # after consumption, absence of effect is not proven
            attempt = AdapterAttempt(
                status=PermitStatus.INDETERMINATE,
                claim={"exception_type": type(exc).__name__, "message": str(exc)},
                actual_consequence_hash=None,
            )

        actual_hash = attempt.actual_consequence_hash
        if attempt.status == PermitStatus.COMPLETED:
            # Executor claim only. Independent observation still decides whether
            # external reality actually matches this consequence.
            actual_hash = permit.consequence_hash

        self._authority.finish(
            permit_id,
            status=attempt.status,
            expected_consequence_hash=permit.consequence_hash,
            actual_consequence_hash=actual_hash,
        )

        body = {
            "receipt_id": str(uuid4()),
            "permit_id": permit.permit_id,
            "permit_nonce": permit.nonce,
            "intent_hash": intent_hash,
            "ceta_operation": ceta_operation,
            "adapter_id": adapter_id,
            "permitted_consequence_hash": permit.consequence_hash,
            "executor_component_id": self.component_id,
            "executor_key_id": self.key_id,
            "gateway_invocation_hash": invocation.invocation_hash,
            "executor_claim_status": attempt.status.value,
            "executor_claim": dict(attempt.claim),
            "actual_consequence_hash": actual_hash,
        }
        gateway_signature_hex = self._signing_private_key.sign(
            ("CETA/EFFECT_EXECUTION_RECEIPT_SIGNATURE/v1\n" + canonical_json(body)).encode("utf-8")
        ).hex()
        return EffectExecutionReceipt(
            receipt_id=body["receipt_id"],
            permit_id=permit.permit_id,
            permit_nonce=permit.nonce,
            intent_hash=intent_hash,
            ceta_operation=str(ceta_operation),
            adapter_id=adapter_id,
            permitted_consequence_hash=permit.consequence_hash,
            executor_component_id=self.component_id,
            executor_key_id=self.key_id,
            gateway_invocation_hash=invocation.invocation_hash,
            executor_claim_status=attempt.status,
            executor_claim_json=canonical_json(dict(attempt.claim)),
            actual_consequence_hash=actual_hash,
            receipt_hash=receipt_hash(body),
            gateway_signature_hex=gateway_signature_hex,
        )
