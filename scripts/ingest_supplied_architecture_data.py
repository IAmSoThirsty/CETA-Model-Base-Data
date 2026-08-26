from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "ceta_architecture_material_v1"
HUMAN_ROOT = "CETA_AGI_Human_Relations_Training_Material_v1.0.0"
DEFENSIVE_ROOT = "AI_Defensive_Knowledge_Eval_Stack_FULL"
SHA256_RE = re.compile(r"(?i)\b[0-9a-f]{64}\b")
STRUCTURED_DERIVATION_ELIGIBLE = "STRUCTURED_DERIVATION_ELIGIBLE"
PROVENANCE_OR_CONSTRAINT_ONLY = "PROVENANCE_OR_CONSTRAINT_ONLY"
CONTROLLED_EVALUATION = "CONTROLLED_EVALUATION"

HUMAN_FILES = {
    "mission/MISSION_PARAGRAPH.txt": "01_MISSION/MISSION_PARAGRAPH.txt",
    "mission/DEPLOYMENT_BOUNDARY.json": "01_MISSION/DEPLOYMENT_BOUNDARY.json",
    "training/public_scenarios.jsonl": "02_SCENARIOS/all_20_public_scenarios.jsonl",
    "training/unacceptable_failures.json": "03_FAILURES/five_unacceptable_failures.json",
    "governance/operation_risk_ranking.json": "04_RISK_AND_EQUIVALENCE/operation_risk_ranking.json",
    "governance/semantic_equivalence_by_operation.json": "04_RISK_AND_EQUIVALENCE/semantic_equivalence_by_operation.json",
    "training/section_awareness_406.jsonl": "05_CODEX_SECTION_AWARENESS/section_awareness_406.jsonl",
    "training/section_situational_templates_1624.jsonl": "05_CODEX_SECTION_AWARENESS/four_situational_templates_1624.jsonl",
    "training/role_contracts_21.json": "06_ROLE_AWARENESS/role_contracts_21.json",
    "training/role_conditioned_cases_84.jsonl": "06_ROLE_AWARENESS/role_conditioned_cases_84.jsonl",
    "maps/high_value_stewardship_section_map.csv": "05_CODEX_SECTION_AWARENESS/high_value_stewardship_section_map.csv",
    "maps/section_dependency_edges.csv": "05_CODEX_SECTION_AWARENESS/section_dependency_edges.csv",
    "maps/section_role_matrix.csv": "06_ROLE_AWARENESS/section_role_matrix.csv",
}

DEFENSIVE_FILES = {
    "evaluation/jbb_benign_behaviors.csv": "02_labeled_datasets/JBB_Behaviors/benign-behaviors.csv",
    "evaluation/jbb_harmful_behaviors.csv": "02_labeled_datasets/JBB_Behaviors/harmful-behaviors.csv",
    "evaluation/owasp_dsgai_risk_taxonomy.json": "01_threat_catalogs/OWASP_GenAI_Data_Security/DSGAI_2026_RISK_TAXONOMY.json",
    "evaluation/aegis_safety_taxonomy.json": "02_labeled_datasets/NVIDIA_Aegis_2/SAFETY_TAXONOMY.json",
    "evaluation/beavertails_harm_categories.json": "02_labeled_datasets/BeaverTails/HARM_CATEGORIES.json",
    "evaluation/mitre_atlas_release_index.json": "01_threat_catalogs/MITRE_ATLAS/ATLAS_2026.07_RELEASE_INDEX.json",
    "evaluation/purplellama_autopatch_samples.json": "03_probes_and_frameworks/PurpleLlama_CyberSecEval/autopatch_samples.json",
    "provenance/defensive_sources.csv": "manifests/SOURCES.csv",
    "provenance/defensive_license_matrix.csv": "manifests/LICENSE_MATRIX.csv",
    "provenance/defensive_retrieval_status.json": "manifests/RETRIEVAL_STATUS.json",
    "provenance/defensive_remote_artifacts.csv": "manifests/REMOTE_ARTIFACTS.csv",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_sha256(sidecar: Path) -> str:
    match = SHA256_RE.search(sidecar.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"SHA-256 sidecar contains no digest: {sidecar}")
    return match.group(0).lower()


def verify_outer_digest(archive: Path, sidecar: Path) -> str:
    expected = expected_sha256(sidecar)
    actual = sha256_file(archive)
    if actual != expected:
        raise ValueError(f"archive SHA-256 mismatch for {archive.name}: expected {expected}, got {actual}")
    return actual


def safe_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    result: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe archive member path: {info.filename}")
        if not info.is_dir():
            result[path.as_posix()] = info
    return result


def read_member(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], path: str) -> bytes:
    try:
        info = members[path]
    except KeyError as exc:
        raise ValueError(f"required archive member missing: {path}") from exc
    return archive.read(info)


