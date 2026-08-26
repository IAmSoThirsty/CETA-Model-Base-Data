#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${CETA_PYTHON:-python}"

if [[ $# -ne 3 ]]; then
  echo "usage: $0 TRAINING_RUN_ROOT CONTROLLED_INFERENCE_ROOT EVALUATION_REPORT" >&2
  exit 2
fi

training_run="$1"
inference_root="$2"
evaluation_report="$3"

if [[ -e "${training_run}" || -e "${inference_root}" || -e "${evaluation_report}" ]]; then
  echo "CETA LANGUAGE H100: FAIL - output paths must not exist" >&2
  exit 2
fi

"${python_bin}" "${repo_root}/scripts/validate_language_adapter_dataset.py"
"${python_bin}" "${repo_root}/scripts/validate_controlled_evaluation.py"
"${python_bin}" "${repo_root}/scripts/train_language_adapter.py" --run-root "${training_run}"
"${python_bin}" "${repo_root}/scripts/run_controlled_language_inference.py" \
  --training-run "${training_run}" \
  --output-root "${inference_root}"
"${python_bin}" "${repo_root}/scripts/score_controlled_language_evaluation.py" \
  --training-run "${training_run}" \
  --inference-root "${inference_root}" \
  --report "${evaluation_report}"
"${python_bin}" "${repo_root}/scripts/verify_language_epoch_report.py" \
  --training-run "${training_run}" \
  --inference-root "${inference_root}" \
  --report "${evaluation_report}"

echo "CETA LANGUAGE H100: COMPLETE"
