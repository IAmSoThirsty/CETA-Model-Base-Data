from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')

import torch

from history import domain_hash
from training import (
    CheckpointPromotionRegistry, GovernedEpochTrainer, IndependentCheckpointEvaluator,
    TrainingConfig, effective_optimizer_events, file_sha256, promotion_policy_from_risk_material,
)

DATA=ROOT/'data/ceta_curriculum_v3'
RISK_POLICY=ROOT/'data/ceta_architecture_material_v1/governance/operation_risk_ranking.json'
DEFAULT_REPORT=ROOT/'evidence/EPOCH_READINESS_REPORT.json'
RUN_ID='EPOCH-READINESS-SMOKE'


def verify_single_h100_device(device: str) -> dict[str,object]:
    requested=torch.device(device)
    if requested.type!='cuda' or requested.index not in {None,0}:
        raise SystemExit('H100 EPOCH: FAIL - continuation requires the single visible cuda device')
    if not torch.cuda.is_available():
        raise SystemExit('H100 EPOCH: FAIL - CUDA is unavailable; this runner does not select or activate hardware')
    visible_devices=torch.cuda.device_count()
    if visible_devices!=1:
        raise SystemExit(f'H100 EPOCH: FAIL - expected exactly one visible CUDA device, found {visible_devices}')
    current_device=torch.cuda.current_device()
    if current_device!=0:
        raise SystemExit(f'H100 EPOCH: FAIL - expected selected CUDA device index 0, found {current_device}')
    device_name=torch.cuda.get_device_name(0)
    if 'H100' not in device_name.upper():
        raise SystemExit(f'H100 EPOCH: FAIL - expected an H100, found {device_name}')
    if torch.distributed.is_available() and torch.distributed.is_initialized() and torch.distributed.get_world_size()!=1:
        raise SystemExit(f'H100 EPOCH: FAIL - distributed world size is {torch.distributed.get_world_size()}; only one H100 is supported')
    try:
        environment_world_size=int(os.environ.get('WORLD_SIZE','1'))
    except ValueError as exc:
        raise SystemExit('H100 EPOCH: FAIL - WORLD_SIZE is not an integer') from exc
    if environment_world_size!=1:
        raise SystemExit(f'H100 EPOCH: FAIL - WORLD_SIZE is {environment_world_size}; only one H100 is supported')
    attestation={'device':'cuda:0','device_name':device_name,'visible_cuda_devices':1,'distributed_training':False}
    print(f'SINGLE H100 DEVICE VERIFIED: index=0 name={device_name} visible_cuda_devices=1 distributed_training=false')
    return attestation


def _training_config() -> TrainingConfig:
    return TrainingConfig(seed=20260824,learning_rate=0.003,weight_decay=0.0,hidden_dim=32,gradient_clip_norm=1.0)


def _policy_record(policy) -> dict[str,object]:
    return {
        'min_target_accuracy':policy.min_target_accuracy,'min_opcode_accuracy':policy.min_opcode_accuracy,
        'opcode_accuracy_semantics':'selected transition operation matches target operation',
        'min_legal_selection_rate':policy.min_legal_selection_rate,'max_mean_transition_loss':policy.max_mean_transition_loss,
        'operation_target_accuracy':dict(policy.operation_target_accuracy),
        'zero_illegal_selection_operations':list(policy.zero_illegal_selection_operations),
    }


