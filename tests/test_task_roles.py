from pathlib import Path
import tempfile
import unittest

from runtime.tasks import TaskRuntime


class Provider:
    provider_id = "ceta-local"

    def __init__(self, status="completed"):
        self.status, self.calls = status, []

    def stream(self, model, messages, **kwargs):
        self.calls.append((model, messages))
        return {"status": self.status, "text": "source.py:1: verify negative inputs.",
                "model": model, "provider": self.provider_id}


class TaskRoleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ceta-role-test-")
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.root = self.directory / "project"
        self.root.mkdir()
        (self.root / "source.py").write_text("answer = 1\n", encoding="utf-8")
        self.runtime = TaskRuntime(self.directory / "state")
        self.addCleanup(self.runtime.close)
        self.project_id = self.runtime.open_project(self.root)["project_id"]
        self.task_id = self.runtime.start_task(self.project_id, "Review source.py")["task_id"]

    def test_roles_use_same_provider_and_context_without_effect_authority(self):
        for role in ("reviewer", "specialist"):
            with self.subTest(role=role):
                provider = Provider()
                result = self.runtime.generate(self.task_id, provider, "test-only", [{"role": "user", "content": "Review it"}], paths=("source.py",), role=role)
                self.assertEqual(len(provider.calls), 1)
                self.assertIn("Selected role: " + role, provider.calls[0][1][0]["content"])
                self.assertIn("answer = 1", provider.calls[0][1][0]["content"])
                proposal = result["role_proposal"]
                self.assertFalse(proposal["grants_authority"])
                self.assertFalse(proposal["independent_evidence"])
                events = self.runtime.timeline(self.task_id)
                self.assertEqual([e for e in events if e["kind"] == "role.proposed"][-1]["payload"], proposal)
                self.assertFalse(any(e["kind"] == "operation.intent" for e in events))
        self.assertEqual((self.root / "source.py").read_text(), "answer = 1\n")
        self.assertTrue(self.runtime.journal.verify())

    def test_failed_or_cancelled_generation_is_not_role_proposal(self):
        for status in ("failed", "cancelled", "timed_out"):
            result = self.runtime.generate(self.task_id, Provider(status), "test-only", [], role="reviewer")
            self.assertIsNone(result["role_proposal"])
        self.assertFalse(any(e["kind"] == "role.proposed" for e in self.runtime.timeline(self.task_id)))

    def test_authority_role_and_revoked_grant_cannot_invoke_provider(self):
        provider = Provider()
        with self.assertRaises(ValueError):
            self.runtime.generate(self.task_id, provider, "test-only", [], role="HUMAN_SCOPE_AUTHORITY")
        self.runtime.revoke_task(self.task_id)
        with self.assertRaises(ValueError):
            self.runtime.generate(self.task_id, provider, "test-only", [], role="reviewer")
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
