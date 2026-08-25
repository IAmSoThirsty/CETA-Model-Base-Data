# Ownership Conflict Map - Initial Pass

The corpus contains repeated implementations of the same fundamental responsibilities. These are not integrated side by side.

| Responsibility | Legacy claimants | Canonical resolution |
|---|---|---|
| Transition legality | AuthoritySurface, RuleGraph, T.A.R.L., Builder policy/kernel | Constitutional VM |
| Authority state | CapabilityBroker, Proof Kernel / Distributed Authority, TAAR registry gate, Builder capability | Authority Ledger |
| Canonical history | Personal Assistant audit, TAAR audit spine, Builder audit, State Register event store | Transition Ledger |
| External effects | Personal Assistant tools, TAAR executor, Builder execution, governed language broker | Effect Gateway |
| Memory | MemoryGraph, conversation stores, embedding indexes | Derived Memory Projection |

The resolution does not mean the legacy implementations are discarded. Their algorithms and tests are evaluated against the canonical owner. A useful mechanism may be ported into the owner; a useful failure becomes a fixture; a conflicting architecture is rejected.
