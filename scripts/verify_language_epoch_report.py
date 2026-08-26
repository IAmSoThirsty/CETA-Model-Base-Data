from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("ceta_language_adapter_verifier", ROOT / "src/training/language_adapter.py")
assert SPEC is not None and SPEC.loader is not None
LANGUAGE_ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANGUAGE_ADAPTER
SPEC.loader.exec_module(LANGUAGE_ADAPTER)


def canonical_hash(value: Any, *, domain: str) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(domain.encode("utf-8") + b"\n" + raw).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"CETA LANGUAGE EPOCH VERIFICATION: FAIL - {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a completed language-adapter epoch and controlled evaluation.")
    parser.add_argument("--training-run", type=Path, required=True)
    parser.add_argument("--inference-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    training_root = args.training_run.resolve()
    training_path = training_root / "TRAINING_REPORT.json"
    binding_path = training_root / "RUN_BINDING.json"
    complete_path = training_root / "TRAINING_COMPLETE"
    for path in (training_path, binding_path, complete_path):
        if not path.is_file():
            fail(f"missing training artifact: {path.name}")
    training = json.loads(training_path.read_text(encoding="utf-8"))
    training_body = {key: value for key, value in training.items() if key != "report_hash"}
    if training.get("report_hash") != canonical_hash(training_body, domain="CETA/LANGUAGE_ADAPTER_TRAINING_REPORT/v1"):
        fail("training report hash mismatch")
    if complete_path.read_text(encoding="utf-8").strip() != training["report_hash"]:
        fail("training completion marker mismatch")
    if training.get("controlled_evaluation_used_for_training") is not False or training.get("controlled_evaluation_run") is not False:
        fail("controlled-evaluation training boundary mismatch")
    if int(training.get("global_step", -1)) != int(training.get("expected_optimizer_steps", -2)):
        fail("optimizer did not finish the bound epoch")
    if LANGUAGE_ADAPTER.sha256_file(binding_path) != training.get("run_binding_sha256"):
        fail("run binding hash mismatch")
    adapter = training_root / "adapter"
    actual_adapter_files = {
        path.relative_to(adapter).as_posix(): LANGUAGE_ADAPTER.sha256_file(path)
        for path in sorted(adapter.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    if actual_adapter_files != training.get("adapter_files"):
        fail("adapter artifact hash mismatch")
    if not any(path.is_dir() and path.name.startswith("checkpoint-") for path in (training_root / "checkpoints").glob("checkpoint-*")):
        fail("no durable Trainer checkpoint exists")

    inference_root = args.inference_root.resolve()
    inference_path = inference_root / "inference_manifest.json"
    predictions_path = inference_root / "predictions.jsonl"
    if not inference_path.is_file() or not predictions_path.is_file():
        fail("inference evidence is incomplete")
    inference = json.loads(inference_path.read_text(encoding="utf-8"))
    inference_body = {key: value for key, value in inference.items() if key != "inference_hash"}
    if inference.get("inference_hash") != canonical_hash(inference_body, domain="CETA/CONTROLLED_LANGUAGE_INFERENCE/v1"):
        fail("inference manifest hash mismatch")
    if inference.get("training_report_hash") != training.get("report_hash") or inference.get("answer_key_accessed") is not False:
        fail("inference independence binding mismatch")
    if LANGUAGE_ADAPTER.sha256_file(predictions_path) != inference.get("predictions_sha256"):
        fail("prediction hash mismatch")

    report = json.loads(args.report.resolve().read_text(encoding="utf-8"))
    report_body = {key: value for key, value in report.items() if key != "report_hash"}
    if report.get("report_hash") != canonical_hash(report_body, domain="CETA/CONTROLLED_LANGUAGE_EVALUATION_REPORT/v1"):
        fail("controlled-evaluation report hash mismatch")
    if report.get("training_report_hash") != training.get("report_hash") or report.get("inference_hash") != inference.get("inference_hash"):
        fail("controlled-evaluation lineage mismatch")
    if report.get("promotion_performed") is not False:
        fail("controlled evaluator performed unauthorized promotion")
    gates = report.get("gates", {})
    expected_status = "QUALIFIED" if gates and all(value is True for value in gates.values()) else "QUARANTINED"
    if report.get("status") != expected_status:
        fail("controlled-evaluation status disagrees with frozen gates")
    policy = report.get("evaluation_policy", {})
    if policy.get("heldout_feedback_to_optimizer") is not False or policy.get("promotion_authority") != "INDEPENDENT_EVALUATOR_ONLY":
        fail("controlled-evaluation authority boundary mismatch")
    print(
        "CETA LANGUAGE EPOCH VERIFICATION: PASS "
        f"steps={training['global_step']} predictions={inference['prediction_count']} "
        f"status={report['status']} report={report['report_hash']}"
    )


if __name__ == "__main__":
    main()
