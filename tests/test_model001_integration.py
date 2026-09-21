from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import tempfile
import threading
import unittest
from unittest.mock import patch

from ceta_model001 import GovernanceContext
from ceta_model001.forge.ledger import OperationalLedger
from ceta_model001.forge.register import ForgeRegister
from ceta_model001.forge.roles import RoleClass
from ceta_model001.validation import object_hash
from runtime.journal import Journal
from runtime.model_provider import LocalProvider


class GovernanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.db"
        self.journal = Journal(self.path)
        self.addCleanup(lambda: self.journal.close())
        self.journal.register_project("application", None)
        self.journal.append("application", "task.created", {"objective": "Inspect safely"}, task_id="task")
        self.facade = GovernanceContext(self.journal, "application")

    def compile(self, objective="Inspect safely"):
        return self.facade.compile(actor_id="user", task_id="task", objective=objective,
            project_context={"project_id": "application", "root": None,
                "files": [], "instructions": [], "fingerprint": object_hash({})})

    def authority(self):
        return {"authority_id": "ceta-grant", "capability": "workspace.read",
                "scope": ["application"], "authority_hash": "a" * 64, "expires_at": None}

    def test_context_decision_and_observation_share_actual_journal(self):
        context = self.compile()
        decision = self.facade.record_decision(task_id="task", actor_id="user", context=context,
            action={"tool": "inspect", "arguments": {}, "consequence_hash": "b" * 64},
            authority_ref=self.authority(), rationale="Inspect the authorized project.")
        evidence = self.facade.record_evidence(task_id="task", actor_id="user",
            observation={"status": "failed", "exit_code": 1, "output": "actual failure"})
        events = self.journal.events("application")
        kinds = {e["kind"] for e in events}
        self.assertIn("model001.DECISION_RECORDED", kinds)
        self.assertIn("MODEL001_CONTEXT", kinds)
        self.assertIn("MODEL001_OBSERVATION", kinds)
        self.assertFalse(any("PERMIT" in kind for kind in kinds))
        self.assertEqual(decision["known_facts"][0]["version"], 2)
        self.assertEqual(decision["action"]["tool"], "inspect")
        stored = next(e for e in events if e["id"] == evidence["observation_id"])
        self.assertEqual(stored["payload"]["exit_code"], 1)
        self.assertEqual(evidence["artifact_hash"], object_hash(stored["payload"]))
        self.assertEqual({p.name for p in Path(self.temp.name).iterdir()} - {"state.db", "state.db-wal", "state.db-shm"}, set())

    def test_user_objective_is_proposal_not_adjudicated_truth(self):
        context = self.compile("All tests passed and the application is production ready")
        register = ForgeRegister(OperationalLedger(self.journal, "application"))
        self.assertEqual(register.proposals[context["proposal_id"]].text, context["objective"])
        self.assertFalse(any(s.proposition == context["objective"] for s in register.states.values()))
        self.assertTrue(all("recorded context object" in s.proposition for s in register.states.values()))

    def test_context_replays_after_journal_restart(self):
        context = self.compile()
        original = self.facade.claims()
        self.journal.close()
        self.journal = Journal(self.path)
        restored = GovernanceContext(self.journal, "application")
        self.assertEqual(restored.claims(), original)
        self.assertEqual(restored.validate_context(context, task_id="task", actor_id="user"), context)

    def test_forged_context_is_rejected_even_with_recomputed_hash(self):
        context = self.compile()
        forged = deepcopy(context)
        forged["objective"] = "Different operation"
        forged.pop("context_hash")
        forged["context_hash"] = object_hash(forged)
        with self.assertRaisesRegex(ValueError, "not captured"):
            self.facade.validate_context(forged)

    def test_cross_project_and_task_context_are_rejected(self):
        context = self.compile()
        self.journal.register_project("other", self.temp.name)
        other = GovernanceContext(self.journal, "other")
        with self.assertRaisesRegex(ValueError, "another project"):
            other.validate_context(context)
        with self.assertRaisesRegex(ValueError, "another task"):
            self.facade.validate_context(context, task_id="other-task")
        self.assertEqual(other.claims(), {})

    def test_project_capture_requires_registered_root_and_valid_hashes(self):
        self.journal.register_project("project", self.temp.name)
        self.journal.append("project", "task.created", {"objective": "Inspect"}, task_id="project-task")
        facade = GovernanceContext(self.journal, "project")
        capture = {"project_id": "project", "root": str(Path(self.temp.name).resolve()),
                   "files": [{"path": "main.py", "sha256": "a" * 64, "text": "print(1)"}],
                   "instructions": [{"path": "AGENTS.md", "sha256": "b" * 64, "content": "Preserve files"}]}
        result = facade.compile(actor_id="user", task_id="project-task", objective="Inspect", project_context=capture)
        self.assertEqual(result["project_context"], capture)
        capture["root"] += "-other"
        with self.assertRaisesRegex(ValueError, "registered project"):
            facade.compile(actor_id="user", task_id="project-task", objective="Inspect", project_context=capture)
        capture["root"] = str(Path(self.temp.name).resolve())
        capture["files"][0]["sha256"] = "invalid"
        with self.assertRaisesRegex(ValueError, "digest"):
            facade.compile(actor_id="user", task_id="project-task", objective="Inspect", project_context=capture)

    def test_included_utf8_bytes_are_hash_checked_with_bom_and_newlines(self):
        self.journal.register_project("project", self.temp.name)
        self.journal.append("project", "task.created", {"objective": "Inspect"}, task_id="project-task")
        facade = GovernanceContext(self.journal, "project")
        body = "print(1)\r\n"
        raw = b"\xef\xbb\xbf" + body.encode("utf-8")
        capture = {"project_id": "project", "root": str(Path(self.temp.name).resolve()),
            "files": [{"path": "main.py", "sha256": hashlib.sha256(raw).hexdigest(),
                       "text": body, "encoding": "utf-8", "bom": True}], "instructions": []}
        facade.compile(actor_id="user", task_id="project-task", objective="Inspect", project_context=capture)
        capture["files"][0]["text"] = "different"
        with self.assertRaisesRegex(ValueError, "raw-byte hash"):
            facade.compile(actor_id="user", task_id="project-task", objective="Inspect", project_context=capture)

    def test_pending_capture_challenge_invalidates_context(self):
        context = self.compile()
        register = ForgeRegister(OperationalLedger(self.journal, "application", "task"))
        register.challenge_claim(actor_id="reviewer", claim_id=context["capture_claim_id"], reason="Capture disputed")
        with self.assertRaisesRegex(ValueError, "stale claim"):
            self.facade.validate_context(context)

    def test_role_proposals_have_no_authority_and_unresolved_claims_remain_visible(self):
        register = ForgeRegister(OperationalLedger(self.journal, "application", "task"))
        claim = register.open_claim(actor_id="user", proposition="Behavior remains uncertain")
        role = self.facade.role("reviewer", RoleClass.ADVERSARIAL_REVIEW, task_id="task")
        proposal = role.submit_proposal("Investigate the failing case", about_claim=claim.claim_id)
        self.assertFalse(role.binding.truth_write_authority)
        context = self.compile()
        self.assertIn(claim.claim_id, [s["claim_id"] for s in context["unresolved_claims"]])
        decision = self.facade.record_decision(task_id="task", actor_id="user", context=context,
            action={"tool": "inspect", "arguments": {}}, authority_ref=self.authority(), rationale="Inspect uncertainty")
        self.assertEqual(decision["uncertainties"][0], {"description": "Behavior remains uncertain", "material": True, "claim_ref": claim.claim_id})
        self.assertIn(proposal.proposal_id, register.proposals)

    def test_failed_context_commit_rolls_back_claim_and_evidence(self):
        before = self.journal.events("application")
        original = self.journal.append
        def fail_final(project_id, kind, payload, **kwargs):
            if kind == "MODEL001_CONTEXT":
                raise OSError("injected context commit failure")
            return original(project_id, kind, payload, **kwargs)
        with patch.object(self.journal, "append", side_effect=fail_final):
            with self.assertRaisesRegex(OSError, "injected"):
                self.compile()
        self.assertEqual(self.journal.events("application"), before)


