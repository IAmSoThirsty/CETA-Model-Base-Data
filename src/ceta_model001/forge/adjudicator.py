from __future__ import annotations

from collections.abc import Iterable

from .types import (
    BasisClass,
    ClaimRecord,
    ClaimState,
    Evidence,
    EvidenceLink,
    EvidenceMethod,
    EvidenceRelation,
    ScopeFit,
    Verdict,
    now_iso,
)


DIRECT_METHODS = {
    EvidenceMethod.DIRECT_OBSERVATION,
    EvidenceMethod.INSTRUMENT,
    EvidenceMethod.MEASUREMENT,
    EvidenceMethod.REPLICATION,
}
REPORT_METHODS = {EvidenceMethod.DOCUMENT, EvidenceMethod.TESTIMONY}
INFERENCE_METHODS = {EvidenceMethod.INFERENCE_RECORD}


class Adjudicator:
    version = "forge-adjudicator-0.3"

    def __init__(self, blinded: bool = True):
        self.blinded = blinded

    def blind_evidence(self, evidence: Evidence) -> Evidence:
        """Strip source prestige / authority cues when identity is not evidentially relevant."""
        if evidence.identity_relevant:
            return evidence
        return Evidence(
            source=f"blinded_source_{evidence.method.value.lower()}",
            method=evidence.method,
            artifact=evidence.artifact,
            limitations=evidence.limitations,
            timestamp=evidence.timestamp,
            identity_relevant=False,
            artifact_hash=evidence.artifact_hash,
            evidence_id=evidence.evidence_id,
        )

    def count_independent_paths(
        self,
        evidence_ids: Iterable[str],
        evidence_by_id: dict[str, Evidence],
    ) -> int:
        """Calculate independent evidence paths. Shared source and artifact hashes count as single paths."""
        seen_roots: set[tuple[str, str | None]] = set()
        for eid in evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev:
                seen_roots.add((ev.source, ev.artifact_hash))
        return len(seen_roots)

    def derive(
        self,
        claim: ClaimRecord,
        evidence_by_id: dict[str, Evidence],
        links: Iterable[EvidenceLink],
        previous: ClaimState | None,
        reason: str | None = None,
        adjudicated_at: str | None = None,
    ) -> ClaimState:
        claim_links = [link for link in links if link.claim_id == claim.claim_id]
        for link in claim_links:
            if link.evidence_id not in evidence_by_id:
                raise ValueError(f"Missing evidence {link.evidence_id}")

        for link in claim_links:
            link.validate()
            evidence_by_id[link.evidence_id].validate()

        effective_evidence = (
            {eid: self.blind_evidence(ev) for eid, ev in evidence_by_id.items()}
            if self.blinded
            else evidence_by_id
        )

        supporting = [link for link in claim_links if link.relation == EvidenceRelation.SUPPORTS and link.scope_fit == ScopeFit.FULL]
        counter = [link for link in claim_links if link.relation == EvidenceRelation.CONTRADICTS and link.scope_fit != ScopeFit.NONE]
        contextual = [
            link
            for link in claim_links
            if link not in supporting and link not in counter
        ]

        basis = self._basis(effective_evidence, supporting, counter)
        verdict = self._verdict(effective_evidence, supporting, counter, contextual)
        now = adjudicated_at or now_iso()
        version = 1 if previous is None else previous.version + 1
        predecessor = None if previous is None else f"{previous.claim_id}@v{previous.version}"
        return ClaimState(
            claim_id=claim.claim_id,
            proposition=claim.proposition,
            question_plane=claim.question_plane,
            basis=basis,
            verdict=verdict,
            confidence=None,
            version=version,
            predecessor=predecessor,
            supersession_reason=reason,
            created_at=claim.created_at,
            updated_at=now,
            evidence_refs=tuple(dict.fromkeys(link.evidence_id for link in supporting)),
            counterevidence_refs=tuple(dict.fromkeys(link.evidence_id for link in counter)),
            contextual_evidence_refs=tuple(dict.fromkeys(link.evidence_id for link in contextual)),
            dependencies=claim.dependencies,
            adjudicator_version=self.version,
        )

    def _basis(
        self,
        evidence_by_id: dict[str, Evidence],
        supporting: list[EvidenceLink],
        counter: list[EvidenceLink],
    ) -> BasisClass:
        relevant = supporting + counter
        if not relevant:
            return BasisClass.NONE

        categories: set[BasisClass] = set()
        for link in relevant:
            ev = evidence_by_id[link.evidence_id]
            if ev.method in DIRECT_METHODS and link.scope_fit == ScopeFit.FULL:
                categories.add(BasisClass.OBSERVED)
            elif ev.method in REPORT_METHODS:
                categories.add(BasisClass.REPORTED)
            elif ev.method in INFERENCE_METHODS:
                categories.add(BasisClass.INFERRED)
            else:
                categories.add(BasisClass.REPORTED)

        if len(categories) == 1:
            return next(iter(categories))
        return BasisClass.MIXED

    def _verdict(
        self,
        evidence_by_id: dict[str, Evidence],
        supporting: list[EvidenceLink],
        counter: list[EvidenceLink],
        contextual: list[EvidenceLink],
    ) -> Verdict:
        if not supporting and not counter:
            return Verdict.UNVERIFIED if contextual else Verdict.UNKNOWN
        if supporting and counter:
            return Verdict.UNRESOLVED
        if supporting:
            return Verdict.SUPPORTED

        full_direct_counter = any(
            link.scope_fit == ScopeFit.FULL and evidence_by_id[link.evidence_id].method in DIRECT_METHODS
            for link in counter
        )
        return Verdict.REFUTED if full_direct_counter else Verdict.CONTRADICTED
