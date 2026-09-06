"""Create checked library-source companions and collect their license notices."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def checked_sources(directory: Path) -> list[Path]:
    specification = json.loads((ROOT / "licenses/desktop-sources.json").read_text(encoding="utf-8"))
    sources = []
    for item in specification["archives"]:
        source = directory / item["filename"]
        with source.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != item["sha256"]:
            raise ValueError(f"Library source checksum mismatch: {source.name}")
        sources.append(source)
    return sources


def collect_source_notices(source: Path, destination: Path) -> int:
    count = 0
    # Keep installed paths short enough for Windows profiles without long-path
    # support. The index preserves the complete original source path for each text.
    label = re.sub(r"[^A-Za-z0-9_.-]", "_", source.name.split("-everywhere-src-")[0])[:24]
    output = destination / label
    index = {}
    with tarfile.open(source, "r:xz") as archive:
        members = {member.name: member for member in archive if member.isfile()}
        selected = {name for name in members if
                    PurePosixPath(name).name.lower().startswith(("license", "copying", "notice")) or
                    PurePosixPath(name).name.lower() in {"copyright", "qt_attribution.json", "qt_attributions.json"} or
                    "LICENSES" in PurePosixPath(name).parts}
        for name in sorted(selected, key=lambda item: members[item].offset_data):
            if PurePosixPath(name).name.lower() not in {"qt_attribution.json", "qt_attributions.json"}:
                continue
            # Qt's checked source archives contain literal newlines inside some
            # attribution strings. Preserve those files and accept that syntax.
            records = json.load(archive.extractfile(members[name]), strict=False)
            for record in records if isinstance(records, list) else [records]:
                license_file = record.get("LicenseFile")
                if isinstance(license_file, str):
                    referenced = posixpath.normpath(posixpath.join(posixpath.dirname(name), license_file))
                    if referenced in members:
                        selected.add(referenced)
        for name in sorted(selected, key=lambda item: members[item].offset_data):
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
                raise ValueError(f"Unsafe source notice path: {name}")
            filename = f"{count + 1:04d}-{re.sub(r'[^A-Za-z0-9_.-]', '_', relative.name)[:24]}.txt"
            target = output / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(members[name]) as reader, target.open("xb") as writer:
                writer.write(reader.read())
            count += 1
            index[filename] = name
    output.mkdir(parents=True, exist_ok=True)
    with (output / "INDEX.json").open("x", encoding="utf-8") as handle:
        json.dump({"source_archive": source.name, "notices": index}, handle, indent=2)
    return count


def write_source_companion(sources: list[Path], output: Path, notices: Path):
    for source in sources:
        collect_source_notices(source, notices / "Qt")
    guide = ROOT / "licenses/THIRD-PARTY-NOTICES.md"
    (notices / "THIRD-PARTY-NOTICES.md").write_bytes(guide.read_bytes())
    (notices / "desktop-sources.json").write_bytes((ROOT / "licenses/desktop-sources.json").read_bytes())
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as bundle:
        for source in sources:
            bundle.write(source, source.name)
        bundle.write(guide, guide.name)
        bundle.write(ROOT / "licenses/desktop-sources.json", "desktop-sources.json")
