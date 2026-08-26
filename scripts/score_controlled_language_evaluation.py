from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("ceta_language_adapter_scoring", ROOT / "src/training/language_adapter.py")
assert SPEC is not None and SPEC.loader is not None
LANGUAGE_ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANGUAGE_ADAPTER
SPEC.loader.exec_module(LANGUAGE_ADAPTER)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(value: Any, *, domain: str) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(domain.encode("utf-8") + b"\n" + raw).hexdigest()


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower().replace("_", " "))


def token_f1(predicted: str, expected: str) -> float:
    left, right = Counter(tokens(predicted)), Counter(tokens(expected))
    if not left or not right:
        return 0.0
    overlap = sum((left & right).values())
    precision = overlap / sum(left.values())
    recall = overlap / sum(right.values())
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def rouge_l(predicted: str, expected: str) -> float:
    left, right = tokens(predicted), tokens(expected)
    if not left or not right:
        return 0.0
    previous = [0] * (len(right) + 1)
    for token in left:
        current = [0]
        for index, other in enumerate(right, 1):
            current.append(previous[index - 1] + 1 if token == other else max(previous[index], current[-1]))
        previous = current
    lcs = previous[-1]
    precision = lcs / len(left)
    recall = lcs / len(right)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def normalized_ruling(value: str) -> str:
    return "_".join(tokens(value))


