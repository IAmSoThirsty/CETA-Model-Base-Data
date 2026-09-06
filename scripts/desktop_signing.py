"""Use a publisher-selected Windows certificate; never creates or exports keys."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


def portable_executable_files(payload: Path) -> list[Path]:
    """Find PE headers throughout a complete payload, independent of extension."""
    payload = payload.resolve(strict=True)
    if not payload.is_dir():
        raise ValueError("The signing payload must be a directory.")
    files = []
    for path in sorted(payload.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Payload links are not allowed: {path.relative_to(payload)}")
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            header = handle.read(64)
            if header[:2] != b"MZ":
                if path.suffix.lower() in {".exe", ".dll", ".pyd"}:
                    raise ValueError(f"Missing PE header: {path.relative_to(payload)}")
                continue
            offset = int.from_bytes(header[60:64], "little")
            if len(header) != 64 or not 64 <= offset <= path.stat().st_size - 24:
                raise ValueError(f"Invalid PE header: {path.relative_to(payload)}")
            handle.seek(offset)
            if handle.read(4) != b"PE\0\0":
                raise ValueError(f"Invalid PE header: {path.relative_to(payload)}")
        files.append(path)
    if not files:
        raise ValueError("The signing payload contains no PE files.")
    return files


def authenticode_statuses(paths: list[Path]) -> dict[str, str]:
    """Read public Windows signature statuses without selecting or opening keys."""
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    environment = dict(os.environ)
    # Do not load another PowerShell version's or project's modules from the host.
    environment["PSModulePath"] = str(powershell.parent / "Modules")
    # Paths are JSON on stdin, never interpolated into PowerShell source.
    command = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$paths = ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
$rows = @(foreach ($path in $paths) {
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    @{path = $path; status = $signature.Status.ToString()}
})
ConvertTo-Json -InputObject $rows -Compress
"""
    requested = [str(path) for path in paths]
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        input=json.dumps(requested), capture_output=True, encoding="utf-8", env=environment,
        check=True, timeout=120,
    )
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != len(requested):
        raise ValueError("Windows returned incomplete payload signature statuses.")
    statuses = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "status"}:
            raise ValueError("Windows returned inconsistent payload signature statuses.")
        if (not isinstance(row["path"], str) or not isinstance(row["status"], str) or
                row["path"] not in requested or row["path"] in statuses):
            raise ValueError("Windows returned inconsistent payload signature statuses.")
        statuses[row["path"]] = row["status"]
    return statuses


@dataclass(frozen=True)
class SigningConfig:
    signtool: Path
    certificate_thumbprint: str
    timestamp_url: str

    @classmethod
    def read(cls, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"signtool", "certificate_thumbprint", "timestamp_url"}:
            raise ValueError("Signing configuration requires signtool, certificate_thumbprint, and timestamp_url.")
        if not all(isinstance(value, str) for value in data.values()):
            raise ValueError("Signing configuration values must be strings.")
        tool = Path(data["signtool"])
        if not tool.is_absolute() or not tool.is_file() or tool.name.lower() != "signtool.exe":
            raise ValueError("Select the absolute path of the Windows SDK signtool.exe.")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", data["certificate_thumbprint"]):
            raise ValueError("Select the 40-character thumbprint of your publisher's signing certificate.")
        url = data["timestamp_url"]
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
                parsed.fragment or any(character.isspace() for character in url)):
            raise ValueError("Select an HTTPS RFC 3161 timestamp service without embedded credentials.")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Invalid timestamp service port.")
        return cls(tool.resolve(), data["certificate_thumbprint"].upper(), url)

    def sign(self, path: Path):
        if not path.is_file():
            raise ValueError("The file to sign does not exist.")
        subprocess.run([str(self.signtool), "sign", "/sha1", self.certificate_thumbprint,
                        "/fd", "SHA256", "/tr", self.timestamp_url, "/td", "SHA256", str(path)],
                       check=True, timeout=180)
        self.verify(path)

    def verify(self, path: Path):
        """Require every embedded signature to pass trust and timestamp checks."""
        # /tw makes a missing timestamp a warning; any nonzero result fails here.
        subprocess.run([str(self.signtool), "verify", "/pa", "/all", "/tw", "/v", str(path)],
                       check=True, timeout=60)

    def sign_payload(self, payload: Path) -> int:
        """Preserve verified vendor signatures and sign every unsigned PE file."""
        paths = portable_executable_files(payload)
        statuses = authenticode_statuses(paths)
        for path in paths:
            status = statuses[str(path)]
            if status not in {"Valid", "NotSigned"}:
                raise ValueError(f"Refusing to replace an invalid signature ({status}): {path}")
        # Verify existing signatures before changing any unsigned file. In
        # particular, a catalog-only status must not substitute for an embedded
        # signature, and a valid primary signature must not hide an invalid one.
        for path in paths:
            if statuses[str(path)] == "Valid":
                self.verify(path)
        for path in paths:
            if statuses[str(path)] == "NotSigned":
                self.sign(path)
        return len(paths)


def uninstaller_finalize(config_path: Path) -> str:
    arguments = [sys.executable, str(Path(__file__).resolve()), "--config", str(config_path.resolve())]
    # These paths enter the compiler's command interpreter. Reject expansion or
    # control characters rather than changing the interpretation of a real path.
    if any(any(character in argument for character in '%!\r\n"') for argument in arguments):
        raise ValueError("Use signing/build paths without percent signs, exclamation marks, quotes, or line breaks.")
    command = " ".join(f'"{argument}"' for argument in arguments) + ' --file "%1"'
    escaped = command.replace("$", "$$").replace('"', '$\\"')
    return f'!uninstfinalize "{escaped}" = 0'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args()
    SigningConfig.read(args.config).sign(args.file)


if __name__ == "__main__":
    main()
