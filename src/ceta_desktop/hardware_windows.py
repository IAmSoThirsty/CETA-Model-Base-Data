"""Read-only DXGI adapter inventory; budgets are not global free VRAM.

No inference device is created, no memory is reserved, and no profile is saved.
The budget belongs to this process; another process such as Ollama can receive a
different budget. Shared/system memory never contributes to dedicated capacity.

ABI: Microsoft's WinSDK dxgi.h / dxgi1_4.h (win32metadata repository).
https://learn.microsoft.com/windows/win32/api/dxgi/ns-dxgi-dxgi_adapter_desc1
https://learn.microsoft.com/windows/win32/api/dxgi1_4/ns-dxgi1_4-dxgi_query_video_memory_info
"""
from __future__ import annotations

import ctypes
import os
import uuid

UINT = ctypes.c_uint32
HRESULT = ctypes.c_int32
POINTER = ctypes.c_void_p
SOFTWARE_ADAPTER = 2
DXGI_ERROR_NOT_FOUND = 0x887A0002


class _GUID(ctypes.Structure):
    _fields_ = [("data1", UINT), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]


class _LUID(ctypes.Structure):
    _fields_ = [("low", UINT), ("high", ctypes.c_int32)]


class _AdapterDescription(ctypes.Structure):
    _fields_ = [
        ("description", ctypes.c_uint16 * 128),
        ("vendor_id", UINT), ("device_id", UINT), ("subsystem_id", UINT), ("revision", UINT),
        ("dedicated_video_memory", ctypes.c_size_t), ("dedicated_system_memory", ctypes.c_size_t),
        ("shared_system_memory", ctypes.c_size_t), ("luid", _LUID), ("flags", UINT),
    ]


class _VideoMemoryInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("budget", "current_usage", "available_for_reservation", "current_reservation")]


_FACTORY1 = _GUID.from_buffer_copy(uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
_ADAPTER3 = _GUID.from_buffer_copy(uuid.UUID("645967a4-1392-4310-a798-8053ce3e93fd").bytes_le)


def _method(pointer, slot, result, *arguments):
    if not pointer:
        raise OSError("DXGI returned a null interface")
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(POINTER))).contents
    if not table or not table[slot]:
        raise OSError("DXGI returned an invalid interface")
    return ctypes.WINFUNCTYPE(result, POINTER, *arguments)(table[slot])


def _release(pointer):
    if pointer:
        _method(pointer, 2, UINT)(pointer)


def _remaining_budget(dedicated: int, budget: int, usage: int) -> int | None:
    if any(type(value) is not int or value < 0 for value in (dedicated, budget, usage)) or dedicated == 0:
        return None
    return min(dedicated, max(0, budget - usage))


def _adapter_record(description, memory=None):
    if description.flags & SOFTWARE_ADAPTER:
        return None
    name = bytes(description.description).decode("utf-16-le").split("\0", 1)[0].strip()
    if not name:
        return None
    dedicated = int(description.dedicated_video_memory)
    available = None if memory is None else _remaining_budget(dedicated, int(memory.budget), int(memory.current_usage))
    return name, dedicated, available


def _query_budget(adapter):
    extended = POINTER()
    try:
        query = _method(adapter, 0, HRESULT, ctypes.POINTER(_GUID), ctypes.POINTER(POINTER))
        if query(adapter, ctypes.byref(_ADAPTER3), ctypes.byref(extended)) < 0 or not extended:
            return None
        memory = _VideoMemoryInfo()
        query_memory = _method(extended, 14, HRESULT, UINT, UINT, ctypes.POINTER(_VideoMemoryInfo))
        # Node zero only; DXGI_MEMORY_SEGMENT_GROUP_LOCAL == 0. No pooling.
        if query_memory(extended, 0, 0, ctypes.byref(memory)) < 0:
            return None
        return memory
    except (OSError, ValueError):
        return None
    finally:
        _release(extended)


def _inventory():
    # LOAD_LIBRARY_SEARCH_SYSTEM32 excludes application/current-directory DLLs.
    library = ctypes.WinDLL("dxgi.dll", winmode=0x00000800)
    create = library.CreateDXGIFactory1
    create.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(POINTER)]
    create.restype = HRESULT
    factory = POINTER()
    records = []
    try:
        if create(ctypes.byref(_FACTORY1), ctypes.byref(factory)) < 0 or not factory:
            raise OSError("DXGI factory unavailable")
        enumerate_adapter = _method(factory, 12, HRESULT, UINT, ctypes.POINTER(POINTER))
        for index in range(64):
            adapter = POINTER()
            try:
                result = enumerate_adapter(factory, index, ctypes.byref(adapter))
                if result & 0xFFFFFFFF == DXGI_ERROR_NOT_FOUND:
                    return tuple(records)
                if result < 0 or not adapter:
                    raise OSError("DXGI adapter enumeration failed")
                description = _AdapterDescription()
                get_description = _method(adapter, 10, HRESULT, ctypes.POINTER(_AdapterDescription))
                if get_description(adapter, ctypes.byref(description)) < 0:
                    continue
                if description.flags & SOFTWARE_ADAPTER:
                    continue
                record = _adapter_record(description, _query_budget(adapter))
                if record is not None:
                    records.append(record)
            finally:
                _release(adapter)
        raise OSError("DXGI adapter enumeration exceeded its bound")
    finally:
        _release(factory)


def windows_gpu_inventory() -> tuple[tuple[str, int, int | None], ...]:
    """Return (name, dedicated bytes, available process budget) or unknown ()."""
    if os.name != "nt":
        return ()
    try:
        return _inventory()
    except (OSError, ValueError, AttributeError):
        return ()
