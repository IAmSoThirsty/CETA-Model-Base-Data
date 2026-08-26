from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "data" / "ceta_controlled_evaluation"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return ["controlled-evaluation manifest is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version mismatch")
    if manifest.get("evaluation_id") != "CETA_CONTROLLED_EVALUATION/v1":
        errors.append("evaluation_id mismatch")
    if manifest.get("usage_class") != "CONTROLLED_EVALUATION":
        errors.append("usage_class mismatch")
    if manifest.get("optimizer_input") is not False or manifest.get("git_delivery") is not False:
        errors.append("controlled-evaluation role boundary mismatch")

    challenge_path = root / str(manifest.get("challenge_path", ""))
    answer_path = root / str(manifest.get("answer_key_path", ""))
    for label, path, expected in (
        ("challenge", challenge_path, manifest.get("challenge_sha256")),
        ("answer key", answer_path, manifest.get("answer_key_sha256")),
    ):
        if not path.is_file():
            errors.append(f"{label} file is missing")
        elif sha256(path) != expected:
            errors.append(f"{label} hash mismatch")
    if errors:
        return errors

    challenges = jsonl(challenge_path)
    answers = jsonl(answer_path)
    challenge_ids = [str(item.get("scenario_id", "")) for item in challenges]
    answer_ids = [str(item.get("scenario_id", "")) for item in answers]
    if not all(challenge_ids) or len(challenge_ids) != len(set(challenge_ids)):
        errors.append("challenge scenario IDs are missing or duplicated")
    if not all(answer_ids) or len(answer_ids) != len(set(answer_ids)):
        errors.append("answer scenario IDs are missing or duplicated")
    if set(challenge_ids) != set(answer_ids):
        errors.append("challenge and answer scenario IDs do not match")
    if len(challenges) != manifest.get("case_count"):
        errors.append("challenge count mismatch")
    if len(answers) != manifest.get("answer_count"):
        errors.append("answer count mismatch")
    exposed = {str(item) for item in manifest.get("known_exposed_case_ids", [])}
    if not exposed.issubset(set(challenge_ids)):
        errors.append("known exposed case IDs are not present in the evaluation set")
    if len(challenge_ids) - len(exposed) != manifest.get("clean_unseen_case_count"):
        errors.append("clean unseen case count mismatch")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print("CETA CONTROLLED EVALUATION VALIDATION: FAIL")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)
    manifest = json.loads((args.root.resolve() / "manifest.json").read_text(encoding="utf-8"))
    print("CETA CONTROLLED EVALUATION VALIDATION: PASS")
    print(
        f"cases={manifest['case_count']} known_exposed={len(manifest['known_exposed_case_ids'])} "
        f"clean_unseen={manifest['clean_unseen_case_count']}"
    )


if __name__ == "__main__":
    main()
