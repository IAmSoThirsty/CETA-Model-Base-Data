# Governed CETA language adapter

## Objective

Provide the missing language boundary around the structured CETA transition engine without giving prose, an LLM, or an evaluator authority over Constitutional VM legality.

## Data flow

```text
2,439 public source records
  -> deterministic chat derivation
  -> lineage-bound train / validation / public-held-out splits
  -> pinned Qwen3-4B LoRA epoch
  -> frozen adapter
  -> challenge-only controlled inference
  -> durable prediction artifact
  -> separate answer-key scoring
  -> QUALIFIED or QUARANTINED evidence
```

`data/ceta_language_adapter_v1/` contains 1,928 training, 249 validation, and 262 public-held-out examples. The public source catalog, source assignments, and `ceta_curriculum_v3` family splits determine identity and partition. All 2,439 public records are represented exactly once; parent section/role derivatives remain in one split.

The raw public files are derivation sources, not optimizer inputs. The optimizer accepts only the derived language dataset. `data/ceta_controlled_evaluation/**`, archive-private-holdout paths, challenges, answers, evaluator outputs, and verification artifacts are rejected by the source policy.

## Training binding

`configs/ceta-language-adapter-qwen3-4b-h100.json` pins:

- `Qwen/Qwen3-4B-Instruct-2507` revision `cdbee75f17c01a7cc42f958dc650907174af0554`;
- one visible H100 and bf16/4-bit LoRA execution;
- dataset, seed, optimizer, checkpoint, and evaluation-policy parameters;
- the exposed-case exclusion and controlled-evaluation thresholds before training begins.

The trainer requires a clean Git revision, records the Git/config/dataset/model/hardware binding, saves durable checkpoints every 25 optimizer steps, supports exact Trainer checkpoint resume, hashes the final adapter, and writes `TRAINING_COMPLETE` only after the final report is durable.

## Controlled evaluation separation

`run_controlled_language_inference.py` verifies only the challenge hash. Its code has no answer-key lookup, and its manifest records `answer_key_accessed: false`. It generates deterministic JSON decisions and durably appends each prediction.

`score_controlled_language_evaluation.py` runs after predictions are frozen. It verifies the training report, frozen policy, inference manifest, prediction hash, answer-key hash, case identities, and `H001` exposure exclusion. It measures parseability, exact normalized ruling, reference token F1, and ROUGE-L on 59 clean cases. It cannot promote a model and does not send scores back to training.

`verify_language_epoch_report.py` then independently rechecks the completed optimizer-step count, durable checkpoint presence, adapter hashes, answer-blind inference binding, prediction hash, evaluation report hash, gate calculation, and absence of evaluator promotion authority.

These metrics are intentionally bounded. Lexical overlap does not establish full semantic correctness, safety, fitness for use, or human acceptance. The automated decision is `QUALIFIED` or `QUARANTINED`; production promotion requires separate owner-authorized human/domain review.

## Commands

```bash
python scripts/build_language_adapter_dataset.py
python scripts/validate_language_adapter_dataset.py
python -m pip install -r requirements-language-adapter.txt

bash scripts/run_h100_language_epoch.sh \
  /teamspace/studios/this_studio/ceta-runs/language-adapter-v1 \
  /teamspace/studios/this_studio/ceta-runs/language-controlled-inference-v1 \
  /teamspace/studios/this_studio/ceta-runs/LANGUAGE_CONTROLLED_EVALUATION_REPORT.json
```

The H100 launcher never overwrites an existing run, inference directory, or report. On interruption, resume the training process explicitly with `train_language_adapter.py --resume --run-root ...`; do not create a second run identity for the same bound run.
