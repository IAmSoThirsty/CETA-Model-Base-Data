"""Model 001 ledger API over the one CETA project journal; no file persistence."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from ..validation import canonical_bytes, strict_loads, text


class LedgerIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class LedgerReceipt:
    sequence: int
    event_id: str
    event_hash: str


class OperationalLedger:
    PREFIX = "model001."

    def __init__(self, journal, project_id, task_id=None):
        self.journal = journal
        self.project_id = text(project_id, "project_id")
        self.task_id = task_id
        if task_id is not None:
            text(task_id, "task_id")

    @contextmanager
    def transaction(self):
        with self.journal.transaction():
            yield self

    def append(self, *, event_type, actor_id, payload, task_id=None,
               session_id=None, occurred_at=None, observed_at=None,
               causal_parent_ids=(), expected_previous_hash=None,
               classification="INTERNAL"):
        text(event_type, "event_type")
        text(actor_id, "actor_id")
        body = strict_loads(canonical_bytes(payload).decode("utf-8"))
        with self.transaction():
            if expected_previous_hash is not None and expected_previous_hash != self.journal.head(self.project_id):
                raise LedgerIntegrityError("Project journal head changed")
            event = self.journal.append(
                self.project_id, self.PREFIX + event_type,
                {"record": body, "metadata": {
                    "committed_at": datetime.now(timezone.utc).isoformat(),
                    "session_id": session_id, "occurred_at": occurred_at,
                    "observed_at": observed_at, "causal_parent_ids": list(causal_parent_ids),
                    "classification": classification,
                }},
                task_id=task_id if task_id is not None else self.task_id,
                actor_id=actor_id,
            )
            return LedgerReceipt(event["sequence"], event["id"], event["event_hash"])

    def records(self):
        records = []
        for event in self.journal.events(self.project_id):
            if not event["kind"].startswith(self.PREFIX):
                continue
            envelope = event["payload"]
            if not isinstance(envelope, dict) or set(envelope) != {"record", "metadata"}:
                raise LedgerIntegrityError("Malformed Model 001 journal envelope")
            records.append({
                **envelope["metadata"], "event_id": event["id"],
                "event_type": event["kind"][len(self.PREFIX):],
                "schema_version": "0.3", "actor_id": event["actor_id"],
                "sequence": event["sequence"], "event_hash": event["event_hash"],
                "previous_event_hash": event["previous_hash"],
                "project_id": self.project_id, "task_id": event.get("task_id"),
                "payload": envelope["record"],
            })
        return tuple(records)

    def head(self):
        events = self.journal.events(self.project_id)
        return (events[-1]["sequence"], events[-1]["event_hash"]) if events else (-1, "0" * 64)

    def verify(self):
        self.records()
        return True
