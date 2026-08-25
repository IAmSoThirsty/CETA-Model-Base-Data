from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from history import domain_hash


class ObservationCompileError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateObservation:
    observation_id: str
    source_id: str
    payload_json: str
    compiler_id: str
    payload_hash: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def as_observe_operands(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "source_id": self.source_id,
            "payload": self.payload,
            "compiler_id": self.compiler_id,
            "payload_hash": self.payload_hash,
        }


class StructuredObservationCompiler:
    """Boundary compiler for already-structured external input.

    It deliberately does not parse unrestricted language. A language or sensor
    adapter may exist above this boundary, but its output must enter as a
    structured mapping and is still only a candidate observation.
    """

    def __init__(self, compiler_id: str = "observation_compiler") -> None:
        if not compiler_id.strip():
            raise ObservationCompileError("compiler_id must be explicit")
        self.compiler_id = compiler_id

    def compile(self, *, observation_id: str, source_id: str, payload: Mapping[str, Any]) -> CandidateObservation:
        if not observation_id.strip() or not source_id.strip():
            raise ObservationCompileError("observation_id and source_id must be explicit")
        if not isinstance(payload, Mapping) or not payload:
            raise ObservationCompileError("candidate observation payload must be a non-empty mapping")
        payload_copy = dict(payload)
        payload_json = json.dumps(payload_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return CandidateObservation(
            observation_id=observation_id,
            source_id=source_id,
            payload_json=payload_json,
            compiler_id=self.compiler_id,
            payload_hash=domain_hash(payload_copy, domain="CETA/OBSERVATION_PAYLOAD/v1"),
        )
