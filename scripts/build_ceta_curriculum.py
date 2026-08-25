from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from training import CetaWorldCurriculum, WorldCurriculumArtifactWriter


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'data/ceta_curriculum_v2'))
    parser.add_argument('--families-per-operation',type=int,default=10)
    parser.add_argument('--variants-per-family',type=int,default=3)
    args=parser.parse_args()
    cases=CetaWorldCurriculum(
        families_per_operation=args.families_per_operation,
        variants_per_family=args.variants_per_family,
    ).build()
    manifest=WorldCurriculumArtifactWriter.write(args.output,cases)
    print('CETA WORLD CURRICULUM BUILT')
    print(f"cases={manifest['case_count']} families={manifest['world_family_count']} operations={manifest['operation_count']} negatives={manifest['illegal_alternative_count']}")
    for split,item in manifest['files'].items():
        print(f"{split}={item['count']} sha256={item['sha256']}")


if __name__=='__main__':
    main()
