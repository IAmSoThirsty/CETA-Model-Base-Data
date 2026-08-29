from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from hashlib import sha256
from typing import Iterable


class TrainingSourceViolation(ValueError):
    pass


# Evaluator/runtime paths are separate from optimizer inputs. This is a role
# boundary, not an instruction imported from the supplied documents.
NEVER_TRAIN_PATTERNS: tuple[str, ...] = (
    "evaluation/**",
    "history/**",
    "authority/state/**",
    "authority/evidence/**",
    "authority/continuity/**",
    "sources/**/tests/**",
    "sources/**/verification/**",
    "views/evaluation/**",
)

# Public source material is allowed to inform deterministic structured
# derivation, but it is not itself optimizer input. Only the resulting
# state/transition cases may be passed to the optimizer.
ARCHITECTURE_MATERIAL_ROOT = "data/ceta_architecture_material_v1"
STRUCTURED_DERIVATION_PATTERNS: tuple[str, ...] = (
    f"{ARCHITECTURE_MATERIAL_ROOT}/training/**",
    f"{ARCHITECTURE_MATERIAL_ROOT}/evaluation/**",
    f"{ARCHITECTURE_MATERIAL_ROOT}/governance/**",
)
CONSTRAINT_ONLY_PATTERNS: tuple[str, ...] = (
    f"{ARCHITECTURE_MATERIAL_ROOT}/maps/**",
    f"{ARCHITECTURE_MATERIAL_ROOT}/mission/**",
    f"{ARCHITECTURE_MATERIAL_ROOT}/provenance/**",
    f"{ARCHITECTURE_MATERIAL_ROOT}/manifest.json",
)

CONTROLLED_EVALUATION_PATTERNS: tuple[str, ...] = (
    "data/ceta_controlled_evaluation/**",
    "**/ceta_controlled_evaluation/**",
    "runtime_state.jsonl",
    "stable_knowledge.jsonl",
    "implementation_reference.jsonl",
    "stable_source_text.jsonl",
    "implementation_code_reference.jsonl",
    "heldout_sources/**",
    "source_archive/**",
    "**/private_holdout/**",
    "**/PRIVATE_EVALUATION_ONLY/**",
    "**/EVALUATOR_ONLY/**",
    "PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl",
    "ANSWER_KEY_SEPARATE.jsonl",
)

STRUCTURED_DERIVATION_ELIGIBLE = "STRUCTURED_DERIVATION_ELIGIBLE"
PROVENANCE_OR_CONSTRAINT_ONLY = "PROVENANCE_OR_CONSTRAINT_ONLY"
CONTROLLED_EVALUATION = "CONTROLLED_EVALUATION"
# Backward-compatible symbol for callers; new manifests use the clearer name.
PRIVATE_EVALUATION_ONLY = CONTROLLED_EVALUATION
EVALUATOR_ONLY = "EVALUATOR_ONLY"
UNCLASSIFIED = "UNCLASSIFIED"


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def source_usage_class(path: str) -> str:
    """Classify a source path without treating public material as optimizer data."""
    normalized = _norm(path)
    basename = normalized.rsplit("/", 1)[-1]
    for pattern in CONTROLLED_EVALUATION_PATTERNS:
        if fnmatch(normalized, pattern) or fnmatch(basename, pattern):
            return CONTROLLED_EVALUATION
    for pattern in NEVER_TRAIN_PATTERNS:
        if fnmatch(normalized, pattern):
            return EVALUATOR_ONLY
    for pattern in STRUCTURED_DERIVATION_PATTERNS:
        if fnmatch(normalized, pattern):
            return STRUCTURED_DERIVATION_ELIGIBLE
    for pattern in CONSTRAINT_ONLY_PATTERNS:
        if fnmatch(normalized, pattern):
            return PROVENANCE_OR_CONSTRAINT_ONLY
    return UNCLASSIFIED


