from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from authority import (  # noqa: E402
    AuthorityBindingError,
    AuthorityLedger,
    Permit,
    PermitReuseError,
    PermitStatus,
    canonical_hash,
)


def _consume(ledger, intent):
    try:
        ledger.consume(
            "P1", consumer_id="gateway", consumer_key_id="key",
            intent_hash=intent, now_ms=3,
        )
        return "consumed"
    except PermitReuseError:
        return "rejected"


def _consume_in_process(path, intent, start, results):
    try:
        ledger = AuthorityLedger(path)
        results.put("ready")
        if not start.wait(15):
            results.put("start timeout")
            return
        results.put(_consume(ledger, intent))
    except Exception as exc:
        results.put(f"{type(exc).__name__}: {exc}")


class AuthorityConcurrencyTests(unittest.TestCase):
    def permit(self, permit_id="P1", nonce="N1"):
        consequence = {"effect": "write", "resource": "/bounded/file"}
        return Permit(
            permit_id=permit_id, nonce=nonce, policy_epoch="E1",
            subject_scope="/bounded", operation="Execute",
            consequence_hash=canonical_hash(consequence), consumer_id="gateway",
            consumer_key_id="key", expires_at_epoch_ms=1000, source_refs=("T1",),
        ), consequence

    def prepare(self, path=None):
        ledger = AuthorityLedger(path)
        permit, consequence = self.permit()
        ledger.issue(permit, consequence=consequence, now_ms=1)
        intent = ledger.prepare(
            "P1", consumer_id="gateway", consumer_key_id="key",
            consequence=consequence, now_ms=2,
        )
        return ledger, intent

    def assert_single_consumption(self, ledger):
        self.assertTrue(ledger.verify())
        self.assertEqual(ledger.status("P1"), PermitStatus.CONSUMED)
        self.assertEqual(sum(e.event_type == "CONSUME" for e in ledger.events), 1)

    def test_stale_instances_cannot_both_consume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.jsonl"
            first, intent = self.prepare(path)
            second = AuthorityLedger(path)
            self.assertEqual(_consume(first, intent), "consumed")
            self.assertEqual(_consume(second, intent), "rejected")
            self.assert_single_consumption(AuthorityLedger(path))

    def test_reads_refresh_durable_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.jsonl"
            first, intent = self.prepare(path)
            second = AuthorityLedger(path)
            _consume(first, intent)
            self.assertTrue(second.consumed("N1"))
            self.assertEqual(second.snapshot()["permits"]["P1"]["status"], "CONSUMED")
            self.assertEqual(second.current_root, first.current_root)

    def test_relative_ledger_does_not_follow_later_working_directory_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(first)
                ledger, intent = self.prepare("authority.jsonl")
                os.chdir(second)
                self.assertEqual(_consume(ledger, intent), "consumed")
            finally:
                os.chdir(previous)
            self.assert_single_consumption(AuthorityLedger(first / "authority.jsonl"))
            self.assertEqual(list(second.iterdir()), [])

    def test_stale_writers_preserve_each_others_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.jsonl"
            first, second = AuthorityLedger(path), AuthorityLedger(path)
            for ledger, permit_id, nonce in ((first, "P1", "N1"), (second, "P2", "N2")):
                permit, consequence = self.permit(permit_id, nonce)
                ledger.issue(permit, consequence=consequence, now_ms=1)
            self.assertEqual(set(first.snapshot()["permits"]), {"P1", "P2"})
            self.assertTrue(AuthorityLedger(path).verify())

    def test_threads_cannot_double_consume_in_memory(self):
        ledger, intent = self.prepare()
        start = threading.Barrier(2)

        def attempt():
            start.wait(timeout=10)
            return _consume(ledger, intent)

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ["consumed", "rejected"])
        self.assert_single_consumption(ledger)

    def test_processes_cannot_double_consume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.jsonl"
            _, intent = self.prepare(path)
            context = multiprocessing.get_context("spawn")
            start, results = context.Event(), context.Queue()
            processes = [
                context.Process(target=_consume_in_process, args=(str(path), intent, start, results))
                for _ in range(2)
            ]
            try:
                for process in processes:
                    process.start()
                self.assertEqual(results.get(timeout=15), "ready")
                self.assertEqual(results.get(timeout=15), "ready")
                start.set()
                self.assertCountEqual(
                    [results.get(timeout=15), results.get(timeout=15)],
                    ["consumed", "rejected"],
                )
                for process in processes:
                    process.join(timeout=15)
                    self.assertEqual(process.exitcode, 0)
                self.assert_single_consumption(AuthorityLedger(path))
            finally:
                start.set()
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=5)
                results.close()
                results.join_thread()

    def test_live_instance_rejects_truncated_consumption_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.jsonl"
            ledger, intent = self.prepare(path)
            prepared_bytes = path.read_bytes()
            _consume(ledger, intent)
            path.write_bytes(prepared_bytes)
            with self.assertRaisesRegex(AuthorityBindingError, "regressed"):
                _consume(ledger, intent)
            self.assertTrue(ledger._consumed_nonces == {"N1"})

    def test_live_instance_rejects_disappeared_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.jsonl"
            ledger, intent = self.prepare(path)
            _consume(ledger, intent)
            path.unlink()
            with self.assertRaisesRegex(AuthorityBindingError, "disappeared"):
                ledger.snapshot()


if __name__ == "__main__":
    unittest.main()
