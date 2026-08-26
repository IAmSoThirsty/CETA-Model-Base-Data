#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_seed="${CETA_BOOTSTRAP_PYTHON:-python3}"

if [[ "${1:-}" == "--target" ]]; then
  if [[ $# -ne 2 || -e "$2" ]]; then
    echo "usage: $0 --target NEW_PACKAGE_DIRECTORY" >&2
    exit 2
  fi
  package_root="$2"
  "${python_seed}" -m pip install \
    --disable-pip-version-check \
    --target "${package_root}" \
    --requirement "${repo_root}/requirements-language-adapter.txt"
  PYTHONPATH="${package_root}" "${python_seed}" -c 'import accelerate, bitsandbytes, peft, safetensors, torch, transformers; assert torch.__version__.split("+")[0] == "2.13.0"; assert transformers.__version__ == "5.5.0"; print("CETA LANGUAGE TARGET: PASS", torch.__version__, transformers.__version__)'
  exit 0
fi

venv_root="${1:-${repo_root}/.venv-language-adapter}"
if [[ ! -e "${venv_root}" ]]; then
  "${python_seed}" -m venv "${venv_root}"
fi

python_bin="${venv_root}/bin/python"
if [[ ! -x "${python_bin}" ]]; then
  echo "CETA LANGUAGE ENV: FAIL - not a usable virtual environment: ${venv_root}" >&2
  exit 2
fi

"${python_bin}" -m pip install --disable-pip-version-check --requirement "${repo_root}/requirements-language-adapter.txt"
"${python_bin}" -m pip check
"${python_bin}" -c 'import accelerate, bitsandbytes, peft, safetensors, torch, transformers; print("CETA LANGUAGE ENV: PASS", torch.__version__, transformers.__version__)'
