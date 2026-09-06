from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def remove_transient() -> None:
    """Compatibility hook: release filtering never deletes working files."""


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def release_paths() -> tuple[Path,...]:
    if __package__:
        from .build_release_zip import registered_paths
    else:
        from build_release_zip import registered_paths

    return registered_paths(ROOT)


def archive_info(name: str) -> zipfile.ZipInfo:
    info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
    info.create_system=3
    info.compress_type=zipfile.ZIP_DEFLATED
    info.external_attr=(0o100644 & 0xFFFF)<<16
    return info


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    out=Path(args.output).resolve()
    sidecar=out.with_suffix(out.suffix+".sha256")
    if out.is_relative_to(ROOT.resolve()):
        raise SystemExit("RELEASE ZIP: FAIL - output must be outside the repository")
    if out.exists() or sidecar.exists():
        raise SystemExit("RELEASE ZIP: FAIL - output or checksum already exists")
    subprocess.run([sys.executable,str(ROOT/"scripts/verify_all.py")],cwd=ROOT,check=True)
    subprocess.run([sys.executable,str(ROOT/"scripts/verify_package.py")],cwd=ROOT,check=True)
    prefix=f"Architecture-Rebuild-CETA-Epoch-Ready-v{(ROOT/'VERSION').read_text().strip()}/"
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
        for path in release_paths():
            rel=path.relative_to(ROOT)
            info=archive_info(prefix+rel.as_posix())
            zf.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    digest=sha256(out)
    with sidecar.open("x",encoding="utf-8",newline="\n") as handle:
        handle.write(f"{digest}  {out.name}\n")
    print(f"RELEASE ZIP: {out}")
    print(f"SHA256: {digest}")


if __name__=="__main__":
    main()
