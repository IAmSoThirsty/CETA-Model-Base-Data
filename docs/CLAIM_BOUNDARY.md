# Claim Boundary — v0.3.0

This package is an **epoch-ready reference implementation** of the rebuilt CETA-centered architecture.

"Epoch-ready" has a narrow meaning: under the included abstract curriculum and reference configuration, the system can generate and bind isolated datasets, optimize a structured neural transition policy, durably checkpoint, survive interruption/restart, reconcile uncommitted optimizer tails, independently evaluate validation/held-out behavior, and issue a separate promotion/quarantine decision.

It does not mean the resulting model is good enough to promote. The included strict gate quarantines the recorded smoke checkpoint.

## Neural reasoning claim

The network receives structured epistemic state and ranks proposals from a deterministic target-blind CETA action space. The supervised target is used for loss only; it is not supplied as an inference candidate. The policy API does not accept caller-supplied candidate sets during normal inference.

Manifest-bound validation and held-out evaluation add only the recorded target-free hostile alternatives. This makes exact-target and VM-legal selection competitive metrics instead of accepting singleton generated action spaces as sufficient quality evidence. A target chosen only because it appears first in a tied score set is recorded as ambiguous and cannot pass promotion or the package evidence gate.

For every v3 reference world, the target-blind generator now exposes exactly one VM-legal transition. Structured relation type, belief-creation eligibility, evidence lifecycle, scope, and split preconditions eliminate arbitrary same-state labels; source-context anchors are prohibited from becoming candidates. This is a bounded reference-world property, not a claim that arbitrary future worlds always have one legal next action.

This proves the reference model can be trained and evaluated as a transition-selection system. It does not prove general reasoning, unlimited compositional generalization, superior performance to LLM/neuro-symbolic baselines, or AGI.

## Curriculum claim

The default v3 curriculum is structured and source-bound. It assigns every eligible public human-relations and defensive record to exactly one family-level source group, while operation targets remain explicit VM-governed recipes rather than guessed labels from prose. Parent sections/roles and their derivatives are indivisible source lineages, so neither source groups nor obvious derivative lineages cross train/validation/held-out partitions. Manifest and byte hashes bind the split and source sidecars at training/evaluation time. The unchanged v2 curriculum remains a reproducible baseline.

The current encoder observes source-derived projected CETA topology, not the raw source prose. Operation-derived risk/accuracy fields are not projected into model input. The deterministic source assignments are not described as reviewed semantic adjudications, and the 5,520 VM-authored hostile alternatives are not described as source-authored. This does not prove language understanding, absence of every possible semantic similarity across different families, or real-world performance. Public defensive records used for v3 are trained-on and are not claimed as unseen evaluation.

The controlled 60-case evaluation set is bound and can be staged for independent evaluation without entering public Git or optimizer input. Case `H001` is recorded as previously exposed; only the remaining 59 support a clean unseen claim until that case is replaced.

## Language-adapter claim

The repository now includes a separate language-adapter training and controlled-evaluation path. Its 2,439 chat examples are deterministic derivatives of public material only, and their source lineages remain isolated across train/validation/public-held-out splits. The pinned Qwen3-4B adapter is outside the structural transition head: it may parse or serialize governed judgments, but the Constitutional VM remains the transition-legality authority.

Controlled inference is answer-blind and produces frozen predictions before a different scoring process opens the answer key. The declared lexical metrics measure exact ruling and reference overlap only. They do not prove complete semantic equivalence, language understanding across unsupported populations, alignment, safety, or human acceptance. Passing the automated policy can produce `QUALIFIED`, not deployment promotion; failure produces `QUARANTINED`.

## Grounding claim

CETA receives normalized structured state and explicit structured exogenous proposal context where information must enter from outside the current state. The language adapter adds a governed language-processing experiment and controlled benchmark path; it does not solve the general problem of converting arbitrary ambiguous language or sensors into truthful epistemic objects.

## Formal claim

The included bounded state exploration exhaustively explores only its declared finite abstraction. It is not a theorem-prover proof of the complete Python runtime.

## Production claim

No production HSM/TPM key custody, Byzantine consensus, distributed training control plane, multi-GPU trainer, production external-effect adapter set, or safety-critical certification is claimed. The H100 launcher verifies one already-active H100 and cannot activate hardware.

## Source claim

Core package verification is local-only. Language-adapter execution additionally fetches the exact pinned base-model revision unless it is already cached; the run binding records that revision and all resulting adapter hashes.
