"""Offline hardware inventory and conservative model-memory estimates.

These estimates select candidates, not certify inference speed, quality, GPU
compatibility, or successful loading. No network requests or model downloads.
"""
from __future__ import annotations

import csv
import ctypes
from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from .hardware_windows import windows_gpu_inventory
from .request_control import ModelCancelledError, ModelDeadlineError, checkpoint, deadline_limit

GIB = 1024 ** 3
CONTEXT_TOKENS = 4096


@dataclass(frozen=True)
class GPUInfo:
    name: str
    total_bytes: int | None
    free_bytes: int | None
    backend: str


@dataclass(frozen=True)
class HardwareProfile:
    total_ram_bytes: int | None
    available_ram_bytes: int | None
    logical_cpus: int
    gpus: tuple[GPUInfo, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelOption:
    tag: str
    download_bytes: int
    working_bytes: int
    description: str


@dataclass(frozen=True)
class ModelAssessment:
    model: ModelOption
    mode: str
    reason: str


def _option(tag: str, size: int, description: str) -> ModelOption:
    return ModelOption(tag, size, math.ceil(size * 1.25) + GIB, description)


# Approximate decimal download sizes from the official Ollama tag pages, checked
# 2026-09-19. Explicit quantizations avoid silently switching Qwen precision.
# https://ollama.com/library/qwen3/tags
# https://ollama.com/library/gpt-oss/tags
# Working memory is CETA's estimate: weights * 1.25 + 1 GiB for a 4096-token
# context, one request and one loaded model. Actual runtime allocations vary.
MODEL_OPTIONS = (
    _option("qwen3:0.6b-q4_K_M", 523_000_000, "Small text assistant; limited reasoning and coding"),
    _option("qwen3:1.7b-q4_K_M", 1_400_000_000, "Lightweight drafting and short questions"),
    _option("qwen3:4b-instruct-2507-q4_K_M", 2_500_000_000, "General text chat and short code assistance"),
    _option("qwen3:8b-q4_K_M", 5_200_000_000, "Larger text and code assistant"),
    _option("qwen3:14b-q4_K_M", 9_300_000_000, "Larger reasoning and code candidate"),
    _option("gpt-oss:20b", 14_000_000_000, "Open-weight OpenAI text model; separate from ChatGPT"),
    _option("qwen3:32b-q4_K_M", 20_000_000_000, "Large text model; substantial memory required"),
    _option("gpt-oss:120b", 65_000_000_000, "Large open-weight text model; workstation-class memory"),
)


def local_model_option(name: str) -> ModelOption | None:
    # Only measured catalog tags qualify. Custom tags/quantizations require a
    # runtime check rather than guessing their size from a parameter-count name.
    return next((model for model in MODEL_OPTIONS if model.tag.casefold() == name.casefold()), None)


def _positive_bytes(value: object) -> bool:
    return type(value) is int and value > 0


def assess_model(profile: HardwareProfile, model: ModelOption) -> ModelAssessment:
    needed = model.working_bytes
    if not _positive_bytes(needed) or not _positive_bytes(model.download_bytes):
        return ModelAssessment(model, "unknown", "Model memory requirement is unknown; test the local runtime first.")
    ram = profile.available_ram_bytes
    total = profile.total_ram_bytes
    known_ram = (_positive_bytes(total) and type(ram) is int and 0 <= ram <= total)
    # Leave headroom in currently available RAM and total capacity. Do not count
    # swap as physical RAM or add shared/integrated GPU memory to system RAM.
    ram_budget = min(max(0, ram - GIB // 2), max(0, total - 2 * GIB)) if known_ram else 0
    for gpu in profile.gpus:
        if (_positive_bytes(gpu.total_bytes) and type(gpu.free_bytes) is int
                and 0 <= gpu.free_bytes <= gpu.total_bytes):
            gpu_budget = max(0, min(gpu.free_bytes, int(gpu.total_bytes * .9)) - GIB // 2)
            if needed <= gpu_budget and known_ram and ram_budget >= GIB:
                return ModelAssessment(model, "gpu", (
                    f"Estimated to fit {gpu.name} at {CONTEXT_TOKENS} context tokens; "
                    "GPU runtime support and actual speed still require a local test."
                ))
    if known_ram and needed <= ram_budget:
        return ModelAssessment(model, "cpu", (
            f"Estimated to fit available RAM at {CONTEXT_TOKENS} context tokens. "
            "CPU inference may be slow; GPU acceleration is unverified."
        ))
    if not known_ram:
        return ModelAssessment(model, "unknown", "Available physical RAM could not be measured; no fit claim is made.")
    return ModelAssessment(model, "insufficient", (
        f"Needs about {needed / GIB:.1f} GiB working memory plus headroom. "
        "Insufficient measured free memory now; close other applications, choose a smaller model, or recheck. "
        "Unmeasured GPU memory and multi-GPU pooling are not counted."
    ))


def assess_models(profile: HardwareProfile) -> tuple[ModelAssessment, ...]:
    return tuple(assess_model(profile, model) for model in MODEL_OPTIONS)


def recommended_model(profile: HardwareProfile) -> ModelAssessment | None:
    candidates = assess_models(profile)
    for mode in ("gpu", "cpu"):
        for tag in ("qwen3:4b-instruct-2507-q4_K_M", "qwen3:1.7b-q4_K_M", "qwen3:0.6b-q4_K_M"):
            for item in candidates:
                if item.model.tag == tag and item.mode == mode:
                    return item
    return None


def _physical_memory() -> tuple[int | None, int | None]:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (field, ctypes.c_uint64) for field in
                ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")
            ]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        query = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
        query.argtypes = [ctypes.POINTER(MemoryStatus)]
        query.restype = ctypes.c_int
        if not query(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return status.total, status.available
    if sys.platform.startswith("linux"):
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(rest.split()[0]) * 1024
        return values.get("MemTotal"), values.get("MemAvailable")
    return None, None


def _check_inventory(cancelled, deadline):
    checkpoint()
    if cancelled is not None and cancelled.is_set():
        raise ModelCancelledError("Hardware inspection cancelled.")
    if time.monotonic() >= deadline:
        raise ModelDeadlineError("Hardware inspection exceeded its time limit.")


def _run_inventory(command: list[str], *, cancelled=None, deadline=None) -> str:
    deadline = deadline_limit(min(deadline or float("inf"), time.monotonic() + 8))
    _check_inventory(cancelled, deadline)
    if os.name == "nt":
        from .backends import _inspect_contained_command
        class Cancellation:
            def is_set(self):
                _check_inventory(cancelled, deadline)
                return False
        return _inspect_contained_command(command[0], command[1:], dict(os.environ),
            Cancellation(), timeout=max(.001, deadline - time.monotonic()), max_output=65536)
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                _check_inventory(cancelled, deadline)
                if os.fstat(output.fileno()).st_size > 65536:
                    raise ValueError("Hardware inventory returned too much data")
                time.sleep(.02)
            _check_inventory(cancelled, deadline)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
            output.seek(0)
            data = output.read(65537)
            if len(data) > 65536:
                raise ValueError("Hardware inventory returned too much data")
            return data.decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)


def _nvidia_gpus(raw: str) -> tuple[GPUInfo, ...]:
    result = []
    for row in csv.reader(io.StringIO(raw)):
        if not row:
            continue
        if len(row) != 3 or not row[0].strip():
            raise ValueError("Malformed NVIDIA memory inventory")
        total, available = (int(value.strip()) * 1024 ** 2 for value in row[1:])
        if total <= 0 or not 0 <= available <= total:
            raise ValueError("Invalid NVIDIA memory inventory")
        result.append(GPUInfo(row[0].strip(), total, available, "nvidia-smi"))
    return tuple(result)


def _windows_gpu_names(*, cancelled=None, deadline=None) -> tuple[str, ...]:
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    command = [str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive", "-Command",
               "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
               "@(Get-CimInstance Win32_VideoController -ErrorAction Stop | "
               "ForEach-Object { $_.Name }) | ConvertTo-Json -Compress"]
    names = json.loads(_run_inventory(command, cancelled=cancelled, deadline=deadline).lstrip("\ufeff"))
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("Malformed Windows GPU inventory")
    return tuple(name.strip() for name in names if name.strip())


def _isolated_gpu_inventory(*, cancelled=None, deadline=None):
    arguments = (["--hardware-gpu-probe"] if getattr(sys, "frozen", False) else
                 ["-B", "-m", "ceta_desktop.hardware", "--gpu-probe"])
    rows = json.loads(_run_inventory([sys.executable, *arguments], cancelled=cancelled, deadline=deadline))
    if (not isinstance(rows, list) or len(rows) > 64 or any(
            not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str) or
            not 0 < len(row[0]) <= 256 or type(row[1]) is not int or row[1] < 0 or
            (row[2] is not None and (type(row[2]) is not int or not 0 <= row[2] <= row[1])) for row in rows)):
        raise ValueError("Malformed Windows GPU inventory")
    return tuple(tuple(row) for row in rows)


def gpu_probe():
    """Internal child entry; no Qt, model load, or persistent hardware profile."""
    data = json.dumps(windows_gpu_inventory()).encode("ascii")
    if os.name == "nt":
        # A frozen windowed executable has no Python stdout stream. Its explicit
        # inherited Win32 pipe still exists, including without a visible console.
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetStdHandle.argtypes, api.GetStdHandle.restype = [ctypes.c_uint32], ctypes.c_void_p
        api.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        api.WriteFile.restype = ctypes.c_int
        written = ctypes.c_uint32()
        if not api.WriteFile(api.GetStdHandle(0xFFFFFFF5), data, len(data), ctypes.byref(written), None) or written.value != len(data):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.write(1, data)
    return 0


def inspect_hardware(*, cancelled=None, deadline=None, include_gpus=True) -> HardwareProfile:
    deadline = deadline_limit(min(deadline or float("inf"), time.monotonic() + 20))
    _check_inventory(cancelled, deadline)
    warnings = []
    total = available = None
    try:
        total, available = _physical_memory()
    except (OSError, ValueError) as exc:
        warnings.append(f"Physical RAM query failed: {exc}")
    _check_inventory(cancelled, deadline)
    if total is None or available is None:
        warnings.append("Physical RAM availability is unknown on this system.")
    gpus: tuple[GPUInfo, ...] = ()
    if not include_gpus:
        return HardwareProfile(total, available, os.cpu_count() or 1, (), tuple(warnings))
    executable = shutil.which("nvidia-smi")
    if not executable and os.name == "nt":
        candidate = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/nvidia-smi.exe"
        if candidate.is_file():
            executable = str(candidate)
    if executable:
        try:
            gpus = _nvidia_gpus(_run_inventory([
                executable, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits",
            ], cancelled=cancelled, deadline=deadline))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            warnings.append(f"NVIDIA VRAM query failed: {exc}")
        _check_inventory(cancelled, deadline)
    if os.name == "nt":
        try:
            measured = {gpu.name.casefold() for gpu in gpus}
            native = _isolated_gpu_inventory(cancelled=cancelled, deadline=deadline)
            if native:
                gpus += tuple(GPUInfo(name, capacity, budget, "DXGI process budget")
                              for name, capacity, budget in native if name.casefold() not in measured)
            else:
                names = _windows_gpu_names(cancelled=cancelled, deadline=deadline)
                gpus += tuple(GPUInfo(name, None, None, "Windows identity only")
                              for name in names if name.casefold() not in measured)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            warnings.append(f"Windows GPU identification failed: {exc}")
        _check_inventory(cancelled, deadline)
    if any(gpu.free_bytes is None for gpu in gpus) or not gpus:
        warnings.append("Dedicated GPU free memory is unverified for unmeasured devices; shared RAM is not extra VRAM.")
    if any(gpu.backend == "DXGI process budget" for gpu in gpus):
        warnings.append("Windows GPU budgets belong to the CETA inventory process; the model service's budget may differ.")
    return HardwareProfile(total, available, os.cpu_count() or 1, gpus, tuple(warnings))


if __name__ == "__main__":
    if sys.argv[1:] != ["--gpu-probe"]:
        raise SystemExit("Use the CETA desktop to inspect hardware.")
    raise SystemExit(gpu_probe())


def format_hardware(profile: HardwareProfile) -> str:
    total = f"{profile.total_ram_bytes / GIB:.1f} GiB" if profile.total_ram_bytes is not None else "unknown"
    free = f"{profile.available_ram_bytes / GIB:.1f} GiB" if profile.available_ram_bytes is not None else "unknown"
    lines = [f"RAM: {total} total / {free} available · {profile.logical_cpus} logical CPUs"]
    for gpu in profile.gpus:
        if gpu.total_bytes is not None and gpu.free_bytes is not None:
            availability = "available process budget" if gpu.backend == "DXGI process budget" else "free"
            lines.append(f"GPU: {gpu.name} · {gpu.total_bytes / GIB:.1f} GiB dedicated / {gpu.free_bytes / GIB:.1f} GiB {availability}")
        else:
            lines.append(f"GPU: {gpu.name} · dedicated free VRAM unverified")
    lines.extend(profile.warnings)
    lines.append("Fit estimates are not a benchmark or a guarantee of model quality. Test the selected model locally.")
    return "\n".join(lines)
