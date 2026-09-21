from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import re
from pathlib import Path
import shutil
import socket
import stat
import threading
import time
from urllib.parse import urlsplit
import uuid

from .hardware import GIB, ModelOption, assess_model, inspect_hardware

MAX_RESPONSE = 2 * 1024 * 1024
_PROBE_LOCK = threading.Lock()


class ModelError(ValueError):
    pass


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
        deadline = time.monotonic() + 120
        while not self.cancelled.is_set():
            try:
                return super().recv_into(buffer, nbytes, flags)
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise ModelError("The local model service has not responded for two minutes.")
        raise ModelError("The model request was cancelled.")


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

    def __init__(self, endpoint: str):
        self.host, self.port, self.prefix = local_endpoint(endpoint)
        self.connection: http.client.HTTPConnection | None = None
        self.cancelled = threading.Event()
        self.backend = "openai-compatible"
        self.skipped_models: list[str] = []
        self.last_memory_assessment: dict | None = None

    def cancel(self):
        self.cancelled.set()

    def _request(self, method: str, path: str, payload=None):
        if self.cancelled.is_set():
            raise ModelError("The model request was cancelled.")
        self.connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        self.connection.connect()
        original = self.connection.sock
        transport = ModelSocket(original.family, original.type, original.proto, fileno=original.detach())
        transport.cancelled = self.cancelled
        transport.settimeout(10)
        self.connection.sock = transport
        if self.cancelled.is_set():
            raise ModelError("The model request was cancelled.")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
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

    def stream(self, model: str, messages: list[dict], *, max_tokens: int = 4096, context_length: int | None = None):
        self._validate_generation_limits(max_tokens, context_length)
        readiness = self.model_readiness(model)
        if readiness["locality"] == "remote" or (readiness["backend"] == "ollama" and readiness["locality"] != "local"):
            raise ModelError(readiness["reason"])
        if readiness["backend"] == "ollama":
            context_length = context_length or 4096
            self.last_memory_assessment = self._preflight_ollama(readiness, context_length)
            yield from self._stream_ollama(
                model, messages, max_tokens=max_tokens, context_length=context_length,
                think=readiness.get("thinking_mode", False),
            )
            return
        try:
            response = self._request("POST", "/chat/completions", {
                "model": model, "messages": messages, "stream": True, "max_tokens": max_tokens,
            })
            count = 0
            text_size = 0
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
                    return
                event = json.loads(raw)
                if "error" in event:
                    raise ModelError("The local model service reported a generation error.")
                for choice in event.get("choices", []):
                    content = choice.get("delta", {}).get("content", "")
                    if content:
                        if not isinstance(content, str):
                            raise ModelError("The local model returned malformed text.")
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
        try:
            response = self._request("POST", "/api/chat", {
                "model": model, "messages": messages, "stream": True, "think": think,
                "options": {"num_predict": max_tokens, "num_ctx": context_length},
            })
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
                if content:
                    text_size += len(content)
                    has_visible_content = has_visible_content or bool(content.strip())
                    if text_size > MAX_RESPONSE:
                        raise ModelError("The model's text exceeded the response limit.")
                    yield content
                if event.get("done") is True:
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
            cleaned = {"name": item["name"], "model": item.get("model", item["name"]), "source": "runtime-reported"}
            for field in ("size", "size_vram", "context_length"):
                value = item.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise ModelError("The local service returned invalid running-model telemetry.")
                cleaned[field] = value
            result.append(cleaned)
        return result

    def _preflight_ollama(self, readiness: dict, context_length: int) -> dict:
        if context_length > 4096:
            raise ModelError("The memory estimate supports at most 4096 context tokens.")
        model = readiness["model"]
        running = self.running_models()
        if any(_model_identity(item["name"]) != _model_identity(model) for item in running):
            raise ModelError("Another model is already loaded. Unload it in the model service before using this model.")
        profile = inspect_hardware()
        if running and (running[0].get("context_length") or 0) >= context_length and (running[0].get("size") or 0) > 0:
            # The service already allocated this context. Do not count its
            # resident weights a second time against remaining physical RAM.
            available, total = profile.available_ram_bytes, profile.total_ram_bytes
            if type(available) is not int or type(total) is not int or not GIB // 2 <= available <= total:
                raise ModelError("The loaded model has insufficient or unverified free RAM headroom. Free memory and recheck.")
            return {"mode": "resident", "preloaded": True,
                    "reason": "The runtime reports this model already loaded at the requested context; new loading is not required."}
        size = readiness["size_bytes"]
        assessment = assess_model(profile, ModelOption(
            model, size, math.ceil(size * 1.25) + GIB, "Installed local weights",
        ))
        if assessment.mode not in {"cpu", "gpu"}:
            raise ModelError(assessment.reason)
        return {"mode": assessment.mode, "preloaded": False, "reason": assessment.reason}

    def probe_local_model(self, model: str, *, max_tokens: int = 128, context_length: int = 4096) -> dict:
        """Complete one bounded synthetic local generation; no conversation is saved."""
        if not _PROBE_LOCK.acquire(blocking=False):
            raise ModelError("Another local readiness test is already running. Wait for it to finish.")
        try:
            return self._probe_local_model(model, max_tokens=max_tokens, context_length=context_length)
        finally:
            _PROBE_LOCK.release()

    def _probe_local_model(self, model: str, *, max_tokens: int, context_length: int) -> dict:
        self._validate_generation_limits(max_tokens, context_length)
        if max_tokens > 128:
            raise ModelError("The readiness probe is limited to 128 output tokens.")
        readiness = self.model_readiness(model)
        if readiness["backend"] != "ollama" or readiness["locality"] != "local":
            raise ModelError(readiness["reason"])
        self.last_memory_assessment = self._preflight_ollama(readiness, context_length)
        thinking_mode = readiness.get("thinking_mode", False)
        prompt = "Reply with CETA_READY and no other text."
        if thinking_mode is False:
            prompt = "/no_think\n" + prompt
        started = time.monotonic()
        response = "".join(self._stream_ollama(
            model, [{"role": "user", "content": prompt}],
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
