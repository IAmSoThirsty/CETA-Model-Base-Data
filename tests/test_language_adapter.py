from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LANGUAGE = load_module("ceta_language_adapter_tests", ROOT / "src/training/language_adapter.py")
SCORER = load_module("ceta_language_adapter_scorer_tests", ROOT / "scripts/score_controlled_language_evaluation.py")
SOURCE_POLICY = load_module("ceta_language_adapter_source_policy_tests", ROOT / "src/training/source_policy.py")
TRAINER = load_module("ceta_language_adapter_trainer_tests", ROOT / "scripts/train_language_adapter.py")


class LanguageAdapterDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset_root = ROOT / "data/ceta_language_adapter_v1"
        cls.manifest, cls.splits = LANGUAGE.load_verified_language_dataset(cls.dataset_root)

    def test_all_public_records_are_present_exactly_once(self):
        self.assertEqual(self.manifest["record_count"], 2439)
        self.assertEqual(
            self.manifest["source_class_counts"],
            {"DEFENSIVE_PUBLIC": 279, "HUMAN_RELATIONS_PUBLIC": 2160},
        )
        source_ids = [row["source_record_id"] for rows in self.splits.values() for row in rows]
        self.assertEqual(len(source_ids), len(set(source_ids)))

    def test_language_splits_are_lineage_disjoint(self):
        lineages = {
            split: {row["source_lineage_id"] for row in rows}
            for split, rows in self.splits.items()
        }
        self.assertFalse(lineages["train"] & lineages["validation"])
        self.assertFalse(lineages["train"] & lineages["heldout"])
        self.assertFalse(lineages["validation"] & lineages["heldout"])

    def test_optimizer_records_have_chat_targets_but_no_controlled_answers(self):
        forbidden = ("PRIVATE_CHALLENGE_60_NO_ANSWERS", "ANSWER_KEY_SEPARATE", "CETA_CONTROLLED_EVALUATION/v1")
        for split, rows in self.splits.items():
            for row in rows:
                with self.subTest(split=split, example=row["example_id"]):
                    self.assertEqual([item["role"] for item in row["messages"]], ["system", "user", "assistant"])
                    json.loads(row["messages"][-1]["content"])
                    serialized = json.dumps(row, sort_keys=True)
                    self.assertFalse(any(token in serialized for token in forbidden))

    def test_derived_language_dataset_is_allowed_but_raw_and_controlled_sources_are_not(self):
        derived = "data/ceta_language_adapter_v1/train.jsonl"
        self.assertEqual(SOURCE_POLICY.validate_training_sources((derived,)), (derived,))
        for path in (
            "data/ceta_architecture_material_v1/training/public_scenarios.jsonl",
            "data/ceta_controlled_evaluation/answer_key.jsonl",
        ):
            with self.subTest(path=path), self.assertRaises(SOURCE_POLICY.TrainingSourceViolation):
                SOURCE_POLICY.validate_training_sources((path,))

    def test_builder_is_byte_deterministic(self):
        examples = LANGUAGE.build_language_adapter_examples(
            ROOT / "data/ceta_architecture_material_v1",
            ROOT / "data/ceta_curriculum_v3",
        )
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            kwargs = {
                "material_manifest_sha256": LANGUAGE.sha256_file(ROOT / "data/ceta_architecture_material_v1/manifest.json"),
                "curriculum_manifest_sha256": LANGUAGE.sha256_file(ROOT / "data/ceta_curriculum_v3/manifest.json"),
            }
            left = LANGUAGE.write_language_adapter_dataset(first, examples, **kwargs)
            right = LANGUAGE.write_language_adapter_dataset(second, examples, **kwargs)
            self.assertEqual(left, right)
            for filename in ("train.jsonl", "validation.jsonl", "heldout.jsonl", "manifest.json"):
                self.assertEqual(
                    (Path(first) / filename).read_bytes(),
                    (Path(second) / filename).read_bytes(),
                )


