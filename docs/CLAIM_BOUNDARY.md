# Claim Boundary — v0.3.0

This package is an **epoch-ready reference implementation** of the rebuilt CETA-centered architecture.

"Epoch-ready" has a narrow meaning: under the included abstract curriculum and reference configuration, the system can generate and bind isolated datasets, optimize a structured neural transition policy, durably checkpoint, survive interruption/restart, reconcile uncommitted optimizer tails, independently evaluate validation/held-out behavior, and issue a separate promotion/quarantine decision.

It does not mean the resulting model is good enough to promote. The included strict gate quarantines the recorded smoke checkpoint.

## Neural reasoning claim

The network receives structured epistemic state and ranks proposals from a deterministic target-blind CETA action space. The supervised target is used for loss only; it is not supplied as an inference candidate. The policy API does not accept caller-supplied candidate sets during normal inference.

Manifest-bound validation and held-out evaluation add only the recorded target-free hostile alternatives. This makes exact-target and VM-legal selection competitive metrics instead of accepting singleton generated action spaces as sufficient quality evidence.

For every v3 reference world, the target-blind generator now exposes exactly one VM-legal transition. Structured relation type, belief-creation eligibility, evidence lifecycle, scope, and split preconditions eliminate arbitrary same-state labels; source-context anchors are prohibited from becoming candidates. This is a bounded reference-world property, not a claim that arbitrary future worlds always have one legal next action.

This proves the reference model can be trained and evaluated as a transition-selection system. It does not prove general reasoning, unlimited compositional generalization, superior performance to LLM/neuro-symbolic baselines, or AGI.

## Curriculum claim

The default v3 curriculum is structured and source-bound. It assigns every eligible public human-relations and defensive record to exactly one family-level source group, while operation targets remain explicit VM-governed recipes rather than guessed labels from prose. Parent sections/roles and their derivatives are indivisible source lineages, so neither source groups nor obvious derivative lineages cross train/validation/held-out partitions. Manifest and byte hashes bind the split and source sidecars at training/evaluation time. The unchanged v2 curriculum remains a reproducible baseline.

The current encoder observes source-derived projected CETA topology, not the raw source prose. Operation-derived risk/accuracy fields are not projected into model input. The deterministic source assignments are not described as reviewed semantic adjudications, and the 5,520 VM-authored hostile alternatives are not described as source-authored. This does not prove language understanding, absence of every possible semantic similarity across different families, or real-world performance. Public defensive records used for v3 are trained-on and are not claimed as unseen evaluation.

The controlled 60-case evaluation set is bound and can be staged for independent evaluation without entering public Git or optimizer input. Case `H001` is recorded as previously exposed; only the remaining 59 support a clean unseen claim until that case is replaced.

## Grounding claim

CETA receives normalized structured state and explicit structured exogenous proposal context where information must enter from outside the current state. This architecture makes the grounding boundary explicit; it does not solve the general problem of converting ambiguous language/sensors into correct epistemic objects.

## Formal claim

The included bounded state exploration exhaustively explores only its declared finite abstraction. It is not a theorem-prover proof of the complete Python runtime.

## Production claim

No production HSM/TPM key custody, Byzantine consensus, distributed training control plane, multi-GPU trainer, production external-effect adapter set, or safety-critical certification is claimed. The H100 launcher verifies one already-active H100 and cannot activate hardware.

## Source claim

Verification is local-only. The release performs no remote fetch and depends only on the corpus/evidence embedded in the package plus declared Python dependencies.
