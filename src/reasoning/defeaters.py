from __future__ import annotations

from dataclasses import dataclass

from ceta import TransitionProposal
from history import ProjectionSnapshot


@dataclass(frozen=True)
class DefeaterFinding:
    target_ref: str
    kind: str
    evidence_refs: tuple[str, ...]
    reason_code: str
    proposed_transition: TransitionProposal | None


class DefeaterEngine:
    """Deterministic search over explicit state relations only.

    It does not invent counterevidence and cannot mutate state. A finding is
    produced only from contradiction/undercut/provenance information already
    present in active objects.
    """

    def __init__(self, proposer_id: str = "defeater_engine") -> None:
        self.proposer_id = proposer_id

    def scan(self, snapshot: ProjectionSnapshot) -> tuple[DefeaterFinding, ...]:
        by_id = {obj.object_id: obj for obj in snapshot.active_objects}
        findings: list[DefeaterFinding] = []
        for obj in snapshot.active_objects:
            if obj.object_type != "BELIEF":
                continue
            content = obj.content
            contradictions = tuple(x for x in content.get("contradiction_refs", []) if x in by_id)
            undercutters = tuple(x for x in content.get("undercut_refs", []) if x in by_id)
            if contradictions:
                replacement_id = f"{obj.object_id}::suspended::{len(contradictions)}"
                findings.append(
                    DefeaterFinding(
                        target_ref=obj.object_id,
                        kind="CONTRADICTION",
                        evidence_refs=contradictions,
                        reason_code="ACTIVE_CONTRADICTING_EVIDENCE",
                        proposed_transition=TransitionProposal(
                            input_state_ref=snapshot.state_ref,
                            operation="Suspend",
                            operands={
                                "target_ref": obj.object_id,
                                "replacement_id": replacement_id,
                                "reason_code": "ACTIVE_CONTRADICTING_EVIDENCE",
                                "evidence_refs": list(contradictions),
                            },
                            proposer_id=self.proposer_id,
                        ),
                    )
                )
            if undercutters:
                replacement_id = f"{obj.object_id}::suspended::u{len(undercutters)}"
                findings.append(
                    DefeaterFinding(
                        target_ref=obj.object_id,
                        kind="UNDERCUT",
                        evidence_refs=undercutters,
                        reason_code="ACTIVE_UNDERCUTTING_EVIDENCE",
                        proposed_transition=TransitionProposal(
                            input_state_ref=snapshot.state_ref,
                            operation="Suspend",
                            operands={
                                "target_ref": obj.object_id,
                                "replacement_id": replacement_id,
                                "reason_code": "ACTIVE_UNDERCUTTING_EVIDENCE",
                                "evidence_refs": list(undercutters),
                            },
                            proposer_id=self.proposer_id,
                        ),
                    )
                )
        return tuple(findings)
