"""Sign a CETA release manifest using an explicit PEM or Windows-protected key."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from desktop_update_keys import load_protected_key
from ceta_desktop.updates import verified_https, version_tuple


def main():
    """Authenticate update metadata with the explicitly selected publisher key."""
    parser = argparse.ArgumentParser(description="Create a publisher-signed CETA update manifest")
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True)
    keys = parser.add_mutually_exclusive_group(required=True)
    keys.add_argument("--private-key", type=Path,
                      help="Publisher-owned Ed25519 PEM key; keep outside this repository")
    keys.add_argument("--protected-private-key", type=Path,
                      help="CETA DPAPI key file outside this repository; current Windows user")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version_tuple(args.version)
    verified_https(args.url)
    if args.output.exists():
        raise SystemExit("Output exists; refusing to replace it.")
    if args.protected_private_key:
        try:
            key = load_protected_key(args.protected_private_key)
        except (OSError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
    else:
        key = load_pem_private_key(args.private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("The publisher key must be Ed25519.")
    with args.installer.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    manifest = {"schema_version": 1, "product": "CETA", "version": args.version,
                "platform": "windows-x64", "url": args.url, "sha256": digest,
                "size": args.installer.stat().st_size}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode()
    signature = base64.b64encode(key.sign(b"CETA/UPDATE/v1\n" + canonical)).decode()
    envelope = {"manifest": manifest, "signature": signature}
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(envelope, handle, indent=2)
    print(f"Signed update manifest written: {args.output}")


if __name__ == "__main__":
    main()
