"""Application-owned local runtime keys; unrelated to publisher signing keys."""
from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from authority.ledger import _file_lock


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, decrypt=False):
    source = ctypes.create_string_buffer(data)
    source_blob = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    if decrypt:
        call = ctypes.windll.crypt32.CryptUnprotectData
        call.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_Blob)]
        ok = call(ctypes.byref(source_blob), None, None, None, None, 1, ctypes.byref(output))
    else:
        call = ctypes.windll.crypt32.CryptProtectData
        call.argtypes = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_Blob)]
        ok = call(ctypes.byref(source_blob), "CETA local runtime identity", None, None, None, 1, ctypes.byref(output))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output.data)


def runtime_keys(directory: Path):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "runtime-identity.json"
    if path.is_symlink():
        raise ValueError("Runtime identity cannot be a symbolic link")
    names = ("authority", "identity", "gateway", "observer")
    with _file_lock(path):
        if not path.exists():
            body = json.dumps({name: base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode("ascii")
                               for name in names}, sort_keys=True).encode("utf-8")
            record = {"version": 1, "protection": "windows-dpapi-user" if os.name == "nt" else "owner-file",
                      "data": base64.b64encode(_dpapi(body) if os.name == "nt" else body).decode("ascii")}
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = "windows-dpapi-user" if os.name == "nt" else "owner-file"
        if raw.get("version") != 1 or raw.get("protection") != expected:
            raise ValueError("Unsupported local runtime key protection")
        body = base64.b64decode(raw["data"], validate=True)
        keys = json.loads((_dpapi(body, decrypt=True) if os.name == "nt" else body).decode("utf-8"))
        if set(keys) != set(names):
            raise ValueError("Runtime key set is incomplete")
        return {name: Ed25519PrivateKey.from_private_bytes(base64.b64decode(value, validate=True))
                for name, value in keys.items()}

