from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_POLICY_PATH = ROOT / "src" / "training" / "source_policy.py"
SPEC = importlib.util.spec_from_file_location("ceta_source_policy_for_test", SOURCE_POLICY_PATH)
assert SPEC is not None and SPEC.loader is not None
SOURCE_POLICY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SOURCE_POLICY
SPEC.loader.exec_module(SOURCE_POLICY)
TrainingSourceViolation = SOURCE_POLICY.TrainingSourceViolation
validate_training_sources = SOURCE_POLICY.validate_training_sources


DATA = ROOT / "data" / "ceta_architecture_material_v1"


class SuppliedArchitectureDataTests(unittest.TestCase):
    def test_material_manifest_preserves_holdout_boundary(self):
        manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataset_id"], "CETA_ARCHITECTURE_MATERIAL/v1")
        self.assertEqual(manifest["counts"]["section_situational_templates"], 1624)
        self.assertEqual(manifest["counts"]["public_scenarios"], 20)
        self.assertFalse(manifest["private_holdout"]["materialized_in_repository"])
        self.assertFalse(manifest["training_boundary"]["current_ceta_curriculum_automatically_modified"])

    def test_private_holdout_payloads_are_absent(self):
        forbidden = {"PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl", "ANSWER_KEY_SEPARATE.jsonl"}
        self.assertFalse(any(path.name in forbidden for path in DATA.rglob("*")))

    def test_raw_material_and_holdout_cannot_be_direct_training_sources(self):
        blocked = (
            "data/ceta_architecture_material_v1/training/public_scenarios.jsonl",
            "evaluation/private_holdout/PRIVATE_CHALLENGE_60_NO_ANSWERS.jsonl",
            "ANSWER_KEY_SEPARATE.jsonl",
        )
        for path in blocked:
            with self.subTest(path=path):
                with self.assertRaises(TrainingSourceViolation):
                    validate_training_sources((path,))


if __name__ == "__main__":
    unittest.main()