class ControlledLanguageEvaluationTests(unittest.TestCase):
    def test_inference_program_has_no_answer_key_lookup(self):
        tree = ast.parse((ROOT / "scripts/run_controlled_language_inference.py").read_text(encoding="utf-8"))
        constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        self.assertNotIn("answer_key_path", constants)
        self.assertNotIn("answer_key.jsonl", constants)

    def test_frozen_policy_excludes_only_recorded_exposure(self):
        config = json.loads((ROOT / "configs/ceta-language-adapter-qwen3-4b-h100.json").read_text(encoding="utf-8"))
        self.assertEqual(config["evaluation_policy"]["clean_case_ids_excluded"], ["H001"])
        self.assertFalse(config["evaluation_policy"]["heldout_feedback_to_optimizer"])
        self.assertEqual(config["evaluation_policy"]["promotion_authority"], "INDEPENDENT_EVALUATOR_ONLY")

    def test_reference_metrics_are_deterministic(self):
        self.assertEqual(SCORER.normalized_ruling("Reject And Escalate"), "reject_and_escalate")
        self.assertAlmostEqual(SCORER.token_f1("alpha beta", "alpha gamma"), 0.5)
        self.assertAlmostEqual(SCORER.rouge_l("alpha beta gamma", "alpha gamma"), 0.8)

    def test_near_unique_private_ruling_space_is_reported_without_weakening_gates(self):
        answers = {
            "A": {"ruling": "defer_for_boundary_evidence"},
            "B": {"ruling": "preserve_and_escalate"},
            "C": {"ruling": "deny_unverified_override"},
        }
        profile = SCORER.ruling_label_profile(answers, ["A", "B", "C"])
        self.assertEqual(profile["unique_label_count"], 3)
        self.assertEqual(profile["maximum_label_reuse"], 1)
        self.assertTrue(profile["near_unique_private_label_space"])

    def test_consumed_evaluator_receipt_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = {
                "schema_id": "CETA_LANGUAGE_ADAPTER_H100_CALIBRATION/v1",
                "challenge_sha256": "challenge-hash",
                "answer_key_sha256": "answer-hash",
                "run_date": "2026-08-26",
            }
            Path(root, "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            found = LANGUAGE.consumed_evaluator_receipt(
                Path(root),
                challenge_sha256="challenge-hash",
                answer_key_sha256="answer-hash",
            )
            self.assertEqual(found, {"receipt": "receipt.json", "run_date": "2026-08-26"})
            self.assertIsNone(
                LANGUAGE.consumed_evaluator_receipt(
                    Path(root),
                    challenge_sha256="different",
                    answer_key_sha256="answer-hash",
                )
            )

    def test_h100_training_is_strictly_deterministic_and_uses_current_loading_api(self):
        config = json.loads((ROOT / "configs/ceta-language-adapter-qwen3-4b-h100.json").read_text(encoding="utf-8"))
        contract = TRAINER.determinism_contract(config)
        self.assertEqual(contract["algorithms"], "strict_error")
        self.assertEqual(contract["attention_implementation"], "eager")
        training_source = (ROOT / "scripts/train_language_adapter.py").read_text(encoding="utf-8")
        inference_source = (ROOT / "scripts/run_controlled_language_inference.py").read_text(encoding="utf-8")
        self.assertNotIn("warn_only=True", training_source)
        self.assertNotIn("torch_dtype=", training_source + inference_source)
        self.assertNotIn('attn_implementation="sdpa"', training_source + inference_source)
        launcher = (ROOT / "scripts/run_h100_language_epoch.sh").read_text(encoding="utf-8")
        self.assertIn("--training-only", launcher)
        self.assertIn("no controlled evaluator was opened", launcher)

    def test_torch_security_floor_is_consistent(self):
        requirements = (ROOT / "requirements-training.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("torch==2.13.0", requirements)
        language_requirements = (ROOT / "requirements-language-adapter.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            language_requirements,
            [
                "-r requirements-training.txt",
                "accelerate==1.14.0",
                "bitsandbytes==0.50.1",
                "peft==0.20.0",
                "safetensors==0.8.0",
                "transformers==5.5.0",
            ],
        )
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["optional-dependencies"]["training"], ["torch>=2.13,<2.14"])

    def test_language_environment_bootstrap_is_isolated_and_pinned(self):
        source = (ROOT / "scripts/bootstrap_language_adapter_env.sh").read_text(encoding="utf-8")
        self.assertIn('python_seed="${CETA_BOOTSTRAP_PYTHON:-python3}"', source)
        self.assertIn('-m venv "${venv_root}"', source)
        self.assertIn('"${python_bin}" -m pip check', source)
        self.assertIn('"${1:-}" == "--target"', source)
        self.assertIn('--target "${package_root}"', source)
        self.assertIn('PYTHONPATH="${package_root}"', source)

    def test_deprecated_transformers_cache_variable_is_migrated(self):
        environment = {"TRANSFORMERS_CACHE": "C:/cache/transformers"}
        self.assertTrue(LANGUAGE.normalize_huggingface_cache_environment(environment))
        self.assertEqual(environment, {"HF_HOME": "C:/cache/transformers"})

        environment = {"TRANSFORMERS_CACHE": "C:/legacy", "HF_HOME": "C:/current"}
        self.assertTrue(LANGUAGE.normalize_huggingface_cache_environment(environment))
        self.assertEqual(environment, {"HF_HOME": "C:/current"})

        environment = {}
        self.assertFalse(LANGUAGE.normalize_huggingface_cache_environment(environment))
        self.assertEqual(environment, {})


if __name__ == "__main__":
    unittest.main()
