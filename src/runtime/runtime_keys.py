"""Application-owned local runtime keys; unrelated to publisher signing keys."""
from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path
import sqlite3

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from authority.ledger import _file_lock
from authority import AuthorityAssertion, TrustedAuthorityVerifier

from .journal import Journal, SCHEMA_VERSION


class RecoveryRequired(ValueError):
    """Startup must preserve existing data and offer recovery without authority."""


def _read_keys(path):
    try:
        if path.is_symlink():
            raise ValueError("Runtime identity cannot be a symbolic link")
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = "windows-dpapi-user" if os.name == "nt" else "owner-file"
        if raw.get("version") != 1 or raw.get("protection") != expected:
            raise ValueError("Unsupported local runtime key protection")
        body = base64.b64decode(raw["data"], validate=True)
        keys = json.loads((_dpapi(body, decrypt=True) if os.name == "nt" else body).decode("utf-8"))
        if set(keys) != {"authority", "identity", "gateway", "observer"}:
            raise ValueError("Runtime key set is incomplete")
        return {name: Ed25519PrivateKey.from_private_bytes(base64.b64decode(value, validate=True))
                for name, value in keys.items()}
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        raise RecoveryRequired("The local runtime identity is unreadable or inaccessible. "
            "Use the original Windows account and its matching identity backup; existing history was preserved.") from exc


def inspect_startup(directory: Path):
    """Read-only preflight, before migrations, recovery writes or key creation."""
    directory = Path(directory).resolve()
    path = directory / "runtime-identity.json"
    database = directory / "desktop.sqlite3"
    keys = _read_keys(path) if path.exists() or path.is_symlink() else None
    if not database.exists():
        return keys
    db = None
    journal = None
    try:
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RecoveryRequired("This database needs a newer CETA version. Keep this data folder and open it with that version.")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RecoveryRequired("The local database integrity check failed. Preserve the data folder for recovery.")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version == 0 and tables:
            raise RecoveryRequired("This database has an unrecognized schema. Preserve the original folder; "
                                   "it cannot be initialized as a fresh CETA installation.")
        if version == SCHEMA_VERSION and "task_events" not in tables:
            raise RecoveryRequired("The local database is missing its governed journal. Preserve it for recovery.")
        if "task_events" not in tables:
            return keys  # A legacy installation has no issued task authority.
        governed = db.execute("SELECT 1 FROM task_events WHERE task_id IS NOT NULL LIMIT 1").fetchone()
        if governed and keys is None:
            raise RecoveryRequired("The runtime identity is missing beside existing governed history. "
                "Restore the matching identity using the original Windows account; no replacement keys were created.")
        journal = Journal(database, read_only=True)
        if governed:
            verifier = TrustedAuthorityVerifier({"local-authority": keys["authority"].public_key()})
            for row in db.execute("SELECT project_id,task_id,payload FROM task_events WHERE kind='task.grant'"):
                raw = json.loads(row[2])
                assertion = AuthorityAssertion(**{**raw, "allowed_operations": tuple(raw["allowed_operations"]),
                                                   "capabilities": tuple(raw["capabilities"])})
                try:
                    # Expired/revoked history is legitimate; verify its original signer.
                    verifier.verify_for(assertion, input_state_ref=row[0] + ":" + row[1],
                                        operation="Context", now_epoch_ms=assertion.issued_at_epoch_ms)
                except ValueError as exc:
                    raise RecoveryRequired("The runtime identity does not match this database's authority. "
                        "Restore the matching identity and history together; no data was reset.") from exc
        return keys
    except RecoveryRequired:
        raise
    except (sqlite3.Error, ValueError, OSError, KeyError, TypeError) as exc:
        raise RecoveryRequired("The local database could not be verified. Preserve the entire data folder; "
            "restore into a separate folder to inspect a backup without replacing newer history.") from exc
    finally:
        if journal is not None:
            journal.close()
        if db is not None:
            db.close()


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
    existing = inspect_startup(directory)
    if existing is not None:
        return existing
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "runtime-identity.json"
    if path.is_symlink():
        raise ValueError("Runtime identity cannot be a symbolic link")
    names = ("authority", "identity", "gateway", "observer")
    with _file_lock(path):
        inspect_startup(directory)
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
        return _read_keys(path)