def read_json(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], path: str):
    return json.loads(read_member(archive, members, path).decode("utf-8"))


def read_jsonl(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], path: str) -> list[dict]:
    text = read_member(archive, members, path).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def verify_human_package(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo]) -> dict:
    prefix = HUMAN_ROOT + "/"
    package_manifest = read_json(archive, members, prefix + "PACKAGE_MANIFEST.json")
    for item in package_manifest["files"]:
        member_path = prefix + str(item["path"])
        payload = read_member(archive, members, member_path)
        if len(payload) != int(item["size_bytes"]):
            raise ValueError(f"human-material size mismatch: {item['path']}")
        if sha256_bytes(payload) != str(item["sha256"]):
            raise ValueError(f"human-material hash mismatch: {item['path']}")

    validation = read_json(archive, members, prefix + "VALIDATION_REPORT.json")
    if validation.get("all_pass") is not True:
        raise ValueError("supplied human-material validation report is not PASS")

    sections = read_jsonl(archive, members, prefix + "05_CODEX_SECTION_AWARENESS/section_awareness_406.jsonl")
    templates = read_jsonl(archive, members, prefix + "05_CODEX_SECTION_AWARENESS/four_situational_templates_1624.jsonl")
    roles = read_json(archive, members, prefix + "06_ROLE_AWARENESS/role_contracts_21.json")
    role_cases = read_jsonl(archive, members, prefix + "06_ROLE_AWARENESS/role_conditioned_cases_84.jsonl")
    public_cases = read_jsonl(archive, members, prefix + "02_SCENARIOS/all_20_public_scenarios.jsonl")
    failures = read_json(archive, members, prefix + "03_FAILURES/five_unacceptable_failures.json")
    risk = read_json(archive, members, prefix + "04_RISK_AND_EQUIVALENCE/operation_risk_ranking.json")
    equivalence = read_json(archive, members, prefix + "04_RISK_AND_EQUIVALENCE/semantic_equivalence_by_operation.json")

    counts = {
        "codex_sections": len(sections),
        "section_situational_templates": len(templates),
        "roles": len(roles),
        "role_conditioned_cases": len(role_cases),
        "public_scenarios": len(public_cases),
        "unacceptable_failure_examples": len(failures),
        "ceta_operations_ranked": len(risk),
    }
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
        raise ValueError(f"human-material counts mismatch: {counts}")

    section_ids = {str(item["section_id"]) for item in sections}
    if len(section_ids) != 406:
        raise ValueError("section IDs are not unique")
    template_ids = {str(item["template_id"]) for item in templates}
    if len(template_ids) != 1624:
        raise ValueError("situational template IDs are not unique")
    template_types = {"APPLIES", "DOES_NOT_APPLY", "ROLE_OWNERSHIP_CHALLENGE", "EVIDENCE_TO_TRANSITION"}
    per_section: dict[str, set[str]] = {}
    for item in templates:
        section_id = str(item.get("section_id") or item.get("provenance", {}).get("section_id", ""))
        if not section_id:
            raise ValueError(f"situational template has no section binding: {item.get('template_id')}")
        per_section.setdefault(section_id, set()).add(str(item["template_type"]))
    if set(per_section) != section_ids or any(types != template_types for types in per_section.values()):
        raise ValueError("each section must have exactly the four required situational template types")

    canonical_ops = set(json.loads((ROOT / "registry/ceta_operations.json").read_text(encoding="utf-8"))["operations"])
    risk_ops = {str(item["Operation"]) for item in risk}
    if risk_ops != canonical_ops or set(equivalence) != canonical_ops:
        raise ValueError("risk/equivalence operations do not match the canonical 23 CETA operations")

    holdout_manifest = read_json(archive, members, prefix + "07_PRIVATE_HOLDOUT/DO_NOT_TRAIN_MANIFEST.json")
    challenge_path = prefix + "07_PRIVATE_HOLDOUT/PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl"
    answer_path = prefix + "07_PRIVATE_HOLDOUT/ANSWER_KEY_SEPARATE.jsonl"
    challenge_payload = read_member(archive, members, challenge_path)
    answer_payload = read_member(archive, members, answer_path)
    if sha256_bytes(challenge_payload) != holdout_manifest["challenge_sha256"]:
        raise ValueError("private challenge hash mismatch")
    if sha256_bytes(answer_payload) != holdout_manifest["answer_key_sha256"]:
        raise ValueError("private answer-key hash mismatch")
    challenge_count = sum(1 for line in challenge_payload.splitlines() if line.strip())
    answer_count = sum(1 for line in answer_payload.splitlines() if line.strip())
    if challenge_count != 60 or answer_count != 60:
        raise ValueError("private holdout must contain 60 questions and 60 answers")

    return {
        "counts": counts,
        "controlled_evaluation": {
            "challenge_sha256": str(holdout_manifest["challenge_sha256"]),
            "answer_key_sha256": str(holdout_manifest["answer_key_sha256"]),
            "case_count": 60,
            "answer_count": 60,
            "archive_declared_status": str(holdout_manifest.get("status", "")),
            "known_exposed_case_ids": ["H001"],
            "clean_unseen_case_count": 59,
        },
        "package_manifest_sha256": sha256_bytes(read_member(archive, members, prefix + "PACKAGE_MANIFEST.json")),
    }


