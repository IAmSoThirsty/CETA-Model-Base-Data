from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ceta_desktop.models import LocalModelClient, ModelError  # noqa: E402
from ceta_desktop.hardware import GIB, HardwareProfile  # noqa: E402


LOCAL_DETAILS = {"details": {"format": "gguf", "parameter_size": "4B", "quantization_level": "Q4_K_M"},
                 "model_info": {"general.architecture": "qwen3"}}
LOCAL_MODEL = {"name": "local:4b", "size": 2_500_000_000}
NATIVE_COMPLETE = b'{"message":{"content":"CETA_READY"},"done":false}\n{"message":{"content":""},"done":true}\n'
OPENAI_COMPLETE = b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'


@contextmanager
def model_service(overrides=None):
    requests = []
    routes = {
        ("GET", "/api/tags"): {"models": [LOCAL_MODEL]},
        ("POST", "/api/show"): LOCAL_DETAILS,
        ("POST", "/api/chat"): NATIVE_COMPLETE,
        ("POST", "/v1/chat/completions"): OPENAI_COMPLETE,
        ("GET", "/api/ps"): lambda _: {"models": [{"name": "local:4b", "size": 3_000_000_000,
                                                   "size_vram": 1_500_000_000, "context_length": 4096}]
                                      if any(request[1] == "/api/chat" for request in requests) else []},
    }
    routes.update(overrides or {})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            payload = json.loads(body) if body else None
            requests.append((self.command, self.path, payload))
            response = routes.get((self.command, self.path), (404, {}))
            if callable(response):
                response = response(payload)
            status, record = response if isinstance(response, tuple) else (200, response)
            encoded = record if isinstance(record, bytes) else json.dumps(record).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = respond
        do_POST = respond

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield LocalModelClient(f"http://127.0.0.1:{server.server_port}/v1"), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


