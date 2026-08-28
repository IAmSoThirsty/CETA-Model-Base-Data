from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import sys
import tempfile
import tomllib
import unittest
import warnings
from pathlib import Path

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
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*torch.jit.script_method.*", category=DeprecationWarning)
            from transformers import TrainingArguments

        config = json.loads((ROOT / "configs/ceta-language-adapter-qwen3-4b-h100.json").read_text(encoding="utf-8"))
        contract = TRAINER.determinism_contract(config)
        self.assertEqual(contract["algorithms"], "strict_error")
        self.assertEqual(contract["attention_implementation"], "eager")
        training_source = (ROOT / "scripts/train_language_adapter.py").read_text(encoding="utf-8")
        inference_source = (ROOT / "scripts/run_controlled_language_inference.py").read_text(encoding="utf-8")
        self.assertNotIn("warn_only=True", training_source)
        self.assertNotIn("torch_dtype=", training_source + inference_source)
        self.assertNotIn('attn_implementation="sdpa"', training_source + inference_source)
        argument_names = set(inspect.signature(TrainingArguments).parameters)
        training_arguments = TRAINER.training_arguments_kwargs(
            config,
            Path("checkpoints"),
            int(config["seed"]),
            1928,
        )
        self.assertLessEqual(
            set(training_arguments),
            argument_names,
        )
        self.assertNotIn("warmup_ratio", training_arguments)
        self.assertEqual(training_arguments["warmup_steps"], 4)
        self.assertEqual(TRAINER.expected_optimizer_steps(config, 1928), 121)

    def test_adapter_config_target_modules_are_serialized_in_bound_order(self):
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"]
        with tempfile.TemporaryDirectory() as root:
            config_path = Path(root, "adapter_config.json")
            config_path.write_text(
                json.dumps({"target_modules": list(reversed(target_modules)), "r": 32}),
                encoding="utf-8",
            )
            TRAINER.canonicalize_adapter_config(config_path, target_modules, root=Path(root))
            first = config_path.read_bytes()
            self.assertEqual(json.loads(first)["target_modules"], target_modules)
            TRAINER.canonicalize_adapter_config(config_path, target_modules, root=Path(root))
            self.assertEqual(config_path.read_bytes(), first)

            config_path.write_text(
                json.dumps({"target_modules": ["q_proj", "unexpected"], "r": 32}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "bound training configuration"):
                TRAINER.canonicalize_adapter_config(config_path, target_modules, root=Path(root))

    def test_training_writes_are_confined_to_the_bound_run_root(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            run_root = Path(root)
            inside = run_root / "report.json"
            TRAINER.write_json(inside, {"status": "PASS"}, root=run_root)
            self.assertEqual(json.loads(inside.read_text(encoding="utf-8")), {"status": "PASS"})
            with self.assertRaisesRegex(ValueError, "trusted root"):
                TRAINER.write_json(Path(outside, "escape.json"), {}, root=run_root)

    def test_strict_h100_training_receipt_is_complete_and_fail_closed(self):
        receipt = json.loads(
            (ROOT / "evidence/LANGUAGE_ADAPTER_H100_STRICT_TRAINING.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["schema_id"], "CETA_LANGUAGE_ADAPTER_H100_STRICT_TRAINING/v1")
        self.assertEqual(receipt["global_step"], receipt["expected_optimizer_steps"])
        self.assertEqual(receipt["checkpoint_names"][-1], "checkpoint-121")
        self.assertTrue(receipt["independent_verifier_passed"])
        self.assertFalse(receipt["controlled_evaluation_used_for_training"])
        self.assertFalse(receipt["controlled_evaluation_run"])
        self.assertFalse(receipt["promotion_performed"])
        self.assertEqual(receipt["determinism"]["algorithms"], "strict_error")
        self.assertTrue(receipt["serialized_target_modules_match_bound_order"])
        self.assertTrue(receipt["cross_run_verification"]["model_weights_byte_identical"])
        self.assertEqual(receipt["post_run_studio_machine"], "CPU")
        for key in ("training_report_file_sha256", "training_report_hash"):
            self.assertRegex(receipt[key], r"^sha256:[0-9a-f]{64}$")
        for digest in receipt["adapter_artifacts"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_assistant_collator_requests_legacy_list_shape_explicitly(self):
        class Tokenizer:
            pad_token_id = 0

            def __init__(self):
                self.calls = []

            def apply_chat_template(self, messages, **kwargs):
                self.calls.append(kwargs)
                return [1, 2] if len(messages) == 2 else [1, 2, 3]

        tokenizer = Tokenizer()
        collator = TRAINER.AssistantOnlyCollator(tokenizer, max_length=16, torch_module=None)
        input_ids, labels = collator._encode({"messages": [{}, {}, {}], "example_id": "example"})
        self.assertEqual(input_ids, [1, 2, 3])
        self.assertEqual(labels, [-100, -100, 3])
        self.assertTrue(all(call["return_dict"] is False for call in tokenizer.calls))
        launcher = (ROOT / "scripts/run_h100_language_epoch.sh").read_text(encoding="utf-8")
        self.assertIn("--training-only", launcher)
        self.assertIn("no controlled evaluator was opened", launcher)
        self.assertIn('CETA_PYTHON_NO_SITE', launcher)
        self.assertIn('python_args+=("-S")', launcher)

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
        self.assertEqual(
            set(project["project"]["optional-dependencies"]["language-adapter"]),
            {
                "accelerate==1.14.0",
                "bitsandbytes==0.50.1",
                "numpy==2.4.2",
                "peft==0.20.0",
                "safetensors==0.8.0",
                "transformers==5.5.0",
            },
        )
        self.assertEqual(set(project["dependency-groups"]["ci"]), {"pip-audit==2.10.1", "ruff==0.16.4"})
        self.assertTrue((ROOT / "uv.lock").is_file())

    def test_language_environment_bootstrap_is_isolated_and_pinned(self):
        source = (ROOT / "scripts/bootstrap_language_adapter_env.sh").read_text(encoding="utf-8")
        self.assertIn('python_seed="${CETA_BOOTSTRAP_PYTHON:-python3}"', source)
        self.assertIn('-m venv "${venv_root}"', source)
        self.assertIn('"${python_bin}" -m pip check', source)
        self.assertIn('"${1:-}" == "--target"', source)
        self.assertIn('--target "${package_root}"', source)
        self.assertIn('PYTHONPATH="${package_root}" "${python_seed}" -S', source)

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
