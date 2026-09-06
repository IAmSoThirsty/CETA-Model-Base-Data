from __future__ import annotations

import argparse
import base64
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def nsis_quote(value: str) -> str:
    return value.replace("$", "$$").replace('"', '$\\"')


def write_notices(destination: Path):
    destination.mkdir()
    rows = []
    for name in ("PySide6-Essentials", "shiboken6", "cryptography", "cffi", "pycparser", "pyinstaller"):
        distribution = metadata.distribution(name)
        rows.append({"name": name, "version": distribution.version,
                     "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License", "See license files")})
        for entry in distribution.files or ():
            if "license" in str(entry).lower() or "copying" in str(entry).lower():
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    target = destination / name / str(entry).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    (destination / "DEPENDENCIES.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    # Preserve the interpreter's license text alongside the shared runtime.
    python_root = Path(sys.base_prefix)
    for name in ("LICENSE.txt", "LICENSE"):
        if (python_root / name).is_file():
            shutil.copyfile(python_root / name, destination / "PYTHON-LICENSE.txt")
            break


def installer_script(payload: Path, output: Path, version: str, finalize: str | None = None) -> str:
    files = sorted(path for path in payload.rglob("*") if path.is_file())
    directories = sorted({path.parent.relative_to(payload) for path in files}, key=lambda p: len(p.parts), reverse=True)
    lines = [
        'Unicode true', '!include "MUI2.nsh"', '!include "x64.nsh"', '!include "LogicLib.nsh"', '!include "FileFunc.nsh"',
        'Name "CETA"', f'OutFile "{nsis_quote(str(output))}"',
        'InstallDir "$LOCALAPPDATA\\Programs\\CETA"',
        'InstallDirRegKey HKCU "Software\\CETA" "InstallDir"',
        'RequestExecutionLevel user', 'SetCompressor /SOLID lzma',
        f'VIProductVersion "{version}.0"',
        'VIAddVersionKey "ProductName" "CETA"',
        f'VIAddVersionKey "ProductVersion" "{version}"',
        'VIAddVersionKey "FileDescription" "CETA desktop installer"',
        'VIAddVersionKey "LegalCopyright" "Dependency notices are included in ThirdPartyNotices."',
        f'VIAddVersionKey "FileVersion" "{version}"',
        '!insertmacro MUI_PAGE_WELCOME', '!insertmacro MUI_PAGE_DIRECTORY',
        '!insertmacro MUI_PAGE_INSTFILES', '!insertmacro MUI_PAGE_FINISH',
        '!insertmacro MUI_UNPAGE_CONFIRM', '!insertmacro MUI_UNPAGE_INSTFILES',
        '!insertmacro MUI_LANGUAGE "English"',
        'Function .onInit',
        '  ${GetParameters} $0', '  ClearErrors',
        '  ${GetOptions} $0 "/WAITPID=" $1', '  IfErrors update_wait_done',
        '  System::Call "kernel32::OpenProcess(i 0x100000, i 0, i r1) p.r2 ?e"',
        '  Pop $3', '  StrCmp $2 0 0 update_wait_opened',
        '  StrCmp $3 87 update_wait_done update_wait_failed',
        '  update_wait_opened:',
        '  System::Call "kernel32::WaitForSingleObject(p r2, i 30000) i.r3"',
        '  System::Call "kernel32::CloseHandle(p r2)"',
        '  StrCmp $3 0 update_wait_done update_wait_failed',
        '  update_wait_failed:',
        '  MessageBox MB_OK|MB_ICONSTOP "CETA has not finished closing. Run the update again after it exits." /SD IDOK',
        '  SetErrorLevel 4', '  Abort', '  update_wait_done:',
        '  ${IfNot} ${RunningX64}',
        '    MessageBox MB_OK|MB_ICONSTOP "CETA requires 64-bit Windows." /SD IDOK',
        '    SetErrorLevel 3', '    Abort', '  ${EndIf}',
        '  System::Call \'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\\CETA.Desktop") p.r0\'',
        '  StrCmp $0 0 ready',
        '  System::Call "kernel32::CloseHandle(p r0)"',
        '  MessageBox MB_OK|MB_ICONSTOP "Close CETA before installing an update." /SD IDOK',
        '  SetErrorLevel 2', '  Abort', '  ready:', 'FunctionEnd',
        'Function un.onInit',
        '  System::Call \'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\\CETA.Desktop") p.r0\'',
        '  StrCmp $0 0 ready',
        '  System::Call "kernel32::CloseHandle(p r0)"',
        '  MessageBox MB_OK|MB_ICONSTOP "Close CETA before uninstalling." /SD IDOK',
        '  SetErrorLevel 2', '  Abort', '  ready:', 'FunctionEnd',
        'Section "CETA"', '  SetShellVarContext current',
        '  SetOutPath "$INSTDIR"',
        f'  File /r "{nsis_quote(str(payload))}\\*"',
        '  WriteUninstaller "$INSTDIR\\Uninstall.exe"',
        '  WriteRegStr HKCU "Software\\CETA" "InstallDir" "$INSTDIR"',
        '  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CETA" "DisplayName" "CETA"',
        f'  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CETA" "DisplayVersion" "{version}"',
        '  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CETA" "UninstallString" \'$\\"$INSTDIR\\Uninstall.exe$\\"\'',
        '  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CETA" "NoModify" 1',
        '  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CETA" "NoRepair" 1',
        '  CreateShortcut "$SMPROGRAMS\\CETA.lnk" "$INSTDIR\\CETA.exe"',
        'SectionEnd', 'Section "Uninstall"', '  SetShellVarContext current',
        '  Delete "$SMPROGRAMS\\CETA.lnk"',
    ]
    if finalize:
        lines.insert(1, finalize)
    # Exact installed-file removal; never recursively delete unknown user files.
    for path in files:
        lines.append(f'  Delete "$INSTDIR\\{nsis_quote(str(path.relative_to(payload)))}"')
    for directory in directories:
        if str(directory) != ".":
            lines.append(f'  RMDir "$INSTDIR\\{nsis_quote(str(directory))}"')
    lines.extend([
        '  Delete "$INSTDIR\\Uninstall.exe"', '  RMDir "$INSTDIR"',
        '  DeleteRegKey HKCU "Software\\CETA"',
        '  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CETA"',
        'SectionEnd',
    ])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Build the isolated CETA Windows desktop release")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--makensis", type=Path, required=True)
    parser.add_argument("--dependency-sources", type=Path, required=True, help="Directory containing the pinned Qt/PySide source archives")
    parser.add_argument("--channel-config", type=Path, help="Publisher HTTPS URL and base64 Ed25519 public key")
    parser.add_argument("--signing-config", type=Path, help="Publisher certificate thumbprint, Windows SDK SignTool path, and timestamp service")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise SystemExit("Use a new output directory outside the repository.")
    if sys.platform != "win32":
        raise SystemExit("Build the Windows installer on Windows.")
    from desktop_signing import SigningConfig, uninstaller_finalize
    signing = SigningConfig.read(args.signing_config) if args.signing_config else None
    signing_snapshot = output / "publisher-signing.json"
    finalize = uninstaller_finalize(signing_snapshot) if signing else None
    # A desktop build must not inherit heavyweight training/model dependencies.
    installed = {dist.metadata["Name"].lower() for dist in metadata.distributions()}
    if {"torch", "transformers", "peft"} & installed:
        raise SystemExit("Use the isolated desktop environment; training dependencies are present.")
    from desktop_notices import checked_sources, write_source_companion
    source_specification = json.loads((ROOT / "licenses/desktop-sources.json").read_text(encoding="utf-8"))
    if any(metadata.version(name) != source_specification["version"] for name in ("PySide6-Essentials", "shiboken6")):
        raise SystemExit("The pinned library sources do not match the installed Qt Python packages.")
    sources = checked_sources(args.dependency_sources)
    subprocess.run([sys.executable, "-m", "pip_audit", "--local", "--progress-spinner", "off"], check=True)
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test_desktop*.py", "-v"], cwd=ROOT, check=True)
    output.mkdir(parents=True)
    if signing:
        with signing_snapshot.open("x", encoding="utf-8") as handle:
            json.dump({"signtool": str(signing.signtool), "certificate_thumbprint": signing.certificate_thumbprint,
                       "timestamp_url": signing.timestamp_url}, handle, indent=2)
    channel = ROOT / "src/ceta_desktop/release_channel.json"
    if args.channel_config:
        config = json.loads(args.channel_config.read_text(encoding="utf-8"))
        if set(config) != {"url", "public_key"} or urlsplit(config["url"]).scheme != "https" or len(base64.b64decode(config["public_key"], validate=True)) != 32:
            raise SystemExit("Invalid publisher channel configuration.")
        channel_directory = output / "channel"
        channel_directory.mkdir()
        channel = channel_directory / "release_channel.json"
        channel.write_text(json.dumps(config, indent=2), encoding="utf-8")
    # Desktop releases evolve independently of the retained reference package.
    sys.path.insert(0, str(ROOT / "src"))
    from ceta_desktop import __version__ as version
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    icon = QImage(256, 256, QImage.Format_ARGB32)
    icon.fill(Qt.transparent)
    painter = QPainter(icon)
    QSvgRenderer(str(ROOT / "src/ceta_desktop/icon.svg")).render(painter)
    painter.end()
    icon_path = output / "CETA.ico"
    if not icon.save(str(icon_path)):
        raise SystemExit("Could not create the application icon.")
    # Do not resolve DLL dependencies from unrelated toolchains on the host PATH.
    build_environment = dict(os.environ)
    build_environment["PATH"] = os.pathsep.join([
        str(Path(sys.executable).parent), str(Path(sys.base_prefix)),
        str(Path(os.environ["SystemRoot"]) / "System32"),
    ])
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
        "--name", "CETA", "--paths", str(ROOT / "src"),
        "--icon", str(icon_path),
        "--add-data", f"{channel};ceta_desktop",
        "--add-data", f"{ROOT / 'src/ceta_desktop/icon.svg'};ceta_desktop",
        "--add-data", f"{ROOT / 'src/ceta_desktop/assets'};ceta_desktop/assets",
        "--distpath", str(output / "app"), "--workpath", str(output / "work"),
        "--specpath", str(output), str(ROOT / "scripts/desktop_entry.py"),
    ], cwd=ROOT, env=build_environment, check=True)
    payload = output / "app" / "CETA"
    write_notices(payload / "ThirdPartyNotices")
    companion = output / f"CETA-{version}-dependency-sources.zip"
    write_source_companion(sources, companion, payload / "ThirdPartyNotices")
    nsis_notice = args.makensis.resolve().parent.parent / "COPYING"
    if not nsis_notice.is_file():
        raise SystemExit("The NSIS compiler's COPYING notice is required for distribution.")
    shutil.copyfile(nsis_notice, payload / "ThirdPartyNotices/NSIS-COPYING.txt")
    verified_payload_pe_files = signing.sign_payload(payload) if signing else 0
    setup = output / f"CETA-{version}-setup.exe"
    script = output / "CETA.nsi"
    script.write_text(installer_script(payload, setup, version, finalize), encoding="utf-8")
    subprocess.run([str(args.makensis.resolve()), str(script)], check=True)
    if signing:
        signing.sign(setup)
    with setup.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    with companion.open("rb") as handle:
        source_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {setup.name}\n{source_digest}  {companion.name}\n", encoding="utf-8")
    print(json.dumps({"installer": str(setup), "sha256": digest, "signed": bool(signing),
                      "verified_payload_pe_files": verified_payload_pe_files,
                      "dependency_sources": str(companion), "sources_sha256": source_digest,
                      "status": "built_signed_not_published" if signing else "built_unsigned_not_published"}, indent=2))


if __name__ == "__main__":
    main()
