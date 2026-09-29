from __future__ import annotations

import copy
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from ceta_desktop.models import LocalModelClient, ModelError, ModelDeadlineError
from ceta_desktop.model_installation import bundled_models, model_name
from ceta_desktop.request_tokens import Cancellation, ManagedTokenCounter, check_runner, owned_tokenizer, text_hash
from runtime.generation_plan import assemble_request
from runtime.tasks import _TaskCancellation


class TokenAllocationTests(unittest.TestCase):
    def test_slow_authority_checks_allow_progress_and_still_observe_revocation(self):
        clock = [1.0]
        runtime = Mock()
        def access(*args):
            clock[0] += .2
        runtime._access.side_effect = access
        supplied = threading.Event()
        cancellation = _TaskCancellation(runtime, "task", supplied)
        with patch("runtime.tasks.time.monotonic", side_effect=lambda: clock[0]):
            for _ in range(1000):
                self.assertFalse(cancellation.is_set())
            self.assertEqual(runtime._access.call_count, 1)
            supplied.set()
            self.assertTrue(cancellation.is_set())
            supplied.clear()
            clock[0] += .101
            runtime._access.side_effect = ValueError("revoked")
            self.assertTrue(cancellation.is_set())
            self.assertEqual(runtime._access.call_count, 2)

    def plan(self, count, text="hello"):
        return assemble_request({"instructions": [], "files": []}, [{"role": "user", "content": text}],
            context_length=512, max_tokens=128,
            token_counter=lambda messages: {"input_tokens": count, "verified": True, "method": "fixture"})

    def test_exact_count_uses_rendered_tokens_including_unicode_instead_of_bytes(self):
        plan = self.plan(383, "中文🙂" * 1000)
        self.assertTrue(plan["budget"]["verified"])
        self.assertEqual(plan["budget"]["input_tokens"] + 128 + 1, 512)
        with self.assertRaisesRegex(ValueError, "mandatory instructions"):
            self.plan(384)

    def test_invalid_counts_do_not_fall_back_to_estimates(self):
        for value in (0, -1, True, 1.5, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "positive count"):
                self.plan(value)

    def test_allocator_counts_sources_and_pairs_then_binds_final_payload(self):
        calls = []
        def counter(messages):
            calls.append(copy.deepcopy(messages))
            return {"input_tokens": 600 if any("too large" in m["content"] for m in messages) else 180,
                    "verified": True, "method": "fixture", "messages_sha256": text_hash(json.dumps(messages, sort_keys=True))}
        context = {"instructions": [], "files": [{"path": "large.txt", "sha256": "a" * 64, "text": "too large"}]}
        plan = assemble_request(context, [{"role": "user", "content": "too large"},
            {"role": "assistant", "content": "old reply"}, {"role": "user", "content": "now"}],
            context_length=512, max_tokens=128, token_counter=counter)
        self.assertEqual(len(calls), 3)
        self.assertEqual(plan["selected_paths"], [])
        self.assertEqual(plan["budget"]["retained_history_pairs"], 0)
        self.assertEqual(plan["budget"]["tokenization"]["messages_sha256"], text_hash(json.dumps(plan["messages"], sort_keys=True)))


class ManagedCounterTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.client = LocalModelClient("http://127.0.0.1:11435/v1", coordination_directory=self.directory / "coordination")
        self.client.managed_directory = self.directory
        self.client.expected_job = "Local\\CETA-runtime-" + "a" * 32
        self.entry = bundled_models()["entries"][0]
        self.model = model_name(self.entry)
        self.profile = {"context_length": 4096, "max_tokens": 128,
                        "observed": {"digest": self.entry["sha256"], "backend": "ollama"}}
        installation = Mock()
        installation.destination = self.directory / "runtime"
        self.assets = self.client.managed_assets = Mock(closed=False, job_name=self.client.expected_job,
            session_id="fixture-session", installation=installation, assert_runtime=Mock())
        self.assets.assert_runtime.return_value = {"version": "0.34.3", "archive_sha256": "b" * 64}
        models = self.enterContext(patch("ceta_desktop.request_tokens.ManagedModels")).return_value
        models.blobs = self.directory / "models/blobs"
        self.metadata = self.enterContext(patch("ceta_desktop.request_tokens.gguf_metadata",
            return_value={"tokenizer.ggml.model": "gpt2", "tokenizer.ggml.add_bos_token": False}))
        self.enterContext(patch.object(self.client, "model_readiness", return_value={}))
        self.enterContext(patch.object(self.client, "_request_profile", return_value=self.profile["observed"]))
        self.enterContext(patch.object(self.client, "_preflight_ollama", return_value={}))
        self.render = {"model": self.model, "_debug_info": {"rendered_template": "<|im_start|>user\nhello"}}
        self.payloads = []
        def request(method, path, payload=None, **kwargs):
            if path == "/api/version":
                return {"version": "0.34.3"}
            self.payloads.append(payload)
            self.client._runtime_lease.begin_dispatch(operation="template-render")
            return self.render
        self.enterContext(patch.object(self.client, "_json_request", side_effect=request))
        self.enterContext(patch("ceta_desktop.runtime_coordination.endpoint_owner", return_value=None))
        self.owner = {"pid": 1234, "created_100ns": 42}
        self.listener = self.enterContext(patch("ceta_desktop.request_tokens.owned_tokenizer",
            return_value={"host": "127.0.0.1", "port": 59001, "owner": self.owner}))
        self.runner = self.enterContext(patch("ceta_desktop.request_tokens.check_runner")).return_value
        self.runner._json_request.return_value = {"tokens": [1, 2, 3]}

    def counter(self, cancelled=None):
        return ManagedTokenCounter(self.client, self.model, self.profile, cancelled)

    def test_missing_closed_or_replaced_asset_session_cannot_prepare(self):
        for assets in (None, Mock(closed=True), Mock(closed=False, job_name="different-job")):
            self.client.managed_assets = assets
            with self.subTest(assets=assets), self.assertRaisesRegex(ModelError, "protected asset session"):
                self.counter()
        self.assertEqual(self.payloads, [])

    def test_dispatch_rechecks_asset_session_before_contacting_worker(self):
        messages = [{"role": "user", "content": "hello"}]
        self.client.expected_tokenization = self.counter()(messages)
        self.assertEqual(self.client.expected_tokenization["binding"]["asset_session"], "fixture-session")
        with patch("ceta_desktop.request_tokens.check_runner") as runner:
            self.client.managed_assets = None
            with self.assertRaisesRegex(ModelError, "asset session changed"):
                self.client._check_tokenization_binding(messages, 4096, 128)
            self.client.managed_assets = self.assets
            self.assets.assert_runtime.side_effect = RuntimeError("protection ended")
            with self.assertRaisesRegex(RuntimeError, "protection ended"):
                self.client._check_tokenization_binding(messages, 4096, 128)
            runner.assert_not_called()

    def test_asset_release_during_allocation_prevents_render_dispatch(self):
        counter = self.counter()
        self.assets.assert_runtime.side_effect = RuntimeError("protection ended")
        with self.assertRaisesRegex(RuntimeError, "protection ended"):
            counter([])
        self.assertEqual(self.payloads, [])

    def test_render_and_tokenize_share_exact_payload_and_special_token_settings(self):
        result = self.counter()([{"role": "user", "content": "hello"}])
        self.assertEqual(result["input_tokens"], 3)
        self.assertTrue(result["verified"])
        payload = self.payloads[0]
        self.assertTrue(payload["_debug_render_only"])
        self.assertFalse(payload["truncate"])
        self.assertFalse(payload["shift"])
        self.runner._json_request.assert_called_once_with("POST", "/tokenize",
            {"content": self.render["_debug_info"]["rendered_template"], "add_special": True, "parse_special": True})
        self.assertEqual(self.client.backend_state["state"], "idle")

    def test_bad_render_retains_uncertain_state_without_tokenization(self):
        self.render["_debug_info"]["image_count"] = 1
        with self.assertRaisesRegex(ModelError, "text-only"):
            self.counter()([])
        self.runner._json_request.assert_not_called()
        self.assertEqual(self.client.backend_state["state"], "uncertain")

    def test_bad_tokens_fail_without_claiming_count(self):
        for tokens in ([], [True], [-1], ["1"], None):
            self.runner._json_request.return_value = {"tokens": tokens}
            with self.subTest(tokens=tokens), self.assertRaisesRegex(ModelError, "invalid token"):
                self.counter()([])

    def test_changed_worker_is_rejected_during_allocation(self):
        counter = self.counter()
        counter([])
        self.listener.return_value = {"host": "127.0.0.1", "port": 59002, "owner": {**self.owner, "pid": 1235}}
        with self.assertRaisesRegex(ModelError, "worker changed"):
            counter([])

    def test_cancelled_count_never_renders_and_restores_event(self):
        cancelled = threading.Event()
        counter = self.counter(cancelled)
        original = self.client.cancelled
        cancelled.set()
        with self.assertRaisesRegex(ModelError, "cancelled"):
            counter([])
        self.assertEqual(self.payloads, [])
        self.assertIs(self.client.cancelled, original)

    def test_busy_client_never_replaces_the_inflight_cancellation_event(self):
        counter = self.counter()
        original = self.client.cancelled
        @contextmanager
        def busy():
            self.assertIs(self.client.cancelled, original)
            raise ModelError("already handling a request")
            yield
        with patch.object(self.client, "_generation_session", busy), self.assertRaisesRegex(ModelError, "already handling"):
            counter([])
        self.assertIs(self.client.cancelled, original)

    def test_preflight_failure_does_not_reuse_old_generation_metrics(self):
        self.client.last_generation_metrics = {"prompt_eval_count": 123}
        with patch.object(self.client, "model_readiness", side_effect=ModelError("failed metadata")), \
                self.assertRaisesRegex(ModelError, "failed metadata"):
            list(self.client.stream(self.model, []))
        self.assertIsNone(self.client.last_generation_metrics)

    def test_unknown_special_token_behavior_and_changed_digest_reject(self):
        self.metadata.return_value["tokenizer.ggml.add_bos_token"] = True
        with self.assertRaisesRegex(ModelError, "special-token"):
            self.counter()
        self.profile["observed"]["digest"] = "c" * 64
        with self.assertRaisesRegex(ModelError, "pinned model digest"):
            self.counter()


