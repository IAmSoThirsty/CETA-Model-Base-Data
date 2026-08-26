from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from training import (
    CETA_CURRICULUM_V3_GENERATOR_ID,
    CetaWorldCurriculumV3,
    PublicSourceCatalog,
    WorldCurriculumArtifactWriter,
    build_source_family_assignments,
    write_source_sidecars,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data/ceta_curriculum_v3")
    parser.add_argument("--material-root", type=Path, default=ROOT / "data/ceta_architecture_material_v1")
    parser.add_argument("--families-per-operation", type=int, default=20)
    parser.add_argument("--variants-per-family", type=int, default=3)
    args = parser.parse_args()

    catalog = PublicSourceCatalog.load(args.material_root)
    assignments = build_source_family_assignments(
        catalog,
        args.material_root,
        families_per_operation=args.families_per_operation,
    )
    catalog_path, assignments_path = write_source_sidecars(args.output, catalog, assignments)
    cases = CetaWorldCurriculumV3(
        assignments,
        variants_per_family=args.variants_per_family,
    ).build()
    source_class_counts = Counter(record.source_class for record in catalog.records)
    manifest = WorldCurriculumArtifactWriter.write(
        args.output,
        cases,
        generator_id=CETA_CURRICULUM_V3_GENERATOR_ID,
        bound_artifacts={
            "source_catalog": catalog_path,
            "source_assignments": assignments_path,
        },
        manifest_metadata={
            "source_binding": {
                "source_dataset_id": catalog.source_dataset_id,
                "source_dataset_manifest_sha256": catalog.source_dataset_manifest_sha256,
                "source_record_count": len(catalog.records),
                "source_lineage_count": len({record.lineage_id for record in catalog.records}),
                "source_family_count": len(assignments),
                "source_to_operation_semantic_adjudication": False,
                "source_assignment_method": "DETERMINISTIC_HASH_PARTITION",
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
            }
        },
    )
    print("CETA WORLD CURRICULUM V3 BUILT")
    print(
        f"cases={manifest['case_count']} families={manifest['world_family_count']} "
        f"operations={manifest['operation_count']} negatives={manifest['illegal_alternative_count']}"
    )
    print(
        f"source_records={len(catalog.records)} source_families={len(assignments)} "
        f"public_defensive={source_class_counts['DEFENSIVE_PUBLIC']}"
    )
    for split, item in manifest["files"].items():
        print(f"{split}={item['count']} sha256={item['sha256']}")


if __name__ == "__main__":
    main()
