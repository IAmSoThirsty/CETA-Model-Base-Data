# Bounded Model Scope

`scripts/run_bounded_models.py` exhaustively explores the finite reference abstraction of the permit lifecycle used by the CETA effect boundary.

It verifies:

- consumed authority never returns to ISSUED, PREPARED, or REVOKED;
- terminal effect states are reachable only after consumption;
- only INDETERMINATE may reconcile;
- reconciliation cannot create pre-effect authority;
- revocation is pre-effect only;
- one nonce is consumed at most once in the abstract path.

This is bounded state exploration. It is not represented as a complete formal proof of the Python implementation.
