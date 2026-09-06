from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import subprocess
import sys

if __package__:
    from .verify_package import safe_package_path
else:
    from verify_package import safe_package_path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "Architecture-Rebuild-CETA-Epoch-Ready-v0.3.0"


def registered_paths(root: Path) -> tuple[Path, ...]:
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    names = [item["path"] for item in manifest["files"]]
    names.extend(["PACKAGE_MANIFEST.json", "SHA256SUMS"])
    if len(names) != len(set(names)):
        raise ValueError("duplicate package path")
    paths = []
    for name in sorted(names):
        path = safe_package_path(root, name)
        if not path.is_file():
            raise ValueError(f"registered payload missing: {name}")
        paths.append(path)
    return tuple(paths)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise SystemExit("RELEASE ZIP: FAIL - output must be outside the repository")
    if output.exists():
        raise SystemExit(f"RELEASE ZIP: FAIL - output already exists: {output}")

    subprocess.run([sys.executable, str(ROOT / "scripts/verify_package.py")], cwd=ROOT, check=True)
    relative_paths = [path.relative_to(ROOT).as_posix() for path in registered_paths(ROOT)]
    archive_root = f"Architecture-Rebuild-CETA-Epoch-Ready-v{(ROOT / 'VERSION').read_text().strip()}"

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(relative_paths):
            info = zipfile.ZipInfo(f"{archive_root}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, (ROOT / relative).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    print("RELEASE ZIP: PASS")
    print(f"output={output}")
    print(f"files={len(relative_paths)}")
    print(f"sha256={sha256(output)}")


if __name__ == "__main__":
    main()
