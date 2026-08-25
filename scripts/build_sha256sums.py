from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "SHA256SUMS"
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    rows=[]
    paths = (x for x in ROOT.rglob("*") if x.is_file() and not x.is_symlink())
    for path in sorted(paths, key=lambda item: item.relative_to(ROOT).as_posix()):
        rel=path.relative_to(ROOT)
        if rel.as_posix()=="SHA256SUMS" or any(part in EXCLUDED_PARTS for part in rel.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        rows.append(f"{sha256(path)}  {rel.as_posix()}")
    OUT.write_text("\n".join(rows)+"\n",encoding="utf-8",newline="\n")
    print(f"SHA256SUMS WRITTEN files={len(rows)}")


if __name__ == "__main__":
    main()
