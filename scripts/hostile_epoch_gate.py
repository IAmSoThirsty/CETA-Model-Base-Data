from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from history import domain_hash
from training import (
    GovernedEpochTrainer, IndependentCheckpointEvaluator, TrainingBindingError,
    TrainingConfig, effective_optimizer_events, hash_torch_state, load_cases,
)
from transition_policy import CetaActionSpaceGenerator, NeuralTransitionPolicy, candidate_sequence, world_from_training_case

DATA=ROOT/'data/ceta_curriculum_v2'
REPORT=ROOT/'evidence/EPOCH_HOSTILE_GATE_REPORT.json'


def pkey(p) -> tuple[str,str]:
    return p.operation,json.dumps(dict(p.operands),sort_keys=True,separators=(',',':'))


def must_fail(fn, label: str) -> None:
    try:
        fn()
    except TrainingBindingError:
        return
    raise RuntimeError(f'{label}: expected TrainingBindingError')


def main() -> None:
    checks=[]

    train_sig=inspect.signature(GovernedEpochTrainer.train_cases)
    if 'checkpoint_at_end' in train_sig.parameters:
        raise SystemExit('HOSTILE EPOCH GATE: FAIL - public checkpoint bypass remains')
    checks.append('mandatory_checkpoint_api')

    propose_sig=tuple(inspect.signature(NeuralTransitionPolicy.propose).parameters)
    if propose_sig != ('self','world'):
        raise SystemExit('HOSTILE EPOCH GATE: FAIL - model propose surface accepts external candidates')
    checks.append('target_blind_propose_api')

    all_cases={}
    for split in ('train','validation','heldout'):
        all_cases.update(load_cases(DATA/f'{split}.jsonl'))
    if len(all_cases)!=690:
        raise SystemExit(f'HOSTILE EPOCH GATE: FAIL - expected 690 curriculum cases, got {len(all_cases)}')
    generator=CetaActionSpaceGenerator()
    recovered=0
    for case in all_cases.values():
        target=pkey(case.target_proposal)
        if target in {pkey(p) for p in candidate_sequence(case)}:
            raise SystemExit(f'HOSTILE EPOCH GATE: FAIL - target injected into adversarial candidates: {case.case_id}')
        generated={pkey(p) for p in generator.generate(world_from_training_case(case))}
        if target not in generated:
            raise SystemExit(f'HOSTILE EPOCH GATE: FAIL - target not recoverable without label: {case.case_id}')
        recovered += 1
    checks.append('all_targets_recoverable_without_label_injection')

    cfg=TrainingConfig(seed=99173,learning_rate=0.002,hidden_dim=16)
    with tempfile.TemporaryDirectory(prefix='ceta-hostile-epoch-') as td_raw:
        td=Path(td_raw)

        # Same logical run in different filesystem roots must have identical
        # checkpoint bytes, model state, and canonical evidence root.
        a=GovernedEpochTrainer(run_root=td/'location-a',dataset_path=DATA/'train.jsonl',config=cfg,run_id='LOCATION-INVARIANT')
        b=GovernedEpochTrainer(run_root=td/'location-b',dataset_path=DATA/'train.jsonl',config=cfg,run_id='LOCATION-INVARIANT')
        ca=a.train_cases(4); cb=b.train_cases(4)
        if (ca.sha256,ca.model_hash,a.ledger.current_root)!=(cb.sha256,cb.model_hash,b.ledger.current_root):
            raise SystemExit('HOSTILE EPOCH GATE: FAIL - training evidence depends on filesystem location')
        checks.append('location_independent_training_evidence')

        # A held-out payload renamed to train must still be rejected by the
        # manifest/hash/family binding, not trusted by filename.
        poisoned=td/'poisoned-curriculum'; shutil.copytree(DATA,poisoned)
        shutil.copyfile(poisoned/'heldout.jsonl',poisoned/'train.jsonl')
        must_fail(lambda: GovernedEpochTrainer(run_root=td/'poisoned-run',dataset_path=poisoned/'train.jsonl',config=cfg,run_id='P'), 'renamed heldout')
        checks.append('renamed_heldout_rejected')

        # Checkpoint bytes are bound by the append-only training ledger.
        tamper=GovernedEpochTrainer(run_root=td/'tamper',dataset_path=DATA/'train.jsonl',config=cfg,run_id='T')
        cp=tamper.train_cases(1); path=Path(cp.path)
        raw=bytearray(path.read_bytes()); raw[len(raw)//2]^=1; path.write_bytes(raw)
        must_fail(lambda: GovernedEpochTrainer(run_root=td/'tamper',dataset_path=DATA/'train.jsonl',config=cfg,run_id='T',resume=True), 'checkpoint tamper')
        checks.append('checkpoint_tamper_rejected')

        # Simulated hard crash after an optimizer receipt but before cursor /
        # checkpoint commit. The tail must be orphaned, then deterministic replay
        # must converge to the uninterrupted model state.
        baseline=GovernedEpochTrainer(run_root=td/'baseline',dataset_path=DATA/'train.jsonl',config=cfg,run_id='CRASH')
        baseline.train_cases(5)
        expected=hash_torch_state(baseline.model.state_dict(),domain='CETA/MODEL_STATE/v1')
        crashed=GovernedEpochTrainer(run_root=td/'crash',dataset_path=DATA/'train.jsonl',config=cfg,run_id='CRASH')
        crashed.train_cases(3)
        order=crashed._epoch_order(crashed.cursor.epoch_index)
        crashed._train_one(crashed.cases[order[crashed.cursor.next_case_offset]])
        resumed=GovernedEpochTrainer(run_root=td/'crash',dataset_path=DATA/'train.jsonl',config=cfg,run_id='CRASH',resume=True)
        resumed.train_cases(2)
        actual=hash_torch_state(resumed.model.state_dict(),domain='CETA/MODEL_STATE/v1')
        if actual!=expected or len(effective_optimizer_events(resumed.ledger.events))!=5:
            raise SystemExit('HOSTILE EPOCH GATE: FAIL - crash replay diverged or orphaned receipt remained effective')
        if not any(e['event_type']=='RECOVERY_REWIND' for e in resumed.ledger.events):
            raise SystemExit('HOSTILE EPOCH GATE: FAIL - uncommitted crash tail was not explicitly orphaned')
        checks.append('crash_tail_orphan_and_deterministic_replay')

        # Evaluator must reject a forged sidecar even when checkpoint bytes are
        # unchanged.
        evalrun=GovernedEpochTrainer(run_root=td/'eval',dataset_path=DATA/'train.jsonl',config=cfg,run_id='E')
        ecp=evalrun.train_cases(1)
        sidecar=Path(ecp.path).with_suffix(Path(ecp.path).suffix+'.json')
        meta=json.loads(sidecar.read_text(encoding='utf-8')); meta['sha256']='0'*64
        sidecar.write_text(json.dumps(meta),encoding='utf-8',newline='\n')
        must_fail(lambda: IndependentCheckpointEvaluator(config=cfg).evaluate(ecp.path,DATA/'validation.jsonl',split='validation'), 'evaluation sidecar tamper')
        checks.append('evaluation_sidecar_tamper_rejected')

    body={
        'schema_version':1,
        'status':'PASS',
        'gate':'CETA final integrated hostile epoch gate',
        'curriculum_cases_checked':recovered,
        'operation_count':23,
        'checks':checks,
        'claim_boundary':{
            'pipeline_integrity_tested':True,
            'production_model_quality_claimed':False,
            'general_reasoning_claimed':False,
            'real_world_grounding_claimed':False,
        },
    }
    body['report_hash']=domain_hash(body,domain='CETA/EPOCH_HOSTILE_GATE_REPORT/v1')
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(body,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print('CETA HOSTILE EPOCH GATE: PASS')
    print(f"checks={len(checks)} curriculum_cases={recovered} report_hash={body['report_hash']}")


if __name__=='__main__':
    main()