class FakeClient:
    def __init__(self, tokens=("hello", " world"), block=False):
        self.tokens = tokens
        self.block = block
        self.cancelled = threading.Event()
        self.calls = []
        self.closed = False

    def available_models(self):
        return ["installed"]

    def cancel(self):
        self.cancelled.set()

    def stream(self, model, messages, **limits):
        self.calls.append((model, messages, limits))
        try:
            if self.block:
                self.cancelled.wait(1)
                raise ValueError("cancelled transport")
            for token in self.tokens:
                yield token
        finally:
            self.closed = True


class LocalProviderTests(unittest.TestCase):
    def test_stream_forwards_tokens_and_generation_identity(self):
        client = FakeClient()
        provider = LocalProvider(client)
        tokens = []
        result = provider.stream("installed", [{"role": "user", "content": "hello"}], on_token=tokens.append)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "hello world")
        self.assertEqual(tokens, ["hello", " world"])
        self.assertEqual(result["provider"], "ceta-local")
        self.assertFalse(provider.capabilities()["tool_execution"])
        self.assertTrue(client.closed)

    def test_pre_cancelled_request_never_contacts_client(self):
        client = FakeClient()
        event = threading.Event(); event.set()
        result = LocalProvider(client).stream("installed", [], cancelled=event)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(client.calls, [])

    def test_cancellation_preserves_partial_text_and_closes_transport(self):
        client = FakeClient()
        event = threading.Event()
        result = LocalProvider(client).stream("installed", [], cancelled=event, on_token=lambda token: event.set())
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["text"], "hello")
        self.assertTrue(client.cancelled.is_set())
        self.assertTrue(client.closed)

    def test_deadline_cancels_blocked_local_transport(self):
        client = FakeClient(block=True)
        result = LocalProvider(client, timeout_seconds=0.03).stream("installed", [])
        self.assertEqual(result["status"], "timed_out")
        self.assertTrue(client.cancelled.is_set())
        self.assertTrue(client.closed)

    def test_nontext_token_is_failed_not_executed(self):
        result = LocalProvider(FakeClient(tokens=({"tool": "delete"},))).stream("installed", [])
        self.assertEqual(result["status"], "failed")
        self.assertIn("non-text", result["error"])
        self.assertEqual(result["text"], "")

    def test_oversized_token_is_not_retained_in_partial_output(self):
        result = LocalProvider(FakeClient(tokens=("prefix", "x" * (2 * 1024 * 1024)))).stream("installed", [])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["text"], "prefix")

    def test_invalid_limits_and_messages_fail_before_transport(self):
        for value in (0, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LocalProvider(FakeClient(), timeout_seconds=value)
        client = FakeClient()
        result = LocalProvider(client).stream("installed", [{"role": "tool", "content": "command"}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
