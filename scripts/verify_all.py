from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verification_commands(hostile_report: Path) -> list[list[str]]:
    return [
        [sys.executable, "-m", "compileall", "-q", str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "examples"), str(ROOT / "tests")],
        [sys.executable, str(ROOT / "scripts/verify_corpus_manifest.py")],
        [sys.executable, str(ROOT / "scripts/validate_architecture.py")],
        [sys.executable, str(ROOT / "scripts/validate_evidence_registry.py")],
        [sys.executable, str(ROOT / "scripts/validate_ceta_curriculum.py")],
        [sys.executable, str(ROOT / "scripts/validate_ceta_curriculum_v3.py")],
        [sys.executable, str(ROOT / "scripts/validate_architecture_material.py")],
        [sys.executable, str(ROOT / "scripts/validate_language_adapter_dataset.py")],
        [sys.executable, str(ROOT / "scripts/hostile_audit.py")],
        [sys.executable, str(ROOT / "scripts/run_bounded_models.py")],
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-q"],
        [sys.executable, str(ROOT / "scripts/hostile_epoch_gate.py"), "--output", str(hostile_report)],
        [sys.executable, str(ROOT / "scripts/verify_epoch_readiness_report.py")],
        [sys.executable, str(ROOT / "scripts/verify_epoch_readiness_report.py"), "--report", str(ROOT / "evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_READINESS.json")],
        [sys.executable, str(ROOT / "scripts/verify_epoch_continuation_report.py"), "--report", str(ROOT / "evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_EPOCH_3.json")],
        [sys.executable, str(ROOT / "scripts/verify_epoch_continuation_report.py"), "--report", str(ROOT / "evidence/STRUCTURED_POLICY_H100_SCHEMA_V4_EPOCH_5.json")],
        [sys.executable, str(ROOT / "scripts/verify_final_heldout_report.py")],
        [sys.executable, str(ROOT / "examples/reference_runtime_demo.py")],
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify CETA without rewriting historical evidence.")
    parser.add_argument(
        "--hostile-report", type=Path,
        help="New hostile-gate report path; defaults to a retained unique temporary directory.",
    )
    args = parser.parse_args(argv)
    hostile_report = args.hostile_report
    if hostile_report is None:
        hostile_report = Path(tempfile.mkdtemp(prefix="ceta-verification-")) / "hostile-epoch-report.json"
    else:
        hostile_report = hostile_report.resolve()
        if hostile_report.exists():
            parser.error(f"report output already exists: {hostile_report}")
    print(f"Hostile-gate report output: {hostile_report}", flush=True)
    for cmd in verification_commands(hostile_report):
        print("RUN", " ".join(cmd), flush=True)
        try:
            subprocess.run(cmd, cwd=ROOT, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"CETA EPOCH-READY REFERENCE VERIFICATION: FAIL (exit {exc.returncode})", file=sys.stderr)
            return exc.returncode or 1
        except OSError as exc:
            print(f"CETA EPOCH-READY REFERENCE VERIFICATION: FAIL ({exc})", file=sys.stderr)
            return 1
    print("CETA EPOCH-READY REFERENCE VERIFICATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
