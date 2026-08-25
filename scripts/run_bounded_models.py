from __future__ import annotations

from collections import deque
from dataclasses import dataclass


PRE = {"ISSUED", "PREPARED"}
POST = {"CONSUMED", "COMPLETED", "FAILED_BEFORE_EFFECT", "PARTIALLY_APPLIED", "INDETERMINATE"}
TERMINAL = {"COMPLETED", "FAILED_BEFORE_EFFECT", "PARTIALLY_APPLIED"}


@dataclass(frozen=True)
class State:
    status: str
    consumed: bool
    consume_count: int


def successors(s: State) -> tuple[tuple[str, State], ...]:
    out: list[tuple[str, State]] = []
    if s.status == "ABSENT":
        out.append(("issue", State("ISSUED", False, 0)))
    elif s.status == "ISSUED":
        out.append(("prepare", State("PREPARED", False, 0)))
        out.append(("revoke", State("REVOKED", False, 0)))
    elif s.status == "PREPARED":
        out.append(("consume", State("CONSUMED", True, s.consume_count + 1)))
        out.append(("revoke", State("REVOKED", False, 0)))
    elif s.status == "CONSUMED":
        for status in ("COMPLETED", "FAILED_BEFORE_EFFECT", "PARTIALLY_APPLIED", "INDETERMINATE"):
            out.append(("finish:" + status, State(status, True, s.consume_count)))
    elif s.status == "INDETERMINATE":
        for status in ("COMPLETED", "FAILED_BEFORE_EFFECT", "PARTIALLY_APPLIED"):
            out.append(("reconcile:" + status, State(status, True, s.consume_count)))
    return tuple(out)


def verify_state(s: State) -> None:
    if s.consumed and s.status in PRE | {"REVOKED"}:
        raise AssertionError(f"consumed authority returned to pre-effect state: {s}")
    if s.status in POST and not s.consumed:
        raise AssertionError(f"post-effect state lacks consumed tombstone: {s}")
    if s.consume_count > 1:
        raise AssertionError(f"nonce consumed more than once: {s}")
    if s.status in TERMINAL and s.consume_count != 1:
        raise AssertionError(f"terminal state lacks one consumption: {s}")


def main() -> None:
    start = State("ABSENT", False, 0)
    queue = deque([(start, ())])
    seen = {start}
    transitions = 0
    max_depth = 0
    while queue:
        state, path = queue.popleft()
        verify_state(state)
        max_depth = max(max_depth, len(path))
        for label, nxt in successors(state):
            transitions += 1
            verify_state(nxt)
            if state.consumed and not nxt.consumed:
                raise AssertionError(f"consumed tombstone lost on {label}: {state} -> {nxt}")
            if state.status != "INDETERMINATE" and label.startswith("reconcile:"):
                raise AssertionError("reconciliation escaped INDETERMINATE precondition")
            if label == "revoke" and state.status not in PRE:
                raise AssertionError("revocation crossed effect boundary")
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, path + (label,)))
    print("BOUNDED AUTHORITY MODEL: PASS")
    print(f"states={len(seen)} transitions={transitions} max_depth={max_depth}")


if __name__ == "__main__":
    main()
