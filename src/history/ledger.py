from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model import CommitCandidate, HistoryBindingError, StateDelta, canonical_json, domain_hash
from .projector import StateProjector


GENESIS_TRANSITION_ROOT = domain_hash(
    {"genesis": "CETA_TRANSITION_LEDGER"},
    domain="CETA/TRANSITION_LEDGER_ROOT/v1",
)


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    transition_id: str
    input_state_ref: str
    operation: str
    operands: Mapping[str, Any]
    proposer_id: str
    constitutional_epoch: str
    vm_decision_hash: str
    output_state_ref: str
    state_delta: StateDelta
    proof: Mapping[str, Any]
    verification: Mapping[str, Any]
    replay_record: Mapping[str, Any]
    previous_entry_hash: str
    entry_hash: str

    def body_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "transition_id": self.transition_id,
            "input_state_ref": self.input_state_ref,
            "operation": self.operation,
            "operands": dict(self.operands),
            "proposer_id": self.proposer_id,
            "constitutional_epoch": self.constitutional_epoch,
            "vm_decision_hash": self.vm_decision_hash,
            "output_state_ref": self.output_state_ref,
            "state_delta": self.state_delta.to_dict(),
            "proof": dict(self.proof),
            "verification": dict(self.verification),
            "replay_record": dict(self.replay_record),
            "previous_entry_hash": self.previous_entry_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        value = self.body_dict()
        value["entry_hash"] = self.entry_hash
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LedgerEntry":
        required = {
            "sequence", "transition_id", "input_state_ref", "operation", "operands", "proposer_id",
            "constitutional_epoch", "vm_decision_hash", "output_state_ref", "state_delta", "proof",
            "verification", "replay_record", "previous_entry_hash", "entry_hash",
        }
        if set(data) != required:
            raise HistoryBindingError("ledger entry field set mismatch")
        return cls(
            sequence=int(data["sequence"]),
            transition_id=str(data["transition_id"]),
            input_state_ref=str(data["input_state_ref"]),
            operation=str(data["operation"]),
            operands=dict(data["operands"]),
            proposer_id=str(data["proposer_id"]),
            constitutional_epoch=str(data["constitutional_epoch"]),
            vm_decision_hash=str(data["vm_decision_hash"]),
            output_state_ref=str(data["output_state_ref"]),
            state_delta=StateDelta.from_dict(data["state_delta"]),
            proof=dict(data["proof"]),
            verification=dict(data["verification"]),
            replay_record=dict(data["replay_record"]),
            previous_entry_hash=str(data["previous_entry_hash"]),
            entry_hash=str(data["entry_hash"]),
        )


