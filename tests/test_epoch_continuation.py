from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from training import (
    GovernedEpochTrainer, TrainingBindingError, TrainingConfig, TrainingEventLedger,
    effective_optimizer_events, file_sha256,
)


SOURCE_DATA=ROOT/'data/ceta_curriculum_v2'
RUNNER_SPEC=importlib.util.spec_from_file_location('ceta_epoch_runner',ROOT/'scripts/run_epoch_readiness.py')
assert RUNNER_SPEC is not None
assert RUNNER_SPEC.loader is not None
EPOCH_RUNNER=importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(EPOCH_RUNNER)


class SimulatedProcessExit(RuntimeError):
    pass


def write_mini_curriculum(root: Path) -> Path:
    root.mkdir(parents=True)
    selected={
        'train':(SOURCE_DATA/'train.jsonl').read_text(encoding='utf-8').splitlines()[:2],
        'validation':(SOURCE_DATA/'validation.jsonl').read_text(encoding='utf-8').splitlines()[:1],
        'heldout':(SOURCE_DATA/'heldout.jsonl').read_text(encoding='utf-8').splitlines()[:1],
    }
    parsed={name:[json.loads(line) for line in lines] for name,lines in selected.items()}
    for name,records in parsed.items():
        payload=''.join(json.dumps(record,sort_keys=True,separators=(',',':'))+'\n' for record in records)
        (root/f'{name}.jsonl').write_text(payload,encoding='utf-8',newline='\n')
    splits={
        'schema_version':1,'generator_id':'CETA_TEST_CURRICULUM/v1',
        'case_splits':{name:[record['case_id'] for record in records] for name,records in parsed.items()},
        'family_splits':{name:sorted({record['world_family_id'] for record in records}) for name,records in parsed.items()},
    }
    (root/'splits.json').write_text(json.dumps(splits,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')
    manifest={
        'schema_version':1,'generator_id':splits['generator_id'],'splits_sha256':file_sha256(root/'splits.json'),
        'files':{
            name:{'path':f'{name}.jsonl','count':len(records),'sha256':file_sha256(root/f'{name}.jsonl')}
            for name,records in parsed.items()
        },
    }
    (root/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')
    return root


class EpochContinuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config=TrainingConfig(seed=123,learning_rate=0.002,hidden_dim=8)

    def test_new_process_finishes_original_fixed_target(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); data=write_mini_curriculum(td/'curriculum')

            expected_root=td/'expected'
            expected_base=GovernedEpochTrainer(
                run_root=expected_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',
            ).train_cases(2)
            expected_trainer=GovernedEpochTrainer(
                run_root=expected_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',resume=True,
            )
            expected=expected_trainer.train_additional_epochs(
                2,expected_base_checkpoint_sha256=expected_base.sha256,
            )

            interrupted_root=td/'interrupted'
            interrupted_base=GovernedEpochTrainer(
                run_root=interrupted_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',
            ).train_cases(2)
            self.assertEqual(interrupted_base.sha256,expected_base.sha256)
            interrupted=GovernedEpochTrainer(
                run_root=interrupted_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',resume=True,
            )
            original_train_cases=interrupted.train_cases
            calls=0

            def train_one_epoch_then_exit(max_cases: int):
                nonlocal calls
                if calls:
                    raise SimulatedProcessExit('simulated process exit after one committed continuation epoch')
                calls+=1
                return original_train_cases(max_cases)

            interrupted.train_cases=train_one_epoch_then_exit
            with self.assertRaises(SimulatedProcessExit):
                interrupted.train_additional_epochs(
                    2,expected_base_checkpoint_sha256=interrupted_base.sha256,
                )

            child_code=(
                "import json,sys; from pathlib import Path; "
                "sys.path.insert(0,sys.argv[1]); "
                "from training import GovernedEpochTrainer,TrainingConfig; "
                "cfg=TrainingConfig(seed=123,learning_rate=0.002,hidden_dim=8); "
                "trainer=GovernedEpochTrainer(run_root=Path(sys.argv[2]),dataset_path=Path(sys.argv[3]),config=cfg,run_id='R',resume=True); "
                "cp=trainer.train_additional_epochs(2,expected_base_checkpoint_sha256=sys.argv[4]); "
                "print(json.dumps({'model_hash':cp.model_hash,'epoch':cp.cursor.epoch_index,'step':cp.cursor.global_step,'sha256':cp.sha256}))"
            )
            child=subprocess.run(
                [sys.executable,'-c',child_code,str(ROOT/'src'),str(interrupted_root),str(data/'train.jsonl'),interrupted_base.sha256],
                cwd=ROOT,text=True,capture_output=True,check=False,
            )
            self.assertEqual(child.returncode,0,msg=f'stdout={child.stdout}\nstderr={child.stderr}')
            recovered=json.loads(child.stdout.splitlines()[-1])
            self.assertEqual(recovered['model_hash'],expected.model_hash)
            self.assertEqual(recovered['sha256'],expected.sha256)
            self.assertEqual((recovered['epoch'],recovered['step']),(3,6))

            ledger=TrainingEventLedger(interrupted_root/'training-events.jsonl')
            self.assertEqual(sum(event['event_type']=='CONTINUATION_PLANNED' for event in ledger.events),1)
            self.assertEqual(sum(event['event_type']=='CONTINUATION_COMPLETED' for event in ledger.events),1)
            self.assertEqual(len(effective_optimizer_events(ledger.events)),6)

            idempotent=GovernedEpochTrainer(
                run_root=interrupted_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',resume=True,
            )
            optimizer_event_count=len(effective_optimizer_events(idempotent.ledger.events))
            retried=idempotent.train_additional_epochs(
                2,expected_base_checkpoint_sha256=interrupted_base.sha256,
            )
            self.assertEqual(retried.sha256,recovered['sha256'])
            self.assertEqual(len(effective_optimizer_events(idempotent.ledger.events)),optimizer_event_count)

    def test_continuation_requires_exact_epoch_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); data=write_mini_curriculum(td/'curriculum'); run_root=td/'run'
            base=GovernedEpochTrainer(
                run_root=run_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',
            ).train_cases(1)
            resumed=GovernedEpochTrainer(
                run_root=run_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',resume=True,
            )
            with self.assertRaisesRegex(TrainingBindingError,'exact epoch boundary'):
                resumed.train_additional_epochs(1,expected_base_checkpoint_sha256=base.sha256)

    def test_curriculum_manifest_change_blocks_checkpoint_continuation(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); data=write_mini_curriculum(td/'curriculum'); run_root=td/'run'
            GovernedEpochTrainer(
                run_root=run_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',
            ).train_cases(2)
            manifest=json.loads((data/'manifest.json').read_text(encoding='utf-8'))
            manifest['test_only_revision']='changed'
            (data/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')
            with self.assertRaisesRegex(TrainingBindingError,'curriculum binding'):
                GovernedEpochTrainer(
                    run_root=run_root,dataset_path=data/'train.jsonl',config=self.config,run_id='R',resume=True,
                )

    def test_h100_check_fails_closed_for_zero_or_multiple_devices(self):
        with self.assertRaisesRegex(SystemExit,'single visible cuda device'):
            EPOCH_RUNNER.verify_single_h100_device('cpu')
        with patch.object(EPOCH_RUNNER.torch.cuda,'is_available',return_value=False):
            with self.assertRaisesRegex(SystemExit,'CUDA is unavailable'):
                EPOCH_RUNNER.verify_single_h100_device('cuda')
        with ExitStack() as stack:
            stack.enter_context(patch.object(EPOCH_RUNNER.torch.cuda,'is_available',return_value=True))
            stack.enter_context(patch.object(EPOCH_RUNNER.torch.cuda,'device_count',return_value=2))
            with self.assertRaisesRegex(SystemExit,'exactly one visible CUDA device'):
                EPOCH_RUNNER.verify_single_h100_device('cuda')

    def test_h100_check_attests_only_one_non_distributed_device(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(EPOCH_RUNNER.torch.cuda,'is_available',return_value=True))
            stack.enter_context(patch.object(EPOCH_RUNNER.torch.cuda,'device_count',return_value=1))
            stack.enter_context(patch.object(EPOCH_RUNNER.torch.cuda,'current_device',return_value=0))
            stack.enter_context(patch.object(EPOCH_RUNNER.torch.cuda,'get_device_name',return_value='NVIDIA H100 80GB HBM3'))
            stack.enter_context(patch.object(EPOCH_RUNNER.torch.distributed,'is_available',return_value=False))
            stack.enter_context(patch.dict(os.environ,{'WORLD_SIZE':'1'}))
            attestation=EPOCH_RUNNER.verify_single_h100_device('cuda')
        self.assertEqual(attestation['visible_cuda_devices'],1)
        self.assertFalse(attestation['distributed_training'])
        self.assertEqual(attestation['device'],'cuda:0')


if __name__=='__main__':
    unittest.main()
