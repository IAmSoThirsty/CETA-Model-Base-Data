from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_FILES = {"data/ceta_curriculum_v3/source_adjudications.jsonl", ".github/instructions/codacy.instructions.md"}
EXCLUDED_PARTS = {
    ".codacy",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".venv",
    ".venv-language-adapter",
    "ceta_controlled_evaluation",
}


def safe_package_path(root: Path, relative: str) -> Path:
    """Reject nonportable, excluded, escaping, or linked package entries."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError(f"unsafe package path: {relative!r}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or pure.as_posix() != relative or ".." in pure.parts:
        raise ValueError(f"unsafe package path: {relative!r}")
    if relative in EXCLUDED_FILES or any(
        part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in pure.parts
    ) or pure.suffix in {".pyc", ".pyo"}:
        raise ValueError(f"excluded package path: {relative}")
    path = root
    for part in pure.parts:
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError(f"linked package path: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"escaping package path: {relative}")
    return path


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_root(files: list[dict]) -> str:
    raw=json.dumps(files,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode("utf-8")
    return "sha256:"+hashlib.sha256(b"ARCHITECTURE_REBUILD/PACKAGE_MANIFEST/v1\n"+raw).hexdigest()


def visible_files() -> set[str]:
    result=set()
    for directory, directories, filenames in os.walk(ROOT):
        directories[:] = [
            name
            for name in directories
            if name not in EXCLUDED_PARTS and not name.endswith(".egg-info")
        ]
        base=Path(directory)
        for filename in filenames:
            path=base/filename
            if not path.is_file() or path.is_symlink():
                continue
            rel=path.relative_to(ROOT)
            if (rel.as_posix() in EXCLUDED_FILES
                    or any(part in EXCLUDED_PARTS for part in rel.parts)
                    or path.suffix in {".pyc", ".pyo"}):
                continue
            result.add(rel.as_posix())
    return result


def main() -> None:
    errors=[]
    verify_controlled_payload(errors)
    manifest_path=ROOT/"PACKAGE_MANIFEST.json"
    sums_path=ROOT/"SHA256SUMS"
    if not manifest_path.is_file() or not sums_path.is_file():
        raise SystemExit("PACKAGE VERIFY: FAIL - PACKAGE_MANIFEST.json and SHA256SUMS are required")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    files=manifest.get("files",[])
    verify_manifest(manifest, files, errors)
    actual=verify_registered_files(files, errors)
    sums=read_sha256sums(sums_path, errors)
    verify_sha256sums(sums, actual, errors)
    if errors:
        print("PACKAGE VERIFY: FAIL")
        for error in errors: print(" -",error)
        raise SystemExit(1)
    print("PACKAGE VERIFY: PASS")
    print(f"files={len(actual)} registered_payload_files={len(files)} content_root={manifest['content_root']}")


def verify_controlled_payload(errors: list[str]) -> None:
    controlled_root=ROOT/"data"/"ceta_controlled_evaluation"
    if not (ROOT/".git").exists() and controlled_root.exists() and any(controlled_root.rglob("*")):
        errors.append("controlled evaluation payload is present in a release/extracted package")


def verify_manifest(manifest: dict, files: list[dict], errors: list[str]) -> None:
    if manifest.get("schema_version")!=1:
        errors.append("unsupported package manifest schema")
    if manifest.get("version")!=(ROOT/"VERSION").read_text(encoding="utf-8").strip():
        errors.append("manifest VERSION mismatch")
    if manifest.get("file_count")!=len(files):
        errors.append("manifest file_count mismatch")
    if manifest.get("content_root")!=manifest_root(files):
        errors.append("manifest content_root mismatch")


def verify_registered_files(files: list[dict], errors: list[str]) -> set[str]:
    expected={str(x.get("path")) for x in files}|{"PACKAGE_MANIFEST.json","SHA256SUMS"}
    actual=visible_files()
    missing=sorted(expected-actual); extra=sorted(actual-expected)
    if missing: errors.append(f"missing registered files: {missing}")
    if extra: errors.append(f"unregistered extra files: {extra}")
    seen=set()
    for item in files:
        if set(item)!={"path","size","sha256"}:
            errors.append(f"manifest entry field mismatch: {item.get('path')}"); continue
        rel=item["path"]
        if rel in seen: errors.append(f"duplicate manifest path: {rel}")
        seen.add(rel)
        try:
            path=safe_package_path(ROOT,rel)
        except ValueError as exc:
            errors.append(str(exc)); continue
        if not path.is_file(): continue
        if path.stat().st_size!=item["size"]: errors.append(f"size mismatch: {rel}")
        if sha256(path)!=item["sha256"]: errors.append(f"hash mismatch: {rel}")
    return actual


def read_sha256sums(sums_path: Path, errors: list[str]) -> dict[str, str]:
    sums={}
    for lineno,line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        try: digest, rel=line.split("  ",1)
        except ValueError: errors.append(f"invalid SHA256SUMS line {lineno}"); continue
        if rel in sums: errors.append(f"duplicate SHA256SUMS path: {rel}")
        sums[rel]=digest
    return sums


def verify_sha256sums(sums: dict[str, str], actual: set[str], errors: list[str]) -> None:
    expected_sums=actual-{"SHA256SUMS"}
    if set(sums)!=expected_sums:
        errors.append(f"SHA256SUMS path set mismatch missing={sorted(expected_sums-set(sums))} extra={sorted(set(sums)-expected_sums)}")
    for rel,digest in sums.items():
        try:
            path=safe_package_path(ROOT,rel)
        except ValueError as exc:
            errors.append(str(exc)); continue
        if path.is_file() and sha256(path)!=digest:
            errors.append(f"SHA256SUMS hash mismatch: {rel}")


if __name__=="__main__":
    main()
