"""Create a public, offline CETA verification bundle without accessing private keys."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import inspect
import json
from pathlib import Path
import re
import stat
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ceta_desktop.updates import (
    UpdateError, validate_manifest, verified_https, verify_manifest, version_tuple,
)

IDENTITY = {
    "schema_version": 1,
    "product": "CETA",
    "publisher": "IAmSoThirsty",
    "repository": "https://github.com/IAmSoThirsty/CETA-Model-Base-Data",
    "website": "https://www.thirstysystems.com/ceta",
    "algorithm": "Ed25519",
}
MAX_JSON_BYTES = 65536


def checked_path(path: Path) -> Path:
    """Reject traversal and filesystem redirects before following any input path."""
    if ".." in path.parts:
        raise ValueError("Parent traversal is not allowed in verification paths.")
    path = path.absolute()
    for part in (path, *path.parents):
        if part.name and (":" in part.name or part.is_reserved()):
            raise ValueError("Verification paths must name regular files or directories.")
        try:
            attributes = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(attributes.st_mode) or
                getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("Symlinks, junctions, and reparse points are not allowed.")
    return path


def unique_fields(pairs: list[tuple]) -> dict:
    """Reject duplicate JSON fields instead of choosing an ambiguous value."""
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate field in CETA verification metadata.")
        result[name] = value
    return result


def read_json(path: Path) -> tuple[bytes, dict]:
    """Read bounded public metadata and retain its original signed-envelope bytes."""
    path = checked_path(path)
    if not path.is_file():
        raise ValueError("CETA verification metadata must be a regular file.")
    with path.open("rb") as handle:
        data = handle.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("CETA verification metadata is too large.")
    return data, json.loads(data, object_pairs_hook=unique_fields)


def public_fingerprint(public_key: str) -> str:
    """Identify the raw 32-byte Ed25519 public key with SHA-256."""
    raw = base64.b64decode(public_key, validate=True)
    if len(raw) != 32:
        raise ValueError("The CETA public key must contain exactly 32 bytes.")
    return hashlib.sha256(raw).hexdigest()


def verify_installer(installer: Path, manifest: dict) -> None:
    """Read and hash installer bytes without executing or changing the file."""
    installer = checked_path(installer)
    if not installer.is_file():
        raise ValueError("The CETA installer must be a regular file.")
    if installer.name != f"CETA-{manifest['version']}-setup.exe":
        raise ValueError("The installer filename does not match the signed CETA version.")
    digest = hashlib.sha256()
    size = 0
    with installer.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            size += len(block)
            if size > manifest["size"]:
                raise ValueError("The installer exceeds its signed size.")
            digest.update(block)
    if size != manifest["size"] or not hmac.compare_digest(digest.hexdigest(), manifest["sha256"]):
        raise ValueError("The installer does not match its signed size and SHA-256.")


def verify_bundle(bundle: Path, installer: Path, trusted_fingerprint: str) -> dict:
    """Verify using a fingerprint obtained independently from the publisher."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", trusted_fingerprint):
        raise ValueError("Supply the 64-digit SHA-256 fingerprint received from the publisher.")
    bundle = checked_path(bundle)
    _, publisher = read_json(bundle / "CETA-PUBLISHER.json")
    fields = set(IDENTITY) | {"public_key", "public_key_sha256"}
    if not isinstance(publisher, dict) or set(publisher) != fields:
        raise ValueError("Unsupported CETA publisher identity fields.")
    if (isinstance(publisher["schema_version"], bool) or
            not isinstance(publisher["schema_version"], int)):
        raise ValueError("Unsupported CETA publisher identity schema.")
    if any(publisher[name] != value for name, value in IDENTITY.items()):
        raise ValueError("The publisher identity is not the expected CETA project.")
    actual = public_fingerprint(publisher["public_key"])
    if (publisher["public_key_sha256"] != actual or
            not hmac.compare_digest(actual, trusted_fingerprint.lower())):
        raise ValueError("The public key does not match the independently received fingerprint.")
    _, envelope = read_json(bundle / "CETA-UPDATE.json")
    manifest = verify_manifest(envelope, publisher["public_key"], "0.0.0")
    verify_installer(installer, manifest)
    return manifest


