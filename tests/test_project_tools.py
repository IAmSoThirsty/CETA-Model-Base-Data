from __future__ import annotations

import codecs
import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ceta_desktop.workspace import WorkspaceError
from runtime import project_tools as tools


class ProjectToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ceta-project-tools-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "AGENTS.md").write_text("Root instructions.\n", encoding="utf-8", newline="\n")
        (self.root / "src").mkdir()
        (self.root / "src/AGENTS.md").write_text("Source instructions.\n", encoding="utf-8", newline="\n")
        (self.root / "src/example.py").write_text("value = 1\n", encoding="utf-8")

    def test_inspection_is_deterministic_and_discovers_nested_instructions(self):
        first = tools.inspect_project(self.root)
        self.assertEqual(first, tools.inspect_project(self.root))
        self.assertEqual(first["root"], str(self.root))
        self.assertEqual(first["git"]["kind"], "non_git")
        self.assertEqual({item["path"] for item in first["instructions"]}, {"AGENTS.md", "src/AGENTS.md"})
        (self.root / "other").mkdir()
        self.assertNotEqual(first["project_id"], tools.inspect_project(self.root / "other")["project_id"])

    def test_context_selects_only_applicable_instructions(self):
        (self.root / "unrelated").mkdir()
        (self.root / "unrelated/AGENTS.md").write_text("Unrelated scope", encoding="utf-8")
        (self.root / ".codex").mkdir()
        (self.root / ".codex/AGENTS.md").write_text("Project-local settings", encoding="utf-8")
        context = tools.compile_project_context(self.root, "Explain source", ["src/example.py"])
        self.assertEqual({item["path"] for item in context["instructions"]},
                         {"AGENTS.md", "src/AGENTS.md", ".codex/AGENTS.md"})
        tools.validate_project_context(context)

    def test_context_does_not_import_parent_instructions(self):
        context = tools.compile_project_context(self.root / "src", "Explain source", ["example.py"])
        self.assertEqual(len(context["instructions"]), 1)
        self.assertEqual(context["instructions"][0]["text"], "Source instructions.\n")

    def test_selected_file_under_generated_directory_retains_instruction_scope(self):
        (self.root / "build").mkdir()
        (self.root / "build/AGENTS.md").write_text("Build-specific instruction", encoding="utf-8")
        context = tools.compile_project_context(self.root, "Add source", ["build/new.py"])
        self.assertIn("build/AGENTS.md", {item["path"] for item in context["instructions"]})
        tools.validate_project_context(context)
        (self.root / "build/AGENTS.md").write_text("Changed instruction", encoding="utf-8")
        with self.assertRaises(tools.ContextStaleError):
            tools.validate_project_context(context)

    def test_new_instruction_in_skipped_directory_invalidates_selected_context(self):
        (self.root / "build").mkdir()
        context = tools.compile_project_context(self.root, "Add source", ["build/new.py"])
        (self.root / "build/AGENTS.md").write_text("New required instruction", encoding="utf-8")
        with self.assertRaises(tools.ContextStaleError):
            tools.validate_project_context(context)

    def test_new_file_context_binds_absence_and_nested_instructions(self):
        context = tools.compile_project_context(self.root, "Add source", ["src/new.py"])
        self.assertEqual(context["new_paths"], ["src/new.py"])
        self.assertEqual(context["files"], [])
        self.assertEqual({item["path"] for item in context["instructions"]}, {"AGENTS.md", "src/AGENTS.md"})
        tools.validate_project_context(context)
        (self.root / "src/new.py").write_text("user-created", encoding="utf-8")
        with self.assertRaises(tools.ContextStaleError):
            tools.validate_project_context(context)

    def test_new_file_context_rejects_missing_parent_and_sensitive_paths(self):
        for path in ["missing/new.py", "src/.env", ".git/config"]:
            with self.subTest(path=path), self.assertRaises(tools.ProjectToolError):
                tools.compile_project_context(self.root, "Add source", [path])

    def test_context_detects_same_size_file_change_with_restored_timestamp(self):
        context = tools.compile_project_context(self.root, "Explain source", ["src/example.py"])
        target = self.root / "src/example.py"
        original = target.stat()
        target.write_text("value = 2\n", encoding="utf-8")
        os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaises(tools.ContextStaleError):
            tools.validate_project_context(context)

    def test_context_detects_instruction_changes_and_tampering(self):
        context = tools.compile_project_context(self.root, "Inspect")
        tampered = copy.deepcopy(context)
        tampered["objective"] = "Other objective"
        with self.assertRaises(tools.ContextStaleError):
            tools.validate_project_context(tampered)
        (self.root / "AGENTS.md").write_text("Changed authority", encoding="utf-8")
        with self.assertRaises(tools.ContextStaleError):
            tools.validate_project_context(context)

    def test_runtime_bookkeeping_does_not_invalidate_context(self):
        context = tools.compile_project_context(self.root, "Inspect")
        for name in ["desktop.sqlite3", "desktop.sqlite3-wal", "desktop.sqlite3-shm",
                     "runtime-identity.json", "runtime-identity.json.lock", ".ceta-save-test"]:
            (self.root / name).write_bytes(b"bookkeeping")
        tools.validate_project_context(context)
        result = tools.search_code(self.root, "bookkeeping")
        self.assertEqual(result["matches"], [])

    def test_mandatory_context_is_never_silently_truncated(self):
        (self.root / "AGENTS.md").write_text("MANDATORY " * 1000, encoding="utf-8")
        with self.assertRaises(tools.ContextBudgetError):
            tools.compile_project_context(self.root, "Inspect", max_context_chars=2000)

    def test_optional_source_omission_is_explicit_and_still_bound(self):
        target = self.root / "src/example.py"
        target.write_text("a" * 20_000, encoding="utf-8")
        context = tools.compile_project_context(self.root, "Inspect", [target], max_context_chars=5000)
        self.assertEqual(context["files"], [])
        self.assertEqual(context["omitted"][0]["path"], "src/example.py")
        tools.validate_project_context(context)
        target.write_text("b" * 20_000, encoding="utf-8")
        with self.assertRaises(tools.ContextStaleError):
            tools.validate_project_context(context)

    def test_incomplete_instruction_discovery_fails_closed(self):
        with patch.object(tools, "MAX_SCAN_ENTRIES", 1):
            self.assertTrue(tools.inspect_project(self.root)["scan_truncated"])
            with self.assertRaises(tools.ContextBudgetError):
                tools.compile_project_context(self.root, "Inspect")

    def test_sensitive_directory_cannot_become_the_project_root(self):
        for name in (".git", ".ssh"):
            target = self.root / name
            target.mkdir()
            (target / "config").write_text("private metadata", encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(tools.ProjectToolError):
                tools.inspect_project(target)
            with self.subTest(name=name), self.assertRaises(tools.ProjectToolError):
                tools.read_file(target, "config")

    def test_git_output_overflow_is_unknown_and_context_cannot_authorize(self):
        with patch.object(tools, "_capture_git", side_effect=tools._GitInspectionLimit("output budget exceeded", truncated=True)):
            snapshot = tools.inspect_project(self.root)
            self.assertEqual(snapshot["git"]["kind"], "unknown")
            self.assertTrue(snapshot["git"]["truncated"])
            with self.assertRaises(tools.ProjectToolError):
                tools.compile_project_context(self.root, "Inspect")

    def test_git_capture_stops_at_combined_output_budget(self):
        script = "import sys,time; sys.stdout.write('x'*100000); sys.stdout.flush(); time.sleep(30)"
        started = time.monotonic()
        with self.assertRaises(tools._GitInspectionLimit) as failure:
            tools._capture_git([sys.executable, "-c", script], self.root, dict(os.environ), output_limit=1024)
        self.assertTrue(failure.exception.truncated)
        self.assertLess(time.monotonic() - started, 5)

    def test_git_capture_timeout_stops_the_process(self):
        started = time.monotonic()
        with self.assertRaises(tools._GitInspectionLimit) as failure:
            tools._capture_git([sys.executable, "-c", "import time; time.sleep(30)"], self.root,
                               dict(os.environ), timeout_seconds=0.2)
        self.assertFalse(failure.exception.truncated)
        self.assertLess(time.monotonic() - started, 5)

    def test_secrets_git_and_nested_projects_are_excluded(self):
        (self.root / ".env").write_text("SECRET_NEEDLE", encoding="utf-8")
        (self.root / ".env.production").write_text("SECRET_NEEDLE", encoding="utf-8")
        (self.root / "nested").mkdir()
        (self.root / "nested/.git").mkdir()
        (self.root / "nested/source.py").write_text("SECRET_NEEDLE", encoding="utf-8")
        for path in [".env", ".env.production", "nested/source.py", "../outside.py"]:
            with self.subTest(path=path), self.assertRaises(tools.ProjectToolError):
                tools.read_file(self.root, path)
        self.assertEqual(tools.search_code(self.root, "SECRET_NEEDLE")["matches"], [])

    def test_hardlinks_are_not_a_cross_project_read_or_write_route(self):
        os.link(self.root / "src/example.py", self.root / "alias.py")
        with self.assertRaises(tools.ProjectToolError):
            tools.read_file(self.root, "alias.py")
        with self.assertRaises(tools.ProjectToolError):
            tools.propose_edit(self.root, "alias.py", "changed")

    def test_symlink_boundary_rejection(self):
        try:
            (self.root / "alias").symlink_to(self.root / "src", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        with self.assertRaises(tools.ProjectToolError):
            tools.read_file(self.root, "alias/example.py")
        with self.assertRaises(tools.ProjectToolError):
            tools.inspect_project(self.root / "alias")

    def test_read_hash_covers_bom_and_original_newlines(self):
        raw = codecs.BOM_UTF8 + b"first\r\nsecond\r\n"
        (self.root / "source.txt").write_bytes(raw)
        result = tools.read_file(self.root, self.root / "source.txt")
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["text"], "first\r\nsecond\r\n")
        self.assertTrue(result["bom"])

    def test_search_literal_scope_and_limits(self):
        (self.root / "src/example.py").write_text("a.b\na.b\naXb\n", encoding="utf-8")
        result = tools.search_code(self.root, "a.b", max_results=1)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["line"], 1)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["scope"]["literal"])

    def test_edit_preserves_bom_and_crlf(self):
        target = self.root / "source.txt"
        target.write_bytes(codecs.BOM_UTF8 + b"old\r\n")
        proposal = tools.propose_edit(self.root, target, "new\n")
        self.assertIn("+new", proposal["diff"])
        result = tools.apply_edit(self.root, proposal)
        self.assertEqual(target.read_bytes(), codecs.BOM_UTF8 + b"new\r\n")
        self.assertEqual(result["sha256"], proposal["new_sha256"])

    def test_stale_proposal_preserves_user_changes(self):
        target = self.root / "src/example.py"
        proposal = tools.propose_edit(self.root, target, "value = 2\n")
        target.write_text("user change", encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            tools.apply_edit(self.root, proposal)
        self.assertEqual(target.read_text(encoding="utf-8"), "user change")

    def test_proposal_tampering_is_rejected(self):
        proposal = tools.propose_edit(self.root, "src/example.py", "value = 2\n")
        proposal["new_text"] = "unreviewed"
        with self.assertRaises(tools.ProjectToolError):
            tools.apply_edit(self.root, proposal)

    def test_new_file_creation_is_explicit_and_exclusive(self):
        proposal = tools.propose_edit(self.root, "src/new.py", "new file\n")
        self.assertFalse(proposal["expected_exists"])
        self.assertIsNone(proposal["old_sha256"])
        self.assertTrue(tools.apply_edit(self.root, proposal)["created"])
        with self.assertRaises(FileExistsError):
            tools.apply_edit(self.root, proposal)
        self.assertEqual((self.root / "src/new.py").read_text(), "new file\n")

    def test_binary_and_mixed_newline_edits_fail(self):
        (self.root / "binary.bin").write_bytes(b"zero\x00byte")
        with self.assertRaises(tools.ProjectToolError):
            tools.read_file(self.root, "binary.bin")
        (self.root / "mixed.txt").write_bytes(b"a\r\nb\n")
        with self.assertRaises(WorkspaceError):
            tools.propose_edit(self.root, "mixed.txt", "replacement")

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_git_state_tracks_branch_and_dirty_paths(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        snapshot = tools.inspect_project(self.root)
        self.assertEqual(snapshot["git"]["kind"], "git")
        self.assertTrue(snapshot["git"]["dirty"])
        self.assertIsNone(snapshot["git"]["head"])
        self.assertIsInstance(snapshot["git"]["branch"], str)
        context = tools.compile_project_context(self.root, "Inspect")
        (self.root / "desktop.sqlite3").write_bytes(b"journal")
        tools.validate_project_context(context)


class CommandAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ceta-command-tools-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def spec(self, script):
        return tools.command_spec(self.root, [sys.executable, "-B", "-c", script])

    def test_command_streams_output_and_records_real_failure(self):
        output = []
        result = tools.run_command(self.spec("import sys; print('hello', flush=True); sys.exit(7)"), on_output=output.append)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("hello", result["output"])
        self.assertEqual("".join(output), result["output"])
        self.assertEqual(result["mode"], "trusted_local")

    def test_shell_string_semantics_are_preserved(self):
        command = "Write-Output 'one'; Write-Output 'two'" if os.name == "nt" else "printf 'one\ntwo\n'"
        spec = tools.command_spec(self.root, command)
        self.assertEqual(spec["args"][-1], command)
        result = tools.run_command(spec)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("one", result["output"])
        self.assertIn("two", result["output"])

    def test_cancel_before_start_has_no_effect(self):
        result = tools.run_command(self.spec("raise RuntimeError('must not run')"), cancelled=lambda: True)
        self.assertFalse(result["started"])
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["exit_code"])

    def test_timeout_stops_owned_process(self):
        started = time.monotonic()
        result = tools.run_command(self.spec("import time; time.sleep(30)"), timeout_seconds=0.2)
        self.assertEqual(result["status"], "timed_out")
        self.assertLess(time.monotonic() - started, 5)
        self.assertNotEqual(result["exit_code"], 0)

    def test_cancel_stops_owned_descendant_before_later_effect(self):
        marker = self.root / "late.txt"
        child = f"import time; from pathlib import Path; time.sleep(2); Path({str(marker)!r}).write_text('escaped')"
        parent = (f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); "
                  "print('child-started', flush=True); time.sleep(30)")
        cancel = {"value": False}
        def on_output(text):
            if "child-started" in text:
                cancel["value"] = True
        result = tools.run_command(self.spec(parent), cancelled=lambda: cancel["value"], on_output=on_output)
        self.assertEqual(result["status"], "cancelled")
        time.sleep(2.2)
        self.assertFalse(marker.exists())

    def test_output_is_bounded_and_disclosed(self):
        result = tools.run_command(self.spec("print('x'*100000)"), max_output_bytes=1000)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["output"].encode()), 1000)
        self.assertGreater(result["output_bytes"], 1000)
        self.assertTrue(result["output_truncated"])

    def test_command_spec_tampering_fails(self):
        spec = self.spec("print('approved')")
        spec["args"][-1] = "print('unapproved')"
        with self.assertRaises(tools.ProjectToolError):
            tools.run_command(spec)

    def test_callback_failure_cancels_command(self):
        def broken_callback(text):
            raise RuntimeError("UI disconnected")
        result = tools.run_command(self.spec("import time; print('ready', flush=True); time.sleep(30)"), on_output=broken_callback)
        self.assertEqual(result["status"], "failed")
        self.assertIn("UI disconnected", result["callback_error"])


if __name__ == "__main__":
    unittest.main()
