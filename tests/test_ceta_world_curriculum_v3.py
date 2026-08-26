from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from training import (
    CETA_CURRICULUM_V3_GENERATOR_ID,
    CetaWorldCurriculum,
    CetaWorldCurriculumV3,
    PublicSourceCatalog,
    TrainingBindingError,
    WorldCurriculumArtifactWriter,
    build_source_family_assignments,
    resolve_curriculum_binding,
    write_source_sidecars,
)
from transition_policy import CetaActionSpaceGenerator, OPERATION_TO_INDEX, StructuredStateEncoder, world_from_training_case
from ceta import ConstitutionalVM, VmDisposition


MATERIAL = ROOT / "data/ceta_architecture_material_v1"


class CetaWorldCurriculumV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = PublicSourceCatalog.load(MATERIAL)
        cls.assignments = build_source_family_assignments(cls.catalog, MATERIAL)
        cls.by_family = {item.family_id: item for item in cls.assignments}
        cls.cases = CetaWorldCurriculumV3(cls.assignments).build()

    def test_scale_operation_and_public_source_coverage(self):
        self.assertEqual(len(self.catalog.records), 2439)
        self.assertEqual(Counter(item.source_class for item in self.catalog.records), {
            "HUMAN_RELATIONS_PUBLIC": 2160,
            "DEFENSIVE_PUBLIC": 279,
        })
        self.assertEqual(len(self.assignments), 460)
        self.assertEqual(len(self.cases), 1380)
        self.assertEqual(sum(len(case.illegal_alternatives) for case in self.cases), 5520)
        self.assertEqual(
            Counter(case.target_proposal.operation for case in self.cases),
            {operation: 60 for operation in CetaWorldCurriculum.OPERATIONS},
        )
        assigned = [source_id for item in self.assignments for source_id in item.source_record_ids]
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(set(assigned), {item.source_record_id for item in self.catalog.records})
        self.assertTrue(self.catalog.controlled_evaluation["bound_to_architecture"])
        self.assertFalse(self.catalog.controlled_evaluation["materialized_in_repository"])
        self.assertEqual(self.catalog.controlled_evaluation["known_exposed_case_ids"], ["H001"])
        self.assertEqual(self.catalog.controlled_evaluation["clean_unseen_case_count"], 59)

    def test_source_lineages_are_indivisible_family_units(self):
        family_by_lineage = {}
        record_by_id = {item.source_record_id: item for item in self.catalog.records}
        for assignment in self.assignments:
            self.assertEqual(assignment.to_record()["assignment_status"], "DETERMINISTIC_PROVENANCE_ASSIGNMENT")
            self.assertFalse(assignment.to_record()["semantic_source_to_operation_adjudication"])
            for source_id in assignment.source_record_ids:
                lineage_id = record_by_id[source_id].lineage_id
                previous = family_by_lineage.setdefault(lineage_id, assignment.family_id)
                self.assertEqual(previous, assignment.family_id)

    def test_family_variants_share_structure_state_and_source_boundaries(self):
        fingerprints = defaultdict(set)
        state_refs = defaultdict(set)
        source_groups = defaultdict(set)
        for case in self.cases:
            fingerprints[case.world_family_id].add(case.structural_fingerprint)
            state_refs[case.world_family_id].add(case.state_ref)
            self.assertNotIn("curriculum_binding", json.loads(case.proposal_context_json))
            assignment = self.by_family[case.world_family_id]
            source_groups[case.world_family_id].add(assignment.source_group_id)
            self.assertEqual(case.target_proposal.operation, assignment.operation)
        self.assertEqual(len(fingerprints), 460)
        self.assertTrue(all(len(values) == 1 for values in fingerprints.values()))
        self.assertTrue(all(len(values) == 3 for values in state_refs.values()))
        self.assertTrue(all(len(values) == 1 for values in source_groups.values()))
        self.assertEqual(len({next(iter(values)) for values in source_groups.values()}), 460)

    def test_source_projection_is_visible_to_the_structured_encoder(self):
        encoder = StructuredStateEncoder()
        for case in self.cases[::59]:
            assignment = self.by_family[case.world_family_id]
            profile = assignment.projection_profile
            world = world_from_training_case(case)
            encoded = encoder.encode_world(world)
            index_by_id = {object_id: index for index, object_id in enumerate(encoded.object_ids)}
            anchors = {
                obj.object_id: obj
                for obj in world.snapshot.active_objects
                if obj.object_id.startswith("UNIVERSE-V3-")
            }
            source_id = next(object_id for object_id in anchors if "-SOURCE-" in object_id)
            source = anchors[source_id]
            self.assertEqual(sum(len(values) for values in source.content["scope"].values()), profile["source_count"])
            self.assertEqual(
                int(encoded.node_numeric[index_by_id[source_id], 1].item()),
                profile["source_count"],
            )

    def test_operation_discriminators_are_visible_to_the_structured_encoder(self):
        encoder = StructuredStateEncoder()
        by_operation = {}
        for case in self.cases:
            by_operation.setdefault(case.target_proposal.operation, case)

        expected_relations = {
            "Support": (1.0, 0.0, 0.0),
            "Contradict": (0.0, 1.0, 0.0),
            "Undercut": (0.0, 0.0, 1.0),
        }
        for operation, expected in expected_relations.items():
            encoded = encoder.encode_world(world_from_training_case(by_operation[operation]))
            actual = tuple(float(x) for x in encoded.node_numeric[:, 8:11].max(dim=0).values)
            self.assertEqual(actual, expected)

        expected_effects = {
            "Execute": (1.0, 0.0),
            "Rollback": (0.0, 1.0),
        }
        for operation, expected in expected_effects.items():
            encoded = encoder.encode_world(world_from_training_case(by_operation[operation]))
            actual = tuple(float(x) for x in encoded.node_numeric[:, 11:13].max(dim=0).values)
            self.assertEqual(actual, expected)

    def test_known_hostile_candidates_have_distinct_structural_encodings(self):
        encoder = StructuredStateEncoder()

        def signature(candidate):
            return (
                candidate.operation_index,
                tuple(candidate.structural_numeric.tolist()),
                tuple(candidate.operand_role.tolist()),
                tuple(candidate.operand_kind.tolist()),
                tuple(tuple(row) for row in candidate.operand_numeric.tolist()),
                candidate.operand_ref_indices,
            )

        for case in self.cases:
            world = encoder.encode_world(world_from_training_case(case))
            target = encoder.encode_candidate(case.target_proposal, world, operation_to_index=OPERATION_TO_INDEX)
            target_signature = signature(target)
            for alternative in case.illegal_alternatives:
                if alternative.proposal.operation not in OPERATION_TO_INDEX:
                    continue
                encoded = encoder.encode_candidate(alternative.proposal, world, operation_to_index=OPERATION_TO_INDEX)
                self.assertNotEqual(
                    signature(encoded), target_signature,
                    f"hostile candidate collapsed onto target encoding: {case.case_id}/{alternative.alternative_id}",
                )

    def test_source_context_anchors_never_enter_the_action_space(self):
        generator = CetaActionSpaceGenerator()
        for case in self.cases:
            world = world_from_training_case(case)
            anchor_ids = {
                obj.object_id
                for obj in world.snapshot.active_objects
                if obj.object_id.startswith("UNIVERSE-V3-")
            }
            self.assertTrue(anchor_ids)
            for proposal in generator.generate(world):
                encoded_operands = json.dumps(dict(proposal.operands), sort_keys=True)
                self.assertFalse(
                    any(anchor_id in encoded_operands for anchor_id in anchor_ids),
                    f"source context anchor entered action space: {case.case_id}/{proposal.operation}",
                )

    def test_target_is_the_unique_vm_legal_generated_transition(self):
        generator = CetaActionSpaceGenerator()
        vm = ConstitutionalVM()
        for case in self.cases:
            world = world_from_training_case(case)
            legal = []
            for proposal in generator.generate(world):
                decision = vm.evaluate(
                    proposal,
                    projected_snapshot=world.snapshot,
                    admitted_evidence_view=world.evidence_view,
                    identity_view=world.identity_view,
                    authority_snapshot=world.authority_view,
                    now_epoch_ms=world.now_epoch_ms,
                    constitutional_epoch="curriculum-v3-test",
                )
                if decision.disposition is VmDisposition.LEGAL:
                    legal.append(proposal)
            self.assertEqual(
                [(item.operation, dict(item.operands)) for item in legal],
                [(case.target_proposal.operation, dict(case.target_proposal.operands))],
                case.case_id,
            )

    def test_byte_deterministic_artifacts_and_bound_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a"
            b = Path(td) / "b"
            a_catalog, a_assignments = write_source_sidecars(a, self.catalog, self.assignments)
            b_catalog, b_assignments = write_source_sidecars(b, self.catalog, reversed(self.assignments))
            ma = WorldCurriculumArtifactWriter.write(
                a,
                self.cases,
                generator_id=CETA_CURRICULUM_V3_GENERATOR_ID,
                bound_artifacts={"source_catalog": a_catalog, "source_assignments": a_assignments},
            )
            mb = WorldCurriculumArtifactWriter.write(
                b,
                reversed(self.cases),
                generator_id=CETA_CURRICULUM_V3_GENERATOR_ID,
                bound_artifacts={"source_catalog": b_catalog, "source_assignments": b_assignments},
            )
            self.assertEqual(ma, mb)
            for name in (
                "train.jsonl", "validation.jsonl", "heldout.jsonl", "splits.json", "manifest.json",
                "source_catalog.json", "source_assignments.jsonl",
            ):
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)
            resolve_curriculum_binding(a / "train.jsonl", split="train")
            with (a / "source_catalog.json").open("a", encoding="utf-8") as handle:
                handle.write(" ")
            with self.assertRaises(TrainingBindingError):
                resolve_curriculum_binding(a / "train.jsonl", split="train")

    def test_v2_regeneration_remains_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            generated = Path(td) / "v2"
            WorldCurriculumArtifactWriter.write(generated, CetaWorldCurriculum().build())
            checked_in = ROOT / "data/ceta_curriculum_v2"
            for name in ("train.jsonl", "validation.jsonl", "heldout.jsonl", "splits.json", "manifest.json"):
                self.assertEqual((generated / name).read_bytes(), (checked_in / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
