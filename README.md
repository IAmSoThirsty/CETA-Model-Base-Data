# Architecture Rebuild — CETA Epoch-Ready Reference v0.3.0

> **Frozen verification release: `V3.1`**
>
> `V3.1` freezes the verified schema-v4 single-H100 structured-policy result: five completed epochs, 5,520 committed optimizer steps, 100% validation exact-target/selected-operation/VM-legal selection, 100% final independent held-out exact-target/selected-operation/VM-legal selection, zero selection errors, and strict `PROMOTED` status. The promoted checkpoint SHA-256 is `b095fc3af9cb3fa6d1bc34ba52d13b55d47da5478e8c88ea92fab2f8a27857ff`. The separate language-adapter track remains outside this promotion claim.

This repository is a clean rebuild derived from the supplied architecture corpus. Existing systems were treated as evidence, tests, failure history, and design lineage. Their APIs were not preserved as compatibility requirements.

The computational center is **Constitutional Epistemic Transition Algebra (CETA)**:

```text
Epistemic State S_t
        |
        v
Neural Transition Policy
        |
        v
TransitionProposal
        |
        v
ConstitutionalVM
        |
   legal / illegal
        |
        v
TransitionLedger -> StateProjector -> S_t+1
```

The neural boundary proposes only a transition. It does not author output state, proof, verification, replay, authority, or effects.

## What v0.3.0 adds

This release crosses the reference-training boundary that v0.2.0 intentionally did not cross:

- source-bound CETA curriculum v3 with **1,380 cases / 460 structural families / 23 operations**;
- exact-once family binding for **2,439 public human-relations and defensive source records** without placing raw prose in optimizer records;
- family- and source-lineage-isolated train/validation/held-out partitions;
- a structured neural transition policy with no language-response target;
- a separate Qwen3-4B language-adapter track derived from all **2,439 public records**, with the same source-lineage split isolation;
- answer-blind controlled-challenge inference and a separate frozen-policy scoring phase for the 59 clean unseen cases;
- a **target-blind action-space generator**: runtime inference never receives the correct transition or a caller-supplied candidate list;
- structural transition/risk losses;
- governed optimizer lifecycle with mandatory durable checkpoints;
- hash-bound optimizer receipts and checkpoint lineage;
- crash-tail orphaning and deterministic resume from the last committed checkpoint;
- fixed-target, cross-process continuation for one already-active H100, with one durable checkpoint per completed epoch;
- independent checkpoint evaluation;
- separate promotion, quarantine, and rollback decisions;
- curriculum/manifest/checkpoint/evaluation binding across the complete training path;
- a full one-epoch CPU readiness run and a separate hostile epoch gate.

The strict promotion policy **quarantines** the included smoke-run checkpoint. Epoch-pipeline readiness and model-quality promotion are deliberately different claims.

## Canonical ownership

The architecture registry assigns one owner to each fundamental responsibility. Core owners include:

- `ceta_isa` — the 23-operation epistemic instruction set.
- `transition_policy_model` — transition proposal only.
- `constitutional_vm` — transition legality and deterministic state delta.
- `transition_ledger` — sole canonical epistemic history committer.
- `state_projector` — reconstructs current epistemic state from committed transitions.
- `evidence_registry` — append-only provenance/integrity records; does not declare truth.
- `identity_registry` — declarations plus signed identity-status assertions.
- `authority_ledger` — exact, single-use, monotonic operational permits.
- `effect_gateway` — the only side-effect invocation boundary.
- `effect_verifier` — independent signed observation of resulting external reality.
- `memory_projection` — disposable derived search/index view.
- `transition_training_system` — structured and derived-language curricula, optimization evidence, checkpointing, independent evaluation, and promotion state.

Ownership is machine-validated from `registry/responsibilities.json` and `registry/components.json`.

## CETA operation set

All 23 supplied CETA operations are bound to executable contracts:

