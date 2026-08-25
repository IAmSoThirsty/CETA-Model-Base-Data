# Architecture Rebuild — CETA Epoch-Ready Reference v0.3.0

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

- deterministic CETA curriculum v2 with **690 cases / 230 structural families / 23 operations**;
- family-isolated train/validation/held-out partitions;
- a structured neural transition policy with no language-response target;
- a **target-blind action-space generator**: runtime inference never receives the correct transition or a caller-supplied candidate list;
- structural transition/risk losses;
- governed optimizer lifecycle with mandatory durable checkpoints;
- hash-bound optimizer receipts and checkpoint lineage;
- crash-tail orphaning and deterministic resume from the last committed checkpoint;
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
- `transition_training_system` — curriculum, optimization evidence, checkpointing, independent evaluation, and promotion state.

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

`NeuralTransitionPolicy.propose(world)` accepts no candidate argument. The action-space generator receives only projected state, normalized evidence/identity/authority views, trusted evaluation time, and explicit structured exogenous proposal context. Every one of the 690 curriculum targets is independently recoverable from that target-blind action space.

This reference action space is intentionally bounded. In particular, neural Merge/Split enumeration is restricted to reference RULE topologies even though the VM supports broader same-type semantics. This release does not claim exhaustive general action-space search.

## Curriculum v2

`data/ceta_curriculum_v2/` contains:

- 552 training cases;
- 69 validation cases;
- 69 held-out cases;
- 230 structural world families with three identity-renamed variants each;
- 2,760 explicit hostile alternatives;
- complete 23-operation coverage;
- deterministic family-level partitioning so variants of one family cannot cross splits.

The trainer does not trust filenames. It binds the split bytes, `manifest.json`, `splits.json`, generator ID, case IDs, family IDs, and hashes before optimization. A held-out file renamed to `train.jsonl` is rejected.

## Governed training lifecycle

Normal training cannot disable end-of-call durable checkpointing. The append-only training ledger, not a mutable `latest.json` pointer, determines the last committed checkpoint.

A hard crash after optimizer work but before checkpoint commit preserves those receipts as evidence but marks the uncommitted tail orphaned before deterministic replay. Checkpoint deserialization uses restricted `torch.load(..., weights_only=True)` and verifies schema, model class, dimensions, configuration, curriculum binding, model hash, optimizer hash, sidecar, and ledger commitment.

Evaluation reloads a fresh model and accepts only validation or held-out artifacts cryptographically bound to the same curriculum as the checkpoint. Held-out evidence cannot authorize promotion.

## Epoch-readiness evidence

`evidence/EPOCH_READINESS_REPORT.json` records a complete CPU reference epoch:

- pause after step 173;
- restart/resume to exactly 552 training cases;
- exact training-split optimizer-receipt coverage;
- no validation/held-out optimizer receipts;
- independent validation and held-out evaluation;
- strict promotion decision.

The corrected target-blind run produced:

- validation exact-target accuracy: **0.869565**;
- validation legal-selection rate: **1.0**;
- held-out exact-target accuracy: **0.869565**;
- held-out legal-selection rate: **1.0**;
- strict promotion outcome: **QUARANTINED**.

Those are reference-smoke results, not a production model-quality claim.

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

Install training dependencies, then run from repository root:

```bash
python -m pip install -r requirements-training.txt
python scripts/verify_package.py
python scripts/verify_all.py
```

The verification path is local-only. It performs no remote fetch.

### Supplied architecture and defensive-evaluation material

The provenance-bound human-relations/stewardship corpus and defensive evaluation subset are materialized under `data/ceta_architecture_material_v1/`. They provide 406 lifecycle-section awareness records, 1,624 situational templates, 21 role contracts, 84 role-conditioned cases, 20 public scenarios, five unacceptable-failure lessons, operation-specific risk/equivalence policy, and 200 defensive behaviors.

These records do not silently alter `ceta_curriculum_v2`. They are validated source material for adjudicating a future structured curriculum. Private challenge questions and their answer key remain outside the repository and are hash-bound as evaluation-only material. See `docs/SUPPLIED_DATA_INTEGRATION.md`.

### Lightning H100 handoff

Keep the Studio on CPU while preparing it. After the operator explicitly switches the Studio to an H100, launch the governed epoch with:

```bash
cd ~/CETA-Model-Base-Data
CETA_PYTHON=/teamspace/studios/this_studio/.venvs/ceta-v0.3.0-runtime/bin/python \
  bash scripts/run_h100_epoch.sh
```

The launcher does not select or activate hardware. It fails closed unless CUDA is available and the selected device identifies as an H100. Its default checkpoint ledger, checkpoints, promotion records, and regenerated readiness report are written under `/teamspace/studios/this_studio/ceta-runs/h100-epoch-v0.3.0`, outside the immutable repository package. Supply a new run-root as the first argument for a later governed run; an existing run-root is never overwritten.

## Claim boundary

Read `docs/CLAIM_BOUNDARY.md`. **Epoch-ready** here means the included abstract CETA training pipeline can start, optimize, checkpoint, interrupt, resume, independently evaluate, quarantine/promote, and reproduce its governed evidence under the included reference configuration.

It does **not** mean the smoke checkpoint is promoted, that general reasoning has been demonstrated, that the system is AGI, that real-world language grounding is solved, or that the architecture is certified for production/safety-critical deployment.
