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
- Strict model promotion correctly quarantined the smoke checkpoint rather than conflating epoch completion with model quality.
- The integrated hostile epoch gate passes all registered final-gate attacks.

## Current smoke-result boundary

The recorded reference run in `evidence/EPOCH_READINESS_REPORT.json` reports:

- validation exact-target accuracy: 1.000000;
- validation opcode accuracy: 0.782609;
- validation legal-selection rate: 1.000000;
- held-out exact-target accuracy: 1.000000;
- held-out opcode accuracy: 0.739130;
- held-out legal-selection rate: 1.000000;
- promotion status: `QUARANTINED` under the strict reference promotion policy.

These numbers establish only the behavior of this bounded synthetic reference run.

## Not proven / not claimed

- The quarantined smoke checkpoint is **not** a promoted model.
- General reasoning, compositional generalization at large scale, real-world reasoning, or AGI is not established.
- The structured source-derived curriculum does not solve language-to-state grounding or observation truth determination; the current encoder does not tokenize source prose.
- Public defensive records used by v3 are trained-on and cannot subsequently support an unseen-benchmark claim.
- The reference action-space generator is bounded and is not claimed exhaustive for arbitrary future CETA states.
- No production-scale model architecture, distributed trainer, multi-GPU path, GPU-specific performance profile, HSM/TPM key custody, or Byzantine consensus is claimed.
- Source assignment is deterministic provenance partitioning, not human semantic source-to-operation adjudication; v3 does not claim that source prose authored its target or hostile alternatives.
- No production filesystem/network/process/device effect-adapter set is certified.
- The Python bounded model exploration is not a theorem-prover proof of the complete runtime.
- The architecture has not been certified for safety-critical deployment.

## Current checkpoint

The package is ready for the **first governed CETA training experiments over its abstract curriculum**. Model promotion remains evidence-gated and independent. Real-world grounding and stronger out-of-distribution evaluation are subsequent research stages, not implied by this status.