`Observe`, `ValidateObservation`, `AdmitEvidence`, `RejectEvidence`, `CreateClaim`, `CreateBelief`, `Support`, `Contradict`, `Undercut`, `Merge`, `Split`, `NarrowScope`, `ExpandScope`, `Verify`, `Invalidate`, `Suspend`, `Expire`, `Reevaluate`, `Adjudicate`, `Authorize`, `RejectAuthorization`, `Execute`, `Rollback`.

See `registry/operation_contracts.json`.

## Target-blind neural policy

The training target remains a `TransitionProposal`, but it is used only as the supervised label for loss. It is **not** inserted into the inference candidate set.

At inference time:

```text
WorldView
  -> deterministic CETA action-space generation
  -> structured candidate encoding
  -> neural ranking / opcode / failure heads
  -> selected TransitionProposal
  -> ConstitutionalVM
```

`NeuralTransitionPolicy.propose(world)` accepts no candidate argument. The action-space generator receives only projected state, normalized evidence/identity/authority views, trusted evaluation time, and explicit structured exogenous proposal context. Every one of the 1,380 v3 curriculum targets is independently recoverable from that target-blind action space.

This reference action space is intentionally bounded. In particular, neural Merge/Split enumeration is restricted to reference RULE topologies even though the VM supports broader same-type semantics. This release does not claim exhaustive general action-space search.

## Curriculum v3

`data/ceta_curriculum_v3/` is the default epoch target and contains:

- 1,104 training cases;
- 138 validation cases;
- 138 held-out cases;
- 460 structural world families with three identity-renamed variants each;
- 5,520 explicit hostile alternatives;
- 2,160 public human-relations records and 279 public defensive records bound exactly once across source groups;
- complete 23-operation coverage;
- deterministic family/source-group/source-lineage partitioning so variants, source records, or parent/derivative lineages cannot cross splits.

The trainer does not trust filenames. It binds the split bytes, `manifest.json`, `splits.json`, generator ID, case IDs, family IDs, and the source-catalog/assignment sidecars before optimization. A held-out file renamed to `train.jsonl`, or a changed source sidecar, is rejected. Curriculum v2 remains unchanged under `data/ceta_curriculum_v2/` as a byte-reproducible regression baseline.

The current neural encoder has no language tokenizer. Source records therefore affect v3 through source-derived categorical counts and encoder-visible CETA topology; source IDs and hashes provide provenance only. Operation-risk and accuracy policy remain in non-model sidecars and promotion logic, so target-derived policy is not projected into `WorldView`. The record-to-family mapping is a deterministic provenance assignment, not a claim of human semantic source-to-operation adjudication or prose understanding. The v3 hostile alternatives remain VM-authored structural negatives; they are not claimed as source-authored negatives.

That boundary now applies specifically to the structured transition head. `data/ceta_language_adapter_v1/` provides a separate, deterministic public-prose derivative for a Qwen3-4B LoRA adapter. It contains 1,928 training, 249 validation, and 262 public held-out chat records. Every public source record appears exactly once, and the existing v3 family/source-lineage partition determines its split. The private controlled challenges and answer key never enter these records.

## Governed training lifecycle

Normal training cannot disable end-of-call durable checkpointing. The append-only training ledger, not a mutable `latest.json` pointer, determines the last committed checkpoint.

A hard crash after optimizer work but before checkpoint commit preserves those receipts as evidence but marks the uncommitted tail orphaned before deterministic replay. Checkpoint deserialization uses restricted `torch.load(..., weights_only=True)` and verifies schema, model class, dimensions, configuration, curriculum binding, model hash, optimizer hash, sidecar, and ledger commitment.

Evaluation reloads a fresh model and accepts only validation or held-out artifacts cryptographically bound to the same curriculum as the checkpoint. Held-out evidence cannot authorize promotion. In report schema v2, `target_accuracy` means the exact selected full transition and `opcode_accuracy` means the operation of that same selected transition. The operation-selection objective is computed from the maximum deployed candidate score per operation; there is no separate state-only opcode head.

