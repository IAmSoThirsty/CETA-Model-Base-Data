# Claim Boundary — v0.3.0

This package is an **epoch-ready reference implementation** of the rebuilt CETA-centered architecture.

"Epoch-ready" has a narrow meaning: under the included abstract curriculum and reference configuration, the system can generate and bind isolated datasets, optimize a structured neural transition policy, durably checkpoint, survive interruption/restart, reconcile uncommitted optimizer tails, independently evaluate validation/held-out behavior, and issue a separate promotion/quarantine decision.

It does not mean the resulting model is good enough to promote. The included strict gate quarantines the recorded smoke checkpoint.

## Neural reasoning claim

The network receives structured epistemic state and ranks proposals from a deterministic target-blind CETA action space. The supervised target is used for loss only; it is not supplied as an inference candidate. The policy API does not accept caller-supplied candidate sets during normal inference.

This proves the reference model can be trained and evaluated as a transition-selection system. It does not prove general reasoning, unlimited compositional generalization, superior performance to LLM/neuro-symbolic baselines, or AGI.

## Curriculum claim

The included v2 curriculum is synthetic and abstract. Family-level split isolation prevents identity-renamed variants of one structural family from crossing train/validation/held-out partitions. Manifest and byte hashes bind the split at training/evaluation time.

This does not prove absence of every possible semantic similarity across different families, nor does synthetic performance establish real-world performance.

## Grounding claim

CETA receives normalized structured state and explicit structured exogenous proposal context where information must enter from outside the current state. This architecture makes the grounding boundary explicit; it does not solve the general problem of converting ambiguous language/sensors into correct epistemic objects.

## Formal claim

The included bounded state exploration exhaustively explores only its declared finite abstraction. It is not a theorem-prover proof of the complete Python runtime.

## Production claim

No production HSM/TPM key custody, Byzantine consensus, distributed training control plane, production external-effect adapter set, or safety-critical certification is claimed.

## Source claim

Verification is local-only. The release performs no remote fetch and depends only on the corpus/evidence embedded in the package plus declared Python dependencies.
