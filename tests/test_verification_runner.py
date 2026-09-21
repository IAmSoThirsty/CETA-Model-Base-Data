from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerificationRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_script("verify_all")
        cls.hostile = load_script("hostile_epoch_gate")

    def report(self):
        return {"checks": ["test-only-check"], "curriculum_cases_checked": 0, "report_hash": "test-only-hash"}

    def test_import_does_not_launch_verification(self):
        with patch("subprocess.run") as run, redirect_stdout(io.StringIO()) as output:
            load_script("verify_all")
        run.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_hostile_cli_writes_new_report_preserving_historical_bytes(self):
        historical = ROOT / "evidence/EPOCH_HOSTILE_GATE_REPORT.json"
        historical_bytes = historical.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-report.json"
            with patch.object(self.hostile, "run_gate", return_value=self.report()), redirect_stdout(io.StringIO()):
                self.assertEqual(self.hostile.main(["--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.report())
            self.assertEqual(historical.read_bytes(), historical_bytes)

    def test_hostile_default_report_is_new_and_outside_historical_path(self):
        historical = ROOT / "evidence/EPOCH_HOSTILE_GATE_REPORT.json"
        historical_bytes = historical.read_bytes()
        real_mkstemp = tempfile.mkstemp
        with tempfile.TemporaryDirectory() as directory:
            def mkstemp(**kwargs):
                return real_mkstemp(dir=directory, **kwargs)

            with patch.object(self.hostile, "run_gate", return_value=self.report()), \
                    patch.object(self.hostile.tempfile, "mkstemp", side_effect=mkstemp), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(self.hostile.main([]), 0)
            reports = list(Path(directory).glob("ceta-hostile-epoch-report-*.json"))
            self.assertEqual(len(reports), 1)
            self.assertEqual(json.loads(reports[0].read_text()), self.report())
            self.assertEqual(historical.read_bytes(), historical_bytes)

    def test_existing_output_is_rejected_before_expensive_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            original = b"historical evidence\n"
            output.write_bytes(original)
            with patch.object(self.hostile, "run_gate") as gate, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    self.hostile.main(["--output", str(output)])
            self.assertEqual(failure.exception.code, 2)
            gate.assert_not_called()
            self.assertEqual(output.read_bytes(), original)

    def test_output_created_during_gate_cannot_be_overwritten_or_report_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"

            def gate():
                output.write_bytes(b"another writer's evidence")
                return self.report()

            with patch.object(self.hostile, "run_gate", side_effect=gate), redirect_stdout(io.StringIO()) as messages:
                with self.assertRaises(FileExistsError):
                    self.hostile.main(["--output", str(output)])
            self.assertNotIn("PASS", messages.getvalue())
            self.assertEqual(output.read_bytes(), b"another writer's evidence")

    def test_runner_passes_explicit_output_to_hostile_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "current-run.json"
            with patch.object(self.runner.subprocess, "run") as run, redirect_stdout(io.StringIO()) as messages:
                self.assertEqual(self.runner.main(["--hostile-report", str(output)]), 0)
            commands = [call.args[0] for call in run.call_args_list]
            hostile = [command for command in commands if any(part.endswith("hostile_epoch_gate.py") for part in command)]
            self.assertEqual(len(hostile), 1)
            self.assertEqual(hostile[0][-2:], ["--output", str(output.resolve())])
            self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))
            self.assertIn("REFERENCE VERIFICATION: PASS", messages.getvalue())

    def test_runner_default_outputs_are_unique_and_retained(self):
        real_mkdtemp = tempfile.mkdtemp
        with tempfile.TemporaryDirectory() as directory:
            def mkdtemp(**kwargs):
                return real_mkdtemp(dir=directory, **kwargs)

            outputs = []
            with patch.object(self.runner.tempfile, "mkdtemp", side_effect=mkdtemp), redirect_stdout(io.StringIO()):
                for _ in range(2):
                    with patch.object(self.runner, "verification_commands", return_value=[]) as commands:
                        self.assertEqual(self.runner.main([]), 0)
                    outputs.append(commands.call_args.args[0])
            self.assertNotEqual(outputs[0], outputs[1])
            self.assertTrue(all(path.parent.is_dir() for path in outputs))
            self.assertTrue(all(path.is_relative_to(directory) for path in outputs))

    def test_runner_failure_stops_subsequent_checks_and_never_prints_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "current-run.json"
            with patch.object(self.runner.subprocess, "run", side_effect=[None, subprocess.CalledProcessError(7, "test-command")]) as run, \
                    redirect_stdout(io.StringIO()) as messages, redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(self.runner.main(["--hostile-report", str(output)]), 7)
            self.assertEqual(run.call_count, 2)
            self.assertNotIn("REFERENCE VERIFICATION: PASS", messages.getvalue())
            self.assertIn("REFERENCE VERIFICATION: FAIL (exit 7)", errors.getvalue())

    def test_runner_launch_failure_is_failure_without_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "current-run.json"
            with patch.object(self.runner.subprocess, "run", side_effect=OSError("cannot launch")) as run, \
                    redirect_stdout(io.StringIO()) as messages, redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(self.runner.main(["--hostile-report", str(output)]), 1)
            self.assertEqual(run.call_count, 1)
            self.assertNotIn("REFERENCE VERIFICATION: PASS", messages.getvalue())
            self.assertIn("cannot launch", errors.getvalue())

    def test_runner_rejects_existing_output_before_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "historical.json"
            output.write_bytes(b"original")
            with patch.object(self.runner.subprocess, "run") as run, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.runner.main(["--hostile-report", str(output)])
            run.assert_not_called()
            self.assertEqual(output.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