Additional governed epochs resume only from an exact committed epoch boundary. A continuation plan fixes its base checkpoint, requested epoch count, dataset/config binding, target epoch, and target optimizer step before work begins. A restarted process finishes that same target instead of silently adding another N epochs. The included launcher supports exactly one visible H100; it neither activates hardware nor implements distributed training.

## Epoch-readiness evidence

`evidence/EPOCH_READINESS_REPORT.json` records a complete CPU reference epoch:

- pause after step 173;
- restart/resume to exactly 1,104 training cases;
- exact training-split optimizer-receipt coverage;
- no validation/held-out optimizer receipts;
- independent validation and held-out evaluation;
- strict promotion decision.

The schema-v2 target-blind adversarial CPU reference run produced:

- validation exact-target accuracy: **0.913043**;
- validation selected-operation accuracy: **0.913043**;
- validation legal-selection rate: **0.913043**;
- validation mean transition loss: **0.611091**;
- held-out exact-target accuracy: **0.913043**;
- held-out selected-operation accuracy: **0.913043**;
- held-out legal-selection rate: **0.913043**;
- held-out mean transition loss: **0.611520**;
- **12** exact-selection errors across **4** structural families in each evaluation split, recorded case by case;
- **552** surviving candidates and **552** target-free hostile inputs per evaluation split;
- strict promotion result: **QUARANTINED**.

Earlier schema-v1 reports called a separate state-only auxiliary classifier's result “opcode accuracy,” even though deployed inference selected from candidate scores. Those historical figures are not selected-transition accuracy and must not be compared to schema-v2 `opcode_accuracy`. Model schema v4 rejects those older checkpoints and requires a fresh run.

### Verified schema-v4 H100 run

The governed single-H100 run bound to training-code commit `effdf231d0b310b9b2eb511d9e443295f22c1ee8` completed five full epochs and 5,520 committed optimizer steps:

- epoch 1: 91.3043% validation exact/operation/legal selection, correctly `QUARANTINED`;
- epoch 3: 97.8261%, with three `AdmitEvidence/F19` selections incorrectly choosing `RejectEvidence`, correctly `QUARANTINED`;
- epoch 5: 100% validation exact-target, selected-operation, and VM-legal selection, zero selection errors, mean transition loss 0.0101404, strictly `PROMOTED`;
- final independent held-out: 100% exact-target, selected-operation, and VM-legal selection, zero selection errors, mean transition loss 0.0102312;
- optimizer receipts remained exactly 5,520 before and after final held-out evaluation; held-out results did not authorize promotion and were not fed back to optimization.

The promoted checkpoint SHA-256 is `b095fc3af9cb3fa6d1bc34ba52d13b55d47da5478e8c88ea92fab2f8a27857ff`. The byte-exact reports are:

- [`STRUCTURED_POLICY_H100_SCHEMA_V4_READINESS.json`](evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_READINESS.json) — fresh epoch-1 gate;
- [`STRUCTURED_POLICY_H100_SCHEMA_V4_EPOCH_3.json`](evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_EPOCH_3.json) — checkpoint-bound epoch-3 continuation;
- [`STRUCTURED_POLICY_H100_SCHEMA_V4_EPOCH_5.json`](evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_EPOCH_5.json) — promoted epoch-5 continuation;
- [`STRUCTURED_POLICY_H100_SCHEMA_V4_FINAL_HELDOUT.json`](evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_FINAL_HELDOUT.json) — final independent held-out evaluation.

`scripts/verify_final_heldout_report.py` fails closed on report/hash/lineage disagreement, non-H100 or multi-device evidence, checkpoint mismatch, optimizer feedback, imperfect aggregate or per-operation results, illegal selections, or held-out use during iterative promotion.
- **zero** singleton candidate cases and **zero** ambiguous top-ranked selections;
- strict validation promotion outcome: **PROMOTED**.

