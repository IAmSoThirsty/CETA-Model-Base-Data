from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from history import domain_hash
from training import file_sha256


DEFAULT_REPORT = ROOT / "evidence" / "STRUCTURED_POLICY_H100_SCHEMA_V4_FINAL_HELDOUT.json"
DEFAULT_CONTINUATION = ROOT / "evidence" / "STRUCTURED_POLICY_H100_SCHEMA_V4_EPOCH_5.json"
DATA = ROOT / "data" / "ceta_curriculum_v3"


def fail(message: str) -> None:
    raise SystemExit(f"FINAL HELDOUT REPORT VERIFY: FAIL - {message}")


def verify_metric_contract(metrics: dict) -> None:
    expected = {
        "target_accuracy": "exact selected full transition matches target",
        "opcode_accuracy": "selected transition operation matches target operation",
        "state_only_auxiliary_opcode_head": False,
        "operation_selection_objective": "maximum candidate score grouped by operation",
    }
    if metrics.get("metric_contract") != expected:
        fail("held-out metric contract mismatch")
    metric_body = dict(metrics)
    evaluation_hash = metric_body.pop("evaluation_hash", None)
    if evaluation_hash != domain_hash(metric_body, domain="CETA/INDEPENDENT_EVALUATION/v2"):
        fail("held-out evaluation hash mismatch")
    if any(float(metrics.get(key, -1.0)) != 1.0 for key in (
        "target_accuracy", "opcode_accuracy", "legal_selection_rate",
    )):
        fail("held-out exact, operation, and legal-selection rates must all equal 1")
    if int(metrics.get("selection_error_count", -1)) != 0 or metrics.get("selection_errors") != []:
        fail("held-out selection errors are not zero")
    if int(metrics.get("selection_error_family_count", -1)) != 0:
        fail("held-out selection-error families are not zero")
    if int(metrics.get("opcode_error_count", -1)) != 0 or int(metrics.get("opcode_error_family_count", -1)) != 0:
        fail("held-out operation errors are not zero")
    if int(metrics.get("ambiguous_top_selection_count", -1)) != 0:
        fail("held-out evaluation contains an ambiguous top selection")
    if float(metrics.get("mean_target_candidate_margin", 0.0)) <= 0.0:
        fail("held-out target-candidate margin is not positive")
    if float(metrics.get("mean_transition_loss", -1.0)) < 0.0:
        fail("held-out transition loss is invalid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--continuation", type=Path, default=DEFAULT_CONTINUATION)
    args = parser.parse_args()
    report_path = args.report.expanduser().resolve()
    continuation_path = args.continuation.expanduser().resolve()
    if not report_path.is_file():
        fail(f"report missing: {report_path}")
    if not continuation_path.is_file():
        fail(f"continuation report missing: {continuation_path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    claimed = report.get("report_hash")
    body = dict(report)
    body.pop("report_hash", None)
    if claimed != domain_hash(body, domain="CETA/FINAL_HELDOUT_EVALUATION/v1"):
        fail("report hash mismatch")
    if (
        report.get("schema_version") != 1
        or report.get("report_type") != "CETA_FINAL_HELDOUT_EVALUATION"
        or report.get("status") != "PASS"
    ):
        fail("report schema, type, or status mismatch")

    continuation = json.loads(continuation_path.read_text(encoding="utf-8"))
    continuation_body = dict(continuation)
    continuation_hash = continuation_body.pop("report_hash", None)
    if continuation_hash != domain_hash(continuation_body, domain="CETA/EPOCH_CONTINUATION_REPORT/v2"):
        fail("source continuation report hash mismatch")
    source = report.get("source_continuation_report", {})
    if source.get("sha256") != file_sha256(continuation_path):
        fail("source continuation byte hash mismatch")
    if source.get("path") != "EPOCH_CONTINUATION_E0005_REPORT.json":
        fail("source continuation path identity mismatch")
    if continuation.get("promotion_gate", {}).get("outcome") != "PROMOTED":
        fail("source continuation checkpoint was not promoted")
    if continuation.get("heldout_evaluation", {}).get("status") != "NOT_RUN":
        fail("source continuation used held-out evaluation iteratively")

    checkpoint = report.get("checkpoint", {})
    source_checkpoint = continuation.get("final_checkpoint", {})
    source_cursor = source_checkpoint.get("cursor", {})
    if checkpoint.get("sha256") != source_checkpoint.get("sha256"):
        fail("held-out checkpoint does not match the promoted checkpoint")
    if checkpoint.get("path") != source_checkpoint.get("path"):
        fail("held-out checkpoint path identity mismatch")
    if checkpoint.get("epoch_index") != source_cursor.get("epoch_index") or checkpoint.get("epoch_index") != 5:
        fail("held-out checkpoint epoch mismatch")
    if checkpoint.get("global_step") != source_cursor.get("global_step") or checkpoint.get("global_step") != 5520:
        fail("held-out checkpoint optimizer-step mismatch")

    attestation = report.get("device_attestation", {})
    if (
        attestation.get("device") != "cuda:0"
        or attestation.get("visible_cuda_devices") != 1
        or attestation.get("distributed_training") is not False
        or "H100" not in str(attestation.get("device_name", "")).upper()
    ):
        fail("single-H100 attestation mismatch")
    optimizer = report.get("optimizer_evidence", {})
    if (
        optimizer.get("before_evaluation") != 5520
        or optimizer.get("after_evaluation") != 5520
        or optimizer.get("heldout_feedback_to_optimizer") is not False
    ):
        fail("held-out optimizer isolation mismatch")
    boundary = report.get("claim_boundary", {})
    if (
        boundary.get("heldout_authorized_promotion") is not False
        or boundary.get("post_heldout_optimizer_steps") != 0
        or boundary.get("production_model_quality_claimed") is not False
    ):
        fail("held-out claim boundary mismatch")

    heldout = report.get("heldout", {})
    verify_metric_contract(heldout)
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    if heldout.get("case_count") != manifest["files"]["heldout"]["count"]:
        fail("held-out case-count mismatch")
    if heldout.get("dataset_sha256") != file_sha256(DATA / "heldout.jsonl"):
        fail("held-out dataset byte hash mismatch")
    if heldout.get("curriculum_manifest_sha256") != file_sha256(DATA / "manifest.json"):
        fail("held-out curriculum manifest binding mismatch")
    if heldout.get("curriculum_splits_sha256") != file_sha256(DATA / "splits.json"):
        fail("held-out curriculum splits binding mismatch")
    if heldout.get("checkpoint_sha256") != checkpoint.get("sha256"):
        fail("held-out metrics are not checkpoint-bound")

    canonical = set(json.loads((ROOT / "registry" / "ceta_operations.json").read_text(encoding="utf-8"))["operations"])
    operation_metrics = heldout.get("operation_metrics", {})
    if set(operation_metrics) != canonical:
        fail("held-out operation coverage mismatch")
    for operation, metrics in operation_metrics.items():
        if int(metrics.get("case_count", 0)) < 1:
            fail(f"held-out operation has no cases: {operation}")
        if any(float(metrics.get(key, -1.0)) != 1.0 for key in (
            "target_accuracy", "opcode_accuracy", "legal_selection_rate",
        )):
            fail(f"held-out operation metric is not perfect: {operation}")
        if int(metrics.get("illegal_selection_count", -1)) != 0:
            fail(f"held-out operation selected an illegal transition: {operation}")

    print("FINAL HELDOUT REPORT VERIFY: PASS")
    print(
        f"report_hash={claimed} checkpoint={checkpoint['sha256']} "
        f"target={heldout['target_accuracy']:.6f} legal={heldout['legal_selection_rate']:.6f}"
    )
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
