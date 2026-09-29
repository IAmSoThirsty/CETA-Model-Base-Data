"""Bounded synthetic observations through the same governed path as local chat."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
from uuid import uuid4

from . import __version__
from .hardware import inspect_hardware
from .request_control import ModelCancelledError, ModelDeadlineError
from .request_tokens import check_runner
from .runtime_installation import _directory, _plain
from runtime.journal import digest
from runtime.model_provider import LocalProvider

REVISION = "ceta-text-capabilities-v1"
SESSION = uuid4().hex
CONTEXT = 4096
OUTPUT = 1024
REQUEST_SECONDS = 180
SUITE_SECONDS = 1260
PERFORMANCE_PROMPT = "Write the numbers from 1 through 60 in order, separated by spaces. Do not add commentary."


def hardware_identity(profile):
    # Free memory is rechecked for every request, not a durable device identity.
    return {"os": platform.system(), "os_version": platform.version(), "architecture": platform.machine(),
            "ram_bytes": profile.total_ram_bytes, "logical_cpus": profile.logical_cpus,
            "gpus": [{"name": gpu.name, "total_bytes": gpu.total_bytes, "source": gpu.backend}
                     for gpu in profile.gpus]}


def build_identity(cancelled=None):
    root = Path(__file__).resolve().parents[1]
    paths = [Path(sys.executable)] if getattr(sys, "frozen", False) else sorted(
        path for path in root.rglob("*") if path.suffix in {".py", ".json"} and "__pycache__" not in path.parts)
    hashes = {}
    for path in paths:
        value = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                if cancelled is not None and cancelled.is_set():
                    raise ModelCancelledError("Measurement stopped.")
                value.update(block)
        hashes[path.name if getattr(sys, "frozen", False) else path.relative_to(root).as_posix()] = value.hexdigest()
    return {"version": __version__, "code_sha256": digest(hashes), "python": platform.python_version(),
            "form": "frozen-executable" if getattr(sys, "frozen", False) else "source"}


def configuration(client, model, hardware, build):
    assets = client.managed_assets
    if assets is None or not client.expected_job or client.managed_directory is None:
        raise ValueError("Measurement currently requires a CETA-managed runtime and pinned model. Start and test one first.")
    runtime = assets.assert_runtime()
    if assets.job_name != client.expected_job:
        raise ValueError("The protected runtime session changed. Recheck setup before measuring.")
    profile = client.request_profile(model)
    if profile.get("backend") != "ollama" or profile.get("locality") != "local" or not profile.get("digest"):
        raise ValueError("The selected model has no qualified local identity.")
    return {"session": SESSION, "fixture_revision": REVISION, "build": build, "model": model,
            "hardware": hardware_identity(hardware), "profile": profile,
            "runtime": {key: runtime[key] for key in ("version", "archive_sha256")},
            "asset_session": assets.session_id, "job": client.expected_job,
            "context_length": CONTEXT, "max_tokens": OUTPUT, "parallel_requests": 1}


def response_metrics(result, first_token, elapsed):
    raw = result.get("generation_metrics") or {}
    if not isinstance(raw, dict):
        raw = {}
    def number(key, maximum, integer=False):
        value = raw.get(key)
        if (type(value) not in ((int,) if integer else (int, float)) or
                not math.isfinite(value) or not 0 < value <= maximum):
            return None
        return value
    count = number("eval_count", OUTPUT, True)
    duration = number("eval_duration", REQUEST_SECONDS * 1e9)
    load = number("load_duration", REQUEST_SECONDS * 1e9)
    return {"first_visible_seconds": first_token, "total_seconds": elapsed,
            "output_tokens": count, "decode_seconds": duration / 1e9 if duration else None,
            "tokens_per_second": count * 1e9 / duration if count and duration else None,
            "load_seconds": load / 1e9 if load else None,
            "source": "CETA monotonic wall time; runtime-reported token counts and nanosecond durations"}


def fixture_passed(identifier, text, token, file_token):
    if identifier.startswith("warm_"):
        return text.split() == [str(number) for number in range(1, 61)]
    if identifier == "instruction_exact":
        return text.strip() == token
    if identifier in {"instruction_json", "selected_file"}:
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            return False
        expected = {"answer": 7} if identifier == "instruction_json" else {"ticket": file_token, "source": "sample.txt"}
        return value == expected and (identifier != "instruction_json" or type(value.get("answer")) is int)
    return bool(text.strip())


def summarize(report):
    rows = {row["case"]: row for row in report.get("samples", [])}
    def outcome(names):
        if any(name not in rows or rows[name]["status"] != "completed" for name in names):
            return "not completed"
        return "passed" if all(rows[name]["matched"] for name in names) else "failed"
    speed = "unmeasured"
    warm = [rows.get(f"warm_{index}") for index in range(1, 4)]
    if all(row and row["status"] == "completed" and row["matched"] and row["metrics"]["first_visible_seconds"] is not None and
           row["metrics"]["tokens_per_second"] is not None and (row["metrics"]["output_tokens"] or 0) >= 16 for row in warm):
        speed = "responsive" if all(row["metrics"]["first_visible_seconds"] <= 5 and
                                      row["metrics"]["tokens_per_second"] >= 5 for row in warm) else "slow"
    return {"local_text": outcome(["cold"]), "instruction_smoke": outcome(["instruction_exact", "instruction_json"]),
            "selected_file_smoke": outcome(["selected_file"]), "warm_speed": speed,
            "unqualified": ["reviewed code edits", "longer context", "GPU placement", "vision", "voice", "autonomous tools"]}


def measure_configuration(runtime, client, model, *, cancelled, progress=lambda _: None):
    """Explicit action: unload selected weights and run seven synthetic requests.

    Results are retained in the canonical application journal, never restored as
    readiness. Synthetic selected-file bytes remain under this profile for audit.
    """
    runtime.application_project()
    started = time.monotonic()
    deadline = started + SUITE_SECONDS
    report = {"schema": "ceta.capability-observation.v1", "id": uuid4().hex, "created_at": time.time(),
              "fixture_revision": REVISION, "status": "running", "samples": [], "configuration": None,
              "scope": "Synthetic smoke checks on this exact session/configuration, not a general quality benchmark"}
    def check():
        if cancelled.is_set():
            raise ModelCancelledError("Measurement stopped. Completed observations are retained.")
        if time.monotonic() >= deadline:
            raise ModelDeadlineError("The measurement time limit was reached.")
    runtime.journal.append("application", "capability.measurement.intent", {"id": report["id"], "revision": REVISION})
    try:
        check()
        progress("Inspecting this computer and the selected protected model…")
        hardware = inspect_hardware(cancelled=cancelled)
        build = build_identity(cancelled)
        binding = configuration(client, model, hardware, build)
        report.update(configuration=binding, hardware_observation=asdict(hardware))
        snapshot = client.resident_snapshot()
        resident = [row for row in snapshot["models"] if row.get("digest") == binding["profile"]["digest"]]
        if len(resident) > 1 or (resident and resident[0]["name"] != model):
            raise ValueError("The selected digest has ambiguous residency. Inspect loaded models before measuring a cold sample.")
        if resident:
            progress("Unloading the selected model for the cold sample…")
            report["unload"] = runtime.application_action("model.unload", {"model": model, "inspection": snapshot},
                lambda: client.unload_model(snapshot, model))
        if any(row.get("digest") == binding["profile"]["digest"] for row in client.resident_snapshot()["models"]):
            raise ValueError("The selected digest is still resident. No cold sample was measured.")
        report["cold_basis"] = "Selected digest reported absent before request preparation; OS file caches are not cleared"
        token, file_token = "CETA_" + uuid4().hex[:12], uuid4().hex
        fixtures = [("cold", PERFORMANCE_PROMPT),
                    ("instruction_exact", f"Reply with exactly {token} and no other text."),
                    ("instruction_json", 'Return exactly one JSON object with the key "answer" and the integer result of 3 + 4. No other text.'),
                    ("selected_file", 'Read the attached sample.txt. Return exactly a JSON object with its ticket value and "source":"sample.txt". No other text.'),
                    *[(f"warm_{index}", PERFORMANCE_PROMPT) for index in range(1, 4)]]
        sample_root = _directory(Path(runtime.directory) / "capability-samples")
        sample_root = sample_root / report["id"]
        sample_root.mkdir()
        _plain(sample_root, directory=True)
        text = f"Synthetic CETA fixture data.\nticket: {file_token}\nquantity: 29\n"
        with (sample_root / "sample.txt").open("x", encoding="utf-8", newline="\n") as fixture:
            fixture.write(text)
        project = runtime.open_project(sample_root)
        report["fixture_project"] = project["project_id"]
        worker_binding = None
        for identifier, prompt in fixtures:
            check()
            if configuration(client, model, hardware, build) != binding:
                raise ValueError("Model/runtime configuration changed during measurement.")
            check()
            progress(f"Measuring {len(report['samples']) + 1}/7: {identifier.replace('_', ' ')}…")
            task = runtime.start_task(project["project_id"] if identifier == "selected_file" else "application",
                                      "Synthetic capability check: " + identifier)
            attachments = []
            if identifier == "selected_file":
                observed = runtime.read(task["task_id"], "sample.txt")
                if observed["sha256"] != hashlib.sha256(text.encode("utf-8")).hexdigest():
                    raise ValueError("The synthetic sample file changed. Its result cannot qualify selected-file use.")
                attachments = [{"path": "sample.txt", "workspace": str(sample_root), "text": text,
                                "base_sha256": observed["sha256"], "text_sha256": hashlib.sha256(text.encode()).hexdigest()}]
            first = None
            check()
            began = time.monotonic()
            def on_token(part):
                nonlocal first
                if first is None and part.strip():
                    first = time.monotonic() - began
            provider = LocalProvider(client=client, context_length=CONTEXT, max_tokens=OUTPUT,
                                     timeout_seconds=min(REQUEST_SECONDS, deadline - began))
            result = runtime.generate(task["task_id"], provider, model, [{"role": "user", "content": prompt}],
                                      cancelled=cancelled, on_token=on_token, attachments=attachments)
            count = result.get("budget", {}).get("tokenization", {})
            current_worker = count.get("binding")
            stable = isinstance(current_worker, dict) and count.get("verified") is True
            if worker_binding is None:
                worker_binding = current_worker
            stable = stable and current_worker == worker_binding
            row = {"case": identifier, "status": result["status"], "text": result.get("text", ""),
                   "matched": result["status"] == "completed" and stable and fixture_passed(identifier, result.get("text", ""), token, file_token),
                   "metrics": response_metrics(result, first, time.monotonic() - began),
                   "request_id": result.get("request_id"), "task_id": task["task_id"], "payload_hash": result.get("payload_hash"),
                   "tokenization": count, "error": result.get("error"), "backend_state": result.get("backend_state"),
                   "resource_admission": result.get("resource_admission")}
            report["samples"].append(row)
            if not stable:
                raise ValueError("Exact counting or the owned worker identity changed; these observations are unqualified.")
            if result["status"] != "completed":
                report["status"] = result["status"]
                break
        else:
            check()
            check_runner(client, worker_binding)
            if (configuration(client, model, inspect_hardware(cancelled=cancelled), build_identity(cancelled)) != binding):
                raise ValueError("Computer, build, model or runtime changed during measurement.")
            report["runtime_residency"] = client.resident_snapshot()
            check()
            report["status"] = "completed"
        report["worker_binding"] = worker_binding
    except Exception as exc:
        report["status"] = "cancelled" if cancelled.is_set() or isinstance(exc, ModelCancelledError) else (
            "timed_out" if isinstance(exc, TimeoutError) else "failed")
        report["error"] = str(exc)
    report["elapsed_seconds"] = time.monotonic() - started
    report["summary"] = summarize(report)
    report["eligible_session_observation"] = report["status"] == "completed"
    report = json.loads(json.dumps(report, allow_nan=False))
    runtime.journal.append("application", "capability.measurement.result", report, actor_id="runtime:capability-observer")
    return report


def format_report(report, *, historical=False):
    summary = report["summary"]
    lines = [("Historical observation — remeasure before using it for current choices." if historical else
              "Synthetic observations for this session; general answer quality remains unproven."),
             "Model: " + str((report.get("configuration") or {}).get("model", "unavailable")),
             f"Suite: {report['status']} · {report['elapsed_seconds']:.1f}s",
             f"Text: {summary['local_text']} · Instruction checks: {summary['instruction_smoke']} · Selected-file check: {summary['selected_file_smoke']}",
             f"Warm response speed: {summary['warm_speed']} (three matching runs; target ≤5s first text and ≥5 reported tokens/s)."]
    for row in report["samples"]:
        metrics = row["metrics"]
        first, speed = metrics["first_visible_seconds"], metrics["tokens_per_second"]
        timing = f"first text {first:.2f}s" if first is not None else "first text unknown"
        rate = f"{speed:.1f} reported tokens/s" if speed is not None else "throughput unknown"
        matched = "text returned" if row["case"] == "cold" and row["matched"] else ("matched" if row["matched"] else "not matched")
        lines.append(f"{row['case']}: {row['status']}, {matched} · {timing} · {rate} · total {metrics['total_seconds']:.2f}s")
        if row["case"] in {"instruction_exact", "instruction_json", "selected_file"}:
            lines.append("  Observed answer: " + row.get("text", "").replace("\n", " ")[:250])
    if report.get("error"):
        lines.append(report["error"])
    lines.append("Not qualified: " + ", ".join(summary["unqualified"]) + ".")
    return "\n".join(lines)
