from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from history import (  # noqa: E402
    CommitCandidate,
    EpistemicObject,
    HistoryBindingError,
    StateDelta,
    StateProjector,
    Supersession,
    TransitionLedger,
)

OPS = {"Observe", "CreateClaim", "Invalidate", "Split", "Merge"}


def candidate(
    ledger: TransitionLedger,
    *,
    transition_id: str,
    operation: str,
    delta: StateDelta,
    proposer_id: str = "transition-policy-model",
) -> CommitCandidate:
    output = ledger.replay_projection().preview(delta).state_ref
    vm_hash = f"vm:{transition_id}"
    return CommitCandidate.create(
        transition_id=transition_id,
        input_state_ref=ledger.current_state_ref,
        operation=operation,
        operands={"fixture": transition_id},
        proposer_id=proposer_id,
        constitutional_epoch="epoch-1",
        vm_decision_hash=vm_hash,
        output_state_ref=output,
        state_delta=delta,
        proof={"vm_decision_hash": vm_hash, "fixture": True},
        verification={"transition_id": transition_id, "fixture": True},
        replay_record={
            "transition_id": transition_id,
            "operation": operation,
            "input_state_ref": ledger.current_state_ref,
            "output_state_ref": output,
        },
    )


class TransitionHistoryTests(unittest.TestCase):
    def test_commit_and_replay_reconstruct_same_state(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        obj = EpistemicObject.create(object_id="O-1", object_type="OBSERVATION", content={"v": 1})
        ledger.commit(candidate(ledger, transition_id="T-1", operation="Observe", delta=StateDelta((obj,), ())))
        self.assertEqual(ledger.current_state_ref, ledger.replay_projection().state_ref)
        ledger.verify()

    def test_identity_reuse_is_rejected_even_with_same_content(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        obj = EpistemicObject.create(object_id="C-1", object_type="CLAIM", content={"x": 1})
        ledger.commit(candidate(ledger, transition_id="T-1", operation="CreateClaim", delta=StateDelta((obj,), ())))
        duplicate = EpistemicObject.create(object_id="C-1", object_type="CLAIM", content={"x": 1})
        with self.assertRaises(HistoryBindingError):
            candidate(ledger, transition_id="T-2", operation="CreateClaim", delta=StateDelta((duplicate,), ()))

    def test_supersession_requires_active_old_and_new_created_same_transition(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        old = EpistemicObject.create(object_id="B-1", object_type="BELIEF", content={"version": 1})
        ledger.commit(candidate(ledger, transition_id="T-1", operation="CreateClaim", delta=StateDelta((old,), ())))
        new = EpistemicObject.create(object_id="B-2", object_type="BELIEF", content={"version": 2})
        ledger.commit(
            candidate(
                ledger,
                transition_id="T-2",
                operation="Invalidate",
                delta=StateDelta((new,), (Supersession("B-1", "B-2"),)),
            )
        )
        illegal = EpistemicObject.create(object_id="B-3", object_type="BELIEF", content={"version": 3})
        with self.assertRaises(HistoryBindingError):
            candidate(
                ledger,
                transition_id="T-3",
                operation="Invalidate",
                delta=StateDelta((illegal,), (Supersession("B-1", "B-3"),)),
            )

    def test_output_state_mismatch_is_rejected(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        obj = EpistemicObject.create(object_id="O-1", object_type="OBSERVATION", content={"v": 1})
        c = candidate(ledger, transition_id="T-1", operation="Observe", delta=StateDelta((obj,), ()))
        bad = CommitCandidate.create(
            transition_id=c.transition_id,
            input_state_ref=c.input_state_ref,
            operation=c.operation,
            operands=c.operands,
            proposer_id=c.proposer_id,
            constitutional_epoch=c.constitutional_epoch,
            vm_decision_hash=c.vm_decision_hash,
            output_state_ref="sha256:wrong",
            state_delta=c.state_delta,
            proof=c.proof,
            verification=c.verification,
            replay_record={**c.replay_record, "output_state_ref": "sha256:wrong"},
        )
        with self.assertRaises(HistoryBindingError):
            ledger.commit(bad)

    def test_replay_record_must_bind_transition(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        obj = EpistemicObject.create(object_id="O-1", object_type="OBSERVATION", content={"v": 1})
        c = candidate(ledger, transition_id="T-1", operation="Observe", delta=StateDelta((obj,), ()))
        bad = CommitCandidate.create(
            transition_id=c.transition_id,
            input_state_ref=c.input_state_ref,
            operation=c.operation,
            operands=c.operands,
            proposer_id=c.proposer_id,
            constitutional_epoch=c.constitutional_epoch,
            vm_decision_hash=c.vm_decision_hash,
            output_state_ref=c.output_state_ref,
            state_delta=c.state_delta,
            proof=c.proof,
            verification=c.verification,
            replay_record={**c.replay_record, "operation": "CreateClaim"},
        )
        with self.assertRaises(HistoryBindingError):
            ledger.commit(bad)

    def test_proof_must_bind_vm_decision(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        obj = EpistemicObject.create(object_id="O-1", object_type="OBSERVATION", content={"v": 1})
        c = candidate(ledger, transition_id="T-1", operation="Observe", delta=StateDelta((obj,), ()))
        bad = CommitCandidate.create(
            transition_id=c.transition_id,
            input_state_ref=c.input_state_ref,
            operation=c.operation,
            operands=c.operands,
            proposer_id=c.proposer_id,
            constitutional_epoch=c.constitutional_epoch,
            vm_decision_hash=c.vm_decision_hash,
            output_state_ref=c.output_state_ref,
            state_delta=c.state_delta,
            proof={"vm_decision_hash": "vm:other"},
            verification=c.verification,
            replay_record=c.replay_record,
        )
        with self.assertRaises(HistoryBindingError):
            ledger.commit(bad)

    def test_file_reload_verifies_and_reconstructs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "transitions.jsonl"
            ledger = TransitionLedger(path, known_operations=OPS)
            obj = EpistemicObject.create(object_id="O-1", object_type="OBSERVATION", content={"v": 1})
            ledger.commit(candidate(ledger, transition_id="T-1", operation="Observe", delta=StateDelta((obj,), ())))
            reloaded = TransitionLedger(path, known_operations=OPS)
            self.assertEqual(ledger.current_root, reloaded.current_root)
            self.assertEqual(ledger.current_state_ref, reloaded.current_state_ref)
            reloaded.verify()

    def test_file_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "transitions.jsonl"
            ledger = TransitionLedger(path, known_operations=OPS)
            obj = EpistemicObject.create(object_id="O-1", object_type="OBSERVATION", content={"v": 1})
            ledger.commit(candidate(ledger, transition_id="T-1", operation="Observe", delta=StateDelta((obj,), ())))
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["operation"] = "CreateClaim"
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            with self.assertRaises(HistoryBindingError):
                TransitionLedger(path, known_operations=OPS)

    def test_audit_view_is_derived_from_entries(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        obj = EpistemicObject.create(object_id="O-1", object_type="OBSERVATION", content={"v": 1})
        entry = ledger.commit(candidate(ledger, transition_id="T-1", operation="Observe", delta=StateDelta((obj,), ())))
        view = ledger.derived_audit_view()
        self.assertEqual(len(view), 1)
        self.assertEqual(view[0]["entry_hash"], entry.entry_hash)
        self.assertEqual(view[0]["output_state_ref"], ledger.current_state_ref)

    def test_split_and_merge_topology_is_supported_without_mutating_objects(self) -> None:
        ledger = TransitionLedger(known_operations=OPS)
        root = EpistemicObject.create(object_id="B-1", object_type="BELIEF", content={"scope": "root"})
        ledger.commit(candidate(ledger, transition_id="T-1", operation="CreateClaim", delta=StateDelta((root,), ())))
        left = EpistemicObject.create(object_id="B-2", object_type="BELIEF", content={"scope": "left"})
        right = EpistemicObject.create(object_id="B-3", object_type="BELIEF", content={"scope": "right"})
        ledger.commit(
            candidate(
                ledger,
                transition_id="T-2",
                operation="Split",
                delta=StateDelta((left, right), (Supersession("B-1", "B-2"), Supersession("B-1", "B-3"))),
            )
        )
        merged = EpistemicObject.create(object_id="B-4", object_type="BELIEF", content={"scope": "merged"})
        ledger.commit(
            candidate(
                ledger,
                transition_id="T-3",
                operation="Merge",
                delta=StateDelta((merged,), (Supersession("B-2", "B-4"), Supersession("B-3", "B-4"))),
            )
        )
        active = {x.object_id for x in ledger.replay_projection().snapshot().active_objects}
        self.assertEqual(active, {"B-4"})


if __name__ == "__main__":
    unittest.main()
