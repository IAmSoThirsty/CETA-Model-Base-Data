from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from ..validation import text


class RoleClass(str, Enum):
    ANALYST_SYNTHESIZER = "ANALYST_SYNTHESIZER"
    HUMAN_IMPACT_CONTEXT = "HUMAN_IMPACT_CONTEXT"
    WORLD_STATE_OBSERVER = "WORLD_STATE_OBSERVER"
    STRUCTURE_COHERENCE = "STRUCTURE_COHERENCE"
    ADVERSARIAL_REVIEW = "ADVERSARIAL_REVIEW"
    INTEGRATOR_CONTINUITY = "INTEGRATOR_CONTINUITY"
    VERIFICATION_REPRODUCTION = "VERIFICATION_REPRODUCTION"
    HUMAN_SCOPE_AUTHORITY = "HUMAN_SCOPE_AUTHORITY"


@dataclass(frozen=True)
class RoleBinding:
    participant_id: str
    role_classes: tuple[RoleClass, ...]
    truth_write_authority: bool = False

    def validate(self) -> None:
        text(self.participant_id, 'participant_id')
        if self.truth_write_authority is not False:
            raise ValueError("Forge roles cannot receive truth-write authority")
        if (not isinstance(self.role_classes, tuple) or not self.role_classes or
            any(not isinstance(role, RoleClass) for role in self.role_classes) or
            len(set(self.role_classes)) != len(self.role_classes)):
            raise ValueError('Invalid or duplicate role classes')
