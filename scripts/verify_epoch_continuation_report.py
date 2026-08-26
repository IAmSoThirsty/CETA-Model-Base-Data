from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from history import domain_hash
from training import file_sha256


DATA = ROOT / "data" / "ceta_curriculum_v3"


def fail(message: str) -> None:
    raise SystemExit(f"EPOCH CONTINUATION REPORT VERIFY: FAIL - {message}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.expanduser().resolve()
    if not report_path.is_file():
        fail(f"report missing: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    claimed = report.get("report_hash")
    body = dict(report)
    body.pop("report_hash", None)
    if claimed != domain_hash(body, domain="CETA/EPOCH_CONTINUATION_REPORT/v1"):
        fail("report hash mismatch")
    if report.get("status") != "PASS" or report.get("report_type") != "CETA_EPOCH_CONTINUATION":
        fail("report status or type mismatch")
    attestation = report.get("device_attestation", {})
    if (
        attestation.get("device") != "cuda:0"
        or attestation.get("visible_cuda_devices") != 1
        or attestation.get("distributed_training") is not False
        or "H100" not in str(attestation.get("device_name", "")).upper()
    ):
        fail("single-H100 attestation mismatch")
    binding = report.get("curriculum_binding", {})
    manifest = DATA / "manifest.json"
    splits = DATA / "splits.json"
    if binding.get("manifest_sha256") != file_sha256(manifest):
        fail("curriculum manifest binding mismatch")
    if binding.get("splits_sha256") != file_sha256(splits):
        fail("curriculum splits binding mismatch")
    if binding.get("generator_id") != json.loads(manifest.read_text(encoding="utf-8")).get("generator_id"):
        fail("curriculum generator binding mismatch")
    base = report.get("base_checkpoint", {}).get("cursor", {})
    final = report.get("final_checkpoint", {}).get("cursor", {})
    additional = int(report.get("additional_epochs", 0))
    train_cases = int(report.get("dataset", {}).get("train_cases", 0))
    if additional < 1 or train_cases < 1:
        fail("continuation size is invalid")
    if final.get("epoch_index") != base.get("epoch_index", -1) + additional:
        fail("final epoch target mismatch")
    if final.get("global_step") != base.get("global_step", -1) + additional * train_cases:
        fail("final optimizer-step target mismatch")
    if final.get("next_case_offset") != 0:
        fail("final checkpoint is not at an epoch boundary")
    validation = report.get("validation", {})
    if validation.get("checkpoint_sha256") != report.get("final_checkpoint", {}).get("sha256"):
        fail("validation is not final-checkpoint bound")
    if validation.get("dataset_sha256") != file_sha256(DATA / "validation.jsonl"):
        fail("validation split hash mismatch")
    if report.get("heldout_evaluation", {}).get("status") != "NOT_RUN":
        fail("heldout was used during iterative continuation")
    boundary = report.get("claim_boundary", {})
    if boundary.get("hardware_activated_by_runner") is not False:
        fail("runner hardware-activation boundary mismatch")
    if boundary.get("single_h100_only") is not True or boundary.get("distributed_training") is not False:
        fail("single-H100 boundary mismatch")
    if boundary.get("controlled_evaluation_optimizer_trained") is not False:
        fail("controlled evaluation optimizer boundary mismatch")
    if report.get("promotion_gate", {}).get("outcome") not in {"PROMOTED", "QUALIFIED", "QUARANTINED"}:
        fail("promotion outcome missing")
    print("EPOCH CONTINUATION REPORT VERIFY: PASS")
    print(
        f"report_hash={claimed} additional_epochs={additional} "
        f"promotion={report['promotion_gate']['outcome']}"
    )


if __name__ == "__main__":
    main()
