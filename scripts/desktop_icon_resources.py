"""Reject missing, default, or mismatched Windows executable icon resources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


def verify_pe_icons(executable: Path, icon_path: Path) -> dict:
    """Read PE resources without loading or executing the inspected executable."""
    import pefile
    from desktop_icons import verify_ico

    sizes = verify_ico(icon_path)
    expected = {}
    raw = icon_path.read_bytes()
    for index, size in enumerate(sizes):
        row = struct.unpack_from("<BBBBHHII", raw, 6 + index * 16)
        expected[size] = (row[:7], raw[row[7]:row[7] + row[6]])
    with pefile.PE(str(executable), fast_load=True) as pe:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        resources = {3: {}, 14: {}}
        for kind in getattr(getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None), "entries", []):
            if kind.id not in resources:
                continue
            for identifier in kind.directory.entries:
                for language in identifier.directory.entries:
                    data = language.data.struct
                    key = (identifier.id if identifier.id is not None else str(identifier.name), language.id)
                    if key in resources[kind.id]:
                        raise ValueError("Duplicate executable icon resource.")
                    resources[kind.id][key] = pe.get_data(data.OffsetToData, data.Size)
    icons, groups = resources[3], resources[14]
    if len(groups) != 1 or len(icons) != len(sizes):
        raise ValueError("Executable must contain one complete CETA icon group and no extra icon images.")
    referenced = set()
    frames = []
    for (_, language), group in groups.items():
        if len(group) != 6 + len(sizes) * 14 or struct.unpack_from("<HHH", group) != (0, 1, len(sizes)):
            raise ValueError("Executable icon group is incomplete or malformed.")
        for index in range(len(sizes)):
            row = struct.unpack_from("<BBBBHHIH", group, 6 + index * 14)
            size = row[0] or 256
            resource_key = (row[7], language)
            data = icons.get(resource_key)
            if size not in expected or row[:7] != expected[size][0] or data != expected[size][1]:
                raise ValueError(f"Executable {size}px icon differs from the approved CETA icon.")
            if resource_key in referenced or size in [frame["size"] for frame in frames]:
                raise ValueError("Duplicate executable icon frame.")
            referenced.add(resource_key)
            frames.append({"size": size, "encoding": "PNG" if data.startswith(b"\x89PNG") else "DIB",
                           "sha256": hashlib.sha256(data).hexdigest()})
    if referenced != set(icons) or {frame["size"] for frame in frames} != set(sizes):
        raise ValueError("Executable contains missing or unreferenced icon images.")
    return {"file": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "ico_sha256": hashlib.sha256(raw).hexdigest(), "frames": frames, "status": "PASS"}


def uninstaller_icon_finalize(icon_path: Path, report_path: Path) -> str:
    """Require icon verification before NSIS embeds the generated uninstaller."""
    arguments = [sys.executable, "-B", str(Path(__file__).resolve()),
                 "--ico", str(icon_path.resolve()), "--report", str(report_path.resolve())]
    if any(any(character in argument for character in '%!\r\n"') for argument in arguments):
        raise ValueError("Use icon/build paths without shell expansion, quotes, or line breaks.")
    command = " ".join(f'"{argument}"' for argument in arguments) + ' --exe "%1"'
    escaped = command.replace("$", "$$").replace('"', '$\\"')
    return f'!uninstfinalize "{escaped}" = 0'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ico", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify_pe_icons(args.exe, args.ico)
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print("CETA executable icon resources: PASS")


if __name__ == "__main__":
    main()
