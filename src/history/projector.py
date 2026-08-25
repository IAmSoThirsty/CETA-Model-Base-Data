from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import EpistemicObject, HistoryBindingError, StateDelta, Supersession, domain_hash


GENESIS_STATE_REF = domain_hash(
    {"active_objects": [], "supersessions": []},
    domain="CETA/STATE_PROJECTION/v1",
)


@dataclass(frozen=True)
class ProjectionSnapshot:
    state_ref: str
    active_objects: tuple[EpistemicObject, ...]
    supersessions: tuple[Supersession, ...]


class StateProjector:
    """Deterministic, non-authoritative projection over committed deltas."""

    def __init__(self) -> None:
        self._all_objects: dict[str, EpistemicObject] = {}
        self._active_ids: set[str] = set()
        self._supersessions: list[Supersession] = []

    @property
    def state_ref(self) -> str:
        return self.snapshot().state_ref

    def snapshot(self) -> ProjectionSnapshot:
        active = tuple(sorted((self._all_objects[x] for x in self._active_ids), key=lambda x: x.object_id))
        supersessions = tuple(
            sorted(self._supersessions, key=lambda x: (x.old_object_id, x.new_object_id))
        )
        payload = {
            "active_objects": [
                {"object_id": obj.object_id, "object_type": obj.object_type, "object_hash": obj.object_hash}
                for obj in active
            ],
            "supersessions": [edge.to_dict() for edge in supersessions],
        }
        state_ref = domain_hash(payload, domain="CETA/STATE_PROJECTION/v1")
        return ProjectionSnapshot(state_ref, active, supersessions)

    def preview(self, delta: StateDelta) -> "StateProjector":
        clone = StateProjector()
        clone._all_objects = dict(self._all_objects)
        clone._active_ids = set(self._active_ids)
        clone._supersessions = list(self._supersessions)
        clone.apply(delta)
        return clone

    def apply(self, delta: StateDelta) -> None:
        created_ids: set[str] = set()
        for obj in delta.creates:
            if obj.object_id in created_ids:
                raise HistoryBindingError(f"duplicate object ID within transition: {obj.object_id}")
            if obj.object_id in self._all_objects:
                raise HistoryBindingError(f"epistemic object identity is immutable and cannot be reused: {obj.object_id}")
            created_ids.add(obj.object_id)

        for edge in delta.supersedes:
            if edge.old_object_id not in self._active_ids:
                raise HistoryBindingError(
                    f"supersession source is not an active object: {edge.old_object_id}"
                )
            if edge.new_object_id not in created_ids:
                raise HistoryBindingError(
                    f"supersession target must be created by the same transition: {edge.new_object_id}"
                )

        for obj in delta.creates:
            self._all_objects[obj.object_id] = obj
            self._active_ids.add(obj.object_id)
        for edge in delta.supersedes:
            self._active_ids.discard(edge.old_object_id)
            self._supersessions.append(edge)

    @classmethod
    def replay(cls, deltas: Iterable[StateDelta]) -> "StateProjector":
        projector = cls()
        for delta in deltas:
            projector.apply(delta)
        return projector
