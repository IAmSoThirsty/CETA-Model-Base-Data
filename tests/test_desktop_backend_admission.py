from __future__ import annotations

import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ceta_desktop.backends import (BackendError, _REQUIRED_OPTIONS, _inspect_command,
    environment_digest, file_digest, gguf_metadata, inspect_llama_runtime,
    llama_environment, llama_launch_plan, model_memory, parse_llama_devices,
    validate_runtime_inspection)
from ceta_desktop.hardware import GIB, GPUInfo, HardwareProfile


def write_gguf(path, fields=None):
    def string(value):
        encoded = value.encode()
        return struct.pack("<Q", len(encoded)) + encoded
    rows = []
    for key, value in (fields or {"general.architecture": "fixture"}).items():
        rows.append(string(key) + (struct.pack("<I", 8) + string(value) if isinstance(value, str)
                                  else struct.pack("<IQ", 10, value)))
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, len(rows)) + b"".join(rows))
    return path


def runtime_fixture(path, devices=None):
    path.write_bytes(b"synthetic runtime executable; never execute")
    return {"path": str(path), "sha256": file_digest(path), "version": "synthetic-test-build",
            "file_revision": [path.stat().st_size, path.stat().st_mtime_ns],
            "environment_sha256": environment_digest(llama_environment()),
            "inspected_at": time.time(), "devices": devices or []}


class BackendAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runtime = runtime_fixture(self.root / "runtime.exe")
        self.record = {"name": "fixture", "path": str(self.root / "model.gguf"), "size": 5 * GIB, "sha256": "a" * 64}

    @unittest.skipUnless(os.name == "nt", "Windows inspection containment requires Windows")
    def test_inspection_deadline_also_ends_child_workers(self):
        from ceta_desktop.runtime_coordination import process_identity
        marker = self.root / "worker.pid"
        script = self.root / "inspection.py"
        script.write_text("import subprocess,sys,time\nfrom pathlib import Path\n"
                          "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
                          f"Path({str(marker)!r}).write_text(str(child.pid))\n"
                          "time.sleep(30)\n")
        with self.assertRaisesRegex(BackendError, "deadline"):
            _inspect_command(sys._base_executable, str(script), llama_environment(), timeout=1)
        self.assertTrue(marker.exists())
        self.assertIsNone(process_identity(int(marker.read_text())))

    def test_runtime_device_inventory_is_strict_and_retains_backend_identity(self):
        rows = parse_llama_devices("backend log\nAvailable devices:\n  CUDA0: Test GPU (24576 MiB, 20480 MiB free)\n")
        self.assertEqual(rows[0]["id"], "CUDA0")
        self.assertEqual(rows[0]["free_bytes"], 20 * GIB)
        self.assertEqual(parse_llama_devices("Available devices:\n  (none)\n"), [])
        for raw in ("no device list", "Available devices:\n", "Available devices:\n  GPU: X (1 MiB, 2 MiB free)",
                    "Available devices:\n  CUDA0: X (1 MiB, 1 MiB free)\n  CUDA0: Y (1 MiB, 1 MiB free)"):
            with self.subTest(raw=raw), self.assertRaises(BackendError):
                parse_llama_devices(raw)

    def test_unrelated_gpu_cannot_justify_cpu_runtime_load(self):
        hardware = HardwareProfile(16 * GIB, 3 * GIB, 8, (GPUInfo("Test GPU", 24 * GIB, 20 * GIB, "nvidia-smi"),))
        with self.assertRaisesRegex(BackendError, "no compatible"):
            llama_launch_plan(self.record, hardware, self.runtime)

    def test_gpu_plan_selects_supported_device_without_pooling_ram_or_other_gpus(self):
        self.runtime["devices"] = parse_llama_devices("Available devices:\n  CUDA0: Test GPU (24576 MiB, 20480 MiB free)")
        hardware = HardwareProfile(16 * GIB, 4 * GIB, 8, (GPUInfo("Test GPU", 24 * GIB, 20 * GIB, "nvidia-smi"),))
        plan = llama_launch_plan(self.record, hardware, self.runtime)
        self.assertEqual(plan["mode"], "gpu")
        self.assertEqual(plan["device"]["id"], "CUDA0")
        args = plan["arguments"]
        for name, value in (("--device", "CUDA0"), ("--n-gpu-layers", "999"), ("--ctx-size", "4096"),
                            ("--parallel", "1"), ("--fit", "off"), ("--split-mode", "none"), ("--cache-type-k", "f16")):
            self.assertEqual(args[args.index(name) + 1], value)
        self.assertFalse(plan["verified"])

    def test_shared_ambiguous_busy_or_unsupported_devices_do_not_admit_gpu_plan(self):
        for gpu, device in (
            (GPUInfo("Integrated", 0, None, "DXGI process budget"), "Vulkan0: Integrated (24576 MiB, 20480 MiB free)"),
            (GPUInfo("Other GPU", 24 * GIB, 20 * GIB, "nvidia-smi"), "CUDA0: Test GPU (24576 MiB, 20480 MiB free)"),
            (GPUInfo("Test GPU", 24 * GIB, GIB, "nvidia-smi"), "CUDA0: Test GPU (24576 MiB, 20480 MiB free)"),
            (GPUInfo("Test GPU", 24 * GIB, 20 * GIB, "nvidia-smi"), "RPC0: Test GPU (24576 MiB, 20480 MiB free)"),
        ):
            with self.subTest(device=device):
                self.runtime["devices"] = parse_llama_devices("Available devices:\n  " + device)
                with self.assertRaises(BackendError):
                    llama_launch_plan(self.record, HardwareProfile(16 * GIB, 4 * GIB, 8, (gpu,)), self.runtime)
        gpu = GPUInfo("Test GPU", 24 * GIB, 20 * GIB, "nvidia-smi")
        self.runtime["devices"] = parse_llama_devices("Available devices:\n  CUDA0: Test GPU (24576 MiB, 20480 MiB free)")
        with self.assertRaises(BackendError):
            llama_launch_plan(self.record, HardwareProfile(16 * GIB, 4 * GIB, 8, (gpu, gpu)), self.runtime)

    def test_cpu_fallback_is_explicit_and_unknown_ram_never_starts(self):
        plan = llama_launch_plan(self.record, HardwareProfile(32 * GIB, 24 * GIB, 8), self.runtime)
        self.assertEqual(plan["mode"], "cpu")
        for arg in ("--no-kv-offload", "--no-op-offload"):
            self.assertIn(arg, plan["arguments"])
        self.assertEqual(plan["arguments"][plan["arguments"].index("--device") + 1], "none")
        with self.assertRaisesRegex(BackendError, "unknown"):
            llama_launch_plan(self.record, HardwareProfile(None, None, 8), self.runtime)

    def test_gpu_plan_rechecks_free_memory_and_never_combines_small_devices(self):
        self.runtime["devices"] = parse_llama_devices("Available devices:\n  CUDA0: GPU A (6144 MiB, 5120 MiB free)\n  CUDA1: GPU B (6144 MiB, 5120 MiB free)")
        hardware = HardwareProfile(16 * GIB, 4 * GIB, 8, (
            GPUInfo("GPU A", 6 * GIB, 5 * GIB, "nvidia-smi"), GPUInfo("GPU B", 6 * GIB, 5 * GIB, "nvidia-smi")))
        with self.assertRaises(BackendError):
            llama_launch_plan(self.record, hardware, self.runtime)
        self.runtime["devices"] = parse_llama_devices("Available devices:\n  CUDA0: GPU A (24576 MiB, 20480 MiB free)")
        hardware = HardwareProfile(16 * GIB, 4 * GIB, 8, (GPUInfo("GPU A", 24 * GIB, 20 * GIB, "nvidia-smi"),))
        self.assertEqual(llama_launch_plan(self.record, hardware, self.runtime)["mode"], "gpu")
        self.runtime["devices"][0]["free_bytes"] = GIB
        with self.assertRaises(BackendError):
            llama_launch_plan(self.record, hardware, self.runtime)

    def test_memory_components_use_dense_kv_metadata_and_expose_fallback(self):
        metadata = {"general.architecture": "qwen3", "qwen3.block_count": 32,
                    "qwen3.embedding_length": 4096, "qwen3.attention.head_count": 32,
                    "qwen3.attention.head_count_kv": 8, "qwen3.context_length": 32768}
        estimate = model_memory(5 * GIB, metadata)
        self.assertEqual(estimate["kv_cache_bytes"], 32 * 8 * (128 + 128) * 2 * 4096)
        self.assertEqual(estimate["total_bytes"], sum(estimate[key] for key in ("weights_bytes", "kv_cache_bytes", "workspace_bytes")))
        self.assertFalse(estimate["verified"])
        self.assertIn("unverified", model_memory(5 * GIB)["method"])
        metadata["qwen3.context_length"] = 2048
        with self.assertRaisesRegex(BackendError, "context"):
            model_memory(5 * GIB, metadata)

    def test_gguf_metadata_reads_scalars_and_rejects_unbounded_or_truncated_headers(self):
        path = write_gguf(self.root / "model.gguf", {"general.architecture": "qwen3", "qwen3.block_count": 32})
        self.assertEqual(gguf_metadata(path)["qwen3.block_count"], 32)
        for raw in (b"GGUF", b"GGUF" + struct.pack("<IQQ", 3, 0, 100001),
                    b"GGUF" + struct.pack("<IQQQ", 3, 0, 1, 100000000)):
            path.write_bytes(raw)
            with self.assertRaises(BackendError):
                gguf_metadata(path)

    def test_gguf_token_arrays_are_skipped_and_duplicate_or_nested_fields_rejected(self):
        def key(value):
            raw = value.encode()
            return struct.pack("<Q", len(raw)) + raw
        array = key("tokenizer.ggml.tokens") + struct.pack("<IIQ", 9, 8, 2) + key("one") + key("two")
        scalar = key("general.architecture") + struct.pack("<I", 8) + key("qwen3")
        path = self.root / "arrays.gguf"
        path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 2) + array + scalar)
        self.assertEqual(gguf_metadata(path), {"general.architecture": "qwen3"})
        path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 2) + scalar + scalar)
        with self.assertRaisesRegex(BackendError, "duplicate"):
            gguf_metadata(path)
        path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + key("nested") + struct.pack("<IIQ", 9, 9, 1))
        with self.assertRaisesRegex(BackendError, "array"):
            gguf_metadata(path)

    def test_inspection_binds_executable_version_options_devices_and_environment(self):
        replies = {"--version": "version: fixture", "--help": "\n".join(_REQUIRED_OPTIONS) + "\n",
                   "--list-devices": "Available devices:\n  (none)\n"}
        with patch("ceta_desktop.backends._inspect_command", side_effect=lambda _exe, arg, *_: replies[arg]):
            report = inspect_llama_runtime(self.runtime["path"])
            validate_runtime_inspection(report)
            replies["--list-devices"] = "unrecognized backend device response"
            cpu_only = inspect_llama_runtime(self.runtime["path"])
            self.assertEqual(cpu_only["devices"], [])
            self.assertIn("inventory", cpu_only["device_error"])
            replies["--help"] = "--model PATH\n"
            with self.assertRaisesRegex(BackendError, "launch controls"):
                inspect_llama_runtime(self.runtime["path"])
        Path(report["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(BackendError, "changed"):
            validate_runtime_inspection(report)

    def test_stale_environment_or_cancelled_inspection_cannot_launch(self):
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "new-device"}):
            with self.assertRaisesRegex(BackendError, "environment"):
                validate_runtime_inspection(self.runtime)
        self.runtime["inspected_at"] -= 60
        with self.assertRaisesRegex(BackendError, "expired"):
            validate_runtime_inspection(self.runtime)
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(BackendError, "stopped"):
            validate_runtime_inspection(self.runtime, event)

    def test_runtime_environment_removes_remote_and_extra_model_defaults(self):
        self.assertEqual(llama_environment({"PATH": "keep", "LLAMA_ARG_RPC": "remote", "LLAMA_ARG_HF_REPO": "download",
                                           "LLAMA_ARG_MODEL": "other", "GGML_RPC_SERVERS": "remote", "CUDA_VISIBLE_DEVICES": "0"}),
                         {"PATH": "keep", "CUDA_VISIBLE_DEVICES": "0"})

    def test_inspection_process_deadline_output_limit_and_cancel_are_bounded(self):
        script = self.root / "probe.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        before = time.monotonic()
        with self.assertRaisesRegex(BackendError, "deadline"):
            _inspect_command(sys.executable, str(script), llama_environment(), timeout=.15)
        self.assertLess(time.monotonic() - before, 3)
        script.write_text("import sys\nsys.stdout.write('x' * (2 * 1024 * 1024))\n", encoding="utf-8")
        with self.assertRaisesRegex(BackendError, "too much"):
            _inspect_command(sys.executable, str(script), llama_environment())
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        event = threading.Event()
        timer = threading.Timer(.15, event.set)
        timer.start()
        try:
            with self.assertRaisesRegex(BackendError, "stopped"):
                _inspect_command(sys.executable, str(script), llama_environment(), event)
        finally:
            timer.join()


if __name__ == "__main__":
    unittest.main()
