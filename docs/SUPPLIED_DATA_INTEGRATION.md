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

## Isolation boundary

The supplied private challenge questions and separate answer key are not materialized in the repository. Their hashes, count, prohibited uses, and evaluation-only status are preserved in the generated manifest. The raw architecture material and defensive evaluation files are also denied as direct transition-policy training sources by `training.source_policy`.

The material is richer than the current `ceta_curriculum_v2` state-to-transition schema. It is therefore not concatenated into that curriculum. Public prose/design records must first be decomposed into atomic CETA decisions, adjudicated to one exact operation and operand set, converted to complete structured world state, assigned structural-family identities, and supplied with VM-checked hostile alternatives. Only those derived artifacts may become a future curriculum version.

This separation prevents prose targets, multi-action outcomes, evaluation material, or role descriptions from being mistaken for executable authority or exact transition labels.

## Rebuild

```powershell
python scripts/ingest_supplied_architecture_data.py `
  --human-material-zip C:\path\to\CETA_AGI_Human_Relations_Training_Material_v1.0.0.zip `
  --human-material-sha256 C:\path\to\CETA_AGI_Human_Relations_Training_Material_v1.0.0.zip.sha256 `
  --defensive-stack-zip C:\path\to\AI_Defensive_Knowledge_Eval_Stack_FULL.zip `
  --defensive-stack-sha256 C:\path\to\AI_Defensive_Knowledge_Eval_Stack_FULL.zip.sha256

python scripts/validate_architecture_material.py
```
