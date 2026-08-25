# Restart and Recovery Contract

A restart may reconstruct state; it may not recreate authority.

- TransitionLedger reload verifies sequence, hashes, VM proof binding, verification binding, replay record, and output-state reconstruction.
- AuthorityLedger reload reconstructs permit states and consumed nonce tombstones from its fsynced event chain.
- A PREPARED permit survives restart only as its exact prepared intent. Resume checks consumer, consumer key, consequence hash, intent hash, and expiry.
- A CONSUMED permit never returns to ISSUED/PREPARED/REVOKED.
- EvidenceRegistry reload verifies every immutable revision and supersession hash.
- IdentityRegistry reload verifies record hashes, revision topology, and every non-declaration assertion against the configured trusted identity-verifier key.
- MemoryProjection is disposable and rebuilt from the projected transition state.

Loss or corruption of required proof material fails closed; recovery does not synthesize missing proof.

## Training restart

Training restart follows the same anti-resurrection principle as operational authority. The append-only training ledger identifies the last `CHECKPOINT_SAVED` event. Mutable pointer files cannot choose an older or different model state.

If optimizer receipts exist after that committed checkpoint because a process died before durable checkpoint completion, the receipts are retained but listed in `RECOVERY_REWIND` as orphaned. Resume reloads the exact committed model/optimizer/cursor and replays from there. Effective optimizer history excludes the explicitly orphaned sequences.

Checkpoint loading verifies bytes, restricted schema/model class, configuration, curriculum binding, cursor, model/optimizer hashes, sidecar, and ledger commitment before training resumes.
