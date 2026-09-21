from __future__ import annotations


from ..validation import text
from .register import ForgeRegister
from .roles import RoleBinding, RoleClass
from .types import (
    Evidence,
    EvidenceLink,
    EvidenceMethod,
    EvidenceRelation,
    Proposal,
    ScopeFit,
)


class BaseForgeRoleHarness:
    """Base class for replaceable agent harnesses in the multi-mind Forge.

    Mandatory Invariant 1:
    No agent or human harness receives direct truth-write authority.
    Harnesses submit proposals, evidence, and challenges only through the governed Forge register.
    """

    def __init__(self, participant_id: str, role_class: RoleClass, register: ForgeRegister):
        self.binding = RoleBinding(
            participant_id=participant_id,
            role_classes=(role_class,),
            truth_write_authority=False,
        )
        self.binding.validate()
        self.participant_id = participant_id
        self.role_class = role_class
        self.register = register

    def submit_proposal(self, text_content: str, about_claim: str | None = None) -> Proposal:
        text(text_content, "text_content")
        return self.register.submit_proposal(
            actor_id=self.participant_id,
            role_class=self.role_class.value,
            text=text_content,
            about_claim=about_claim,
        )

    def submit_evidence(
        self,
        *,
        source: str,
        method: EvidenceMethod,
        artifact: str,
        limitations: str,
        artifact_hash: str | None = None,
        identity_relevant: bool = False,
    ) -> Evidence:
        evidence = Evidence(
            source=source,
            method=method,
            artifact=artifact,
            limitations=limitations,
            artifact_hash=artifact_hash,
            identity_relevant=identity_relevant,
        )
        return self.register.ingest_evidence(evidence=evidence, actor_id=self.participant_id)

    def link_evidence(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        relation: EvidenceRelation,
        scope_fit: ScopeFit,
        notes: str | None = None,
    ) -> EvidenceLink:
        link = EvidenceLink(
            claim_id=claim_id,
            evidence_id=evidence_id,
            relation=relation,
            scope_fit=scope_fit,
            submitted_by=self.participant_id,
            notes=notes,
        )
        return self.register.link_evidence(link=link)

    def submit_challenge(self, *, claim_id: str, reason: str, evidence_ids: tuple[str, ...] = ()):
        return self.register.challenge_claim(
            claim_id=claim_id,
            actor_id=self.participant_id,
            reason=reason,
        )


class AnalystSynthesizerHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.ANALYST_SYNTHESIZER, register)


class HumanImpactContextHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.HUMAN_IMPACT_CONTEXT, register)


class WorldStateObserverHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.WORLD_STATE_OBSERVER, register)


class StructureCoherenceHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.STRUCTURE_COHERENCE, register)


class AdversarialReviewHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.ADVERSARIAL_REVIEW, register)


class IntegratorContinuityHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.INTEGRATOR_CONTINUITY, register)


class VerificationReproductionHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.VERIFICATION_REPRODUCTION, register)


class HumanScopeAuthorityHarness(BaseForgeRoleHarness):
    def __init__(self, participant_id: str, register: ForgeRegister):
        super().__init__(participant_id, RoleClass.HUMAN_SCOPE_AUTHORITY, register)


def create_role_harness(
    role_class: RoleClass,
    participant_id: str,
    register: ForgeRegister,
) -> BaseForgeRoleHarness:
    harnesses = {
        RoleClass.ANALYST_SYNTHESIZER: AnalystSynthesizerHarness,
        RoleClass.HUMAN_IMPACT_CONTEXT: HumanImpactContextHarness,
        RoleClass.WORLD_STATE_OBSERVER: WorldStateObserverHarness,
        RoleClass.STRUCTURE_COHERENCE: StructureCoherenceHarness,
        RoleClass.ADVERSARIAL_REVIEW: AdversarialReviewHarness,
        RoleClass.INTEGRATOR_CONTINUITY: IntegratorContinuityHarness,
        RoleClass.VERIFICATION_REPRODUCTION: VerificationReproductionHarness,
        RoleClass.HUMAN_SCOPE_AUTHORITY: HumanScopeAuthorityHarness,
    }
    cls = harnesses.get(role_class)
    if cls is None:
        raise ValueError(f"Unknown role class: {role_class}")
    return cls(participant_id, register)
