# CETA Training Boundary — v0.3.0

The reasoner is trained to select structured transitions, not generate language.

## Input

A `WorldView` contains only the structured material needed by the transition substrate:

- projected epistemic state;
- normalized evidence view;
- normalized identity view;
- normalized authority conditions;
- trusted evaluation time when temporal logic requires it;
- explicit structured exogenous proposal context for material that does not yet exist in canonical state.

Exogenous proposal context is input, not a hidden target channel. Examples include a new observation payload awaiting `Observe`, claim material awaiting `CreateClaim`, or an external authorization request awaiting adjudication.

Operational secrets, signatures, live permit internals, governance histories, evaluator outputs, controlled evaluation answers, verification artifacts, and source archives are separate from optimizer inputs. Public human-relations and defensive records may drive deterministic structured derivation; the raw source files are not direct optimizer datasets. Controlled evaluation is integrated through a hash-verified evaluator staging path rather than discarded.

## Target

```text
TransitionProposal {
  input_state_ref,
  operation,
  operands,
  proposer_id
}
```

The target is a supervised loss label. It is never inserted into the normal inference candidate list.

## Target-blind action space

`CetaActionSpaceGenerator.generate(world)` receives no target. It deterministically enumerates structured candidate transitions from the current `WorldView`. `NeuralTransitionPolicy.propose(world)` accepts no candidate parameter and ranks only that generated action space.

Training and manifest-bound evaluation append explicit hostile alternatives to the generated action space to test failure discrimination. `candidate_sequence(case)` contains only those adversarial alternatives and never the target. Normal runtime `propose(world)` remains caller-candidate-free and ranks only the target-blind generated action space.

## Loss

Loss is structural:

- opcode classification;
- correct-transition ranking within the target-blind action space;
- failure-surface prediction for illegal transition, missing transition, invariant violation, provenance loss, missing defeaters, improper scope, illegal authorization, belief corruption, and replay mismatch.

Non-target candidates are not automatically labeled illegal. The Constitutional VM evaluates them; a legal but non-target transition is treated as a missing/correct-choice error rather than falsely declared constitutionally illegal.

## Split isolation

Training accepts only the manifest-bound training split. The trainer verifies all three split artifacts, generator identity, family/case assignments, and hashes before optimization. Validation/held-out data cannot enter the optimizer by renaming a file.

Curriculum v3 also binds `source_catalog.json` and `source_assignments.jsonl`. Every eligible public source record belongs to exactly one source group, every source group belongs to exactly one structural family, and parent/derivative source lineages are indivisible. The family-level split therefore keeps both source groups and source lineages in one partition. Public defensive records used in this derivation are explicitly marked trained-on and are no longer eligible for an unseen-benchmark claim.

Only categorical/hash metadata is retained as provenance inside the curriculum. Source-derived context counts are projected into encoder-visible object status, scope cardinality, and topology. Operation-risk/accuracy policy is kept out of `WorldView` and used only in sidecars/promotion. The encoder does not tokenize or learn opaque source strings.

The evaluator independently reloads a checkpoint and accepts only manifest-bound validation or held-out artifacts from that same curriculum. It records hostile and surviving candidate counts and fails the package gate if evaluation collapses to singleton candidate sets. Held-out evaluation cannot authorize promotion.

## Checkpoint law

A successful `train_cases()` call always durably checkpoints before returning. There is no public `checkpoint_at_end=False` path.

The append-only training ledger is authoritative for resume. A mutable convenience pointer cannot select an older checkpoint. If a crash leaves optimizer receipts after the last committed checkpoint, those receipts remain in evidence but are explicitly orphaned before deterministic replay.

Checkpoint loading uses restricted weights-only deserialization and verifies checkpoint bytes, sidecar, schema/model class, dimensions, configuration, curriculum binding, cursor, model state hash, optimizer state hash, and committed ledger record.

Additional epochs require an exact committed epoch boundary. The append-only ledger records a fixed continuation plan before optimization, including its base checkpoint and target epoch/step. A new process resumes that plan deterministically. The supplied H100 launcher requires exactly one already-visible H100, rejects distributed/multi-device execution, and never activates hardware.

## Promotion law

Epoch completion is not model approval. Independent validation metrics are evaluated against a separate promotion policy. Failed checkpoints are quarantined. Held-out results are reserved for final evaluation and cannot promote a checkpoint.