Those are reference-smoke results, not a production model-quality claim. Exact-target selection is measured against the generated target plus manifest-bound hostile alternatives, none of which contains the target label. The structured encoder exposes the relation, effect-authority, state-binding, hash-binding, scope, trusted-time, consequence, and split-conservation relationships needed to distinguish those candidates. Tie-order selection is independently counted and cannot pass the package or promotion gate.

`evidence/EPOCH_HOSTILE_GATE_REPORT.json` records the separate integrated hostile gate.

## Authority and effects

Positive authority cannot be supplied as a caller-authored capability dictionary. It is established by a signed, state/operation-bound assertion plus the `AuthorityLedger`'s own permit state.

For `Execute` and `Rollback`:

```text
legal proposal
  -> exact authorization
  -> permit PREPARE before canonical effect-transition commit
  -> signed gateway invocation
  -> permit CONSUME before adapter mutation
  -> signed execution receipt
  -> signed independent observation
  -> independent effect verification
  -> Verify / Invalidate / Suspend settlement transition
```

## Verify

The CI and reproducible local verification path uses the committed `uv.lock`:

```bash
uv sync --locked --no-build --no-install-project --extra training --extra language-adapter --group ci
uv run --no-sync --no-build python -m pip_audit --local --progress-spinner off
uv run --no-sync --no-build ruff check --select F,E9 src scripts tests examples
uv run --no-sync --no-build python scripts/verify_all.py
uv run --no-sync --no-build python scripts/verify_package.py
```

The minimal structured-reference path remains available when language-adapter dependencies are not required:

```bash
python -m pip install -r requirements-training.txt
python scripts/verify_package.py
python scripts/verify_all.py
```

The verification path is local-only. It performs no remote fetch.

### Supplied architecture and defensive-evaluation material

The provenance-bound human-relations/stewardship corpus and defensive evaluation subset are materialized under `data/ceta_architecture_material_v1/`. They provide 406 lifecycle-section awareness records, 1,624 situational templates, 21 role contracts, 84 role-conditioned cases, 20 public scenarios, five unacceptable-failure lessons, operation-specific risk/equivalence policy, and 200 defensive behaviors.

These records drive both the deterministic structured `ceta_curriculum_v3` source catalog and the separately derived `ceta_language_adapter_v1` chat dataset. Raw public files are never passed directly to either optimizer. All materialized public defensive records are accounted as trained-on and therefore are not claimed as unseen benchmarks. The 60 controlled challenge/answer records are cryptographically bound and can be staged through a gitignored evaluator path; they are not discarded or optimizer inputs. Because case `H001` and its answer were previously exposed during inspection, only 59 cases are currently eligible for a clean unseen-evaluation claim. See `docs/SUPPLIED_DATA_INTEGRATION.md` and `docs/LANGUAGE_ADAPTER.md`.

The supplied 23-operation risk policy is enforced now: independent evaluation records per-operation metrics, and governed promotion applies the operation-specific accuracy and zero-illegal-selection requirements in addition to aggregate floors.

## H100 handoff and continuation

The launcher verifies an H100 that the operator has already selected. It does not select, start, resize, or activate Lightning hardware. This reference uses one H100; selecting two or four would add cost without being used because no DDP path is claimed.

```bash
# Fresh governed readiness epoch after the operator activates one H100.
bash scripts/run_h100_epoch.sh /teamspace/studios/this_studio/ceta-runs/curriculum-v3

# Continue exactly two more epochs from the printed committed checkpoint.
bash scripts/run_h100_epoch.sh \
  --additional-epochs 2 \
  --from-checkpoint-sha256 <64-hex-checkpoint-sha256> \
  /teamspace/studios/this_studio/ceta-runs/curriculum-v3

python scripts/verify_epoch_continuation_report.py \
  --report /teamspace/studios/this_studio/ceta-runs/curriculum-v3/EPOCH_CONTINUATION_REPORT.json
```

Continuation evaluates validation and issues a promotion, qualification-without-head-replacement, or quarantine decision. A policy-passing checkpoint is `QUALIFIED` rather than made trusted head when its deterministic validation score does not improve on the current head. It deliberately does not run held-out evaluation during iterative epoch decisions.

