from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "corpus" / "local_file_manifest.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def root_hash(entries: list[dict]) -> str:
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(b"ARCHITECTURE_REBUILD/CORPUS_MANIFEST/v1\n" + raw).hexdigest()


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    entries = data.get("files")
    if not isinstance(entries, list):
        raise SystemExit("CORPUS MANIFEST: FAIL - files is not a list")
    if data.get("file_count") != len(entries):
        errors.append("file_count does not match entries")
    seen: set[tuple[str, str]] = set()
    for i, item in enumerate(entries):
        verify_entry(i, item, seen, errors)
    expected = root_hash(entries)
    if data.get("manifest_root_hash") != expected:
        errors.append("manifest_root_hash mismatch")
    if errors:
        print("CORPUS MANIFEST: FAIL")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)
    print("CORPUS MANIFEST: PASS")
    print(f"files={len(entries)} root={expected}")


def verify_entry(index: int, item: dict, seen: set[tuple[str, str]], errors: list[str]) -> None:
    if set(item) != {"root", "relative_path", "size", "sha256"}:
        errors.append(f"entry {index} has unexpected fields")
        return
    key = (item["root"], item["relative_path"])
    if key in seen:
        errors.append(f"duplicate entry {key}")
    seen.add(key)
    if item["root"] not in {"uploaded", "local"}:
        errors.append(f"invalid root {item['root']}")
    if item["relative_path"].startswith("/") or ".." in Path(item["relative_path"]).parts:
        errors.append(f"unsafe relative path {item['relative_path']}")
    if not isinstance(item["size"], int) or item["size"] < 0:
        errors.append(f"invalid size for {item['relative_path']}")
    if not isinstance(item["sha256"], str) or not HEX64.fullmatch(item["sha256"]):
        errors.append(f"invalid sha256 for {item['relative_path']}")


if __name__ == "__main__":
    main()
