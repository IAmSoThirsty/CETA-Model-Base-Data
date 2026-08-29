from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

from history import domain_hash


DATASET_ID = "CETA_LANGUAGE_ADAPTER_DATASET/v1"
SCHEMA_VERSION = 1
SYSTEM_PROMPT = (
    "You are the language and observation adapter for a Constitutional Epistemic "
    "Transition Algebra (CETA) system. Analyze the supplied language without "
    "inventing identity, authority, evidence, consent, or certainty. Preserve human "
    "decision authority. Return only the requested JSON object."
)
STARTING_STATE_LABEL = "Starting state"
AVAILABLE_EVIDENCE_LABEL = "Available evidence"
MISSING_EVIDENCE_LABEL = "Missing or uncertain evidence"
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class _SourceSpec:
    record_kind: str
    serialization: str
    json_object_mode: str = "single"


PUBLIC_SOURCE_SPECS: Mapping[str, _SourceSpec] = {
    "training/public_scenarios.jsonl": _SourceSpec("public_scenario", "jsonl"),
    "training/section_situational_templates_1624.jsonl": _SourceSpec("section_template", "jsonl"),
    "training/section_awareness_406.jsonl": _SourceSpec("section_awareness", "jsonl"),
    "training/role_contracts_21.json": _SourceSpec("role_contract", "json_array"),
    "training/role_conditioned_cases_84.jsonl": _SourceSpec("role_case", "jsonl"),
    "training/unacceptable_failures.json": _SourceSpec("unacceptable_failure", "json_array"),
    "evaluation/jbb_benign_behaviors.csv": _SourceSpec("jbb_behavior", "csv"),
    "evaluation/jbb_harmful_behaviors.csv": _SourceSpec("jbb_behavior", "csv"),
    "evaluation/owasp_dsgai_risk_taxonomy.json": _SourceSpec("owasp_risk", "json_array"),
    "evaluation/aegis_safety_taxonomy.json": _SourceSpec("aegis_category", "json_object", "lists"),
    "evaluation/beavertails_harm_categories.json": _SourceSpec("beavertails_category", "json_array"),
    "evaluation/mitre_atlas_release_index.json": _SourceSpec("mitre_release", "json_object"),
    "evaluation/purplellama_autopatch_samples.json": _SourceSpec("purplellama_sample", "json_array"),
}


class LanguageAdapterBindingError(ValueError):
    pass


def normalize_huggingface_cache_environment(environment: MutableMapping[str, str]) -> bool:
    """Migrate the removed Transformers cache variable without discarding its path."""
    legacy_cache = environment.pop("TRANSFORMERS_CACHE", None)
    if legacy_cache:
        environment.setdefault("HF_HOME", legacy_cache)
        return True
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def consumed_evaluator_receipt(
    evidence_root: Path,
    *,
    challenge_sha256: str,
    answer_key_sha256: str,
) -> dict[str, str] | None:
    """Return the public receipt that proves an evaluator is no longer clean-unseen."""
    for path in sorted(evidence_root.glob("*.json")):
        receipt = _matching_calibration_receipt(path, challenge_sha256, answer_key_sha256)
        if receipt is not None:
            return receipt
    return None


def _matching_calibration_receipt(path: Path, challenge_sha256: str, answer_key_sha256: str) -> dict[str, str] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if value.get("schema_id") != "CETA_LANGUAGE_ADAPTER_H100_CALIBRATION/v1":
        return None
    if value.get("challenge_sha256") != challenge_sha256 or value.get("answer_key_sha256") != answer_key_sha256:
        return None
    return {"receipt": path.name, "run_date": str(value.get("run_date", ""))}


def _read_records(path: Path, spec: _SourceSpec) -> list[tuple[str, Any, str | None]]:
    result: list[tuple[str, Any, str | None]] = []
    if spec.serialization == "jsonl":
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                result.append((f"line:{index:06d}", json.loads(line), None))
    elif spec.serialization == "csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            result.extend((f"row:{index:06d}", dict(row), None) for index, row in enumerate(csv.DictReader(handle), 1))
    elif spec.serialization == "json_array":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise LanguageAdapterBindingError(f"expected JSON array: {path}")
        result.extend((f"index:{index:06d}", item, None) for index, item in enumerate(value))
    elif spec.serialization == "json_object":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise LanguageAdapterBindingError(f"expected JSON object: {path}")
        if spec.json_object_mode == "lists":
            for key in sorted(value):
                items = value[key]
                if not isinstance(items, list):
                    raise LanguageAdapterBindingError(f"expected list at {path}#{key}")
                result.extend((f"key:{key}/index:{index:06d}", item, str(key)) for index, item in enumerate(items))
        else:
            result.append(("document", value, None))
    else:
        raise LanguageAdapterBindingError(f"unsupported source serialization: {spec.serialization}")
    return result


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return _json(value)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return "\n".join(f"- {_text(item)}" for item in value)
    return str(value)


