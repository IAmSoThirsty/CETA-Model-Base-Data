from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from training import (
    CheckpointPromotionRegistry, EvaluationMetrics, GovernedEpochTrainer,
    IndependentCheckpointEvaluator, PromotionPolicy, TrainingBindingError,
    TrainingConfig, TrainingEventLedger, effective_optimizer_events, file_sha256, hash_torch_state,
    promotion_policy_from_risk_material,
)
from history import domain_hash

DATA=ROOT/'data/ceta_curriculum_v2'


class GovernedTrainingTests(unittest.TestCase):
    def setUp(self):
        self.cfg=TrainingConfig(seed=123,learning_rate=0.002,hidden_dim=16)

    def _metrics_body(self,cp,**overrides):
        body={
            'split':'validation','case_count':69,'target_accuracy':0.0,'opcode_accuracy':0.0,
            'legal_selection_rate':0.0,'mean_transition_loss':99.0,'rejected_candidate_count':69,
            'checkpoint_sha256':cp.sha256,'dataset_sha256':file_sha256(DATA/'validation.jsonl'),
            'curriculum_manifest_sha256':cp.cursor.curriculum_manifest_sha256,
            'curriculum_splits_sha256':cp.cursor.curriculum_splits_sha256,
        }
        body.update(overrides)
        return body

    def test_pause_resume_matches_uninterrupted_model_state(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            uninterrupted=GovernedEpochTrainer(run_root=td/'a',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            uninterrupted.train_cases(8)
            expected=hash_torch_state(uninterrupted.model.state_dict(),domain='CETA/MODEL_STATE/v1')

            paused=GovernedEpochTrainer(run_root=td/'b',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            paused.train_cases(3)
            resumed=GovernedEpochTrainer(run_root=td/'b',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R',resume=True)
            resumed.train_cases(5)
            actual=hash_torch_state(resumed.model.state_dict(),domain='CETA/MODEL_STATE/v1')
            self.assertEqual(actual,expected)

    def test_training_evidence_root_is_location_independent(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            a=GovernedEpochTrainer(run_root=td/'alpha',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            b=GovernedEpochTrainer(run_root=td/'beta',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            ca=a.train_cases(4); cb=b.train_cases(4)
            self.assertEqual(ca.sha256,cb.sha256)
            self.assertEqual(ca.model_hash,cb.model_hash)
            self.assertEqual(a.ledger.current_root,b.ledger.current_root)
            self.assertEqual(a.ledger.events[-1]['payload']['checkpoint']['path'],Path(ca.path).name)

    def test_training_api_cannot_disable_checkpointing(self):
        import inspect
        signature=inspect.signature(GovernedEpochTrainer.train_cases)
        self.assertNotIn('checkpoint_at_end',signature.parameters)
        self.assertIn('device',inspect.signature(GovernedEpochTrainer).parameters)
        with tempfile.TemporaryDirectory() as td:
            trainer=GovernedEpochTrainer(run_root=Path(td)/'run',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            self.assertEqual(trainer.device,torch.device('cpu'))
            checkpoint=trainer.train_cases(1)
            self.assertTrue(Path(checkpoint.path).is_file())
            self.assertEqual(trainer.ledger.events[-1]['event_type'],'CHECKPOINT_SAVED')
            if not torch.cuda.is_available():
                with self.assertRaisesRegex(TrainingBindingError,'CUDA training requested'):
                    GovernedEpochTrainer(run_root=Path(td)/'cuda',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='CUDA',device='cuda')

    def test_optimizer_receipts_are_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            trainer=GovernedEpochTrainer(run_root=Path(td)/'run',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            trainer.train_cases(2)
            events=[e for e in trainer.ledger.events if e['event_type']=='OPTIMIZER_STEP']
            self.assertEqual(len(events),2)
            for event in events:
                payload=dict(event['payload']); receipt_hash=payload.pop('receipt_hash')
                self.assertEqual(receipt_hash,domain_hash(payload,domain='CETA/OPTIMIZER_RECEIPT/v1'))
                self.assertNotEqual(payload['model_hash_before'],payload['model_hash_after'])

    def test_checkpoint_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'
            trainer=GovernedEpochTrainer(run_root=root,dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            cp=trainer.train_cases(1)
            path=Path(cp.path)
            raw=bytearray(path.read_bytes()); raw[len(raw)//2]^=1; path.write_bytes(raw)
            with self.assertRaises(TrainingBindingError):
                GovernedEpochTrainer(run_root=root,dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R',resume=True)

    def test_training_ledger_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'
            trainer=GovernedEpochTrainer(run_root=root,dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            trainer.train_cases(1)
            path=root/'training-events.jsonl'
            lines=path.read_text().splitlines(); first=json.loads(lines[0]); first['payload']['case_count']+=1; lines[0]=json.dumps(first,separators=(',',':'))
            path.write_text('\n'.join(lines)+'\n')
            with self.assertRaises(TrainingBindingError): TrainingEventLedger(path)

    def test_training_cannot_consume_validation_or_heldout_split(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ('validation.jsonl','heldout.jsonl'):
                with self.assertRaises(TrainingBindingError):
                    GovernedEpochTrainer(run_root=Path(td)/name,dataset_path=DATA/name,config=self.cfg,run_id='R')

    def test_independent_evaluation_is_checkpoint_bound(self):
        with tempfile.TemporaryDirectory() as td:
            trainer=GovernedEpochTrainer(run_root=Path(td)/'run',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            cp=trainer.train_cases(2)
            metrics=IndependentCheckpointEvaluator(config=self.cfg).evaluate(cp.path,DATA/'validation.jsonl',split='validation')
            self.assertEqual(metrics.checkpoint_sha256,cp.sha256)
            self.assertEqual(metrics.case_count,69)
            self.assertGreaterEqual(metrics.legal_selection_rate,0.0)
            self.assertLessEqual(metrics.legal_selection_rate,1.0)
            self.assertEqual(len(metrics.operation_metrics),23)
            self.assertTrue(all(item['case_count']==3 for item in metrics.operation_metrics.values()))

    def test_supplied_operation_risk_policy_is_machine_enforced(self):
        path=ROOT/'data/ceta_architecture_material_v1/governance/operation_risk_ranking.json'
        policy=promotion_policy_from_risk_material(path)
        self.assertEqual(len(policy.operation_target_accuracy),23)
        self.assertAlmostEqual(policy.operation_target_accuracy['Authorize'],0.999999)
        self.assertIn('Execute',policy.zero_illegal_selection_operations)
        self.assertNotIn('Reevaluate',policy.zero_illegal_selection_operations)

        body={
            'split':'validation','case_count':1,'target_accuracy':1.0,'opcode_accuracy':1.0,
            'legal_selection_rate':1.0,'mean_transition_loss':0.0,'rejected_candidate_count':0,
            'checkpoint_sha256':'cp','dataset_sha256':'data','curriculum_manifest_sha256':'manifest',
            'curriculum_splits_sha256':'splits',
            'operation_metrics':{
                operation:{'case_count':1,'target_accuracy':1.0,'opcode_accuracy':1.0,'legal_selection_rate':1.0,'illegal_selection_count':0}
                for operation in policy.operation_target_accuracy
            },
        }
        body['operation_metrics']['Execute']['illegal_selection_count']=1
        metrics=EvaluationMetrics(**body,evaluation_hash=domain_hash(body,domain='CETA/INDEPENDENT_EVALUATION/v1'))
        passed,failures=policy.evaluate(metrics)
        self.assertFalse(passed)
        self.assertIn('OPERATION_ILLEGAL_SELECTION:Execute',failures)

    def test_promotion_quarantine_and_rollback_are_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            trainer=GovernedEpochTrainer(run_root=td/'run',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            cp=trainer.train_cases(1)
            registry=CheckpointPromotionRegistry(td/'registry',trainer.ledger)
            body=self._metrics_body(cp)
            bad=EvaluationMetrics(**body,evaluation_hash=domain_hash(body,domain='CETA/INDEPENDENT_EVALUATION/v1'))
            strict=PromotionPolicy(0.9,0.9,0.9,1.0)
            self.assertEqual(registry.decide(cp,bad,strict),'QUARANTINED')

            body2={**body,'target_accuracy':1.0,'opcode_accuracy':1.0,'legal_selection_rate':1.0,'mean_transition_loss':0.0}
            good=EvaluationMetrics(**body2,evaluation_hash=domain_hash(body2,domain='CETA/INDEPENDENT_EVALUATION/v1'))
            permissive_for_fixture=PromotionPolicy(1.0,1.0,1.0,0.0)
            self.assertEqual(registry.decide(cp,good,permissive_for_fixture),'PROMOTED')
            registry.rollback(cp,reason_code='HOSTILE_TEST_ROLLBACK')
            head=json.loads((td/'registry/trusted-head.json').read_text())
            self.assertEqual(head['checkpoint_sha256'],cp.sha256)
            self.assertEqual(head['rollback_reason_code'],'HOSTILE_TEST_ROLLBACK')

    def test_promotion_rejects_heldout_as_authority(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            trainer=GovernedEpochTrainer(run_root=td/'run',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            cp=trainer.train_cases(1)
            body=self._metrics_body(cp,split='heldout',target_accuracy=1.0,opcode_accuracy=1.0,legal_selection_rate=1.0,mean_transition_loss=0.0,rejected_candidate_count=0,dataset_sha256=file_sha256(DATA/'heldout.jsonl'))
            metrics=EvaluationMetrics(**body,evaluation_hash=domain_hash(body,domain='CETA/INDEPENDENT_EVALUATION/v1'))
            with self.assertRaises(TrainingBindingError):
                CheckpointPromotionRegistry(td/'registry',trainer.ledger).decide(cp,metrics,PromotionPolicy(0,0,0,99))


    def test_renamed_heldout_cannot_enter_training(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)/'curriculum'
            shutil.copytree(DATA,base)
            shutil.copyfile(base/'heldout.jsonl',base/'train.jsonl')
            with self.assertRaises(TrainingBindingError):
                GovernedEpochTrainer(run_root=Path(td)/'run',dataset_path=base/'train.jsonl',config=self.cfg,run_id='R')

    def test_split_manifest_tampering_blocks_training(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)/'curriculum'
            shutil.copytree(DATA,base)
            splits=json.loads((base/'splits.json').read_text())
            moved=splits['case_splits']['heldout'][0]
            splits['case_splits']['train'].append(moved)
            (base/'splits.json').write_text(json.dumps(splits,sort_keys=True))
            with self.assertRaises(TrainingBindingError):
                GovernedEpochTrainer(run_root=Path(td)/'run',dataset_path=base/'train.jsonl',config=self.cfg,run_id='R')

    def test_evaluator_rejects_checkpoint_sidecar_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            trainer=GovernedEpochTrainer(run_root=td/'run',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            cp=trainer.train_cases(1)
            sidecar=Path(cp.path).with_suffix(Path(cp.path).suffix+'.json')
            meta=json.loads(sidecar.read_text()); meta['sha256']='0'*64; sidecar.write_text(json.dumps(meta))
            with self.assertRaises(TrainingBindingError):
                IndependentCheckpointEvaluator(config=self.cfg).evaluate(cp.path,DATA/'validation.jsonl',split='validation')

    def test_promotion_rejects_cross_curriculum_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            trainer=GovernedEpochTrainer(run_root=td/'run',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            cp=trainer.train_cases(1)
            body=self._metrics_body(cp,curriculum_manifest_sha256='f'*64)
            metrics=EvaluationMetrics(**body,evaluation_hash=domain_hash(body,domain='CETA/INDEPENDENT_EVALUATION/v1'))
            with self.assertRaises(TrainingBindingError):
                CheckpointPromotionRegistry(td/'registry',trainer.ledger).decide(cp,metrics,PromotionPolicy(0,0,0,99))


    def test_crash_tail_is_orphaned_before_deterministic_replay(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            baseline=GovernedEpochTrainer(run_root=td/'baseline',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            baseline.train_cases(5)
            expected=hash_torch_state(baseline.model.state_dict(),domain='CETA/MODEL_STATE/v1')

            crashed=GovernedEpochTrainer(run_root=td/'crashed',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            crashed.train_cases(3)
            order=crashed._epoch_order(crashed.cursor.epoch_index)
            orphan_case=crashed.cases[order[crashed.cursor.next_case_offset]]
            crashed._train_one(orphan_case)  # simulate process death before cursor/checkpoint commit

            resumed=GovernedEpochTrainer(run_root=td/'crashed',dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R',resume=True)
            self.assertEqual(resumed.ledger.events[-2]['event_type'],'RECOVERY_REWIND')
            resumed.train_cases(2)
            actual=hash_torch_state(resumed.model.state_dict(),domain='CETA/MODEL_STATE/v1')
            self.assertEqual(actual,expected)
            effective=effective_optimizer_events(resumed.ledger.events)
            self.assertEqual(len(effective),5)
            self.assertEqual([e['payload']['global_step_before'] for e in effective],list(range(5)))

    def test_resume_uses_ledger_checkpoint_not_mutable_latest_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'
            trainer=GovernedEpochTrainer(run_root=root,dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            older=trainer.train_cases(2)
            newer=trainer.train_cases(2)
            sidecar=Path(older.path).with_suffix(Path(older.path).suffix+'.json')
            (root/'checkpoints/latest.json').write_text(json.dumps({'checkpoint':Path(older.path).name,'sidecar':sidecar.name,'sha256':older.sha256}))
            resumed=GovernedEpochTrainer(run_root=root,dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R',resume=True)
            self.assertEqual(resumed.checkpoint.sha256,newer.sha256)
            latest=json.loads((root/'checkpoints/latest.json').read_text())
            self.assertEqual(latest['sha256'],newer.sha256)

    def test_resume_does_not_require_latest_pointer_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'
            trainer=GovernedEpochTrainer(run_root=root,dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R')
            cp=trainer.train_cases(2)
            (root/'checkpoints/latest.json').unlink()
            resumed=GovernedEpochTrainer(run_root=root,dataset_path=DATA/'train.jsonl',config=self.cfg,run_id='R',resume=True)
            self.assertEqual(resumed.checkpoint.sha256,cp.sha256)


if __name__=='__main__': unittest.main()
