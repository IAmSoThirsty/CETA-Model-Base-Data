# Canonical Architecture

## Rule

Every fundamental responsibility has one owner. A legacy mechanism may be rewritten beneath that owner, preserved as a test fixture, retained as research evidence, or rejected. No compatibility requirement may create a second owner.

## Data flow

```text
World / User / Tool Output
          |
          v
ObservationCompiler / SecuritySensors
          |
          v
structured Observation candidates
          |
          v
ConstitutionalVM <--- EvidenceRegistry / IdentityRegistry / verified Authority context
          ^
          |
TransitionProposal
          ^
          |
TransitionPolicyModel / DefeaterEngine / TransitionSearch

LEGAL decision
     |
     v
TransitionLedger ----> StateProjector ----> Epistemic State
     |                                      |
     |                                      +--> MemoryProjection
     |
     +--> derived audit/replay views

AUTHORIZED external effect
     |
     v
AuthorityLedger -> EffectGateway -> ToolAdapter
                         |
                         v
                signed execution receipt
                         |
independent observer ----+
         |
         v
EffectVerifier -> EvidenceRegistry -> CETA settlement transition
```

## Three histories that must not be confused

1. **Canonical epistemic history** — `TransitionLedger`. This alone defines `S = projection(T)`.
2. **Operational authority journal** — `AuthorityLedger`. This records single-use permit lifecycle needed to prevent effect-authority resurrection. It does not create beliefs, claims, evidence objects, or other epistemic state directly.
3. **Proof registries** — Evidence and Identity registries. These preserve the exact immutable material that a transition may reference. They do not independently advance epistemic state.

The architecture therefore does not make audit, memory, operational permits, or proof storage a second source of epistemic truth.

## Network boundary

The transition model returns only:

```text
TransitionProposal {
  input_state_ref
  operation
  operands
  proposer_id
}
```

The VM/runtime own legality, state delta, output state, proof, verification, and replay material. A proposal carrying extra VM-owned fields is rejected.

## Effect boundary

The legality engine cannot execute. The authority owner cannot execute. The executor cannot verify its own effect. The effect verifier cannot execute. An adapter cannot be called successfully without a signed gateway invocation. These separations are both registry-level constraints and runtime tests.

## Neural transition-selection boundary

The v0.3.0 reference policy does not receive a label-derived multiple-choice list at inference time.

```text
WorldView
   |
   v
CetaActionSpaceGenerator   (deterministic, target-blind)
   |
   v
structured candidate encodings
   |
   v
NeuralTransitionPolicy
   |
   v
one TransitionProposal
   |
   v
ConstitutionalVM
```

Exogenous structured input that does not yet exist in canonical state is carried in `proposal_context`; the target label is not. The VM remains the only legality authority.

## Governed training path

```text
source-bound curriculum v3
   -> source catalog + deterministic lineage-safe family assignments
   -> family/hash-bound train split
   -> target-blind action space + hostile alternatives
   -> transition losses
   -> optimizer receipt
   -> mandatory durable checkpoint
   -> append-only training ledger
   -> restart/resume from last committed checkpoint
   -> fresh-model validation evaluation
   -> promotion OR quarantine
   -> held-out final evaluation (never promotion authority)
```

A mutable latest-checkpoint pointer is a convenience cache only. Uncheckpointed optimizer work after a crash cannot silently become committed training history.

Additional epochs are represented by a ledger-bound continuation plan with a fixed base checkpoint and final epoch/optimizer-step target. The reference launcher verifies one already-active H100; hardware activation and multi-GPU orchestration remain outside this repository.
