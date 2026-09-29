from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runtime.journal import Journal
from runtime.tasks import TaskRuntime
from runtime import project_tools


class FakeProvider:
    provider_id = "ceta-local"

    def __init__(self, token="proposed explanation"):
        self.token = token
        self.calls = []

    def stream(self, model, messages, cancelled=None, on_token=None):
        self.calls.append({"model": model, "messages": copy.deepcopy(messages)})
        if on_token:
            on_token(self.token)
        check_cancelled = getattr(cancelled, "is_set", cancelled)
        return {"status": "cancelled" if check_cancelled and check_cancelled() else "completed",
                "text": self.token, "provider": self.provider_id, "model": model,
                "configuration": {"temperature": 0, "max_tokens": 32}}


class TaskRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ceta-task-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.directory = self.base / "state"
        self.root = self.base / "project-one"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text("Preserve source and report evidence.\n", encoding="utf-8", newline="\n")
        self.source = self.root / "example.py"
        self.source.write_text("value = 1\n", encoding="utf-8", newline="\n")
        self.runtime = self.new_runtime()
        self.project = self.runtime.open_project(self.root)
        self.task = self.runtime.start_task(self.project["project_id"], "Inspect and improve the selected project")
        self.task_id = self.task["task_id"]

    def new_runtime(self):
        runtime = TaskRuntime(self.directory)
        self.addCleanup(runtime.close)
        return runtime

    def test_authority_check_verifies_one_current_task_snapshot(self):
        journal = self.runtime.journal
        with patch.object(journal, "_verify_project", wraps=journal._verify_project) as verification:
            self.assertEqual(self.runtime._access(self.task_id, "Generate")["task_id"], self.task_id)
            self.assertEqual(verification.call_count, 1)
        with self.assertRaises(ValueError):
            self.runtime._access(self.task_id, "Execute")

    def test_task_snapshot_observes_revocation_from_another_runtime(self):
        self.runtime._access(self.task_id, "Generate")
        other = self.new_runtime()
        other.revoke_task(self.task_id)
        self.assertEqual(self.runtime.task_access_status(self.task_id)["status"], "revoked")
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.runtime._access(self.task_id, "Generate")

    def events(self, kind=None, runtime=None, task_id=None):
        runtime = runtime or self.runtime
        return runtime.journal.events(self.project["project_id"], kind=kind, task_id=task_id or self.task_id)

    def proposal(self, text="value = 2\n"):
        return self.runtime.propose_edit(self.task_id, self.source, text)

    def command(self, script):
        return self.runtime.prepare_command(self.task_id, [sys.executable, "-B", "-c", script])

    def test_open_project_rejects_raw_root_alias_before_recording_access(self):
        alias = self.base / "project-alias"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(self.root), str(alias))
        else:
            alias.symlink_to(self.root, target_is_directory=True)
        try:
            nested = self.root / "nested"
            nested.mkdir()
            before = self.runtime.journal.events(self.project["project_id"])
            for selected in (alias, alias / "nested"):
                with self.subTest(selected=selected):
                    with self.assertRaisesRegex(project_tools.ProjectToolError, "symlink or reparse"):
                        self.runtime.open_project(selected)
            self.assertEqual(self.runtime.journal.events(self.project["project_id"]), before)
            self.assertTrue(self.source.is_file())
        finally:
            if os.name == "nt":
                alias.rmdir()
            else:
                alias.unlink()

    def test_open_project_rejects_git_internal_root(self):
        internal = self.root / ".git"
        internal.mkdir()
        before = self.runtime.journal.events(self.project["project_id"])
        with self.assertRaisesRegex(project_tools.ProjectToolError, "Git internals"):
            self.runtime.open_project(internal)
        self.assertEqual(self.runtime.journal.events(self.project["project_id"]), before)

    def test_real_edit_has_verified_ceta_receipt_and_survives_restart(self):
        proposal = self.proposal()
        result = self.runtime.apply_edit(self.task_id, proposal["proposal_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["verification"]["status"], "VERIFIED")
        self.assertEqual(result["receipt"]["adapter_id"], "ceta.task.edit")
        self.assertEqual(self.source.read_text(encoding="utf-8"), "value = 2\n")
        self.assertEqual(len(self.events("operation.intent")), 1)
        self.assertEqual(len(self.events("operation.result")), 1)
        before = self.runtime.timeline(self.task_id)
        reopened = self.new_runtime()
        self.assertEqual(reopened.timeline(self.task_id), before)
        self.assertEqual(reopened.task(self.task_id)["status"], "completed")
        self.assertTrue(reopened.journal.verify())
        with self.assertRaises(ValueError):
            reopened.apply_edit(self.task_id, proposal["proposal_id"])

    def test_stale_source_refuses_admission_and_preserves_user_edit(self):
        proposal = self.proposal()
        self.source.write_text("user-owned change\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(self.task_id, proposal["proposal_id"])
        self.assertEqual(self.source.read_text(), "user-owned change\n")
        self.assertEqual(self.events("operation.intent"), [])

    def test_stale_instruction_refuses_admission(self):
        proposal = self.proposal()
        (self.root / "AGENTS.md").write_text("New applicable instruction", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(self.task_id, proposal["proposal_id"])
        self.assertEqual(self.source.read_text(), "value = 1\n")
        self.assertEqual(self.events("operation.intent"), [])

    def test_new_file_context_keeps_nested_instruction_and_detects_creation_race(self):
        nested = self.root / "src"
        nested.mkdir()
        (nested / "AGENTS.md").write_text("Nested instruction", encoding="utf-8")
        proposal = self.runtime.propose_edit(self.task_id, "src/new.py", "new content\n")
        context = self.events("edit.proposed")[-1]["payload"]["context"]["project_context"]
        self.assertEqual(context["new_paths"], ["src/new.py"])
        self.assertIn("src/AGENTS.md", {item["path"] for item in context["instructions"]})
        (nested / "new.py").write_text("user created", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(self.task_id, proposal["proposal_id"])
        self.assertEqual((nested / "new.py").read_text(), "user created")

    def test_new_file_can_be_created_through_the_same_runtime(self):
        proposal = self.runtime.propose_edit(self.task_id, "new.py", "new content\n")
        result = self.runtime.apply_edit(self.task_id, proposal["proposal_id"])
        self.assertEqual(result["verification"]["status"], "VERIFIED")
        self.assertEqual((self.root / "new.py").read_text(), "new content\n")

    def test_project_task_and_proposal_identities_do_not_cross(self):
        proposal = self.proposal()
        other_root = self.base / "project-two"
        other_root.mkdir()
        other_source = other_root / "example.py"
        other_source.write_text("unrelated project\n", encoding="utf-8")
        other_project = self.runtime.open_project(other_root)
        other_task = self.runtime.start_task(other_project["project_id"], "Inspect the other project")
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(other_task["task_id"], proposal["proposal_id"])
        with self.assertRaises(ValueError):
            self.runtime.read(other_task["task_id"], self.source)
        self.assertEqual(other_source.read_text(), "unrelated project\n")
        self.assertEqual(self.source.read_text(), "value = 1\n")
        other_events = self.runtime.timeline(other_task["task_id"])
        self.assertFalse(any(event["kind"] == "edit.proposed" for event in other_events))

    def test_same_project_different_task_cannot_use_proposal(self):
        proposal = self.proposal()
        other = self.runtime.start_task(self.project["project_id"], "Separate task")
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(other["task_id"], proposal["proposal_id"])
        self.assertEqual(self.source.read_text(), "value = 1\n")

    def test_model_origin_cannot_self_approve_an_edit(self):
        proposal = self.proposal()
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(self.task_id, proposal["proposal_id"], actor_id="model")
        self.assertEqual(self.events("operation.intent"), [])

    def test_failed_command_preserves_real_exit_and_failed_task_status(self):
        prepared = self.command("import sys; print('failing-check', flush=True); sys.exit(9)")
        result = self.runtime.run_command(self.task_id, prepared["prepared_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 9)
        self.assertIn("failing-check", result["output"])
        self.assertEqual(self.runtime.task(self.task_id)["status"], "failed")
        recorded = self.events("operation.result")[-1]["payload"]["result"]
        self.assertEqual(recorded["exit_code"], 9)
        self.assertEqual(recorded["status"], "failed")

    def test_command_exit_does_not_claim_semantic_effect_verification(self):
        prepared = self.command("print('done')")
        result = self.runtime.run_command(self.task_id, prepared["prepared_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertNotEqual(result["verification"]["status"], "VERIFIED")
        self.assertEqual(result["mode"], "trusted_local")

    def test_generation_receives_context_and_records_provider_metadata_without_effect(self):
        provider = FakeProvider()
        result = self.runtime.generate(self.task_id, provider, "fake-local-model",
                                       [{"role": "user", "content": "Explain this file"}], paths=["example.py"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(provider.calls[0]["model"], "fake-local-model")
        system = provider.calls[0]["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("Preserve source and report evidence", system["content"])
        self.assertIn("value = 1", provider.calls[0]["messages"][-1]["content"])
        self.assertEqual(self.events("operation.intent"), [])
        self.assertEqual(self.source.read_text(), "value = 1\n")
        intent = self.events("provider.intent")[-1]["payload"]
        self.assertEqual(intent["provider"], "ceta-local")
        self.assertEqual(intent["model"], "fake-local-model")
        observed = self.events("provider.result")[-1]["payload"]
        self.assertEqual(observed["configuration"], {"temperature": 0, "max_tokens": 32})
        self.assertEqual(intent["context_hash"], observed["context_hash"])

    def test_revoked_task_denies_read_generation_and_edit(self):
        proposal = self.proposal()
        self.runtime.revoke_task(self.task_id)
        with self.assertRaises(ValueError):
            self.runtime.read(self.task_id, "example.py")
        provider = FakeProvider()
        with self.assertRaises(ValueError):
            self.runtime.generate(self.task_id, provider, "fake", [])
        with self.assertRaises(ValueError):
            self.runtime.apply_edit(self.task_id, proposal["proposal_id"])
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.source.read_text(), "value = 1\n")

    def test_revocation_during_generation_is_observed_as_cancellation(self):
        second = self.new_runtime()
        provider = FakeProvider()
        with patch("runtime.tasks.time.monotonic", return_value=100.0):
            result = self.runtime.generate(self.task_id, provider, "fake", [],
                                           on_token=lambda _text: second.revoke_task(self.task_id))
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.events("provider.result")[-1]["payload"]["status"], "cancelled")
        self.assertEqual(self.runtime.task(self.task_id)["status"], "cancelled")

    def test_revocation_during_command_cancels_owned_process(self):
        second = self.new_runtime()
        prepared = self.command("import time; print('started', flush=True); time.sleep(30)")
        revoked = []
        def output(text):
            if "started" in text and not revoked:
                revoked.append(True)
                second.revoke_task(self.task_id)
        started = time.monotonic()
        result = self.runtime.run_command(self.task_id, prepared["prepared_id"], on_output=output, timeout_seconds=4)
        self.assertTrue(revoked)
        self.assertEqual(result["status"], "cancelled")
        self.assertLess(time.monotonic() - started, 5)

    def test_expired_grant_cancels_active_command(self):
        from runtime import tasks as task_module
        prepared = self.command("import time; print('started', flush=True); time.sleep(30)")
        original_now = task_module._now
        clock = {"offset": 0}
        def output(text):
            if "started" in text:
                clock["offset"] = 25 * 60 * 60 * 1000
        with patch.object(task_module, "_now", side_effect=lambda: original_now() + clock["offset"]):
            result = self.runtime.run_command(self.task_id, prepared["prepared_id"], on_output=output, timeout_seconds=4)
        self.assertEqual(result["status"], "cancelled")
        self.assertNotEqual(result["exit_code"], 0)

    def test_expired_grant_cancels_active_generation(self):
        from runtime import tasks as task_module
        original_now = task_module._now
        clock = {"offset": 0}
        def token(_text):
            clock["offset"] = 25 * 60 * 60 * 1000
        with patch.object(task_module, "_now", side_effect=lambda: original_now() + clock["offset"]), \
                patch("runtime.tasks.time.monotonic", return_value=100.0):
            result = self.runtime.generate(self.task_id, FakeProvider(), "fake", [], on_token=token)
        self.assertEqual(result["status"], "cancelled")

    def test_active_command_blocks_another_effect_in_the_same_task(self):
        second = self.new_runtime()
        prepared = self.command("import time; print('started', flush=True); time.sleep(30)")
        rejections = []
        cancel = threading.Event()
        def output(text):
            if "started" in text and not cancel.is_set():
                try:
                    another = second.prepare_command(self.task_id, [sys.executable, "-c", "print('second')"])
                    second.run_command(self.task_id, another["prepared_id"])
                except ValueError as exc:
                    rejections.append(str(exc))
                finally:
                    cancel.set()
        # Admission exclusion is the assertion; allow unrelated host scheduling
        # delays without turning this into a four-second startup benchmark.
        result = self.runtime.run_command(self.task_id, prepared["prepared_id"], cancelled=cancel,
                                          on_output=output, timeout_seconds=20)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(rejections), 1)
        self.assertEqual(len(self.events("operation.intent")), 1)

    def test_duplicate_command_admission_across_two_journal_connections_runs_once(self):
        prepared = self.command("from pathlib import Path; p=Path('count.txt'); p.write_text(p.read_text()+'x' if p.exists() else 'x')")
        second = self.new_runtime()
        barrier = threading.Barrier(2)
        def execute(runtime):
            barrier.wait(timeout=10)
            try:
                return ("result", runtime.run_command(self.task_id, prepared["prepared_id"]))
            except ValueError as exc:
                return ("denied", str(exc))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(execute, runtime) for runtime in [self.runtime, second]]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(kind == "result" for kind, _ in results), 1, results)
        self.assertEqual(sum(kind == "denied" for kind, _ in results), 1, results)
        self.assertEqual((self.root / "count.txt").read_text(), "x")
        self.assertEqual(len(self.events("operation.intent")), 1)
        self.assertTrue(self.runtime.journal.verify())
        self.assertTrue(second.journal.verify())

    def test_log_failure_after_effect_prevents_replay_on_restart(self):
        proposal = self.proposal()
        original_append = self.runtime.journal.append
        def append(project_id, kind, *args, **kwargs):
            if kind == "operation.result":
                raise OSError("simulated result journal failure")
            return original_append(project_id, kind, *args, **kwargs)
        with patch.object(self.runtime.journal, "append", side_effect=append), \
                patch.object(project_tools, "apply_edit", wraps=project_tools.apply_edit) as actual_edit:
            with self.assertRaises(OSError):
                self.runtime.apply_edit(self.task_id, proposal["proposal_id"])
            self.assertEqual(actual_edit.call_count, 1)
            reopened = self.new_runtime()
            reopened.recover_interrupted()
            with self.assertRaises(ValueError):
                reopened.apply_edit(self.task_id, proposal["proposal_id"])
            self.assertEqual(actual_edit.call_count, 1)
        self.assertEqual(self.source.read_text(), "value = 2\n")
        self.assertEqual(self.runtime.task(self.task_id)["status"], "needs_reconciliation")
        self.assertEqual(self.events("operation.result"), [])

    def test_recovery_finds_unmatched_provider_intent_even_if_task_was_ready(self):
        self.runtime.journal.append(self.project["project_id"], "provider.intent",
                                    {"invocation_id": "generation-unfinished", "provider": "ceta-local", "model": "fake"},
                                    task_id=self.task_id)
        self.assertEqual(self.runtime.task(self.task_id)["status"], "ready")
        reopened = self.new_runtime()
        self.assertIn(self.task_id, reopened.recover_interrupted())
        self.assertEqual(reopened.task(self.task_id)["status"], "interrupted")
        self.assertEqual(reopened.recover_interrupted(), [])

    def test_recovery_finds_unmatched_effect_intent_without_reexecution(self):
        self.runtime.journal.append(self.project["project_id"], "operation.intent",
                                    {"action_id": "action-unfinished", "kind": "command", "proposal_id": "not-run"},
                                    task_id=self.task_id)
        reopened = self.new_runtime()
        self.assertIn(self.task_id, reopened.recover_interrupted())
        self.assertEqual(reopened.task(self.task_id)["status"], "needs_reconciliation")
        self.assertEqual(reopened.recover_interrupted(), [])
        self.assertEqual(self.events("operation.result"), [])
        self.assertEqual(self.source.read_text(), "value = 1\n")

    def test_unregistered_provider_is_never_invoked(self):
        provider = FakeProvider()
        provider.provider_id = "remote-provider"
        with self.assertRaises(ValueError):
            self.runtime.generate(self.task_id, provider, "fake", [])
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.events("provider.intent"), [])

    def test_completed_generation_is_not_reclassified_on_restart(self):
        self.runtime.generate(self.task_id, FakeProvider(), "fake", [])
        reopened = self.new_runtime()
        self.assertNotIn(self.task_id, reopened.recover_interrupted())
        self.assertEqual(reopened.task(self.task_id)["status"], "completed")

    def test_read_and_search_evidence_stays_in_authoritative_project_stream(self):
        result = self.runtime.read(self.task_id, "example.py")
        matches = self.runtime.search(self.task_id, "value")
        self.assertEqual(result["text"], "value = 1\n")
        self.assertEqual(matches["matches"][0]["path"], "example.py")
        events = self.runtime.timeline(self.task_id)
        self.assertEqual(len([event for event in events if event["kind"] == "access.intent"]), 2)
        self.assertEqual(len([event for event in events if event["kind"] == "access.completed"]), 2)
        observer = Journal(self.directory / "desktop.sqlite3")
        self.addCleanup(observer.close)
        self.assertEqual(observer.events(self.project["project_id"], task_id=self.task_id), events)


if __name__ == "__main__":
    unittest.main()
