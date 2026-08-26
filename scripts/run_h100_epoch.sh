#!/usr/bin/env bash
set -euo pipefail

export CUBLAS_WORKSPACE_CONFIG="${CUBLAS_WORKSPACE_CONFIG:-:4096:8}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${CETA_PYTHON:-python}"
additional_epochs=""
from_checkpoint_sha256=""
continuation_report_output=""
positionals=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --additional-epochs)
      [[ $# -ge 2 ]] || { echo "H100 EPOCH: FAIL - --additional-epochs requires a value" >&2; exit 2; }
      additional_epochs="$2"
      shift 2
      ;;
    --from-checkpoint-sha256)
      [[ $# -ge 2 ]] || { echo "H100 EPOCH: FAIL - --from-checkpoint-sha256 requires a value" >&2; exit 2; }
      from_checkpoint_sha256="$2"
      shift 2
      ;;
    --report-output)
      [[ $# -ge 2 ]] || { echo "H100 EPOCH: FAIL - --report-output requires a value" >&2; exit 2; }
      continuation_report_output="$2"
      shift 2
      ;;
    --help|-h)
      echo "fresh:        $0 [RUN_ROOT [REPORT_OUTPUT]]"
      echo "continuation: $0 --additional-epochs N [--from-checkpoint-sha256 SHA256] [--report-output PATH] RUN_ROOT"
      exit 0
      ;;
    --*)
      echo "H100 EPOCH: FAIL - unknown option: $1" >&2
      exit 2
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

if [[ -n "${additional_epochs}" ]]; then
  if [[ ${#positionals[@]} -ne 1 ]]; then
    echo "H100 EPOCH: FAIL - continuation requires exactly one existing RUN_ROOT" >&2
    exit 2
  fi
  continuation_args=(
    --device cuda
    --run-root "${positionals[0]}"
    --additional-epochs "${additional_epochs}"
  )
  if [[ -n "${from_checkpoint_sha256}" ]]; then
    continuation_args+=(--from-checkpoint-sha256 "${from_checkpoint_sha256}")
  fi
  if [[ -n "${continuation_report_output}" ]]; then
    continuation_args+=(--report-output "${continuation_report_output}")
  fi
  "${python_bin}" "${repo_root}/scripts/run_epoch_readiness.py" "${continuation_args[@]}"
  exit 0
fi

if [[ -n "${from_checkpoint_sha256}" ]]; then
  echo "H100 EPOCH: FAIL - --from-checkpoint-sha256 requires --additional-epochs" >&2
  exit 2
fi
if [[ -n "${continuation_report_output}" ]]; then
  echo "H100 EPOCH: FAIL - --report-output is an option only in continuation mode; use the fresh positional REPORT_OUTPUT" >&2
  exit 2
fi
if [[ ${#positionals[@]} -gt 2 ]]; then
  echo "H100 EPOCH: FAIL - fresh readiness accepts only RUN_ROOT and REPORT_OUTPUT" >&2
  exit 2
fi

run_root="${positionals[0]:-/teamspace/studios/this_studio/ceta-runs/h100-epoch-v0.3.0-curriculum-v3}"
report_output="${positionals[1]:-${run_root}/EPOCH_READINESS_REPORT.json}"

if [[ -e "${run_root}" ]]; then
  echo "H100 EPOCH: FAIL - run root already exists: ${run_root}" >&2
  exit 2
fi

"${python_bin}" "${repo_root}/scripts/run_epoch_readiness.py" \
  --device cuda \
  --run-root "${run_root}" \
  --report-output "${report_output}"

"${python_bin}" "${repo_root}/scripts/verify_epoch_readiness_report.py" \
  --report "${report_output}"
