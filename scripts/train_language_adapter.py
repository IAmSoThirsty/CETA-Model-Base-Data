from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = (ROOT / "configs").resolve()
RUNS_ROOT = (ROOT.parent / "ceta-runs").resolve()
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("ceta_language_adapter_training", ROOT / "src/training/language_adapter.py")
assert SPEC is not None and SPEC.loader is not None
LANGUAGE_ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANGUAGE_ADAPTER
SPEC.loader.exec_module(LANGUAGE_ADAPTER)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_hash(value: Any, *, domain: str) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(domain.encode("utf-8") + b"\n" + payload).hexdigest()


def confined_path(path: Path, *, root: Path, must_exist: bool = False) -> Path:
    trusted_root = root.resolve(strict=must_exist)
    candidate = path.resolve(strict=must_exist)
    if candidate == trusted_root or not candidate.is_relative_to(trusted_root):
        raise ValueError(f"path must be a child of the trusted root {trusted_root}: {candidate}")
    if path.is_symlink():
        raise ValueError(f"symbolic-link paths are not permitted: {path}")
    return candidate


def write_json(path: Path, value: Any, *, root: Path) -> None:
    target = confined_path(path, root=root)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def canonicalize_adapter_config(path: Path, target_modules: list[str], *, root: Path) -> None:
    target = confined_path(path, root=root, must_exist=True)
    config = json.loads(target.read_text(encoding="utf-8"))
    saved_modules = config.get("target_modules")
    if not isinstance(saved_modules, list) or sorted(saved_modules) != sorted(target_modules):
        raise RuntimeError("saved adapter target_modules do not match the bound training configuration")
    config["target_modules"] = list(target_modules)
    write_json(target, config, root=root)


def append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def git_identity() -> dict[str, Any]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    if status.strip():
        raise RuntimeError("language-adapter training requires a clean Git worktree")
    return {"commit": commit, "worktree_clean": True}


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): LANGUAGE_ADAPTER.sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def determinism_contract(config: dict[str, Any]) -> dict[str, Any]:
    attention = str(config.get("attention_implementation", ""))
    strict = config.get("strict_determinism") is True
    if not strict:
        raise ValueError("strict_determinism must be true")
    if attention != "eager":
        raise ValueError("strict deterministic training requires eager attention")
    return {
        "algorithms": "strict_error",
        "attention_implementation": attention,
        "cublas_workspace_config": ":4096:8",
        "cudnn_benchmark": False,
        "cudnn_deterministic": True,
        "tf32": False,
    }


def expected_optimizer_steps(config: dict[str, Any], train_size: int) -> int:
    examples_per_step = int(config["per_device_train_batch_size"]) * int(config["gradient_accumulation_steps"])
    return math.ceil(train_size / examples_per_step) * int(config["epochs"])


def training_arguments_kwargs(
    config: dict[str, Any], checkpoint_root: Path, seed: int, train_size: int
) -> dict[str, Any]:
    optimizer_steps = expected_optimizer_steps(config, train_size)
    return {
        "output_dir": str(checkpoint_root),
        "num_train_epochs": float(config["epochs"]),
        "per_device_train_batch_size": int(config["per_device_train_batch_size"]),
        "per_device_eval_batch_size": int(config["per_device_eval_batch_size"]),
        "gradient_accumulation_steps": int(config["gradient_accumulation_steps"]),
        "learning_rate": float(config["learning_rate"]),
        "warmup_steps": math.ceil(optimizer_steps * float(config["warmup_ratio"])),
        "weight_decay": float(config["weight_decay"]),
        "bf16": bool(config["bf16"]),
        "tf32": False,
        "gradient_checkpointing": bool(config["gradient_checkpointing"]),
        "optim": "paged_adamw_8bit",
        "logging_strategy": "steps",
        "logging_steps": int(config["logging_every_steps"]),
        "eval_strategy": "steps",
        "eval_steps": int(config["evaluate_every_steps"]),
        "save_strategy": "steps",
        "save_steps": int(config["checkpoint_every_steps"]),
        "save_total_limit": 4,
        "load_best_model_at_end": False,
        "report_to": [],
        "seed": seed,
        "data_seed": seed,
        "remove_unused_columns": False,
    }


@dataclass
class ChatDataset:
    rows: tuple[dict[str, Any], ...]

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.rows[index]


