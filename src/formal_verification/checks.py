from __future__ import annotations

from collections import Counter
from typing import Iterable

from authority import PermitStatus
from history import LedgerEntry


class FormalInvariantViolation(AssertionError):
    pass


def verify_transition_chain(entries: Iterable[LedgerEntry]) -> None:
    entries=tuple(entries)
    ids=[e.transition_id for e in entries]
    if len(ids)!=len(set(ids)):
        raise FormalInvariantViolation('transition identity uniqueness violated')
    for index,entry in enumerate(entries,1):
        if entry.sequence != index:
            raise FormalInvariantViolation('transition sequence continuity violated')
        if not entry.proof.get('vm_decision_hash') == entry.vm_decision_hash:
            raise FormalInvariantViolation('VM proof binding violated')
        if entry.verification.get('transition_id') != entry.transition_id:
            raise FormalInvariantViolation('verification transition binding violated')


def verify_consumed_nonce_monotonic(status_history: Iterable[PermitStatus]) -> None:
    history=tuple(status_history)
    if PermitStatus.CONSUMED not in history:
        return
    i=history.index(PermitStatus.CONSUMED)
    forbidden={PermitStatus.ISSUED,PermitStatus.PREPARED,PermitStatus.REVOKED}
    if any(x in forbidden for x in history[i+1:]):
        raise FormalInvariantViolation('authority returned to a pre-consumption state')


def verify_single_owner(responsibility_owner_pairs: Iterable[tuple[str,str]]) -> None:
    counts=Counter(r for r,_ in responsibility_owner_pairs)
    bad=[r for r,n in counts.items() if n!=1]
    if bad:
        raise FormalInvariantViolation(f'canonical responsibility ownership violation: {bad}')
