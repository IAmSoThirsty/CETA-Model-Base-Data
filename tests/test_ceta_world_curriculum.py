from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from training import CetaWorldCurriculum, TransitionTrainingCase, WorldCurriculumArtifactWriter, partition_world_families


class CetaWorldCurriculumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=CetaWorldCurriculum().build()

    def test_complete_opcode_and_scale_contract(self):
        self.assertEqual(len(self.cases),690)
        counts=Counter(c.target_proposal.operation for c in self.cases)
        self.assertEqual(set(counts),set(CetaWorldCurriculum.OPERATIONS))
        self.assertEqual(set(counts.values()),{30})
        self.assertEqual(sum(len(c.illegal_alternatives) for c in self.cases),2760)

    def test_family_variants_share_structure_but_not_state_identity(self):
        fingerprints=defaultdict(set); state_refs=defaultdict(set)
        for case in self.cases:
            fingerprints[case.world_family_id].add(case.structural_fingerprint)
            state_refs[case.world_family_id].add(case.state_ref)
        self.assertEqual(len(fingerprints),230)
        self.assertTrue(all(len(v)==1 for v in fingerprints.values()))
        self.assertTrue(all(len(v)==3 for v in state_refs.values()))

    def test_family_partition_is_exact_and_leakage_free(self):
        split=partition_world_families(self.cases)
        self.assertEqual((len(split.train),len(split.validation),len(split.heldout)),(552,69,69))
        self.assertEqual((len(split.train_families),len(split.validation_families),len(split.heldout_families)),(184,23,23))
        split.verify_disjoint()
        by_id={c.case_id:c for c in self.cases}
        for op in CetaWorldCurriculum.OPERATIONS:
            self.assertEqual(sum(by_id[x].target_proposal.operation==op for x in split.train),24)
            self.assertEqual(sum(by_id[x].target_proposal.operation==op for x in split.validation),3)
            self.assertEqual(sum(by_id[x].target_proposal.operation==op for x in split.heldout),3)

    def test_records_are_structured_not_language_targets(self):
        forbidden={'prompt','response','answer','completion','expected_output','expected_text'}
        def walk(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    self.assertNotIn(str(k).lower(),forbidden)
                    walk(v)
            elif isinstance(value,list):
                for v in value: walk(v)
        for case in self.cases:
            walk(case.to_record())

    def test_round_trip_record(self):
        case=self.cases[117]
        restored=TransitionTrainingCase.from_record(case.to_record())
        self.assertEqual(restored,case)

    def test_artifact_writer_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'a'; b=Path(td)/'b'
            ma=WorldCurriculumArtifactWriter.write(a,self.cases)
            mb=WorldCurriculumArtifactWriter.write(b,reversed(self.cases))
            self.assertEqual(ma,mb)
            for name in ('train.jsonl','validation.jsonl','heldout.jsonl','splits.json','manifest.json'):
                self.assertEqual((a/name).read_bytes(),(b/name).read_bytes(),name)
                self.assertNotIn(b'\r\n',(a/name).read_bytes(),name)
        package_manifest=json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
        package_paths=[entry['path'] for entry in package_manifest['files']]
        self.assertEqual(package_paths,sorted(package_paths))
        checksum_paths=[line.split('  ',1)[1] for line in (ROOT/'SHA256SUMS').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(checksum_paths,sorted(checksum_paths))


if __name__=='__main__': unittest.main()
