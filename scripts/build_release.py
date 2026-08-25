from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def remove_transient() -> None:
    for name in ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"):
        for path in list(ROOT.rglob(name)):
            if path.is_dir(): shutil.rmtree(path,ignore_errors=True)
    for path in list(ROOT.rglob("*.pyc"))+list(ROOT.rglob("*.pyo")):
        path.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    out=Path(args.output).resolve()
    subprocess.run([sys.executable,str(ROOT/"scripts/verify_all.py")],cwd=ROOT,check=True)
    remove_transient()
    subprocess.run([sys.executable,str(ROOT/"scripts/build_package_manifest.py")],cwd=ROOT,check=True)
    subprocess.run([sys.executable,str(ROOT/"scripts/build_sha256sums.py")],cwd=ROOT,check=True)
    subprocess.run([sys.executable,str(ROOT/"scripts/verify_package.py")],cwd=ROOT,check=True)
    prefix=f"Architecture-Rebuild-CETA-Epoch-Ready-v{(ROOT/'VERSION').read_text().strip()}/"
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists(): out.unlink()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
        for path in sorted(x for x in ROOT.rglob("*") if x.is_file() and not x.is_symlink()):
            rel=path.relative_to(ROOT)
            if any(part in {"__pycache__",".pytest_cache",".mypy_cache",".ruff_cache",".git"} for part in rel.parts) or path.suffix in {".pyc",".pyo"}:
                continue
            info=zipfile.ZipInfo(prefix+rel.as_posix(),date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100644 & 0xFFFF)<<16
            zf.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    digest=sha256(out)
    sidecar=out.with_suffix(out.suffix+".sha256")
    sidecar.write_text(f"{digest}  {out.name}\n",encoding="utf-8")
    print(f"RELEASE ZIP: {out}")
    print(f"SHA256: {digest}")


if __name__=="__main__":
    main()
