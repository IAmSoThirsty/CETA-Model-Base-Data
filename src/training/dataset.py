from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from .model import TransitionTrainingCase
from .source_policy import WorldDatasetPartition, partition_world_families


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


class TransitionDatasetWriter:
    """Writes state->transition records only; no conversational target text."""

    @staticmethod
    def write_jsonl(path: str | Path, cases: Iterable[TransitionTrainingCase]) -> int:
        target=Path(path)
        target.parent.mkdir(parents=True,exist_ok=True)
        count=0
        with target.open('w',encoding='utf-8',newline='\n') as handle:
            for case in cases:
                handle.write(json.dumps(case.to_record(),sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n')
                count += 1
        return count


class WorldCurriculumArtifactWriter:
    """Materializes leakage-safe train/validation/heldout world datasets."""

    @classmethod
    def write(
        cls,
        root: str | Path,
        cases: Iterable[TransitionTrainingCase],
        *,
        generator_id: str = 'CETA_WORLD_CURRICULUM/v2',
    ) -> dict:
        destination=Path(root)
        destination.mkdir(parents=True,exist_ok=True)
        materialized=tuple(cases)
        partition=partition_world_families(materialized)
        by_id={case.case_id:case for case in materialized}
        split_case_ids={
            'train':partition.train,
            'validation':partition.validation,
            'heldout':partition.heldout,
        }
        split_family_ids={
            'train':partition.train_families,
            'validation':partition.validation_families,
            'heldout':partition.heldout_families,
        }
        files={}
        for split,ids in split_case_ids.items():
            path=destination/f'{split}.jsonl'
            count=TransitionDatasetWriter.write_jsonl(path,(by_id[x] for x in ids))
            files[split]={
                'path':path.name,
                'count':count,
                'sha256':_sha256(path),
            }

        operation_counts: dict[str,dict[str,int]]={}
        for split,ids in split_case_ids.items():
            for case_id in ids:
                op=by_id[case_id].target_proposal.operation
                operation_counts.setdefault(op,{'train':0,'validation':0,'heldout':0})[split]+=1

        failure_tag_counts: dict[str,int]={}
        for case in materialized:
            tags=set(case.failure_surface_tags)
            for alt in case.illegal_alternatives:
                tags.update(alt.failure_tags)
            for tag in tags:
                failure_tag_counts[tag]=failure_tag_counts.get(tag,0)+1

        split_map={
            'schema_version':1,
            'generator_id':generator_id,
            'case_splits':{k:list(v) for k,v in split_case_ids.items()},
            'family_splits':{k:list(v) for k,v in split_family_ids.items()},
        }
        split_path=destination/'splits.json'
        split_path.write_text(json.dumps(split_map,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')

        manifest={
            'schema_version':1,
            'generator_id':generator_id,
            'case_count':len(materialized),
            'world_family_count':len(set(c.world_family_id for c in materialized)),
            'structural_fingerprint_count':len(set(c.structural_fingerprint for c in materialized)),
            'operation_count':len(operation_counts),
            'illegal_alternative_count':sum(len(c.illegal_alternatives) for c in materialized),
            'files':files,
            'splits_sha256':_sha256(split_path),
            'operation_counts':dict(sorted(operation_counts.items())),
            'failure_tag_counts':dict(sorted(failure_tag_counts.items())),
        }
        manifest_path=destination/'manifest.json'
        manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
        return manifest
