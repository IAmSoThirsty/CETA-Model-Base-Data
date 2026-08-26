from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "data" / "ceta_architecture_material_v1"
STRUCTURED_DERIVATION_ELIGIBLE = "STRUCTURED_DERIVATION_ELIGIBLE"
PROVENANCE_OR_CONSTRAINT_ONLY = "PROVENANCE_OR_CONSTRAINT_ONLY"


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


def expected_source_usage(relative_path: str) -> str:
    top_level = PurePosixPath(relative_path).parts[0]
    if top_level in {"training", "evaluation", "governance"}:
        return STRUCTURED_DERIVATION_ELIGIBLE
    if top_level in {"maps", "mission", "provenance"}:
        return PROVENANCE_OR_CONSTRAINT_ONLY
    raise ValueError(f"material path has no expected source-usage classification: {relative_path}")


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
    if manifest.get("schema_version") != 3:
        fail(errors, "manifest schema_version must be 3")
    expected_paths = set()
    declared_usage: dict[str, str] = {}
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
        try:
            expected_usage = expected_source_usage(relative)
        except ValueError as exc:
            fail(errors, str(exc))
        else:
            actual_usage = str(item.get("source_usage", ""))
            declared_usage[relative] = actual_usage
            if actual_usage != expected_usage:
                fail(errors, f"source-usage classification mismatch: {relative} -> {actual_usage!r}")

    actual_paths = {
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        fail(errors, f"manifest/file-set mismatch: missing={sorted(expected_paths-actual_paths)} extra={sorted(actual_paths-expected_paths)}")

    boundary = manifest.get("training_boundary", {})
    if boundary.get("source_usage_policy_version") != 2:
        fail(errors, "source-usage policy version mismatch")
    if boundary.get("source_usage_by_path") != declared_usage:
        fail(errors, "training-boundary source_usage_by_path does not match file records")
    expected_usage_counts = {
        STRUCTURED_DERIVATION_ELIGIBLE: 15,
        PROVENANCE_OR_CONSTRAINT_ONLY: 9,
    }
    if boundary.get("source_usage_counts") != expected_usage_counts:
        fail(errors, f"source-usage counts mismatch: {boundary.get('source_usage_counts')}")
    if boundary.get("optimizer_requires_derived_structured_cases") is not True:
        fail(errors, "optimizer boundary must require derived structured cases")

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

    controlled_evaluation = manifest.get("controlled_evaluation", {})
    if (
        controlled_evaluation.get("usage_class") != "CONTROLLED_EVALUATION"
        or controlled_evaluation.get("bound_to_architecture") is not True
        or controlled_evaluation.get("materialized_in_repository") is not False
        or controlled_evaluation.get("known_exposed_case_ids") != ["H001"]
        or controlled_evaluation.get("clean_unseen_case_count") != 59
    ):
        fail(errors, "controlled evaluation binding is missing or incomplete")
    forbidden_names = {"PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl", "ANSWER_KEY_SEPARATE.jsonl"}
    if any(path.name in forbidden_names for path in base.rglob("*")):
        fail(errors, "controlled evaluation payload entered the public material directory")
    if boundary.get("current_ceta_curriculum_automatically_modified") is not True:
        fail(errors, "material manifest does not acknowledge the generated v3 curriculum")

    if errors:
        print("CETA ARCHITECTURE MATERIAL VALIDATION: FAIL")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)
    print("CETA ARCHITECTURE MATERIAL VALIDATION: PASS")
    print(f"files={len(expected_paths)} sections={record_counts['codex_sections']} templates={record_counts['section_situational_templates']}")
    print(
        f"public_scenarios={record_counts['public_scenarios']} defensive_behaviors=200 "
        f"derivation_eligible_sources={expected_usage_counts[STRUCTURED_DERIVATION_ELIGIBLE]} "
        "controlled_evaluation_bound=true"
    )


if __name__ == "__main__":
    main()
