#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_root="${1:-${repo_root}/.venv-language-adapter}"
python_seed="${CETA_BOOTSTRAP_PYTHON:-python3}"

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
