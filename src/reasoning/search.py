from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any

from ceta import ConstitutionalVM, TransitionProposal, VmDecision, VmDisposition
from history import ProjectionSnapshot


@dataclass(frozen=True)
class SearchResult:
    proposal: TransitionProposal
    decision: VmDecision


class AlternativeTransitionSearch:
    """Evaluates caller-supplied neighboring proposals without creating authority.

    This service deliberately does not synthesize semantic alternatives from
    prose. Candidate generation may be neural or deterministic elsewhere; this
    class provides a governed ranking surface over explicit proposals.
    """

    def __init__(self, vm: ConstitutionalVM) -> None:
        self.vm = vm

    def evaluate_candidates(
        self,
        candidates: Iterable[TransitionProposal],
        *,
        snapshot: ProjectionSnapshot,
        evidence_view: Mapping[str, Any] | None = None,
        authority_snapshot: Mapping[str, Any] | None = None,
        identity_view: Mapping[str, Any] | None = None,
        now_epoch_ms: int | None = None,
        constitutional_epoch: str = "",
    ) -> tuple[SearchResult, ...]:
        results = []
        for proposal in candidates:
            decision = self.vm.evaluate(
                proposal,
                projected_snapshot=snapshot,
                admitted_evidence_view=evidence_view,
                authority_snapshot=authority_snapshot,
                identity_view=identity_view,
                now_epoch_ms=now_epoch_ms,
                constitutional_epoch=constitutional_epoch,
            )
            results.append(SearchResult(proposal, decision))
        rank = {
            VmDisposition.LEGAL: 0,
            VmDisposition.ESCALATE: 1,
            VmDisposition.DENY: 2,
            VmDisposition.HALT: 3,
        }
        results.sort(key=lambda x: (rank[x.decision.disposition], x.proposal.operation, str(x.proposal.operands)))
        return tuple(results)
