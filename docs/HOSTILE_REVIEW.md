# Hostile Review Record — v0.3.0

The rebuild treats every discovered defect as retained test/evidence, not a one-time patch.

## Core defects closed before v0.3.0

1. Caller-supplied capability dictionaries could manufacture VM authority context. Replaced by signed state/operation-bound authority assertions plus AuthorityLedger-owned permit state.
2. Adapters could be called directly with a consequence object. Replaced by gateway-signed invocation binding permit, intent, exact consequence, adapter, gateway, and key identity.
3. Receipt hashes and observer names were integrity labels rather than cryptographic identities. Execution receipts and independent observations are now signature-verified.
4. Effect transitions could be committed while permits remained merely ISSUED. Permit preparation now precedes canonical effect-transition commit.
5. Evidence and identity proof registries were memory-only. Both now support fsynced append-only durable replay and tamper rejection.
6. Identity verification accepted verifier names/codes without cryptographic proof. Status changes now require signed assertions bound to the exact prior identity revision.

## Final epoch-gate defects closed in v0.3.0

7. `checkpoint_at_end=False` was publicly exposed. The comparison test needed the behavior conceptually, but the production training surface did not. The flag was removed; successful training calls checkpoint durably before returning.
8. Dataset isolation partly trusted filenames. A held-out payload could be renamed `train.jsonl`. Curriculum generator ID, manifest, split map, all split bytes, case IDs, family IDs, and hashes are now bound at trainer/evaluator entry.
9. Evaluation/promotion evidence was not cryptographically bound to the checkpoint's exact curriculum. Curriculum manifest/split hashes now travel in cursor, checkpoint, evaluation, and promotion checks.
10. Uncheckpointed optimizer receipts after a hard crash could remain alongside replayed steps. Resume now uses the last ledger-committed checkpoint and records an explicit `RECOVERY_REWIND` orphan set before deterministic replay.
11. `latest.json` could influence resume selection. It is now only a convenience cache; append-only `CHECKPOINT_SAVED` evidence is authoritative.
12. Checkpoint loading used unrestricted pickle-compatible deserialization. It now uses `torch.load(..., weights_only=True)` plus schema/class/config/hash checks.
13. The first neural reference policy was a multiple-choice discriminator: training and evaluation handed it a candidate list containing the correct target. This was rejected as an inference model. v0.3.0 generates the action space deterministically from state/context without receiving the target; `propose(world)` has no candidate argument.
14. Failure labels initially risked treating every non-target transition as constitutionally illegal. Non-target candidates are now executed through the VM before illegality labels are assigned.
15. Canonical training evidence recorded temporary absolute checkpoint paths, making identical logical runs produce different event roots. Canonical checkpoint records now use location-independent artifact names; identical runs in different directories produce identical checkpoint hashes and training-event roots.

`evidence/EPOCH_HOSTILE_GATE_REPORT.json` is the machine-readable final-gate record.
