from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
commands = [
    [sys.executable, "-m", "compileall", "-q", str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "examples"), str(ROOT / "tests")],
    [sys.executable, str(ROOT / "scripts/verify_corpus_manifest.py")],
    [sys.executable, str(ROOT / "scripts/validate_architecture.py")],
    [sys.executable, str(ROOT / "scripts/validate_evidence_registry.py")],
    [sys.executable, str(ROOT / "scripts/validate_ceta_curriculum.py")],
    [sys.executable, str(ROOT / "scripts/validate_ceta_curriculum_v3.py")],
    [sys.executable, str(ROOT / "scripts/validate_architecture_material.py")],
    [sys.executable, str(ROOT / "scripts/hostile_audit.py")],
    [sys.executable, str(ROOT / "scripts/run_bounded_models.py")],
    [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
    [sys.executable, str(ROOT / "scripts/hostile_epoch_gate.py")],
    [sys.executable, str(ROOT / "scripts/verify_epoch_readiness_report.py")],
    [sys.executable, str(ROOT / "examples/reference_runtime_demo.py")],
]
for cmd in commands:
    print("RUN", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
print("CETA EPOCH-READY REFERENCE VERIFICATION: PASS")