def verify_defensive_package(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo]) -> dict:
    prefix = DEFENSIVE_ROOT + "/"
    coverage = read_json(archive, members, prefix + "manifests/COVERAGE.json")
    retrieval = read_json(archive, members, prefix + "manifests/RETRIEVAL_STATUS.json")
    if int(coverage.get("requested_source_count", -1)) != 20 or int(coverage.get("represented_source_count", -1)) != 20:
        raise ValueError("defensive source coverage is not 20/20")

    hash_lines = read_member(archive, members, prefix + "manifests/FILE_HASHES.sha256").decode("utf-8").splitlines()
    verified_hashes = 0
    for line in hash_lines:
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        relative = relative.lstrip("* ").replace("\\", "/")
        while relative.startswith("./"):
            relative = relative[2:]
        payload = read_member(archive, members, prefix + relative)
        if sha256_bytes(payload) != digest.lower():
            raise ValueError(f"defensive stack hash mismatch: {relative}")
        verified_hashes += 1

    for relative in (
        "02_labeled_datasets/JBB_Behaviors/benign-behaviors.csv",
        "02_labeled_datasets/JBB_Behaviors/harmful-behaviors.csv",
    ):
        text = read_member(archive, members, prefix + relative).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) != 100:
            raise ValueError(f"expected 100 JBB behavior records in {relative}, got {len(rows)}")

    return {
        "requested_sources": int(coverage["requested_source_count"]),
        "represented_sources": int(coverage["represented_source_count"]),
        "locally_hashed_files": verified_hashes,
        "embedded_full_payloads": len(retrieval.get("embedded_full_payloads", [])),
        "not_embedded_due_transfer_boundary": len(retrieval.get("not_embedded_due_transfer_boundary", [])),
    }


