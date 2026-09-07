"""Offline API/security smoke, not H100 or quantized-training validation."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch
from peft import LoraConfig, PeftModel, get_peft_model
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedTokenizerFast,
    Qwen3Config,
    Trainer,
    TrainerCallback,
    TrainingArguments,
)
from transformers.trainer_utils import get_last_checkpoint

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ceta_language_dependency_training", ROOT / "scripts/train_language_adapter.py"
)
assert SPEC is not None and SPEC.loader is not None
TRAINING = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TRAINING
SPEC.loader.exec_module(TRAINING)

CHAT_TEMPLATE = (
    "{% for message in messages %}"
    "{{ message['role'] + ': ' + message['content'] + ' ' }}"
    "{% if message['role'] == 'assistant' %}{{ eos_token + ' ' }}{% endif %}"
    "{% endfor %}"
    "{% if add_generation_prompt %}{{ 'assistant: ' }}{% endif %}"
)


def synthetic_tokenizer():
    """Build a tiny vocabulary locally without any pretrained assets."""
    words = [
        "[PAD]",
        "[UNK]",
        "[EOS]",
        "system",
        "user",
        "assistant",
        ":",
        "test",
        "hello",
        "answer",
    ]
    backend = Tokenizer(
        WordLevel({word: index for index, word in enumerate(words)}, unk_token="[UNK]")
    )
    backend.pre_tokenizer = Whitespace()
    return PreTrainedTokenizerFast(
        tokenizer_object=backend,
        pad_token="[PAD]",
        unk_token="[UNK]",
        eos_token="[EOS]",
        chat_template=CHAT_TEMPLATE,
        model_max_length=64,
    )


class StopAfterFirstStep(TrainerCallback):
    """Stop at a durable checkpoint without changing the planned schedule."""

    def on_step_end(self, args, state, control, **kwargs):
        """Request a graceful stop after the first optimizer update."""
        if state.global_step == 1:
            control.should_training_stop = True
        return control


class LanguageDependencyCompatibilityTests(unittest.TestCase):
    """Exercise CETA's training APIs and tokenizer write boundary offline."""

    def setUp(self):
        self.directory = Path(
            self.enterContext(tempfile.TemporaryDirectory(prefix="ceta-language-compatibility-"))
        )
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "HF_HOME": str(self.directory / "hf"),
                    "HF_HUB_CACHE": str(self.directory / "hf" / "hub"),
                    "HF_HUB_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                    "TOKENIZERS_PARALLELISM": "false",
                },
            )
        )
        for target in (
            "socket.create_connection",
            "socket.socket.connect",
            "socket.socket.connect_ex",
        ):
            self.enterContext(
                patch(target, side_effect=AssertionError("Compatibility tests must remain offline"))
            )
        self.enterContext(torch.random.fork_rng(devices=[]))
        self.addCleanup(random.setstate, random.getstate())
        self.addCleanup(np.random.set_state, np.random.get_state())
        thread_count = torch.get_num_threads()
        torch.set_num_threads(1)
        self.addCleanup(torch.set_num_threads, thread_count)
        torch.manual_seed(417)

    def _write_tiny_base(self, tokenizer, target_modules):
        """Save synthetic base weights with the production projection names."""
        configuration = Qwen3Config(
            vocab_size=len(tokenizer),
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=4,
            num_key_value_heads=2,
            head_dim=8,
            max_position_embeddings=64,
            use_cache=False,
            bos_token_id=None,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
        )
        base_directory = self.directory / "base"
        base = AutoModelForCausalLM.from_config(configuration, attn_implementation="eager")
        self.assertTrue(
            set(target_modules).issubset(
                {name.rsplit(".", 1)[-1] for name, _ in base.named_modules()}
            )
        )
        base.save_pretrained(base_directory, safe_serialization=True)

    def _load_base(self):
        """Exercise the local-only form of the production model-loading API."""
        return AutoModelForCausalLM.from_pretrained(
            self.directory / "base",
            local_files_only=True,
            trust_remote_code=False,
            dtype=torch.float32,
            attn_implementation="eager",
        )

    def _load_trainable(self, target_modules):
        """Attach a small deterministic adapter to the same base weights."""
        return get_peft_model(
            self._load_base(),
            LoraConfig(
                r=2,
                lora_alpha=4,
                lora_dropout=0.0,
                target_modules=target_modules,
                task_type="CAUSAL_LM",
                bias="none",
            ),
        )

    def _synthetic_data(self, tokenizer):
        """Cover masked prompts, padding and an entirely truncated prompt."""
        rows = tuple(
            {
                "example_id": f"synthetic-{index}",
                "messages": [
                    {"role": "system", "content": "test"},
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": answer},
                ],
            }
            for index, answer in enumerate(("answer", "answer " * 40))
        )
        collator = TRAINING.AssistantOnlyCollator(tokenizer, max_length=24, torch_module=torch)
        batch = collator(list(rows))
        self.assertEqual(tuple(batch["input_ids"].shape), (2, 24))
        self.assertEqual(batch["labels"][0, 0].item(), -100)
        self.assertNotEqual(batch["labels"][1, 0].item(), -100)
        self.assertTrue(torch.all(batch["labels"][batch["attention_mask"] == 0] == -100))
        self.assertGreater(collator.truncated_examples, 0)
        return TRAINING.ChatDataset(rows), collator

    def _arguments(self, bound_config):
        """Adapt the real argument builder for a two-step CPU-only smoke."""
        cpu_config = {
            **bound_config,
            "bf16": False,
            "gradient_checkpointing": False,
            "per_device_train_batch_size": 2,
            "per_device_eval_batch_size": 2,
            "gradient_accumulation_steps": 1,
            "checkpoint_every_steps": 1,
            "evaluate_every_steps": 1,
            "logging_every_steps": 1,
            "warmup_ratio": 0.0,
        }
        checkpoint_directory = self.directory / "checkpoints"

        kwargs = TRAINING.training_arguments_kwargs(cpu_config, checkpoint_directory, 417, 2)
        # CPU-only smoke overrides; the production H100 contract stays unchanged.
        kwargs.update(
            max_steps=2,
            use_cpu=True,
            optim="adamw_torch",
            disable_tqdm=True,
            dataloader_pin_memory=False,
            learning_rate=0.01,
        )
        return TrainingArguments(**kwargs)

    def _checkpoint_and_resume(self, bound_config, dataset, collator, target_modules):
        """Require optimizer work, durable checkpoint recovery and finite loss."""
        model = self._load_trainable(target_modules)
        before = {
            name: parameter.detach().clone()
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
        }
        trainer = Trainer(
            model=model,
            args=self._arguments(bound_config),
            train_dataset=dataset,
            eval_dataset=dataset,
            data_collator=collator,
            callbacks=[StopAfterFirstStep()],
        )
        first = trainer.train()
        self.assertEqual(trainer.state.global_step, 1)
        self.assertTrue(math.isfinite(first.training_loss))
        self.assertTrue(
            any(
                not torch.equal(before[name], parameter)
                for name, parameter in model.named_parameters()
                if name in before
            )
        )
        checkpoint = get_last_checkpoint(str(self.directory / "checkpoints"))
        self.assertIsNotNone(checkpoint)
        self.assertEqual(Path(checkpoint).name, "checkpoint-1")
        self.assertTrue((Path(checkpoint) / "optimizer.pt").is_file())

        resumed = Trainer(
            model=self._load_trainable(target_modules),
            args=self._arguments(bound_config),
            train_dataset=dataset,
            eval_dataset=dataset,
            data_collator=collator,
        )
        second = resumed.train(resume_from_checkpoint=checkpoint)
        self.assertEqual(resumed.state.global_step, 2)
        self.assertTrue(math.isfinite(second.training_loss))
        self.assertTrue(math.isfinite(resumed.evaluate()["eval_loss"]))
        self.assertTrue(
            all(torch.isfinite(parameter).all() for parameter in resumed.model.parameters())
        )
        return resumed

    def _assert_adapter_roundtrip(self, resumed, target_modules, tokenizer, dataset):
        """Save and reload both adapter and tokenizer through real public APIs."""
        adapter_directory = self.directory / "adapter"
        resumed.save_model(str(adapter_directory))
        TRAINING.canonicalize_adapter_config(
            adapter_directory / "adapter_config.json", target_modules, root=self.directory
        )
        tokenizer.save_pretrained(adapter_directory)
        reloaded_tokenizer = AutoTokenizer.from_pretrained(
            adapter_directory, local_files_only=True, trust_remote_code=False
        )
        self.assertEqual(reloaded_tokenizer.chat_template, tokenizer.chat_template)
        self.assertEqual(reloaded_tokenizer.get_vocab(), tokenizer.get_vocab())
        reloaded_model = PeftModel.from_pretrained(
            self._load_base(), adapter_directory, is_trainable=False, local_files_only=True
        )
        self._assert_generation(resumed.model, reloaded_model, reloaded_tokenizer, dataset.rows[0])

    def _assert_generation(self, trained_model, reloaded_model, tokenizer, row):
        """Require identical bounded greedy output before and after reloading."""
        inputs = tokenizer.apply_chat_template(
            row["messages"][:2],
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to("cpu")
        generation = deepcopy(reloaded_model.generation_config)
        generation.do_sample = False
        generation.temperature = generation.top_p = generation.top_k = None
        generation.max_new_tokens = 3
        generation.pad_token_id = tokenizer.pad_token_id
        generation.eos_token_id = tokenizer.eos_token_id
        reloaded_model.eval()
        trained_model.eval()
        with torch.no_grad():
            expected = trained_model.generate(**inputs, generation_config=generation)
            actual = reloaded_model.generate(**inputs, generation_config=generation)
        self.assertTrue(torch.equal(actual, expected))
        generated_count = actual.shape[-1] - inputs["input_ids"].shape[-1]
        self.assertGreater(generated_count, 0)
        self.assertLessEqual(generated_count, 3)

    def test_tiny_qwen_lora_checkpoint_resume_and_local_reload(self):
        """Train, resume, save and reload a tiny local Qwen3 LoRA adapter."""
        bound_config = json.loads(
            (ROOT / "configs/ceta-language-adapter-qwen3-4b-h100.json").read_text(encoding="utf-8")
        )
        target_modules = bound_config["lora"]["target_modules"]
        tokenizer = synthetic_tokenizer()
        self._write_tiny_base(tokenizer, target_modules)
        dataset, collator = self._synthetic_data(tokenizer)
        resumed = self._checkpoint_and_resume(bound_config, dataset, collator, target_modules)
        self._assert_adapter_roundtrip(resumed, target_modules, tokenizer, dataset)

    def test_named_chat_template_save_rejects_escape_without_touching_canary(self):
        """Reject untrusted template paths while retaining valid named templates."""
        tokenizer = synthetic_tokenizer()
        tokenizer.chat_template = {"default": CHAT_TEMPLATE, "tool": CHAT_TEMPLATE}
        valid_directory = self.directory / "valid"
        tokenizer.save_pretrained(valid_directory)
        restored = AutoTokenizer.from_pretrained(
            valid_directory, local_files_only=True, trust_remote_code=False
        )
        self.assertEqual(restored.chat_template, tokenizer.chat_template)

        canary = self.directory / "canary.jinja"
        canary.write_bytes(b"CETA TEST ONLY: preserve this existing outside file\n")
        original = canary.read_bytes()
        names = ["../../canary", str(self.directory / "canary")]
        if os.name == "nt":
            names.append("..\\..\\canary")
        for index, name in enumerate(names):
            with self.subTest(template_name=name):
                tokenizer.chat_template = {
                    "default": CHAT_TEMPLATE,
                    name: "CETA TEST ONLY replacement",
                }
                with self.assertRaisesRegex(ValueError, "Invalid chat template name"):
                    tokenizer.save_pretrained(self.directory / f"rejected-{index}")
                self.assertEqual(canary.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