def forbidden_reason(path: str) -> str | None:
    normalized = _norm(path)
    for pattern in NEVER_TRAIN_PATTERNS:
        if fnmatch(normalized, pattern):
            return f"never_train:{pattern}"
    for pattern in CONTROLLED_EVALUATION_PATTERNS:
        if fnmatch(normalized, pattern) or fnmatch(normalized.rsplit("/", 1)[-1], pattern):
            return f"controlled_evaluation_not_optimizer_input:{pattern}"
    for pattern in STRUCTURED_DERIVATION_PATTERNS:
        if fnmatch(normalized, pattern):
            return f"raw_source_requires_structured_derivation:{pattern}"
    for pattern in CONSTRAINT_ONLY_PATTERNS:
        if fnmatch(normalized, pattern):
            return f"provenance_or_constraint_not_optimizer_input:{pattern}"
    return None


def validate_training_sources(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(_norm(p) for p in paths)
    violations = [(p, forbidden_reason(p)) for p in normalized]
    violations = [(p, r) for p, r in violations if r is not None]
    if violations:
        detail = "; ".join(f"{p} -> {r}" for p, r in violations)
        raise TrainingSourceViolation(f"training source isolation violation: {detail}")
    return normalized


def validate_structured_derivation_sources(paths: Iterable[str]) -> tuple[str, ...]:
    """Accept only public records approved to derive structured curriculum cases.

    This is a separate boundary from :func:`validate_training_sources`: passing
    this check authorizes deterministic derivation, not direct optimizer use.
    """
    normalized = tuple(_norm(p) for p in paths)
    violations = [
        (path, source_usage_class(path))
        for path in normalized
        if source_usage_class(path) != STRUCTURED_DERIVATION_ELIGIBLE
    ]
    if violations:
        detail = "; ".join(f"{path} -> {usage}" for path, usage in violations)
        raise TrainingSourceViolation(f"structured derivation source violation: {detail}")
    return normalized


@dataclass(frozen=True)
class DatasetPartition:
    train: tuple[str, ...]
    validation: tuple[str, ...]
    heldout: tuple[str, ...]

    def verify_disjoint(self) -> None:
        a, b, c = set(self.train), set(self.validation), set(self.heldout)
        if a & b or a & c or b & c:
            raise TrainingSourceViolation("dataset partition overlap detected")


def deterministic_partition(
    case_ids: Iterable[str],
    *,
    train_percent: int = 80,
    validation_percent: int = 10,
) -> DatasetPartition:
    """Stable split by case identity; never forces tiny strata into all splits."""
    if not 1 <= train_percent <= 98:
        raise TrainingSourceViolation("train_percent must be between 1 and 98")
    if not 1 <= validation_percent <= 98 or train_percent + validation_percent >= 100:
        raise TrainingSourceViolation("validation percentage leaves no heldout partition")
    unique = sorted({str(x) for x in case_ids})
    if not unique:
        raise TrainingSourceViolation("cannot partition an empty case set")
    train: list[str] = []
    validation: list[str] = []
    heldout: list[str] = []
    train_cut = train_percent * 100
    validation_cut = (train_percent + validation_percent) * 100
    for case_id in unique:
        bucket = int.from_bytes(sha256(("CETA/SPLIT/v1\n" + case_id).encode("utf-8")).digest()[:8], "big") % 10000
        if bucket < train_cut:
            train.append(case_id)
        elif bucket < validation_cut:
            validation.append(case_id)
        else:
            heldout.append(case_id)
    result = DatasetPartition(tuple(train), tuple(validation), tuple(heldout))
    result.verify_disjoint()
    return result

@dataclass(frozen=True)
class WorldDatasetPartition:
    train: tuple[str, ...]
    validation: tuple[str, ...]
    heldout: tuple[str, ...]
    train_families: tuple[str, ...]
    validation_families: tuple[str, ...]
    heldout_families: tuple[str, ...]

    def verify_disjoint(self) -> None:
        cases=(set(self.train),set(self.validation),set(self.heldout))
        if cases[0]&cases[1] or cases[0]&cases[2] or cases[1]&cases[2]:
            raise TrainingSourceViolation("dataset case overlap detected")
        families=(set(self.train_families),set(self.validation_families),set(self.heldout_families))
        if families[0]&families[1] or families[0]&families[2] or families[1]&families[2]:
            raise TrainingSourceViolation("world-family leakage across dataset partitions")


def partition_world_families(cases: Iterable[object]) -> WorldDatasetPartition:
    """Stratified 80/10/10 split over world families, never individual variants.

    Each opcode must provide at least ten distinct families. Families are sorted
    by a stable domain hash within each opcode, then assigned 8/1/1. Every
    variant from one family follows its family into the same split.
    """
    materialized=tuple(cases)
    if not materialized:
        raise TrainingSourceViolation("cannot partition an empty world curriculum")
    by_operation: dict[str, dict[str,list[str]]] = {}
    fingerprint_to_family: dict[str,str] = {}
    for case in materialized:
        case_id, family, fingerprint, operation = _world_partition_fields(case)
        previous=fingerprint_to_family.setdefault(fingerprint,family)
        if previous != family:
            raise TrainingSourceViolation(
                f"structurally identical worlds assigned different family IDs: {previous} vs {family}"
            )
        by_operation.setdefault(operation,{}).setdefault(family,[]).append(case_id)

    train_cases: list[str]=[]; validation_cases: list[str]=[]; heldout_cases: list[str]=[]
    train_families: list[str]=[]; validation_families: list[str]=[]; heldout_families: list[str]=[]
    for operation in sorted(by_operation):
        families=by_operation[operation]
        groups=_partition_operation_families(operation, families)
        for family in groups[0]:
            train_families.append(family); train_cases.extend(sorted(families[family]))
        for family in groups[1]:
            validation_families.append(family); validation_cases.extend(sorted(families[family]))
        for family in groups[2]:
            heldout_families.append(family); heldout_cases.extend(sorted(families[family]))

    result=WorldDatasetPartition(
        tuple(sorted(train_cases)),tuple(sorted(validation_cases)),tuple(sorted(heldout_cases)),
        tuple(sorted(train_families)),tuple(sorted(validation_families)),tuple(sorted(heldout_families)),
    )
    result.verify_disjoint()
    assigned=set(result.train)|set(result.validation)|set(result.heldout)
    expected={str(case.case_id) for case in materialized}
    if assigned != expected:
        raise TrainingSourceViolation("world-family partition did not assign every case exactly once")
    return result


def _world_partition_fields(case: object) -> tuple[str, str, str, str]:
    try:
        return (
            str(case.case_id),
            str(case.world_family_id),
            str(case.structural_fingerprint),
            str(case.target_proposal.operation),
        )
    except AttributeError as exc:
        raise TrainingSourceViolation("world-family partition requires TransitionTrainingCase-like objects") from exc


def _partition_operation_families(operation: str, families: dict[str, list[str]]) -> tuple[list[str], list[str], list[str]]:
    if len(families) < 10:
        raise TrainingSourceViolation(
            f"operation {operation} has {len(families)} world families; at least 10 are required"
        )
    ordered=sorted(
        families,
        key=lambda family: sha256(
            ("CETA/WORLD_FAMILY_SPLIT/v1\n" + operation + "\n" + family).encode("utf-8")
        ).digest(),
    )
    n_val=max(1,len(ordered)//10)
    n_held=max(1,len(ordered)//10)
    n_train=len(ordered)-n_val-n_held
    if n_train < 1:
        raise TrainingSourceViolation(f"operation {operation} leaves no training families")
    return ordered[:n_train],ordered[n_train:n_train+n_val],ordered[n_train+n_val:]
