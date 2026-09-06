"""Prepare a network-disabled Windows Sandbox installation lifecycle check."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

VALIDATION = r'''@echo off
if /I not "%USERNAME%"=="WDAGUtilityAccount" exit /b 99
echo STARTED>C:\Results\stage.txt
start "" /wait "C:\Payload\setup.exe" /S /D=C:\CETA
if errorlevel 1 goto failure
echo INSTALLED>C:\Results\stage.txt
for %%C in (qtbase qtsvg pyside-setup) do (
  if not exist "C:\CETA\ThirdPartyNotices\Qt\%%C\INDEX.json" goto failure
  findstr /M /C:"GNU LESSER GENERAL PUBLIC LICENSE" "C:\CETA\ThirdPartyNotices\Qt\%%C\*.txt" >nul
  if errorlevel 1 goto failure
)
start "" /wait "C:\CETA\CETA.exe" --smoke-test --data-dir C:\CETA-TestData --screenshot C:\Results\installed-window.png
if errorlevel 1 goto failure
if not exist C:\CETA-TestData\desktop.sqlite3 goto failure
echo STARTUP_PASSED>C:\Results\stage.txt
echo preserve application data>C:\CETA-TestData\keep.txt
echo preserve unrecognized file>C:\CETA\keep.txt
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\Payload\validate-update.ps1
if errorlevel 1 goto failure
start "" /wait "C:\CETA\CETA.exe" --smoke-test --data-dir C:\CETA-TestData
if errorlevel 1 goto failure
echo UPDATE_PASSED>C:\Results\stage.txt
start "" /wait "C:\CETA\Uninstall.exe" /S _?=C:\CETA
if errorlevel 1 goto failure
if exist C:\CETA\CETA.exe goto failure
if not exist C:\CETA\keep.txt goto failure
if not exist C:\CETA-TestData\keep.txt goto failure
if not exist C:\CETA-TestData\desktop.sqlite3 goto failure
echo {"status":"PASS","environment":"Windows Sandbox","network":"disabled","checks":["install","dependency_license_notices","startup","update_wait_timeout","update_wait_for_exit","update","uninstall","application_data_preserved","unrecognized_file_preserved"]}>C:\Results\result.json
exit /b 0
:failure
echo {"status":"FAIL","environment":"Windows Sandbox","detail":"See stage.txt for the last completed stage"}>C:\Results\result.json
exit /b 1
'''

UPDATE_VALIDATION = r'''
$ErrorActionPreference = 'Stop'
if ($env:USERNAME -ne 'WDAGUtilityAccount') { exit 99 }
$originalHash = (Get-FileHash -LiteralPath 'C:\CETA\CETA.exe' -Algorithm SHA256).Hash
$shellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach ($seconds in @(45, 3)) {
    $waitTarget = Start-Process -FilePath $shellPath -WindowStyle Hidden -PassThru -ArgumentList @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', "Start-Sleep -Seconds $seconds")
    try {
        $installerProcess = Start-Process -FilePath 'C:\Payload\setup.exe' -Wait -PassThru -ArgumentList @('/S', "/WAITPID=$($waitTarget.Id)", '/D=C:\CETA')
        if ($seconds -eq 45) {
            if ($installerProcess.ExitCode -ne 4) { throw 'The installer did not reject an unfinished parent process.' }
            if ((Get-FileHash -LiteralPath 'C:\CETA\CETA.exe' -Algorithm SHA256).Hash -ne $originalHash) { throw 'The timeout changed the installed executable.' }
        } else {
            $waitTarget.Refresh()
            if ($installerProcess.ExitCode -ne 0 -or -not $waitTarget.HasExited) { throw 'The installer failed to wait for successful application exit.' }
        }
    } finally {
        $waitTarget.Refresh()
        if (-not $waitTarget.HasExited) { Stop-Process -Id $waitTarget.Id }
        $waitTarget.Dispose()
    }
}
'{"status":"PASS","timeout_exit_code":4,"completed_parent_exit_code":0}' | Set-Content -LiteralPath 'C:\Results\update-handoff.json' -Encoding UTF8
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise SystemExit("Use a new external validation directory.")
    payload = output / "payload"
    results = output / "results"
    payload.mkdir(parents=True)
    results.mkdir()
    shutil.copyfile(args.installer, payload / "setup.exe")
    (payload / "validate.cmd").write_text(VALIDATION, encoding="ascii", newline="\r\n")
    (payload / "validate-update.ps1").write_text(UPDATE_VALIDATION, encoding="ascii", newline="\r\n")
    config = ET.Element("Configuration")
    for key in ("VGpu", "Networking", "ClipboardRedirection", "AudioInput", "PrinterRedirection"):
        ET.SubElement(config, key).text = "Disable"
    ET.SubElement(config, "MemoryInMB").text = "3072"
    folders = ET.SubElement(config, "MappedFolders")
    for host, guest, readonly in ((payload, "C:\\Payload", "true"), (results, "C:\\Results", "false")):
        folder = ET.SubElement(folders, "MappedFolder")
        ET.SubElement(folder, "HostFolder").text = str(host)
        ET.SubElement(folder, "SandboxFolder").text = guest
        ET.SubElement(folder, "ReadOnly").text = readonly
    ET.SubElement(ET.SubElement(config, "LogonCommand"), "Command").text = "cmd.exe /c C:\\Payload\\validate.cmd"
    ET.indent(config)
    target = output / "CETA-validation.wsb"
    ET.ElementTree(config).write(target, encoding="utf-8", xml_declaration=True)
    print(target)


if __name__ == "__main__":
    main()