class DesktopModelReadinessTests(unittest.TestCase):
    def setUp(self):
        self.hardware = patch("ceta_desktop.models.inspect_hardware", return_value=HardwareProfile(16 * GIB, 12 * GIB, 8))
        self.hardware.start()
        self.addCleanup(self.hardware.stop)

    def test_model_list_omits_cloud_names_and_remote_aliases(self):
        catalog = {"models": [LOCAL_MODEL, {"name": "model:cloud", "size": 300},
                              {"name": "hidden:latest", "size": 300, "remote_host": "https://example.invalid"}]}
        with model_service({("GET", "/api/tags"): catalog}) as (client, requests):
            self.assertEqual(client.available_models(), ["local:4b"])
            self.assertEqual(client.skipped_models, ["model:cloud", "hidden:latest"])
            self.assertEqual(client.backend, "ollama")
            self.assertEqual([request[1] for request in requests], ["/api/tags", "/api/show"])

    def test_known_cloud_names_cannot_send_or_pull(self):
        with model_service() as (client, requests):
            for model in ("model:cloud", "model:4b-cloud"):
                with self.subTest(model=model):
                    with self.assertRaises(ModelError):
                        list(client.stream(model, [{"role": "user", "content": "private"}]))
                    with self.assertRaises(ModelError):
                        list(client.pull_ollama_model(model))
            self.assertEqual(requests, [])

    def test_remote_metadata_alias_is_rejected_before_chat_text_is_transmitted(self):
        for field in ("remote_model", "remote_host"):
            with self.subTest(field=field), model_service({
                ("POST", "/api/show"): {**LOCAL_DETAILS, field: "upstream"},
            }) as (client, requests):
                with self.assertRaises(ModelError):
                    list(client.stream("local:4b", [{"role": "user", "content": "private conversation"}]))
                self.assertNotIn("private conversation", json.dumps(requests))
                self.assertNotIn("/v1/chat/completions", [request[1] for request in requests])

    def test_missing_weights_or_local_metadata_cannot_send_chat(self):
        for details in ({}, {"details": {"format": "gguf"}}, {"details": {"format": "unknown"}, "model_info": {"x": 1}}):
            with self.subTest(details=details), model_service({("POST", "/api/show"): details}) as (client, requests):
                with self.assertRaises(ModelError):
                    list(client.stream("local:4b", [{"role": "user", "content": "private"}]))
                self.assertFalse(any("chat" in request[1] for request in requests))

    def test_locality_is_rechecked_before_every_chat(self):
        responses = iter([LOCAL_DETAILS, {**LOCAL_DETAILS, "remote_host": "https://example.invalid"}])
        with model_service({("POST", "/api/show"): lambda _: next(responses)}) as (client, requests):
            self.assertEqual("".join(client.stream("local:4b", [{"role": "user", "content": "first"}])), "CETA_READY")
            with self.assertRaises(ModelError):
                list(client.stream("local:4b", [{"role": "user", "content": "second-private"}]))
            self.assertNotIn("second-private", json.dumps(requests))

    def test_generic_openai_endpoint_remains_supported_with_unverified_locality(self):
        with model_service({("GET", "/api/tags"): (404, {}),
                            ("GET", "/v1/models"): {"data": [{"id": "fixture-model"}]}}) as (client, requests):
            self.assertEqual(client.available_models(), ["fixture-model"])
            self.assertEqual(client.model_readiness("fixture-model")["locality"], "unverified")
            messages = [{"role": "user", "content": "fixture"}]
            self.assertEqual("".join(client.stream("fixture-model", messages, max_tokens=64)), "Hello")
            chat = next(request[2] for request in requests if request[1] == "/v1/chat/completions")
            self.assertEqual(chat["messages"], messages)
            self.assertEqual(chat["max_tokens"], 64)
            with self.assertRaisesRegex(ModelError, "unverified"):
                client.probe_local_model("fixture-model")

    def test_metadata_service_failure_does_not_downgrade_to_unverified_chat(self):
        with model_service({("GET", "/api/tags"): (500, {})}) as (client, requests):
            with self.assertRaisesRegex(ModelError, "HTTP 500"):
                list(client.stream("local:4b", [{"role": "user", "content": "private"}]))
            self.assertEqual([request[1] for request in requests], ["/api/tags"])

    def test_recognized_ollama_cannot_downgrade_when_catalog_disappears(self):
        responses = iter([{"models": [LOCAL_MODEL]}, (404, {})])
        with model_service({("GET", "/api/tags"): lambda _: next(responses)}) as (client, requests):
            self.assertEqual(client.model_readiness("local:4b")["locality"], "local")
            with self.assertRaisesRegex(ModelError, "HTTP 404"):
                list(client.stream("local:4b", [{"role": "user", "content": "private"}]))
            self.assertFalse(any("chat" in request[1] for request in requests))

    def test_probe_requires_completed_generation_and_reports_actual_runtime_telemetry(self):
        with model_service() as (client, requests):
            result = client.probe_local_model("local:4b", max_tokens=32, context_length=4096)
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["response"], "CETA_READY")
            self.assertEqual(result["characters"], 10)
            self.assertGreaterEqual(result["elapsed_seconds"], 0)
            self.assertEqual(result["runtime"]["size_vram"], 1_500_000_000)
            self.assertEqual(result["runtime"]["context_length"], 4096)
            self.assertNotIn("tokens_per_second", result)
            request = next(request[2] for request in requests if request[1] == "/api/chat")
            self.assertFalse(request["think"])
            self.assertEqual(request["options"], {"num_predict": 32, "num_ctx": 4096})
            self.assertEqual(len(request["messages"]), 1)

    def test_probe_does_not_verify_truncated_empty_or_malformed_generation(self):
        records = (
            b'not-json\n',
            b'{"message":{"content":"partial"},"done":false}\n',
            b'{"message":{"content":""},"done":true}\n',
            b'{"message":{"content":3},"done":true}\n',
            b'{"message":{"content":"text"},"done":true,"remote_host":"https://example.invalid"}\n',
        )
        for record in records:
            with self.subTest(record=record), model_service({("POST", "/api/chat"): record}) as (client, _):
                with self.assertRaises(ModelError):
                    client.probe_local_model("local:4b")

    def test_probe_reports_missing_telemetry_without_inventing_usage(self):
        replies = iter([{"models": []}, (500, {})])
        with model_service({("GET", "/api/ps"): lambda _: next(replies)}) as (client, _):
            result = client.probe_local_model("local:4b")
            self.assertEqual(result["status"], "verified")
            self.assertIsNone(result["runtime"])
            self.assertIn("HTTP 500", result["telemetry_error"])

    def test_probe_preserves_generation_result_when_telemetry_connection_is_truncated(self):
        import http.client

        with model_service() as (client, _), patch.object(
            client, "running_models", side_effect=[[], http.client.IncompleteRead(b"", 20)],
        ):
            result = client.probe_local_model("local:4b")
            self.assertEqual(result["status"], "verified")
            self.assertIsNone(result["runtime"])
            self.assertIn("IncompleteRead", result["telemetry_error"])

    def test_insufficient_or_unknown_memory_stops_probe_before_generation(self):
        for profile in (HardwareProfile(16 * GIB, GIB, 8), HardwareProfile(None, None, 8)):
            with self.subTest(profile=profile), model_service() as (client, requests), patch(
                "ceta_desktop.models.inspect_hardware", return_value=profile,
            ):
                with self.assertRaises(ModelError):
                    client.probe_local_model("local:4b")
                self.assertNotIn("/api/chat", [request[1] for request in requests])

    def test_another_loaded_model_stops_probe_before_generation(self):
        with model_service({("GET", "/api/ps"): {"models": [{"name": "other:latest"}]}}) as (client, requests):
            with self.assertRaisesRegex(ModelError, "Another model is already loaded"):
                client.probe_local_model("local:4b")
            self.assertNotIn("/api/chat", [request[1] for request in requests])

    def test_concurrent_probe_is_rejected_until_the_active_probe_finishes(self):
        entered, release = threading.Event(), threading.Event()
        results = []

        def blocked_generation(_):
            entered.set()
            release.wait(5)
            return NATIVE_COMPLETE

        with model_service({("POST", "/api/chat"): blocked_generation}) as (client, requests):
            worker = threading.Thread(target=lambda: results.append(client.probe_local_model("local:4b")))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                second = LocalModelClient(f"http://127.0.0.1:{client.port}/v1")
                with self.assertRaisesRegex(ModelError, "already running"):
                    second.probe_local_model("local:4b")
            finally:
                release.set()
                worker.join(5)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "verified")
            self.assertEqual(sum(request[1] == "/api/chat" for request in requests), 1)

    def test_invalid_telemetry_is_rejected(self):
        with model_service({("GET", "/api/ps"): {"models": [{"name": "local:4b", "size_vram": -1}]}}) as (client, _):
            with self.assertRaises(ModelError):
                client.running_models()

    def test_generation_limits_are_validated_before_requests(self):
        with model_service() as (client, requests):
            for limit in (0, -1, True, 4097):
                with self.subTest(limit=limit), self.assertRaises(ModelError):
                    list(client.stream("local:4b", [], max_tokens=limit))
            with self.assertRaises(ModelError):
                client.probe_local_model("local:4b", max_tokens=129)
            with self.assertRaises(ModelError):
                client.probe_local_model("local:4b", context_length=32769)
            self.assertEqual(requests, [])

    def test_normal_chat_also_applies_memory_gate_to_custom_installed_model(self):
        with model_service() as (client, requests), patch(
            "ceta_desktop.models.inspect_hardware", return_value=HardwareProfile(16 * GIB, GIB, 8),
        ):
            with self.assertRaisesRegex(ModelError, "Insufficient"):
                list(client.stream("local:4b", [{"role": "user", "content": "private"}], context_length=4096))
            self.assertNotIn("private", json.dumps(requests))

    def test_resident_model_reuses_allocated_memory_at_the_requested_context(self):
        resident = {"models": [{"name": "local:4b", "size": 3_000_000_000, "size_vram": 0, "context_length": 4096}]}
        with model_service({("GET", "/api/ps"): resident}) as (client, _), patch(
            "ceta_desktop.models.inspect_hardware", return_value=HardwareProfile(16 * GIB, 3 * GIB // 4, 8),
        ):
            self.assertEqual("".join(client.stream("local:4b", [], context_length=4096)), "CETA_READY")
            self.assertEqual(client.last_memory_assessment["mode"], "resident")
            self.assertTrue(client.last_memory_assessment["preloaded"])

    def test_resident_model_still_requires_free_ram_headroom(self):
        resident = {"models": [{"name": "local:4b", "size": 3_000_000_000, "context_length": 4096}]}
        with model_service({("GET", "/api/ps"): resident}) as (client, requests), patch(
            "ceta_desktop.models.inspect_hardware", return_value=HardwareProfile(16 * GIB, GIB // 4, 8),
        ):
            with self.assertRaisesRegex(ModelError, "headroom"):
                list(client.stream("local:4b", [], context_length=4096))
            self.assertNotIn("/api/chat", [request[1] for request in requests])

    def test_larger_context_cannot_reuse_smaller_resident_allocation(self):
        resident = {"models": [{"name": "local:4b", "size": 3_000_000_000, "context_length": 2048}]}
        with model_service({("GET", "/api/ps"): resident}) as (client, _), patch(
            "ceta_desktop.models.inspect_hardware", return_value=HardwareProfile(16 * GIB, GIB, 8),
        ):
            with self.assertRaisesRegex(ModelError, "Insufficient"):
                list(client.stream("local:4b", [], context_length=4096))

    def test_unestimated_context_is_rejected_before_generation(self):
        with model_service() as (client, requests):
            with self.assertRaisesRegex(ModelError, "4096"):
                client.probe_local_model("local:4b", context_length=8192)
            self.assertNotIn("/api/chat", [request[1] for request in requests])

    def test_context_budget_is_sent_to_native_ollama_chat(self):
        with model_service() as (client, requests):
            messages = [{"role": "user", "content": "fixture"}]
            self.assertEqual("".join(client.stream("local:4b", messages, max_tokens=32, context_length=4096)), "CETA_READY")
            request = next(request[2] for request in requests if request[1] == "/api/chat")
            self.assertEqual(request["messages"], messages)
            self.assertEqual(request["options"], {"num_predict": 32, "num_ctx": 4096})

    def test_gpt_oss_alias_uses_metadata_thinking_level_for_chat_and_probe(self):
        metadata_cases = (
            {**LOCAL_DETAILS, "model_info": {"general.architecture": "gptoss"}},
            {**LOCAL_DETAILS, "details": {**LOCAL_DETAILS["details"], "family": "gpt-oss"}},
        )
        native = (b'{"message":{"thinking":"internal fixture trace","content":""},"done":false}\n'
                  b'{"message":{"content":"CETA_READY"},"done":true}\n')
        for metadata in metadata_cases:
            with self.subTest(metadata=metadata), model_service({
                ("POST", "/api/show"): metadata, ("POST", "/api/chat"): native,
            }) as (client, requests):
                # This alias contains no GPT-OSS name marker.
                response = "".join(client.stream("local:4b", [{"role": "user", "content": "fixture"}]))
                self.assertEqual(response, "CETA_READY")
                self.assertEqual(client.probe_local_model("local:4b")["response"], "CETA_READY")
                chats = [request[2] for request in requests if request[1] == "/api/chat"]
                self.assertEqual([chat["think"] for chat in chats], ["low", "low"])
                self.assertNotIn("/no_think", chats[-1]["messages"][0]["content"])

    def test_thinking_only_native_completion_does_not_complete_chat_or_expose_trace(self):
        native = (b'{"message":{"thinking":"internal fixture trace","content":""},"done":false}\n'
                  b'{"message":{"content":""},"done":true}\n')
        with model_service({("POST", "/api/chat"): native}) as (client, _):
            visible = []
            with self.assertRaisesRegex(ModelError, "without generating visible text"):
                for content in client.stream("local:4b", [{"role": "user", "content": "fixture"}]):
                    visible.append(content)
            self.assertEqual(visible, [])


if __name__ == "__main__":
    unittest.main()
