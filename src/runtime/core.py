from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Callable

from authority import (
    AuthorityAssertion,
    AuthorityAssertionError,
    AuthorityLedger,
    Permit,
    PermitStatus,
    TrustedAuthorityVerifier,
    canonical_hash,
)
from ceta import ConstitutionalVM, TransitionProposal, VmDecision, VmDisposition
from effects import EffectExecutionReceipt, EffectGateway, EffectObservation, EffectVerification, EffectVerificationStatus, EffectVerifier
from evidence_registry import EvidenceRegistry
from history import CommitCandidate, LedgerEntry, TransitionLedger
from identity_registry import IdentityRegistry
from memory_projection import MemoryProjection


class RuntimeBindingError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransitionResult:
    decision: VmDecision
    entry: LedgerEntry | None


@dataclass(frozen=True)
class EffectSettlementResult:
    receipt: EffectExecutionReceipt
    verification: EffectVerification
    evidence_entry: LedgerEntry
    settlement_entry: LedgerEntry


class CetaRuntime:
    """Reference coordinator over canonical owners.

    Coordination is not ownership: the VM decides legality, AuthorityLedger
    owns permit lifecycle, EffectGateway performs effects, EffectVerifier checks
    resulting reality, and TransitionLedger alone commits epistemic state.
    """

    def __init__(
        self,
        *,
        ledger: TransitionLedger,
        vm: ConstitutionalVM,
        evidence: EvidenceRegistry,
        identity: IdentityRegistry,
        authority: AuthorityLedger,
        authority_verifier: TrustedAuthorityVerifier | None = None,
        memory: MemoryProjection | None = None,
        effect_gateway: EffectGateway | None = None,
        effect_verifier: EffectVerifier | None = None,
        constitutional_epoch: str = "epoch-1",
    ) -> None:
        self.ledger = ledger
        self.vm = vm
        self.evidence = evidence
        self.identity = identity
        self.authority = authority
        self.authority_verifier = authority_verifier
        self.memory = memory or MemoryProjection()
        self.effect_gateway = effect_gateway
        self.effect_verifier = effect_verifier
        self.constitutional_epoch = constitutional_epoch
        # Fail closed at startup if any durable owner cannot reconstruct itself.
        self.ledger.verify()
        self.authority.verify()
        self.evidence.verify()
        self.identity.verify_integrity()
        self._refresh_memory()

    def evaluate(
        self,
        proposal: TransitionProposal,
        *,
        authority_assertion: AuthorityAssertion | None = None,
        now_epoch_ms: int | None = None,
    ) -> VmDecision:
        vm_authority_context = self.authority.snapshot()
        if authority_assertion is not None:
            if self.authority_verifier is None:
                raise RuntimeBindingError("no trusted authority verifier is configured")
            if not isinstance(now_epoch_ms, int):
                raise RuntimeBindingError("trusted evaluation time is required for authority assertion verification")
            try:
                verified = self.authority_verifier.verify_for(
                    authority_assertion,
                    input_state_ref=proposal.input_state_ref,
                    operation=proposal.operation,
                    now_epoch_ms=now_epoch_ms,
                )
            except AuthorityAssertionError as exc:
                raise RuntimeBindingError(f"authority assertion rejected: {exc}") from exc
            vm_authority_context.update(verified)
        return self.vm.evaluate(
            proposal,
            projected_snapshot=self.ledger.replay_projection().snapshot(),
            admitted_evidence_view=self.evidence.view(),
            identity_view=self.identity.view(),
            authority_snapshot=vm_authority_context,
            now_epoch_ms=now_epoch_ms,
            constitutional_epoch=self.constitutional_epoch,
        )

    def commit(
        self,
        proposal: TransitionProposal,
        *,
        transition_id: str,
        authority_assertion: AuthorityAssertion | None = None,
        now_epoch_ms: int | None = None,
        verification_extra: Mapping[str, Any] | None = None,
    ) -> TransitionResult:
        decision = self.evaluate(proposal, authority_assertion=authority_assertion, now_epoch_ms=now_epoch_ms)
        if decision.disposition is not VmDisposition.LEGAL:
            return TransitionResult(decision, None)

        projection = self.ledger.replay_projection()
        output_state_ref = projection.preview(decision.state_delta).state_ref
        proof: dict[str, Any] = {
            "vm_decision_hash": decision.decision_hash,
            "contract_hash": decision.contract_hash,
            "proof_obligations": list(decision.proof_obligations),
            "required_authority": list(decision.required_authority),
            "authority_root_before": self.authority.current_root,
        }
        if authority_assertion is not None:
            proof["authority_assertion_hash"] = authority_assertion.assertion_hash

        prepared_permit_id: str | None = None
        try:
            if proposal.operation in {"Execute", "Rollback"}:
                if self.effect_gateway is None:
                    raise RuntimeBindingError("effect transition requires a configured EffectGateway")
                if not isinstance(now_epoch_ms, int):
                    raise RuntimeBindingError("trusted evaluation time is required for effect transition")
                consequence = proposal.operands.get("consequence")
                if not isinstance(consequence, Mapping):
                    raise RuntimeBindingError("effect transition consequence must be structured")
                self.effect_gateway.validate_route(consequence)
                authorization_ref = str(proposal.operands.get("authorization_ref", ""))
                auth_obj = self._active(authorization_ref, "AUTHORITY")
                permit_id = str(auth_obj.content.get("permit_id", ""))
                permit = self.authority.permit(permit_id)
                if permit.consumer_id != self.effect_gateway.component_id or permit.consumer_key_id != self.effect_gateway.key_id:
                    raise RuntimeBindingError("operational permit is not bound to the configured EffectGateway identity/key")
                intent_hash = self.authority.prepare(
                    permit_id,
                    consumer_id=permit.consumer_id,
                    consumer_key_id=permit.consumer_key_id,
                    consequence=consequence,
                    now_ms=now_epoch_ms,
                )
                prepared_permit_id = permit_id
                proof["authority_intent_hash"] = intent_hash
                proof["authority_root_after_prepare"] = self.authority.current_root

            verification = {
                "transition_id": transition_id,
                "status": "PRECOMMIT_VERIFIED",
                "verification_plan": dict(decision.verification_plan or {}),
            }
            verification.update(dict(verification_extra or {}))
            replay = {
                "transition_id": transition_id,
                "operation": proposal.operation,
                "input_state_ref": proposal.input_state_ref,
                "output_state_ref": output_state_ref,
                "contract_hash": decision.contract_hash,
            }
            candidate = CommitCandidate.create(
                transition_id=transition_id,
                input_state_ref=proposal.input_state_ref,
                operation=proposal.operation,
                operands=proposal.operands,
                proposer_id=proposal.proposer_id,
                constitutional_epoch=self.constitutional_epoch,
                vm_decision_hash=decision.decision_hash,
                output_state_ref=output_state_ref,
                state_delta=decision.state_delta,
                proof=proof,
                verification=verification,
                replay_record=replay,
            )
            entry = self.ledger.commit(candidate)
        except Exception:
            if prepared_permit_id is not None:
                try:
                    self.authority.revoke(prepared_permit_id)
                except Exception as revoke_exc:
                    raise RuntimeBindingError(
                        f"transition commit failed after permit preparation and prepared authority could not be revoked: {revoke_exc}"
                    ) from revoke_exc
            raise
        self._refresh_memory()
        return TransitionResult(decision, entry)

    def materialize_permit(self, authorization_ref: str, *, now_ms: int) -> Permit:
        obj = self._active(authorization_ref, "AUTHORITY")
        c = obj.content
        if c.get("status") != "AUTHORIZED":
            raise RuntimeBindingError("authority object is not an authorization")
        consequence = c.get("consequence")
        if not isinstance(consequence, Mapping):
            raise RuntimeBindingError("authorization consequence is not structured")
        if canonical_hash(consequence) != c.get("consequence_hash"):
            raise RuntimeBindingError("authorization consequence hash does not reconstruct")
        permit = Permit(
            permit_id=str(c["permit_id"]),
            nonce=str(c["nonce"]),
            policy_epoch=self.constitutional_epoch,
            subject_scope=str(c["subject_scope"]),
            operation=str(c["operation"]),
            consequence_hash=str(c["consequence_hash"]),
            consumer_id=str(c["consumer_id"]),
            consumer_key_id=str(c["consumer_key_id"]),
            expires_at_epoch_ms=int(c["expires_at_epoch_ms"]),
            source_refs=tuple(str(x) for x in c.get("source_refs", [])),
            use_limit=1,
        )
        self.authority.issue(permit, consequence=consequence, now_ms=now_ms)
        return permit

    def execute_and_settle(
        self,
        *,
        action_ref: str,
        observer: Callable[[EffectExecutionReceipt], EffectObservation],
        now_ms: int,
        evidence_transition_id: str,
        settlement_transition_id: str,
        evidence_id: str,
        settled_action_id: str,
    ) -> EffectSettlementResult:
        if self.effect_gateway is None or self.effect_verifier is None:
            raise RuntimeBindingError("effect gateway and independent verifier are required")
        action = self._active(action_ref, "ACTION")
        c = action.content
        if c.get("status") not in {"EXECUTION_REQUESTED", "ROLLBACK_REQUESTED"}:
            raise RuntimeBindingError("action is not awaiting external effect")
        consequence = c.get("consequence")
        if not isinstance(consequence, Mapping):
            raise RuntimeBindingError("action consequence is not structured")
        receipt = self.effect_gateway.execute(str(c["permit_id"]), consequence=consequence, now_ms=now_ms)
        observation = observer(receipt)
        if not isinstance(observation, EffectObservation):
            raise RuntimeBindingError("independent observer must return EffectObservation")
        verification = self.effect_verifier.verify(receipt, observation)

        record_id = f"effect-verification:{receipt.receipt_hash}"
        payload = {
            "kind": "effect_verification",
            "receipt": receipt.to_dict(),
            "observation": observation.to_dict(),
            "verification": {
                "receipt_hash": verification.receipt_hash,
                "observation_id": verification.observation_id,
                "verifier_id": verification.verifier_id,
                "status": verification.status.value,
                "reason_code": verification.reason_code,
                "expected_consequence_hash": verification.expected_consequence_hash,
                "observed_consequence_hash": verification.observed_consequence_hash,
            },
        }
        self.evidence.register(record_id=record_id, source_id=self.effect_verifier.verifier_id, payload=payload, provenance_refs=(receipt.receipt_hash, observation.observation_id))
        self.evidence.validate(record_id, validator_id=self.effect_verifier.verifier_id, validation_code="VERIFICATION_RECORD_INTEGRITY_OK")

        admit = TransitionProposal(
            input_state_ref=self.ledger.current_state_ref,
            operation="AdmitEvidence",
            operands={"evidence_id": evidence_id, "evidence_record_id": record_id, "observation_refs": []},
            proposer_id="runtime_effect_settlement",
        )
        evidence_result = self.commit(admit, transition_id=evidence_transition_id, now_epoch_ms=now_ms)
        if evidence_result.entry is None:
            raise RuntimeBindingError(f"effect verification evidence could not be admitted: {evidence_result.decision.reason_code}")

        if verification.status is EffectVerificationStatus.VERIFIED:
            operation = "Verify"
            operands = {
                "target_ref": action_ref,
                "replacement_id": settled_action_id,
                "evidence_refs": [evidence_id],
                "verification_code": verification.reason_code,
            }
        elif verification.status is EffectVerificationStatus.MISMATCH:
            operation = "Invalidate"
            operands = {
                "target_ref": action_ref,
                "replacement_id": settled_action_id,
                "reason_code": verification.reason_code,
                "evidence_refs": [evidence_id],
            }
        else:
            operation = "Suspend"
            operands = {
                "target_ref": action_ref,
                "replacement_id": settled_action_id,
                "reason_code": verification.reason_code,
                "evidence_refs": [evidence_id],
            }
        settlement = TransitionProposal(
            input_state_ref=self.ledger.current_state_ref,
            operation=operation,
            operands=operands,
            proposer_id="runtime_effect_settlement",
        )
        settlement_result = self.commit(
            settlement,
            transition_id=settlement_transition_id,
            now_epoch_ms=now_ms,
            verification_extra={"effect_receipt_hash": receipt.receipt_hash, "effect_verification_status": verification.status.value},
        )
        if settlement_result.entry is None:
            raise RuntimeBindingError(f"effect settlement could not commit: {settlement_result.decision.reason_code}")
        return EffectSettlementResult(receipt, verification, evidence_result.entry, settlement_result.entry)

    def _active(self, object_ref: str, expected_type: str):
        by_id = {obj.object_id: obj for obj in self.ledger.replay_projection().snapshot().active_objects}
        try:
            obj = by_id[object_ref]
        except KeyError as exc:
            raise RuntimeBindingError(f"active object not found: {object_ref}") from exc
        if obj.object_type != expected_type:
            raise RuntimeBindingError(f"object type mismatch: expected {expected_type}, got {obj.object_type}")
        return obj

    def _refresh_memory(self) -> None:
        self.memory.rebuild(self.ledger.replay_projection().snapshot())
