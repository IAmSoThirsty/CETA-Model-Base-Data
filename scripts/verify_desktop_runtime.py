"""One native desktop and governed-runtime verification gate, without training extras."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEST_GROUPS = {
    "desktop": ("test_desktop*.py",),
    "task_runtime": ("test_task_runtime.py", "test_task_roles.py", "test_generation_plan.py", "test_runtime_recovery.py", "test_project_tools.py", "test_model001_integration.py"),
    "journal": ("test_*journal*.py", "test_legacy_history.py"),
    "authority": ("test_authority*.py", "test_identity_authority_trust.py"),
    "effects": ("test_effect*.py",),
    "history_and_evidence": ("test_transition_history.py", "test_memory_projection.py", "test_source_boundaries.py"),
    "ceta_core": ("test_ceta_vm_boundary.py", "test_ceta_operation_algebra.py", "test_runtime_end_to_end.py",
                  "test_architecture_contracts.py"),
    "distribution": ("test_merged_distribution.py", "test_release_safety.py"),
}


def verify_contract_resource(root: Path = ROOT) -> str:
    canonical = (root / "registry/operation_contracts.json").read_bytes()
    bundled = (root / "src/ceta/operation_contracts.json").read_bytes()
    if canonical != bundled:
        raise ValueError("Bundled CETA operation contracts differ from the canonical registry; review and synchronize the resource before release.")
    return hashlib.sha256(canonical).hexdigest()


def selected_tests(root: Path = ROOT) -> tuple[Path, ...]:
    selected = set()
    for group, patterns in TEST_GROUPS.items():
        group_files = set()
        for pattern in patterns:
            matched = set((root / "tests").glob(pattern))
            if not matched:
                raise ValueError(f"Required {group} verification pattern has no test files: {pattern}")
            group_files.update(matched)
        selected.update(group_files)
    return tuple(sorted(selected))


def source_attribution(root: Path = ROOT) -> dict:
    def git(*arguments):
        try:
            return subprocess.run(["git", "-C", str(root), *arguments], capture_output=True,
                                  text=True, timeout=10, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    paths = {path for folder in ("src", "scripts", "tests") for path in (root / folder).rglob("*")
             if path.is_file() and path.suffix in {".py", ".json"} and "__pycache__" not in path.parts}
    paths.update(path for name in ("uv.lock", "pyproject.toml") if (path := root / name).is_file())
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    return {"root": str(root.resolve()), "head": git("rev-parse", "HEAD"),
            "branch": git("branch", "--show-current"), "status": git("status", "--porcelain=v1"),
            "file_hashes": hashes, "source_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List selected test modules without executing them")
    parser.add_argument("--report", type=Path, help="Write a new JSON verification report; never replace an existing report")
    args = parser.parse_args(argv)
    if args.report is not None and args.report.exists():
        parser.error(f"Report already exists: {args.report}")
    started = time.monotonic()
    try:
        contract_sha256 = verify_contract_resource()
        files = selected_tests()
        if args.list:
            for path in files:
                print(path.relative_to(ROOT).as_posix())
            return 0
        if importlib.util.find_spec("PySide6") is None:
            raise RuntimeError("The desktop dependency extra is required; native UI tests must not be silently skipped.")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        for directory in (ROOT, ROOT / "src", ROOT / "tests"):
            if str(directory) not in sys.path:
                sys.path.insert(0, str(directory))
        suite = unittest.defaultTestLoader.loadTestsFromNames([path.stem for path in files])
        cases = list(test_ids(suite))
        if suite.countTestCases() == 0:
            raise RuntimeError("No desktop/runtime tests were discovered.")
        before = source_attribution()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        after = source_attribution()
        unchanged = before["source_sha256"] == after["source_sha256"]
        passed = result.wasSuccessful() and unchanged
        interpreter = Path(getattr(sys, "_base_executable", sys.executable))
        report = {"schema": "ceta.desktop-runtime-verification.v2", "passed": passed,
                  "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                  "skipped": len(result.skipped), "elapsed_seconds": time.monotonic() - started,
                  "test_cases": cases, "skip_details": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
                  "failure_details": [{"test": test.id(), "traceback": trace} for test, trace in result.failures + result.errors],
                  "source_before": before, "source_unchanged_during_tests": unchanged,
                  "source_after_sha256": after["source_sha256"],
                  "interpreter": {"path": sys.executable, "version": sys.version,
                                  "base_executable": str(interpreter), "sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest()},
                  "operation_contracts_sha256": contract_sha256,
                  "test_files": [path.relative_to(ROOT).as_posix() for path in files],
                  "scope": "native desktop and governed runtime; no training, installer, or deployment claim"}
        if args.report is not None:
            with args.report.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
                handle.write("\n")
        print("CETA DESKTOP AND GOVERNED RUNTIME VERIFICATION: " + ("PASS" if passed else "FAIL"))
        return 0 if passed else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"CETA DESKTOP AND GOVERNED RUNTIME VERIFICATION: FAIL ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
