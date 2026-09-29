"""Exact text counts for CETA's pinned Windows Ollama/Qwen3 path.

Rendering may load the model. It therefore uses memory admission and the same
durable runtime lease as inference. Tokenization never probes unrelated services.
Counts are bound to the observed worker and its protected asset session. Model
quality, GPU support and OS network isolation require separate qualification.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time

from .backends import gguf_metadata
from .model_installation import ManagedModels, bundled_models, model_layers, model_name
from .models import LocalModelClient, ModelDeadlineError, ModelError
from .runtime_coordination import loopback_listeners, process_identity
from .windows_job import inspect_job, process_image
from .request_control import checkpoint, deadline_limit


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Cancellation:
    def __init__(self, event, additional, deadline):
        self.event, self.additional, self.deadline = event, additional, deadline

    def is_set(self):
        if time.monotonic() >= self.deadline:
            raise ModelDeadlineError("Request token preparation exceeded its deadline; your draft is retained.")
        return self.event.is_set() or (self.additional is not None and self.additional.is_set())

    def set(self):
        self.event.set()

    def wait(self, seconds):
        return self.is_set() or self.event.wait(min(seconds, .05)) or self.is_set()


def owned_tokenizer(job, executable, cancelled=None):
    matches = []
    for listener in loopback_listeners():
        if cancelled is not None and cancelled.is_set():
            raise ModelError("Tokenizer discovery cancelled; your draft is retained.")
        try:
            owner = process_identity(listener["pid"])
            if (owner and inspect_job(job, owner).get("owner_contained") and
                    Path(process_image(owner)) == Path(executable)):
                matches.append({"host": listener["host"], "port": listener["port"], "owner": owner})
        except (OSError, ValueError):
            continue  # A disappearing/uninspectable process is never a candidate.
    if len(matches) != 1:
        raise ModelError("Exactly one owned model tokenizer must be observable; recheck the managed runtime.")
    return matches[0]


def runner_client(client, binding):
    if client.expected_job != binding["job"]:
        raise ModelError("The tokenizer's owned runtime changed after preparation.")
    runner = LocalModelClient(f"http://127.0.0.1:{binding['runner']['port']}")
    runner.expected_job = binding["job"]
    runner.expected_owner = binding["runner"]["owner"]
    runner.cancelled, runner.deadline = client.cancelled, client.deadline
    if Path(process_image(runner.expected_owner)) != Path(binding["executable"]):
        raise ModelError("The tokenizer executable changed after preparation.")
    return runner


def check_runner(client, binding):
    runner = runner_client(client, binding)
    props = runner._json_request("GET", "/props")
    settings = props.get("default_generation_settings", {})
    if (not isinstance(props.get("model_path"), str) or
            Path(props["model_path"]) != Path(binding["model_path"]) or
            not isinstance(settings, dict) or settings.get("n_ctx") != binding["context_length"] or
            props.get("total_slots") != 1):
        raise ModelError("The tokenizer model, context or slot configuration changed; prepare again.")
    return runner


class ManagedTokenCounter:
    def __init__(self, client, model, profile, cancelled=None):
        self.client, self.model, self.profile = client, model, profile
        self.deadline = deadline_limit(time.monotonic() + 90)
        checkpoint()
        self.cancellation = Cancellation(client.cancelled, cancelled, self.deadline)
        entries = bundled_models()["entries"]
        entry = next((entry for entry in entries if model_name(entry) == model), None)
        if not entry or profile["observed"].get("digest") != entry["sha256"]:
            raise ModelError("Exact managed token counting requires the selected pinned model digest.")
        self.entry = entry
        assets = client.managed_assets
        if assets is None or assets.closed or assets.job_name != client.expected_job:
            raise ModelError("The managed runtime has no live protected asset session. Restart it before preparing a request.")
        self.assets = assets
        runtime = assets.installation
        self.installation = assets.assert_runtime()
        if self.installation["version"] != "0.34.3" or entry["runtime_version"] != "0.34.3":
            raise ModelError("This runtime version has no qualified template/tokenizer contract.")
        models = ManagedModels(client.managed_directory)
        assets.protect_model(models, entry["id"], cancelled=self.cancellation)
        weights = [row for row in model_layers(entry) if row["mediaType"] == "application/vnd.ollama.image.model"]
        if len(weights) != 1:
            raise ModelError("Exact text counting requires one pinned GGUF model.")
        path = models.blobs / weights[0]["digest"].replace(":", "-")
        metadata = gguf_metadata(path, self.cancellation, include_tokenizer=True)
        if (metadata.get("tokenizer.ggml.model") != "gpt2" or
                metadata.get("tokenizer.ggml.add_bos_token") is not False or
                metadata.get("tokenizer.ggml.add_eos_token", False) is not False):
            raise ModelError("This tokenizer's special-token behavior is not qualified for exact counting.")
        self.binding = {"job": client.expected_job, "executable": str(runtime.destination / "lib/ollama/llama-server.exe"),
                        "asset_session": assets.session_id,
                        "model_path": str(path), "model_digest": entry["sha256"],
                        "runtime_archive_sha256": self.installation["archive_sha256"],
                        "context_length": profile["context_length"]}
        self.calls = 0

    @contextmanager
    def operation(self):
        with self.client._generation_session(), self.client._deadline_scope(max(.001, self.deadline - time.monotonic())):
            original = self.client.cancelled
            self.client.cancelled = self.cancellation
            try:
                yield
            finally:
                self.client.cancelled = original

    def __call__(self, messages):
        self.calls += 1
        if self.calls > 128:
            raise ModelError("Too many request allocation candidates; shorten the conversation. Your draft is retained.")
        if self.cancellation.is_set():
            raise ModelError("Request preparation cancelled; your draft is retained.")
        client = self.client
        with self.operation():
            if client.managed_assets is not self.assets or self.assets.job_name != client.expected_job:
                raise ModelError("The protected asset session changed during preparation.")
            self.assets.assert_runtime()
            readiness = client.model_readiness(self.model)
            if client._request_profile(readiness) != self.profile["observed"]:
                raise ModelError("The model changed during token preparation.")
            if client._json_request("GET", "/api/version", root=True).get("version") != "0.34.3":
                raise ModelError("The running template renderer has an unsupported version.")
            client.last_memory_assessment = client._preflight_ollama(readiness, self.profile["context_length"])
            payload = client.generation_payload(self.model, messages, max_tokens=self.profile["max_tokens"],
                context_length=self.profile["context_length"], profile=self.profile["observed"])["body"]
            payload.update(stream=False, _debug_render_only=True)
            response = client._json_request("POST", "/api/chat", payload, root=True)
            debug = response.get("_debug_info", {})
            prompt = debug.get("rendered_template") if isinstance(debug, dict) else None
            if (response.get("model") != self.model or not isinstance(prompt, str) or not prompt or
                    type(debug.get("image_count", 0)) is not int or debug.get("image_count", 0) != 0 or
                    response.get("remote_host") or response.get("remote_model")):
                raise ModelError("The runtime did not return a valid text-only rendered template.")
            # The pinned render-only handler returns after rendering, without
            # dispatching completion. Failed/interrupted renders remain uncertain.
            client._runtime_lease.observe_terminal()
            observed = owned_tokenizer(client.expected_job, self.binding["executable"], self.cancellation)
            if "runner" in self.binding and self.binding["runner"] != observed:
                raise ModelError("The tokenizer worker changed during request allocation.")
            self.binding["runner"] = observed
            runner = check_runner(client, self.binding)
            record = runner._json_request("POST", "/tokenize", {"content": prompt, "add_special": True, "parse_special": True})
            tokens = record.get("tokens")
            if (not isinstance(tokens, list) or not tokens or len(tokens) > 512000 or
                    any(type(token) is not int or token < 0 for token in tokens)):
                raise ModelError("The model tokenizer returned invalid token IDs.")
            check_runner(client, self.binding)
            if client._request_profile(client.model_readiness(self.model)) != self.profile["observed"]:
                raise ModelError("The model changed after tokenization.")
            return {"input_tokens": len(tokens), "verified": True, "method": "owned-ollama-render-llama-tokenize-v1",
                    "rendered_sha256": text_hash(prompt), "messages_sha256": text_hash(json.dumps(messages, sort_keys=True)),
                    "binding": dict(self.binding),
                    "scope": "Exact text count for this owned worker and protected asset session; capability qualification remains separate."}
