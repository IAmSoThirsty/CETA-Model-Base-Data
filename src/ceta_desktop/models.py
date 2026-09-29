from __future__ import annotations

import hashlib
from contextlib import contextmanager
import errno
import http.client
import json
import os
import re
import select
from pathlib import Path
import shutil
import socket
import stat
import threading
import time
from urllib.parse import urlsplit
import uuid

from .hardware import GIB, inspect_hardware
from .backends import BackendError, model_memory, ram_budget
from .runtime_coordination import RuntimeCoordinationError, RuntimeLease, connection_owner
from .request_control import ModelError, ModelDeadlineError, checkpoint, deadline_limit

MAX_RESPONSE = 2 * 1024 * 1024


class _ModelHTTPError(ModelError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"The local model service returned HTTP {status}.")


def _cloud_model(name: str) -> bool:
    tag = name.rsplit(":", 1)[-1].lower()
    return tag == "cloud" or tag.endswith("-cloud")


def _model_identity(name: str) -> str:
    return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"


class ModelSocket(socket.socket):
    """Poll cancellation inside reads, before SocketIO can poison its buffer.

    Closing a buffered HTTP response from another thread does not reliably wake
    Windows socket waits. Only the worker owns/closes this socket.
    """

    def recv_into(self, buffer, nbytes=0, flags=0):
        deadline = min(time.monotonic() + 120, getattr(self, "deadline", float("inf")))
        while not self.cancelled.is_set():
            checkpoint()
            if time.monotonic() >= deadline:
                raise ModelDeadlineError("The local model request exceeded its deadline.")
            try:
                return super().recv_into(buffer, nbytes, flags)
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise ModelDeadlineError("The local model response exceeded its remaining time limit.")
        raise ModelError("The model request was cancelled.")

    def sendall(self, data, flags=0):
        remaining = memoryview(data)
        while remaining:
            checkpoint()
            if self.cancelled.is_set():
                raise ModelError("The model request was cancelled.")
            if time.monotonic() >= self.deadline:
                raise ModelDeadlineError("The local model request exceeded its deadline.")
            try:
                count = self.send(remaining[:65536], flags)
            except TimeoutError:
                continue
            if not count:
                raise ModelError("The model connection closed during transmission.")
            remaining = remaining[count:]