def _run_continuation(
    args: argparse.Namespace,
    *,
    run_root: Path,
    train_path: Path,
    validation_path: Path,
    report_path: Path,
    device_attestation: dict[str,object],
) -> None:
    if not run_root.is_dir() or not (run_root/'training-events.jsonl').is_file():
        raise SystemExit(f'H100 EPOCH: FAIL - continuation requires an existing governed run root: {run_root}')
    config=_training_config()
    trainer=GovernedEpochTrainer(
        run_root=run_root,dataset_path=train_path,config=config,run_id=RUN_ID,resume=True,device=args.device,
    )
    base_checkpoint=trainer.checkpoint
    if base_checkpoint is None:
        raise SystemExit('H100 EPOCH: FAIL - continuation base checkpoint is unavailable')
    final_checkpoint=trainer.train_additional_epochs(
        args.additional_epochs,expected_base_checkpoint_sha256=args.from_checkpoint_sha256,
    )
    evaluator=IndependentCheckpointEvaluator(config=config,device=args.device)
    validation=evaluator.evaluate(final_checkpoint.path,validation_path,split='validation')
    strict_policy=promotion_policy_from_risk_material(
        RISK_POLICY,min_target_accuracy=0.95,min_opcode_accuracy=0.95,
        min_legal_selection_rate=0.99,max_mean_transition_loss=1.0,
    )
    promotion_registry=CheckpointPromotionRegistry(run_root/'promotion',trainer.ledger)
    promotion_status=promotion_registry.decide(final_checkpoint,validation,strict_policy)
    trainer.ledger.verify()
    event_counts=Counter(event['event_type'] for event in trainer.ledger.events)
    report={
        'schema_version':2,
        'report_type':'CETA_EPOCH_CONTINUATION',
        'status':'PASS',
        'torch_version':torch.__version__,
        'device_attestation':device_attestation,
        'run_id':RUN_ID,
        'additional_epochs':args.additional_epochs,
        'base_checkpoint':base_checkpoint.to_dict(),
        'final_checkpoint':final_checkpoint.to_dict(),
        'curriculum_binding':trainer.binding.to_dict(),
        'dataset':{
            'train_sha256':file_sha256(train_path),
            'validation_sha256':file_sha256(validation_path),
            'train_cases':len(trainer.cases),
        },
        'training_evidence':{
            'event_root':trainer.ledger.current_root,
            'event_count':len(trainer.ledger.events),
            'event_type_counts':dict(sorted(event_counts.items())),
            'target_epoch_index':base_checkpoint.cursor.epoch_index+args.additional_epochs,
            'target_global_step':base_checkpoint.cursor.global_step+args.additional_epochs*len(trainer.cases),
            'checkpoint_each_epoch':True,
            'cross_process_resume':True,
        },
        'validation':{**validation.body(),'evaluation_hash':validation.evaluation_hash},
        'promotion_gate':{'policy':_policy_record(strict_policy),'outcome':promotion_status},
        'heldout_evaluation':{'status':'NOT_RUN','reason':'reserved from iterative continuation decisions'},
        'claim_boundary':{
            'single_h100_only':True,'distributed_training':False,'hardware_activated_by_runner':False,
            'controlled_evaluation_optimizer_trained':False,'production_model_quality_claimed':False,
        },
    }
    report['report_hash']=domain_hash(report,domain='CETA/EPOCH_CONTINUATION_REPORT/v2')
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print('CETA EPOCH CONTINUATION: PASS')
    print(f'additional_epochs={args.additional_epochs} final_epoch_index={final_checkpoint.cursor.epoch_index} final_global_step={final_checkpoint.cursor.global_step}')
    print(f'final_checkpoint_sha256={final_checkpoint.sha256}')
    print(f'curriculum_manifest_sha256={final_checkpoint.cursor.curriculum_manifest_sha256}')
    print(f'curriculum_splits_sha256={final_checkpoint.cursor.curriculum_splits_sha256}')
    print(
        f'validation_target_accuracy={validation.target_accuracy:.6f} '
        f'validation_opcode_accuracy={validation.opcode_accuracy:.6f} '
        f'validation_legal_rate={validation.legal_selection_rate:.6f}'
    )
    print(f'promotion_outcome={promotion_status}')
    print('visible_cuda_devices=1 distributed_training=false')
    print(f'run_root={run_root}')
    print(f'report={report_path}')


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--device',default='cpu',help='Torch device for training and independent evaluation (for example cpu or cuda)')
    parser.add_argument('--run-root',help='Durable checkpoint/ledger directory; omitted only for the disposable reference smoke run')
    parser.add_argument('--report-output',help='Report destination; defaults to the packaged reference report')
    parser.add_argument('--additional-epochs',type=int,help='Continue an existing committed run for this many additional full epochs')
    parser.add_argument('--from-checkpoint-sha256',help='Optional exact base checkpoint binding; makes continuation retries idempotent')
    args=parser.parse_args()
    durable_root=Path(args.run_root).expanduser().resolve() if args.run_root else None
    if args.additional_epochs is not None and args.additional_epochs < 1:
        raise SystemExit('H100 EPOCH: FAIL - --additional-epochs must be a positive integer')
    if args.from_checkpoint_sha256 and args.additional_epochs is None:
        raise SystemExit('H100 EPOCH: FAIL - --from-checkpoint-sha256 requires --additional-epochs')
    if args.additional_epochs is not None and durable_root is None:
        raise SystemExit('H100 EPOCH: FAIL - continuation requires --run-root')
    requested_device=torch.device(args.device)
    if args.additional_epochs is not None and requested_device.type!='cuda':
        raise SystemExit('H100 EPOCH: FAIL - continuation requires --device cuda')
    device_attestation=None
    if requested_device.type=='cuda':
        device_attestation=verify_single_h100_device(args.device)

    train_path=DATA/'train.jsonl'; validation_path=DATA/'validation.jsonl'; heldout_path=DATA/'heldout.jsonl'
    if args.additional_epochs is not None:
        report_path=(
            Path(args.report_output).expanduser().resolve()
            if args.report_output else durable_root/'EPOCH_CONTINUATION_REPORT.json'
        )
        _run_continuation(
            args,run_root=durable_root,train_path=train_path,validation_path=validation_path,
            report_path=report_path,device_attestation=device_attestation or {},
        )
        return
    report_path=Path(args.report_output).expanduser().resolve() if args.report_output else DEFAULT_REPORT
    if durable_root and durable_root.exists() and any(durable_root.iterdir()):
        raise SystemExit(f'EPOCH READINESS: FAIL - durable run root is not empty: {durable_root}')

    split_manifest=json.loads((DATA/'splits.json').read_text(encoding='utf-8'))
    curriculum_manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    train_ids=set(split_manifest['case_splits']['train'])
    validation_ids=set(split_manifest['case_splits']['validation'])
    heldout_ids=set(split_manifest['case_splits']['heldout'])
    if train_ids&validation_ids or train_ids&heldout_ids or validation_ids&heldout_ids:
        raise SystemExit('EPOCH READINESS: FAIL - split overlap')

    config=_training_config()
    pause_after=173
    full_epoch_cases=len(train_ids)
    run_context=nullcontext(None) if durable_root else tempfile.TemporaryDirectory(prefix='ceta-epoch-readiness-')
    with run_context as td:
        run_root=durable_root or Path(td)/'run'
        first=GovernedEpochTrainer(run_root=run_root,dataset_path=train_path,config=config,run_id=RUN_ID,device=args.device)
        pause_checkpoint=first.train_cases(pause_after)
        if pause_checkpoint.cursor.global_step != pause_after or pause_checkpoint.cursor.epoch_index != 0:
            raise SystemExit('EPOCH READINESS: FAIL - pause cursor mismatch')
        first.ledger.verify()

        resumed=GovernedEpochTrainer(run_root=run_root,dataset_path=train_path,config=config,run_id=RUN_ID,resume=True,device=args.device)
        final_checkpoint=resumed.train_cases(full_epoch_cases-pause_after)
        if final_checkpoint.cursor.global_step != full_epoch_cases or final_checkpoint.cursor.epoch_index != 1 or final_checkpoint.cursor.next_case_offset != 0:
            raise SystemExit('EPOCH READINESS: FAIL - resumed epoch did not close exactly')
        resumed.ledger.verify()

        optimizer_events=list(effective_optimizer_events(resumed.ledger.events))
        trained_case_ids=[e['payload']['case_id'] for e in optimizer_events]
        if len(optimizer_events)!=full_epoch_cases or set(trained_case_ids)!=train_ids:
            raise SystemExit('EPOCH READINESS: FAIL - optimizer receipts do not cover exact training split')
        if set(trained_case_ids)&validation_ids or set(trained_case_ids)&heldout_ids:
            raise SystemExit('EPOCH READINESS: FAIL - evaluation split leaked into optimizer receipts')

        evaluator=IndependentCheckpointEvaluator(config=config,device=args.device)
        validation=evaluator.evaluate(final_checkpoint.path,validation_path,split='validation')
        strict_policy=promotion_policy_from_risk_material(
            RISK_POLICY,
            min_target_accuracy=0.95,
            min_opcode_accuracy=0.95,
            min_legal_selection_rate=0.99,
            max_mean_transition_loss=1.0,
        )
        promotion_registry=CheckpointPromotionRegistry(run_root/'promotion',resumed.ledger)
        promotion_status=promotion_registry.decide(final_checkpoint,validation,strict_policy)
        heldout=evaluator.evaluate(final_checkpoint.path,heldout_path,split='heldout')

        event_counts=Counter(e['event_type'] for e in resumed.ledger.events)
        report={
            'schema_version':2,
            'readiness_target':'CETA epoch start/pause/resume/evaluate gate',
            'status':'PASS',
            'torch_version':torch.__version__,
            'device':str(resumed.device),
            'config':config.to_dict(),
            'config_hash':config.config_hash,
            'dataset':{
                'generator_id':curriculum_manifest['generator_id'],
                'manifest_sha256':file_sha256(DATA/'manifest.json'),'splits_sha256':file_sha256(DATA/'splits.json'),
                'train_sha256':file_sha256(train_path),'validation_sha256':file_sha256(validation_path),'heldout_sha256':file_sha256(heldout_path),
                'train_cases':len(train_ids),'validation_cases':len(validation_ids),'heldout_cases':len(heldout_ids),
            },
            'pause':pause_checkpoint.to_dict(),
            'resume':{
                'remaining_cases':full_epoch_cases-pause_after,
                'final_checkpoint':final_checkpoint.to_dict(),
                'final_epoch_index':final_checkpoint.cursor.epoch_index,
                'final_global_step':final_checkpoint.cursor.global_step,
            },
            'training_evidence':{
                'event_root':resumed.ledger.current_root,
                'event_count':len(resumed.ledger.events),
                'event_type_counts':dict(sorted(event_counts.items())),
                'optimizer_receipts':len(optimizer_events),
                'exact_train_split_coverage':True,
                'evaluation_leakage_detected':False,
                'target_candidate_injection':False,
                'unique_vm_legal_generated_target':True,
                'source_context_anchors_actionable':False,
                'checkpoint_required_before_successful_return':True,
                'resume_authority':'append-only CHECKPOINT_SAVED ledger event',
            },
            'validation':{**validation.body(),'evaluation_hash':validation.evaluation_hash},
            'promotion_gate':{
                'policy':_policy_record(strict_policy),
                'outcome':promotion_status,
                'note':'Smoke checkpoint quality is not a production-model claim. Strict promotion is intentionally independent of epoch-readiness.',
            },
            'heldout':{**heldout.body(),'evaluation_hash':heldout.evaluation_hash},
            'claim_boundary':{
                'epoch_pipeline_ready':True,
                'target_blind_action_space':True,
                'unique_vm_legal_generated_target':True,
                'normal_inference_accepts_caller_candidates':False,
                'production_model_quality_claimed':False,
                'real_world_fact_knowledge_trained':False,
                'language_generation_trained':False,
                'raw_source_prose_trained':False,
                'public_defensive_structural_derivatives_trained':True,
                'controlled_evaluation_bound':True,
                'controlled_evaluation_optimizer_trained':False,
                'known_exposed_evaluation_case_count':1,
                'clean_unseen_evaluation_case_count':59,
            },
        }
        report['report_hash']=domain_hash(report,domain='CETA/EPOCH_READINESS_REPORT/v2')
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')

    print('CETA EPOCH READINESS: PASS')
    print(f"train_cases={full_epoch_cases} pause_after={pause_after} optimizer_receipts={full_epoch_cases}")
    print(
        f"validation_target_accuracy={validation.target_accuracy:.6f} "
        f"validation_opcode_accuracy={validation.opcode_accuracy:.6f} "
        f"validation_legal_rate={validation.legal_selection_rate:.6f}"
    )
    print(f"promotion_outcome={promotion_status}")
    print(
        f"heldout_target_accuracy={heldout.target_accuracy:.6f} "
        f"heldout_opcode_accuracy={heldout.opcode_accuracy:.6f} "
        f"heldout_legal_rate={heldout.legal_selection_rate:.6f}"
    )
    print(f"run_root={run_root}")
    print(f"report={report_path}")


if __name__=='__main__': main()
