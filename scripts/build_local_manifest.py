from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "corpus" / "local_file_manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_entries_hash(entries: list[dict]) -> str:
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(b"ARCHITECTURE_REBUILD/CORPUS_MANIFEST/v1\n" + raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the offline evidence-corpus manifest from an explicitly supplied local corpus root.")
    parser.add_argument("--corpus-root", required=True, help="Root containing optional uploaded/ and local/ subdirectories")
    args = parser.parse_args()
    work = Path(args.corpus_root).resolve()
    roots = [work / "uploaded", work / "local"]
    entries: list[dict] = []
    for root in roots:
        if not root.exists():
            continue
        paths = (x for x in root.rglob("*") if x.is_file() and not x.is_symlink())
        for p in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
            entries.append({
                "root": root.name,
                "relative_path": p.relative_to(root).as_posix(),
                "size": p.stat().st_size,
                "sha256": sha256(p),
            })
    payload = {
        "schema_version": 2,
        "file_count": len(entries),
        "manifest_root_hash": canonical_entries_hash(entries),
        "files": entries,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"WROTE {OUT} ({len(entries)} files) root={payload['manifest_root_hash']}")


if __name__ == "__main__":
    main()
