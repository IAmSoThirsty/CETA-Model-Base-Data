from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

import torch

from history import domain_hash
from training import (
    CheckpointPromotionRegistry, GovernedEpochTrainer, IndependentCheckpointEvaluator,
    TrainingConfig, effective_optimizer_events, file_sha256, promotion_policy_from_risk_material,
)

DATA=ROOT/'data/ceta_curriculum_v2'
RISK_POLICY=ROOT/'data/ceta_architecture_material_v1/governance/operation_risk_ranking.json'
DEFAULT_REPORT=ROOT/'evidence/EPOCH_READINESS_REPORT.json'


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--device',default='cpu',help='Torch device for training and independent evaluation (for example cpu or cuda)')
    parser.add_argument('--run-root',help='Durable checkpoint/ledger directory; omitted only for the disposable reference smoke run')
    parser.add_argument('--report-output',help='Report destination; defaults to the packaged reference report')
    args=parser.parse_args()
    report_path=Path(args.report_output).expanduser().resolve() if args.report_output else DEFAULT_REPORT
    durable_root=Path(args.run_root).expanduser().resolve() if args.run_root else None
    if durable_root and durable_root.exists() and any(durable_root.iterdir()):
        raise SystemExit(f'EPOCH READINESS: FAIL - durable run root is not empty: {durable_root}')

    train_path=DATA/'train.jsonl'; validation_path=DATA/'validation.jsonl'; heldout_path=DATA/'heldout.jsonl'
    split_manifest=json.loads((DATA/'splits.json').read_text(encoding='utf-8'))
    train_ids=set(split_manifest['case_splits']['train'])
    validation_ids=set(split_manifest['case_splits']['validation'])
    heldout_ids=set(split_manifest['case_splits']['heldout'])
    if train_ids&validation_ids or train_ids&heldout_ids or validation_ids&heldout_ids:
        raise SystemExit('EPOCH READINESS: FAIL - split overlap')

    config=TrainingConfig(seed=20260824,learning_rate=0.003,weight_decay=0.0,hidden_dim=32,gradient_clip_norm=1.0)
    pause_after=173
    full_epoch_cases=len(train_ids)
    run_context=nullcontext(None) if durable_root else tempfile.TemporaryDirectory(prefix='ceta-epoch-readiness-')
    with run_context as td:
        run_root=durable_root or Path(td)/'run'
        first=GovernedEpochTrainer(run_root=run_root,dataset_path=train_path,config=config,run_id='EPOCH-READINESS-SMOKE',device=args.device)
        pause_checkpoint=first.train_cases(pause_after)
        if pause_checkpoint.cursor.global_step != pause_after or pause_checkpoint.cursor.epoch_index != 0:
            raise SystemExit('EPOCH READINESS: FAIL - pause cursor mismatch')
        first.ledger.verify()

        resumed=GovernedEpochTrainer(run_root=run_root,dataset_path=train_path,config=config,run_id='EPOCH-READINESS-SMOKE',resume=True,device=args.device)
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
            'schema_version':1,
            'readiness_target':'CETA epoch start/pause/resume/evaluate gate',
            'status':'PASS',
            'torch_version':torch.__version__,
            'device':str(resumed.device),
            'config':config.to_dict(),
            'config_hash':config.config_hash,
            'dataset':{
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
                'checkpoint_required_before_successful_return':True,
                'resume_authority':'append-only CHECKPOINT_SAVED ledger event',
            },
            'validation':{**validation.body(),'evaluation_hash':validation.evaluation_hash},
            'promotion_gate':{
                'policy':{
                    'min_target_accuracy':strict_policy.min_target_accuracy,'min_opcode_accuracy':strict_policy.min_opcode_accuracy,
                    'min_legal_selection_rate':strict_policy.min_legal_selection_rate,'max_mean_transition_loss':strict_policy.max_mean_transition_loss,
                    'operation_target_accuracy':dict(strict_policy.operation_target_accuracy),
                    'zero_illegal_selection_operations':list(strict_policy.zero_illegal_selection_operations),
                },
                'outcome':promotion_status,
                'note':'Smoke checkpoint quality is not a production-model claim. Strict promotion is intentionally independent of epoch-readiness.',
            },
            'heldout':{**heldout.body(),'evaluation_hash':heldout.evaluation_hash},
            'claim_boundary':{
                'epoch_pipeline_ready':True,
                'target_blind_action_space':True,
                'normal_inference_accepts_caller_candidates':False,
                'production_model_quality_claimed':False,
                'real_world_fact_knowledge_trained':False,
                'language_generation_trained':False,
            },
        }
        report['report_hash']=domain_hash(report,domain='CETA/EPOCH_READINESS_REPORT/v1')
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')

    print('CETA EPOCH READINESS: PASS')
    print(f"train_cases={full_epoch_cases} pause_after={pause_after} optimizer_receipts={full_epoch_cases}")
    print(f"validation_target_accuracy={validation.target_accuracy:.6f} validation_legal_rate={validation.legal_selection_rate:.6f}")
    print(f"promotion_outcome={promotion_status}")
    print(f"heldout_target_accuracy={heldout.target_accuracy:.6f} heldout_legal_rate={heldout.legal_selection_rate:.6f}")
    print(f"run_root={run_root}")
    print(f"report={report_path}")


if __name__=='__main__': main()
