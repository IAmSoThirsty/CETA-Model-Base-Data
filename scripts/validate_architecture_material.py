from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "data" / "ceta_architecture_material_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    base = args.root.resolve()
    manifest_path = base / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"CETA ARCHITECTURE MATERIAL VALIDATION: FAIL - missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if manifest.get("dataset_id") != "CETA_ARCHITECTURE_MATERIAL/v1":
        fail(errors, "dataset_id mismatch")
    expected_paths = set()
    for item in manifest.get("files", []):
        relative = str(item.get("path", ""))
        if not relative or relative in expected_paths:
            fail(errors, f"invalid or duplicate file record: {relative!r}")
            continue
        expected_paths.add(relative)
        path = base / relative
        if not path.is_file():
            fail(errors, f"registered file missing: {relative}")
            continue
        if path.stat().st_size != int(item.get("size_bytes", -1)):
            fail(errors, f"registered file size mismatch: {relative}")
        if sha256(path) != item.get("sha256"):
            fail(errors, f"registered file hash mismatch: {relative}")

    actual_paths = {
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        fail(errors, f"manifest/file-set mismatch: missing={sorted(expected_paths-actual_paths)} extra={sorted(actual_paths-expected_paths)}")

    counts = manifest.get("counts", {})
    expected_counts = {
        "codex_sections": 406,
        "section_situational_templates": 1624,
        "roles": 21,
        "role_conditioned_cases": 84,
        "public_scenarios": 20,
        "unacceptable_failure_examples": 5,
        "ceta_operations_ranked": 23,
    }
    if counts != expected_counts:
        fail(errors, f"declared counts mismatch: {counts}")

    record_counts = {
        "codex_sections": len(jsonl(base / "training/section_awareness_406.jsonl")),
        "section_situational_templates": len(jsonl(base / "training/section_situational_templates_1624.jsonl")),
        "roles": len(json.loads((base / "training/role_contracts_21.json").read_text(encoding="utf-8"))),
        "role_conditioned_cases": len(jsonl(base / "training/role_conditioned_cases_84.jsonl")),
        "public_scenarios": len(jsonl(base / "training/public_scenarios.jsonl")),
        "unacceptable_failure_examples": len(json.loads((base / "training/unacceptable_failures.json").read_text(encoding="utf-8"))),
        "ceta_operations_ranked": len(json.loads((base / "governance/operation_risk_ranking.json").read_text(encoding="utf-8"))),
    }
    if record_counts != expected_counts:
        fail(errors, f"materialized record counts mismatch: {record_counts}")

    canonical_ops = set(json.loads((ROOT / "registry/ceta_operations.json").read_text(encoding="utf-8"))["operations"])
    risk = json.loads((base / "governance/operation_risk_ranking.json").read_text(encoding="utf-8"))
    equivalence = json.loads((base / "governance/semantic_equivalence_by_operation.json").read_text(encoding="utf-8"))
    if {str(item["Operation"]) for item in risk} != canonical_ops:
        fail(errors, "risk ranking does not cover the canonical 23 operations")
    if set(equivalence) != canonical_ops:
        fail(errors, "semantic-equivalence map does not cover the canonical 23 operations")

    for name in ("evaluation/jbb_benign_behaviors.csv", "evaluation/jbb_harmful_behaviors.csv"):
        with (base / name).open("r", encoding="utf-8-sig", newline="") as handle:
            if sum(1 for _ in csv.DictReader(handle)) != 100:
                fail(errors, f"JBB evaluation record count mismatch: {name}")

    holdout = manifest.get("private_holdout", {})
    if holdout.get("status") != "PRIVATE_EVALUATION_ONLY" or holdout.get("materialized_in_repository") is not False:
        fail(errors, "private holdout exclusion boundary is missing")
    forbidden_names = {"PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl", "ANSWER_KEY_SEPARATE.jsonl"}
    if any(path.name in forbidden_names for path in base.rglob("*")):
        fail(errors, "private challenge or answer key was materialized")
    if manifest.get("training_boundary", {}).get("current_ceta_curriculum_automatically_modified") is not False:
        fail(errors, "raw supplied material must not claim automatic structured-curriculum conversion")

    if errors:
        print("CETA ARCHITECTURE MATERIAL VALIDATION: FAIL")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)
    print("CETA ARCHITECTURE MATERIAL VALIDATION: PASS")
    print(f"files={len(expected_paths)} sections={record_counts['codex_sections']} templates={record_counts['section_situational_templates']}")
    print(f"public_scenarios={record_counts['public_scenarios']} defensive_behaviors=200 private_holdout_materialized=false")


if __name__ == "__main__":
    main()
