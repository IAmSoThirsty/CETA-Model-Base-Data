from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT=Path(__file__).resolve().parents[1]
DATA_ROOT=(ROOT/'data').resolve()
sys.path.insert(0,str(ROOT/'src'))

from ceta import ConstitutionalVM, VmDisposition
from history import EpistemicObject, ProjectionSnapshot, StateDelta, Supersession, domain_hash
from training import CetaWorldCurriculum, TransitionTrainingCase, structural_world_fingerprint
from transition_policy.actions import CetaActionSpaceGenerator
from transition_policy.encoder import WorldView

FORBIDDEN_LANGUAGE_KEYS=frozenset({'prompt','response','answer','completion','expected_output','expected_text','assistant_message','user_message'})
REQUIRED_FAILURE_SURFACES=frozenset({
    'replay_fault','provenance_corruption','missing_defeaters','improper_scope',
    'illegal_authorization','authority_failure','belief_corruption','objective_substitution_failure',
    'invariant_violation','structural_output_failure',
})


def confined_data_root(path: Path) -> Path:
    candidate=path.resolve(strict=True)
    if path.is_symlink() or not candidate.is_dir():
        raise ValueError(f'curriculum root must be a regular directory: {path}')
    if candidate==DATA_ROOT or not candidate.is_relative_to(DATA_ROOT):
        raise ValueError(f'curriculum root must be a child of {DATA_ROOT}: {candidate}')
    return candidate


def confined_file(base: Path, relative: str) -> Path:
    fragment=Path(relative)
    if fragment.is_absolute() or '..' in fragment.parts:
        raise ValueError(f'curriculum manifest path is unsafe: {relative}')
    candidate=(base/fragment).resolve(strict=True)
    if candidate==base or not candidate.is_relative_to(base) or candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f'curriculum file is outside the bound root: {relative}')
    return candidate


def sha256(base: Path, relative: str) -> str:
    path=confined_file(base,relative)
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot_from_record(record: Mapping[str,Any]) -> ProjectionSnapshot:
    state=record['state']
    objects=tuple(EpistemicObject.from_dict(x) for x in state['active_objects'])
    supersessions=tuple(Supersession(**x) for x in state['supersessions'])
    payload={
        'active_objects':[{'object_id':o.object_id,'object_type':o.object_type,'object_hash':o.object_hash} for o in sorted(objects,key=lambda x:x.object_id)],
        'supersessions':[x.to_dict() for x in sorted(supersessions,key=lambda x:(x.old_object_id,x.new_object_id))],
    }
    expected=domain_hash(payload,domain='CETA/STATE_PROJECTION/v1')
    if expected != state['state_ref']:
        raise ValueError('training state_ref does not match deterministic projection')
    return ProjectionSnapshot(expected,objects,supersessions)


def preview_snapshot(snapshot: ProjectionSnapshot, delta: StateDelta) -> str:
    active={o.object_id:o for o in snapshot.active_objects}
    created={o.object_id:o for o in delta.creates}
    if len(created)!=len(delta.creates):
        raise ValueError('duplicate create identity in target state delta')
    if set(created)&set(active):
        raise ValueError('target delta reuses active object identity')
    for edge in delta.supersedes:
        if edge.old_object_id not in active:
            raise ValueError('target delta supersedes inactive object')
        if edge.new_object_id not in created:
            raise ValueError('target delta supersession target is not created in transition')
    active.update(created)
    for edge in delta.supersedes:
        active.pop(edge.old_object_id,None)
    supersessions=tuple(snapshot.supersessions)+tuple(delta.supersedes)
    payload={
        'active_objects':[{'object_id':o.object_id,'object_type':o.object_type,'object_hash':o.object_hash} for o in sorted(active.values(),key=lambda x:x.object_id)],
        'supersessions':[x.to_dict() for x in sorted(supersessions,key=lambda x:(x.old_object_id,x.new_object_id))],
    }
    return domain_hash(payload,domain='CETA/STATE_PROJECTION/v1')


