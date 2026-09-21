"""Prepare a network-disabled Windows Sandbox installation lifecycle check."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
import shutil
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

VALIDATION = r'''@echo off
if /I not "%USERNAME%"=="WDAGUtilityAccount" exit /b 99
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\Payload\validate-lifecycle.ps1
exit /b %ERRORLEVEL%
'''

LIFECYCLE_VALIDATION = r'''
$ErrorActionPreference = 'Stop'
if ($env:USERNAME -ne 'WDAGUtilityAccount') { exit 99 }
function Set-Stage([string] $Name) {
    $Name | Set-Content -LiteralPath 'C:\Results\stage.txt' -Encoding ASCII
}
function Invoke-Wait([string] $File, [string[]] $Arguments, [int] $TimeoutSeconds = 180) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    try {
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id
            throw "Process exceeded the validation time bound: $File"
        }
        $process.Refresh()
        if ($process.ExitCode -ne 0) { throw "Process failed ($($process.ExitCode)): $File" }
    } finally { $process.Dispose() }
}
function Invoke-Probe([string] $Label, [int] $MinimumPriorLaunches) {
    $before = @(Get-ChildItem -LiteralPath 'C:\CETA-TestData' -Filter 'merger-self-test-*.json' | ForEach-Object { $_.Name })
    Invoke-Wait 'C:\CETA\CETA.exe' @('--smoke-test', '--merger-self-test', '--data-dir', 'C:\CETA-TestData', '--screenshot', "C:\Results\$Label-window.png")
    $fresh = @(Get-ChildItem -LiteralPath 'C:\CETA-TestData' -Filter 'merger-self-test-*.json' | Where-Object { $_.Name -notin $before })
    if ($fresh.Count -ne 1) { throw 'The merged executable did not produce exactly one fresh self-test report.' }
    $report = Get-Content -LiteralPath $fresh[0].FullName -Raw | ConvertFrom-Json
    if ($report.status -ne 'passed' -or $report.schema -ne 'ceta.merged-packaged-self-test.v1' -or $report.synthetic -ne $true) {
        throw 'The synchronous merged workflow self-test failed.'
    }
    $migration = $report.migration
    if ($migration.status -ne 'passed' -or $migration.schema_after -ne 2 -or $migration.backup_schema -ne 1 -or $migration.backup_integrity -ne 'ok' -or
        $migration.unknown_rows_preserved -ne $true -or $migration.legacy_rows_preserved -ne $true -or
        $migration.backup_sha256 -ne $fixture.expected_backup_sha256 -or
        $migration.prior_successful_launches_verified -lt $MinimumPriorLaunches) {
        throw 'The installed migration, backup, unknown-row, or restart check failed.'
    }
    foreach ($check in @('native_project_open','native_inspection_search','native_diff_review_apply','verified_file_observation','native_command_output','history_reopen','bound_transcript','unrelated_bytes_preserved')) {
        if ($check -notin $report.checks) { throw "Missing merged workflow check: $check" }
    }
    [IO.File]::Copy($fresh[0].FullName, "C:\Results\$Label-report.json", $false)
    Set-Stage "$Label`_PASSED"
}
try {
    Set-Stage 'STARTED'
    $metadata = Get-Content -LiteralPath 'C:\Payload\payload-manifest.json' -Raw | ConvertFrom-Json
    $fixture = Get-Content -LiteralPath 'C:\Payload\sandbox-fixture.json' -Raw | ConvertFrom-Json
    foreach ($item in $metadata.files) {
        if ((Get-FileHash -LiteralPath (Join-Path 'C:\Payload' $item.name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) {
            throw "Payload hash mismatch: $($item.name)"
        }
    }
    $previous = Test-Path -LiteralPath 'C:\Payload\previous-setup.exe'
    $initialInstaller = if ($previous) { 'C:\Payload\previous-setup.exe' } else { 'C:\Payload\setup.exe' }
    Invoke-Wait $initialInstaller @('/S', '/D=C:\CETA')
    Set-Stage 'INSTALLED'
    if ($previous) {
        Invoke-Wait 'C:\CETA\CETA.exe' @('--smoke-test', '--data-dir', 'C:\CETA-PreviousStartup')
        Set-Stage 'PREVIOUS_VERSION_STARTUP_PASSED'
    }
    if (Test-Path -LiteralPath 'C:\CETA-TestData') { throw 'Synthetic validation directory already exists.' }
    New-Item -ItemType Directory -Path 'C:\CETA-TestData' | Out-Null
    [IO.File]::Copy('C:\Payload\schema1-fixture.sqlite3', 'C:\CETA-TestData\desktop.sqlite3', $false)
    [IO.File]::Copy('C:\Payload\sandbox-fixture.json', 'C:\CETA-TestData\sandbox-fixture.json', $false)
    if ((Get-FileHash -LiteralPath 'C:\CETA-TestData\desktop.sqlite3' -Algorithm SHA256).Hash.ToLowerInvariant() -ne $fixture.source_sha256) {
        throw 'Synthetic migration source differs from its prepared hash.'
    }
    'Preserve synthetic application data.' | Set-Content -LiteralPath 'C:\CETA-TestData\keep.txt' -Encoding ASCII
    'Preserve synthetic unrecognized install file.' | Set-Content -LiteralPath 'C:\CETA\keep.txt' -Encoding ASCII
    $keepDataHash = (Get-FileHash -LiteralPath 'C:\CETA-TestData\keep.txt' -Algorithm SHA256).Hash
    $keepInstallHash = (Get-FileHash -LiteralPath 'C:\CETA\keep.txt' -Algorithm SHA256).Hash
    if ($previous) { Invoke-Wait (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') @('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File','C:\Payload\validate-update.ps1') 120 }
    foreach ($component in @('qtbase', 'qtsvg', 'pyside-setup')) {
        $noticePath = "C:\CETA\ThirdPartyNotices\Qt\$component"
        if (-not (Test-Path -LiteralPath (Join-Path $noticePath 'INDEX.json'))) { throw 'Dependency notice index missing.' }
        if (@(Get-ChildItem -LiteralPath $noticePath -Filter '*.txt' | Select-String -SimpleMatch 'GNU LESSER GENERAL PUBLIC LICENSE').Count -eq 0) {
            throw 'Dependency LGPL notice missing.'
        }
    }
    Invoke-Probe 'installed-migration' 0
    Invoke-Probe 'restart' 1
    if (-not $previous) { Invoke-Wait (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') @('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File','C:\Payload\validate-update.ps1') 120 }
    Invoke-Probe 'updated' 2
    if ((Get-FileHash -LiteralPath 'C:\CETA-TestData\keep.txt' -Algorithm SHA256).Hash -ne $keepDataHash -or
        (Get-FileHash -LiteralPath 'C:\CETA\keep.txt' -Algorithm SHA256).Hash -ne $keepInstallHash) {
        throw 'Install/update changed a synthetic unknown file.'
    }
    $retained = @(Get-ChildItem -LiteralPath 'C:\CETA-TestData' -File | ForEach-Object {
        [PSCustomObject]@{ name = $_.Name; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
    Invoke-Wait 'C:\CETA\Uninstall.exe' @('/S', '_?=C:\CETA')
    if (Test-Path -LiteralPath 'C:\CETA\CETA.exe') { throw 'Uninstall left the installed executable.' }
    if ((Get-FileHash -LiteralPath 'C:\CETA\keep.txt' -Algorithm SHA256).Hash -ne $keepInstallHash) { throw 'Uninstall changed the unknown install file.' }
    foreach ($item in $retained) {
        if ((Get-FileHash -LiteralPath (Join-Path 'C:\CETA-TestData' $item.name) -Algorithm SHA256).Hash -ne $item.sha256) {
            throw "Uninstall changed retained synthetic application data: $($item.name)"
        }
    }
    Set-Stage 'UNINSTALL_PASSED'
    [ordered]@{status='PASS'; environment='Windows Sandbox'; network='disabled'; synthetic=$true;
        previous_installer=$metadata.previous_installer; source_fixture_sha256=$fixture.source_sha256;
        migration_backup_sha256=$fixture.expected_backup_sha256; retained_files=$retained;
        checks=@('install','dependency_license_notices','merged_workflow','schema1_to_schema2','backup_integrity',
                 'legacy_rows_preserved','unknown_rows_preserved','restart_checkpoint_preserved','update_wait_timeout',
                 'update_wait_for_exit','update','uninstall','application_data_preserved','unrecognized_file_preserved');
        limits='Synthetic local lifecycle only; no model inference, online deployment, signature authenticity, or clean-hardware claim.'
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath 'C:\Results\result.json' -Encoding UTF8
    exit 0
} catch {
    [ordered]@{status='FAIL'; environment='Windows Sandbox'; detail=$_.Exception.Message;
        stage=(Get-Content -LiteralPath 'C:\Results\stage.txt' -ErrorAction SilentlyContinue)} |
        ConvertTo-Json | Set-Content -LiteralPath 'C:\Results\result.json' -Encoding UTF8
    exit 1
}
'''

UPDATE_VALIDATION = r'''
$ErrorActionPreference = 'Stop'
if ($env:USERNAME -ne 'WDAGUtilityAccount') { exit 99 }
$originalHash = (Get-FileHash -LiteralPath 'C:\CETA\CETA.exe' -Algorithm SHA256).Hash
$shellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach ($seconds in @(45, 3)) {
    $waitTarget = Start-Process -FilePath $shellPath -WindowStyle Hidden -PassThru -ArgumentList @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', "Start-Sleep -Seconds $seconds")
    try {
        $installerProcess = Start-Process -FilePath 'C:\Payload\setup.exe' -WindowStyle Hidden -Wait -PassThru -ArgumentList @('/S', "/WAITPID=$($waitTarget.Id)", '/D=C:\CETA')
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


def create_synthetic_fixture(payload):
    """Generate new schema-1 bytes only; never read the user's application DB."""
    source = payload / "schema1-fixture.sqlite3"
    reference = payload / "expected-schema1-backup.sqlite3"
    if source.exists() or reference.exists():
        raise ValueError("Synthetic fixture outputs must be new")
    db = sqlite3.connect(source)
    try:
        db.executescript("""
            PRAGMA user_version=1;
            CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO settings VALUES ('sandbox_fixture','{"synthetic":true}');
            CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE messages(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),role TEXT NOT NULL,
                content TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE workloads(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,command TEXT NOT NULL,
                status TEXT NOT NULL,exit_code INTEGER,output TEXT NOT NULL,created REAL NOT NULL);
            INSERT INTO conversations VALUES ('legacy-sandbox','Synthetic retained history',12.5);
            INSERT INTO messages VALUES (1,'legacy-sandbox','user','Synthetic retained transcript','complete',13.5);
            CREATE TABLE unknown_user_data(name TEXT PRIMARY KEY,data BLOB NOT NULL);
            INSERT INTO unknown_user_data VALUES ('retain',X'0001FEFF');
        """)
        backup = sqlite3.connect(reference)
        try:
            db.backup(backup)
        finally:
            backup.close()
    finally:
        db.close()
    fixture = {"schema": "ceta.sandbox-fixture.v1", "synthetic": True,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "expected_backup_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "expected_rows": {
            "conversation": [["legacy-sandbox", "Synthetic retained history", 12.5]],
            "message": [[1, "legacy-sandbox", "user", "Synthetic retained transcript", "complete", 13.5]],
            "setting": [["sandbox_fixture", '{"synthetic":true}']],
            "unknown": [["retain", "0001FEFF"]],
        }}
    (payload / "sandbox-fixture.json").write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    return fixture


