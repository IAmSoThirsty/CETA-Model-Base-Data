"""One local provider interface; generation returns data and never executes tools."""
from __future__ import annotations

import math
import threading
import time

from ceta_desktop.models import LocalModelClient


class LocalProvider:
    provider_id = "ceta-local"

    def __init__(self, client=None, *, endpoint="http://127.0.0.1:11434/v1",
                 timeout_seconds=180, max_tokens=4096, context_length=None, readiness_probe=False):
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

    @staticmethod
    def _cancelled(value):
        if value is None:
            return False
        if hasattr(value, "is_set"):
            return value.is_set()
        if callable(value):
            return bool(value())
        return bool(value)

    def stream(self, model, messages, cancelled=None, on_token=None):
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
        started = time.monotonic()
        chunks = []
        text_size = 0
        generation = None
        def observe_cancellation():
            while not stopped.wait(0.02):
                if time.monotonic() - started >= self.timeout_seconds:
                    timed_out.set(); self.client.cancel(); return
                if self._cancelled(cancelled):
                    requested_cancel.set(); self.client.cancel(); return
        monitor = threading.Thread(target=observe_cancellation, name="ceta-provider-cancellation", daemon=True)
        try:
            client_event = getattr(self.client, "cancelled", None)
            if isinstance(client_event, threading.Event):
                client_event.clear()
            monitor.start()
            if self.readiness_probe:
                result["probe"] = self.client.probe_local_model(model, max_tokens=self.max_tokens,
                    context_length=self.context_length or 4096)
                generation = iter([result["probe"]["response"]])
            else:
                generation = self.client.stream(model, messages, max_tokens=self.max_tokens, context_length=self.context_length)
            for token in generation:
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
        finally:
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
        if timed_out.is_set():
            result.update(status="timed_out", error="The model request exceeded its time limit.")
        elif requested_cancel.is_set() or self._cancelled(cancelled) or self._cancelled(getattr(self.client, "cancelled", None)):
            result.update(status="cancelled", error=None)
        return result