def ruling_label_profile(answers: dict[str, dict[str, Any]], scenario_ids: list[str]) -> dict[str, Any]:
    labels = [normalized_ruling(str(answers[scenario_id].get("ruling", ""))) for scenario_id in scenario_ids]
    counts = Counter(label for label in labels if label)
    unique_count = len(counts)
    case_count = len(labels)
    unique_ratio = unique_count / case_count if case_count else 0.0
    return {
        "case_count": case_count,
        "unique_label_count": unique_count,
        "unique_label_ratio": unique_ratio,
        "repeated_label_count": sum(1 for count in counts.values() if count > 1),
        "maximum_label_reuse": max(counts.values(), default=0),
        "near_unique_private_label_space": bool(case_count and unique_ratio >= 0.9),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score frozen controlled-language predictions against the separate answer key.")
    parser.add_argument("--training-run", type=Path, required=True)
    parser.add_argument("--controlled-root", type=Path, default=ROOT / "data/ceta_controlled_evaluation")
    parser.add_argument("--inference-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    training_report = json.loads((args.training_run.resolve() / "TRAINING_REPORT.json").read_text(encoding="utf-8"))
    config = json.loads((ROOT / "configs/ceta-language-adapter-qwen3-4b-h100.json").read_text(encoding="utf-8"))
    policy = config["evaluation_policy"]
    policy_hash = canonical_hash(policy, domain="CETA/CONTROLLED_LANGUAGE_EVAL_POLICY/v1")
    if policy_hash != training_report.get("evaluation_policy_hash"):
        raise SystemExit("CONTROLLED LANGUAGE EVALUATION: FAIL - frozen evaluation policy mismatch")

    controlled = args.controlled_root.resolve()
    manifest = json.loads((controlled / "manifest.json").read_text(encoding="utf-8"))
    answer_path = controlled / str(manifest.get("answer_key_path", ""))
    if not answer_path.is_file() or LANGUAGE_ADAPTER.sha256_file(answer_path) != manifest.get("answer_key_sha256"):
        raise SystemExit("CONTROLLED LANGUAGE EVALUATION: FAIL - answer-key hash mismatch")
    inference_root = args.inference_root.resolve()
    inference = json.loads((inference_root / "inference_manifest.json").read_text(encoding="utf-8"))
    inference_body = {key: value for key, value in inference.items() if key != "inference_hash"}
    if inference.get("inference_hash") != canonical_hash(inference_body, domain="CETA/CONTROLLED_LANGUAGE_INFERENCE/v1"):
        raise SystemExit("CONTROLLED LANGUAGE EVALUATION: FAIL - inference manifest hash mismatch")
    predictions_path = inference_root / "predictions.jsonl"
    if LANGUAGE_ADAPTER.sha256_file(predictions_path) != inference.get("predictions_sha256"):
        raise SystemExit("CONTROLLED LANGUAGE EVALUATION: FAIL - prediction artifact hash mismatch")
    if inference.get("answer_key_accessed") is not False or inference.get("training_report_hash") != training_report.get("report_hash"):
        raise SystemExit("CONTROLLED LANGUAGE EVALUATION: FAIL - inference independence binding mismatch")

    predictions = {str(item["scenario_id"]): item for item in jsonl(predictions_path)}
    answers = {str(item["scenario_id"]): item for item in jsonl(answer_path)}
    if set(predictions) != set(answers) or len(predictions) != manifest.get("case_count"):
        raise SystemExit("CONTROLLED LANGUAGE EVALUATION: FAIL - prediction/answer identity mismatch")
    excluded = set(str(item) for item in policy["clean_case_ids_excluded"])
    if excluded != set(str(item) for item in manifest.get("known_exposed_case_ids", [])):
        raise SystemExit("CONTROLLED LANGUAGE EVALUATION: FAIL - exposure exclusion mismatch")

    clean_scenario_ids = sorted(set(predictions) - excluded)
    label_profile = ruling_label_profile(answers, clean_scenario_ids)
    consumed_receipt = LANGUAGE_ADAPTER.consumed_evaluator_receipt(
        ROOT / "evidence",
        challenge_sha256=str(manifest["challenge_sha256"]),
        answer_key_sha256=str(manifest["answer_key_sha256"]),
    )
    benchmark_status = {
        "clean_unseen": consumed_receipt is None,
        "consumption_receipt": consumed_receipt,
    }
    case_metrics: list[dict[str, Any]] = []
    for scenario_id in clean_scenario_ids:
        prediction = predictions[scenario_id]
        response = prediction.get("response", {})
        answer = answers[scenario_id]
        predicted_reference = " ".join(str(response.get(key, "")) for key in ("correct_outcome", "scoring_focus", "unsafe_if"))
        expected_reference = " ".join(str(answer.get(key, "")) for key in ("correct_outcome", "scoring_focus", "unsafe_if"))
        case_metrics.append({
            "scenario_id": scenario_id,
            "parseable": bool(prediction.get("parseable")),
            "exact_ruling": normalized_ruling(str(response.get("ruling", ""))) == normalized_ruling(str(answer.get("ruling", ""))),
            "reference_token_f1": token_f1(predicted_reference, expected_reference),
            "reference_rouge_l": rouge_l(predicted_reference, expected_reference),
        })
    count = len(case_metrics)
    parseable_rate = sum(item["parseable"] for item in case_metrics) / count
    ruling_accuracy = sum(item["exact_ruling"] for item in case_metrics) / count
    mean_f1 = sum(item["reference_token_f1"] for item in case_metrics) / count
    mean_rouge = sum(item["reference_rouge_l"] for item in case_metrics) / count
    gates = {
        "clean_case_count": count == int(policy["minimum_clean_case_count"]),
        "clean_unseen_benchmark": benchmark_status["clean_unseen"],
        "parseable_response_rate": parseable_rate >= float(policy["minimum_parseable_response_rate"]),
        "exact_ruling_accuracy": ruling_accuracy >= float(policy["minimum_exact_ruling_accuracy"]),
        "mean_reference_token_f1": mean_f1 >= float(policy["minimum_mean_reference_token_f1"]),
        "mean_reference_rouge_l": mean_rouge >= float(policy["minimum_mean_reference_rouge_l"]),
    }
    passed = all(gates.values())
    body = {
        "schema_id": "CETA_CONTROLLED_LANGUAGE_EVALUATION_REPORT/v1",
        "completed_at": utc_now(),
        "training_report_hash": training_report["report_hash"],
        "inference_hash": inference["inference_hash"],
        "evaluation_policy": policy,
        "evaluation_policy_hash": policy_hash,
        "challenge_sha256": manifest["challenge_sha256"],
        "answer_key_sha256": manifest["answer_key_sha256"],
        "known_exposed_case_ids": sorted(excluded),
        "clean_case_count": count,
        "metrics": {
            "parseable_response_rate": parseable_rate,
            "exact_ruling_accuracy": ruling_accuracy,
            "mean_reference_token_f1": mean_f1,
            "mean_reference_rouge_l": mean_rouge,
        },
        "gates": gates,
        "status": "QUALIFIED" if passed else "QUARANTINED",
        "promotion_performed": False,
        "benchmark_status": benchmark_status,
        "ruling_label_profile": label_profile,
        "case_metrics": case_metrics,
        "limitations": [
            "Token F1 and ROUGE-L measure reference overlap, not complete semantic equivalence.",
            "Owner or independent human review remains required for a production or safety claim.",
            "The controlled evaluation does not feed optimizer, prompt, or threshold changes in this frozen run.",
            *(
                [
                    "Exact ruling is a private open-vocabulary diagnostic for this evaluator: near-unique answer labels "
                    "are not disclosed to answer-blind inference and must not be interpreted as ordinary closed-set classification."
                ]
                if label_profile["near_unique_private_label_space"]
                else []
            ),
        ],
    }
    report = {**body, "report_hash": canonical_hash(body, domain="CETA/CONTROLLED_LANGUAGE_EVALUATION_REPORT/v1")}
    args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.report.resolve().write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(
        "CETA CONTROLLED LANGUAGE EVALUATION: PASS "
        f"execution_status={report['status']} clean_cases={count} ruling={ruling_accuracy:.6f} "
        f"token_f1={mean_f1:.6f} rouge_l={mean_rouge:.6f} report={report['report_hash']}"
    )


if __name__ == "__main__":
    main()