def _scenario_prompt(record: Mapping[str, Any], *, title_key: str, action_key: str) -> str:
    fields = (
        ("Scenario", title_key),
        (STARTING_STATE_LABEL, _preferred_key(record, STARTING_STATE_LABEL, "starting_state")),
        (AVAILABLE_EVIDENCE_LABEL, _preferred_key(record, AVAILABLE_EVIDENCE_LABEL, "available_evidence")),
        (
            MISSING_EVIDENCE_LABEL,
            _preferred_key(record, MISSING_EVIDENCE_LABEL, "missing_or_uncertain_evidence"),
        ),
        ("Identity", _preferred_key(record, "Identity involved", "identity_involved")),
        ("Authority", _preferred_key(record, "Authority granted", "authority_granted")),
        ("Requested action", action_key),
    )
    body = "\n\n".join(f"{label}:\n{_text(record.get(key))}" for label, key in fields)
    return (
        f"{body}\n\nDetermine the bounded decision. Return JSON with keys "
        '"decision", "reasoning", "missing_evidence", and "wrong_decision_risks".'
    )


def _preferred_key(record: Mapping[str, Any], preferred: str, fallback: str) -> str:
    return preferred if preferred in record else fallback


def _messages_for_record(kind: str, value: Any, *, path: str, group: str | None) -> list[dict[str, str]]:
    if kind == "public_scenario":
        assert isinstance(value, Mapping)
        user = _scenario_prompt(value, title_key="Scenario name", action_key="Requested action")
        assistant = {
            "decision": value.get("Correct outcome", ""),
            "reasoning": value.get("Why it is correct", ""),
            "missing_evidence": value.get(MISSING_EVIDENCE_LABEL, []),
            "wrong_decision_risks": value.get("Consequences of a wrong decision", []),
        }
    elif kind == "section_template":
        assert isinstance(value, Mapping)
        user = _scenario_prompt(value, title_key="scenario_name", action_key="requested_decision")
        assistant = {
            "decision": value.get("correct_outcome", ""),
            "reasoning": value.get("why", ""),
            "missing_evidence": value.get("missing_or_uncertain_evidence", []),
            "wrong_decision_risks": [value.get("wrong_consequence", "")],
        }
    elif kind == "section_awareness":
        assert isinstance(value, Mapping)
        user = (
            f"Section candidate: {value.get('section_id')} {value.get('title')}\n"
            f"Purpose: {_text(value.get('purpose'))}\n"
            f"Domain cues:\n{_text(value.get('domain_cues'))}\n\n"
            "State when this discipline applies, when it does not, the human authority boundary, "
            "the AI boundary, required evidence, and recovery. Return JSON with keys "
            '"section", "applies_when", "does_not_apply_when", "human_authority", '
            '"ai_boundary", "evidence", and "recovery".'
        )
        assistant = {
            "section": {"id": value.get("section_id"), "title": value.get("title")},
            "applies_when": value.get("applies_when", []),
            "does_not_apply_when": value.get("does_not_apply_when", []),
            "human_authority": value.get("human_authority", ""),
            "ai_boundary": value.get("ai_boundary", ""),
            "evidence": value.get("evidence_requirements", []),
            "recovery": value.get("recovery", []),
        }
    elif kind == "role_contract":
        assert isinstance(value, Mapping)
        user = (
            f"Role candidate: {value.get('role_id')} {value.get('role_name')}\n"
            "State the role's legitimate function, responsibility, operating boundary, and prohibited behavior. "
            'Return JSON with keys "role", "function", "responsibility", "boundary", and "prohibited".'
        )
        assistant = {
            "role": {"id": value.get("role_id"), "name": value.get("role_name")},
            "function": value.get("primary_function", ""),
            "responsibility": value.get("core_responsibility", ""),
            "boundary": value.get("operating_posture", ""),
            "prohibited": value.get("prohibited_behavior", ""),
        }
    elif kind == "role_case":
        assert isinstance(value, Mapping)
        user = (
            f"Scenario:\n{_text(value.get('scenario'))}\n\nDetermine the correct role behavior and authority boundary. "
            'Return JSON with keys "role_behavior", "boundary", and "incorrect_behavior".'
        )
        assistant = {
            "role_behavior": value.get("correct_role_behavior", ""),
            "boundary": value.get("boundary", ""),
            "incorrect_behavior": value.get("incorrect_behavior", ""),
        }
    elif kind == "unacceptable_failure":
        assert isinstance(value, Mapping)
        user = (
            f"Failure scenario: {value.get('name')}\nPrior failure: {_text(value.get('prior_failure'))}\n"
            "Identify the unacceptable decision, required lesson, and danger. "
            'Return JSON with keys "unacceptable_decision", "required_lesson", and "danger".'
        )
        assistant = {
            "unacceptable_decision": value.get("unacceptable_decision", ""),
            "required_lesson": value.get("required_lesson", ""),
            "danger": value.get("danger", ""),
        }
    elif kind == "jbb_behavior":
        assert isinstance(value, Mapping)
        polarity = "BENIGN" if "benign" in path else "HARMFUL"
        user = (
            f"Requested behavior:\n{_text(value.get('Goal'))}\n\nClassify the supplied request using the bound public "
            'defensive label. Return JSON with keys "safety_polarity", "behavior", and "category".'
        )
        assistant = {
            "safety_polarity": polarity,
            "behavior": value.get("Behavior", ""),
            "category": value.get("Category", ""),
        }
    elif kind == "owasp_risk":
        assert isinstance(value, Mapping)
        user = (
            f"Risk name: {_text(value.get('name'))}\nIdentify the canonical bound risk. "
            'Return JSON with keys "risk_id" and "risk_name".'
        )
        assistant = {"risk_id": value.get("id", ""), "risk_name": value.get("name", "")}
    elif kind == "aegis_category":
        user = (
            f"Safety taxonomy term: {_text(value)}\nClassify its canonical taxonomy group. "
            'Return JSON with keys "term" and "taxonomy_group".'
        )
        assistant = {"term": value, "taxonomy_group": group or "UNKNOWN"}
    elif kind == "beavertails_category":
        user = (
            f"Safety taxonomy term: {_text(value)}\nIdentify it as a BeaverTails harm category. "
            'Return JSON with keys "term" and "taxonomy".'
        )
        assistant = {"term": value, "taxonomy": "BeaverTails harm category"}
    elif kind == "mitre_release":
        user = (
            "Report the exact manifest-bound MITRE ATLAS release metadata supplied to this system. "
            'Return JSON with key "release_metadata".'
        )
        assistant = {"release_metadata": value}
    elif kind == "purplellama_sample":
        user = (
            f"PurpleLlama CyberSecEval AutoPatch sample identifier: {_text(value)}\n"
            'Record the bound public sample identity. Return JSON with keys "sample_id" and "source".'
        )
        assistant = {"sample_id": value, "source": "PurpleLlama CyberSecEval AutoPatch"}
    else:
        raise LanguageAdapterBindingError(f"unsupported public record kind: {kind}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": _json(assistant)},
    ]


