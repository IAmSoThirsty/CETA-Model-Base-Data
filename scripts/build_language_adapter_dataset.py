from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("ceta_language_adapter_builder", ROOT / "src/training/language_adapter.py")
assert SPEC is not None and SPEC.loader is not None
LANGUAGE_ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANGUAGE_ADAPTER
SPEC.loader.exec_module(LANGUAGE_ADAPTER)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the public-only CETA language-adapter dataset.")
    parser.add_argument("--material-root", type=Path, default=ROOT / "data/ceta_architecture_material_v1")
    parser.add_argument("--curriculum-root", type=Path, default=ROOT / "data/ceta_curriculum_v3")
    parser.add_argument("--output", type=Path, default=ROOT / "data/ceta_language_adapter_v1")
    args = parser.parse_args()

    examples = LANGUAGE_ADAPTER.build_language_adapter_examples(args.material_root, args.curriculum_root)
    manifest = LANGUAGE_ADAPTER.write_language_adapter_dataset(
        args.output,
        examples,
        material_manifest_sha256=LANGUAGE_ADAPTER.sha256_file(args.material_root / "manifest.json"),
        curriculum_manifest_sha256=LANGUAGE_ADAPTER.sha256_file(args.curriculum_root / "manifest.json"),
    )
    print(
        "CETA LANGUAGE ADAPTER DATASET WRITTEN "
        f"records={manifest['record_count']} splits={manifest['split_counts']} hash={manifest['dataset_hash']}"
    )


if __name__ == "__main__":
    main()
