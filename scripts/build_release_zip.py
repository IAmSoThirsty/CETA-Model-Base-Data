from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "Architecture-Rebuild-CETA-Epoch-Ready-v0.3.0"


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

    manifest = json.loads((ROOT / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    relative_paths = [str(item["path"]) for item in manifest.get("files", [])]
    relative_paths.extend(["PACKAGE_MANIFEST.json", "SHA256SUMS"])
    if len(relative_paths) != len(set(relative_paths)):
        raise SystemExit("RELEASE ZIP: FAIL - duplicate package path")
    if any(path.startswith("data/ceta_controlled_evaluation/") for path in relative_paths):
        raise SystemExit("RELEASE ZIP: FAIL - controlled evaluation entered package manifest")
    for relative in relative_paths:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"RELEASE ZIP: FAIL - registered payload missing or unsafe: {relative}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(relative_paths):
            info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
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
