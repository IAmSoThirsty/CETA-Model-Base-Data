#!/usr/bin/env bash
set -euo pipefail

export CUBLAS_WORKSPACE_CONFIG="${CUBLAS_WORKSPACE_CONFIG:-:4096:8}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${CETA_PYTHON:-python}"
run_root="${1:-/teamspace/studios/this_studio/ceta-runs/h100-epoch-v0.3.0}"
report_output="${2:-${run_root}/EPOCH_READINESS_REPORT.json}"

if [[ -e "${run_root}" ]]; then
  echo "H100 EPOCH: FAIL - run root already exists: ${run_root}" >&2
  exit 2
fi

"${python_bin}" -c 'import torch; assert torch.cuda.is_available(), "CUDA is unavailable; activate the H100 before running this launcher"; name=torch.cuda.get_device_name(0); assert "H100" in name.upper(), f"expected an H100, found {name}"; print(f"H100 DEVICE VERIFIED: {name}")'

"${python_bin}" "${repo_root}/scripts/run_epoch_readiness.py" \
  --device cuda \
  --run-root "${run_root}" \
  --report-output "${report_output}"

"${python_bin}" "${repo_root}/scripts/verify_epoch_readiness_report.py" \
  --report "${report_output}"
