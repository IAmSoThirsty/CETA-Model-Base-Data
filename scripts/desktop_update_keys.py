"""
Create and read CETA update keys protected for the current Windows user.

Plaintext private bytes are never written to disk or printed. Python and the
cryptography library do not guarantee erasure of every temporary memory copy.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hmac
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

ROOT = Path(__file__).resolve().parents[1]
ENTROPY = b"CETA/DESKTOP-UPDATE-KEY/v1\n"
MAX_KEY_FILE_BYTES = 65536
PROTECTION = "windows-dpapi-current-user"


class _DataBlob(ctypes.Structure):

    """Windows DATA_BLOB layout, including pointer alignment on x64."""

    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """Use DPAPI without machine-wide scope or an interactive credential prompt."""
    if os.name != "nt":
        raise ValueError("Protected update keys require Windows DPAPI.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    operation.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
    ]
    operation.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    input_buffer = ctypes.create_string_buffer(data)
    entropy_buffer = ctypes.create_string_buffer(ENTROPY)
    input_blob = _DataBlob(len(data), ctypes.addressof(input_buffer))
    entropy_blob = _DataBlob(len(ENTROPY), ctypes.addressof(entropy_buffer))
    output_blob = _DataBlob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN=1; never set CRYPTPROTECT_LOCAL_MACHINE=4.
        if not operation(ctypes.byref(input_blob), None, ctypes.byref(entropy_blob),
                         None, None, 1, ctypes.byref(output_blob)):
            action = "protect" if protect else "decrypt"
            raise ValueError(f"Windows DPAPI could not {action} this key for the current user.")
        if not output_blob.data or not 0 < output_blob.size <= MAX_KEY_FILE_BYTES:
            raise ValueError("Windows DPAPI returned an invalid key payload.")
        return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        ctypes.memset(input_buffer, 0, ctypes.sizeof(input_buffer))
        if output_blob.data:
            ctypes.memset(output_blob.data, 0, output_blob.size)
            kernel32.LocalFree(output_blob.data)


def _external_path(path: Path) -> Path:
    """Resolve existing junctions and reject this repository as a key location."""
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT):
        raise ValueError("Private update keys must be stored outside the CETA repository.")
    if os.name == "nt" and (":" in resolved.name or resolved.is_reserved()):
        raise ValueError("The update key requires a regular external file path.")
    return resolved


def public_key_text(key: Ed25519PrivateKey) -> str:
    """Return the base64 public key accepted by the CETA update verifier."""
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(public).decode("ascii")


def generate_protected_key(path: Path) -> dict:
    """Create a new external protected key, refusing any existing destination."""
    target = _external_path(path)
    if target.exists():
        raise FileExistsError("Update key exists; refusing to replace it.")
    if not target.parent.is_dir():
        raise ValueError("Create the external key directory before generating the key.")
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    protected = _dpapi(raw, protect=True)
    del raw
    public = public_key_text(key)
    record = {
        "schema_version": 1, "product": "CETA", "algorithm": "Ed25519",
        "protection": PROTECTION, "public_key": public,
        "protected_private_key": base64.b64encode(protected).decode("ascii"),
    }
    # Exclusive creation closes the race with another writer; only ciphertext
    # and public metadata enter this file. Failures never delete an unknown file.
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"product": "CETA", "algorithm": "Ed25519", "protection": PROTECTION,
            "public_key": public}


def _unique_fields(pairs: list[tuple]) -> dict:
    """Reject ambiguous protected-key JSON before interpreting its metadata."""
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate field in protected update key.")
        result[name] = value
    return result


def load_protected_key(path: Path) -> Ed25519PrivateKey:
    """Decrypt only in memory, then bind the private key to its public metadata."""
    with _external_path(path).open("rb") as handle:
        data = handle.read(MAX_KEY_FILE_BYTES + 1)
    if len(data) > MAX_KEY_FILE_BYTES:
        raise ValueError("The protected update key file is too large.")
    try:
        record = json.loads(data, object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeError):
        raise ValueError("Invalid protected update key JSON.") from None
    expected = {"schema_version", "product", "algorithm", "protection",
                "public_key", "protected_private_key"}
    if not isinstance(record, dict) or set(record) != expected:
        raise ValueError("Unsupported protected update key fields.")
    if (not isinstance(record["schema_version"], int)
            or isinstance(record["schema_version"], bool) or record["schema_version"] != 1):
        raise ValueError("Unsupported protected update key schema.")
    if (record["product"] != "CETA" or record["algorithm"] != "Ed25519"
            or record["protection"] != PROTECTION):
        raise ValueError("Unsupported protected update key format or product.")
    try:
        public = base64.b64decode(record["public_key"], validate=True)
        protected = base64.b64decode(record["protected_private_key"], validate=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid protected update key encoding.") from None
    if len(public) != 32 or not protected:
        raise ValueError("Invalid protected update key length.")
    raw = _dpapi(protected, protect=False)
    try:
        key = Ed25519PrivateKey.from_private_bytes(raw)
    except ValueError:
        raise ValueError("Decrypted update key is not an Ed25519 private key.") from None
    finally:
        del raw
    actual_public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if not hmac.compare_digest(actual_public, public):
        raise ValueError("The protected update key does not match its public key.")
    return key


def main():
    """Generate only when explicitly invoked; print public metadata only."""
    parser = argparse.ArgumentParser(description="Create a Windows-protected CETA update key")
    parser.add_argument("--output", type=Path, required=True,
                        help="New key file outside this repository; never overwritten")
    args = parser.parse_args()
    try:
        metadata = generate_protected_key(args.output)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