def prepare(installer, output, previous_installer=None):
    installer, output = Path(installer).resolve(strict=True), Path(output).resolve()
    previous_installer = Path(previous_installer).resolve(strict=True) if previous_installer is not None else None
    if not installer.is_file() or (previous_installer is not None and not previous_installer.is_file()):
        raise ValueError("Select installer files")
    if output.exists() or output.is_relative_to(ROOT):
        raise ValueError("Use a new external validation directory.")
    payload, results = output / "payload", output / "results"
    payload.mkdir(parents=True)
    results.mkdir()
    shutil.copyfile(installer, payload / "setup.exe")
    if previous_installer is not None:
        shutil.copyfile(previous_installer, payload / "previous-setup.exe")
    create_synthetic_fixture(payload)
    (payload / "validate.cmd").write_text(VALIDATION, encoding="ascii", newline="\r\n")
    (payload / "validate-lifecycle.ps1").write_text(LIFECYCLE_VALIDATION, encoding="ascii", newline="\r\n")
    (payload / "validate-update.ps1").write_text(UPDATE_VALIDATION, encoding="ascii", newline="\r\n")
    manifest = {"schema": "ceta.sandbox-payload.v1", "synthetic": True,
        "previous_installer": None if previous_installer is None else previous_installer.name,
        "files": [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                  for path in sorted(payload.iterdir()) if path.is_file()]}
    (payload / "payload-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
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
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--previous-installer", type=Path, help="Optional prior installer for a real prior-to-current upgrade")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(prepare(args.installer, args.output, args.previous_installer))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