### Lightning H100 handoff

Keep the Studio on CPU while preparing it. After the operator explicitly switches the Studio to an H100, launch the governed epoch with:

```bash
cd ~/CETA-Model-Base-Data
CETA_PYTHON=/teamspace/studios/this_studio/.venvs/ceta-v0.3.0-runtime/bin/python \
  bash scripts/run_h100_epoch.sh
```

The launcher does not select or activate hardware. It fails closed unless CUDA is available and the selected device identifies as an H100. Its default checkpoint ledger, checkpoints, promotion records, and regenerated readiness report are written under `/teamspace/studios/this_studio/ceta-runs/h100-epoch-v0.3.0-curriculum-v3`, outside the immutable repository package. Supply a new run-root as the first argument for a later governed run; an existing run-root is never overwritten.

### Governed language-adapter epoch and controlled evaluation

The language track uses the pinned `Qwen/Qwen3-4B-Instruct-2507` revision, trains a LoRA adapter from the derived public dataset, freezes the evaluation policy before training, performs challenge-only inference, and only then opens the separate answer key in the scoring process:

```bash
bash scripts/bootstrap_language_adapter_env.sh --target /teamspace/studios/this_studio/.ceta-packages/language-adapter-REPO_COMMIT
PYTHONPATH=/teamspace/studios/this_studio/.ceta-packages/language-adapter-REPO_COMMIT CETA_PYTHON=python3 CETA_PYTHON_NO_SITE=1 \
bash scripts/run_h100_language_epoch.sh --training-only /teamspace/studios/this_studio/ceta-runs/language-adapter-training
bash scripts/run_h100_language_epoch.sh \
  /teamspace/studios/this_studio/ceta-runs/language-adapter-v1 \
  /teamspace/studios/this_studio/ceta-runs/language-controlled-inference-v1 \
  /teamspace/studios/this_studio/ceta-runs/LANGUAGE_CONTROLLED_EVALUATION_REPORT.json
```

The script requires exactly one already-visible H100. Use `scripts/run_h100_language_epoch.sh --training-only TRAINING_RUN_ROOT` when no new clean-unseen evaluator is staged; this runs the governed optimizer epoch without opening controlled evaluation. A completed epoch is not a promotion: the scorer emits `QUALIFIED` only if every frozen gate passes; otherwise it emits `QUARANTINED`. Token-overlap metrics remain bounded diagnostics and do not replace independent human review.

The first live one-H100 language epoch completed 121/121 optimizer steps and passed artifact verification, then correctly remained `QUARANTINED` under the independent frozen gates. Its scrubbed receipt and interpretation limits are recorded in `evidence/LANGUAGE_ADAPTER_H100_CALIBRATION.json`. The current validator rejects that consumed evaluator before future paid training, and the scorer/verifier prevent it from qualifying a model even when explicitly opened for calibration.

A later strict training-only proof at revision `4de687e73cdefc75ff8bd65717a3dde2529f7cbc` completed 121/121 optimizer steps under the pinned PyTorch 2.13/Transformers 5.5 stack. The independent verifier passed, four durable checkpoints were present, and the final adapter weights were byte-identical to the prior strict run. The adapter configuration is now serialized in its bound target-module order. The consumed evaluator was not opened, so no new evaluation or promotion claim is made. The scrubbed proof is `evidence/LANGUAGE_ADAPTER_H100_STRICT_TRAINING.json`.

## Claim boundary

Read `docs/CLAIM_BOUNDARY.md`. **Epoch-ready** here means the included abstract CETA transition pipeline and public-data-derived language-adapter pipeline have explicit, reproducible data, training, checkpoint, evaluation, quarantine, and evidence paths under their declared configurations.

It does **not** mean the language adapter is promoted, that the structured smoke checkpoint's bounded promotion is production approval, that general reasoning has been demonstrated, that the system is AGI, that unrestricted real-world language grounding is solved, or that the architecture is certified for production/safety-critical deployment.
