from __future__ import annotations

from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ceta_desktop.hardware import (  # noqa: E402
    GIB, GPUInfo, HardwareProfile, ModelOption, _nvidia_gpus, _run_inventory,
    assess_model, assess_models, format_hardware, inspect_hardware,
    local_model_option, recommended_model,
)


class HardwareAssessmentTests(unittest.TestCase):
    def test_cpu_fit_uses_current_free_physical_ram_with_headroom(self):
        small = ModelOption("small", GIB, 2 * GIB, "fixture")
        self.assertEqual(assess_model(HardwareProfile(16 * GIB, 3 * GIB, 8), small).mode, "cpu")
        self.assertEqual(assess_model(HardwareProfile(64 * GIB, 2 * GIB, 8), small).mode, "insufficient")

    def test_gpu_fit_uses_free_not_installed_vram(self):
        model = ModelOption("model", 5 * GIB, 7 * GIB, "fixture")
        busy = HardwareProfile(16 * GIB, 3 * GIB, 8, (GPUInfo("GPU", 24 * GIB, 2 * GIB, "fixture"),))
        free = HardwareProfile(16 * GIB, 3 * GIB, 8, (GPUInfo("GPU", 24 * GIB, 20 * GIB, "fixture"),))
        self.assertEqual(assess_model(busy, model).mode, "insufficient")
        self.assertEqual(assess_model(free, model).mode, "gpu")

    def test_gpu_still_requires_host_ram_headroom(self):
        profile = HardwareProfile(16 * GIB, GIB, 8, (GPUInfo("GPU", 24 * GIB, 20 * GIB, "fixture"),))
        self.assertEqual(assess_model(profile, ModelOption("model", GIB, 2 * GIB, "fixture")).mode, "insufficient")

    def test_multiple_gpus_are_not_silently_pooled(self):
        profile = HardwareProfile(16 * GIB, 3 * GIB, 8, tuple(GPUInfo("GPU", 8 * GIB, 8 * GIB, "fixture") for _ in range(4)))
        self.assertEqual(assess_model(profile, ModelOption("large", 14 * GIB, 20 * GIB, "fixture")).mode, "insufficient")

    def test_unmeasured_integrated_memory_is_not_added_to_ram(self):
        profile = HardwareProfile(16 * GIB, 3 * GIB, 8, (GPUInfo("Integrated GPU", None, None, "identity"),))
        self.assertEqual(assess_model(profile, ModelOption("large", 4 * GIB, 6 * GIB, "fixture")).mode, "insufficient")
        self.assertIn("unverified", format_hardware(profile))

    def test_more_free_gpu_memory_enables_larger_candidates(self):
        def profile(size):
            return HardwareProfile(32 * GIB, 4 * GIB, 8, (GPUInfo("GPU", size * GIB, size * GIB, "fixture"),))
        small, large = (max((item for item in assess_models(profile(size)) if item.mode == "gpu"),
                            key=lambda item: item.model.working_bytes) for size in (8, 24))
        self.assertEqual(small.mode, "gpu")
        self.assertEqual(large.mode, "gpu")
        self.assertGreater(large.model.working_bytes, small.model.working_bytes)

    def test_recommendation_prefers_gpu_fit_over_larger_cpu_fit(self):
        profile = HardwareProfile(128 * GIB, 100 * GIB, 8, (GPUInfo("GPU", 8 * GIB, 8 * GIB, "fixture"),))
        self.assertEqual(recommended_model(profile).mode, "gpu")
        self.assertEqual(recommended_model(profile).model.tag, "qwen3:4b-instruct-2507-q4_K_M")

    def test_unknown_or_invalid_ram_never_becomes_a_fit_claim(self):
        for total, available in ((None, None), (16 * GIB, None), (GIB, 2 * GIB), (-1, 0), (True, 1)):
            with self.subTest(total=total, available=available):
                profile = HardwareProfile(total, available, 8)
                self.assertIsNone(recommended_model(profile))
                self.assertTrue(all(item.mode == "unknown" for item in assess_models(profile)))

    def test_zero_free_ram_has_no_recommendation(self):
        self.assertIsNone(recommended_model(HardwareProfile(16 * GIB, 0, 8)))

    def test_unknown_quantizations_and_cloud_tags_are_not_catalog_guesses(self):
        self.assertIsNone(local_model_option("qwen3:8b-fp16"))
        self.assertIsNone(local_model_option("gpt-oss:120b-cloud"))
        self.assertIsNotNone(local_model_option("qwen3:8b-q4_K_M"))

    def test_nvidia_parser_supports_large_vram_without_32bit_truncation(self):
        gpu, = _nvidia_gpus('"NVIDIA fixture, GPU", 81920, 73728\n')
        self.assertEqual(gpu.total_bytes, 80 * GIB)
        self.assertEqual(gpu.free_bytes, 72 * GIB)

    def test_nvidia_unknown_and_impossible_values_fail_closed(self):
        for raw in ("GPU, N/A, N/A", "GPU, 10, 20", "GPU, -1, 0", "GPU, 0, 0", "GPU, 100"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _nvidia_gpus(raw)

    def test_inventory_failure_preserves_unknown_state(self):
        with patch("ceta_desktop.hardware._physical_memory", side_effect=OSError("unavailable")), \
                patch("ceta_desktop.hardware.shutil.which", return_value=None), \
                patch("ceta_desktop.hardware.Path.is_file", return_value=False), \
                patch("ceta_desktop.hardware._isolated_gpu_inventory", return_value=()), \
                patch("ceta_desktop.hardware._windows_gpu_names", side_effect=ValueError("unavailable")):
            profile = inspect_hardware()
        self.assertIsNone(profile.total_ram_bytes)
        self.assertIsNone(profile.available_ram_bytes)
        self.assertIsNone(recommended_model(profile))
        self.assertTrue(profile.warnings)

    @unittest.skipUnless(os.name == "nt", "Windows contained inventory")
    def test_inventory_process_is_bounded_and_does_not_use_shell(self):
        with patch("ceta_desktop.backends._inspect_contained_command", return_value="output") as run:
            self.assertEqual(_run_inventory(["inventory", "argument"]), "output")
        self.assertEqual(run.call_args.args[:2], ("inventory", ["argument"]))
        self.assertLessEqual(run.call_args.kwargs["timeout"], 8)
        self.assertEqual(run.call_args.kwargs["max_output"], 65536)
        self.assertNotIn("shell", run.call_args.kwargs)

    @unittest.skipUnless(os.name == "nt", "Windows GPU inventory integration")
    def test_native_budget_is_labelled_and_measured_nvidia_free_takes_precedence(self):
        with patch("ceta_desktop.hardware._physical_memory", return_value=(32 * GIB, 20 * GIB)), \
                patch("ceta_desktop.hardware.shutil.which", return_value="nvidia-smi"), \
                patch("ceta_desktop.hardware._run_inventory", return_value="Synthetic NVIDIA, 8192, 4096"), \
                patch("ceta_desktop.hardware._isolated_gpu_inventory", return_value=(
                    ("Synthetic NVIDIA", 8 * GIB, 7 * GIB), ("Synthetic AMD", 16 * GIB, 12 * GIB),
                )), patch("ceta_desktop.hardware._windows_gpu_names") as fallback:
            profile = inspect_hardware()
        fallback.assert_not_called()
        self.assertEqual(len(profile.gpus), 2)
        self.assertEqual(profile.gpus[0].free_bytes, 4 * GIB)
        self.assertEqual(profile.gpus[0].backend, "nvidia-smi")
        self.assertEqual(profile.gpus[1].free_bytes, 12 * GIB)
        self.assertEqual(profile.gpus[1].backend, "DXGI process budget")
        self.assertIn("available process budget", format_hardware(profile))
        self.assertIn("may differ", format_hardware(profile))


if __name__ == "__main__":
    unittest.main()
