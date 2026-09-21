from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ceta_desktop import hardware_windows as dxgi  # noqa: E402

GIB = 1024 ** 3


def description(name="Synthetic GPU", dedicated=8 * GIB, *, software=False):
    value = dxgi._AdapterDescription()
    encoded = name.encode("utf-16-le")
    for index in range(len(encoded) // 2):
        value.description[index] = int.from_bytes(encoded[index * 2:index * 2 + 2], "little")
    value.dedicated_video_memory = dedicated
    value.dedicated_system_memory = 2 * GIB
    value.shared_system_memory = 32 * GIB
    value.flags = dxgi.SOFTWARE_ADAPTER if software else 0
    return value


class WindowsHardwareParsingTests(unittest.TestCase):
    def test_abi_sizes_and_offsets_match_windows_sdk(self):
        self.assertEqual(ctypes.sizeof(dxgi._GUID), 16)
        self.assertEqual(ctypes.sizeof(dxgi._LUID), 8)
        self.assertEqual(ctypes.sizeof(dxgi._VideoMemoryInfo), 32)
        self.assertEqual(dxgi._AdapterDescription.vendor_id.offset, 256)
        self.assertEqual(dxgi._AdapterDescription.dedicated_video_memory.offset, 272)
        self.assertEqual(ctypes.sizeof(dxgi._AdapterDescription), 312 if ctypes.sizeof(ctypes.c_size_t) == 8 else 296)

    def test_description_decodes_utf16_and_preserves_capacity_above_four_gib(self):
        total = 80 * GIB if ctypes.sizeof(ctypes.c_size_t) == 8 else 2 * GIB
        name, dedicated, available = dxgi._adapter_record(description("Synthetic Ω GPU", total))
        self.assertEqual(name, "Synthetic Ω GPU")
        self.assertEqual(dedicated, total)
        self.assertIsNone(available)

    def test_only_dedicated_video_memory_contributes_to_capacity(self):
        item = description()
        memory = dxgi._VideoMemoryInfo(64 * GIB, 0, 64 * GIB, 0)
        self.assertEqual(dxgi._adapter_record(item, memory), ("Synthetic GPU", 8 * GIB, 8 * GIB))

    def test_shared_only_adapter_does_not_acquire_dedicated_capacity(self):
        item = description("Synthetic integrated GPU", dedicated=0)
        memory = dxgi._VideoMemoryInfo(16 * GIB, GIB, 8 * GIB, 0)
        self.assertEqual(dxgi._adapter_record(item, memory), ("Synthetic integrated GPU", 0, None))

    def test_process_usage_is_subtracted_from_budget_and_clamped(self):
        for total, budget, used, expected in (
            (8 * GIB, 6 * GIB, 2 * GIB, 4 * GIB),
            (8 * GIB, 10 * GIB, GIB, 8 * GIB),
            (8 * GIB, GIB, 2 * GIB, 0),
            (8 * GIB, 0, 0, 0),
        ):
            with self.subTest(total=total, budget=budget, used=used):
                self.assertEqual(dxgi._remaining_budget(total, budget, used), expected)

    def test_invalid_or_unknown_capacity_never_becomes_budget(self):
        for values in ((0, GIB, 0), (None, GIB, 0), (GIB, -1, 0), (GIB, GIB, -1), (True, GIB, 0)):
            with self.subTest(values=values):
                self.assertIsNone(dxgi._remaining_budget(*values))

    def test_software_and_blank_adapters_are_excluded(self):
        self.assertIsNone(dxgi._adapter_record(description(software=True)))
        self.assertIsNone(dxgi._adapter_record(description("   ")))

    def test_unavailable_native_inventory_fails_to_unknown(self):
        with patch.object(dxgi.os, "name", "nt"), patch.object(dxgi, "_inventory", side_effect=OSError("unsupported")):
            self.assertEqual(dxgi.windows_gpu_inventory(), ())

    def test_other_platforms_do_not_load_windows_library(self):
        with patch.object(dxgi.os, "name", "posix"), patch.object(dxgi, "_inventory") as inventory:
            self.assertEqual(dxgi.windows_gpu_inventory(), ())
            inventory.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Native DXGI COM ABI requires Windows")
class WindowsHardwareNativeTests(unittest.TestCase):
    def test_adapter3_call_uses_local_node_zero_and_releases_interface(self):
        calls = []

        def method(pointer, slot, result, *arguments):
            if slot == 0:
                def query(this, iid, output):
                    self.assertEqual(bytes(ctypes.cast(iid, ctypes.POINTER(dxgi._GUID)).contents), bytes(dxgi._ADAPTER3))
                    ctypes.cast(output, ctypes.POINTER(dxgi.POINTER))[0] = dxgi.POINTER(2)
                    return 0
                return query
            if slot == 14:
                def budget(this, node, group, output):
                    calls.append((node, group))
                    value = ctypes.cast(output, ctypes.POINTER(dxgi._VideoMemoryInfo)).contents
                    value.budget, value.current_usage = 6 * GIB, 2 * GIB
                    return 0
                return budget
            if slot == 2:
                return lambda this: calls.append("release") or 0
            self.fail(f"Unexpected COM method {slot}")

        with patch.object(dxgi, "_method", side_effect=method):
            memory = dxgi._query_budget(dxgi.POINTER(1))
        self.assertEqual((memory.budget, memory.current_usage), (6 * GIB, 2 * GIB))
        self.assertEqual(calls, [(0, 0), "release"])

    def test_missing_adapter3_interface_returns_unknown(self):
        with patch.object(dxgi, "_method", return_value=lambda *args: -2147467262):
            self.assertIsNone(dxgi._query_budget(dxgi.POINTER(1)))

    def test_failed_budget_query_releases_interface_and_returns_unknown(self):
        released = []

        def method(pointer, slot, result, *arguments):
            if slot == 0:
                def query(this, iid, output):
                    ctypes.cast(output, ctypes.POINTER(dxgi.POINTER))[0] = dxgi.POINTER(2)
                    return 0
                return query
            if slot == 14:
                return lambda *args: -1
            if slot == 2:
                return lambda this: released.append(this.value) or 0
            self.fail(f"Unexpected COM method {slot}")

        with patch.object(dxgi, "_method", side_effect=method):
            self.assertIsNone(dxgi._query_budget(dxgi.POINTER(1)))
        self.assertEqual(released, [2])

    def test_real_read_only_inventory_returns_valid_records_or_unknown(self):
        # No machine name, capacity, availability, or GPU count is assumed or saved.
        for name, dedicated, available in dxgi.windows_gpu_inventory():
            self.assertTrue(name.strip())
            self.assertIs(type(dedicated), int)
            self.assertGreaterEqual(dedicated, 0)
            if available is not None:
                self.assertIs(type(available), int)
                self.assertGreaterEqual(available, 0)
                self.assertLessEqual(available, dedicated)


if __name__ == "__main__":
    unittest.main()