def verifier_source() -> bytes:
    """Ship readable source using the same canonical CETA verification functions."""
    imports = '''"""Offline CETA verification; never downloads or executes an installer."""
import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
'''
    functions = (
        UpdateError, verified_https, version_tuple, validate_manifest, verify_manifest,
        checked_path, unique_fields, read_json, public_fingerprint, verify_installer, verify_bundle,
    )
    source = imports + f"\nIDENTITY = {IDENTITY!r}\nMAX_JSON_BYTES = {MAX_JSON_BYTES}\n\n"
    source += "\n\n".join(inspect.getsource(function) for function in functions)
    source += '''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--trusted-fingerprint", required=True,
                        help="Public-key SHA-256 received independently from IAmSoThirsty")
    args = parser.parse_args()
    try:
        manifest = verify_bundle(Path(__file__).parent, args.installer, args.trusted_fingerprint)
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"VERIFICATION FAILED: {exc}") from None
    print(f"VERIFIED: CETA {manifest['version']} matches the independently pinned publisher key.")
    print("Installer SHA-256: " + manifest["sha256"])


if __name__ == "__main__":
    main()
'''
    return source.encode("utf-8")


def readme_text(manifest: dict, fingerprint: str) -> str:
    """Give recipients usable hash and independently pinned signature checks."""
    filename = f"CETA-{manifest['version']}-setup.exe"
    return f"""CETA personal publisher verification

Publisher: IAmSoThirsty
Project: {IDENTITY['repository']}
Website: {IDENTITY['website']}
Release: CETA {manifest['version']} for Windows x64
Installer: {filename}
Installer SHA-256: {manifest['sha256']}
Installer bytes: {manifest['size']}
Public-key SHA-256 fingerprint: {fingerprint}

Receive the public-key fingerprint independently from IAmSoThirsty, such as
through a personal message from a contact you already trust. Do not trust a
fingerprint solely because it appears in this downloaded bundle: an attacker
could replace both a download and the key beside it.

Put the installer beside the extracted verification files. In PowerShell, check:

Get-FileHash -LiteralPath '.\\{filename}' -Algorithm SHA256

Compare its Hash with the exact installer SHA-256 above. A hash match checks the
bytes; the offline signature check also binds those bytes to your trusted key.

The readable verify_ceta.py source requires Python 3.11 or later and the declared
cryptography dependency in requirements.txt. With those already available, run:

python -B .\\verify_ceta.py --installer '.\\{filename}' `
  --trusted-fingerprint '<fingerprint received independently>'

Replace the placeholder with the 64 hexadecimal digits received independently.
The verifier performs no network requests and never runs the installer. It checks
the expected CETA identity, key fingerprint, Ed25519 signature, filename, size,
and SHA-256. Any failure means this installation identity has not been verified.

This is a personal Ed25519 publisher signature. It does not provide Windows CA
trust or remove Windows unknown-publisher or SmartScreen notices.

CETA-UPDATE.json retains the original signed update envelope byte for byte.
CETA-PUBLISHER.json contains only public identity information, never a private key.
The ZIP uses fixed format-minimum timestamps for reproducibility; these are not
claims about when an installer or signature was created.
"""


def create_bundle(manifest_path: Path, public_key: str, installer: Path, output: Path) -> dict:
    """Validate all inputs before exclusively creating the requested new bundle."""
    output = checked_path(output)
    if output.exists():
        raise FileExistsError("Verification output exists; refusing to replace it.")
    if not output.parent.is_dir():
        raise ValueError("The new verification directory requires an existing parent.")
    fingerprint = public_fingerprint(public_key)
    original, envelope = read_json(manifest_path)
    manifest = verify_manifest(envelope, public_key, "0.0.0")
    verify_installer(installer, manifest)
    publisher = {**IDENTITY, "public_key": public_key, "public_key_sha256": fingerprint}
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency = next(item for item in project["project"]["dependencies"]
                      if re.match(r"^cryptography(?:[<>=!~;\[]|$)", item))
    contents = {
        "CETA-PUBLISHER.json": (json.dumps(publisher, indent=2) + "\n").encode("utf-8"),
        "CETA-UPDATE.json": original,
        "README.txt": readme_text(manifest, fingerprint).encode("utf-8"),
        "requirements.txt": (dependency + "\n").encode("utf-8"),
        "verify_ceta.py": verifier_source(),
    }
    output.mkdir()
    for name, data in contents.items():
        with (output / name).open("xb") as handle:
            handle.write(data)
    archive = output / f"CETA-{manifest['version']}-verification.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as handle:
        for name, data in sorted(contents.items()):
            # ZIP format minimum, not a fabricated release/signature timestamp.
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            handle.writestr(entry, data)
    return {"product": "CETA", "version": manifest["version"],
            "public_key_sha256": fingerprint, "installer_sha256": manifest["sha256"],
            "archive": str(archive)}


def main():
    """Accept public release inputs only; no private-key option exists."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--public-key", required=True, help="Base64 Ed25519 public key")
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New verification directory")
    args = parser.parse_args()
    try:
        result = create_bundle(args.manifest, args.public_key, args.installer, args.output)
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
