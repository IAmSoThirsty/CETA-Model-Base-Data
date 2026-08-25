from __future__ import annotations

from typing import Protocol, Sequence

from ceta import TransitionProposal
from history import ProjectionSnapshot
from .encoder import WorldView


class TransitionPolicy(Protocol):
    """Neural-policy boundary: state in, transition proposal out."""
    model_id: str
    def propose(self, world: WorldView) -> TransitionProposal: ...


class FixedTransitionPolicy:
    """Non-neural conformance fixture implementing the same proposal surface."""
    def __init__(self, model_id: str, proposals: Sequence[tuple[str,dict]]) -> None:
        if not model_id.strip() or not proposals:
            raise ValueError('model_id and proposal sequence are required')
        self.model_id=model_id
        self._proposals=list(proposals)
        self._index=0

    def propose(self, snapshot: ProjectionSnapshot) -> TransitionProposal:
        if self._index >= len(self._proposals):
            raise StopIteration
        operation,operands=self._proposals[self._index]
        self._index += 1
        return TransitionProposal(snapshot.state_ref,operation,dict(operands),self.model_id)
