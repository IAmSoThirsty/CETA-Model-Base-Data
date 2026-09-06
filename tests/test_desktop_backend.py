from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ceta_desktop.models import LocalModelClient, ModelError, ModelPacks, local_endpoint
from ceta_desktop.storage import Store, application_directory
from ceta_desktop.workspace import Workspace, WorkspaceError


class DesktopStorageTests(unittest.TestCase):
    def test_new_application_data_uses_ceta_without_creating_a_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LOCALAPPDATA": directory, "XDG_DATA_HOME": directory}):
                self.assertEqual(application_directory(), Path(directory) / "CETA")
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_pre_release_conversations_remain_accessible_without_moving_data(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "ThirstyAI"
            store = Store(legacy)
            identifier = store.new_conversation("Retained conversation")
            store.add_message(identifier, "user", "Keep this conversation")
            store.close()
            with patch.dict(os.environ, {"LOCALAPPDATA": directory, "XDG_DATA_HOME": directory}):
                selected = application_directory()
                self.assertEqual(selected, legacy)
                reopened = Store(selected)
                try:
                    self.assertEqual(reopened.messages(identifier)[0]["content"], "Keep this conversation")
                finally:
                    reopened.close()
            self.assertFalse((Path(directory) / "CETA").exists())
            self.assertTrue((legacy / "desktop.sqlite3").is_file())

    def test_existing_ceta_folder_does_not_merge_pre_release_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = Store(root / "ThirstyAI")
            legacy.new_conversation("Legacy only")
            legacy.close()
            before = (root / "ThirstyAI" / "desktop.sqlite3").read_bytes()
            current = root / "CETA"
            current.mkdir()
            with patch.dict(os.environ, {"LOCALAPPDATA": directory, "XDG_DATA_HOME": directory}):
                self.assertEqual(application_directory(), current)
                store = Store(application_directory())
                try:
                    self.assertEqual(store.conversations(), [])
                finally:
                    store.close()
            self.assertEqual((root / "ThirstyAI" / "desktop.sqlite3").read_bytes(), before)

    def test_partial_response_is_recovered_as_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            conversation = store.new_conversation()
            response = store.add_message(conversation, "assistant", "", "generating")
            store.update_response(response, "Checkpoint before interruption", "generating")
            store.close()
            reopened = Store(Path(directory))
            self.assertEqual(reopened.messages(conversation), [{"role": "assistant", "content": "Checkpoint before interruption", "status": "interrupted"}])
            with self.assertRaises(ValueError):
                reopened.update_response(response, "must not replace", "complete")
            reopened.close()

    def test_conversation_survives_restart_and_incomplete_work_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            conversation = store.new_conversation()
            store.add_message(conversation, "user", "Plan this task")
            store.add_message(conversation, "assistant", "Partial response", "cancelled")
            workload = store.start_workload(Path(directory), "command")
            store.close()
            reopened = Store(Path(directory))
            self.assertEqual(reopened.messages(conversation)[1]["status"], "cancelled")
            self.assertEqual(reopened.conversations()[0]["title"], "Plan this task")
            self.assertEqual(reopened.db.execute("SELECT status FROM workloads WHERE id=?", (workload,)).fetchone()[0], "interrupted")
            reopened.close()

    def test_workspace_preserves_bom_line_endings_and_detects_external_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "code.py"
            path.write_bytes(b"\xef\xbb\xbffirst\r\nsecond\r\n")
            workspace = Workspace(root)
            document = workspace.open(path)
            workspace.save(document, "first\nthird\n")
            self.assertEqual(path.read_bytes(), b"\xef\xbb\xbffirst\r\nthird\r\n")
            path.write_text("external change")
            with self.assertRaises(WorkspaceError):
                workspace.save(document, "my edit")
            self.assertEqual(path.read_text(), "external change")

    def test_workspace_rejects_escape_binary_git_and_mixed_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "workspace"
            root.mkdir()
            workspace = Workspace(root)
            (parent / "private").write_text("private")
            (root / "binary").write_bytes(b"\x00\x01")
            (root / "mixed").write_bytes(b"a\r\nb\nc\r\n")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("git")
            for name in ("../private", "binary", "mixed", ".git/config"):
                with self.subTest(name=name), self.assertRaises(WorkspaceError):
                    workspace.open(Path(name))

    def test_model_install_hashes_content_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "example.gguf"
            content = b"GGUF" + (3).to_bytes(4, "little") + bytes(16) + b"fixture"
            source.write_bytes(content)
            packs = ModelPacks(root / "application")
            result = packs.install(source)
            self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(Path(result["path"]).read_bytes(), content)
            self.assertEqual(source.read_bytes(), content)
            self.assertEqual(len(packs.installed()), 1)
            self.assertEqual(packs.install(source)["sha256"], result["sha256"])
            self.assertEqual(len(packs.installed()), 1)
            installed_path = Path(result["path"])
            installed_path.write_bytes(content[:-1] + b"X")
            with self.assertRaises(ModelError):
                packs.verify_installed(result["sha256"])

    def test_model_pack_pull_reports_success_only_after_service_confirmation(self):
        from unittest.mock import patch
        from io import BytesIO
        client = LocalModelClient("http://127.0.0.1:11434/v1")
        with patch.object(client, "_request", return_value=BytesIO(b'{"status":"pulling","total":10,"completed":5}\n{"status":"success"}\n')):
            self.assertEqual(list(client.pull_ollama_model("example:small")), ["pulling · 50%", "success"])
        with patch.object(client, "_request", return_value=BytesIO(b'{"status":"pulling"}\n')):
            with self.assertRaises(ModelError):
                list(client.pull_ollama_model("example:small"))
        with self.assertRaises(ModelError):
            list(client.pull_ollama_model("https://untrusted.example/model"))

    def test_model_install_rejects_executable_and_cancelled_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bad.gguf"
            source.write_bytes(b"MZ" + bytes(50))
            packs = ModelPacks(root / "application")
            with self.assertRaises(ModelError):
                packs.install(source)
            source.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(40))
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(ModelError):
                packs.install(source, cancelled)
            self.assertEqual(packs.installed(), [])
            self.assertEqual(list(packs.directory.glob(".install-*")), [])

    def test_invalid_pack_does_not_hide_other_models_or_change_its_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "valid.gguf"
            source.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(30))
            packs = ModelPacks(root / "application")
            valid = packs.install(source)
            broken = packs.directory / ("f" * 64)
            broken.mkdir()
            (broken / "model.gguf").write_bytes(source.read_bytes())
            manifest = broken / "pack.json"
            for malformed in ("null", "{}", '{"schema_version":1}', "{broken json", '"unexpected string"'):
                manifest.write_text(malformed)
                self.assertEqual([record["sha256"] for record in packs.installed()], [valid["sha256"]])
                self.assertEqual(len(packs.problems), 1)
                self.assertEqual(manifest.read_text(), malformed)
                with self.assertRaises(ValueError):
                    packs.verify_installed("f" * 64)

    def test_editor_preserves_cr_only_files_and_refuses_oversized_saves(self):
        from ceta_desktop.workspace import MAX_EDITOR_BYTES
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "old.txt"
            path.write_bytes(b"one\rtwo\r")
            workspace = Workspace(root)
            document = workspace.open(path)
            self.assertEqual(document.text, "one\ntwo\n")
            workspace.save(document, "one\nthree\n")
            self.assertEqual(path.read_bytes(), b"one\rthree\r")
            with self.assertRaises(WorkspaceError):
                workspace.save(document, "x" * (MAX_EDITOR_BYTES + 1))
            self.assertEqual(path.read_bytes(), b"one\rthree\r")
            path.write_bytes(b"one\rtwo\n")
            with self.assertRaises(WorkspaceError):
                workspace.open(path)

    def test_remote_model_endpoints_are_rejected(self):
        for value in ("https://example.com/v1", "http://127.0.0.1.evil.test/v1",
                      "http://user:password@localhost/v1", "http://localhost/v1?redirect=remote"):
            with self.subTest(value=value), self.assertRaises(ModelError):
                local_endpoint(value)


class DesktopTransportTests(unittest.TestCase):
    def test_cancel_interrupts_a_stalled_http10_response(self):
        started, release, completed = threading.Event(), threading.Event(), threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.flush()
                started.set()
                release.wait(5)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        client = LocalModelClient(f"http://127.0.0.1:{server.server_port}/v1")

        def receive():
            try:
                list(client.stream("fixture-model", [{"role": "user", "content": "test"}]))
            except (ModelError, OSError):
                pass
            finally:
                completed.set()

        worker = threading.Thread(target=receive, daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(3))
            client.cancel()
            self.assertTrue(completed.wait(2), "Cancellation did not interrupt the pending response read")
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            worker.join(3)
            server_thread.join(3)

    def test_local_model_list_and_stream(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"fixture-model"}]}')

            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = LocalModelClient(f"http://127.0.0.1:{server.server_port}/v1")
            self.assertEqual(client.available_models(), ["fixture-model"])
            messages = [{"role": "user", "content": "Hi"}]
            self.assertEqual("".join(client.stream("fixture-model", messages)), "Hello")
            self.assertEqual(captured[0]["messages"], messages)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