@dataclass(frozen=True)
class LanguageAdapterExample:
    example_id: str
    source_record_id: str
    source_record_sha256: str
    source_path: str
    source_locator: str
    source_lineage_id: str
    source_class: str
    record_kind: str
    license_id: str
    family_id: str
    split: str
    messages: tuple[Mapping[str, str], ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": DATASET_ID,
            "example_id": self.example_id,
            "source_record_id": self.source_record_id,
            "source_record_sha256": self.source_record_sha256,
            "source_path": self.source_path,
            "source_locator": self.source_locator,
            "source_lineage_id": self.source_lineage_id,
            "source_class": self.source_class,
            "record_kind": self.record_kind,
            "license_id": self.license_id,
            "family_id": self.family_id,
            "split": self.split,
            "messages": [dict(message) for message in self.messages],
        }


def build_language_adapter_examples(
    material_root: str | Path,
    curriculum_root: str | Path,
) -> tuple[LanguageAdapterExample, ...]:
    material = Path(material_root)
    curriculum = Path(curriculum_root)
    catalog = json.loads((curriculum / "source_catalog.json").read_text(encoding="utf-8"))
    if catalog.get("catalog_id") != "CETA_PUBLIC_SOURCE_CATALOG/v3" or catalog.get("source_record_count") != 2439:
        raise LanguageAdapterBindingError("public source catalog identity mismatch")
    if catalog.get("source_dataset_manifest_sha256") != sha256_file(material / MANIFEST_FILENAME):
        raise LanguageAdapterBindingError("public source catalog material-manifest binding mismatch")
    boundary = catalog.get("controlled_evaluation", {})
    if boundary.get("usage_class") != "CONTROLLED_EVALUATION" or boundary.get("materialized_in_repository") is not False:
        raise LanguageAdapterBindingError("controlled evaluation boundary is not preserved by the source catalog")
    catalog_records = tuple(catalog.get("records", []))
    by_key = {(str(record["path"]), str(record["locator"])): record for record in catalog_records}
    source_files = {str(item["path"]): item for item in catalog.get("source_files", [])}

    assignments: dict[str, str] = {}
    for line in (curriculum / "source_assignments.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        family_id = str(raw["family_id"])
        for source_id in raw["source_record_ids"]:
            if source_id in assignments:
                raise LanguageAdapterBindingError(f"source record has multiple family assignments: {source_id}")
            assignments[str(source_id)] = family_id

    split_record = json.loads((curriculum / "splits.json").read_text(encoding="utf-8"))
    family_to_split: dict[str, str] = {}
    for split in ("train", "validation", "heldout"):
        for family_id in split_record["family_splits"][split]:
            if family_id in family_to_split:
                raise LanguageAdapterBindingError(f"family appears in multiple splits: {family_id}")
            family_to_split[str(family_id)] = split

    examples: list[LanguageAdapterExample] = []
    for path, spec in sorted(PUBLIC_SOURCE_SPECS.items()):
        source_file = source_files.get(path)
        if not isinstance(source_file, Mapping) or sha256_file(material / path) != source_file.get("artifact_sha256"):
            raise LanguageAdapterBindingError(f"public source file is not hash-bound: {path}")
        for locator, value, group in _read_records(material / path, spec):
            source = by_key.get((path, locator))
            if source is None:
                raise LanguageAdapterBindingError(f"source payload is not catalog-bound: {path}#{locator}")
            source_id = str(source["source_record_id"])
            family_id = assignments.get(source_id)
            if family_id is None:
                raise LanguageAdapterBindingError(f"source record has no family assignment: {source_id}")
            split = family_to_split.get(family_id)
            if split is None:
                raise LanguageAdapterBindingError(f"source family has no split: {family_id}")
            record_kind = str(source["record_kind"])
            if record_kind != spec.record_kind:
                raise LanguageAdapterBindingError(f"source record kind mismatch: {path}#{locator}")
            messages = _messages_for_record(record_kind, value, path=path, group=group)
            example_id = domain_hash(
                {"source_record_id": source_id, "messages": messages},
                domain="CETA/LANGUAGE_ADAPTER_EXAMPLE/v1",
            )
            examples.append(LanguageAdapterExample(
                example_id=example_id,
                source_record_id=source_id,
                source_record_sha256=str(source["record_sha256"]),
                source_path=str(source["path"]),
                source_locator=str(source["locator"]),
                source_lineage_id=str(source["lineage_id"]),
                source_class=str(source["source_class"]),
                record_kind=record_kind,
                license_id=str(source["license_id"]),
                family_id=family_id,
                split=split,
                messages=tuple(messages),
            ))

    ordered = tuple(sorted(examples, key=lambda item: item.example_id))
    expected_ids = {str(record["source_record_id"]) for record in catalog_records}
    actual_ids = [item.source_record_id for item in ordered]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise LanguageAdapterBindingError("public source records are not represented exactly once")
    lineage_splits: dict[str, str] = {}
    for item in ordered:
        previous = lineage_splits.setdefault(item.source_lineage_id, item.split)
        if previous != item.split:
            raise LanguageAdapterBindingError(f"source lineage crosses language-adapter splits: {item.source_lineage_id}")
        if len(item.messages) != 3 or [message["role"] for message in item.messages] != ["system", "user", "assistant"]:
            raise LanguageAdapterBindingError(f"invalid chat structure: {item.example_id}")
        json.loads(item.messages[-1]["content"])
    return ordered


def write_language_adapter_dataset(
    output_root: str | Path,
    examples: Iterable[LanguageAdapterExample],
    *,
    material_manifest_sha256: str,
    curriculum_manifest_sha256: str,
) -> dict[str, Any]:
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    materialized = tuple(examples)
    files: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for split in ("train", "validation", "heldout"):
        path = output / f"{split}.jsonl"
        records = [item.to_record() for item in materialized if item.split == split]
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(_json(record) + "\n")
        counts[split] = len(records)
        files[split] = {"path": path.name, "count": len(records), "sha256": sha256_file(path)}

    by_class: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    licenses: dict[str, int] = {}
    for item in materialized:
        by_class[item.source_class] = by_class.get(item.source_class, 0) + 1
        by_kind[item.record_kind] = by_kind.get(item.record_kind, 0) + 1
        licenses[item.license_id] = licenses.get(item.license_id, 0) + 1
    body = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "record_count": len(materialized),
        "split_counts": counts,
        "source_class_counts": dict(sorted(by_class.items())),
        "record_kind_counts": dict(sorted(by_kind.items())),
        "license_counts": dict(sorted(licenses.items())),
        "source_lineage_count": len({item.source_lineage_id for item in materialized}),
        "material_manifest_sha256": material_manifest_sha256,
        "curriculum_manifest_sha256": curriculum_manifest_sha256,
        "files": files,
        "training_boundary": {
            "derived_public_records_only": True,
            "raw_source_files_direct_optimizer_input": False,
            "controlled_evaluation_optimizer_input": False,
            "controlled_evaluation_answer_access": False,
            "split_unit": "source_lineage_via_ceta_curriculum_v3_family",
        },
    }
    manifest = {**body, "dataset_hash": domain_hash(body, domain="CETA/LANGUAGE_ADAPTER_DATASET/v1")}
    (output / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def load_verified_language_dataset(root: str | Path) -> tuple[dict[str, Any], dict[str, tuple[dict[str, Any], ...]]]:
    base = Path(root)
    manifest = json.loads((base / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID or manifest.get("schema_version") != SCHEMA_VERSION:
        raise LanguageAdapterBindingError("language-adapter dataset identity mismatch")
    boundary = manifest.get("training_boundary", {})
    if boundary.get("derived_public_records_only") is not True or boundary.get("controlled_evaluation_optimizer_input") is not False:
        raise LanguageAdapterBindingError("language-adapter optimizer boundary mismatch")
    body = {key: value for key, value in manifest.items() if key != "dataset_hash"}
    if manifest.get("dataset_hash") != domain_hash(body, domain="CETA/LANGUAGE_ADAPTER_DATASET/v1"):
        raise LanguageAdapterBindingError("language-adapter manifest hash mismatch")
    result: dict[str, tuple[dict[str, Any], ...]] = {}
    seen_examples: set[str] = set()
    lineage_splits: dict[str, str] = {}
    for split in ("train", "validation", "heldout"):
        info = manifest["files"][split]
        path = base / str(info["path"])
        if sha256_file(path) != info["sha256"]:
            raise LanguageAdapterBindingError(f"language-adapter split hash mismatch: {split}")
        rows = tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        if len(rows) != int(info["count"]) or len(rows) != int(manifest["split_counts"][split]):
            raise LanguageAdapterBindingError(f"language-adapter split count mismatch: {split}")
        for row in rows:
            if row.get("dataset_id") != DATASET_ID or row.get("split") != split:
                raise LanguageAdapterBindingError(f"language-adapter row binding mismatch: {split}")
            example_id = str(row["example_id"])
            if example_id in seen_examples:
                raise LanguageAdapterBindingError(f"duplicate language-adapter example: {example_id}")
            seen_examples.add(example_id)
            lineage = str(row["source_lineage_id"])
            previous = lineage_splits.setdefault(lineage, split)
            if previous != split:
                raise LanguageAdapterBindingError(f"language-adapter lineage leakage: {lineage}")
            messages = row.get("messages")
            if not isinstance(messages, list) or [message.get("role") for message in messages] != ["system", "user", "assistant"]:
                raise LanguageAdapterBindingError(f"invalid language-adapter messages: {example_id}")
            json.loads(str(messages[-1]["content"]))
        result[split] = rows
    if len(seen_examples) != int(manifest["record_count"]):
        raise LanguageAdapterBindingError("language-adapter total count mismatch")
    return manifest, result
