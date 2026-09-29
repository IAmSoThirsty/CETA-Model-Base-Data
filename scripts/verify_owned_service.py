"""Check an installed Ollama's owned HTTP lifecycle with an empty temporary profile.

No model download or inference. Managed mode verifies the pinned distribution
files and uses CETA's private child environment. Neither mode establishes offline
isolation, loaded driver provenance, GPU capability or frozen application behavior.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--managed-data-dir", type=Path,
                        help="Verify pinned managed runtime files and use CETA's managed child environment")
    args = parser.parse_args()
    if os.name != "nt" or not args.executable.is_file() or args.report.exists():
        parser.error("Windows, an existing Ollama executable, and a new report path are required.")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess, QProcessEnvironment
    from PySide6.QtWidgets import QApplication
    from ceta_desktop.models import LocalModelClient
    from ceta_desktop.owned_process import OwnedModelProcess
    from ceta_desktop.runtime_installation import RuntimeInstallation, managed_environment
    from verify_desktop_runtime import source_attribution
    application = QApplication.instance() or QApplication([])
    executable = args.executable.resolve()
    before = source_attribution()
    managed = RuntimeInstallation(args.managed_data_dir).verify() if args.managed_data_dir else None
    if managed is not None and Path(managed["executable"]).resolve() != executable:
        parser.error("The executable does not belong to the verified managed installation.")
    with executable.open("rb") as handle:
        executable_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    report = {"schema": "ceta.owned-service-smoke.v1", "passed": False,
              "executable": str(executable), "executable_sha256": executable_digest,
              "source_before": before, "cycles": [], "inference_performed": False,
              "models_downloaded": False, "os_network_isolation": False,
              "scope": "Installed Ollama metadata health, Qt owned process adapter, shutdown and restart; empty temporary profile"}
    if managed:
        report["managed_runtime"] = managed
    with tempfile.TemporaryDirectory(prefix="ceta-owned-service-") as temporary:
        directory = Path(temporary)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        environment = QProcessEnvironment()
        for key, value in os.environ.items():
            if not key.upper().startswith("OLLAMA_"):
                environment.insert(key, value)
        for key, value in {
            "USERPROFILE": str(directory / "profile"), "LOCALAPPDATA": str(directory / "local"),
            "APPDATA": str(directory / "roaming"), "OLLAMA_MODELS": str(directory / "models"),
            "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_NO_CLOUD": "1",
            "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_CONTEXT_LENGTH": "4096",
        }.items():
            environment.insert(key, value)
        if managed:
            environment = QProcessEnvironment()
            for key, value in managed_environment(directory, executable, dict(os.environ)).items():
                environment.insert(key, value)
            environment.insert("OLLAMA_HOST", f"127.0.0.1:{port}")
        process = OwnedModelProcess(coordination_directory=directory / "coordination")
        process.setProgram(str(executable))
        process.setArguments(["serve"])
        process.setProcessEnvironment(environment)
        process.setEndpoint("127.0.0.1", port)
        process.readyReadStandardOutput.connect(process.readAllStandardOutput)
        try:
            for _ in range(2):
                process.start()
                if process.state() != QProcess.Running:
                    raise RuntimeError(process.errorString())
                client = LocalModelClient(f"http://127.0.0.1:{port}/v1", coordination_directory=directory / "coordination")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(client.wait_owned_service, "ollama", process.containment["job_name"], timeout=20)
                    try:
                        deadline = time.monotonic() + 25
                        while not future.done():
                            application.processEvents()
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Owned service smoke exceeded its deadline")
                            if process.state() == QProcess.NotRunning:
                                raise RuntimeError("Owned service exited before becoming healthy")
                            time.sleep(.01)
                        health = future.result()
                        if managed and health["health"]["version"] != managed["version"]:
                            raise RuntimeError("Managed runtime returned an unexpected version")
                        if health["models"]:
                            raise RuntimeError("The smoke profile unexpectedly exposed installed models")
                    finally:
                        client.cancel()
                process.kill()
                if not process.waitForFinished(3000):
                    raise RuntimeError("Owned workers did not confirm shutdown")
                report["cycles"].append({"health": health, "shutdown": process.last_observation,
                                         "recovery": client.reconcile_runtime()})
            report["passed"] = len({cycle["health"]["containment"]["job_name"] for cycle in report["cycles"]}) == 2
        except (OSError, ValueError, RuntimeError) as exc:
            report["error"] = str(exc)
        finally:
            process.kill()
            if not process.waitForFinished(3000):
                report.update(passed=False, cleanup_error="Worker shutdown was not confirmed")
            process.deleteLater()
            application.processEvents()
    after = source_attribution()
    report["source_after_sha256"] = after["source_sha256"]
    report["source_unchanged"] = before["source_sha256"] == after["source_sha256"]
    report["passed"] = report["passed"] and report["source_unchanged"]
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"passed": report["passed"], "cycles": len(report["cycles"]),
                      "error": report.get("error"), "report": str(args.report)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