class AssistantOnlyCollator:
    def __init__(self, tokenizer: Any, *, max_length: int, torch_module: Any) -> None:
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.torch = torch_module
        self.truncated_examples = 0

    def _encode(self, row: dict[str, Any]) -> tuple[list[int], list[int]]:
        messages = row["messages"]
        prompt_ids = self.tokenizer.apply_chat_template(
            messages[:2], tokenize=True, add_generation_prompt=True, return_dict=False
        )
        full_ids = self.tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False, return_dict=False
        )
        if full_ids[: len(prompt_ids)] != prompt_ids:
            common = 0
            for left, right in zip(prompt_ids, full_ids):
                if left != right:
                    break
                common += 1
            if common < max(8, len(prompt_ids) // 2):
                raise RuntimeError(f"chat template prompt is not a prefix for {row['example_id']}")
            prompt_length = common
        else:
            prompt_length = len(prompt_ids)
        if len(full_ids) > self.max_length:
            trim = len(full_ids) - self.max_length
            full_ids = full_ids[trim:]
            prompt_length = max(0, prompt_length - trim)
            self.truncated_examples += 1
        labels = [-100] * prompt_length + full_ids[prompt_length:]
        if not any(value != -100 for value in labels):
            raise RuntimeError(f"assistant response was fully truncated: {row['example_id']}")
        return list(full_ids), labels

    def __call__(self, features: list[dict[str, Any]]) -> dict[str, Any]:
        encoded = [self._encode(feature) for feature in features]
        width = max(len(input_ids) for input_ids, _ in encoded)
        pad = self.tokenizer.pad_token_id
        input_rows: list[list[int]] = []
        label_rows: list[list[int]] = []
        masks: list[list[int]] = []
        for input_ids, labels in encoded:
            padding = width - len(input_ids)
            input_rows.append(input_ids + [pad] * padding)
            label_rows.append(labels + [-100] * padding)
            masks.append([1] * len(input_ids) + [0] * padding)
        return {
            "input_ids": self.torch.tensor(input_rows, dtype=self.torch.long),
            "labels": self.torch.tensor(label_rows, dtype=self.torch.long),
            "attention_mask": self.torch.tensor(masks, dtype=self.torch.long),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the public-only CETA Qwen language adapter on one H100.")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/ceta-language-adapter-qwen3-4b-h100.json")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    config_path = confined_path(args.config, root=CONFIG_ROOT, must_exist=True)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_id") != "CETA_LANGUAGE_ADAPTER_TRAINING/v1":
        raise SystemExit("LANGUAGE ADAPTER TRAINING: FAIL - configuration identity mismatch")
    if config.get("evaluation_policy", {}).get("heldout_feedback_to_optimizer") is not False:
        raise SystemExit("LANGUAGE ADAPTER TRAINING: FAIL - held-out feedback boundary is not fail-closed")
    try:
        deterministic = determinism_contract(config)
    except ValueError as exc:
        raise SystemExit(f"LANGUAGE ADAPTER TRAINING: FAIL - {exc}") from exc
    LANGUAGE_ADAPTER.normalize_huggingface_cache_environment(os.environ)
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = deterministic["cublas_workspace_config"]
    dataset_root = (ROOT / config["dataset_root"]).resolve()
    dataset_manifest, splits = LANGUAGE_ADAPTER.load_verified_language_dataset(dataset_root)
    config_hash = canonical_hash(config, domain="CETA/LANGUAGE_ADAPTER_CONFIG/v1")
    policy_hash = canonical_hash(config["evaluation_policy"], domain="CETA/CONTROLLED_LANGUAGE_EVAL_POLICY/v1")
    git = git_identity()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        Trainer,
        TrainingArguments,
        set_seed,
    )
    from transformers.trainer_utils import get_last_checkpoint

    if os.environ.get("WORLD_SIZE", "1") != "1" or torch.cuda.device_count() != 1:
        raise SystemExit("LANGUAGE ADAPTER TRAINING: FAIL - exactly one visible CUDA device is required")
    if not torch.cuda.is_available():
        raise SystemExit("LANGUAGE ADAPTER TRAINING: FAIL - CUDA is unavailable")
    device_name = torch.cuda.get_device_name(0)
    if "H100" not in device_name.upper():
        raise SystemExit(f"LANGUAGE ADAPTER TRAINING: FAIL - expected H100, got {device_name}")
    if not torch.cuda.is_bf16_supported():
        raise SystemExit("LANGUAGE ADAPTER TRAINING: FAIL - bf16 is unavailable")

    run_root = confined_path(args.run_root, root=RUNS_ROOT)
    binding_path = run_root / "RUN_BINDING.json"
    events_path = run_root / "EVENTS.jsonl"
    if run_root.exists() and not args.resume:
        raise SystemExit(f"LANGUAGE ADAPTER TRAINING: FAIL - run root already exists: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    binding = {
        "schema_id": "CETA_LANGUAGE_ADAPTER_RUN_BINDING/v1",
        "created_at": utc_now(),
        "repo_commit": git["commit"],
        "worktree_clean": True,
        "config_path": config_path.as_posix(),
        "config_sha256": LANGUAGE_ADAPTER.sha256_file(config_path),
        "config_hash": config_hash,
        "evaluation_policy_hash": policy_hash,
        "dataset_root": dataset_root.as_posix(),
        "dataset_manifest_sha256": LANGUAGE_ADAPTER.sha256_file(dataset_root / "manifest.json"),
        "dataset_hash": dataset_manifest["dataset_hash"],
        "base_model": config["base_model"],
        "base_model_revision": config["base_model_revision"],
        "device": device_name,
        "cuda_device_count": torch.cuda.device_count(),
        "determinism": deterministic,
    }
    if binding_path.exists():
        existing = json.loads(binding_path.read_text(encoding="utf-8"))
        immutable = {key: value for key, value in binding.items() if key != "created_at"}
        old_immutable = {key: existing.get(key) for key in immutable}
        if immutable != old_immutable:
            raise SystemExit("LANGUAGE ADAPTER TRAINING: FAIL - resume binding mismatch")
    else:
        write_json(binding_path, binding, root=run_root)
        append_event(events_path, {"event": "RUN_BOUND", "at": utc_now(), "binding_hash": canonical_hash(binding, domain="CETA/LANGUAGE_ADAPTER_RUN_BINDING/v1")})

    seed = int(config["seed"])
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    set_seed(seed)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    if hasattr(torch, "use_deterministic_algorithms"):
        torch.use_deterministic_algorithms(True, warn_only=False)

    tokenizer = AutoTokenizer.from_pretrained(
        config["base_model"], revision=config["base_model_revision"], trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quantization = BitsAndBytesConfig(
        load_in_4bit=bool(config["load_in_4bit"]),
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        revision=config["base_model_revision"],
        trust_remote_code=False,
        dtype=torch.bfloat16,
        quantization_config=quantization,
        device_map={"": 0},
        attn_implementation=deterministic["attention_implementation"],
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=bool(config["gradient_checkpointing"]))
    lora = config["lora"]
    model = get_peft_model(model, LoraConfig(
        r=int(lora["r"]),
        lora_alpha=int(lora["alpha"]),
        lora_dropout=float(lora["dropout"]),
        target_modules=list(lora["target_modules"]),
        task_type="CAUSAL_LM",
        bias="none",
    ))

    checkpoint_root = run_root / "checkpoints"
    collator = AssistantOnlyCollator(tokenizer, max_length=int(config["max_length"]), torch_module=torch)
    training_args = TrainingArguments(
        **training_arguments_kwargs(config, checkpoint_root, seed, len(splits["train"]))
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=ChatDataset(splits["train"]),
        eval_dataset=ChatDataset(splits["validation"]),
        data_collator=collator,
    )
    resume_checkpoint = get_last_checkpoint(str(checkpoint_root)) if args.resume and checkpoint_root.exists() else None
    append_event(events_path, {"event": "TRAINING_STARTED", "at": utc_now(), "resume_checkpoint": resume_checkpoint})
    try:
        train_result = trainer.train(resume_from_checkpoint=resume_checkpoint)
        validation_metrics = trainer.evaluate()
        adapter_root = run_root / "adapter"
        trainer.save_model(str(adapter_root))
        canonicalize_adapter_config(
            adapter_root / "adapter_config.json",
            list(lora["target_modules"]),
            root=run_root,
        )
        tokenizer.save_pretrained(str(adapter_root))
        adapter_files = tree_hashes(adapter_root)
        package_versions = {
            name: importlib.metadata.version(name)
            for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes", "safetensors")
        }
        report_body = {
            "schema_id": "CETA_LANGUAGE_ADAPTER_TRAINING_REPORT/v1",
            "completed_at": utc_now(),
            "run_binding_sha256": LANGUAGE_ADAPTER.sha256_file(binding_path),
            "repo_commit": git["commit"],
            "config_hash": config_hash,
            "evaluation_policy_hash": policy_hash,
            "dataset_hash": dataset_manifest["dataset_hash"],
            "base_model": config["base_model"],
            "base_model_revision": config["base_model_revision"],
            "device": device_name,
            "determinism": deterministic,
            "global_step": int(trainer.state.global_step),
            "expected_optimizer_steps": expected_optimizer_steps(config, len(splits["train"])),
            "train_metrics": train_result.metrics,
            "validation_metrics": validation_metrics,
            "truncated_collation_events": collator.truncated_examples,
            "adapter_files": adapter_files,
            "package_versions": package_versions,
            "controlled_evaluation_used_for_training": False,
            "controlled_evaluation_run": False,
        }
        report = {**report_body, "report_hash": canonical_hash(report_body, domain="CETA/LANGUAGE_ADAPTER_TRAINING_REPORT/v1")}
        write_json(run_root / "TRAINING_REPORT.json", report, root=run_root)
        append_event(events_path, {"event": "TRAINING_COMPLETE", "at": utc_now(), "report_hash": report["report_hash"]})
        (run_root / "TRAINING_COMPLETE").write_text(report["report_hash"] + "\n", encoding="utf-8", newline="\n")
        print(f"CETA LANGUAGE ADAPTER TRAINING: PASS steps={report['global_step']} report={report['report_hash']}")
    except Exception as exc:
        append_event(events_path, {"event": "TRAINING_FAILED", "at": utc_now(), "error_type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
