from __future__ import annotations

from dataclasses import dataclass


FAILURE_CATEGORIES: tuple[str, ...] = (
    "authority_failure",
    "source_identity_failure",
    "objective_substitution_failure",
    "pathway_failure",
    "data_adequacy_failure",
    "label_signal_failure",
    "model_capacity_failure",
    "training_budget_failure",
    "structural_output_failure",
    "semantic_competence_failure",
    "robustness_failure",
    "evaluator_failure",
    "metric_design_failure",
    "policy_engine_failure",
    "runtime_environment_failure",
    "concurrency_state_failure",
    "security_failure",
    "governance_failure",
    "ux_accessibility_failure",
    "continuity_failure",
    "recovery_failure",
    "documentation_truth_failure",
    "artifact_consistency_failure",
    "unresolved_failure_cause",
)


@dataclass(frozen=True)
class FailureClassification:
    category: str
    evidence_refs: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.category not in FAILURE_CATEGORIES:
            raise ValueError(f"unknown failure category: {self.category}")
        if self.category != "unresolved_failure_cause" and not self.evidence_refs:
            raise ValueError("specific failure categories require evidence")


def classify_failure(
    category: str | None,
    *,
    evidence_refs: tuple[str, ...] = (),
    reason: str = "",
) -> FailureClassification:
    """Specific causal labels require evidence; otherwise cause stays unresolved."""
    if category is None or category not in FAILURE_CATEGORIES or (category != "unresolved_failure_cause" and not evidence_refs):
        return FailureClassification(
            "unresolved_failure_cause",
            tuple(evidence_refs),
            reason or "evidence is insufficient to establish a specific cause",
        )
    return FailureClassification(category, tuple(evidence_refs), reason)
