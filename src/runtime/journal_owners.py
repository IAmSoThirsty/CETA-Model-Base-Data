"""CETA canonical owners backed by one transactional project journal."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import json

from authority.ledger import AuthorityLedger, AuthorityEvent, _event_hash, GENESIS_AUTHORITY_HASH
from history.ledger import TransitionLedger, LedgerEntry
from evidence_registry.registry import EvidenceRegistry
from evidence_registry.model import EvidenceRecord
from identity_registry.registry import IdentityRegistry, IdentityRecord

from .journal import JournalError, canonical


def _copy(value):
    return json.loads(canonical(value))


class JournalAuthorityLedger(AuthorityLedger):
    def __init__(self, journal, project_id, task_id=None):
        self.journal, self.project_id, self.task_id = journal, project_id, task_id
        self._owner_depth = 0
        super().__init__()

    @contextmanager
    def _transaction(self):
        with self.journal.transaction():
            outer = self._owner_depth == 0
            self._owner_depth += 1
            try:
                if outer:
                    self._reload()
                yield
            finally:
                self._owner_depth -= 1

    def _reload(self):
        replay = AuthorityLedger()
        previous, sequence = GENESIS_AUTHORITY_HASH, 1
        for row in self.journal.events(self.project_id, kind="ceta.authority"):
            raw = row["payload"]
            event = AuthorityEvent(**raw)
            if event.sequence != sequence or event.previous_hash != previous or _event_hash(event.body()) != event.event_hash:
                raise JournalError("Invalid CETA authority event in project history")
            replay._apply_event(event)
            replay._events.append(event)
            sequence += 1
            previous = event.event_hash
        self._events, self._permits = replay._events, replay._permits
        self._consumed_nonces = replay._consumed_nonces

    def _commit_event(self, event_type, permit_id, payload):
        event = super()._commit_event(event_type, permit_id, payload)
        self.journal.append(self.project_id, "ceta.authority", _copy(event.to_dict()),
                            task_id=self.task_id, actor_id="runtime:authority")
        return event


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.journal.transaction():
            outer = not self._busy
            if outer:
                self._busy = True
            try:
                if outer:
                    self._reload()
                return method(self, *args, **kwargs)
            finally:
                if outer:
                    self._busy = False
    return call


class JournalTransitionLedger(TransitionLedger):
    def __init__(self, journal, project_id, task_id=None, *, known_operations=()):
        self.journal, self.project_id, self.task_id = journal, project_id, task_id
        self._busy = False
        super().__init__(known_operations=known_operations)
        self.verify()

    def _reload(self):
        entries = [LedgerEntry.from_dict(row["payload"])
                   for row in self.journal.events(self.project_id, kind="ceta.transition")]
        self._projector, self._ids = self._replay_and_validate(entries)
        self._entries = entries

    @_locked
    def commit(self, candidate):
        entry = super().commit(candidate)
        self.journal.append(self.project_id, "ceta.transition", _copy(entry.to_dict()),
                            task_id=self.task_id, actor_id=candidate.proposer_id)
        return entry

    @property
    @_locked
    def entries(self):
        return tuple(LedgerEntry.from_dict(_copy(entry.to_dict())) for entry in self._entries)

    @property
    @_locked
    def current_state_ref(self):
        return super().current_state_ref

    @property
    @_locked
    def current_root(self):
        return super().current_root

    @_locked
    def verify(self):
        super().verify()

    @_locked
    def replay_projection(self):
        return super().replay_projection()

    @_locked
    def derived_audit_view(self):
        return super().derived_audit_view()


class JournalEvidenceRegistry(EvidenceRegistry):
    def __init__(self, journal, project_id, task_id=None):
        self.journal, self.project_id, self.task_id = journal, project_id, task_id
        self._busy = False
        super().__init__()

    def _reload(self):
        self._revisions = {}
        self._hashes = set()
        for row in self.journal.events(self.project_id, kind="ceta.evidence"):
            super()._append(EvidenceRecord.from_dict(row["payload"]), write=False)

    def _append(self, record, *, write=True):
        super()._append(record, write=False)
        if write:
            self.journal.append(self.project_id, "ceta.evidence", record.to_dict(),
                                task_id=self.task_id, actor_id="runtime:evidence")


class JournalIdentityRegistry(IdentityRegistry):
    def __init__(self, journal, project_id, task_id=None, *, trusted_verifier=None):
        self.journal, self.project_id, self.task_id = journal, project_id, task_id
        self._busy = False
        super().__init__(trusted_verifier=trusted_verifier)

    def _reload(self):
        self._records = {}
        self._hashes = set()
        for row in self.journal.events(self.project_id, kind="ceta.identity"):
            super()._append(IdentityRecord.from_dict(row["payload"]), write=False)

    def _append(self, record, *, write=True):
        super()._append(record, write=False)
        if write:
            self.journal.append(self.project_id, "ceta.identity", record.to_dict(),
                                task_id=self.task_id, actor_id="runtime:identity")


# All original public registry operations retain their contracts. Their state
# refresh, semantic validation and append now share the journal transaction.
for _name in ("register", "validate", "reject", "latest", "view", "history", "verify"):
    setattr(JournalEvidenceRegistry, _name, _locked(getattr(EvidenceRegistry, _name)))
for _name in ("declare", "verify", "reject", "revoke", "latest", "view", "history", "verify_integrity"):
    setattr(JournalIdentityRegistry, _name, _locked(getattr(IdentityRegistry, _name)))

