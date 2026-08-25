from __future__ import annotations

import json
from typing import Any, Mapping

from history import ProjectionSnapshot


class SerializationError(ValueError):
    pass


class StateSerializer:
    """Pure output serialization over already-registered state.

    The serializer has no state mutation, authority, evidence admission or
    transition proposal methods. Its canonical format is JSON so language is
    visibly downstream of epistemic state.
    """

    def canonical_json(self, snapshot: ProjectionSnapshot) -> str:
        payload = {
            "state_ref": snapshot.state_ref,
            "active_objects": [obj.to_dict() for obj in snapshot.active_objects],
            "supersessions": [edge.to_dict() for edge in snapshot.supersessions],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def selected_view(self, snapshot: ProjectionSnapshot, object_refs: list[str]) -> str:
        by_id = {obj.object_id: obj for obj in snapshot.active_objects}
        missing = [ref for ref in object_refs if ref not in by_id]
        if missing:
            raise SerializationError(f"cannot serialize unknown active objects: {missing}")
        payload = {
            "state_ref": snapshot.state_ref,
            "objects": [by_id[ref].to_dict() for ref in object_refs],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def transition_record(self, record: Mapping[str, Any]) -> str:
        return json.dumps(dict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
