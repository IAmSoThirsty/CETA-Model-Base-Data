from __future__ import annotations

import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.generation_plan import assemble_request
from runtime.journal import digest
from runtime.tasks import TaskRuntime
from test_task_runtime import FakeProvider
from runtime.model_provider import LocalProvider
from ceta_desktop.models import LocalModelClient, ModelError


class RequestAllocationTests(unittest.TestCase):
    def context(self):
        return {"project_id": "application", "root": None, "objective": "Chat", "instructions": [], "files": []}

    def plan(self, messages, context=None, **kwargs):
        return assemble_request(context or self.context(), messages, context_length=4096, max_tokens=1024, **kwargs)

    def test_all_content_and_output_reserve_are_accounted_for(self):
        plan = self.plan([{"role": "user", "content": "中文🙂" * 50}])
        budget = plan["budget"]
        self.assertLessEqual(budget["input_token_estimate"] + budget["reserved_output_tokens"] + budget["template_overhead_reserve"], 4096)
        self.assertFalse(budget["verified"])
        self.assertEqual(plan["messages_hash"], digest(plan["messages"]))

    def test_plain_chat_omits_internal_task_metadata_and_retains_user_format(self):
        context = self.context()
        context["objective"] = "Internal task label, not an instruction to the assistant"
        messages = [{"role": "user", "content": 'Return only JSON: {"answer":7}'}]
        before = copy.deepcopy(context)
        plan = self.plan(messages, context)
        self.assertEqual(plan["messages"][-1], messages[-1])
        system = plan["messages"][0]["content"]
        self.assertNotIn(context["objective"], system)
        self.assertNotIn('"project_id"', system)
        self.assertNotIn("Project context", system)
        self.assertIn("requested response format", system)
        self.assertIn("only the application can authorize and execute", system)
        self.assertEqual(context, before)

    def test_project_and_role_instructions_remain_mandatory_context(self):
        context = self.context()
        context.update(root="/synthetic/project", objective="Review the implementation",
            instructions=[{"path": "AGENTS.md", "sha256": "a" * 64, "text": "Keep the documented interface"}])
        plan = self.plan([{"role": "user", "content": "Review the code"}], context,
                         role_instruction="\nSelected role: reviewer")
        system = plan["messages"][0]["content"]
        for expected in (context["root"], context["objective"], "AGENTS.md", "a" * 64,
                         "Keep the documented interface", "Selected role: reviewer"):
            self.assertIn(expected, system)
        self.assertEqual(plan["messages_hash"], digest(plan["messages"]))

    def test_mandatory_instructions_are_not_silently_dropped(self):
        context = self.context()
        context["instructions"] = [{"path": "AGENTS.md", "sha256": "a" * 64, "text": "mandatory" * 1000}]
        with self.assertRaisesRegex(ValueError, "mandatory instructions"):
            self.plan([{"role": "user", "content": "hello"}], context)

    def test_retained_history_is_chronological_and_current_turn_is_last(self):
        messages = [{"role": role, "content": str(index) + ":" + "x" * 300}
                    for index in range(10) for role in ("user", "assistant")]
        messages.append({"role": "user", "content": "current"})
        before = copy.deepcopy(messages)
        plan = self.plan(messages)
        self.assertEqual(plan["messages"][-1], messages[-1])
        retained = plan["messages"][1:-1]
        self.assertEqual([row["role"] for row in retained], ["user", "assistant"] * (len(retained) // 2))
        self.assertEqual([row["content"] for row in retained], [row["content"] for row in messages[-len(retained)-1:-1]])
        self.assertTrue(plan["omitted"])
        self.assertEqual(messages, before)

    def test_large_attachment_is_disclosed_instead_of_consuming_output_reserve(self):
        context = self.context()
        context["files"] = [{"path": "huge.py", "text": "x" * 5000, "sha256": "a" * 64}]
        plan = self.plan([{"role": "user", "content": "Explain"}], context)
        self.assertEqual(plan["selected_paths"], [])
        self.assertIn({"path": "huge.py", "reason": "source_exceeds_request_budget"}, plan["omitted"])


class PreparedGenerationTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch("ceta_desktop.runtime_coordination.default_directory", return_value=Path(directory)))
        self.temp = tempfile.TemporaryDirectory(prefix="ceta-prepared-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "src/AGENTS.md").write_text("Nested required instruction", encoding="utf-8")
        (self.root / "src/file.py").write_text("disk_text = 1", encoding="utf-8")
        self.runtime = TaskRuntime(Path(self.temp.name) / "data")
        self.addCleanup(self.runtime.close)
        self.project = self.runtime.open_project(self.root)["project_id"]
        self.task = self.runtime.start_task(self.project, "Review the file")["task_id"]
        self.provider = FakeProvider()
        self.messages = [{"role": "user", "content": "Explain this file"}]

    def prepare(self, **kwargs):
        return self.runtime.prepare_generation(self.task, self.provider, "test-model", self.messages, **kwargs)

    def test_nested_instructions_and_exact_payload_are_bound(self):
        prepared = self.prepare(paths=["src/file.py"])
        result = self.runtime.generate(self.task, self.provider, "test-model", self.messages, prepared=prepared)
        self.assertEqual(result["status"], "completed")
        sent = self.provider.calls[0]["messages"]
        self.assertIn("Nested required instruction", sent[0]["content"])
        self.assertIn("disk_text = 1", sent[-1]["content"])
        self.assertEqual(prepared["messages_hash"], digest(sent))
        self.assertEqual(result["request_id"], prepared["request_id"])
        with self.assertRaisesRegex(ValueError, "already"):
            self.runtime.generate(self.task, self.provider, "test-model", self.messages, prepared=prepared)

    def test_stale_file_rejects_before_provider_intent(self):
        prepared = self.prepare(paths=["src/file.py"])
        (self.root / "src/file.py").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.runtime.generate(self.task, self.provider, "test-model", self.messages, prepared=prepared)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.runtime.journal.events(self.project, kind="provider.intent"), [])

    def test_rehashed_forged_plan_and_changed_request_are_rejected(self):
        prepared = self.prepare()
        forged = copy.deepcopy(prepared)
        forged["messages"][-1]["content"] = "forged"
        forged["messages_hash"] = digest(forged["messages"])
        forged["plan_hash"] = digest({key: value for key, value in forged.items() if key != "plan_hash"})
        for plan, messages in ((forged, self.messages), (prepared, [{"role": "user", "content": "different"}])):
            with self.assertRaises(ValueError):
                self.runtime.generate(self.task, self.provider, "test-model", messages, prepared=plan)
        self.assertEqual(self.provider.calls, [])

    def test_attachment_base_and_text_hash_are_checked_before_preparation(self):
        source = self.runtime.read(self.task, "src/file.py")
        attachment = {"workspace": str(self.root), "path": "src/file.py", "text": "draft = 2",
                      "base_sha256": source["sha256"], "text_sha256": hashlib.sha256(b"draft = 2").hexdigest()}
        prepared = self.prepare(attachments=[attachment])
        self.assertIn("draft = 2", prepared["messages"][-1]["content"])
        for field in ("base_sha256", "text_sha256"):
            invalid = {**attachment, field: "a" * 64}
            with self.assertRaises(ValueError):
                self.prepare(attachments=[invalid])

    def test_changed_model_profile_refuses_dispatch(self):
        class ProfileProvider(FakeProvider):
            revision = "first"
            def generation_profile(self, model):
                return {"provider": self.provider_id, "model": model, "context_length": 4096,
                        "max_tokens": 1024, "revision": self.revision}
        provider = ProfileProvider()
        prepared = self.runtime.prepare_generation(self.task, provider, "test-model", self.messages)
        provider.revision = "different"
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            self.runtime.generate(self.task, provider, "test-model", self.messages, prepared=prepared)
        self.assertEqual(provider.calls, [])

    def transport_fixture(self):
        client = LocalModelClient("http://127.0.0.1:11434/v1")
        observed = {"model": "test-model", "backend": "ollama", "locality": "local", "thinking_mode": False,
                    "digest": "a" * 64, "context_limit": 4096}
        self.enterContext(patch.object(client, "model_readiness", return_value=observed))
        self.enterContext(patch.object(client, "_preflight_ollama", return_value={"mode": "synthetic"}))
        request = self.enterContext(patch.object(client, "_request", return_value=io.BytesIO(
            b'{"message":{"content":"local response"},"done":true}\n')))
        return client, LocalProvider(client, context_length=4096), observed, request

    def test_receipt_hash_covers_the_actual_transport_body(self):
        client, provider, _, request = self.transport_fixture()
        prepared = self.runtime.prepare_generation(self.task, provider, "test-model", self.messages)
        result = self.runtime.generate(self.task, provider, "test-model", self.messages, prepared=prepared)
        self.assertEqual(result["status"], "completed", result.get("error"))
        request.assert_called_once()
        method, path, body = request.call_args.args
        self.assertEqual(method, "POST")
        self.assertEqual({"path": path, "body": body}, prepared["payload"])
        self.assertEqual(result["payload_hash"], digest({"path": path, "body": body}))

    def test_source_rechecked_after_backend_preflight_before_http(self):
        client, provider, _, request = self.transport_fixture()
        prepared = self.runtime.prepare_generation(self.task, provider, "test-model", self.messages, paths=["src/file.py"])
        def change(*args):
            (self.root / "src/file.py").write_text("changed during preflight", encoding="utf-8")
            return {"mode": "synthetic"}
        with patch.object(client, "_preflight_ollama", side_effect=change):
            result = self.runtime.generate(self.task, provider, "test-model", self.messages, prepared=prepared)
        self.assertEqual(result["status"], "failed")
        request.assert_not_called()


    def test_tag_change_at_final_transport_inspection_is_rejected(self):
        client, provider, observed, request = self.transport_fixture()
        prepared = self.runtime.prepare_generation(self.task, provider, "test-model", self.messages)
        count = 0
        def readiness(_):
            nonlocal count
            count += 1
            return {**observed, "digest": "b" * 64} if count > 1 else observed
        with patch.object(client, "model_readiness", side_effect=readiness):
            result = self.runtime.generate(self.task, provider, "test-model", self.messages, prepared=prepared)
        self.assertEqual(result["status"], "failed")
        request.assert_not_called()


class PreparedTransportTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch("ceta_desktop.runtime_coordination.default_directory", return_value=Path(directory)))

    def test_generic_empty_done_and_malformed_events_fail(self):
        for response in (b'data: [DONE]\n', b'data: {"choices":[{"delta":{"content":" "}}]}\ndata: [DONE]\n',
                         b'data: []\n', b'data: {"choices":[null]}\n'):
            with self.subTest(response=response):
                client = LocalModelClient("http://127.0.0.1:8080/v1")
                with patch.object(client, "model_readiness", return_value={"backend": "openai-compatible", "locality": "unverified"}), \
                        patch.object(client, "_request", return_value=io.BytesIO(response)):
                    with self.assertRaises(ModelError):
                        list(client.stream("test", [{"role": "user", "content": "hello"}]))

    def test_cancellation_during_provider_acquisition_is_not_cleared(self):
        from test_model001_integration import FakeClient
        client = FakeClient()
        class CancelOnAcquire:
            def acquire(self, blocking=False):
                client.cancelled.set()
                return True
            def release(self):
                pass
        provider = LocalProvider(client)
        provider._active = CancelOnAcquire()
        result = provider.stream("test", [{"role": "user", "content": "hello"}], cancelled=client.cancelled)
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(client.cancelled.is_set())
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
