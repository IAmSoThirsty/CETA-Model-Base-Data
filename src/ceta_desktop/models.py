from __future__ import annotations

import hashlib
import http.client
import json
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

MAX_RESPONSE = 2 * 1024 * 1024


class ModelError(ValueError):
    pass


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
            raise ModelError(f"The local model service returned HTTP {response.status}.")
        return response

    def available_models(self) -> list[str]:
        try:
            response = self._request("GET", "/models")
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise ModelError("The model list is too large.")
            return [item["id"] for item in json.loads(data)["data"] if isinstance(item.get("id"), str)]
        finally:
            if self.connection:
                self.connection.close()

    def stream(self, model: str, messages: list[dict]):
        if not model.strip():
            raise ModelError("Select an installed model first.")
        try:
            response = self._request("POST", "/chat/completions", {
                "model": model, "messages": messages, "stream": True, "max_tokens": 4096,
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

    def pull_ollama_model(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", name) or "://" in name:
            raise ModelError("Enter an Ollama model name such as qwen3:4b, not a URL.")
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
