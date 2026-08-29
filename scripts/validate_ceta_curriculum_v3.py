from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ceta import ConstitutionalVM, VmDisposition
from history import EpistemicObject, ProjectionSnapshot, StateDelta, Supersession, domain_hash
from training import (
    CETA_CURRICULUM_V3_GENERATOR_ID,
    CetaWorldCurriculum,
    CetaWorldCurriculumV3,
    PublicSourceCatalog,
    SourceFamilyAssignment,
    TransitionTrainingCase,
    WorldCurriculumArtifactWriter,
    build_source_family_assignments,
    structural_world_fingerprint,
    write_source_sidecars,
)
from transition_policy.actions import CetaActionSpaceGenerator
from transition_policy.encoder import WorldView


FORBIDDEN_LANGUAGE_KEYS = frozenset({
    "prompt", "response", "answer", "completion", "expected_output", "expected_text",
    "assistant_message", "user_message", "correct_outcome", "why", "scenario",
})
SPLITS_FILENAME = "splits.json"
REQUIRED_FAILURE_SURFACES = frozenset({
    "replay_fault", "provenance_corruption", "missing_defeaters", "improper_scope",
    "illegal_authorization", "authority_failure", "belief_corruption", "objective_substitution_failure",
    "invariant_violation", "structural_output_failure",
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_from_record(record: Mapping[str, Any]) -> ProjectionSnapshot:
    state = record["state"]
    objects = tuple(EpistemicObject.from_dict(item) for item in state["active_objects"])
    supersessions = tuple(Supersession(**item) for item in state["supersessions"])
    payload = {
        "active_objects": [
            {"object_id": obj.object_id, "object_type": obj.object_type, "object_hash": obj.object_hash}
            for obj in sorted(objects, key=lambda item: item.object_id)
        ],
        "supersessions": [
            item.to_dict() for item in sorted(supersessions, key=lambda item: (item.old_object_id, item.new_object_id))
        ],
    }
    expected = domain_hash(payload, domain="CETA/STATE_PROJECTION/v1")
    if expected != state["state_ref"]:
        raise ValueError("training state_ref does not match deterministic projection")
    return ProjectionSnapshot(expected, objects, supersessions)


def preview_snapshot(snapshot: ProjectionSnapshot, delta: StateDelta) -> str:
    active = {obj.object_id: obj for obj in snapshot.active_objects}
    created = {obj.object_id: obj for obj in delta.creates}
    if len(created) != len(delta.creates) or set(created) & set(active):
        raise ValueError("target delta reuses or duplicates object identity")
    for edge in delta.supersedes:
        if edge.old_object_id not in active or edge.new_object_id not in created:
            raise ValueError("target delta has an invalid supersession")
    active.update(created)
    for edge in delta.supersedes:
        active.pop(edge.old_object_id, None)
    supersessions = tuple(snapshot.supersessions) + tuple(delta.supersedes)
    payload = {
        "active_objects": [
            {"object_id": obj.object_id, "object_type": obj.object_type, "object_hash": obj.object_hash}
            for obj in sorted(active.values(), key=lambda item: item.object_id)
        ],
        "supersessions": [
            item.to_dict() for item in sorted(supersessions, key=lambda item: (item.old_object_id, item.new_object_id))
        ],
    }
    return domain_hash(payload, domain="CETA/STATE_PROJECTION/v1")


def scan_forbidden_keys(value: Any, path: str = "record") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_LANGUAGE_KEYS:
                errors.append(f"{path}.{key}")
            errors.extend(scan_forbidden_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(scan_forbidden_keys(child, f"{path}[{index}]"))
    return errors


def proposal_key(proposal) -> str:
    return json.dumps(
        {"operation": proposal.operation, "operands": dict(proposal.operands)},
        sort_keys=True,
        separators=(",", ":"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "data/ceta_curriculum_v3")
    parser.add_argument("--material-root", type=Path, default=ROOT / "data/ceta_architecture_material_v1")
    args = parser.parse_args()
    base = args.root.resolve()
    material_root = args.material_root.resolve()
    errors: list[str] = []

    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    splits = json.loads((base / SPLITS_FILENAME).read_text(encoding="utf-8"))
    catalog = PublicSourceCatalog.load(material_root)
    expected_assignments = build_source_family_assignments(catalog, material_root, families_per_operation=20)
    expected_catalog_text = json.dumps(catalog.to_record(), indent=2, sort_keys=True) + "\n"
    expected_assignment_text = "".join(
        json.dumps(item.to_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for item in sorted(expected_assignments, key=lambda item: (item.operation, item.family_id))
    )
    catalog_path = base / "source_catalog.json"
    assignment_path = base / "source_assignments.jsonl"
    if catalog_path.read_text(encoding="utf-8") != expected_catalog_text:
        errors.append("source_catalog.json is not the deterministic material-bound catalog")
    if assignment_path.read_text(encoding="utf-8") != expected_assignment_text:
        errors.append("source_assignments.jsonl is not the deterministic provenance assignment set")

    assignments: dict[str, SourceFamilyAssignment] = {}
    for line in assignment_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = SourceFamilyAssignment.from_record(json.loads(line))
        if item.family_id in assignments:
            errors.append(f"duplicate source-family assignment: {item.family_id}")
        assignments[item.family_id] = item
    expected_source_ids = {record.source_record_id for record in catalog.records}
    assigned_source_ids = [source_id for item in assignments.values() for source_id in item.source_record_ids]
    if len(assigned_source_ids) != len(set(assigned_source_ids)) or set(assigned_source_ids) != expected_source_ids:
        errors.append("public source records are not bound exactly once across v3 families")
    record_by_id = {record.source_record_id: record for record in catalog.records}
    lineage_family: dict[str, str] = {}
    for item in assignments.values():
        for source_id in item.source_record_ids:
            lineage_id = record_by_id[source_id].lineage_id
            owner = lineage_family.setdefault(lineage_id, item.family_id)
            if owner != item.family_id:
                errors.append(f"source lineage crosses families: {lineage_id}")

    expected_family_count = len(expected_assignments)
    expected_case_count = expected_family_count * 3
    expected_negative_count = expected_case_count * 4
    if manifest.get("generator_id") != CETA_CURRICULUM_V3_GENERATOR_ID:
        errors.append("generator_id mismatch")
    if manifest.get("operation_count") != len(CetaWorldCurriculum.OPERATIONS):
        errors.append("operation_count mismatch")
    if manifest.get("world_family_count") != expected_family_count:
        errors.append("world_family_count mismatch")
    if manifest.get("case_count") != expected_case_count:
        errors.append("case_count mismatch")
    if manifest.get("illegal_alternative_count") != expected_negative_count:
        errors.append("illegal_alternative_count mismatch")
    if manifest.get("splits_sha256") != sha256(base / SPLITS_FILENAME):
        errors.append(f"{SPLITS_FILENAME} hash mismatch")
    bound = manifest.get("bound_artifacts", {})
    required_bound = {
        "source_catalog": catalog_path,
        "source_assignments": assignment_path,
    }
    if set(bound) != set(required_bound):
        errors.append("bound artifact set mismatch")
    else:
        for artifact_id, path in required_bound.items():
            info = bound[artifact_id]
            if info.get("path") != path.name or info.get("sha256") != sha256(path) or info.get("size_bytes") != path.stat().st_size:
                errors.append(f"bound artifact mismatch: {artifact_id}")
    source_binding = manifest.get("source_binding", {})
    if source_binding.get("source_record_count") != len(catalog.records):
        errors.append("source record coverage mismatch")
    if source_binding.get("source_lineage_count") != len(lineage_family):
        errors.append("source lineage coverage mismatch")
    if source_binding.get("source_family_count") != expected_family_count:
        errors.append("source family coverage mismatch")
    if source_binding.get("source_group_split_isolation") is not True:
        errors.append("source-group split isolation claim is missing")
    if source_binding.get("source_lineage_split_isolation") is not True:
        errors.append("source-lineage split isolation claim is missing")
    if source_binding.get("source_to_operation_semantic_adjudication") is not False:
        errors.append("source assignment is incorrectly claimed as semantic adjudication")
    if source_binding.get("source_assignment_method") != "DETERMINISTIC_HASH_PARTITION":
        errors.append("source assignment method is missing or unexpected")
    if source_binding.get("public_defensive_records_trained_on") is not True:
        errors.append("public defensive material is not explicitly classified as trained-on")
    if source_binding.get("public_defensive_records_unseen_benchmark_eligible") is not False:
        errors.append("trained-on defensive records remain incorrectly marked unseen-benchmark eligible")
    if source_binding.get("controlled_evaluation_bound") is not True:
        errors.append("controlled evaluation is not bound")
    if source_binding.get("controlled_evaluation_materialized_in_public_repo") is not False:
        errors.append("controlled evaluation public-repository boundary mismatch")
    if source_binding.get("controlled_evaluation_case_count") != 60:
        errors.append("controlled evaluation case count mismatch")
    if source_binding.get("known_exposed_evaluation_case_ids") != ["H001"]:
        errors.append("known exposed evaluation case is not recorded")
    if source_binding.get("clean_unseen_evaluation_case_count") != 59:
        errors.append("clean unseen evaluation count mismatch")
    if source_binding.get("raw_prose_in_optimizer_records") is not False:
        errors.append("raw prose boundary mismatch")

    all_cases: dict[str, TransitionTrainingCase] = {}
    split_of_family: dict[str, str] = {}
    family_fingerprints: dict[str, set[str]] = defaultdict(set)
    fingerprint_family: dict[str, str] = {}
    family_state_refs: dict[str, set[str]] = defaultdict(set)
    family_source_groups: dict[str, set[str]] = defaultdict(set)
    source_group_split: dict[str, str] = {}
    failure_tags: set[str] = set()
    operation_split_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    vm = ConstitutionalVM()

    for split in ("train", "validation", "heldout"):
        info = manifest.get("files", {}).get(split, {})
        path = base / str(info.get("path", ""))
        if not path.is_file() or sha256(path) != info.get("sha256"):
            errors.append(f"{split} file hash mismatch")
            continue
        text = path.read_text(encoding="utf-8")
        if "PRIVATE_CHALLENGE_60_NO_ANSWERS" in text or "ANSWER_KEY_SEPARATE" in text:
            errors.append(f"{split} contains private evaluation material")
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        if len(records) != info.get("count"):
            errors.append(f"{split} count mismatch")
        for raw in records:
            bad_keys = scan_forbidden_keys(raw)
            if bad_keys:
                errors.append(f"{raw.get('case_id')} language-target keys: {bad_keys}")
            try:
                case = TransitionTrainingCase.from_record(raw)
                snapshot = snapshot_from_record(raw)
            except Exception as exc:
                errors.append(f"{raw.get('case_id')} record/state invalid: {exc}")
                continue
            if case.case_id in all_cases:
                errors.append(f"duplicate case_id: {case.case_id}")
            all_cases[case.case_id] = case
            assignment = assignments.get(case.world_family_id)
            if assignment is None:
                errors.append(f"{case.case_id} has no source-family assignment")
                continue
            if case.target_proposal.operation != assignment.operation:
                errors.append(f"{case.case_id} target/assignment operation mismatch")
            if "curriculum_binding" in raw.get("proposal_context", {}):
                errors.append(f"{case.case_id} exposes provenance binding in model proposal context")
            forbidden_projection_keys = {"operation_policy_hash", "risk_level", "accuracy_bucket"}
            for obj in raw.get("state", {}).get("active_objects", []):
                overlap = forbidden_projection_keys.intersection(obj.get("content", {}))
                if overlap:
                    errors.append(f"{case.case_id} exposes target-policy fields in WorldView: {sorted(overlap)}")
            family_source_groups[case.world_family_id].add(assignment.source_group_id)
            previous_split = split_of_family.setdefault(case.world_family_id, split)
            if previous_split != split:
                errors.append(f"world-family leakage: {case.world_family_id}")
            group_split = source_group_split.setdefault(assignment.source_group_id, split)
            if group_split != split:
                errors.append(f"source-group leakage: {assignment.source_group_id}")
            family_fingerprints[case.world_family_id].add(case.structural_fingerprint)
            family_state_refs[case.world_family_id].add(case.state_ref)
            owner = fingerprint_family.setdefault(case.structural_fingerprint, case.world_family_id)
            if owner != case.world_family_id:
                errors.append(f"structural fingerprint crosses families: {owner}/{case.world_family_id}")
            recomputed = structural_world_fingerprint(
                state=raw["state"],
                evidence_view=raw["evidence_view"],
                identity_view=raw["identity_view"],
                authority_view=raw["authority_view"],
                proposal_context=raw["proposal_context"],
                target_transition=raw["target_transition"],
                required_defeater_count=len(raw["required_defeater_refs"]),
            )
            if recomputed != case.structural_fingerprint:
                errors.append(f"{case.case_id} structural fingerprint mismatch")
            world = WorldView(
                snapshot=snapshot,
                evidence_view=raw["evidence_view"],
                identity_view=raw["identity_view"],
                authority_view=raw["authority_view"],
                proposal_context=raw["proposal_context"],
                now_epoch_ms=raw["now_epoch_ms"],
            )
            action_space = CetaActionSpaceGenerator().generate(world)
            anchor_ids = {
                obj.object_id for obj in snapshot.active_objects if obj.object_id.startswith("UNIVERSE-V3-")
            }
            for proposal in action_space:
                operand_text = json.dumps(dict(proposal.operands), sort_keys=True)
                if any(anchor_id in operand_text for anchor_id in anchor_ids):
                    errors.append(f"{case.case_id} source anchor entered target-blind action space")
            target = case.target_proposal
            if proposal_key(target) not in {proposal_key(item) for item in action_space}:
                errors.append(f"{case.case_id} target is not recoverable from target-blind action space")
            legal_generated = []
            for generated in action_space:
                generated_decision = vm.evaluate(
                    generated,
                    projected_snapshot=snapshot,
                    admitted_evidence_view=raw["evidence_view"],
                    identity_view=raw["identity_view"],
                    authority_snapshot=raw["authority_view"],
                    now_epoch_ms=raw["now_epoch_ms"],
                    constitutional_epoch="curriculum-v3-action-space-audit",
                )
                if generated_decision.disposition is VmDisposition.LEGAL:
                    legal_generated.append(generated)
            if [proposal_key(item) for item in legal_generated] != [proposal_key(target)]:
                errors.append(
                    f"{case.case_id} target is not the unique VM-legal generated transition: "
                    f"{[item.operation for item in legal_generated]}"
                )
            decision = vm.evaluate(
                target,
                projected_snapshot=snapshot,
                admitted_evidence_view=raw["evidence_view"],
                identity_view=raw["identity_view"],
                authority_snapshot=raw["authority_view"],
                now_epoch_ms=raw["now_epoch_ms"],
                constitutional_epoch="curriculum-v3",
            )
            if decision.disposition is not VmDisposition.LEGAL:
                errors.append(f"{case.case_id} target not LEGAL: {decision.disposition}:{decision.reason_code}")
            else:
                try:
                    preview_snapshot(snapshot, decision.state_delta)
                except Exception as exc:
                    errors.append(f"{case.case_id} target projection replay failed: {exc}")
            for alternative in case.illegal_alternatives:
                alt_decision = vm.evaluate(
                    alternative.proposal,
                    projected_snapshot=snapshot,
                    admitted_evidence_view=raw["evidence_view"],
                    identity_view=raw["identity_view"],
                    authority_snapshot=raw["authority_view"],
                    now_epoch_ms=raw["now_epoch_ms"],
                    constitutional_epoch="curriculum-v3",
                )
                if alt_decision.disposition is VmDisposition.LEGAL:
                    errors.append(f"{case.case_id}/{alternative.alternative_id} illegal alternative became LEGAL")
                if alt_decision.disposition.value != alternative.expected_disposition or alt_decision.reason_code != alternative.expected_reason_code:
                    errors.append(f"{case.case_id}/{alternative.alternative_id} oracle mismatch")
                failure_tags.update(alternative.failure_tags)
            failure_tags.update(case.failure_surface_tags)
            operation_split_counts[target.operation][split] += 1

    expected_cases = set().union(*(set(values) for values in splits.get("case_splits", {}).values()))
    if expected_cases != set(all_cases):
        errors.append(f"{SPLITS_FILENAME} case set mismatch")
    if set(assignments) != set(split_of_family):
        errors.append("assignment/family set mismatch")
    lineage_split: dict[str, str] = {}
    for lineage_id, family_id in lineage_family.items():
        family_split = split_of_family.get(family_id)
        if family_split is None:
            errors.append(f"source lineage has no dataset split: {lineage_id}")
            continue
        previous = lineage_split.setdefault(lineage_id, family_split)
        if previous != family_split:
            errors.append(f"source lineage crosses dataset splits: {lineage_id}")
    if any(len(values) != 1 for values in family_fingerprints.values()):
        errors.append("variants within a world family do not share one structural fingerprint")
    if any(len(values) != 3 for values in family_state_refs.values()):
        errors.append("world-family variants are not three identity-distinct states")
    if any(len(values) != 1 for values in family_source_groups.values()):
        errors.append("world-family variants do not share one source group")
    missing_surfaces = REQUIRED_FAILURE_SURFACES - failure_tags
    if missing_surfaces:
        errors.append(f"missing hostile failure surfaces: {sorted(missing_surfaces)}")
    for operation in CetaWorldCurriculum.OPERATIONS:
        counts = operation_split_counts[operation]
        if counts != {"train": 48, "validation": 6, "heldout": 6}:
            errors.append(f"{operation} split counts unexpected: {dict(counts)}")

    # Regenerate the complete artifact set and compare checked-in bytes. This
    # closes the stale-data blind spot where generator code and self-consistent
    # checked-in JSONL could otherwise drift independently.
    with tempfile.TemporaryDirectory() as td:
        regenerated = Path(td) / "v3"
        generated_catalog, generated_assignments = write_source_sidecars(
            regenerated, catalog, expected_assignments
        )
        generated_cases = CetaWorldCurriculumV3(expected_assignments).build()
        source_class_counts = Counter(record.source_class for record in catalog.records)
        WorldCurriculumArtifactWriter.write(
            regenerated,
            generated_cases,
            generator_id=CETA_CURRICULUM_V3_GENERATOR_ID,
            bound_artifacts={
                "source_catalog": generated_catalog,
                "source_assignments": generated_assignments,
            },
            manifest_metadata={
                "source_binding": {
                    "source_dataset_id": catalog.source_dataset_id,
                    "source_dataset_manifest_sha256": catalog.source_dataset_manifest_sha256,
                    "source_record_count": len(catalog.records),
                    "source_lineage_count": len({record.lineage_id for record in catalog.records}),
                    "source_family_count": len(expected_assignments),
                    "source_class_counts": dict(sorted(source_class_counts.items())),
                    "source_group_split_isolation": True,
                    "source_lineage_split_isolation": True,
                    "public_defensive_records_trained_on": True,
                    "public_defensive_records_unseen_benchmark_eligible": False,
                    "controlled_evaluation_bound": True,
                    "controlled_evaluation_materialized_in_public_repo": False,
                    "controlled_evaluation_case_count": catalog.controlled_evaluation["case_count"],
                    "known_exposed_evaluation_case_ids": catalog.controlled_evaluation["known_exposed_case_ids"],
                    "clean_unseen_evaluation_case_count": catalog.controlled_evaluation["clean_unseen_case_count"],
                    "raw_prose_in_optimizer_records": False,
                    "source_to_operation_semantic_adjudication": False,
                    "source_assignment_method": "DETERMINISTIC_HASH_PARTITION",
                }
            },
        )
        for name in (
            "train.jsonl", "validation.jsonl", "heldout.jsonl", SPLITS_FILENAME,
            "manifest.json", "source_catalog.json", "source_assignments.jsonl",
        ):
            if (base / name).read_bytes() != (regenerated / name).read_bytes():
                errors.append(f"checked-in v3 artifact is stale relative to generator: {name}")

    if errors:
        print("CETA CURRICULUM V3 VALIDATION: FAIL")
        for error in errors[:100]:
            print(" -", error)
        if len(errors) > 100:
            print(f" - ... {len(errors) - 100} additional errors")
        raise SystemExit(1)
    print("CETA CURRICULUM V3 VALIDATION: PASS")
    print(
        f"cases={len(all_cases)} families={len(split_of_family)} sources={len(expected_source_ids)} "
        f"negatives={sum(len(case.illegal_alternatives) for case in all_cases.values())}"
    )
    print(
        f"train={len(splits['case_splits']['train'])} validation={len(splits['case_splits']['validation'])} "
        f"heldout={len(splits['case_splits']['heldout'])} operations={len(operation_split_counts)}"
    )


if __name__ == "__main__":
    main()
