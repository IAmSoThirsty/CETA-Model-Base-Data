from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from history import domain_hash
from training import file_sha256

DEFAULT_REPORT=ROOT/'evidence/EPOCH_READINESS_REPORT.json'
DATA=ROOT/'data/ceta_curriculum_v3'


def fail(msg: str) -> None:
    raise SystemExit(f'EPOCH READINESS REPORT VERIFY: FAIL - {msg}')


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',help='Readiness report to verify; defaults to the packaged reference report')
    args=parser.parse_args()
    report_path=Path(args.report).expanduser().resolve() if args.report else DEFAULT_REPORT
    if not report_path.is_file(): fail(f'report missing: {report_path}')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    claimed=report.get('report_hash')
    body=dict(report); body.pop('report_hash',None)
    expected=domain_hash(body,domain='CETA/EPOCH_READINESS_REPORT/v1')
    if claimed!=expected: fail('report hash mismatch')
    if report.get('status')!='PASS': fail('status is not PASS')

    dataset=report.get('dataset',{})
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    required={split:(manifest['files'][split]['path'],manifest['files'][split]['count']) for split in ('train','validation','heldout')}
    if dataset.get('generator_id')!=manifest.get('generator_id'): fail('curriculum generator mismatch')
    if dataset.get('manifest_sha256')!=file_sha256(DATA/'manifest.json'): fail('curriculum manifest byte hash mismatch')
    if dataset.get('splits_sha256')!=file_sha256(DATA/'splits.json'): fail('curriculum splits byte hash mismatch')
    for split,(name,count) in required.items():
        path=DATA/name
        if dataset.get(f'{split}_cases')!=count: fail(f'{split} case-count mismatch')
        if dataset.get(f'{split}_sha256')!=file_sha256(path): fail(f'{split} byte hash mismatch')

    claim=report.get('claim_boundary',{})
    if claim.get('epoch_pipeline_ready') is not True: fail('epoch pipeline readiness flag absent')
    if claim.get('target_blind_action_space') is not True: fail('target-blind action-space flag absent')
    if claim.get('unique_vm_legal_generated_target') is not True: fail('unique VM-legal generated target flag absent')
    if claim.get('normal_inference_accepts_caller_candidates') is not False: fail('caller candidate inference surface not denied')
    if claim.get('production_model_quality_claimed') is not False: fail('production quality claim must remain false')

    evidence=report.get('training_evidence',{})
    if evidence.get('optimizer_receipts')!=required['train'][1] or evidence.get('exact_train_split_coverage') is not True:
        fail('optimizer receipt coverage mismatch')
    if evidence.get('evaluation_leakage_detected') is not False: fail('evaluation leakage flag is not false')
    if evidence.get('target_candidate_injection') is not False: fail('target candidate injection flag is not false')
    if evidence.get('unique_vm_legal_generated_target') is not True: fail('unique generated-target evidence is absent')
    if evidence.get('source_context_anchors_actionable') is not False: fail('source context anchor action-space boundary mismatch')
    if evidence.get('checkpoint_required_before_successful_return') is not True: fail('mandatory checkpoint flag absent')
    if evidence.get('resume_authority')!='append-only CHECKPOINT_SAVED ledger event': fail('resume authority mismatch')

    for key in ('pause',):
        path=str(report.get(key,{}).get('path',''))
        if not path or '/' in path or '\\' in path: fail(f'{key} checkpoint evidence is location-dependent')
    final_path=str(report.get('resume',{}).get('final_checkpoint',{}).get('path',''))
    if not final_path or '/' in final_path or '\\' in final_path: fail('final checkpoint evidence is location-dependent')

    for split in ('validation','heldout'):
        metrics=report.get(split,{})
        if metrics.get('case_count')!=required[split][1]: fail(f'{split} evaluation case count mismatch')
        if int(metrics.get('hostile_candidate_count',0)) < int(metrics.get('case_count',0)):
            fail(f'{split} hostile candidates were not exercised')
        if int(metrics.get('candidate_count_total',0)) <= int(metrics.get('case_count',0)):
            fail(f'{split} evaluation candidate sets are not competitive')
        if int(metrics.get('singleton_candidate_case_count',-1)) != 0:
            fail(f'{split} evaluation contains singleton candidate cases')
        legal=float(metrics.get('legal_selection_rate',-1.0))
        if not 0.0 <= legal <= 1.0: fail(f'{split} legal selection rate out of range')
        if metrics.get('checkpoint_sha256')!=report['resume']['final_checkpoint']['sha256']:
            fail(f'{split} evaluation is not checkpoint-bound')
    if report.get('promotion_gate',{}).get('outcome') not in {'PROMOTED','QUARANTINED'}:
        fail('promotion outcome missing')
    if claim.get('raw_source_prose_trained') is not False: fail('raw source prose training boundary is not explicit')
    if claim.get('public_defensive_structural_derivatives_trained') is not True: fail('public defensive structural training is not recorded')
    if claim.get('controlled_evaluation_bound') is not True: fail('controlled evaluation binding is absent')
    if claim.get('controlled_evaluation_optimizer_trained') is not False: fail('controlled evaluation optimizer boundary is not explicit')
    if claim.get('known_exposed_evaluation_case_count') != 1: fail('known exposed evaluation count mismatch')
    if claim.get('clean_unseen_evaluation_case_count') != 59: fail('clean unseen evaluation count mismatch')

    policy=report.get('promotion_gate',{}).get('policy',{})
    operation_floors=policy.get('operation_target_accuracy')
    if operation_floors is not None:
        canonical=set(json.loads((ROOT/'registry/ceta_operations.json').read_text(encoding='utf-8'))['operations'])
        if set(operation_floors)!=canonical: fail('operation-specific promotion policy coverage mismatch')
        zero_illegal=set(policy.get('zero_illegal_selection_operations',[]))
        if not zero_illegal <= canonical: fail('zero-illegal-selection policy names unknown operations')
        for split in ('validation','heldout'):
            operation_metrics=report.get(split,{}).get('operation_metrics',{})
            if set(operation_metrics)!=canonical: fail(f'{split} operation metrics coverage mismatch')
            for operation,metrics in operation_metrics.items():
                if int(metrics.get('case_count',0)) < 1: fail(f'{split}/{operation} has no evaluated cases')
                for key in ('target_accuracy','opcode_accuracy','legal_selection_rate'):
                    if not 0.0 <= float(metrics.get(key,-1.0)) <= 1.0: fail(f'{split}/{operation} {key} out of range')
                if int(metrics.get('illegal_selection_count',-1)) < 0: fail(f'{split}/{operation} illegal-selection count invalid')

    print('EPOCH READINESS REPORT VERIFY: PASS')
    print(f"report_hash={claimed} promotion={report['promotion_gate']['outcome']} validation_target={report['validation']['target_accuracy']:.6f} heldout_target={report['heldout']['target_accuracy']:.6f}")
    print(f"report={report_path}")


if __name__=='__main__': main()
