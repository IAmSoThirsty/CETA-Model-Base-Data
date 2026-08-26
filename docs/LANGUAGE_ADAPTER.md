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
- PyTorch 2.13.x and Transformers 5.5.x security floors, strict deterministic algorithms, eager attention, disabled TF32, deterministic cuDNN, and a fixed cuBLAS workspace contract;
- one visible H100 and bf16/4-bit LoRA execution;
- dataset, seed, optimizer, checkpoint, and evaluation-policy parameters;
- the exposed-case exclusion and controlled-evaluation thresholds before training begins.

The trainer requires a clean Git revision, records the Git/config/dataset/model/hardware binding, saves durable checkpoints every 25 optimizer steps, supports exact Trainer checkpoint resume, hashes the final adapter, and writes `TRAINING_COMPLETE` only after the final report is durable.

## Controlled evaluation separation

`run_controlled_language_inference.py` verifies only the challenge hash. Its code has no answer-key lookup, and its manifest records `answer_key_accessed: false`. It generates deterministic JSON decisions and durably appends each prediction.

`score_controlled_language_evaluation.py` runs after predictions are frozen. It verifies the training report, frozen policy, inference manifest, prediction hash, answer-key hash, case identities, and `H001` exposure exclusion. It measures parseability, exact normalized ruling, reference token F1, and ROUGE-L on 59 clean cases. It cannot promote a model and does not send scores back to training.

An evaluator whose challenge and answer hashes match a public calibration receipt is permanently classified as consumed. The default validator rejects it before optimization begins, the scorer adds a failing `clean_unseen_benchmark` gate, and the independent verifier rejects any attempted `QUALIFIED` result from it. `--allow-consumed-calibration` permits structural validation only; it does not restore unseen status or promotion eligibility.

When no new clean-unseen evaluator is staged, `run_h100_language_epoch.sh --training-only TRAINING_RUN_ROOT` executes and checkpoints the governed epoch without opening the consumed evaluator. Full train/infer/score mode remains fail-closed until a clean evaluator is supplied.

`verify_language_epoch_report.py` then independently rechecks the completed optimizer-step count, durable checkpoint presence, adapter hashes, answer-blind inference binding, prediction hash, evaluation report hash, gate calculation, and absence of evaluator promotion authority.

These metrics are intentionally bounded. Lexical overlap does not establish full semantic correctness, safety, fitness for use, or human acceptance. The automated decision is `QUALIFIED` or `QUARANTINED`; production promotion requires separate owner-authorized human/domain review.

The scorer also records a non-gating ruling-label profile. If the private evaluator uses a near-unique open vocabulary of answer labels, the report makes that limitation explicit. The exact-ruling gate remains frozen and fail-closed; it is not retroactively weakened after results are seen. A near-unique private label space is calibration evidence, not an ordinary learnable closed-set classification target, unless a label ontology is independently specified before inference.

## Live H100 calibration boundary

The 2026-08-26 run at Git revision `90b170529b89548181aa957e5633629e5cde3f28` completed 121/121 optimizer steps on one NVIDIA H100 80 GB and passed independent artifact verification. The separate controlled evaluator returned `QUARANTINED` on 59 clean cases: parseable response rate 0.559322, exact ruling 0.000000, mean reference token F1 0.220748, and mean ROUGE-L 0.148984. No promotion occurred.

That run also established that the staged answer key contains 59 distinct ruling labels across 60 cases, while answer-blind inference receives no private label list. The result is retained as a calibration receipt in `evidence/LANGUAGE_ADAPTER_H100_CALIBRATION.json`. It does not remain an unseen benchmark after this diagnosis. The current launcher now refuses this consumed evaluator before beginning a paid epoch.

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
