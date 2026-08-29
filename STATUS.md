# Status — v0.3.0 CETA Epoch-Ready Reference

## Proven by this package

- One canonical owner is assigned to each registered fundamental responsibility; duplicate ownership fails validation.
- All **23 CETA opcodes** have executable contracts.
- Proposal components cannot authorize, execute, self-verify effects, or commit canonical state.
- `TransitionLedger` is the sole canonical epistemic history committer; state is reconstructed by projection.
- Epistemic objects are immutable and change through supersession.
- Evidence and identity registries are durable, append-only proof stores rather than competing truth stores.
- Operational permits are exact, expiring, single-use, durable, and anti-resurrection.
- Execute/Rollback reserve authority before canonical effect-transition commit and consume authority before mutation.
- Execution receipts and resulting-reality observations are independently signature-bound.
- Memory remains a rebuildable projection with no canonical memory-write authority.
- Curriculum v3 contains 1,380 VM-validated cases across 460 source-bound structural families and all 23 operations, with 5,520 explicit hostile alternatives.
- All 2,439 eligible public records are bound exactly once: 2,160 human-relations records and 279 defensive records. Parent sections/roles and their derivative records are indivisible source lineages and cannot cross dataset splits.
- The 60 controlled evaluation cases are hash-bound and stageable outside public Git; `H001` is recorded as exposed, leaving 59 currently clean unseen cases.
- Curriculum v2 remains byte-for-byte reproducible as the retained baseline.
- Train/validation/held-out separation is family-level and hash/manifest bound, not filename-trusted.
- The neural policy operates on structured state and a fixed 23-opcode vocabulary; it has no language-response target.
- A separate public-only language-adapter dataset contains all 2,439 eligible source records exactly once across lineage-isolated train/validation/public-held-out splits.
- The language-adapter H100 runner pins Qwen3-4B, records durable checkpoints, and separates answer-blind prediction from frozen-policy answer-key scoring.
- The first live one-H100 language-adapter calibration completed 121/121 optimizer steps at revision `90b170529b89548181aa957e5633629e5cde3f28`; independent verification passed and the controlled evaluator correctly returned `QUARANTINED` without promotion.
- A later strict training-only run completed 121/121 optimizer steps at revision `4de687e73cdefc75ff8bd65717a3dde2529f7cbc`; its model weights were byte-identical to the prior strict run, its adapter metadata was canonicalized in the bound order, and the consumed evaluator was not opened. This run made no promotion decision.
- The live calibration exposed a near-unique private ruling-label space (59 distinct labels across 60 cases). Future reports surface this as an interpretation limitation without weakening the frozen exact-ruling gate.
- Evaluator-consumption receipts now fail closed before paid training and remain a mandatory failing gate if explicitly reused for calibration.
- Language training now requires the security-fixed PyTorch 2.13 and Transformers 5.5 lines plus a strict deterministic H100 contract; warning-only Flash Attention execution is rejected.
- Runtime inference uses a target-blind deterministic action-space generator. `propose(world)` has no caller candidate argument.
- Every curriculum target is recoverable from the target-blind action space without inserting the label into the candidate list.
- Every v3 target is the unique VM-legal transition in its generated action space; source-context anchors never enter that action space.
- Successful training calls always commit a durable checkpoint before returning.
- Optimizer receipts are hash-bound to pre/post model state and optimizer state.
- Resume authority comes from the append-only training ledger's last committed checkpoint, not mutable pointer state.
- Uncheckpointed crash tails are explicitly orphaned before deterministic replay.
- Additional epochs use a fixed, ledger-bound continuation target and remain deterministic across process restarts.
- Checkpoints use restricted weights-only deserialization and verify schema/config/curriculum/model/optimizer/sidecar/ledger bindings.
- Independent evaluation reloads a fresh model and cannot train on validation/held-out partitions.
- Held-out results cannot authorize model promotion.
- Canonical training evidence is filesystem-location independent for identical logical runs.
- A full 1,104-case CPU reference epoch completed across pause/restart/resume with exact training split coverage.
- The corrected target-blind epoch selected VM-legal transitions on 100% of validation and held-out cases in the reference run.
- The current schema-v2 structured smoke checkpoint is correctly `QUARANTINED`; epoch-pipeline readiness is independent of model promotion.
- The integrated hostile epoch gate passes all registered final-gate attacks.

## Current smoke-result boundary

The recorded reference run in `evidence/EPOCH_READINESS_REPORT.json` reports:

- validation exact-target accuracy: 0.913043;
- validation selected-operation accuracy: 0.913043;
- validation legal-selection rate: 0.913043;
- held-out exact-target accuracy: 0.913043;
- held-out selected-operation accuracy: 0.913043;
- held-out legal-selection rate: 0.913043;
- 12 exact-selection errors across 4 structural families per evaluation split;
- promotion status: `QUARANTINED` under the strict reference promotion policy.

These numbers establish only the behavior of this bounded synthetic reference run. Report schema v2 measures the operation of the selected transition, not the separate state-only auxiliary head used by historical schema-v1 checkpoints. Model schema v4 removes that head, derives operation loss from deployed candidate scores, and refuses to resume schema-v3 checkpoints.

## Verified H100 result

A fresh single-H100 schema-v4 run bound to commit `effdf231d0b310b9b2eb511d9e443295f22c1ee8` completed five epochs and 5,520 committed optimizer steps. The gates remained fail-closed throughout:

- epoch 1: 0.913043 validation exact/operation/legal selection, `QUARANTINED`;
- epoch 3: 0.978261, with three errors in `AdmitEvidence/F19`, `QUARANTINED`;
- epoch 5: 1.000000 exact-target, selected-operation, and VM-legal selection, zero errors, `PROMOTED`;
- final independent held-out: 1.000000 exact-target, selected-operation, and VM-legal selection, zero errors;
- optimizer-step count before/after held-out evaluation: 5,520 / 5,520.

Promoted checkpoint: `b095fc3af9cb3fa6d1bc34ba52d13b55d47da5478e8c88ea92fab2f8a27857ff`. All H100 reports are package-tracked under `evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_*.json` and are verified by the normal package gate.

## Not proven / not claimed

- The structurally `QUARANTINED` smoke checkpoint is **not** a production model, deployment approval, or language-adapter promotion.
- General reasoning, compositional generalization at large scale, real-world reasoning, or AGI is not established.
- The structured source-derived curriculum does not itself solve language-to-state grounding or observation truth determination; the separate language adapter is an experimental parsing/serialization layer and cannot establish observation truth.
- Public defensive records used by v3 are trained-on and cannot subsequently support an unseen-benchmark claim.
- The 2026-08-26 controlled evaluator has been consumed for calibration and inspected during diagnosis; it cannot support a new clean-unseen claim for later optimizer or prompt changes.
- The reference action-space generator is bounded and is not claimed exhaustive for arbitrary future CETA states.
- No production-scale model architecture, distributed trainer, multi-GPU path, GPU-specific performance profile, HSM/TPM key custody, or Byzantine consensus is claimed.
- Source assignment is deterministic provenance partitioning, not human semantic source-to-operation adjudication; v3 does not claim that source prose authored its target or hostile alternatives.
- No production filesystem/network/process/device effect-adapter set is certified.
- The Python bounded model exploration is not a theorem-prover proof of the complete runtime.
- The architecture has not been certified for safety-critical deployment.

## Current checkpoint

The package supports governed structural CETA epochs and a separate governed public-language adapter epoch followed by controlled evaluation. Model promotion remains evidence-gated and independent. Real-world grounding, human validation, and production safety remain subsequent stages, not implied by this status.