def local_endpoint(value: str) -> tuple[str, int, str]:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ModelError("Use a local model endpoint, such as http://127.0.0.1:11434/v1.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelError("The local endpoint cannot contain credentials, a query, or a fragment.")
    try:
        port = parsed.port if parsed.port is not None else 80
    except ValueError as exc:
        raise ModelError("Invalid local model port.") from exc
    if not 1 <= port <= 65535:
        raise ModelError("Invalid local model port.")
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    return host, port, parsed.path.rstrip("/")


class LocalModelClient:
    """OpenAI-compatible transport restricted to loopback; no proxy or redirects."""

    def __init__(self, endpoint: str, *, coordination_directory=None):
        self.host, self.port, self.prefix = local_endpoint(endpoint)
        self.connection: http.client.HTTPConnection | None = None
        self.cancelled = threading.Event()
        self.backend = "openai-compatible"
        self.skipped_models: list[str] = []
        self.last_memory_assessment: dict | None = None
        self.coordination_directory = coordination_directory
        self._runtime_lease = None
        self.deadline = None
        self.timeout_seconds = 180
        self.backend_state = None
        self._session_guard = threading.Lock()
        self.expected_job = None
        self.expected_owner = None
        self.observe_connection_owner = False
        self.last_connection_owner = None
        self.endpoint_observation = None
        self.managed_directory = None
        self.managed_assets = None
        self.expected_tokenization = None
        self.last_generation_metrics = None

    @contextmanager
    def _client_operation(self):
        if not self._session_guard.acquire(blocking=False):
            raise ModelError("This local model client is already handling a request.")
        try:
            yield
        finally:
            self._session_guard.release()

    @contextmanager
    def _deadline_scope(self, seconds):
        prior = self.deadline
        self.deadline = deadline_limit(min(prior or float("inf"), time.monotonic() + seconds))
        try:
            checkpoint()
            yield
        finally:
            self.deadline = prior

    @contextmanager
    def _generation_session(self, *, timeout=None):
        with self._client_operation():
            self.last_generation_metrics = None
            lease = RuntimeLease(self.host, self.port, directory=self.coordination_directory)
            try:
                with self._deadline_scope(min(self.timeout_seconds, timeout or self.timeout_seconds)), lease:
                    self._runtime_lease = lease
                    yield
            except RuntimeCoordinationError as exc:
                raise ModelError(str(exc)) from exc
            finally:
                state = lease.record.get("state", "uncertain") if isinstance(lease.record, dict) else "uncertain"
                if lease.busy:
                    state = "busy"
                self.backend_state = {"state": state, "terminal_observed": lease.terminal,
                                      "dispatched": lease.dispatched, "runtime": lease.key,
                                      "scope": "cooperating CETA requests in this OS account; external clients remain independent"}
                self._runtime_lease = None

    def reconcile_runtime(self):
        with RuntimeLease(self.host, self.port, directory=self.coordination_directory, allow_uncertain=True) as lease:
            return lease.reconcile()

    def cancel(self):
        self.cancelled.set()

    def _request(self, method: str, path: str, payload=None):
        checkpoint()
        if self.cancelled.is_set():
            raise ModelError("The model request was cancelled.")
        deadline = deadline_limit(self.deadline or time.monotonic() + 30)
        if time.monotonic() >= deadline:
            raise ModelDeadlineError("The local model request exceeded its deadline.")
        self.connection = http.client.HTTPConnection(self.host, self.port, timeout=.25)
        transport = ModelSocket(socket.AF_INET6 if self.host == "::1" else socket.AF_INET, socket.SOCK_STREAM)
        transport.cancelled = self.cancelled
        transport.deadline = deadline
        self.connection.sock = transport
        transport.setblocking(False)
        code = transport.connect_ex((self.host, self.port))
        if code not in {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036}:
            raise OSError(code, "Cannot connect to the local model service")
        while code:
            checkpoint()
            if self.cancelled.is_set():
                raise ModelError("The model request was cancelled.")
            if time.monotonic() >= min(deadline, transport.deadline):
                raise ModelDeadlineError("The local model connection exceeded its deadline.")
            _, ready, errors = select.select([], [transport], [transport], .05)
            if ready or errors:
                code = transport.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code:
                    raise OSError(code, "Cannot connect to the local model service")
                break
        transport.settimeout(.25)
        if self.cancelled.is_set():
            raise ModelError("The model request was cancelled.")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        if self.expected_job is not None or self.expected_owner is not None or self.observe_connection_owner:
            owner = connection_owner(self.host, self.port, transport.getsockname()[1])
            if not owner:
                raise ModelError("The runtime connection has no observable process identity.")
            if self.expected_owner is not None and owner != self.expected_owner:
                raise ModelError("The runtime process changed; no request was sent.")
            self.last_connection_owner = owner
        if self.expected_job is not None:
            from .windows_job import inspect_job
            observation = inspect_job(self.expected_job, owner)
            if not observation.get("owner_contained"):
                raise ModelError("The connection belongs to a different runtime; no request was sent.")
            self.endpoint_observation = {**observation, "owner": owner}
        if method == "POST" and path in {"/api/chat", "/chat/completions", "/api/generate"} and self._runtime_lease is not None:
            self._runtime_lease.begin_dispatch(client_port=transport.getsockname()[1],
                operation="template-render" if isinstance(payload, dict) and payload.get("_debug_render_only") is True else
                    "unload" if path == "/api/generate" else "generation")
        self.connection.request(method, self.prefix + path, body=body, headers={"Content-Type": "application/json"})
        transport.settimeout(0.25)
        if self.cancelled.is_set():
            raise ModelError("The model request was cancelled.")
        response = self.connection.getresponse()
        if response.status != 200:
            raise _ModelHTTPError(response.status)
        return response

    def _json_request(self, method: str, path: str, payload=None, *, root=False) -> dict:
        original_prefix = self.prefix
        if root:
            self.prefix = ""
        try:
            response = self._request(method, path, payload)
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise ModelError("The model metadata response is too large.")
            try:
                record = json.loads(data)
            except (ValueError, UnicodeError) as exc:
                raise ModelError("The local model service returned malformed metadata.") from exc
            if not isinstance(record, dict) or "error" in record:
                raise ModelError("The local model service returned invalid metadata.")
            return record
        finally:
            self.prefix = original_prefix
            if self.connection:
                self.connection.close()

    def _ollama_catalog(self) -> list[dict] | None:
        try:
            record = self._json_request("GET", "/api/tags", root=True)
        except _ModelHTTPError as exc:
            if exc.status in {404, 405, 501} and self.backend != "ollama":
                return None
            raise
        if "models" not in record and isinstance(record.get("data"), list) and self.backend != "ollama":
            # Some OpenAI-compatible servers route unknown GET paths to their
            # model list. This says nothing about where they run inference.
            return None
        catalog = record.get("models")
        if not isinstance(catalog, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in catalog
        ):
            raise ModelError("The local model service returned an invalid Ollama catalog.")
        self.backend = "ollama"
        return catalog

    def _ollama_readiness(self, model: str, catalog: list[dict]) -> dict:
        result = {"model": model, "backend": "ollama", "locality": "unverified"}
        installed = next((item for item in catalog if _model_identity(item["name"]) == _model_identity(model)), None)
        if installed is None:
            return {**result, "reason": "The selected model is not installed in this Ollama service."}
        if _cloud_model(model) or installed.get("remote_model") or installed.get("remote_host"):
            return {**result, "locality": "remote", "reason": "Cloud-backed models cannot be used for offline chat."}
        details = self._json_request("POST", "/api/show", {"model": model}, root=True)
        if details.get("remote_model") or details.get("remote_host"):
            return {**result, "locality": "remote", "reason": "This model alias forwards inference to a remote service."}
        size = installed.get("size")
        model_details = details.get("details")
        model_info = details.get("model_info")
        if (type(size) is not int or size <= 0 or not isinstance(model_details, dict)
                or model_details.get("format") != "gguf" or not isinstance(model_info, dict) or not model_info):
            return {**result, "reason": "Ollama did not report installed local model weights and metadata."}
        return {
            **result, "locality": "local", "reason": "Ollama reports installed local GGUF weights; generation is not yet tested.",
            "size_bytes": size, "parameter_size": model_details.get("parameter_size"),
            "quantization": model_details.get("quantization_level"), "source": "runtime-reported",
            "digest": installed.get("digest"), "architecture": model_info.get("general.architecture"),
            "memory_metadata": {key: value for key, value in model_info.items()
                                if isinstance(key, str) and (key == "general.architecture" or
                                    key.endswith((".block_count", ".embedding_length", ".context_length",
                                                  ".attention.head_count", ".attention.head_count_kv",
                                                  ".attention.key_length", ".attention.value_length")))},
            "context_limit": model_info.get(str(model_info.get("general.architecture")) + ".context_length"),
            "template_sha256": hashlib.sha256(str(details.get("template", "")).encode("utf-8")).hexdigest(),
            "parameters_sha256": hashlib.sha256(json.dumps(details.get("parameters"), sort_keys=True).encode("utf-8")).hexdigest(),
            "thinking_mode": "low" if any(
                isinstance(value, str) and value.lower().replace("-", "").replace("_", "") == "gptoss"
                for value in (model_info.get("general.architecture"), model_details.get("family"))
            ) else False,
        }

    def model_readiness(self, model: str) -> dict:
        """Inspect service-reported locality without transmitting conversation text."""
        if not isinstance(model, str) or not model.strip():
            raise ModelError("Select an installed model first.")
        if _cloud_model(model):
            return {"model": model, "backend": self.backend, "locality": "remote",
                    "reason": "Cloud-backed models cannot be used for offline chat."}
        catalog = self._ollama_catalog()
        if catalog is not None:
            return self._ollama_readiness(model, catalog)
        return {"model": model, "backend": "openai-compatible", "locality": "unverified",
                "reason": "Loopback transport only; this service's inference locality is unverified."}

    def available_models(self) -> list[str]:
        with self._client_operation(), self._deadline_scope(30):
            return self._available_models()

    def _available_models(self) -> list[str]:
        self.skipped_models = []
        catalog = self._ollama_catalog()
        if catalog is not None:
            available = []
            for item in catalog:
                name = item["name"]
                if self._ollama_readiness(name, catalog)["locality"] == "local":
                    available.append(name)
                else:
                    self.skipped_models.append(name)
            return available
        record = self._json_request("GET", "/models")
        if not isinstance(record.get("data"), list):
            raise ModelError("The local model service returned an invalid model list.")
        names = [item["id"] for item in record["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)]
        self.skipped_models = [name for name in names if _cloud_model(name)]
        return [name for name in names if not _cloud_model(name)]

    def wait_owned_service(self, backend, job_name, *, timeout=120):
        """Poll owned HTTP metadata; never load a model or send a test prompt."""
        if backend not in {"ollama", "llama.cpp"} or not 0 < timeout <= 300:
            raise ModelError("Invalid owned runtime health request.")
        started = time.monotonic()
        with self._client_operation(), self._deadline_scope(timeout):
            self.expected_job = job_name
            try:
                while True:
                    if self.cancelled.is_set():
                        raise ModelError("Runtime health inspection was stopped.")
                    if time.monotonic() >= self.deadline:
                        raise ModelDeadlineError("The owned runtime did not become healthy before its deadline.")
                    try:
                        if backend == "ollama":
                            health = self._json_request("GET", "/api/version", root=True)
                            if not isinstance(health.get("version"), str) or not health["version"].strip():
                                raise ModelError("Ollama did not report a valid runtime version.")
                            models = self._available_models()
                            if self.backend != "ollama":
                                raise ModelError("The owned service did not expose the expected Ollama API.")
                        else:
                            health = self._json_request("GET", "/health", root=True)
                            if health.get("status") != "ok":
                                raise ModelError("llama-server did not report a healthy state.")
                            record = self._json_request("GET", "/models")
                            rows = record.get("data")
                            if not isinstance(rows, list) or not rows or any(
                                    not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows):
                                raise ModelError("llama-server did not report its loaded model.")
                            models = [row["id"] for row in rows]
                        return {"status": "service_healthy", "backend": backend, "health": health,
                                "models": models, "skipped_models": list(self.skipped_models),
                                "endpoint": {"host": self.host, "port": self.port, "prefix": self.prefix},
                                "containment": self.endpoint_observation,
                                "elapsed_seconds": time.monotonic() - started,
                                "inference": "not_tested", "scope": "Owned HTTP metadata response only"}
                    except _ModelHTTPError as exc:
                        if exc.status != 503:
                            raise
                    except OSError as exc:
                        if isinstance(exc, ModelDeadlineError):
                            raise
                        # Retry startup connection failures only. Observation
                        # errors and access denial must not be called readiness.
                        if exc.errno not in {errno.ECONNREFUSED, errno.ECONNRESET, 10061, 10054}:
                            raise
                    finally:
                        if self.connection:
                            self.connection.close()
                    self.cancelled.wait(min(.2, max(0, self.deadline - time.monotonic())))
            finally:
                self.expected_job = None

    def _request_profile(self, readiness):
        if readiness["locality"] == "remote" or (readiness["backend"] == "ollama" and readiness["locality"] != "local"):
            raise ModelError(readiness["reason"])
        return {"endpoint": {"host": self.host, "port": self.port, "prefix": self.prefix},
                **{key: readiness.get(key) for key in ("model", "backend", "locality", "digest", "architecture", "size_bytes",
                   "context_limit", "template_sha256", "parameters_sha256", "thinking_mode", "memory_metadata")},
                "thinking_mode": readiness.get("thinking_mode", False),
                "identity_scope": "runtime-reported identity at inspection; mutable tags are not immutable execution identity"}

    def request_profile(self, model):
        with self._client_operation(), self._deadline_scope(30), RuntimeLease(self.host, self.port, directory=self.coordination_directory):
            return self._request_profile(self.model_readiness(model))

    def _check_tokenization_binding(self, messages, context_length, max_tokens):
        if self.expected_tokenization is not None:
            from .request_tokens import check_runner, text_hash
            counted = self.expected_tokenization
            protection = counted["binding"].get("asset_session")
            if protection is not None:
                if (self.managed_assets is None or self.managed_assets.session_id != protection or
                        self.managed_assets.job_name != self.expected_job):
                    raise ModelError("The protected asset session changed; restart and prepare again.")
                self.managed_assets.assert_runtime()
            if (text_hash(json.dumps(messages, sort_keys=True)) != counted["messages_sha256"] or
                    context_length != counted["binding"]["context_length"] or
                    counted["input_tokens"] + max_tokens + 1 > context_length):
                raise ModelError("The request no longer matches its token budget; prepare again.")
            check_runner(self, self.expected_tokenization["binding"])

    @staticmethod
    def generation_payload(model, messages, *, max_tokens, context_length, profile):
        if profile.get("backend") == "ollama":
            return {"path": "/api/chat", "body": {"model": model, "messages": messages, "stream": True,
                "truncate": False, "shift": False,
                "think": profile.get("thinking_mode", False),
                "options": {"num_predict": max_tokens, "num_ctx": context_length or 4096}}}
        return {"path": str(profile.get("endpoint", {}).get("prefix", "/v1")) + "/chat/completions",
                "body": {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens}}

    def stream(self, model: str, messages: list[dict], *, max_tokens: int = 4096, context_length: int | None = None,
               expected_profile=None, before_dispatch=None):
        with self._generation_session():
            yield from self._stream_request(model, messages, max_tokens=max_tokens, context_length=context_length,
                                            expected_profile=expected_profile, before_dispatch=before_dispatch)

    def _stream_request(self, model, messages, *, max_tokens, context_length, expected_profile=None, before_dispatch=None):
        self._validate_generation_limits(max_tokens, context_length)
        readiness = self.model_readiness(model)
        if expected_profile is not None and self._request_profile(readiness) != expected_profile:
            raise ModelError("Model or runtime configuration changed after preparation. Prepare the request again.")
        if readiness["locality"] == "remote" or (readiness["backend"] == "ollama" and readiness["locality"] != "local"):
            raise ModelError(readiness["reason"])
        if readiness["backend"] == "ollama":
            context_length = context_length or 4096
            self.last_memory_assessment = self._preflight_ollama(readiness, context_length)
            self._check_tokenization_binding(messages, context_length, max_tokens)
            if before_dispatch is not None:
                before_dispatch()
            yield from self._stream_ollama(
                model, messages, max_tokens=max_tokens, context_length=context_length,
                think=readiness.get("thinking_mode", False),
            )
            return
        try:
            if before_dispatch is not None:
                before_dispatch()
            payload = self.generation_payload(model, messages, max_tokens=max_tokens,
                context_length=context_length, profile=self._request_profile(readiness))
            response = self._request("POST", "/chat/completions", payload["body"])
            count = 0
            text_size = 0
            has_visible_content = False
            while not self.cancelled.is_set():
                line = response.readline(MAX_RESPONSE + 1)
                if not line:
                    raise ModelError("The model connection ended before completing its response.")
                count += len(line)
                if len(line) > MAX_RESPONSE or count > 32 * MAX_RESPONSE:
                    raise ModelError("The model response exceeded the safety limit.")
                if not line.startswith(b"data:"):
                    continue
                raw = line[5:].strip()
                if raw == b"[DONE]":
                    if self._runtime_lease is not None:
                        self._runtime_lease.observe_terminal()
                    if not has_visible_content:
                        raise ModelError("The local model completed without generating visible text.")
                    return
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeError) as exc:
                    raise ModelError("The local model returned malformed generation data.") from exc
                if not isinstance(event, dict):
                    raise ModelError("The local model returned malformed generation data.")
                if "error" in event:
                    raise ModelError("The local model service reported a generation error.")
                choices = event.get("choices", [])
                if not isinstance(choices, list):
                    raise ModelError("The local model returned malformed choices.")
                for choice in choices:
                    if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                        raise ModelError("The local model returned malformed text.")
                    content = choice.get("delta", {}).get("content", "")
                    if not isinstance(content, str):
                        raise ModelError("The local model returned malformed text.")
                    if content:
                        has_visible_content = has_visible_content or bool(content.strip())
                        text_size += len(content)
                        if text_size > MAX_RESPONSE:
                            raise ModelError("The model's text exceeded the response limit.")
                        yield content
        finally:
            if self.connection:
                self.connection.close()

    @staticmethod
    def _validate_generation_limits(max_tokens: int, context_length: int | None) -> None:
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ModelError("The response token limit must be between 1 and 4096.")
        if context_length is not None and (type(context_length) is not int or not 512 <= context_length <= 32768):
            raise ModelError("The context length must be between 512 and 32768 tokens.")

    def _stream_ollama(
        self, model: str, messages: list[dict], *, max_tokens: int, context_length: int, think: bool | str = False,
    ):
        original_prefix = self.prefix
        self.prefix = ""
        self.last_generation_metrics = None
        try:
            payload = self.generation_payload(model, messages, max_tokens=max_tokens, context_length=context_length,
                                              profile={"backend": "ollama", "thinking_mode": think})
            response = self._request("POST", "/api/chat", payload["body"])
            count = 0
            text_size = 0
            has_visible_content = False
            while not self.cancelled.is_set():
                line = response.readline(MAX_RESPONSE + 1)
                if not line:
                    raise ModelError("The model connection ended before completing its response.")
                count += len(line)
                if len(line) > MAX_RESPONSE or count > 32 * MAX_RESPONSE:
                    raise ModelError("The model response exceeded the safety limit.")
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise ModelError("The local model returned malformed generation data.") from exc
                if not isinstance(event, dict) or "error" in event:
                    raise ModelError("The local model service reported a generation error.")
                if event.get("remote_model") or event.get("remote_host"):
                    raise ModelError("The local service unexpectedly reported remote inference.")
                message = event.get("message", {})
                content = message.get("content", "") if isinstance(message, dict) else None
                if not isinstance(content, str):
                    raise ModelError("The local model returned malformed text.")
                if event.get("done") is True and self._runtime_lease is not None:
                    self._runtime_lease.observe_terminal()
                if content:
                    text_size += len(content)
                    has_visible_content = has_visible_content or bool(content.strip())
                    if text_size > MAX_RESPONSE:
                        raise ModelError("The model's text exceeded the response limit.")
                    yield content
                if event.get("done") is True:
                    self.last_generation_metrics = {key: event.get(key) for key in
                        ("prompt_eval_count", "prompt_eval_cached_count", "eval_count", "done_reason",
                         "total_duration", "load_duration", "prompt_eval_duration", "eval_duration")}
                    if self.expected_tokenization is not None and (
                            type(event.get("prompt_eval_count")) is not int or
                            event["prompt_eval_count"] != self.expected_tokenization["input_tokens"]):
                        raise ModelError("The runtime's evaluated prompt count differs from the prepared token budget; this response is unqualified.")
                    if not has_visible_content:
                        raise ModelError("The local model completed without generating visible text.")
                    return
            raise ModelError("The model request was cancelled.")
        finally:
            self.prefix = original_prefix
            if self.connection:
                self.connection.close()

    def running_models(self) -> list[dict]:
        """Return measured residency reported by Ollama, without estimating VRAM."""
        record = self._json_request("GET", "/api/ps", root=True)
        models = record.get("models")
        if not isinstance(models, list):
            raise ModelError("The local service returned invalid running-model telemetry.")
        result = []
        for item in models:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ModelError("The local service returned invalid running-model telemetry.")
            cleaned = {"name": item["name"], "model": item.get("model", item["name"]),
                       "digest": item.get("digest"), "source": "runtime-reported"}
            for field in ("size", "size_vram", "context_length"):
                value = item.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise ModelError("The local service returned invalid running-model telemetry.")
                cleaned[field] = value
            result.append(cleaned)
        return result

    def resident_snapshot(self):
        """Inspect an endpoint-bound resident list without modifying residency."""
        with self._client_operation(), self._deadline_scope(30), RuntimeLease(
                self.host, self.port, directory=self.coordination_directory):
            self.observe_connection_owner = True
            try:
                if self._ollama_catalog() is None:
                    raise ModelError("Resident-model management requires an Ollama service.")
                self.expected_owner = self.last_connection_owner
                models = self.running_models()
                return {"schema": "ceta.resident-snapshot.v1", "models": models,
                        "owner": self.expected_owner, "observed_at": time.time(),
                        "endpoint": {"host": self.host, "port": self.port, "prefix": self.prefix},
                        "scope": "Runtime-reported residency; external clients may change it independently."}
            finally:
                self.observe_connection_owner = False
                self.expected_owner = None

    def unload_model(self, snapshot, name):
        """Unload only the explicitly selected, freshly rechecked resident model."""
        endpoint = {"host": self.host, "port": self.port, "prefix": self.prefix}
        if (not isinstance(snapshot, dict) or snapshot.get("schema") != "ceta.resident-snapshot.v1" or
                snapshot.get("endpoint") != endpoint or not isinstance(snapshot.get("owner"), dict) or
                not isinstance(snapshot.get("models"), list) or any(not isinstance(row, dict) for row in snapshot["models"]) or
                not isinstance(snapshot.get("observed_at"), (int, float)) or
                not 0 <= time.time() - snapshot["observed_at"] <= 60):
            raise ModelError("The resident-model inspection is stale or belongs to another service. Inspect loaded models again.")
        if not isinstance(name, str) or not name.strip() or _cloud_model(name):
            raise ModelError("Select a local resident model to unload.")
        prior = [row for row in snapshot.get("models", []) if row.get("name") == name]
        if len(prior) != 1 or not isinstance(prior[0].get("digest"), str) or not prior[0]["digest"]:
            raise ModelError("The selected resident has no unambiguous model identity. Inspect it again.")
        with self._generation_session(timeout=30):
            self.expected_owner = snapshot["owner"]
            try:
                catalog = self._ollama_catalog()
                if catalog is None:
                    raise ModelError("The inspected service no longer exposes Ollama residency.")
                readiness = self._ollama_readiness(name, catalog)
                if readiness["locality"] != "local" or readiness.get("digest") != prior[0]["digest"]:
                    raise ModelError("The selected model identity changed. No unload was sent.")
                current = [row for row in self.running_models() if _model_identity(row["name"]) == _model_identity(name)]
                if len(current) != 1 or current[0].get("digest") != prior[0]["digest"]:
                    raise ModelError("Residency changed since inspection. No unload was sent.")
                result = self._json_request("POST", "/api/generate",
                    {"model": name, "prompt": "", "keep_alive": 0, "stream": False}, root=True)
                if (result.get("done") is not True or result.get("done_reason") != "unload" or
                        result.get("response", "") != "" or not isinstance(result.get("model"), str) or
                        _model_identity(result["model"]) != _model_identity(name)):
                    raise ModelError("The service did not confirm the selected model unload. Runtime state remains uncertain.")
                while any(_model_identity(row["name"]) == _model_identity(name) for row in self.running_models()):
                    if self.cancelled.wait(.1):
                        raise ModelError("Model unload observation was cancelled; runtime state remains uncertain.")
                    if time.monotonic() >= self.deadline:
                        raise ModelDeadlineError("The model unload was not observed before its deadline.")
                self._runtime_lease.observe_terminal()
                return {"status": "unloaded", "model": name, "digest": prior[0]["digest"],
                        "owner": snapshot["owner"], "observed_at": time.time(),
                        "scope": "Ollama acknowledged unload and no longer reports this model resident; external clients remain independent."}
            finally:
                self.expected_owner = None

    def _preflight_ollama(self, readiness: dict, context_length: int) -> dict:
        if context_length > 4096:
            raise ModelError("The memory estimate supports at most 4096 context tokens.")
        model = readiness["model"]
        running = self.running_models()
        if any(_model_identity(item["name"]) != _model_identity(model) for item in running):
            raise ModelError("Another model is already loaded. Open Models, inspect loaded models, and explicitly unload the selected resident before switching.")
        # This admission uses host RAM only. GPU placement remains the service's
        # responsibility; querying graphics drivers cannot qualify it here.
        profile = inspect_hardware(cancelled=self.cancelled, deadline=self.deadline, include_gpus=False)
        checkpoint()
        digest = readiness.get("digest")
        if running and isinstance(digest, str) and digest and running[0].get("digest") != digest:
            raise ModelError("The resident model identity differs from the selected installed model. Reconcile the service before generation.")
        if running and isinstance(digest, str) and digest and (running[0].get("context_length") or 0) >= context_length and (running[0].get("size") or 0) > 0:
            # The service already allocated this context. Do not count its
            # resident weights a second time against remaining physical RAM.
            available, total = profile.available_ram_bytes, profile.total_ram_bytes
            if type(available) is not int or type(total) is not int or not GIB // 2 <= available <= total:
                raise ModelError("The loaded model has insufficient or unverified free RAM headroom. Free memory and recheck.")
            return {"mode": "resident", "preloaded": True,
                    "digest": digest, "placement": "external-runtime-managed", "verified": False,
                    "reason": "The runtime reports this digest already allocated at the requested context; placement and quiescence remain unverified."}
        try:
            estimate = model_memory(readiness["size_bytes"], readiness.get("memory_metadata"), context_length)
            available = ram_budget(profile)
        except BackendError as exc:
            raise ModelError(str(exc)) from exc
        if estimate["total_bytes"] > available:
            raise ModelError("Insufficient measured RAM for this external runtime load. A GPU fit estimate cannot establish that this service can use that device. Select a smaller model or a verified owned runtime configuration.")
        return {"mode": "cpu", "preloaded": False, "placement": "external-runtime-managed", "verified": False,
                "memory": estimate, "available_ram_budget": available,
                "reason": "Estimated host RAM fit; external service selects actual placement. GPU compatibility is unverified."}

    def probe_local_model(self, model: str, *, max_tokens: int = 128, context_length: int = 4096,
                          messages=None, expected_profile=None, before_dispatch=None) -> dict:
        """Complete one bounded synthetic local generation; no conversation is saved."""
        with self._generation_session():
            result = self._probe_local_model(model, max_tokens=max_tokens, context_length=context_length,
                                              messages=messages, expected_profile=expected_profile, before_dispatch=before_dispatch)
        result["backend_state"] = self.backend_state
        return result

    def _probe_local_model(self, model: str, *, max_tokens: int, context_length: int,
                           messages=None, expected_profile=None, before_dispatch=None) -> dict:
        self._validate_generation_limits(max_tokens, context_length)
        if max_tokens > 128:
            raise ModelError("The readiness probe is limited to 128 output tokens.")
        readiness = self.model_readiness(model)
        if expected_profile is not None and self._request_profile(readiness) != expected_profile:
            raise ModelError("Model or runtime configuration changed after preparation")
        if readiness["backend"] != "ollama" or readiness["locality"] != "local":
            raise ModelError(readiness["reason"])
        self.last_memory_assessment = self._preflight_ollama(readiness, context_length)
        self._check_tokenization_binding(messages, context_length, max_tokens)
        thinking_mode = readiness.get("thinking_mode", False)
        prompt = "Reply with CETA_READY and no other text."
        if thinking_mode is False:
            prompt = "/no_think\n" + prompt
        started = time.monotonic()
        if before_dispatch is not None:
            before_dispatch()
        response = "".join(self._stream_ollama(
            model, messages if messages is not None else [{"role": "user", "content": prompt}],
            max_tokens=max_tokens, context_length=context_length, think=thinking_mode,
        ))
        elapsed = time.monotonic() - started
        if not response.strip():
            raise ModelError("The local model completed without generating visible text.")
        result = {"status": "verified", "model": model, "response": response,
                  "elapsed_seconds": elapsed, "characters": len(response), "locality": "local",
                  "runtime": None, "telemetry_source": "runtime-reported",
                  "memory_assessment": self.last_memory_assessment}
        try:
            result["runtime"] = next((item for item in self.running_models()
                                      if _model_identity(item["name"]) == _model_identity(model)), None)
        except (ModelError, OSError, http.client.HTTPException) as exc:
            result["telemetry_error"] = str(exc)
        return result

    def pull_ollama_model(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", name) or "://" in name:
            raise ModelError("Enter an Ollama model name such as qwen3:4b, not a URL.")
        if _cloud_model(name):
            raise ModelError("Choose a local model; cloud-backed model aliases cannot provide offline chat.")
        original_prefix = self.prefix
        self.prefix = ""
        try:
            response = self._request("POST", "/api/pull", {"name": name, "stream": True})
            while not self.cancelled.is_set():
                line = response.readline(65537)
                if not line or len(line) > 65536:
                    raise ModelError("The model download ended before the service confirmed installation.")
                record = json.loads(line)
                if "error" in record:
                    raise ModelError(str(record["error"]))
                status = record.get("status", "Downloading")
                if record.get("total"):
                    status += f" · {record.get('completed', 0) * 100 / record['total']:.0f}%"
                yield status
                if record.get("status") == "success":
                    return
        finally:
            self.prefix = original_prefix
            if self.connection:
                self.connection.close()


class ModelPacks:
    """Content-addressed local GGUF expansions; model files are never executable."""

    def __init__(self, directory: Path):
        self.directory = directory / "models"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.problems: list[str] = []

    def _record(self, identifier: str) -> dict:
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise ModelError("Invalid model pack identifier.")
        folder = self.directory / identifier
        model, manifest = folder / "model.gguf", folder / "pack.json"
        if any(path.is_symlink() or (os.name == "nt" and path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
               for path in (folder, model, manifest)):
            raise ModelError("Installed model files cannot be links or redirected folders.")
        with manifest.open("rb") as handle:
            raw = handle.read(16385)
        if len(raw) > 16384:
            raise ModelError("The installed model manifest is too large.")
        record = json.loads(raw)
        if not isinstance(record, dict) or set(record) != {"schema_version", "name", "format", "sha256", "size"}:
            raise ModelError("Invalid installed model manifest fields.")
        if (type(record["schema_version"]) is not int or record["schema_version"] != 1 or
                record["format"] != "gguf" or record["sha256"] != identifier or
                not isinstance(record["name"], str) or not 1 <= len(record["name"]) <= 255 or
                type(record["size"]) is not int or not 24 <= record["size"] <= 64 * 1024**3):
            raise ModelError("Invalid installed model manifest values.")
        if not model.is_file() or model.stat().st_size != record["size"]:
            raise ModelError("The installed model is missing or its size has changed.")
        return {**record, "path": str(model)}

    def installed(self) -> list[dict]:
        result = []
        self.problems = []
        for manifest in sorted(self.directory.glob("*/pack.json")):
            if manifest.parent.name.startswith(".install-"):
                continue
            try:
                result.append(self._record(manifest.parent.name))
            except (ValueError, OSError) as exc:
                self.problems.append(f"{manifest.parent.name}: {exc}")
        return result

    def verify_installed(self, identifier: str, cancelled: threading.Event | None = None) -> dict:
        record = self._record(identifier)
        model = Path(record["path"])
        with model.open("rb") as handle:
            digest = hashlib.sha256()
            while block := handle.read(1024 * 1024):
                if cancelled and cancelled.is_set():
                    raise ModelError("Model verification cancelled.")
                digest.update(block)
            actual = digest.hexdigest()
        if actual != identifier or record.get("sha256") != identifier or model.stat().st_size != record.get("size"):
            raise ModelError(f"Installed model integrity check failed. Restore the original bytes from your backup: {model}")
        return {**record, "path": str(model)}

    def install(self, source: Path, cancelled: threading.Event | None = None) -> dict:
        if source.is_symlink() or not source.is_file():
            raise ModelError("Select a regular GGUF model file.")
        size = source.stat().st_size
        if size < 24 or size > 64 * 1024**3:
            raise ModelError("Supported GGUF expansion sizes are 24 bytes through 64 GiB.")
        if shutil.disk_usage(self.directory).free < size + 128 * 1024**2:
            raise ModelError("There is not enough free disk space to install this model.")
        staging = self.directory / (".install-" + uuid.uuid4().hex)
        staging.mkdir()
        try:
            digest = hashlib.sha256()
            copied = 0
            with source.open("rb") as reader, (staging / "model.gguf").open("xb") as writer:
                header = reader.read(24)
                if header[:4] != b"GGUF" or int.from_bytes(header[4:8], "little") not in {2, 3}:
                    raise ModelError("This is not a supported GGUF v2/v3 model.")
                reader.seek(0)
                while block := reader.read(1024 * 1024):
                    if cancelled and cancelled.is_set():
                        raise ModelError("Model installation cancelled.")
                    copied += len(block)
                    if copied > size:
                        raise ModelError("The source model changed during installation.")
                    digest.update(block)
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            if copied != size:
                raise ModelError("The source model changed during installation.")
            identifier = digest.hexdigest()
            record = {"schema_version": 1, "name": source.stem, "format": "gguf", "sha256": identifier, "size": size}
            with (staging / "pack.json").open("x", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            destination = self.directory / identifier
            if not destination.exists():
                staging.rename(destination)
            else:
                self.verify_installed(identifier)
            return {**record, "path": str(destination / "model.gguf")}
        finally:
            # This is only our uniquely created, unpublished staging directory.
            if staging.exists():
                shutil.rmtree(staging)
