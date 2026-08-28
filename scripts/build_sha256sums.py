from __future__ import annotations

import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "SHA256SUMS"
EXCLUDED_FILES = {"data/ceta_curriculum_v3/source_adjudications.jsonl"}
EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".venv",
    ".venv-language-adapter",
    "ceta_controlled_evaluation",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    return (
        path.is_file()
        and not path.is_symlink()
        and rel.as_posix() != "SHA256SUMS"
        and rel.as_posix() not in EXCLUDED_FILES
        and not any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in rel.parts)
        and path.suffix not in {".pyc", ".pyo"}
    )


def candidate_files():
    for directory, directories, filenames in os.walk(ROOT):
        directories[:] = [
            name
            for name in directories
            if name not in EXCLUDED_PARTS and not name.endswith(".egg-info")
        ]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            if included(path):
                yield path


def main() -> None:
    rows=[]
    for path in sorted(candidate_files(), key=lambda item: item.relative_to(ROOT).as_posix()):
        rel=path.relative_to(ROOT)
        rows.append(f"{sha256(path)}  {rel.as_posix()}")
    OUT.write_text("\n".join(rows)+"\n",encoding="utf-8",newline="\n")
    print(f"SHA256SUMS WRITTEN files={len(rows)}")


if __name__ == "__main__":
    main()
