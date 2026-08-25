from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum

class PermitStatus(StrEnum):
    ISSUED='ISSUED'
    PREPARED='PREPARED'
    CONSUMED='CONSUMED'
    COMPLETED='COMPLETED'
    FAILED_BEFORE_EFFECT='FAILED_BEFORE_EFFECT'
    PARTIALLY_APPLIED='PARTIALLY_APPLIED'
    INDETERMINATE='INDETERMINATE'
    REVOKED='REVOKED'

TERMINAL_AFTER_EFFECT=frozenset({
    PermitStatus.COMPLETED, PermitStatus.FAILED_BEFORE_EFFECT,
    PermitStatus.PARTIALLY_APPLIED, PermitStatus.INDETERMINATE
})
RECONCILABLE=frozenset({PermitStatus.COMPLETED, PermitStatus.FAILED_BEFORE_EFFECT, PermitStatus.PARTIALLY_APPLIED})

@dataclass(frozen=True)
class Permit:
    permit_id: str
    nonce: str
    policy_epoch: str
    subject_scope: str
    operation: str
    consequence_hash: str
    consumer_id: str
    consumer_key_id: str
    expires_at_epoch_ms: int
    source_refs: tuple[str,...]
    use_limit: int=1
