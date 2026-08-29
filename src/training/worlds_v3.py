from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from ceta import TransitionProposal
from history import EpistemicObject, StateDelta, StateProjector, canonical_json, domain_hash

from .worlds import CetaWorldCurriculum, _AltSpec, _WorldDraft


GENERATOR_ID = "CETA_WORLD_CURRICULUM/v3"
SOURCE_CATALOG_ID = "CETA_PUBLIC_SOURCE_CATALOG/v3"
ASSIGNMENT_SCHEMA_ID = "CETA_SOURCE_FAMILY_ASSIGNMENT/v3"


@dataclass(frozen=True)
class _SourceSpec:
    source_class: str
    record_kind: str
    serialization: str
    json_object_mode: str = "single"
    license_id: str = "USER_SUPPLIED"


PUBLIC_SOURCE_SPECS: Mapping[str, _SourceSpec] = {
    "training/public_scenarios.jsonl": _SourceSpec("HUMAN_RELATIONS_PUBLIC", "public_scenario", "jsonl"),
    "training/section_situational_templates_1624.jsonl": _SourceSpec("HUMAN_RELATIONS_PUBLIC", "section_template", "jsonl"),
    "training/section_awareness_406.jsonl": _SourceSpec("HUMAN_RELATIONS_PUBLIC", "section_awareness", "jsonl"),
    "training/role_contracts_21.json": _SourceSpec("HUMAN_RELATIONS_PUBLIC", "role_contract", "json_array"),
    "training/role_conditioned_cases_84.jsonl": _SourceSpec("HUMAN_RELATIONS_PUBLIC", "role_case", "jsonl"),
    "training/unacceptable_failures.json": _SourceSpec("HUMAN_RELATIONS_PUBLIC", "unacceptable_failure", "json_array"),
    "evaluation/jbb_benign_behaviors.csv": _SourceSpec("DEFENSIVE_PUBLIC", "jbb_behavior", "csv", license_id="MIT"),
    "evaluation/jbb_harmful_behaviors.csv": _SourceSpec("DEFENSIVE_PUBLIC", "jbb_behavior", "csv", license_id="MIT"),
    "evaluation/owasp_dsgai_risk_taxonomy.json": _SourceSpec("DEFENSIVE_PUBLIC", "owasp_risk", "json_array", license_id="CC-BY-SA-4.0"),
    "evaluation/aegis_safety_taxonomy.json": _SourceSpec("DEFENSIVE_PUBLIC", "aegis_category", "json_object", json_object_mode="lists", license_id="CC-BY-4.0"),
    "evaluation/beavertails_harm_categories.json": _SourceSpec("DEFENSIVE_PUBLIC", "beavertails_category", "json_array", license_id="CC-BY-NC-4.0"),
    "evaluation/mitre_atlas_release_index.json": _SourceSpec("DEFENSIVE_PUBLIC", "mitre_release", "json_object", license_id="UPSTREAM_TERMS"),
    "evaluation/purplellama_autopatch_samples.json": _SourceSpec("DEFENSIVE_PUBLIC", "purplellama_sample", "json_array", license_id="MIT_AND_UPSTREAM_MODEL_TERMS"),
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_sha256(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _label_token(value: Any) -> str:
    return _sha256_bytes(str(value).encode("utf-8"))[:16]


def _categorical_profile(path: str, kind: str, record: Any, *, group: str | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    if kind == "section_template" and isinstance(record, Mapping):
        result["template_type"] = str(record.get("template_type", "UNKNOWN"))
    elif kind == "role_case" and isinstance(record, Mapping):
        result["case_type"] = str(record.get("case_type", "UNKNOWN"))
    elif kind == "jbb_behavior":
        result["safety_polarity"] = "BENIGN" if "benign" in path else "HARMFUL"
        if isinstance(record, Mapping):
            result["category_token"] = _label_token(record.get("Category", "UNKNOWN"))
    elif kind == "aegis_category":
        result["taxonomy_group"] = str(group or "UNKNOWN")
    elif kind in {"owasp_risk", "beavertails_category", "purplellama_sample"}:
        result["category_token"] = _label_token(record)
    elif kind == "section_awareness" and isinstance(record, Mapping):
        result["priority_token"] = _label_token(record.get("training_priority", "UNKNOWN"))
        result["status_token"] = _label_token(record.get("status", "UNKNOWN"))
    elif kind == "unacceptable_failure":
        result["failure_surface"] = "UNACCEPTABLE_FAILURE"
    return dict(sorted(result.items()))


def _lineage_id(path: str, kind: str, record: Any, source_record_id: str) -> str:
    """Return the indivisible split unit for a source and its derivatives."""
    lineage_key: str | None = None
    if kind == "section_template" and isinstance(record, Mapping):
        provenance = record.get("provenance")
        if isinstance(provenance, Mapping):
            lineage_key = str(provenance.get("source_sha256") or "") or None
        if lineage_key is None:
            lineage_key = f"section:{record.get('template_id', '')}".rsplit("-", 1)[0]
    elif kind == "section_awareness" and isinstance(record, Mapping):
        lineage_key = str(record.get("source_sha256") or f"section:{record.get('section_id', '')}")
    elif kind == "role_contract" and isinstance(record, Mapping):
        lineage_key = f"role:{record.get('role_id', '')}"
    elif kind == "role_case" and isinstance(record, Mapping):
        provenance = record.get("provenance")
        if isinstance(provenance, Mapping):
            role_id = str(provenance.get("role_id") or "")
            source_sha = str(provenance.get("source_sha256") or "")
            lineage_key = f"role:{role_id}" if role_id else source_sha or None
        if lineage_key is None:
            lineage_key = f"role:{record.get('case_id', '')}".rsplit("-", 1)[0]
    if not lineage_key:
        lineage_key = f"record:{source_record_id}"
    return domain_hash(
        {"path_class": "HUMAN_DERIVATIVE" if kind.startswith(("section_", "role_")) else path,
         "lineage_key": lineage_key},
        domain="CETA/SOURCE_LINEAGE/v3",
    )


@dataclass(frozen=True)
class PublicSourceRecord:
    source_record_id: str
    path: str
    locator: str
    artifact_sha256: str
    record_sha256: str
    lineage_id: str
    source_class: str
    record_kind: str
    usage_class: str
    license_id: str
    categorical_profile: Mapping[str, str]

    def to_record(self) -> dict[str, Any]:
        return {
            "source_record_id": self.source_record_id,
            "path": self.path,
            "locator": self.locator,
            "artifact_sha256": self.artifact_sha256,
            "record_sha256": self.record_sha256,
            "lineage_id": self.lineage_id,
            "source_class": self.source_class,
            "record_kind": self.record_kind,
            "usage_class": self.usage_class,
            "license_id": self.license_id,
            "categorical_profile": dict(sorted(self.categorical_profile.items())),
        }


@dataclass(frozen=True)
class PublicSourceCatalog:
    source_dataset_id: str
    source_dataset_manifest_sha256: str
    records: tuple[PublicSourceRecord, ...]
    source_files: tuple[Mapping[str, Any], ...]
    controlled_evaluation: Mapping[str, Any]

    @classmethod
    def load(cls, root: str | Path) -> "PublicSourceCatalog":
        base = Path(root)
        manifest_path = base / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dataset_id") != "CETA_ARCHITECTURE_MATERIAL/v1":
            raise ValueError("source material dataset_id mismatch")
        if manifest.get("schema_version") != 3:
            raise ValueError("source material manifest must use the classified v3 schema")
        controlled_evaluation = manifest.get("controlled_evaluation", {})
        if (
            controlled_evaluation.get("usage_class") != "CONTROLLED_EVALUATION"
            or controlled_evaluation.get("bound_to_architecture") is not True
            or controlled_evaluation.get("materialized_in_repository") is not False
        ):
            raise ValueError("controlled evaluation is not bound to the source dataset")
        usage_by_path = manifest.get("training_boundary", {}).get("source_usage_by_path")
        if not isinstance(usage_by_path, Mapping):
            raise ValueError("source material manifest has no source_usage_by_path classification")
        manifest_files = {str(item["path"]): item for item in manifest.get("files", [])}

        records: list[PublicSourceRecord] = []
        source_files: list[Mapping[str, Any]] = []
        for relative, spec in sorted(PUBLIC_SOURCE_SPECS.items()):
            info = manifest_files.get(relative)
            if not isinstance(info, Mapping):
                raise ValueError(f"public source file is not manifest-bound: {relative}")
            path = base / relative
            actual = _sha256_file(path)
            if actual != info.get("sha256"):
                raise ValueError(f"public source file hash mismatch: {relative}")
            usage = str(usage_by_path.get(relative, ""))
            if usage != "STRUCTURED_DERIVATION_ELIGIBLE":
                raise ValueError(f"public source is not structured-derivation eligible: {relative} -> {usage}")
            if info.get("source_usage") != usage:
                raise ValueError(f"public source file classification disagrees with the training boundary: {relative}")
            extracted = _read_records(path, spec)
            source_files.append({
                "path": relative,
                "artifact_sha256": actual,
                "record_count": len(extracted),
                "source_class": spec.source_class,
                "record_kind": spec.record_kind,
                "usage_class": usage,
                "license_id": spec.license_id,
            })
            for locator, value, group in extracted:
                record_sha = _record_sha256(value)
                source_id = domain_hash(
                    {"path": relative, "locator": locator, "record_sha256": record_sha},
                    domain="CETA/PUBLIC_SOURCE_RECORD/v3",
                )
                records.append(PublicSourceRecord(
                    source_record_id=source_id,
                    path=relative,
                    locator=locator,
                    artifact_sha256=actual,
                    record_sha256=record_sha,
                    lineage_id=_lineage_id(relative, spec.record_kind, value, source_id),
                    source_class=spec.source_class,
                    record_kind=spec.record_kind,
                    usage_class=usage,
                    license_id=spec.license_id,
                    categorical_profile=_categorical_profile(relative, spec.record_kind, value, group=group),
                ))

        ordered = tuple(sorted(records, key=lambda item: item.source_record_id))
        if len({item.source_record_id for item in ordered}) != len(ordered):
            raise ValueError("duplicate public source record identity")
        return cls(
            source_dataset_id=str(manifest["dataset_id"]),
            source_dataset_manifest_sha256=_sha256_file(manifest_path),
            records=ordered,
            source_files=tuple(source_files),
            controlled_evaluation={
                "usage_class": "CONTROLLED_EVALUATION",
                "bound_to_architecture": True,
                "materialized_in_repository": False,
                "challenge_sha256": str(controlled_evaluation.get("challenge_sha256", "")),
                "answer_key_sha256": str(controlled_evaluation.get("answer_key_sha256", "")),
                "case_count": int(controlled_evaluation.get("case_count", 0)),
                "known_exposed_case_ids": list(controlled_evaluation.get("known_exposed_case_ids", [])),
                "clean_unseen_case_count": int(controlled_evaluation.get("clean_unseen_case_count", 0)),
            },
        )

    def to_record(self) -> dict[str, Any]:
        class_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        for record in self.records:
            class_counts[record.source_class] = class_counts.get(record.source_class, 0) + 1
            kind_counts[record.record_kind] = kind_counts.get(record.record_kind, 0) + 1
        body = {
            "schema_version": 2,
            "catalog_id": SOURCE_CATALOG_ID,
            "source_dataset_id": self.source_dataset_id,
            "source_dataset_manifest_sha256": self.source_dataset_manifest_sha256,
            "source_file_count": len(self.source_files),
            "source_record_count": len(self.records),
            "source_lineage_count": len({record.lineage_id for record in self.records}),
            "source_class_counts": dict(sorted(class_counts.items())),
            "record_kind_counts": dict(sorted(kind_counts.items())),
            "source_files": [dict(item) for item in self.source_files],
            "records": [item.to_record() for item in self.records],
            "controlled_evaluation": dict(self.controlled_evaluation),
            "content_boundary": {
                "raw_prose_in_optimizer_records": False,
                "categorical_and_hash_metadata_only": True,
                "public_defensive_records_reused_as_unseen_benchmark": False,
            },
        }
        return {**body, "catalog_hash": domain_hash(body, domain="CETA/PUBLIC_SOURCE_CATALOG/v3")}


def _read_records(path: Path, spec: _SourceSpec) -> list[tuple[str, Any, str | None]]:
    result: list[tuple[str, Any, str | None]] = []
    if spec.serialization == "jsonl":
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                result.append((f"line:{index:06d}", json.loads(line), None))
    elif spec.serialization == "csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), 1):
                result.append((f"row:{index:06d}", dict(row), None))
    elif spec.serialization == "json_array":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"expected JSON array: {path}")
        result.extend((f"index:{index:06d}", item, None) for index, item in enumerate(value))
    elif spec.serialization == "json_object":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError(f"expected JSON object: {path}")
        if spec.json_object_mode == "lists":
            for key in sorted(value):
                items = value[key]
                if not isinstance(items, list):
                    raise ValueError(f"expected list at {path}#{key}")
                result.extend((f"key:{key}/index:{index:06d}", item, str(key)) for index, item in enumerate(items))
        else:
            result.append(("document", value, None))
    else:
        raise ValueError(f"unknown source serialization: {spec.serialization}")
    return result


@dataclass(frozen=True)
class SourceFamilyAssignment:
    assignment_id: str
    family_id: str
    operation: str
    source_group_id: str
    source_record_ids: tuple[str, ...]
    operation_policy_hash: str
    risk_record_sha256: str
    equivalence_record_sha256: str
    failure_severity: str
    required_accuracy: float
    zero_unsafe_selection: bool
    projection_profile: Mapping[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "schema_id": ASSIGNMENT_SCHEMA_ID,
            "assignment_id": self.assignment_id,
            "assignment_status": "DETERMINISTIC_PROVENANCE_ASSIGNMENT",
            "family_id": self.family_id,
            "operation": self.operation,
            "source_group_id": self.source_group_id,
            "source_record_ids": list(self.source_record_ids),
            "operation_policy_hash": self.operation_policy_hash,
            "risk_record_sha256": self.risk_record_sha256,
            "equivalence_record_sha256": self.equivalence_record_sha256,
            "failure_severity": self.failure_severity,
            "required_accuracy": self.required_accuracy,
            "zero_unsafe_selection": self.zero_unsafe_selection,
            "projection_profile": dict(self.projection_profile),
            "target_basis": "EXPLICIT_OPERATION_POLICY_AND_CONSTITUTIONAL_VM_RECIPE",
            "source_role": "STRUCTURED_CONTEXT_AND_PROVENANCE_ONLY",
            "semantic_source_to_operation_adjudication": False,
            "raw_prose_used_as_target": False,
        }

    @classmethod
    def from_record(cls, raw: Mapping[str, Any]) -> "SourceFamilyAssignment":
        if (
            raw.get("schema_id") != ASSIGNMENT_SCHEMA_ID
            or raw.get("assignment_status") != "DETERMINISTIC_PROVENANCE_ASSIGNMENT"
            or raw.get("semantic_source_to_operation_adjudication") is not False
        ):
            raise ValueError("source-family assignment is not deterministic v3 provenance material")
        return cls(
            assignment_id=str(raw["assignment_id"]),
            family_id=str(raw["family_id"]),
            operation=str(raw["operation"]),
            source_group_id=str(raw["source_group_id"]),
            source_record_ids=tuple(str(x) for x in raw["source_record_ids"]),
            operation_policy_hash=str(raw["operation_policy_hash"]),
            risk_record_sha256=str(raw["risk_record_sha256"]),
            equivalence_record_sha256=str(raw["equivalence_record_sha256"]),
            failure_severity=str(raw["failure_severity"]),
            required_accuracy=float(raw["required_accuracy"]),
            zero_unsafe_selection=bool(raw["zero_unsafe_selection"]),
            projection_profile=dict(raw["projection_profile"]),
        )


def build_source_family_assignments(
    catalog: PublicSourceCatalog,
    material_root: str | Path,
    *,
    families_per_operation: int = 20,
) -> tuple[SourceFamilyAssignment, ...]:
    if families_per_operation < 10:
        raise ValueError("v3 requires at least ten source families per operation")
    base = Path(material_root)
    risk_path = base / "governance/operation_risk_ranking.json"
    equivalence_path = base / "governance/semantic_equivalence_by_operation.json"
    source_manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    manifest_files = {str(item["path"]): item for item in source_manifest.get("files", [])}
    usage_by_path = source_manifest.get("training_boundary", {}).get("source_usage_by_path", {})
    for relative, path in (
        ("governance/operation_risk_ranking.json", risk_path),
        ("governance/semantic_equivalence_by_operation.json", equivalence_path),
    ):
        info = manifest_files.get(relative)
        if not isinstance(info, Mapping) or _sha256_file(path) != info.get("sha256"):
            raise ValueError(f"governance source is not manifest-bound: {relative}")
        if usage_by_path.get(relative) != "STRUCTURED_DERIVATION_ELIGIBLE" or info.get("source_usage") != "STRUCTURED_DERIVATION_ELIGIBLE":
            raise ValueError(f"governance source is not structured-derivation eligible: {relative}")
    risk_records = json.loads(risk_path.read_text(encoding="utf-8"))
    equivalence = json.loads(equivalence_path.read_text(encoding="utf-8"))
    risk_by_operation = {str(item["Operation"]): item for item in risk_records}
    if set(risk_by_operation) != set(CetaWorldCurriculum.OPERATIONS) or set(equivalence) != set(CetaWorldCurriculum.OPERATIONS):
        raise ValueError("operation policy coverage does not match the canonical CETA vocabulary")

    family_keys = [
        (operation, family_index)
        for operation in CetaWorldCurriculum.OPERATIONS
        for family_index in range(families_per_operation)
    ]
    by_lineage: dict[str, list[PublicSourceRecord]] = {}
    for record in catalog.records:
        by_lineage.setdefault(record.lineage_id, []).append(record)
    ordered_lineages = sorted(
        by_lineage.items(),
        key=lambda item: hashlib.sha256(("CETA/V3/SOURCE_LINEAGE_ASSIGNMENT\n" + item[0]).encode("utf-8")).digest(),
    )
    if len(ordered_lineages) < len(family_keys):
        raise ValueError(
            f"v3 needs at least one indivisible source lineage per family: {len(ordered_lineages)} < {len(family_keys)}"
        )
    bundles: list[list[PublicSourceRecord]] = [[] for _ in family_keys]
    for index, (_, lineage_records) in enumerate(ordered_lineages):
        bundles[index % len(bundles)].extend(sorted(lineage_records, key=lambda item: item.source_record_id))

    result: list[SourceFamilyAssignment] = []
    for (operation, family_index), bundle in zip(family_keys, bundles):
        if not bundle:
            raise ValueError(f"source family has no public source records: {operation}/F{family_index:02d}")
        risk = risk_by_operation[operation]
        required = str(risk.get("Required accuracy", ""))
        match = re.search(r">=\s*(\d+(?:\.\d+)?)%", required)
        if match is None:
            raise ValueError(f"operation risk row has no parseable accuracy: {operation}")
        accuracy = float(match.group(1)) / 100.0
        severity = str(risk.get("Failure severity", "")).strip().lower()
        if severity not in {"moderate", "high", "catastrophic"}:
            raise ValueError(f"unknown operation failure severity: {operation}={severity}")
        source_ids = tuple(sorted(item.source_record_id for item in bundle))
        source_group_id = domain_hash(list(source_ids), domain="CETA/SOURCE_GROUP/v3")
        risk_hash = _record_sha256(risk)
        equivalence_hash = _record_sha256(equivalence[operation])
        operation_policy_hash = domain_hash(
            {"operation": operation, "risk_record_sha256": risk_hash, "equivalence_record_sha256": equivalence_hash},
            domain="CETA/OPERATION_SOURCE_POLICY/v3",
        )
        human_count = sum(item.source_class == "HUMAN_RELATIONS_PUBLIC" for item in bundle)
        defensive_count = sum(item.source_class == "DEFENSIVE_PUBLIC" for item in bundle)
        harmful_count = sum(item.categorical_profile.get("safety_polarity") == "HARMFUL" for item in bundle)
        benign_count = sum(item.categorical_profile.get("safety_polarity") == "BENIGN" for item in bundle)
        evidence_template_count = sum(item.categorical_profile.get("template_type") == "EVIDENCE_TO_TRANSITION" for item in bundle)
        role_boundary_count = sum(
            item.record_kind in {"role_case", "role_contract"}
            or item.categorical_profile.get("template_type") == "ROLE_OWNERSHIP_CHALLENGE"
            for item in bundle
        )
        # The encoder-visible profile is derived only from source records. The
        # target operation's risk/accuracy policy remains in this sidecar and
        # must never be projected into WorldView.
        profile_body = {
            "source_count": len(bundle),
            "human_relations_count": human_count,
            "public_defensive_count": defensive_count,
            "harmful_behavior_count": harmful_count,
            "benign_behavior_count": benign_count,
            "evidence_template_count": evidence_template_count,
            "role_boundary_count": role_boundary_count,
        }
        profile = {**profile_body, "projection_profile_hash": domain_hash(profile_body, domain="CETA/SOURCE_PROJECTION_PROFILE/v3")}
        family_id = f"CETA-V3/{operation}/F{family_index:02d}"
        assignment_body = {
            "family_id": family_id,
            "operation": operation,
            "source_group_id": source_group_id,
            "source_record_ids": list(source_ids),
            "operation_policy_hash": operation_policy_hash,
            "projection_profile": profile,
        }
        result.append(SourceFamilyAssignment(
            assignment_id=domain_hash(assignment_body, domain="CETA/SOURCE_FAMILY_ASSIGNMENT/v3"),
            family_id=family_id,
            operation=operation,
            source_group_id=source_group_id,
            source_record_ids=source_ids,
            operation_policy_hash=operation_policy_hash,
            risk_record_sha256=risk_hash,
            equivalence_record_sha256=equivalence_hash,
            failure_severity=severity,
            required_accuracy=accuracy,
            zero_unsafe_selection=str(risk.get("Must unsafe selections equal zero?", "")).strip().lower() == "yes",
            projection_profile=profile,
        ))

    assigned = [source_id for item in result for source_id in item.source_record_ids]
    expected = {item.source_record_id for item in catalog.records}
    if len(assigned) != len(set(assigned)) or set(assigned) != expected:
        raise ValueError("public source records were not assigned to exactly one v3 source family")
    family_by_lineage: dict[str, str] = {}
    record_by_id = {item.source_record_id: item for item in catalog.records}
    for item in result:
        for source_id in item.source_record_ids:
            lineage_id = record_by_id[source_id].lineage_id
            owner = family_by_lineage.setdefault(lineage_id, item.family_id)
            if owner != item.family_id:
                raise ValueError(f"source lineage crosses v3 families: {lineage_id}")
    return tuple(result)


def write_source_sidecars(
    destination: str | Path,
    catalog: PublicSourceCatalog,
    assignments: Iterable[SourceFamilyAssignment],
) -> tuple[Path, Path]:
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    catalog_path = root / "source_catalog.json"
    assignments_path = root / "source_assignments.jsonl"
    catalog_path.write_text(json.dumps(catalog.to_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    ordered = sorted(assignments, key=lambda item: (item.operation, item.family_id))
    with assignments_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in ordered:
            handle.write(json.dumps(item.to_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    return catalog_path, assignments_path


class CetaWorldCurriculumV3(CetaWorldCurriculum):
    """Source-bound structured curriculum with no raw language targets.

    Exact operations come from explicit VM family recipes bound to the supplied
    operation-risk and semantic-equivalence policy. Public human-relations and
    defensive records contribute only hash-bound provenance and source-derived
    topology. The class does not infer transition labels from prose and does
    not claim human semantic source-to-operation adjudication.
    """

    CONSTITUTIONAL_EPOCH = "curriculum-v3"
    CASE_PREFIX = "CETA-V3"

    def __init__(self, assignments: Iterable[SourceFamilyAssignment], *, variants_per_family: int = 3) -> None:
        materialized = tuple(assignments)
        by_operation: dict[str, list[SourceFamilyAssignment]] = {}
        family_ids: set[str] = set()
        source_ids: set[str] = set()
        for item in materialized:
            if item.operation not in self.OPERATIONS:
                raise ValueError(f"v3 assignment names unknown operation: {item.operation}")
            if item.family_id in family_ids:
                raise ValueError(f"duplicate v3 family assignment: {item.family_id}")
            family_ids.add(item.family_id)
            if source_ids.intersection(item.source_record_ids):
                raise ValueError(f"source record appears in multiple v3 families: {item.family_id}")
            source_ids.update(item.source_record_ids)
            by_operation.setdefault(item.operation, []).append(item)
        if set(by_operation) != set(self.OPERATIONS):
            raise ValueError("v3 assignments do not cover all CETA operations")
        counts = {operation: len(items) for operation, items in by_operation.items()}
        if len(set(counts.values())) != 1 or next(iter(counts.values())) < 10:
            raise ValueError(f"v3 requires one uniform family count of at least ten per operation: {counts}")
        self._assignments = {
            operation: tuple(sorted(items, key=lambda item: item.family_id))
            for operation, items in by_operation.items()
        }
        super().__init__(families_per_operation=next(iter(counts.values())), variants_per_family=variants_per_family)

    def _draft(self, operation: str, family_index: int, variant_index: int) -> _WorldDraft:
        base = super()._draft(operation, family_index, variant_index)
        assignment = self._assignments[operation][family_index]
        if assignment.family_id != f"CETA-V3/{operation}/F{family_index:02d}":
            raise ValueError(f"v3 family ordering mismatch: {assignment.family_id}")
        if base.snapshot.supersessions:
            raise ValueError("v3 source projection cannot rehydrate a world with prior supersessions")

        projector = StateProjector()
        singleton_scope_operations = {
            "CreateBelief", "Support", "Contradict", "Undercut", "Verify",
            "Invalidate", "Suspend", "Expire", "Reevaluate", "Adjudicate",
        }
        prepared_objects: list[EpistemicObject] = []
        for obj in base.snapshot.active_objects:
            content = dict(obj.content)
            if operation in singleton_scope_operations and isinstance(content.get("scope"), Mapping):
                content["scope"] = {
                    str(key): list(values[:1]) if isinstance(values, list) else values
                    for key, values in content["scope"].items()
                }
            if obj.object_type == "CLAIM" and operation != "CreateBelief":
                content["belief_creation_allowed"] = False
            if operation in {"Support", "Contradict", "Undercut"} and obj.object_type == "EVIDENCE":
                content["relation_kind"] = operation
            prepared_objects.append(EpistemicObject.create(
                object_id=obj.object_id,
                object_type=obj.object_type,
                content=content,
            ))
        projector.apply(StateDelta(tuple(prepared_objects), ()))
        token = _sha256_bytes(f"{assignment.source_group_id}\n{variant_index}".encode("utf-8"))[:12].upper()
        profile = assignment.projection_profile
        # UNIVERSE anchors are encoder-only context. Their status must remain
        # outside every action-space trigger; SUSPENDED/INVALIDATED/EXPIRED
        # would incorrectly make them legal Reevaluate targets.
        def anchor(name: str, ordinal: int, *, status: str, count: int) -> EpistemicObject:
            return EpistemicObject.create(
                object_id=f"UNIVERSE-V3-{name}-{token}-{ordinal:02d}",
                object_type="UNIVERSE",
                content={
                    "status": status,
                    "scope": {name: [f"{name}-{i:02d}" for i in range(max(0, count))]},
                },
            )

        anchors = [
            anchor("SOURCE", 0, status="ACTIVE", count=int(profile["source_count"])),
        ]
        if int(profile["public_defensive_count"]):
            anchors.append(anchor("DEFENSIVE", 2, status="VALIDATED", count=int(profile["public_defensive_count"])))
        if int(profile["harmful_behavior_count"]):
            anchors.append(anchor("HARMFUL", 3, status="REJECTED", count=int(profile["harmful_behavior_count"])))
        if int(profile["benign_behavior_count"]):
            anchors.append(anchor("BENIGN", 4, status="ACTIVE", count=int(profile["benign_behavior_count"])))
        if int(profile["evidence_template_count"]):
            anchors.append(anchor("EVIDENCE", 5, status="ADMITTED", count=int(profile["evidence_template_count"])))
        if int(profile["role_boundary_count"]):
            anchors.append(anchor("ROLE", 6, status="AUTHORIZED", count=int(profile["role_boundary_count"])))
        projector.apply(StateDelta(tuple(anchors), ()))

        context = dict(base.proposal_context)
        state_ref = projector.state_ref
        target = TransitionProposal(state_ref, base.target.operation, base.target.operands, base.target.proposer_id)
        alternatives = []
        for item in base.alternatives:
            proposal = item.proposal
            alternative_id = item.alternative_id
            failure_tags = item.failure_tags
            if (
                operation in {"Support", "Contradict", "Undercut"}
                and item.alternative_id == "MISSING_EVIDENCE_RELATION_SOURCE"
            ):
                wrong_operation = {
                    "Support": "Contradict",
                    "Contradict": "Undercut",
                    "Undercut": "Support",
                }[operation]
                proposal = TransitionProposal(
                    proposal.input_state_ref,
                    wrong_operation,
                    base.target.operands,
                    proposal.proposer_id,
                )
                alternative_id = "EVIDENCE_RELATION_MISMATCH"
                failure_tags = ("belief_corruption",)
            rebound_ref = state_ref if proposal.input_state_ref == base.snapshot.state_ref else proposal.input_state_ref
            alternatives.append(_AltSpec(
                alternative_id,
                TransitionProposal(rebound_ref, proposal.operation, proposal.operands, proposal.proposer_id),
                failure_tags,
            ))
        return _WorldDraft(
            family_id=assignment.family_id,
            variant_id=base.variant_id,
            snapshot=projector.snapshot(),
            evidence_view=base.evidence_view,
            identity_view=base.identity_view,
            authority_view=base.authority_view,
            proposal_context=context,
            now_epoch_ms=base.now_epoch_ms,
            target=target,
            alternatives=tuple(alternatives),
            required_defeater_refs=base.required_defeater_refs,
            failure_surface_tags=base.failure_surface_tags,
        )
