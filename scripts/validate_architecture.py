from pathlib import Path
import json, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from architecture_contracts import validate

errors = validate()
if errors:
    print('ARCHITECTURE VALIDATION: FAIL')
    for e in errors:
        print(' -', e)
    raise SystemExit(1)

queue = json.loads((ROOT/'registry'/'legacy_admission_queue.json').read_text())['items']
unresolved = sum(1 for x in queue if x['decision'] == 'UNRESOLVED')
print('ARCHITECTURE VALIDATION: PASS')
resp_count=len(json.loads((ROOT/'registry'/'responsibilities.json').read_text())['responsibilities'])
op_count=len(json.loads((ROOT/'registry'/'ceta_operations.json').read_text())['operations'])
print(f'canonical_responsibilities={resp_count}')
print(f'ceta_operations={op_count}')
print(f'legacy_queue={len(queue)} unresolved={unresolved}')
print('note=PASS validates the declared reference-core contract; it is not a production certification')
