from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ceta import ConstitutionalVM
from ceta import vm


def load_runner():
    spec = importlib.util.spec_from_file_location("verify_desktop_runtime", ROOT / "scripts/verify_desktop_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MergedDistributionTests(unittest.TestCase):
    def test_bundled_contracts_match_canonical_registry_bytes(self):
        runner = load_runner()
        expected = hashlib.sha256((ROOT / "registry/operation_contracts.json").read_bytes()).hexdigest()
        self.assertEqual(runner.verify_contract_resource(), expected)

    def test_contract_resource_drift_fails_release_gate(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "registry").mkdir()
            (root / "src/ceta").mkdir(parents=True)
            (root / "registry/operation_contracts.json").write_bytes(b"canonical")
            (root / "src/ceta/operation_contracts.json").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "differ"):
                runner.verify_contract_resource(root)

    def test_explicit_contract_path_preserves_public_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contracts.json"
            path.write_text('{"contracts": [{"operation": "ExplicitOnly", "status": "BOUND"}]}', encoding="utf-8")
            self.assertEqual(set(ConstitutionalVM(path)._contracts), {"ExplicitOnly"})
            with self.assertRaises(FileNotFoundError):
                ConstitutionalVM(Path(directory) / "missing.json")

    def test_source_checkout_prefers_its_current_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "registry").mkdir()
            (root / "registry/operation_contracts.json").write_text(
                '{"contracts": [{"operation": "SourceOnly", "status": "BOUND"}]}', encoding="utf-8")
            with patch.object(vm, "ROOT", root):
                self.assertEqual(set(ConstitutionalVM()._contracts), {"SourceOnly"})

    def test_fresh_package_context_loads_bundled_contracts_without_repository(self):
        with tempfile.TemporaryDirectory(prefix="ceta-distribution-") as directory:
            root = Path(directory).resolve()
            packages = root / "packages"
            packages.mkdir()
            for name in ("ceta", "history"):
                shutil.copytree(ROOT / "src" / name, packages / name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            script = (
                "import sys,json; from pathlib import Path; "
                f"sys.path.insert(0, {str(packages)!r}); "
                "from ceta import ConstitutionalVM, vm; "
                "from importlib import resources; import hashlib; "
                "assert not (vm.ROOT/'registry/operation_contracts.json').exists(); "
                "machine=ConstitutionalVM(); "
                "print(json.dumps({'module':str(Path(vm.__file__).resolve()), "
                "'operations':sorted(machine._contracts), "
                "'sha256':hashlib.sha256(resources.files('ceta').joinpath('operation_contracts.json').read_bytes()).hexdigest()}))"
            )
            result = subprocess.run([sys.executable, "-I", "-B", "-c", script], cwd=root,
                                    text=True, capture_output=True, timeout=30, check=True)
            loaded = json.loads(result.stdout)
            self.assertTrue(Path(loaded["module"]).is_relative_to(packages))
            self.assertIn("Execute", loaded["operations"])
            self.assertIn("Authorize", loaded["operations"])
            self.assertEqual(loaded["sha256"], load_runner().verify_contract_resource())

    def test_package_data_and_frozen_builder_include_vm_resource(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("operation_contracts.json", config["tool"]["setuptools"]["package-data"]["ceta"])
        builder = (ROOT / "scripts/build_desktop.py").read_text(encoding="utf-8")
        self.assertIn("src/ceta/operation_contracts.json", builder)
        self.assertIn(";ceta", builder)

    def test_builder_and_ci_share_the_merged_runtime_verifier(self):
        builder = (ROOT / "scripts/build_desktop.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/desktop.yml").read_text(encoding="utf-8")
        for text in (builder, workflow):
            self.assertIn("scripts/verify_desktop_runtime.py", text)
            self.assertNotIn('"test_desktop*.py", "-v"', text)

    def test_runner_groups_include_merger_and_pure_core_without_training(self):
        runner = load_runner()
        patterns = {pattern for group in runner.TEST_GROUPS.values() for pattern in group}
        for pattern in ("test_desktop*.py", "test_task_runtime.py", "test_project_tools.py",
                        "test_model001_integration.py", "test_task_roles.py", "test_legacy_history.py", "test_*journal*.py", "test_authority*.py",
                        "test_effect*.py", "test_transition_history.py", "test_ceta_vm_boundary.py"):
            self.assertIn(pattern, patterns)
        for path in (ROOT / "tests").glob("test_*.py"):
            if any(term in path.stem for term in ("training", "language_adapter", "language_dependency", "h100", "curriculum", "neural")):
                self.assertFalse(any(path.match(pattern) for pattern in patterns), path.name)

    def test_missing_required_test_pattern_is_not_a_pass(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "no test files"):
                runner.selected_tests(Path(directory))

    def test_importing_runner_does_not_execute_tests_or_subprocesses(self):
        with patch("subprocess.run") as run, patch("unittest.TextTestRunner.run") as test_run, \
                redirect_stdout(io.StringIO()) as output:
            load_runner()
        run.assert_not_called()
        test_run.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_existing_verification_report_is_preserved(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_bytes(b"historical evidence")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.main(["--report", str(path)])
            self.assertEqual(path.read_bytes(), b"historical evidence")

    def test_runner_test_failure_returns_nonzero_without_pass_claim(self):
        runner = load_runner()
        result = unittest.TestResult()
        result.testsRun = 1
        result.failures = [(unittest.FunctionTestCase(lambda: None), "synthetic failure")]
        with patch.object(runner, "verify_contract_resource", return_value="a" * 64), \
                patch.object(runner, "selected_tests", return_value=(ROOT / "tests/test_task_runtime.py",)), \
                patch.object(runner.importlib.util, "find_spec", return_value=object()), \
                patch.object(runner.unittest.defaultTestLoader, "loadTestsFromNames", return_value=unittest.TestSuite([unittest.FunctionTestCase(lambda: None)])), \
                patch.object(runner.unittest.TextTestRunner, "run", return_value=result), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main([]), 1)
        self.assertIn("FAIL", output.getvalue())
        self.assertNotIn("PASS", output.getvalue())

    def test_runner_records_exact_skip_and_rejects_source_change_during_run(self):
        runner = load_runner()
        case = unittest.FunctionTestCase(lambda: None)
        result = unittest.TestResult()
        result.testsRun = 1
        result.skipped = [(case, "fixture unavailable")]
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            with patch.object(runner, "verify_contract_resource", return_value="a" * 64), \
                    patch.object(runner, "selected_tests", return_value=(ROOT / "tests/test_task_runtime.py",)), \
                    patch.object(runner.importlib.util, "find_spec", return_value=object()), \
                    patch.object(runner.unittest.defaultTestLoader, "loadTestsFromNames", return_value=unittest.TestSuite([case])), \
                    patch.object(runner.unittest.TextTestRunner, "run", return_value=result), \
                    patch.object(runner, "source_attribution", side_effect=[{"source_sha256": "before"}, {"source_sha256": "after"}]), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(["--report", str(report)]), 1)
            record = json.loads(report.read_text())
            self.assertFalse(record["passed"])
            self.assertFalse(record["source_unchanged_during_tests"])
            self.assertEqual(record["skip_details"], [{"test": case.id(), "reason": "fixture unavailable"}])
            self.assertEqual(record["test_cases"], [case.id()])


if __name__ == "__main__":
    unittest.main()
