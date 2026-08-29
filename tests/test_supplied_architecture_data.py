from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_POLICY_PATH = ROOT / "src" / "training" / "source_policy.py"
INGEST_PATH = ROOT / "scripts" / "ingest_supplied_architecture_data.py"
PACKAGE_BUILDER_PATH = ROOT / "scripts" / "build_package_manifest.py"
PACKAGE_SUMS_PATH = ROOT / "scripts" / "build_sha256sums.py"
PACKAGE_VERIFY_PATH = ROOT / "scripts" / "verify_package.py"
SPEC = importlib.util.spec_from_file_location("ceta_source_policy_for_test", SOURCE_POLICY_PATH)
assert SPEC is not None
assert SPEC.loader is not None
SOURCE_POLICY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SOURCE_POLICY
SPEC.loader.exec_module(SOURCE_POLICY)
INGEST_SPEC = importlib.util.spec_from_file_location("ceta_ingest_for_test", INGEST_PATH)
assert INGEST_SPEC is not None
assert INGEST_SPEC.loader is not None
INGEST = importlib.util.module_from_spec(INGEST_SPEC)
INGEST_SPEC.loader.exec_module(INGEST)
PACKAGE_BUILDER_SPEC = importlib.util.spec_from_file_location("ceta_package_builder_for_test", PACKAGE_BUILDER_PATH)
assert PACKAGE_BUILDER_SPEC is not None
assert PACKAGE_BUILDER_SPEC.loader is not None
PACKAGE_BUILDER = importlib.util.module_from_spec(PACKAGE_BUILDER_SPEC)
PACKAGE_BUILDER_SPEC.loader.exec_module(PACKAGE_BUILDER)
PACKAGE_SUMS_SPEC = importlib.util.spec_from_file_location("ceta_package_sums_for_test", PACKAGE_SUMS_PATH)
assert PACKAGE_SUMS_SPEC is not None
assert PACKAGE_SUMS_SPEC.loader is not None
PACKAGE_SUMS = importlib.util.module_from_spec(PACKAGE_SUMS_SPEC)
PACKAGE_SUMS_SPEC.loader.exec_module(PACKAGE_SUMS)
PACKAGE_VERIFY_SPEC = importlib.util.spec_from_file_location("ceta_package_verify_for_test", PACKAGE_VERIFY_PATH)
assert PACKAGE_VERIFY_SPEC is not None
assert PACKAGE_VERIFY_SPEC.loader is not None
PACKAGE_VERIFY = importlib.util.module_from_spec(PACKAGE_VERIFY_SPEC)
PACKAGE_VERIFY_SPEC.loader.exec_module(PACKAGE_VERIFY)
TrainingSourceViolation = SOURCE_POLICY.TrainingSourceViolation
source_usage_class = SOURCE_POLICY.source_usage_class
validate_training_sources = SOURCE_POLICY.validate_training_sources
validate_structured_derivation_sources = SOURCE_POLICY.validate_structured_derivation_sources
STRUCTURED_DERIVATION_ELIGIBLE = SOURCE_POLICY.STRUCTURED_DERIVATION_ELIGIBLE
PROVENANCE_OR_CONSTRAINT_ONLY = SOURCE_POLICY.PROVENANCE_OR_CONSTRAINT_ONLY
CONTROLLED_EVALUATION = SOURCE_POLICY.CONTROLLED_EVALUATION
EVALUATOR_ONLY = SOURCE_POLICY.EVALUATOR_ONLY


DATA = ROOT / "data" / "ceta_architecture_material_v1"