class TransitionLedger:
    """Single-process reference implementation of canonical CETA history.

    The ledger owns append-only committed history. It never decides transition
    legality, issues authority, executes effects, or performs semantic effect
    verification. State and audit surfaces are recomputed from ledger entries.
    """

    def __init__(self, path: str | Path | None = None, *, known_operations: Iterable[str] = ()) -> None:
        self.path = Path(path) if path is not None else None
        self._known_operations = frozenset(known_operations)
        self._entries: list[LedgerEntry] = []
        self._ids: set[str] = set()
        self._projector = StateProjector()
        if self.path is not None and self.path.exists():
            self._load_and_verify()

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    @property
    def current_state_ref(self) -> str:
        return self._projector.state_ref

    @property
    def current_root(self) -> str:
        return self._entries[-1].entry_hash if self._entries else GENESIS_TRANSITION_ROOT

    def commit(self, candidate: CommitCandidate) -> LedgerEntry:
        if candidate.transition_id in self._ids:
            raise HistoryBindingError(f"duplicate transition ID: {candidate.transition_id}")
        if self._known_operations and candidate.operation not in self._known_operations:
            raise HistoryBindingError(f"unknown CETA operation at ledger boundary: {candidate.operation}")
        if candidate.input_state_ref != self.current_state_ref:
            raise HistoryBindingError("candidate input state does not match current projected state")

        self._validate_runtime_bindings(candidate)
        preview = self._projector.preview(candidate.state_delta)
        if candidate.output_state_ref != preview.state_ref:
            raise HistoryBindingError("candidate output state does not match deterministic projection")

        sequence = len(self._entries) + 1
        previous_hash = self.current_root
        entry = LedgerEntry(
            sequence=sequence,
            transition_id=candidate.transition_id,
            input_state_ref=candidate.input_state_ref,
            operation=candidate.operation,
            operands=candidate.operands,
            proposer_id=candidate.proposer_id,
            constitutional_epoch=candidate.constitutional_epoch,
            vm_decision_hash=candidate.vm_decision_hash,
            output_state_ref=candidate.output_state_ref,
            state_delta=candidate.state_delta,
            proof=candidate.proof,
            verification=candidate.verification,
            replay_record=candidate.replay_record,
            previous_entry_hash=previous_hash,
            entry_hash="",
        )
        entry_hash = domain_hash(entry.body_dict(), domain="CETA/COMMITTED_TRANSITION/v1")
        entry = LedgerEntry(**{**entry.__dict__, "entry_hash": entry_hash})

        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(entry.to_dict()) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

        self._entries.append(entry)
        self._ids.add(entry.transition_id)
        self._projector = preview
        return entry

    def verify(self) -> None:
        self._replay_and_validate(self._entries)

    def derived_audit_view(self) -> tuple[dict[str, Any], ...]:
        """Audit is a read model over canonical history, not a second ledger."""
        return tuple(
            {
                "sequence": entry.sequence,
                "transition_id": entry.transition_id,
                "operation": entry.operation,
                "proposer_id": entry.proposer_id,
                "input_state_ref": entry.input_state_ref,
                "output_state_ref": entry.output_state_ref,
                "vm_decision_hash": entry.vm_decision_hash,
                "verification_hash": domain_hash(entry.verification, domain="CETA/VERIFICATION_VIEW/v1"),
                "entry_hash": entry.entry_hash,
            }
            for entry in self._entries
        )

    def replay_projection(self) -> StateProjector:
        return StateProjector.replay(entry.state_delta for entry in self._entries)

    def _load_and_verify(self) -> None:
        entries: list[LedgerEntry] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    entries.append(LedgerEntry.from_dict(raw))
                except Exception as exc:
                    raise HistoryBindingError(f"invalid ledger line {lineno}: {exc}") from exc
        projector, ids = self._replay_and_validate(entries)
        self._entries = entries
        self._ids = ids
        self._projector = projector

    def _replay_and_validate(self, entries: Iterable[LedgerEntry]) -> tuple[StateProjector, set[str]]:
        projector = StateProjector()
        ids: set[str] = set()
        previous_hash = GENESIS_TRANSITION_ROOT
        expected_sequence = 1
        for entry in entries:
            self._validate_replay_entry(entry, expected_sequence, ids, previous_hash, projector.state_ref)
            self._validate_entry_runtime_bindings(entry)
            projector.apply(entry.state_delta)
            if entry.output_state_ref != projector.state_ref:
                raise HistoryBindingError(f"output-state replay mismatch at sequence {entry.sequence}")
            ids.add(entry.transition_id)
            previous_hash = entry.entry_hash
            expected_sequence += 1
        return projector, ids

    def _validate_replay_entry(
        self, entry: LedgerEntry, expected_sequence: int, ids: set[str], previous_hash: str, state_ref: str
    ) -> None:
        if entry.sequence != expected_sequence:
            raise HistoryBindingError(f"ledger sequence mismatch at {entry.sequence}")
        if entry.transition_id in ids:
            raise HistoryBindingError(f"duplicate transition ID in history: {entry.transition_id}")
        if self._known_operations and entry.operation not in self._known_operations:
            raise HistoryBindingError(f"unknown CETA operation in history: {entry.operation}")
        if entry.previous_entry_hash != previous_hash:
            raise HistoryBindingError(f"previous-entry hash mismatch at sequence {entry.sequence}")
        expected_hash = domain_hash(entry.body_dict(), domain="CETA/COMMITTED_TRANSITION/v1")
        if entry.entry_hash != expected_hash:
            raise HistoryBindingError(f"entry hash mismatch at sequence {entry.sequence}")
        if entry.input_state_ref != state_ref:
            raise HistoryBindingError(f"input-state replay mismatch at sequence {entry.sequence}")

    @staticmethod
    def _validate_runtime_bindings(candidate: CommitCandidate) -> None:
        replay = candidate.replay_record
        required = {
            "transition_id": candidate.transition_id,
            "operation": candidate.operation,
            "input_state_ref": candidate.input_state_ref,
            "output_state_ref": candidate.output_state_ref,
        }
        for key, expected in required.items():
            if replay.get(key) != expected:
                raise HistoryBindingError(f"replay record is not bound to {key}")
        if candidate.proof.get("vm_decision_hash") != candidate.vm_decision_hash:
            raise HistoryBindingError("proof is not bound to VM decision hash")
        if candidate.verification.get("transition_id") != candidate.transition_id:
            raise HistoryBindingError("verification is not bound to transition ID")

    @staticmethod
    def _validate_entry_runtime_bindings(entry: LedgerEntry) -> None:
        required = {
            "transition_id": entry.transition_id,
            "operation": entry.operation,
            "input_state_ref": entry.input_state_ref,
            "output_state_ref": entry.output_state_ref,
        }
        for key, expected in required.items():
            if entry.replay_record.get(key) != expected:
                raise HistoryBindingError(f"replay record is not bound to {key} at sequence {entry.sequence}")
        if entry.proof.get("vm_decision_hash") != entry.vm_decision_hash:
            raise HistoryBindingError(f"proof/VM binding mismatch at sequence {entry.sequence}")
        if entry.verification.get("transition_id") != entry.transition_id:
            raise HistoryBindingError(f"verification/transition binding mismatch at sequence {entry.sequence}")
