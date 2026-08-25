from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authority import AuthorityAssertion, AuthorityLedger, PermitStatus, TrustedAuthorityVerifier
from ceta import ConstitutionalVM, TransitionProposal
from effects import EffectGateway, EffectObservation, EffectVerifier
from evidence_registry import EvidenceRegistry
from history import TransitionLedger
from identity_registry import IdentityAssertion, IdentityRegistry, TrustedIdentityVerifier
from runtime import CetaRuntime
from tool_adapters import InMemoryMutationAdapter

OPS = {
    "Observe", "ValidateObservation", "AdmitEvidence", "RejectEvidence", "CreateClaim", "CreateBelief",
    "Support", "Contradict", "Undercut", "Merge", "Split", "NarrowScope", "ExpandScope", "Verify",
    "Invalidate", "Suspend", "Expire", "Reevaluate", "Adjudicate", "Authorize", "RejectAuthorization",
    "Execute", "Rollback",
}


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        gateway_key = Ed25519PrivateKey.generate()
        observer_key = Ed25519PrivateKey.generate()
        authority_key = Ed25519PrivateKey.generate()
        identity_key = Ed25519PrivateKey.generate()

        ledger = TransitionLedger(base / "transitions.jsonl", known_operations=OPS)
        evidence = EvidenceRegistry(base / "evidence.jsonl")
        identity_verifier = TrustedIdentityVerifier({"identity-verifier": ("identity-key", identity_key.public_key())})
        identity = IdentityRegistry(base / "identity.jsonl", trusted_verifier=identity_verifier)
        authority = AuthorityLedger(base / "authority.jsonl")
        adapter = InMemoryMutationAdapter()
        gateway = EffectGateway(
            authority=authority, component_id="effect_gateway", key_id="gateway-key",
            signing_private_key=gateway_key, adapters={"memory": adapter},
        )
        verifier = EffectVerifier(
            "effect_verifier",
            trusted_gateway_keys={"gateway-key": gateway.public_key},
            trusted_observers={"sensor": ("sensor-key", observer_key.public_key())},
        )
        runtime = CetaRuntime(
            ledger=ledger, vm=ConstitutionalVM(), evidence=evidence, identity=identity, authority=authority,
            authority_verifier=TrustedAuthorityVerifier({"authority-root": authority_key.public_key()}),
            effect_gateway=gateway, effect_verifier=verifier,
        )

        declared = identity.declare(identity_id="operator", declaration={"kind": "human_operator"}, source_ref="demo:declaration")
        identity_assertion = IdentityAssertion.sign(
            assertion_id="identity-assertion-1", identity_id="operator", prior_record_hash=declared.record_hash,
            target_status="VERIFIED", verifier_id="identity-verifier", verifier_key_id="identity-key",
            verification_code="DEMO_KEY_BOUND", issued_at_epoch_ms=10, expires_at_epoch_ms=1000,
            private_key=identity_key,
        )
        identity.verify("operator", assertion=identity_assertion, now_epoch_ms=20)

        consequence = {
            "adapter_id": "memory", "ceta_operation": "Execute", "resource": "resource-A",
            "mutation": {"state": "updated"},
        }
        auth_proposal = TransitionProposal(
            runtime.ledger.current_state_ref, "Authorize",
            {
                "authorization_id": "AUTH-1", "permit_id": "PERMIT-1", "nonce": "NONCE-1",
                "subject_id": "operator", "subject_scope": "resource-A", "operation": "Execute",
                "consequence": consequence, "consumer_id": "effect_gateway", "consumer_key_id": "gateway-key",
                "expires_at_epoch_ms": 1000, "source_refs": ["demo:policy"],
            },
            "demo-transition-policy",
        )
        authority_assertion = AuthorityAssertion.sign(
            assertion_id="authority-assertion-1", principal_id="owner", root_key_id="authority-root",
            input_state_ref=runtime.ledger.current_state_ref, allowed_operations=("Authorize",),
            capabilities=("authorize",), issued_at_epoch_ms=10, expires_at_epoch_ms=1000,
            private_key=authority_key,
        )
        auth_result = runtime.commit(auth_proposal, transition_id="T-AUTH", authority_assertion=authority_assertion, now_epoch_ms=30)
        assert auth_result.entry is not None
        runtime.materialize_permit("AUTH-1", now_ms=30)

        execute = TransitionProposal(
            runtime.ledger.current_state_ref, "Execute",
            {"action_id": "ACTION-1", "authorization_ref": "AUTH-1", "consequence": consequence},
            "demo-transition-policy",
        )
        execute_result = runtime.commit(execute, transition_id="T-EXEC", now_epoch_ms=40)
        assert execute_result.entry is not None
        assert authority.status("PERMIT-1") is PermitStatus.PREPARED

        def observe(receipt):
            return EffectObservation.sign(
                observation_id="OBS-1", receipt_hash=receipt.receipt_hash,
                observer_id="sensor", observer_key_id="sensor-key",
                observed_status=PermitStatus.COMPLETED,
                observed_consequence_hash=receipt.permitted_consequence_hash,
                private_key=observer_key,
            )

        settled = runtime.execute_and_settle(
            action_ref="ACTION-1", observer=observe, now_ms=50,
            evidence_transition_id="T-EVID", settlement_transition_id="T-SETTLE",
            evidence_id="E-EFFECT", settled_action_id="ACTION-1-VERIFIED",
        )
        assert settled.verification.status.value == "VERIFIED"
        assert authority.consumed("NONCE-1")
        ledger.verify(); authority.verify(); evidence.verify(); identity.verify_integrity()
        summary = {
            "status": "PASS",
            "state_ref": ledger.current_state_ref,
            "transition_count": len(ledger.entries),
            "permit_status": authority.status("PERMIT-1").value,
            "effect_verification": settled.verification.status.value,
            "memory_resource_state": adapter.state["resource-A"],
        }
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