class SuppliedArchitectureDataTests(unittest.TestCase):
    def test_material_manifest_binds_controlled_evaluation(self):
        manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataset_id"], "CETA_ARCHITECTURE_MATERIAL/v1")
        self.assertEqual(manifest["counts"]["section_situational_templates"], 1624)
        self.assertEqual(manifest["counts"]["public_scenarios"], 20)
        evaluation = manifest["controlled_evaluation"]
        self.assertFalse(evaluation["materialized_in_repository"])
        self.assertTrue(evaluation["bound_to_architecture"])
        self.assertEqual(evaluation["usage_class"], CONTROLLED_EVALUATION)
        self.assertEqual(evaluation["known_exposed_case_ids"], ["H001"])
        self.assertEqual(evaluation["clean_unseen_case_count"], 59)
        self.assertTrue(manifest["training_boundary"]["current_ceta_curriculum_automatically_modified"])
        self.assertTrue(manifest["training_boundary"]["optimizer_requires_derived_structured_cases"])

    def test_manifest_classifies_each_materialized_source_for_v3_derivation(self):
        manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        by_path = manifest["training_boundary"]["source_usage_by_path"]
        self.assertEqual(by_path, {item["path"]: item["source_usage"] for item in manifest["files"]})
        self.assertEqual(
            manifest["training_boundary"]["source_usage_counts"],
            {
                STRUCTURED_DERIVATION_ELIGIBLE: 15,
                PROVENANCE_OR_CONSTRAINT_ONLY: 9,
            },
        )
        for path in (
            "training/public_scenarios.jsonl",
            "training/section_situational_templates_1624.jsonl",
            "evaluation/jbb_harmful_behaviors.csv",
            "evaluation/owasp_dsgai_risk_taxonomy.json",
            "governance/operation_risk_ranking.json",
        ):
            self.assertEqual(by_path[path], STRUCTURED_DERIVATION_ELIGIBLE)
        for path in (
            "mission/MISSION_PARAGRAPH.txt",
            "maps/section_dependency_edges.csv",
            "provenance/defensive_sources.csv",
        ):
            self.assertEqual(by_path[path], PROVENANCE_OR_CONSTRAINT_ONLY)

    def test_controlled_evaluation_payloads_are_absent_from_public_material(self):
        forbidden = {"PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl", "ANSWER_KEY_SEPARATE.jsonl"}
        self.assertFalse(any(path.name in forbidden for path in DATA.rglob("*")))

    def test_raw_public_material_and_holdout_cannot_be_direct_optimizer_sources(self):
        blocked = (
            "data/ceta_architecture_material_v1/training/public_scenarios.jsonl",
            "data/ceta_architecture_material_v1/evaluation/jbb_harmful_behaviors.csv",
            "evaluation/private_holdout/PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl",
            "ANSWER_KEY_SEPARATE.jsonl",
        )
        for path in blocked:
            with self.subTest(path=path):
                with self.assertRaises(TrainingSourceViolation):
                    validate_training_sources((path,))

    def test_public_human_and_defensive_sources_are_v3_derivation_eligible(self):
        eligible = (
            "data/ceta_architecture_material_v1/training/public_scenarios.jsonl",
            "data/ceta_architecture_material_v1/evaluation/jbb_harmful_behaviors.csv",
            "data/ceta_architecture_material_v1/governance/operation_risk_ranking.json",
        )
        self.assertEqual(validate_structured_derivation_sources(eligible), eligible)
        for path in eligible:
            self.assertEqual(source_usage_class(path), STRUCTURED_DERIVATION_ELIGIBLE)

    def test_private_evaluator_and_constraint_only_sources_cannot_drive_derivation(self):
        blocked = {
            "evaluation/heldout.jsonl": EVALUATOR_ONLY,
            "data/ceta_architecture_material_v1/provenance/defensive_sources.csv": PROVENANCE_OR_CONSTRAINT_ONLY,
            "data/private_holdout/PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl": CONTROLLED_EVALUATION,
        }
        for path, usage in blocked.items():
            with self.subTest(path=path):
                self.assertEqual(source_usage_class(path), usage)
                with self.assertRaises(TrainingSourceViolation):
                    validate_structured_derivation_sources((path,))

    def test_derived_v3_artifact_remains_an_optimizer_source_candidate(self):
        path = "data/ceta_curriculum_v3/train.jsonl"
        self.assertEqual(validate_training_sources((path,)), (path,))

    def test_controlled_evaluation_staging_cannot_target_public_repo_paths(self):
        expected = ROOT / "data" / "ceta_controlled_evaluation"
        self.assertEqual(
            INGEST.validate_controlled_evaluation_output(expected, DATA),
            expected.resolve(),
        )
        for unsafe in (DATA / "evaluation", ROOT / "docs" / "evaluation", ROOT):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    INGEST.validate_controlled_evaluation_output(unsafe, DATA)

    def test_controlled_evaluation_is_excluded_from_release_payload(self):
        answer_path = ROOT / "data" / "ceta_controlled_evaluation" / "answer_key.jsonl"
        self.assertFalse(PACKAGE_BUILDER.included(answer_path))
        self.assertNotIn("data/ceta_controlled_evaluation/answer_key.jsonl", PACKAGE_VERIFY.visible_files())

    def test_environment_metadata_is_excluded_from_release_payload(self):
        metadata_path = ROOT / "src" / "architecture_rebuild_ceta_reference_core.egg-info" / "PKG-INFO"
        self.assertFalse(PACKAGE_BUILDER.included(metadata_path))
        self.assertFalse(PACKAGE_SUMS.included(metadata_path))
        self.assertNotIn(
            "src/architecture_rebuild_ceta_reference_core.egg-info/PKG-INFO",
            PACKAGE_VERIFY.visible_files(),
        )
        virtualenv_path = ROOT / ".venv" / "pyvenv.cfg"
        self.assertFalse(PACKAGE_BUILDER.included(virtualenv_path))
        self.assertFalse(PACKAGE_SUMS.included(virtualenv_path))
        self.assertNotIn(".venv/pyvenv.cfg", PACKAGE_VERIFY.visible_files())

    def test_supplied_input_files_are_confined_to_trusted_roots(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            allowed_root = Path(allowed)
            inside = allowed_root / "source.zip"
            inside.write_bytes(b"source")
            escaped = Path(outside, "source.zip")
            escaped.write_bytes(b"source")
            self.assertEqual(
                INGEST.confined_regular_file(inside, roots=(allowed_root,)),
                inside.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "trusted source roots"):
                INGEST.confined_regular_file(escaped, roots=(allowed_root,))


if __name__ == "__main__":
    unittest.main()
