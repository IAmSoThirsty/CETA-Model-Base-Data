"""Inspect the selected local llama.cpp executable and plan bounded launches.

All memory quantities are estimates or fresh backend observations, never an OS
reservation or a capability certificate. External services own their placement.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from .hardware import GIB, HardwareProfile


class BackendError(ValueError):
    pass


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise BackendError("Runtime inspection stopped; no model was started.")


def llama_environment(source=None):
    # A selected file must not inherit model URLs, RPC servers, extra models,
    # context/offload overrides or automatic downloads from LLAMA_ARG_* defaults.
    return {key: value for key, value in (os.environ if source is None else source).items()
            if not key.upper().startswith(("LLAMA_ARG_", "GGML_RPC"))}


def environment_digest(environment):
    relevant = {key.upper(): value for key, value in environment.items()
                if key.upper().startswith(("CUDA", "HIP", "ROCR", "GGML", "VK_", "SYCL", "ONEAPI"))
                or key.upper() == "PATH"}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()


def file_digest(path, cancelled=None):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            _check_cancelled(cancelled)
            result.update(block)
    return result.hexdigest()


def _inspect_command(executable, argument, environment, cancelled=None, *, timeout=8):
    """Bound output, deadline and cancellation of an explicitly selected program."""
    _check_cancelled(cancelled)
    if os.name == "nt":
        return _inspect_contained_command(executable, argument, environment, cancelled, timeout=timeout)
    started = time.monotonic()
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([str(executable), argument], stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            while process.poll() is None:
                _check_cancelled(cancelled)
                if time.monotonic() - started >= timeout:
                    raise BackendError("The selected runtime did not finish inspection within its deadline.")
                if os.fstat(output.fileno()).st_size > 1024 * 1024:
                    raise BackendError("The selected runtime returned too much inspection output.")
                time.sleep(0.02)
            _check_cancelled(cancelled)
            output.seek(0)
            raw = output.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise BackendError("The selected runtime returned too much inspection output.")
            if process.returncode:
                raise BackendError(f"Runtime inspection {argument} failed (exit {process.returncode}). Select a compatible llama-server.")
            return raw.decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)


def _inspect_contained_command(executable, argument, environment, cancelled, *, timeout, max_output=1024 * 1024):
    from .windows_job import WindowsJobProcess
    process = WindowsJobProcess()
    deadline = time.monotonic() + timeout
    output = bytearray()
    def admit(_):
        _check_cancelled(cancelled)
        if time.monotonic() >= deadline:
            raise BackendError("The selected runtime did not finish inspection within its deadline.")
    def read():
        output.extend(process.read())
        if len(output) > max_output:
            raise BackendError("The selected runtime returned too much inspection output.")
    try:
        process.start(str(executable), argument if isinstance(argument, list) else [argument], environment, admit)
        while True:
            admit(None)
            read()
            code = process.poll()
            if code is not None:
                read()  # Capture the final pipe bytes written before root exit.
                if code:
                    raise BackendError(f"Runtime inspection {argument} failed (exit {code}). Select a compatible llama-server.")
                return output.decode("utf-8", errors="replace")
            time.sleep(.02)
    finally:
        try:
            if process.process is not None:
                process.stop()
                shutdown_deadline = time.monotonic() + 3
                while process.poll() is None:
                    if time.monotonic() >= shutdown_deadline:
                        raise BackendError("Runtime inspection worker shutdown is unconfirmed.")
                    time.sleep(.01)
        finally:
            process.close()


def parse_llama_devices(raw):
    marker = "Available devices:"
    if raw.count(marker) != 1:
        raise BackendError("The runtime did not provide a recognized device inventory.")
    lines = [line.strip() for line in raw.split(marker, 1)[1].splitlines() if line.strip()]
    if lines == ["(none)"]:
        return []
    devices = []
    for line in lines:
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*): (.+) \((\d+) MiB, (\d+) MiB free\)", line)
        if not match:
            raise BackendError("The runtime returned an unrecognized device record; no GPU plan is admitted.")
        identifier, name, total, free = match.groups()
        total, free = int(total) * 1024**2, int(free) * 1024**2
        if total <= 0 or not 0 <= free <= total or any(row["id"] == identifier for row in devices):
            raise BackendError("The runtime returned invalid or duplicate device memory records.")
        devices.append({"id": identifier, "name": name, "total_bytes": total, "free_bytes": free,
                        "source": "selected-executable --list-devices"})
    if not devices:
        raise BackendError("The runtime returned no device result.")
    return devices


_REQUIRED_OPTIONS = ("--model", "--host", "--port", "--ctx-size", "--parallel", "--device",
                     "--n-gpu-layers", "--split-mode", "--batch-size", "--ubatch-size",
                     "--cache-type-k", "--cache-type-v", "--flash-attn", "--fit",
                     "--no-kv-offload", "--no-op-offload")


def inspect_llama_runtime(executable, cancelled=None):
    executable = Path(executable).resolve(strict=True)
    if not executable.is_file():
        raise BackendError("Select a llama-server executable file.")
    environment = llama_environment()
    identity = file_digest(executable, cancelled)
    version = _inspect_command(executable, "--version", environment, cancelled).strip()
    if not version or len(version) > 16384:
        raise BackendError("The runtime returned no usable build/version identity.")
    help_text = _inspect_command(executable, "--help", environment, cancelled)
    missing = [option for option in _REQUIRED_OPTIONS
               if re.search(re.escape(option) + r"(?=[\s,=\]])", help_text) is None]
    if missing:
        raise BackendError("This llama-server lacks required launch controls: " + ", ".join(missing))
    device_error = None
    try:
        devices = parse_llama_devices(_inspect_command(executable, "--list-devices", environment, cancelled))
    except BackendError as exc:
        _check_cancelled(cancelled)
        devices, device_error = [], str(exc)
    if file_digest(executable, cancelled) != identity:
        raise BackendError("The runtime executable changed during inspection.")
    return {"backend": "llama.cpp", "path": str(executable), "sha256": identity, "version": version,
            "file_revision": [executable.stat().st_size, executable.stat().st_mtime_ns],
            "environment_sha256": environment_digest(environment), "devices": devices, "device_error": device_error,
            "inspected_at": time.time(), "identity_scope": "selected local executable; dependent libraries unqualified"}


def validate_runtime_inspection(inspection, cancelled=None, *, rehash=True):
    _check_cancelled(cancelled)
    if not 0 <= time.time() - inspection["inspected_at"] <= 15:
        raise BackendError("Runtime inspection expired. Start again to recheck this computer.")
    current = Path(inspection["path"]).stat()
    if [current.st_size, current.st_mtime_ns] != inspection["file_revision"] or (
            rehash and file_digest(inspection["path"], cancelled) != inspection["sha256"]):
        raise BackendError("The runtime executable changed after inspection.")
    if environment_digest(llama_environment()) != inspection["environment_sha256"]:
        raise BackendError("The runtime environment changed after inspection.")


def gguf_metadata(path, cancelled=None, *, include_tokenizer=False):
    """Read bounded GGUF v2/v3 scalar metadata; skip token/tensor arrays."""
    started = time.monotonic()
    with Path(path).open("rb") as handle:
        def read(count):
            _check_cancelled(cancelled)
            if count < 0 or handle.tell() + count > 64 * 1024**2 or time.monotonic() - started > 8:
                raise BackendError("GGUF metadata exceeded the bounded inspection limit.")
            data = handle.read(count)
            if len(data) != count:
                raise BackendError("GGUF metadata is truncated.")
            return data
        def number(fmt):
            return struct.unpack("<" + fmt, read(struct.calcsize(fmt)))[0]
        def string():
            length = number("Q")
            if length > 2 * 1024**2:
                raise BackendError("GGUF metadata string is too large.")
            try:
                return read(length).decode("utf-8")
            except UnicodeError as exc:
                raise BackendError("GGUF metadata has invalid text.") from exc
        def value(kind, *, in_array=False):
            formats = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
            if kind in formats:
                return number(formats[kind])
            if kind == 8:
                return string()
            if kind == 9 and not in_array:
                element, count = number("I"), number("Q")
                if count > 1024 * 1024 or element not in (*formats, 8):
                    raise BackendError("GGUF metadata has an unsupported array.")
                if element in formats:
                    read(count * struct.calcsize(formats[element]))
                else:
                    for _ in range(count):
                        string()
                return None
            raise BackendError("GGUF metadata has an unsupported value type.")
        if read(4) != b"GGUF" or number("I") not in {2, 3}:
            raise BackendError("This model requires a supported GGUF v2/v3 header.")
        number("Q")  # Tensor count; tensor data is verified separately by hash.
        count = number("Q")
        if count > 100000:
            raise BackendError("GGUF metadata has too many fields.")
        result, seen = {}, set()
        for _ in range(count):
            key = string()
            if key in seen:
                raise BackendError("GGUF metadata contains duplicate keys.")
            seen.add(key)
            item = value(number("I"))
            if item is not None and (include_tokenizer or not key.startswith("tokenizer.")):
                result[key] = item
        return result


def model_memory(size_bytes, metadata=None, context_length=4096):
    if type(size_bytes) is not int or size_bytes <= 0:
        raise BackendError("Model weight size is unknown; no loading plan can be assessed.")
    if type(context_length) is not int or not 512 <= context_length <= 4096:
        raise BackendError("Resource estimates currently support 512 to 4096 context tokens.")
    metadata = metadata or {}
    architecture = metadata.get("general.architecture")
    kv = max(GIB // 2, (size_bytes + 3) // 4) * context_length // 4096
    method = "unverified size-based cache allowance"
    if architecture in {"llama", "qwen2", "qwen3"}:
        prefix = str(architecture) + "."
        values = [metadata.get(prefix + key) for key in
                  ("block_count", "embedding_length", "attention.head_count", "attention.head_count_kv")]
        if all(type(item) is int and 0 < item <= 1000000 for item in values):
            layers, embedding, heads, kv_heads = values
            key = metadata.get(prefix + "attention.key_length", embedding // heads)
            value = metadata.get(prefix + "attention.value_length", embedding // heads)
            if embedding % heads == 0 and kv_heads <= heads and all(type(item) is int and 0 < item <= embedding for item in (key, value)):
                kv = layers * kv_heads * (key + value) * 2 * context_length
                method = "dense attention metadata; f16 K/V, one slot, full context"
    context_limit = metadata.get(str(architecture) + ".context_length")
    if type(context_limit) is int and 0 < context_limit < context_length:
        raise BackendError("The selected context exceeds the model's reported context limit.")
    workspace = max(GIB, (size_bytes + 19) // 20)
    return {"weights_bytes": size_bytes, "kv_cache_bytes": kv, "workspace_bytes": workspace,
            "host_staging_bytes": max(GIB, min(size_bytes, 2 * GIB)),
            "total_bytes": size_bytes + kv + workspace, "context_length": context_length,
            "parallel": 1, "cache_type": "f16", "method": method, "verified": False,
            "limitation": "Estimate only; allocations and driver compatibility require a successful local load."}


def ram_budget(profile: HardwareProfile):
    total, available = profile.total_ram_bytes, profile.available_ram_bytes
    if type(total) is not int or type(available) is not int or not 0 <= available <= total or total <= 0:
        raise BackendError("Available physical RAM is unknown; recheck hardware before loading a model.")
    return min(max(0, available - GIB // 2), max(0, total - 2 * GIB))


def llama_launch_plan(record, profile, inspection, metadata=None):
    budget = ram_budget(profile)
    estimate = model_memory(record["size"], metadata)
    mode, selected = "cpu", None
    # Device memory comes from this executable/backend, not a different process's
    # DXGI budget or an unrelated GPU in the hardware inventory. Never pool GPUs.
    for device in sorted(inspection["devices"], key=lambda row: row["free_bytes"], reverse=True):
        if not re.fullmatch(r"(?:CUDA|Vulkan|HIP|ROCm|SYCL)\d+", device["id"]):
            continue  # Unknown/RPC/integrated backends need separate qualification.
        matches = [gpu for gpu in profile.gpus if gpu.name.strip().casefold() == device["name"].strip().casefold()
                   and gpu.backend in {"nvidia-smi", "DXGI process budget"}
                   and type(gpu.total_bytes) is int and gpu.total_bytes > 0]
        if len(matches) != 1:
            continue  # Shared/unified or ambiguous identity cannot count as dedicated VRAM.
        device = {**device, "total_bytes": min(device["total_bytes"], matches[0].total_bytes)}
        if matches[0].backend == "nvidia-smi" and type(matches[0].free_bytes) is int:
            device["free_bytes"] = min(device["free_bytes"], max(0, matches[0].free_bytes))
        gpu_budget = max(0, min(device["free_bytes"], device["total_bytes"] * 9 // 10) - GIB // 2)
        if estimate["total_bytes"] <= gpu_budget and estimate["host_staging_bytes"] + estimate["workspace_bytes"] <= budget:
            mode, selected = "gpu", device
            break
    if selected is None and estimate["total_bytes"] > budget:
        raise BackendError("Insufficient measured RAM and no compatible runtime device with enough memory. Select a smaller model or recheck hardware.")
    arguments = ["--model", record["path"], "--host", "127.0.0.1", "--port", "8081",
                 "--ctx-size", "4096", "--parallel", "1", "--batch-size", "512", "--ubatch-size", "128",
                 "--cache-type-k", "f16", "--cache-type-v", "f16", "--flash-attn", "off", "--fit", "off",
                 "--split-mode", "none", "--device", selected["id"] if selected else "none",
                 "--n-gpu-layers", "999" if selected else "0"]
    if selected is None:
        arguments.extend(["--no-kv-offload", "--no-op-offload"])
    return {"schema": "ceta.local-launch-plan.v1", "backend": "llama.cpp", "mode": mode,
            "program": inspection["path"], "runtime_sha256": inspection["sha256"],
            "runtime_version": inspection["version"], "environment_sha256": inspection["environment_sha256"],
            "runtime_identity_scope": inspection.get("identity_scope", "synthetic fixture"),
            "device_error": inspection.get("device_error"),
            "model_sha256": record["sha256"], "model_size": record["size"], "device": selected,
            "memory": estimate, "available_ram_budget": budget, "arguments": arguments,
            "assessed_at": time.time(), "verified": False}
