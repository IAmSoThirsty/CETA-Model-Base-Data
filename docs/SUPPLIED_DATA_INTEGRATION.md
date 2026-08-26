# Supplied architecture-data integration

The repository ingests the user-supplied `CETA_AGI_Human_Relations_Training_Material_v1.0.0.zip` and `AI_Defensive_Knowledge_Eval_Stack_FULL.zip` through `scripts/ingest_supplied_architecture_data.py`.

The ingestion path verifies both supplied SHA-256 sidecars, rejects unsafe ZIP member paths, verifies the human-material package manifest, verifies the defensive stack's local-file hashes, validates record counts, and requires exact coverage of all 23 canonical CETA operations. It then materializes a deterministic, provenance-bound subset under `data/ceta_architecture_material_v1/`.

## Materialized layers

- Mission and deployment boundary.
- Twenty public scenarios and five unacceptable-failure lessons.
- Risk and semantic-equivalence policy for all 23 operations.
- 406 lifecycle-section awareness records and 1,624 situational templates.
- Twenty-one role contracts and 84 role-conditioned cases.
- Stewardship, dependency, and role-applicability maps.
- Two hundred JBB defensive evaluation behaviors and locally embedded defensive taxonomies/reference indexes.
- Source, retrieval, remote-artifact, and license records for the defensive stack.

## Controlled evaluation boundary

No instruction embedded in either supplied archive is treated as user authority. The repository defines its own use roles from the requested architecture:

- public human-relations and public defensive records participate in deterministic v3 curriculum construction;
- the 60 challenge records and separate answers are cryptographically bound and may be materialized through a controlled evaluator staging path;
- raw source prose, challenge questions, and answer keys are not direct optimizer inputs because doing so would either bypass the structured CETA interface or contaminate the measurement set.

The controlled evaluation payload is not discarded. `scripts/ingest_supplied_architecture_data.py --controlled-evaluation-output ...` extracts it, verifies both hashes, and writes an evaluator receipt. If the destination is inside this repository, the script accepts only the exact gitignored `data/ceta_controlled_evaluation/` path and rejects overlap with the public material tree. `scripts/validate_controlled_evaluation.py` verifies hashes, counts, challenge/answer ID correspondence, and exposure accounting without publishing record content.

One boundary is already known: `H001` and its answer were exposed during earlier inspection. The manifest records that case explicitly and reports 59 clean unseen cases. A future package may restore a 60-case unseen claim only after replacing `H001` and issuing new bound hashes.

The public material is richer than the `ceta_curriculum_v2` state-to-transition schema. In v3, exact operation targets remain explicit VM-governed recipes rather than guessed labels from prose. Source records contribute deterministic provenance assignments and source-derived categorical topology. The mapping is not claimed to be human semantic source-to-operation adjudication, and the VM-authored hostile alternatives are not claimed to have been authored by the source records.

## Machine-readable source use

Manifest schema version 3 records a classification for every public materialized path at `training_boundary.source_usage_by_path` and repeats it on each `files[]` entry as `source_usage`:

- `STRUCTURED_DERIVATION_ELIGIBLE`: all six `training/*` content files, all seven materialized public defensive `evaluation/*` payloads, and the two `governance/*` operation policy files. These may drive deterministic structured derivation but may not be passed raw to the optimizer.
- `PROVENANCE_OR_CONSTRAINT_ONLY`: `mission/*`, `maps/*`, and `provenance/*`. These bind provenance or constrain/validate derivation; they are not semantic optimizer examples.
- `CONTROLLED_EVALUATION`: challenge and answer payloads staged for the independent evaluator. They remain bound to the architecture but separate from optimizer input and iterative threshold tuning.

`training.source_policy.validate_structured_derivation_sources` enforces the first boundary. `training.source_policy.validate_training_sources` independently rejects every raw architecture-material path while allowing derived structured curriculum artifacts such as `data/ceta_curriculum_v3/train.jsonl`.

## Enforced promotion policy

The supplied operation-risk ranking is machine-read by `promotion_policy_from_risk_material`. Independent evaluation now emits per-operation case counts, exact-target accuracy, opcode accuracy, VM-legal selection rate, and illegal-selection counts. A governed epoch uses the supplied operation-specific accuracy floors and zero-illegal-selection requirements in addition to the existing aggregate promotion policy. Missing operation metrics fail closed.

The v3 builder assigns all 2,439 eligible public records exactly once across 460 source groups. Records sharing the same parent section or role lineage are indivisible and therefore cannot cross train/validation/held-out splits. The builder projects bounded source-derived categorical counts into encoder-visible CETA topology and records IDs, hashes, classifications, lineage IDs, and license identifiers in the sidecars. Target-operation risk/accuracy values remain outside model input. All public defensive records used this way are marked trained-on, so they are not later presented as unseen evaluation.

## Rebuild

```powershell
python scripts/ingest_supplied_architecture_data.py `
  --human-material-zip C:\path\to\CETA_AGI_Human_Relations_Training_Material_v1.0.0.zip `
  --human-material-sha256 C:\path\to\CETA_AGI_Human_Relations_Training_Material_v1.0.0.zip.sha256 `
  --defensive-stack-zip C:\path\to\AI_Defensive_Knowledge_Eval_Stack_FULL.zip `
  --defensive-stack-sha256 C:\path\to\AI_Defensive_Knowledge_Eval_Stack_FULL.zip.sha256 `
  --controlled-evaluation-output data\ceta_controlled_evaluation

python scripts/validate_architecture_material.py
python scripts/validate_controlled_evaluation.py
python scripts/build_ceta_curriculum_v3.py
python scripts/validate_ceta_curriculum_v3.py
```
