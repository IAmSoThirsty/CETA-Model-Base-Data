from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "PACKAGE_MANIFEST.json"
EXCLUDED_FILES = {
    "PACKAGE_MANIFEST.json",
    "SHA256SUMS",
    "data/ceta_curriculum_v3/source_adjudications.jsonl",
}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", "ceta_controlled_evaluation"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if rel.as_posix() in EXCLUDED_FILES:
        return False
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if any(part.endswith(".egg-info") for part in rel.parts):
        return False
    if path.suffix in {".pyc", ".pyo"}:
        return False
    return path.is_file() and not path.is_symlink()


def manifest_root(files: list[dict]) -> str:
    raw = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(b"ARCHITECTURE_REBUILD/PACKAGE_MANIFEST/v1\n" + raw).hexdigest()


def main() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    files = []
    paths = (x for x in ROOT.rglob("*") if included(x))
    for path in sorted(paths, key=lambda item: item.relative_to(ROOT).as_posix()):
        rel = path.relative_to(ROOT).as_posix()
        files.append({"path": rel, "size": path.stat().st_size, "sha256": sha256(path)})
    payload = {
        "schema_version": 1,
        "package": "Architecture Rebuild — CETA Epoch-Ready Reference",
        "version": version,
        "file_count": len(files),
        "content_root": manifest_root(files),
        "files": files,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"PACKAGE MANIFEST WRITTEN files={len(files)} root={payload['content_root']}")


if __name__ == "__main__":
    main()
