from __future__ import annotations

from serialization import StateSerializer
from history import ProjectionSnapshot


class HostShell:
    """Operator presentation surface with no proposal/authority/effect methods."""
    def __init__(self, serializer: StateSerializer | None = None) -> None:
        self.serializer=serializer or StateSerializer()

    def render_state(self, snapshot: ProjectionSnapshot) -> str:
        return self.serializer.canonical_json(snapshot)
