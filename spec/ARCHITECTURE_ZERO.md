# Architecture Zero

This file defines the first clean computational topology. It is a constraint result, not a legacy integration map.

```text
External language / sensors / tools
            |
            v
   Observation Compiler
            |
            v
   Candidate Observations
            |
            v
       Evidence Registry
            |
            v
      State Projector <------------------------------+
            |                                        |
            v                                        |
    Transition Policy Model                          |
      (proposal only)                                |
            |                                        |
            v                                        |
     TransitionProposal                              |
            |                                        |
      +-----+------------------+                     |
      |                        |                     |
      v                        v                     |
Defeater Engine          Transition Search            |
      |                        |                     |
      +-----------+------------+                     |
                  v                                  |
          Constitutional VM                          |
                  |                                  |
        illegal --+-- legal                          |
                  |                                  |
                  v                                  |
            Authority Ledger                         |
                  |                                  |
          [effect requested?]                        |
             |          |                            |
             no         yes                          |
             |          v                            |
             |     Effect Gateway                    |
             |          |                            |
             |     External Reality                  |
             |          |                            |
             |     Effect Verifier                   |
             |          |                            |
             +----------+                            |
                  |                                  |
                  v                                  |
          Committed Transition                       |
                  |                                  |
                  v                                  |
           Transition Ledger ------------------------+
                  |
                  +--> memory/search projections
                  +--> audit/replay projections
                  +--> language serialization
                  +--> training/evaluation evidence
```

## Hard boundary

The network proposal is not the committed transition. The network proposes `input_state_ref + operation + operands`. The VM/runtime computes or verifies the result, proof obligations, verification status and replay record before the ledger can admit a committed transition.

## Legacy policy

Existing modules are not dependencies until an explicit architectural decision assigns their invariant to a canonical responsibility. Compatibility is not a requirement. A source implementation may be ported, rewritten, reduced to a test fixture, or rejected.
