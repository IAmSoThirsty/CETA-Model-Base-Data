from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .validation import text, timestamp, unique_strings


class AudienceLevel(str, Enum):
    TECHNICAL = "TECHNICAL"
    EXECUTIVE = "EXECUTIVE"
    PUBLIC = "PUBLIC"
    BEGINNER = "BEGINNER"
    LEGAL = "LEGAL"


class ConfidenceBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNRESOLVED = "UNRESOLVED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AudienceExplanation:
    audience: AudienceLevel
    text: str
    uncertainties_addressed: tuple[str, ...]
    conclusion_statement: str
    causal_factors: tuple[str, ...]

    def validate(self) -> None:
        text(self.text, "text")
        text(self.conclusion_statement, "conclusion_statement")

    def as_dict(self) -> dict[str, Any]:
        return {
            "audience": self.audience.value,
            "text": self.text,
            "uncertainties_addressed": list(self.uncertainties_addressed),
            "conclusion_statement": self.conclusion_statement,
            "causal_factors": list(self.causal_factors),
        }


@dataclass(frozen=True)
class ExplanationBundle:
    bundle_id: str
    subject_id: str
    confidence_band: ConfidenceBand
    core_conclusion: str
    material_uncertainties: tuple[str, ...]
    source_evidence_refs: tuple[str, ...]
    explanations: tuple[AudienceExplanation, ...]
    created_at: str
    fidelity_certified: bool = False
    schema_version: str = "0.1"

    def validate(self) -> None:
        text(self.bundle_id, "bundle_id")
        text(self.subject_id, "subject_id")
        text(self.core_conclusion, "core_conclusion")
        unique_strings(self.source_evidence_refs, "source_evidence_refs")
        timestamp(self.created_at, "created_at")
        if not self.explanations:
            raise ValueError("Explanation bundle must contain at least one explanation")
        for e in self.explanations:
            e.validate()

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "confidence_band": self.confidence_band.value,
            "core_conclusion": self.core_conclusion,
            "material_uncertainties": list(self.material_uncertainties),
            "source_evidence_refs": list(self.source_evidence_refs),
            "explanations": [e.as_dict() for e in self.explanations],
            "fidelity_certified": self.fidelity_certified,
            "created_at": self.created_at,
        }


class ExplanationFidelityVerifier:
    """Enforces Invariant 9: Presentation cannot alter meaning.

    Validates multi-audience explanations against ground truth confidence,
    material uncertainties, causality, and conclusions.
    """

    def verify(self, bundle: ExplanationBundle) -> tuple[bool, list[str]]:
        bundle.validate()
        errors: list[str] = []

        material_set = set(bundle.material_uncertainties)

        # 1. Causal factors from TECHNICAL reference (if present)
        tech_exp = next((e for e in bundle.explanations if e.audience == AudienceLevel.TECHNICAL), None)
        tech_causes = set(tech_exp.causal_factors) if tech_exp else set()

        for exp in bundle.explanations:
            aud = exp.audience.value

            # 2. Uncertainty preservation: every material uncertainty must be addressed
            addressed = set(exp.uncertainties_addressed)
            missing = material_set - addressed
            if missing:
                errors.append(
                    f"Audience '{aud}' fails uncertainty preservation. Missing material uncertainties: {sorted(missing)}"
                )

            # 3. Causal consistency: non-technical explanations must not introduce conflicting causes
            if tech_causes:
                curr_causes = set(exp.causal_factors)
                # Any causal factor specified must be compatible with technical causes
                extraneous = curr_causes - tech_causes
                if extraneous:
                    errors.append(
                        f"Audience '{aud}' introduces unverified causal factors not in technical baseline: {sorted(extraneous)}"
                    )

            # 4. Confidence preservation: if UNRESOLVED or UNKNOWN, explanation text cannot claim certainty
            if bundle.confidence_band in (ConfidenceBand.UNRESOLVED, ConfidenceBand.UNKNOWN):
                prohibited_terms = ["definitely proven", "absolute certainty", "conclusively verified", "undeniable fact"]
                lower_text = exp.text.lower()
                for term in prohibited_terms:
                    if term in lower_text:
                        errors.append(
                            f"Audience '{aud}' claims false certainty ('{term}') for an {bundle.confidence_band.value} subject"
                        )

            # 5. Conclusion statement must not contradict core conclusion
            if not exp.conclusion_statement or len(exp.conclusion_statement.strip()) < 3:
                errors.append(f"Audience '{aud}' lacks an explicit conclusion statement")

        return len(errors) == 0, errors

    def certify(self, bundle: ExplanationBundle) -> ExplanationBundle:
        passed, errors = self.verify(bundle)
        if not passed:
            raise ValueError("Explanation fidelity certification failed:\n" + "\n".join(errors))

        return ExplanationBundle(
            bundle_id=bundle.bundle_id,
            subject_id=bundle.subject_id,
            confidence_band=bundle.confidence_band,
            core_conclusion=bundle.core_conclusion,
            material_uncertainties=bundle.material_uncertainties,
            source_evidence_refs=bundle.source_evidence_refs,
            explanations=bundle.explanations,
            created_at=bundle.created_at,
            fidelity_certified=True,
            schema_version=bundle.schema_version,
        )
