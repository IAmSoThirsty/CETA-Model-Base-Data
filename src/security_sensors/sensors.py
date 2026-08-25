from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from observation_compiler import CandidateObservation, StructuredObservationCompiler


@dataclass(frozen=True)
class ThreatSignal:
    signal_id: str
    sensor_id: str
    category: str
    severity: int
    indicators: tuple[str, ...]
    subject_ref: str | None = None


class SecuritySensorBridge:
    """Converts detector output into candidate observations only.

    Security sensors can report evidence. They cannot DENY a CETA transition,
    issue authority, invoke tools, or commit state.
    """

    def __init__(self, compiler: StructuredObservationCompiler | None = None) -> None:
        self.compiler=compiler or StructuredObservationCompiler('security_sensor_bridge')

    def compile_signal(self, signal: ThreatSignal) -> CandidateObservation:
        if not signal.signal_id.strip() or not signal.sensor_id.strip() or not signal.category.strip():
            raise ValueError('security signal identity/category must be explicit')
        if not 0 <= signal.severity <= 100:
            raise ValueError('security severity must be in [0,100]')
        payload: Mapping[str,Any]={
            'kind':'security_signal',
            'sensor_id':signal.sensor_id,
            'category':signal.category,
            'severity':signal.severity,
            'indicators':list(signal.indicators),
            'subject_ref':signal.subject_ref,
        }
        return self.compiler.compile(observation_id=signal.signal_id,source_id=signal.sensor_id,payload=payload)
