from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from authority import PermitStatus, canonical_hash
from effects import AdapterAttempt, GatewayInvocation


class AdapterBindingError(RuntimeError):
    pass


class ToolAdapter(Protocol):
    adapter_id: str

    def bind_gateway(
        self,
        *,
        gateway_id: str,
        key_id: str,
        public_key: Ed25519PublicKey,
    ) -> None: ...

    def perform(
        self,
        consequence: Mapping[str, Any],
        invocation: GatewayInvocation,
    ) -> AdapterAttempt: ...


@dataclass
class GatewayBoundAdapter:
    """Reference adapter boundary that refuses unsigned/direct calls."""

    adapter_id: str

    def __post_init__(self) -> None:
        self._gateway_id: str | None = None
        self._gateway_key_id: str | None = None
        self._gateway_public_key: Ed25519PublicKey | None = None

    def bind_gateway(
        self,
        *,
        gateway_id: str,
        key_id: str,
        public_key: Ed25519PublicKey,
    ) -> None:
        if not gateway_id.strip() or not key_id.strip():
            raise AdapterBindingError("gateway identity and key id are required")
        if not isinstance(public_key, Ed25519PublicKey):
            raise AdapterBindingError("gateway public key must be Ed25519")
        if self._gateway_id is not None:
            if (
                self._gateway_id != gateway_id
                or self._gateway_key_id != key_id
                or self._gateway_public_key != public_key
            ):
                raise AdapterBindingError("adapter cannot be rebound to another gateway identity")
            return
        self._gateway_id = gateway_id
        self._gateway_key_id = key_id
        self._gateway_public_key = public_key

    def verify_gateway_invocation(
        self,
        consequence: Mapping[str, Any],
        invocation: GatewayInvocation,
    ) -> str:
        if self._gateway_public_key is None or self._gateway_id is None or self._gateway_key_id is None:
            raise AdapterBindingError("adapter is not bound to an effect gateway")
        if not isinstance(invocation, GatewayInvocation):
            raise AdapterBindingError("adapter requires a gateway-signed invocation")
        if invocation.adapter_id != self.adapter_id:
            raise AdapterBindingError("gateway invocation adapter identity mismatch")
        if invocation.gateway_id != self._gateway_id:
            raise AdapterBindingError("gateway invocation gateway identity mismatch")
        if invocation.key_id != self._gateway_key_id:
            raise AdapterBindingError("gateway invocation key identity mismatch")
        if invocation.consequence_hash != canonical_hash(consequence):
            raise AdapterBindingError("gateway invocation consequence hash mismatch")
        if not invocation.verify(self._gateway_public_key):
            raise AdapterBindingError("gateway invocation signature invalid")
        return invocation.invocation_hash


@dataclass
class InMemoryMutationAdapter(GatewayBoundAdapter):
    """Deterministic reference adapter; owns no authority or verification."""

    adapter_id: str = "memory"

    def __post_init__(self) -> None:
        super().__post_init__()
        self.state: dict[str, Any] = {}

    def perform(
        self,
        consequence: Mapping[str, Any],
        invocation: GatewayInvocation,
    ) -> AdapterAttempt:
        invocation_hash = self.verify_gateway_invocation(consequence, invocation)
        resource = consequence.get("resource")
        mutation = consequence.get("mutation")
        if not isinstance(resource, str) or not resource.strip() or not isinstance(mutation, Mapping):
            return AdapterAttempt(
                PermitStatus.FAILED_BEFORE_EFFECT,
                {"reason": "invalid_adapter_input", "gateway_invocation_hash": invocation_hash},
            )
        if consequence.get("ceta_operation") in {"Execute", "Rollback"}:
            self.state[resource] = dict(mutation)
        else:
            return AdapterAttempt(
                PermitStatus.FAILED_BEFORE_EFFECT,
                {"reason": "unsupported_operation", "gateway_invocation_hash": invocation_hash},
            )
        return AdapterAttempt(
            PermitStatus.COMPLETED,
            {
                "resource": resource,
                "state": self.state[resource],
                "gateway_invocation_hash": invocation_hash,
            },
            actual_consequence_hash=canonical_hash(consequence),
        )
