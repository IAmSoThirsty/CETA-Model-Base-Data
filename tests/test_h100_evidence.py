from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from history import domain_hash


REPORT = ROOT / "evidence" / "STRUCTURED_POLICY_H100_SCHEMA_V4_FINAL_HELDOUT.json"
VERIFIER = ROOT / "scripts" / "verify_final_heldout_report.py"


class H100EvidenceTests(unittest.TestCase):
    def test_final_heldout_evidence_verifies(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFIER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_rehashed_nonperfect_heldout_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report = json.loads(REPORT.read_text(encoding="utf-8"))
            report["heldout"]["target_accuracy"] = 0.99
            report.pop("report_hash")
            report["report_hash"] = domain_hash(report, domain="CETA/FINAL_HELDOUT_EVALUATION/v1")
            path = Path(td) / "tampered.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFIER), "--report", str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("evaluation hash mismatch", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
