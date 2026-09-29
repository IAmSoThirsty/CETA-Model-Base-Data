"""One local provider interface; generation returns data and never executes tools."""
from __future__ import annotations

import math
import threading
import time

from ceta_desktop.models import LocalModelClient
from ceta_desktop.request_control import ModelCancelledError, ModelDeadlineError, current_budget, request_scope


class LocalProvider:
    provider_id = "ceta-local"

    def __init__(self, client=None, *, endpoint="http://127.0.0.1:11434/v1",
                 timeout_seconds=180, max_tokens=1024, context_length=None, readiness_probe=False):
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be between zero and 3600")
        LocalModelClient._validate_generation_limits(max_tokens, context_length)
        self.client = client if client is not None else LocalModelClient(endpoint)
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.context_length = context_length
        if type(readiness_probe) is not bool or (readiness_probe and max_tokens > 128):
            raise ValueError("Readiness probes require a Boolean mode and at most 128 output tokens")
        self.readiness_probe = readiness_probe
        self._active = threading.Lock()

    def capabilities(self):
        return {"streaming": True, "cancellation": True, "tool_execution": False,
                "structured_tool_calls": False, "transport": "loopback"}

    def available_models(self):
        return self.client.available_models()

    def cancel(self):
        self.client.cancel()

    def generation_profile(self, model):
        inspect = getattr(self.client, "request_profile", None)
        observed = inspect(model) if callable(inspect) else {"backend": "adapter", "model": model,
                                                            "identity_scope": "unverified adapter"}
        limit = observed.get("context_limit")
        context = self.context_length or 4096
        if type(limit) is int and 0 < limit < context:
            raise ValueError(f"This model reports a {limit}-token context, below the selected {context}. Select a supported profile.")
        return {"provider": self.provider_id, "model": model, "max_tokens": self.max_tokens,
                "context_length": context, "readiness_probe": self.readiness_probe, "observed": observed}

    def transport_payload(self, model, messages, profile):
        return LocalModelClient.generation_payload(model, messages, max_tokens=profile["max_tokens"],
            context_length=profile["context_length"], profile=profile["observed"])

    def request_counter(self, model, profile, *, cancelled=None):
        if (isinstance(self.client, LocalModelClient) and self.client.managed_directory is not None and
                self.client.expected_job and profile["observed"].get("backend") == "ollama" and model.startswith("ceta-")):
            from ceta_desktop.request_tokens import ManagedTokenCounter
            return ManagedTokenCounter(self.client, model, profile, cancelled)
        return None

    def bind_prepared_request(self, prepared):
        if not isinstance(self.client, LocalModelClient):
            return
        budget = prepared["budget"]
        self.client.expected_tokenization = budget.get("tokenization") if budget.get("verified") else None

    def stream_prepared(self, model, messages, profile, cancelled=None, on_token=None, before_dispatch=None):
        if profile["max_tokens"] != self.max_tokens or profile["context_length"] != (self.context_length or 4096):
            raise ValueError("Generation limits changed after preparation")
        return self.stream(model, messages, cancelled=cancelled, on_token=on_token,
                           expected_profile=profile["observed"], before_dispatch=before_dispatch)

    @staticmethod
    def _cancelled(value):
        if value is None:
            return False
        if hasattr(value, "is_set"):
            return value.is_set()
        if callable(value):
            return bool(value())
        return bool(value)

    def stream(self, model, messages, cancelled=None, on_token=None, expected_profile=None, before_dispatch=None):
        try:
            with request_scope(self.timeout_seconds, cancelled):
                return self._stream(model, messages, cancelled, on_token, expected_profile, before_dispatch)
        except (ModelCancelledError, ModelDeadlineError) as exc:
            return {"provider": self.provider_id, "model": model, "text": "",
                    "status": "timed_out" if isinstance(exc, TimeoutError) else "cancelled",
                    "error": str(exc) if isinstance(exc, TimeoutError) else None}

    def _stream(self, model, messages, cancelled=None, on_token=None, expected_profile=None, before_dispatch=None):
        result = {"provider": self.provider_id, "model": model, "status": "failed", "text": "", "error": None,
                  "generation": {"max_tokens": self.max_tokens, "context_length": self.context_length}}
        if not isinstance(model, str) or not model.strip():
            return {**result, "error": "Select a model first."}
        if not isinstance(messages, list) or any(not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant"}
                or not isinstance(m.get("content"), str) for m in messages):
            return {**result, "error": "Messages must contain supported roles and text content."}
        if self._cancelled(cancelled):
            return {**result, "status": "cancelled"}
        if not self._active.acquire(blocking=False):
            return {**result, "error": "This provider is already generating a response."}
        stopped = threading.Event()
        timed_out = threading.Event()
        requested_cancel = threading.Event()
        monitor_guard = threading.Lock()
        started = time.monotonic()
        deadline = current_budget().deadline
        chunks = []
        text_size = 0
        generation = None
        def observe_cancellation():
            while not stopped.wait(0.02):
                if time.monotonic() >= deadline:
                    with monitor_guard:
                        if stopped.is_set():
                            return
                        timed_out.set()
                        # Native transport checks the same deadline itself. Do
                        # not turn a timeout into a user cancellation in the UI.
                        if not isinstance(self.client, LocalModelClient):
                            self.client.cancel()
                    return
                if self._cancelled(cancelled):
                    with monitor_guard:
                        if not stopped.is_set():
                            requested_cancel.set(); self.client.cancel()
                    return
        monitor = threading.Thread(target=observe_cancellation, name="ceta-provider-cancellation", daemon=True)
        try:
            client_event = getattr(self.client, "cancelled", None)
            if isinstance(client_event, threading.Event) and client_event.is_set():
                return {**result, "status": "cancelled"}
            if isinstance(self.client, LocalModelClient):
                self.client.timeout_seconds = self.timeout_seconds
            monitor.start()
            if self.readiness_probe:
                result["probe"] = self.client.probe_local_model(model, max_tokens=self.max_tokens,
                    context_length=self.context_length or 4096, messages=messages, expected_profile=expected_profile,
                    before_dispatch=before_dispatch)
                generation = iter([result["probe"]["response"]])
            else:
                limits = {"max_tokens": self.max_tokens, "context_length": self.context_length}
                if expected_profile is not None:
                    limits["expected_profile"] = expected_profile
                if before_dispatch is not None:
                    limits["before_dispatch"] = before_dispatch
                generation = self.client.stream(model, messages, **limits)
            for token in generation:
                if time.monotonic() >= deadline:
                    timed_out.set()
                    break
                if self._cancelled(cancelled):
                    requested_cancel.set(); self.client.cancel(); break
                if timed_out.is_set():
                    break
                if not isinstance(token, str):
                    raise ValueError("The model returned a non-text token.")
                text_size += len(token)
                if text_size > 2 * 1024 * 1024:
                    raise ValueError("The model response exceeded the text limit.")
                chunks.append(token)
                if on_token is not None:
                    on_token(token)
            result["status"] = "completed"
        except Exception as exc:
            result["error"] = str(exc)[:1000]
            if isinstance(exc, TimeoutError):
                timed_out.set()
        finally:
            with monitor_guard:
                stopped.set()
            if monitor.is_alive():
                monitor.join(timeout=0.2)
            try:
                if generation is not None and hasattr(generation, "close"):
                    generation.close()
            except Exception as exc:
                result.update(status="failed", error=str(exc)[:1000])
            finally:
                self._active.release()
        result["text"] = "".join(chunks)
        result["request_time_budget"] = current_budget().receipt()
        result["stream_elapsed_seconds"] = time.monotonic() - started
        resource_admission = getattr(self.client, "last_memory_assessment", None)
        if isinstance(resource_admission, dict):
            result["resource_admission"] = resource_admission
        backend_state = getattr(self.client, "backend_state", None)
        if isinstance(backend_state, dict):
            result["backend_state"] = backend_state
        metrics = getattr(self.client, "last_generation_metrics", None)
        if isinstance(metrics, dict):
            result["generation_metrics"] = metrics
        if result["status"] == "completed" and not result["text"].strip():
            result.update(status="failed", error="The local model completed without generating visible text.")
        if timed_out.is_set() or time.monotonic() >= deadline:
            result.update(status="timed_out", error="The model request exceeded its time limit.")
        elif requested_cancel.is_set() or self._cancelled(cancelled) or self._cancelled(getattr(self.client, "cancelled", None)):
            result.update(status="cancelled", error=None)
        return result