def copy_selected(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    *,
    archive_root: str,
    selected: dict[str, str],
    output: Path,
) -> None:
    for destination, source in sorted(selected.items()):
        payload = read_member(archive, members, f"{archive_root}/{source}")
        target = output / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() in {".csv", ".json", ".jsonl", ".md", ".txt"}:
            text = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            payload = text.encode("utf-8")
        target.write_bytes(payload)


def material_source_usage(relative_path: str) -> str:
    """Return the deterministic use boundary for a materialized public source."""
    top_level = PurePosixPath(relative_path).parts[0]
    if top_level in {"training", "evaluation", "governance"}:
        return STRUCTURED_DERIVATION_ELIGIBLE
    if top_level in {"maps", "mission", "provenance"}:
        return PROVENANCE_OR_CONSTRAINT_ONLY
    raise ValueError(f"material path has no source-usage classification: {relative_path}")


def materialize_controlled_evaluation(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    output: Path,
    binding: dict,
) -> None:
    """Stage the supplied challenge and answer key for the evaluator, not Git."""
    selected = {
        "challenges.jsonl": "07_PRIVATE_HOLDOUT/PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl",
        "answer_key.jsonl": "07_PRIVATE_HOLDOUT/ANSWER_KEY_SEPARATE.jsonl",
    }
    copy_selected(
        archive,
        members,
        archive_root=HUMAN_ROOT,
        selected=selected,
        output=output,
    )
    challenge = output / "challenges.jsonl"
    answers = output / "answer_key.jsonl"
    if sha256_file(challenge) != binding["challenge_sha256"]:
        raise ValueError("materialized controlled-evaluation challenge hash mismatch")
    if sha256_file(answers) != binding["answer_key_sha256"]:
        raise ValueError("materialized controlled-evaluation answer-key hash mismatch")
    receipt = {
        "schema_version": 1,
        "evaluation_id": "CETA_CONTROLLED_EVALUATION/v1",
        "usage_class": CONTROLLED_EVALUATION,
        "challenge_path": challenge.name,
        "challenge_sha256": binding["challenge_sha256"],
        "answer_key_path": answers.name,
        "answer_key_sha256": binding["answer_key_sha256"],
        "case_count": binding["case_count"],
        "answer_count": binding["answer_count"],
        "known_exposed_case_ids": list(binding["known_exposed_case_ids"]),
        "clean_unseen_case_count": binding["clean_unseen_case_count"],
        "optimizer_input": False,
        "git_delivery": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def validate_controlled_evaluation_output(path: Path, public_output: Path) -> Path:
    resolved = path.resolve()
    public_resolved = public_output.resolve()
    repo_root = ROOT.resolve()
    repo_staging = (ROOT / "data" / "ceta_controlled_evaluation").resolve()
    if (
        resolved == public_resolved
        or resolved.is_relative_to(public_resolved)
        or public_resolved.is_relative_to(resolved)
    ):
        raise ValueError("controlled-evaluation output must not overlap the public material output")
    if resolved.is_relative_to(repo_root) and resolved != repo_staging:
        raise ValueError(
            "controlled-evaluation output inside the repository must be exactly "
            f"{repo_staging}"
        )
    return resolved


def output_manifest(output: Path, *, human_sha: str, defensive_sha: str, human: dict, defensive: dict) -> dict:
    files = []
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "manifest.json"):
        relative = path.relative_to(output).as_posix()
        files.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "source_usage": material_source_usage(relative),
        })
    source_usage_by_path = {item["path"]: item["source_usage"] for item in files}
    source_usage_counts = {
        usage: sum(value == usage for value in source_usage_by_path.values())
        for usage in (STRUCTURED_DERIVATION_ELIGIBLE, PROVENANCE_OR_CONSTRAINT_ONLY)
    }
    return {
        "schema_version": 3,
        "dataset_id": "CETA_ARCHITECTURE_MATERIAL/v1",
        "source_archives": {
            "human_relations_training_material": {
                "filename": "CETA_AGI_Human_Relations_Training_Material_v1.0.0.zip",
                "sha256": human_sha,
                "package_manifest_sha256": human["package_manifest_sha256"],
            },
            "defensive_knowledge_eval_stack": {
                "filename": "AI_Defensive_Knowledge_Eval_Stack_FULL.zip",
                "sha256": defensive_sha,
            },
        },
        "counts": human["counts"],
        "defensive_coverage": defensive,
        "controlled_evaluation": {
            **human["controlled_evaluation"],
            "usage_class": CONTROLLED_EVALUATION,
            "materialized_in_repository": False,
            "bound_to_architecture": True,
            "staging_path": "data/ceta_controlled_evaluation (gitignored)",
            "note": "The challenge and answer records are integrated through a hash-verified evaluator staging path; they are not optimizer inputs or public Git payloads.",
        },
        "training_boundary": {
            "current_ceta_curriculum_automatically_modified": True,
            "reason": "Public source records contribute deterministic source-derived topology and provenance assignments; only structured state-to-transition cases are optimizer inputs.",
            "source_usage_policy_version": 2,
            "source_usage_by_path": source_usage_by_path,
            "source_usage_counts": source_usage_counts,
            "optimizer_requires_derived_structured_cases": True,
            "allowed_now": [
                "deterministic structured curriculum derivation from eligible public human-relations records",
                "deterministic structured curriculum derivation from eligible public defensive records",
                "risk and semantic-equivalence policy binding",
                "controlled evaluation through the independent evaluator staging path",
            ],
            "optimizer_exclusions": [
                "passing raw prose or source-content files directly to the optimizer",
                "passing controlled evaluation questions or answer keys to the optimizer",
                "passing evaluator outputs back into threshold tuning after freeze",
                "treating source prose as an executable authority grant",
            ],
        },
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-material-zip", type=Path, required=True)
    parser.add_argument("--human-material-sha256", type=Path, required=True)
    parser.add_argument("--defensive-stack-zip", type=Path, required=True)
    parser.add_argument("--defensive-stack-sha256", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--controlled-evaluation-output",
        type=Path,
        help="Optional gitignored/runtime path for hash-verified evaluator challenge and answer files.",
    )
    args = parser.parse_args()

    human_sha = verify_outer_digest(args.human_material_zip, args.human_material_sha256)
    defensive_sha = verify_outer_digest(args.defensive_stack_zip, args.defensive_stack_sha256)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    controlled_output = None
    if args.controlled_evaluation_output is not None:
        controlled_output = validate_controlled_evaluation_output(
            args.controlled_evaluation_output,
            output,
        )

    with zipfile.ZipFile(args.human_material_zip) as human_archive:
        human_members = safe_members(human_archive)
        human = verify_human_package(human_archive, human_members)
        copy_selected(
            human_archive,
            human_members,
            archive_root=HUMAN_ROOT,
            selected=HUMAN_FILES,
            output=output,
        )
        if controlled_output is not None:
            materialize_controlled_evaluation(
                human_archive,
                human_members,
                controlled_output,
                human["controlled_evaluation"],
            )

    with zipfile.ZipFile(args.defensive_stack_zip) as defensive_archive:
        defensive_members = safe_members(defensive_archive)
        defensive = verify_defensive_package(defensive_archive, defensive_members)
        copy_selected(
            defensive_archive,
            defensive_members,
            archive_root=DEFENSIVE_ROOT,
            selected=DEFENSIVE_FILES,
            output=output,
        )

    manifest = output_manifest(
        output,
        human_sha=human_sha,
        defensive_sha=defensive_sha,
        human=human,
        defensive=defensive,
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("CETA SUPPLIED ARCHITECTURE DATA INGEST: PASS")
    print(f"output={output}")
    print(f"files={len(manifest['files'])} public_scenarios={manifest['counts']['public_scenarios']}")
    print(f"sections={manifest['counts']['codex_sections']} templates={manifest['counts']['section_situational_templates']}")
    print(f"controlled_evaluation_bound={manifest['controlled_evaluation']['bound_to_architecture']}")
    if controlled_output is not None:
        print(f"controlled_evaluation_output={controlled_output}")


if __name__ == "__main__":
    main()