class WorkerBindingTests(unittest.TestCase):
    def test_only_the_exact_owned_image_is_selected_without_probing_other_services(self):
        with patch("ceta_desktop.request_tokens.loopback_listeners", return_value=[
                {"host": "127.0.0.1", "port": 50 + pid, "pid": pid} for pid in (1, 2, 3)]), \
             patch("ceta_desktop.request_tokens.process_identity", side_effect=lambda pid: {"pid": pid}), \
             patch("ceta_desktop.request_tokens.inspect_job", side_effect=lambda job, owner: {"owner_contained": owner["pid"] != 1}), \
             patch("ceta_desktop.request_tokens.process_image", side_effect=lambda owner: "runner.exe" if owner["pid"] == 3 else "other.exe"):
            self.assertEqual(owned_tokenizer("job", "runner.exe")["owner"], {"pid": 3})
            with self.assertRaisesRegex(ModelError, "Exactly one"):
                owned_tokenizer("job", "missing.exe")

    def test_props_reject_wrong_model_context_or_concurrency(self):
        binding = {"model_path": "model.gguf", "context_length": 4096}
        correct = {"model_path": "model.gguf", "default_generation_settings": {"n_ctx": 4096}, "total_slots": 1}
        with patch("ceta_desktop.request_tokens.runner_client") as connect:
            connect.return_value._json_request.return_value = correct
            check_runner(Mock(), binding)
            for change in ({"model_path": "other.gguf"}, {"default_generation_settings": {"n_ctx": 2048}}, {"total_slots": 2}):
                connect.return_value._json_request.return_value = {**correct, **change}
                with self.assertRaisesRegex(ModelError, "configuration changed"):
                    check_runner(Mock(), binding)

    def test_expired_count_raises_deadline_without_resetting_cancellation(self):
        event = threading.Event()
        with self.assertRaises(ModelDeadlineError):
            Cancellation(event, None, time.monotonic() - 1).is_set()
        self.assertFalse(event.is_set())

    def test_changed_messages_or_worker_fail_before_completion_dispatch(self):
        client = LocalModelClient("http://127.0.0.1:11435/v1")
        messages = [{"role": "user", "content": "hello"}]
        client.expected_tokenization = {"messages_sha256": text_hash(json.dumps(messages, sort_keys=True)),
            "input_tokens": 100, "binding": {"context_length": 4096}}
        with patch("ceta_desktop.request_tokens.check_runner", side_effect=ModelError("worker changed")):
            with self.assertRaisesRegex(ModelError, "worker changed"):
                client._check_tokenization_binding(messages, 4096, 128)
            with self.assertRaisesRegex(ModelError, "token budget"):
                client._check_tokenization_binding([], 4096, 128)
            with self.assertRaisesRegex(ModelError, "token budget"):
                client._check_tokenization_binding(messages, 512, 128)

    def test_reported_inference_count_must_match_prepared_count(self):
        for observed in (5, 6, None):
            client = LocalModelClient("http://127.0.0.1:11435/v1")
            client.expected_tokenization = {"input_tokens": 5}
            response = io.BytesIO((json.dumps({"done": True, "message": {"content": "answer"},
                "prompt_eval_count": observed}) + "\n").encode())
            with patch.object(client, "_request", return_value=response):
                stream = client._stream_ollama("model", [], max_tokens=32, context_length=4096)
                if observed == 5:
                    self.assertEqual("".join(stream), "answer")
                else:
                    with self.assertRaisesRegex(ModelError, "differs"):
                        list(stream)
