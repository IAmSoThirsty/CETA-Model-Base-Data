from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from ceta import ConstitutionalVM, TransitionProposal
from training import ExecutableTransitionEvaluator, ReferenceCurriculum, TransitionDatasetWriter


class TransitionTrainingTests(unittest.TestCase):
    def test_reference_curriculum_contains_only_structured_state_and_transition_targets(self):
        cases=ReferenceCurriculum().build()
        self.assertGreaterEqual(len(cases),3)
        for case in cases:
            record=case.to_record()
            self.assertIn('state',record)
            self.assertIn('target_transition',record)
            self.assertNotIn('prompt',record)
            self.assertNotIn('expected_output',record)
            self.assertIsInstance(record['target_transition']['operands'],dict)

    def test_correct_transition_scores_zero(self):
        evaluator=ExecutableTransitionEvaluator(ConstitutionalVM())
        for case in ReferenceCurriculum().build():
            loss=evaluator.score(case,case.target_proposal)
            self.assertEqual(loss.total,0,(case.case_id,loss))

    def test_stale_state_is_replay_mismatch_and_illegal(self):
        case=ReferenceCurriculum().build()[0]
        target=case.target_proposal
        prediction=TransitionProposal('STALE',target.operation,target.operands,'model')
        loss=ExecutableTransitionEvaluator(ConstitutionalVM()).score(case,prediction)
        self.assertEqual(loss.illegal_transition,1)
        self.assertEqual(loss.replay_mismatch,1)

    def test_verify_over_known_defeater_is_penalized(self):
        case=ReferenceCurriculum().build()[1]
        prediction=TransitionProposal(case.state_ref,'Verify',{
            'target_ref':'B-B','replacement_id':'B-BV','evidence_refs':['E-S'],'verification_code':'IGNORE_CONTRADICTION'},'model')
        loss=ExecutableTransitionEvaluator(ConstitutionalVM()).score(case,prediction)
        self.assertEqual(loss.missing_defeaters,1)
        self.assertEqual(loss.illegal_transition,1)

    def test_dataset_writer_is_deterministic_jsonl(self):
        cases=ReferenceCurriculum().build()
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'a.jsonl'; b=Path(td)/'b.jsonl'
            self.assertEqual(TransitionDatasetWriter.write_jsonl(a,cases),len(cases))
            self.assertEqual(TransitionDatasetWriter.write_jsonl(b,cases),len(cases))
            self.assertEqual(a.read_bytes(),b.read_bytes())
            for line in a.read_text().splitlines(): json.loads(line)

if __name__=='__main__': unittest.main()

class TrainingIsolationTests(unittest.TestCase):
    def test_governance_and_evaluation_material_is_never_training_input(self):
        from training import TrainingSourceViolation, validate_training_sources
        for path in (
            'evaluation/heldout.jsonl',
            'history/events.jsonl',
            'authority/state/runtime.json',
            'authority/evidence/proof.json',
            'authority/continuity/head.json',
            'sources/x/tests/test_case.py',
            'sources/x/verification/report.json',
            'views/evaluation/results.jsonl',
        ):
            with self.assertRaises(TrainingSourceViolation, msg=path):
                validate_training_sources([path])

    def test_deterministic_partition_is_disjoint_and_stable(self):
        from training import deterministic_partition
        ids=[f'CASE-{i:05d}' for i in range(2000)]
        a=deterministic_partition(ids)
        b=deterministic_partition(reversed(ids))
        self.assertEqual(a,b)
        a.verify_disjoint()
        self.assertEqual(len(set(a.train)|set(a.validation)|set(a.heldout)),len(ids))
        self.assertGreater(len(a.train),1500)
        self.assertGreater(len(a.validation),120)
        self.assertGreater(len(a.heldout),120)

    def test_failure_cause_remains_unresolved_without_evidence(self):
        from training import classify_failure
        result=classify_failure('model_capacity_failure',reason='possible capacity issue')
        self.assertEqual(result.category,'unresolved_failure_cause')
        specific=classify_failure('model_capacity_failure',evidence_refs=('E1',),reason='measured capacity bound')
        self.assertEqual(specific.category,'model_capacity_failure')
