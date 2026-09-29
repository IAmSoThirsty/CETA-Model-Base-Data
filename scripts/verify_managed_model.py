"""Exercise pinned local weights through CETA's actual governed generation path.

Use an isolated CETA data directory with the managed runtime/model already
installed. No downloads and no user conversation content. This is a source-level
real-model lifecycle check, not OS network isolation or frozen-app qualification.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import ctypes
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--tokenizer-cases", action="store_true", help="Compare prepared and evaluated token counts on synthetic boundary cases")
    parser.add_argument("--asset-cases", action="store_true", help="Check write-access denial and release without modifying installed assets")
    parser.add_argument("--deadline-cases", action="store_true", help="Exercise a real stream with a deliberately stalled output consumer")
    parser.add_argument("--capability-cases", action="store_true", help="Measure seven synthetic instruction/file/speed cases; quality failures are recorded honestly")
    parser.add_argument("--conversation-cases", action="store_true", help="Observe arithmetic, conversation recall, rewriting, Unicode and JSON responses")
    args = parser.parse_args()
    if os.name != "nt" or args.report.exists():
        parser.error("Windows and a new report path are required")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess, QProcessEnvironment
    from PySide6.QtWidgets import QApplication
    from ceta_desktop.hardware import inspect_hardware
    from ceta_desktop.model_installation import ManagedModels
    from ceta_desktop.managed_assets import ManagedAssets
    from ceta_desktop.models import LocalModelClient
    from ceta_desktop.owned_process import OwnedModelProcess
    from ceta_desktop.runtime_installation import RuntimeInstallation, managed_environment
    from runtime.model_provider import LocalProvider
    from runtime.tasks import TaskRuntime
    from verify_desktop_runtime import source_attribution
    application = QApplication.instance() or QApplication([])
    before = source_attribution()
    directory = args.data_dir.resolve()
    report = {"schema": "ceta.managed-model-lifecycle.v1", "passed": False, "source_before": before,
              "scope": "Source runtime, pinned weights, real local generation and owned lifecycle with synthetic prompts",
              "models_downloaded": False, "os_network_isolation": False, "frozen_application": False,
              "steps": []}
    process = OwnedModelProcess(coordination_directory=directory / "verification-coordination")
    runtime = None
    access_api = ctypes.WinDLL("kernel32", use_last_error=True)
    access_api.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    access_api.CreateFileW.restype = ctypes.c_void_p
    access_api.CloseHandle.argtypes = [ctypes.c_void_p]
    access_api.CloseHandle.restype = ctypes.c_int

    def write_access(path, expected_error):
        # OPEN_EXISTING and no write operation: never alter installed bytes.
        # Use Win32 directly because Python's CRT open loses the sharing error.
        handle = access_api.CreateFileW(str(path), 0x40000000, 7, None, 3, 0x80, None)
        error = ctypes.get_last_error() if handle == ctypes.c_void_p(-1).value else 0
        if not error:
            access_api.CloseHandle(handle)
        if error != expected_error:
            raise RuntimeError(f"Asset write-access check expected Win32 {expected_error}, got {error}: {path}")

    try:
        report["runtime"] = RuntimeInstallation(directory).verify()
        report["model"] = ManagedModels(directory).verify(args.model)
        report["hardware"] = asdict(inspect_hardware())
        executable = report["runtime"]["executable"]
        name = report["model"]["model"]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        environment = QProcessEnvironment()
        for key, value in managed_environment(directory, executable, dict(os.environ)).items():
            environment.insert(key, value)
        environment.insert("OLLAMA_HOST", f"127.0.0.1:{port}")
        process.setProgram(executable); process.setArguments(["serve"])
        process.setProcessEnvironment(environment); process.setEndpoint("127.0.0.1", port)
        process.readyReadStandardOutput.connect(process.readAllStandardOutput)
        runtime = TaskRuntime(directory)
        runtime.application_project()

        def client():
            result = LocalModelClient(f"http://127.0.0.1:{port}/v1", coordination_directory=directory / "verification-coordination")
            result.expected_job = process.containment["job_name"]
            result.managed_directory = directory
            result.managed_assets = process.managed_assets
            return result

        def work(callback, active_client, timeout=210):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(callback)
                deadline = time.monotonic() + timeout
                try:
                    while not future.done():
                        application.processEvents()
                        if time.monotonic() >= deadline:
                            active_client.cancel(); process.kill()
                            raise TimeoutError("Real model verification exceeded its deadline")
                        if process.state() == QProcess.NotRunning:
                            raise RuntimeError("Owned runtime exited during verification")
                        time.sleep(.01)
                    return future.result()
                finally:
                    active_client.cancel()

        def start():
            assets = ManagedAssets(RuntimeInstallation(directory))
            try:
                assets.protect_runtime()
                assets.protect_model(ManagedModels(directory), args.model)
                process.setManagedAssets(assets)
            except BaseException:
                assets.close()
                raise
            process.start()
            if process.state() != QProcess.Running:
                raise RuntimeError(process.errorString())
            connection = client()
            health = work(lambda: connection.wait_owned_service("ollama", process.containment["job_name"], timeout=20), connection, 30)
            if health["health"]["version"] != report["runtime"]["version"] or name not in health["models"]:
                raise RuntimeError("The managed runtime did not report the pinned version/model")
            report["steps"].append({"operation": "health", "result": health})
            if args.asset_cases:
                paths = [resource.path for resource in assets._paths.values() if not resource.directory]
                for path in paths:
                    write_access(path, 32)
                report["steps"].append({"operation": "asset_write_access_denied", "files": len(paths),
                    "session_id": assets.session_id, "job_name": assets.job_name})

        def stop():
            assets = process.managed_assets
            paths = [resource.path for resource in assets._paths.values() if not resource.directory] if assets else []
            process.kill()
            if not process.waitForFinished(5000):
                raise RuntimeError("Owned model workers did not stop")
            report["steps"].append({"operation": "stop", "result": process.last_observation})
            if args.asset_cases:
                if assets is None or not assets.closed or process.managed_assets is not None:
                    raise RuntimeError("Confirmed worker shutdown did not release its asset session")
                for path in paths:
                    write_access(path, 0)
                report["steps"].append({"operation": "asset_write_access_released", "files": len(paths),
                    "session_id": assets.session_id})

        start()
        connection = client()
        probe = work(lambda: runtime.probe_model(connection, name), connection)
        report["steps"].append({"operation": "governed_probe", "result": probe})
        if not probe.get("response", "").strip():
            raise RuntimeError("The local model probe produced no visible response")

        connection = client()
        task = runtime.start_task("application", "Synthetic managed text verification")
        provider = LocalProvider(client=connection, max_tokens=96, context_length=4096)
        response = work(lambda: runtime.generate(task["task_id"], provider, name,
            [{"role": "user", "content": "What is two plus two? Answer in one short sentence."}]), connection)
        report["steps"].append({"operation": "governed_chat", "result": response})
        if response["status"] != "completed" or not response.get("text", "").strip():
            raise RuntimeError("The governed real-model chat did not complete")

        if args.tokenizer_cases:
            fixtures = {
                "unicode": [{"role": "user", "content": "中文🙂 café e\u0301 العربية\n" * 12 + "Reply with the word hello."}],
                "code_and_control_text": [{"role": "user", "content":
                    'Literal text: <|im_start|> and <|im_end|>.\n```python\nprint("hello")\n```\nReply hello.'}],
                "paired_history": [{"role": "user", "content": "What is 2 + 2?"},
                    {"role": "assistant", "content": "Four."}, {"role": "user", "content": "Reply hello."}],
                "long_prompt": [{"role": "user", "content": "alpha beta gamma delta\n" * 200 + "Reply hello."}],
            }
            for label, messages in fixtures.items():
                connection = client()
                task = runtime.start_task("application", "Synthetic tokenizer case: " + label)
                provider = LocalProvider(client=connection, max_tokens=96, context_length=4096)
                observed = work(lambda: runtime.generate(task["task_id"], provider, name, messages), connection)
                budget, metrics = observed.get("budget", {}), observed.get("generation_metrics", {})
                matched = budget.get("verified") is True and budget.get("input_tokens") == metrics.get("prompt_eval_count")
                report["steps"].append({"operation": "tokenizer_case", "case": label, "matched": matched,
                    "result": observed})
                if not matched or observed["status"] != "completed":
                    raise RuntimeError("Actual tokenization/generation did not qualify: " + label)
            connection = client()
            task = runtime.start_task("application", "Synthetic oversized request")
            provider = LocalProvider(client=connection, max_tokens=128, context_length=4096)
            try:
                work(lambda: runtime.prepare_generation(task["task_id"], provider, name,
                    [{"role": "user", "content": "alpha beta gamma delta\n" * 1100}]), connection)
            except ValueError as exc:
                if "mandatory instructions exceed" not in str(exc):
                    raise
                intents = [e for e in runtime.timeline(task["task_id"]) if e["kind"] == "provider.intent"]
                if intents:
                    raise RuntimeError("Oversized request reached generation intent")
                report["steps"].append({"operation": "oversized_request_rejected", "reason": str(exc),
                                        "generation_intents": len(intents), "backend_state": connection.backend_state})
            else:
                raise RuntimeError("Oversized mandatory input was admitted")

        if args.deadline_cases:
            from ceta_desktop.request_control import current_budget
            connection = client()
            deadline_task = runtime.start_task("application", "Synthetic stalled output consumer deadline")
            provider = LocalProvider(client=connection, max_tokens=512, context_length=4096, timeout_seconds=30)
            delayed = False
            def slow_consumer(_):
                nonlocal delayed
                if delayed:
                    return
                delayed = True
                # Exercise deadline handling after real output. This deliberately
                # delays the harness consumer, not the model or its transport.
                end = current_budget().deadline + .05
                while time.monotonic() < end:
                    time.sleep(.01)
            def deadline_request():
                started = time.monotonic()
                result = runtime.generate(deadline_task["task_id"], provider, name,
                    [{"role": "user", "content": "Write a long numbered list of simple English words."}],
                    on_token=slow_consumer)
                return {"result": result, "elapsed_seconds": time.monotonic() - started,
                        "caller_cancelled": connection.cancelled.is_set(), "consumer_delayed": delayed}
            observed = work(deadline_request, connection, 45)
            report["steps"].append({"operation": "stalled_consumer_deadline", **observed})
            if (observed["result"]["status"] != "timed_out" or not observed["result"]["text"] or
                    observed["caller_cancelled"] or not delayed or observed["elapsed_seconds"] > 33):
                raise RuntimeError("The real request deadline did not preserve partial output and timeout identity")
            stop()
            reconciler = LocalModelClient(f"http://127.0.0.1:{port}/v1", coordination_directory=directory / "verification-coordination")
            report["steps"].append({"operation": "reconcile_after_deadline", "result": reconciler.reconcile_runtime()})
            start()
            connection = client()
            report["steps"].append({"operation": "probe_after_deadline_restart",
                                    "result": work(lambda: runtime.probe_model(connection, name), connection)})

        if args.capability_cases:
            from ceta_desktop.capabilities import measure_configuration
            connection = client()
            observed = work(lambda: measure_configuration(runtime, connection, name, cancelled=connection.cancelled), connection, 1320)
            report["steps"].append({"operation": "capability_measurement", "result": observed})
            if observed["status"] != "completed" or len(observed["samples"]) != 7:
                raise RuntimeError("The actual capability suite did not complete: " + str(observed.get("error", observed["status"])))

        if args.conversation_cases:
            fixtures = [
                ("arithmetic", [{"role": "user", "content": "What is 19 + 23? Reply with the number only."}], "42"),
                ("conversation_recall", [{"role": "user", "content": "For this conversation, my chosen color is teal."},
                    {"role": "assistant", "content": "I'll remember teal."},
                    {"role": "user", "content": "What color did I choose? Reply with the lowercase color only."}], "teal"),
                ("sentence_rewrite", [{"role": "user", "content": "Rewrite 'the meeting is at noon' with normal sentence capitalization and a final period. Return only the rewritten sentence."}], "The meeting is at noon."),
                ("unicode_copy", [{"role": "user", "content": "Copy exactly this text with no quotes or explanation: café_東京_17"}], "café_東京_17"),
                ("json_array", [{"role": "user", "content": 'Return only a JSON array containing "red" followed by "blue". Do not use a Markdown code block.'}], ["red", "blue"]),
            ]
            for label, messages, expected in fixtures:
                connection = client()
                task = runtime.start_task("application", "Synthetic conversation case: " + label)
                provider = LocalProvider(client=connection, max_tokens=1024, context_length=4096)
                observed = work(lambda: runtime.generate(task["task_id"], provider, name, messages), connection)
                answer = observed.get("text", "").strip()
                if isinstance(expected, list):
                    try:
                        answer = json.loads(answer)
                    except ValueError:
                        answer = None
                report["steps"].append({"operation": "conversation_case", "case": label,
                    "messages": messages, "expected": expected,
                    "matched": observed["status"] == "completed" and answer == expected, "result": observed})
                if observed["status"] != "completed":
                    raise RuntimeError("The conversation request did not complete: " + label)

        connection = client()
        def unload():
            snapshot = connection.resident_snapshot()
            return runtime.application_action("model.unload", {"model": name, "inspection": snapshot},
                lambda: connection.unload_model(snapshot, name))
        report["steps"].append({"operation": "unload", "result": work(unload, connection, 40)})

        connection = client()
        cancellation = threading.Event()
        task = runtime.start_task("application", "Synthetic managed cancellation verification")
        provider = LocalProvider(client=connection, max_tokens=512, context_length=4096)
        result = work(lambda: runtime.generate(task["task_id"], provider, name,
            [{"role": "user", "content": "Write a long numbered list of simple English words, one word per line."}],
            cancelled=cancellation, on_token=lambda _: cancellation.set()), connection)
        report["steps"].append({"operation": "cancel_generation", "result": result})
        if result["status"] != "cancelled":
            raise RuntimeError("The generation did not observe cancellation")
        stop()
        reconciler = LocalModelClient(f"http://127.0.0.1:{port}/v1", coordination_directory=directory / "verification-coordination")
        report["steps"].append({"operation": "reconcile", "result": reconciler.reconcile_runtime()})
        start()
        connection = client()
        report["steps"].append({"operation": "probe_after_restart",
                                "result": work(lambda: runtime.probe_model(connection, name), connection)})
        stop()
        report["passed"] = True
    except (OSError, ValueError, RuntimeError) as exc:
        report["error"] = str(exc)
    finally:
        process.kill()
        if not process.waitForFinished(5000):
            report.update(passed=False, cleanup_error="Owned worker shutdown is unconfirmed")
        if runtime is not None:
            runtime.close()
        process.deleteLater(); application.processEvents()
    after = source_attribution()
    report["source_after_sha256"] = after["source_sha256"]
    report["source_unchanged"] = before["source_sha256"] == after["source_sha256"]
    report["passed"] = report["passed"] and report["source_unchanged"]
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2); handle.write("\n")
    print(json.dumps({"passed": report["passed"], "steps": len(report["steps"]), "error": report.get("error"), "report": str(args.report)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
