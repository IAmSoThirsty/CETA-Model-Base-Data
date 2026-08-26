from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("ceta_language_adapter_validator", ROOT / "src/training/language_adapter.py")
assert SPEC is not None and SPEC.loader is not None
LANGUAGE_ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANGUAGE_ADAPTER
SPEC.loader.exec_module(LANGUAGE_ADAPTER)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the derived public CETA language-adapter dataset.")
    parser.add_argument("--root", type=Path, default=ROOT / "data/ceta_language_adapter_v1")
    args = parser.parse_args()
    manifest, splits = LANGUAGE_ADAPTER.load_verified_language_dataset(args.root)
    if manifest["record_count"] != 2439:
        raise SystemExit(f"CETA LANGUAGE ADAPTER DATASET: FAIL - expected 2439 records, got {manifest['record_count']}")
    if manifest["source_class_counts"] != {"DEFENSIVE_PUBLIC": 279, "HUMAN_RELATIONS_PUBLIC": 2160}:
        raise SystemExit("CETA LANGUAGE ADAPTER DATASET: FAIL - public source coverage mismatch")
    if not all(splits[split] for split in ("train", "validation", "heldout")):
        raise SystemExit("CETA LANGUAGE ADAPTER DATASET: FAIL - an expected split is empty")
    print(
        "CETA LANGUAGE ADAPTER DATASET: PASS "
        f"records={manifest['record_count']} splits={manifest['split_counts']} "
        f"lineages={manifest['source_lineage_count']}"
    )


if __name__ == "__main__":
    main()
