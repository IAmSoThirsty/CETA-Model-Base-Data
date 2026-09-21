from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authority.ledger import AuthorityLedger, canonical_hash
from authority.model import Permit
from evidence_registry.registry import EvidenceRegistry
from history.ledger import TransitionLedger
from history.model import CommitCandidate, StateDelta
from identity_registry import IdentityAssertion, IdentityRegistry, TrustedIdentityVerifier
from runtime.journal import Journal, JournalError
from runtime.journal_owners import (JournalAuthorityLedger, JournalEvidenceRegistry,
                                    JournalIdentityRegistry, JournalTransitionLedger)
from runtime.legacy_history import LegacyHistoryError, import_legacy_history


def records_for(kind):
    if kind == "evidence":
        registry = EvidenceRegistry()
        registry.register(record_id="historic-evidence", source_id="synthetic:test", payload={"result": "old result"})
        registry.validate("historic-evidence", validator_id="old-validator", validation_code="OLD_TEST")
        return [row.to_dict() for row in registry.history("historic-evidence")]
    if kind == "identity":
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        registry = IdentityRegistry(trusted_verifier=TrustedIdentityVerifier({"old-verifier": ("old-key", key.public_key())}))
        first = registry.declare(identity_id="historic-user", declaration={"role": "old operator"}, source_ref="synthetic:test")
        assertion = IdentityAssertion.sign(assertion_id="old-assertion", identity_id="historic-user",
            prior_record_hash=first.record_hash, target_status="VERIFIED", verifier_id="old-verifier",
            verifier_key_id="old-key", verification_code="OLD_BINDING", issued_at_epoch_ms=1,
            expires_at_epoch_ms=100, private_key=key)
        registry.verify("historic-user", assertion=assertion, now_epoch_ms=2)
        return [row.to_dict() for row in registry.history("historic-user")]
    if kind == "authority":
        ledger, consequence = AuthorityLedger(), {"old": "consequence"}
        permit = Permit(permit_id="historic-permit", nonce="old-nonce", policy_epoch="old-epoch",
            subject_scope="old-project", operation="OldOperation", consequence_hash=canonical_hash(consequence),
            consumer_id="old-consumer", consumer_key_id="old-key", expires_at_epoch_ms=100,
            source_refs=("synthetic:test",))
        ledger.issue(permit, consequence=consequence, now_ms=1)
        ledger.prepare(permit.permit_id, consumer_id=permit.consumer_id, consumer_key_id=permit.consumer_key_id,
                       consequence=consequence, now_ms=2)
        return [event.to_dict() for event in ledger.events]
    ledger = TransitionLedger()
    for index in range(2):
        tid, state = f"historic-transition-{index}", ledger.current_state_ref
        candidate = CommitCandidate.create(transition_id=tid, input_state_ref=state, operation="OldInspect",
            operands={"synthetic": True}, proposer_id="old-user", constitutional_epoch="old-epoch",
            vm_decision_hash="old-vm-decision", output_state_ref=state, state_delta=StateDelta(),
            proof={"vm_decision_hash": "old-vm-decision"}, verification={"transition_id": tid},
            replay_record={"transition_id": tid, "operation": "OldInspect", "input_state_ref": state,
                           "output_state_ref": state})
        ledger.commit(candidate)
    return [row.to_dict() for row in ledger.entries]


class LegacyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.journal = Journal(self.root / "journal.sqlite3")
        self.addCleanup(lambda: self.journal.close())
        self.journal.register_project("selected-project", self.root)
        self.journal.append("selected-project", "task.created", {"objective": "Import selected old history"}, task_id="task")
        self.provenance = {"source_application": "CETA", "project_id": "selected-project",
                           "scope_statement": "User-selected synthetic legacy history for this project"}

    def write(self, kind="evidence", records=None, raw=None):
        path = self.root / (kind + ".jsonl")
        if raw is None:
            records = records_for(kind) if records is None else records
            raw = b"\xef\xbb\xbf" + b"".join((json.dumps(row, ensure_ascii=False) + "\r\n").encode() for row in records)
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest(), raw

    def run_import(self, path, sha, kind="evidence", **kwargs):
        options = {"expected_sha256": sha, "kind": kind, "provenance": self.provenance,
                   "task_id": "task", "actor_id": "user"}
        options.update(kwargs)
        return import_legacy_history(self.journal, "selected-project", path, **options)

    def imported(self):
        return self.journal.events("selected-project", kind="legacy.history.imported")

    def test_all_four_formats_preserve_original_bytes_order_ids_hashes_and_signatures(self):
        for kind in ("transition", "authority", "evidence", "identity"):
            with self.subTest(kind=kind):
                records = records_for(kind)
                path, sha, raw = self.write(kind, records)
                result = self.run_import(path, sha, kind)
                payload = self.imported()[-1]["payload"]
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(base64.b64decode(payload["artifact"], validate=True), raw)
                self.assertEqual(payload["source_sha256"], sha)
                self.assertEqual([line["record"] for line in payload["records"]], records)
                self.assertEqual([line["line_number"] for line in payload["records"]], [1, 2])
                for line in payload["records"]:
                    original = raw[line["byte_offset"]:line["byte_offset"] + line["byte_length"]]
                    self.assertEqual(hashlib.sha256(original).hexdigest(), line["line_sha256"])
                self.assertFalse(payload["current_authority"])
                self.assertFalse(payload["fresh_validation_of_historical_results"])
                self.assertEqual(payload["signature_authentication"], "not_performed_no_trusted_source_keys")
                self.assertEqual(result["disposition"], "historical_only")
                self.assertFalse(result["already_imported"])
        self.assertEqual(JournalAuthorityLedger(self.journal, "selected-project").events, ())
        self.assertEqual(JournalEvidenceRegistry(self.journal, "selected-project").view(), {})
        self.assertEqual(JournalIdentityRegistry(self.journal, "selected-project").view(), {})
        self.assertEqual(JournalTransitionLedger(self.journal, "selected-project").entries, ())
        self.journal.verify()

    def test_identical_artifact_is_idempotent_across_restart_and_selected_alias(self):
        path, sha, raw = self.write()
        first = self.run_import(path, sha)
        original_events = self.journal.events("selected-project")
        self.journal.close()
        self.journal = Journal(self.root / "journal.sqlite3")
        alias = self.root / "selected-again.jsonl"
        alias.write_bytes(raw)
        second = self.run_import(alias, sha)
        self.assertEqual(second["event_id"], first["event_id"])
        self.assertTrue(second["already_imported"])
        self.assertEqual(self.journal.events("selected-project"), original_events)
        self.assertEqual(self.imported()[0]["payload"]["source_path"], str(path.resolve()))

    def test_simultaneous_imports_commit_one_artifact(self):
        path, sha, _ = self.write()
        def perform(_):
            journal = Journal(self.root / "journal.sqlite3")
            try:
                return import_legacy_history(journal, "selected-project", path, expected_sha256=sha,
                    kind="evidence", provenance=self.provenance, task_id="task")
            finally:
                journal.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(perform, range(2)))
        self.assertEqual(len(self.imported()), 1)
        self.assertEqual(sorted(result["already_imported"] for result in results), [False, True])
        self.assertEqual(results[0]["event_id"], results[1]["event_id"])

    def test_wrong_hash_and_changed_file_are_rejected_without_history_append(self):
        path, sha, _ = self.write()
        head = self.journal.head("selected-project")
        with self.assertRaisesRegex(LegacyHistoryError, "SHA-256 differs"):
            self.run_import(path, "0" * 64)
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(LegacyHistoryError, "SHA-256 differs"):
            self.run_import(path, sha)
        self.assertEqual(self.journal.head("selected-project"), head)
        self.assertEqual(self.imported(), [])

    def test_project_provenance_task_and_actor_are_explicit(self):
        path, sha, _ = self.write()
        for options in ({"provenance": {}}, {"provenance": {**self.provenance, "project_id": "other"}},
                        {"provenance": {**self.provenance, "source_application": "Model 001"}},
                        {"provenance": {**self.provenance, "scope_statement": " "}}, {"actor_id": ""},
                        {"task_id": "missing"}, {"expected_sha256": sha.upper()}, {"kind": "permit"}):
            with self.subTest(options=options), self.assertRaises(JournalError):
                self.run_import(path, sha, **options)
        other = self.root / "other"
        other.mkdir()
        self.journal.register_project("other", other)
        self.journal.append("other", "task.created", {"objective": "different project"}, task_id="other-task")
        with self.assertRaisesRegex(LegacyHistoryError, "destination project"):
            self.run_import(path, sha, task_id="other-task")
        self.assertEqual(self.imported(), [])

    def test_previous_binding_cannot_be_silently_redeclared(self):
        path, sha, _ = self.write()
        self.run_import(path, sha)
        original = self.imported()
        with self.assertRaisesRegex(LegacyHistoryError, "different recorded"):
            self.run_import(path, sha, provenance={**self.provenance, "scope_statement": "different declaration"})
        self.assertEqual(self.imported(), original)

    def test_invalid_json_types_duplicates_nonfinite_truncation_and_blanks_fail_closed(self):
        invalid = (b"{}", b"\n", b"[]\n", b'{"a":1,"a":2}\n', b'{"a":NaN}\n',
                   b'{"a":1e999}\n', b'{"a":"\xff"}\n', b'{"record_id":"unknown"}\n')
        for raw in invalid:
            with self.subTest(raw=raw):
                path, sha, _ = self.write(raw=raw)
                with self.assertRaises(LegacyHistoryError):
                    self.run_import(path, sha)
        self.assertEqual(self.imported(), [])

    def test_every_format_rejects_hash_tampering_and_reordered_records(self):
        for kind in ("transition", "authority", "evidence", "identity"):
            original = records_for(kind)
            corrupt = json.loads(json.dumps(original))
            hash_field = "entry_hash" if kind == "transition" else "event_hash" if kind == "authority" else "record_hash"
            corrupt[0][hash_field] = "0" * 64
            for records in (corrupt, list(reversed(original))):
                with self.subTest(kind=kind, records=records):
                    path, sha, _ = self.write(kind, records)
                    with self.assertRaises(LegacyHistoryError):
                        self.run_import(path, sha, kind)
        self.assertEqual(self.imported(), [])

    def test_wrong_kind_and_size_limit_are_rejected(self):
        path, sha, _ = self.write()
        with self.assertRaises(LegacyHistoryError):
            self.run_import(path, sha, "authority")
        with patch("runtime.legacy_history.MAX_BYTES", 100):
            with self.assertRaisesRegex(LegacyHistoryError, "import limit"):
                self.run_import(path, sha)
        self.assertEqual(self.imported(), [])

    def test_journal_append_failure_preserves_source_and_does_not_create_partial_import(self):
        path, sha, raw = self.write()
        before = self.journal.events("selected-project")
        self.journal.db.execute("""CREATE TRIGGER reject_legacy BEFORE INSERT ON task_events
            WHEN NEW.kind='legacy.history.imported' BEGIN SELECT RAISE(ABORT,'injected import failure'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected import failure"):
            self.run_import(path, sha)
        self.assertEqual(self.journal.events("selected-project"), before)
        self.assertEqual(path.read_bytes(), raw)
        self.journal.db.execute("DROP TRIGGER reject_legacy")
        self.assertFalse(self.run_import(path, sha)["already_imported"])
        self.journal.verify()


if __name__ == "__main__":
    unittest.main()