def scan_forbidden_keys(value: Any, path: str='record') -> list[str]:
    errors=[]
    if isinstance(value,Mapping):
        for k,v in value.items():
            if str(k).lower() in FORBIDDEN_LANGUAGE_KEYS:
                errors.append(f'{path}.{k}')
            errors.extend(scan_forbidden_keys(v,f'{path}.{k}'))
    elif isinstance(value,list):
        for i,v in enumerate(value): errors.extend(scan_forbidden_keys(v,f'{path}[{i}]'))
    return errors


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default=str(ROOT/'data/ceta_curriculum_v2'))
    args=parser.parse_args()
    base=confined_data_root(Path(args.root))
    manifest=json.loads(confined_file(base,'manifest.json').read_text(encoding='utf-8'))
    splits=json.loads(confined_file(base,'splits.json').read_text(encoding='utf-8'))
    errors=[]

    if manifest.get('generator_id')!='CETA_WORLD_CURRICULUM/v2': errors.append('generator_id mismatch')
    if manifest.get('operation_count')!=23: errors.append('operation_count is not 23')
    if manifest.get('world_family_count')!=230: errors.append('world_family_count is not 230')
    if manifest.get('case_count')!=690: errors.append('case_count is not 690')
    if manifest.get('illegal_alternative_count')!=2760: errors.append('illegal_alternative_count is not 2760')
    if manifest.get('splits_sha256')!=sha256(base,'splits.json'): errors.append('splits.json hash mismatch')

    all_cases={}; split_of_case={}; split_of_family={}; fingerprint_family={}; family_fingerprints=defaultdict(set); family_state_refs=defaultdict(set)
    failure_tags=set(); operation_split_counts=defaultdict(lambda:defaultdict(int))
    vm=ConstitutionalVM()

    for split in ('train','validation','heldout'):
        info=manifest['files'][split]; path=confined_file(base,str(info['path']))
        if sha256(base,str(info['path']))!=info['sha256']: errors.append(f'{split} file hash mismatch')
        records=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if len(records)!=info['count']: errors.append(f'{split} count mismatch')
        for raw in records:
            bad=scan_forbidden_keys(raw)
            if bad: errors.append(f"{raw.get('case_id')} language-target keys: {bad}")
            try:
                case=TransitionTrainingCase.from_record(raw)
                snapshot=snapshot_from_record(raw)
            except Exception as exc:
                errors.append(f"{raw.get('case_id')} record/state invalid: {exc}"); continue
            if case.case_id in all_cases: errors.append(f'duplicate case_id {case.case_id}')
            all_cases[case.case_id]=case; split_of_case[case.case_id]=split
            previous=split_of_family.setdefault(case.world_family_id,split)
            if previous!=split: errors.append(f'world-family leakage {case.world_family_id}: {previous}/{split}')
            family_fingerprints[case.world_family_id].add(case.structural_fingerprint)
            family_state_refs[case.world_family_id].add(case.state_ref)
            fp_owner=fingerprint_family.setdefault(case.structural_fingerprint,case.world_family_id)
            if fp_owner!=case.world_family_id: errors.append(f'structural fingerprint crosses families {fp_owner}/{case.world_family_id}')
            recomputed=structural_world_fingerprint(
                state=raw['state'], evidence_view=raw['evidence_view'], identity_view=raw['identity_view'],
                authority_view=raw['authority_view'], proposal_context=raw['proposal_context'], target_transition=raw['target_transition'],
                required_defeater_count=len(raw['required_defeater_refs']),
            )
            if recomputed!=case.structural_fingerprint: errors.append(f'{case.case_id} structural fingerprint mismatch')
            target=case.target_proposal
            world=WorldView(snapshot=snapshot,evidence_view=raw['evidence_view'],identity_view=raw['identity_view'],authority_view=raw['authority_view'],proposal_context=raw['proposal_context'],now_epoch_ms=raw['now_epoch_ms'])
            action_space=CetaActionSpaceGenerator().generate(world)
            target_key=json.dumps({'operation':target.operation,'operands':dict(target.operands)},sort_keys=True,separators=(',',':'))
            action_keys={json.dumps({'operation':p.operation,'operands':dict(p.operands)},sort_keys=True,separators=(',',':')) for p in action_space}
            if target_key not in action_keys:
                errors.append(f'{case.case_id} target is not recoverable from target-blind action space')
            decision=vm.evaluate(target,projected_snapshot=snapshot,admitted_evidence_view=raw['evidence_view'],identity_view=raw['identity_view'],authority_snapshot=raw['authority_view'],now_epoch_ms=raw['now_epoch_ms'],constitutional_epoch='curriculum-v2')
            if decision.disposition is not VmDisposition.LEGAL:
                errors.append(f'{case.case_id} target not LEGAL: {decision.disposition}:{decision.reason_code}')
            else:
                try: preview_snapshot(snapshot,decision.state_delta)
                except Exception as exc: errors.append(f'{case.case_id} target projection replay failed: {exc}')
            for alt in case.illegal_alternatives:
                alt_decision=vm.evaluate(alt.proposal,projected_snapshot=snapshot,admitted_evidence_view=raw['evidence_view'],identity_view=raw['identity_view'],authority_snapshot=raw['authority_view'],now_epoch_ms=raw['now_epoch_ms'],constitutional_epoch='curriculum-v2')
                if alt_decision.disposition is VmDisposition.LEGAL:
                    errors.append(f'{case.case_id}/{alt.alternative_id} illegal alternative became LEGAL')
                if alt_decision.disposition.value!=alt.expected_disposition or alt_decision.reason_code!=alt.expected_reason_code:
                    errors.append(f'{case.case_id}/{alt.alternative_id} oracle mismatch')
                failure_tags.update(alt.failure_tags)
            failure_tags.update(case.failure_surface_tags)
            operation_split_counts[target.operation][split]+=1

    expected_cases=set().union(*(set(v) for v in splits['case_splits'].values()))
    if expected_cases!=set(all_cases): errors.append('splits.json case set mismatch')
    for split,ids in splits['case_splits'].items():
        if set(ids)!={cid for cid,s in split_of_case.items() if s==split}: errors.append(f'splits.json {split} case membership mismatch')
    for split,families in splits['family_splits'].items():
        if set(families)!={fam for fam,s in split_of_family.items() if s==split}: errors.append(f'splits.json {split} family membership mismatch')
    if any(len(v)!=1 for v in family_fingerprints.values()): errors.append('variants within a world family do not share one structural fingerprint')
    if any(len(v)!=3 for v in family_state_refs.values()): errors.append('world-family identity-renamed variants are not state-distinct')
    missing_surfaces=REQUIRED_FAILURE_SURFACES-failure_tags
    if missing_surfaces: errors.append(f'missing hostile failure surfaces: {sorted(missing_surfaces)}')
    for op in CetaWorldCurriculum.OPERATIONS:
        counts=operation_split_counts[op]
        if counts!={'train':24,'validation':3,'heldout':3}:
            errors.append(f'{op} split counts unexpected: {dict(counts)}')

    if errors:
        print('CETA CURRICULUM VALIDATION: FAIL')
        for error in errors[:100]: print(' -',error)
        if len(errors)>100: print(f' - ... {len(errors)-100} additional errors')
        raise SystemExit(1)
    print('CETA CURRICULUM VALIDATION: PASS')
    print(f"cases={len(all_cases)} families={len(split_of_family)} fingerprints={len(fingerprint_family)} negatives={sum(len(c.illegal_alternatives) for c in all_cases.values())}")
    print(f"train={len(splits['case_splits']['train'])} validation={len(splits['case_splits']['validation'])} heldout={len(splits['case_splits']['heldout'])}")
    print(f"failure_surfaces={len(failure_tags)} operations={len(operation_split_counts)}")


if __name__=='__main__':
    main()
