from __future__ import annotations

import os
import errno
from pathlib import Path
import sys
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from ceta_desktop.hardware import GIB, _isolated_gpu_inventory, _run_inventory, inspect_hardware
from ceta_desktop.models import LocalModelClient
from ceta_desktop.request_control import (
    ModelCancelledError, ModelDeadlineError, ModelError, RequestBudget, checkpoint,
    current_budget, deadline_limit, request_scope,
)
from runtime.model_provider import LocalProvider
from runtime.tasks import TaskRuntime
from runtime import project_tools
from test_desktop_model_readiness import model_service


class BudgetTests(unittest.TestCase):
    def test_nested_stages_and_resumed_preparation_keep_one_deadline(self):
        clock = [100.0]
        with patch("ceta_desktop.request_control.time.monotonic", side_effect=lambda: clock[0]):
            with request_scope(10) as budget:
                clock[0] = 104
                with request_scope(10) as nested:
                    self.assertIs(nested, budget)
                    self.assertEqual(deadline_limit(200), 110)
                receipt = budget.receipt()
            self.assertIsNone(current_budget())
            clock[0] = 109
            with request_scope(10, receipt=receipt):
                clock[0] = 110
                with self.assertRaises(ModelDeadlineError):
                    checkpoint()
            with self.assertRaises(ModelDeadlineError):
                with request_scope(10, receipt=receipt):
                    self.fail("expired request resumed")

    def test_foreign_changed_or_nonfinite_receipts_are_refused(self):
        receipt = RequestBudget(10).receipt()
        for change in ({"origin": "other-process"}, {"seconds": 20}, {"deadline": float("inf")},
                       {"deadline": receipt["deadline"] + 1}, {"started": True}):
            with self.subTest(change=change), self.assertRaises(ModelError):
                RequestBudget(10, receipt={**receipt, **change})

    def test_cancel_is_preserved_and_context_does_not_leak_to_another_thread(self):
        event = threading.Event()
        with request_scope(10, event):
            values = []
            worker = threading.Thread(target=lambda: values.append(current_budget()))
            worker.start(); worker.join(1)
            self.assertEqual(values, [None])
            event.set()
            with self.assertRaises(ModelCancelledError):
                checkpoint()
        self.assertTrue(event.is_set())
        self.assertIsNone(current_budget())

    def test_nested_scope_cannot_replace_budget_or_extend_deadline(self):
        with request_scope(1):
            with self.assertRaisesRegex(ModelError, "changed within"):
                with request_scope(10):
                    pass


class RequestDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runtime = TaskRuntime(self.directory / "data")
        self.addCleanup(self.runtime.close)
        self.runtime.application_project()
        self.task = self.runtime.start_task("application", "Synthetic request deadline")
        self.messages = [{"role": "user", "content": "hello"}]

    def test_preparation_cancellation_interrupts_metadata_with_distinct_client_event(self):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        def stalled(_):
            entered.set(); release.wait(4)
            return {"models": []}
        with model_service({("GET", "/api/tags"): stalled}) as (client, requests):
            errors = []
            def prepare():
                try:
                    self.runtime.prepare_generation(self.task["task_id"], LocalProvider(client),
                        "local:4b", self.messages, cancelled=cancelled)
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=prepare)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                started = time.monotonic(); cancelled.set(); worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertLess(time.monotonic() - started, 2)
                self.assertIsInstance(errors[0], ModelCancelledError)
                self.assertFalse(client.cancelled.is_set())
                self.assertNotIn("/api/chat", [path for _, path, _ in requests])
                self.assertEqual(self.runtime.journal.events("application", kind="provider.intent"), [])
            finally:
                release.set(); worker.join(3)

    def test_preparation_deadline_covers_metadata_before_generation(self):
        release = threading.Event()
        def stalled(_):
            release.wait(3)
            return {"models": []}
        with model_service({("GET", "/api/tags"): stalled}) as (client, requests):
            try:
                started = time.monotonic()
                with self.assertRaises(ModelDeadlineError):
                    self.runtime.prepare_generation(self.task["task_id"], LocalProvider(client, timeout_seconds=.4),
                        "local:4b", self.messages)
                self.assertLess(time.monotonic() - started, 1.5)
                self.assertFalse(client.cancelled.is_set())
                self.assertNotIn("/api/chat", [path for _, path, _ in requests])
            finally:
                release.set()

    def test_context_scan_observes_request_cancel_before_source_or_git_reads(self):
        root = self.directory / "project"
        root.mkdir()
        cancelled = threading.Event()
        with request_scope(10, cancelled):
            cancelled.set()
            with patch("runtime.project_tools.os.scandir") as scan, patch("runtime.project_tools._capture_git") as git:
                with self.assertRaises(ModelCancelledError):
                    project_tools.inspect_project(root)
                scan.assert_not_called(); git.assert_not_called()

    def test_context_scan_observes_cancellation_during_directory_enumeration(self):
        cancelled = threading.Event()
        seen = []
        def entries():
            for index in range(100):
                seen.append(index)
                if index == 4:
                    cancelled.set()
                yield Mock()
        with request_scope(10, cancelled), patch("runtime.project_tools.os.scandir") as scan:
            scan.return_value.__enter__.return_value = entries()
            with self.assertRaises(ModelCancelledError):
                project_tools._inventory(self.directory)
        self.assertEqual(seen, list(range(5)))

    def test_nonprogressing_connect_respects_shared_deadline(self):
        client = LocalModelClient("http://127.0.0.1:11435/v1")
        with patch("ceta_desktop.models.ModelSocket.connect_ex", return_value=errno.EINPROGRESS), \
             patch("ceta_desktop.models.select.select", return_value=([], [], [])):
            started = time.monotonic()
            try:
                with request_scope(.1), self.assertRaises(ModelDeadlineError):
                    client._request("GET", "/models")
            finally:
                if client.connection:
                    client.connection.close()
        self.assertLess(time.monotonic() - started, 1)

    def test_nonreading_peer_cannot_hold_request_write_past_deadline(self):
        accepted, release = threading.Event(), threading.Event()
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        listener.bind(("127.0.0.1", 0)); listener.listen(1)
        def peer():
            with listener.accept()[0]:
                accepted.set(); release.wait(3)
        worker = threading.Thread(target=peer)
        worker.start()
        client = LocalModelClient(f"http://127.0.0.1:{listener.getsockname()[1]}/v1")
        started = time.monotonic()
        try:
            with request_scope(.3), self.assertRaises(ModelDeadlineError):
                client._request("POST", "/fixture", {"text": "x" * (8 * 1024 * 1024)})
            self.assertTrue(accepted.is_set())
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertFalse(client.cancelled.is_set())
        finally:
            if client.connection:
                client.connection.close()
            release.set(); listener.close(); worker.join(3)

    def test_preparation_review_and_generation_share_limit_and_preserve_partial_text(self):
        clock = [100.0]
        class Client:
            def __init__(self):
                self.cancelled = threading.Event()
                self.calls = 0
            def request_profile(self, model):
                clock[0] += .2
                return {"model": model, "backend": "adapter"}
            def cancel(self):
                self.cancelled.set()
            def stream(self, model, messages, **kwargs):
                kwargs["before_dispatch"]()
                self.calls += 1
                clock[0] += .1
                yield "first"
                clock[0] += .5
                yield "late"
        client = Client()
        provider = LocalProvider(client, timeout_seconds=1)
        with patch("ceta_desktop.request_control.time.monotonic", side_effect=lambda: clock[0]):
            prepared = self.runtime.prepare_generation(self.task["task_id"], provider, "fixture", self.messages)
            clock[0] += .2  # The native preview/review time consumes the same budget.
            result = self.runtime.generate(self.task["task_id"], provider, "fixture", self.messages, prepared=prepared)
        self.assertEqual(client.calls, 1)
        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(result["text"], "first")
        self.assertEqual(result["request_time_budget"], prepared["request_time_budget"])
        recorded = self.runtime.journal.events("application", kind="provider.result")[-1]["payload"]
        self.assertEqual((recorded["status"], recorded["text"]), ("timed_out", "first"))

    def test_late_cancel_monitor_cannot_cancel_a_subsequent_use_of_the_client(self):
        entered, release = threading.Event(), threading.Event()
        monitors = []
        class Cancellation:
            def is_set(self):
                if threading.current_thread().name == "ceta-provider-cancellation":
                    monitors.append(threading.current_thread())
                    entered.set(); release.wait(3)
                    return True
                return False
        client = Mock(cancelled=threading.Event())
        def stream(*args, **kwargs):
            self.assertTrue(entered.wait(2))
            yield "finished"
        client.stream = stream
        try:
            result = LocalProvider(client).stream("fixture", [], cancelled=Cancellation())
            self.assertEqual(result["status"], "completed")
        finally:
            release.set()
            for worker in monitors:
                worker.join(1)
        client.cancel.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Windows owned inventory required")
class HardwareDeadlineTests(unittest.TestCase):
    def test_host_ram_admission_does_not_wait_for_gpu_inventory(self):
        with patch("ceta_desktop.hardware._physical_memory", return_value=(16 * GIB, 12 * GIB)), \
             patch("ceta_desktop.hardware._isolated_gpu_inventory") as gpu, \
             patch("ceta_desktop.hardware.shutil.which") as executable:
            result = inspect_hardware(include_gpus=False)
        self.assertEqual(result.available_ram_bytes, 12 * GIB)
        gpu.assert_not_called(); executable.assert_not_called()

    def test_cancel_stalled_owned_inventory_stops_all_workers_within_two_seconds(self):
        from ceta_desktop.windows_job import WindowsJobProcess, inspect_job
        entered, cancelled = threading.Event(), threading.Event()
        jobs, errors = [], []
        original = WindowsJobProcess.start
        def start(process, *args):
            original(process, *args)
            jobs.append(process.name); entered.set()
        def inspect():
            try:
                _run_inventory([sys.executable, "-c", "import time; time.sleep(30)"], cancelled=cancelled)
            except Exception as exc:
                errors.append(exc)
        with patch.object(WindowsJobProcess, "start", start):
            worker = threading.Thread(target=inspect)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                started = time.monotonic(); cancelled.set(); worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertLess(time.monotonic() - started, 2)
            finally:
                cancelled.set(); worker.join(4)
        self.assertIsInstance(errors[0], ModelCancelledError)
        self.assertTrue(jobs)
        self.assertTrue(all(inspect_job(name)["active_processes"] == 0 for name in jobs))

    def test_owned_inventory_deadline_and_output_limit(self):
        started = time.monotonic()
        with self.assertRaises(ModelDeadlineError):
            _run_inventory([sys.executable, "-c", "import time; time.sleep(30)"], deadline=started + .2)
        self.assertLess(time.monotonic() - started, 2)
        with self.assertRaisesRegex(ValueError, "too much"):
            _run_inventory([sys.executable, "-c", "print('x'*65537)"])

    def test_actual_gpu_probe_child_returns_bounded_inventory(self):
        rows = _isolated_gpu_inventory()
        self.assertIsInstance(rows, tuple)
        self.assertLessEqual(len(rows), 64)

    def test_frozen_dispatch_and_untrusted_helper_results(self):
        from scripts.desktop_entry import launch
        with patch.object(sys, "argv", ["CETA.exe", "--hardware-gpu-probe"]), \
             patch("ceta_desktop.hardware.gpu_probe", return_value=0) as probe:
            self.assertEqual(launch(), 0)
            probe.assert_called_once_with()
        with patch.object(sys, "frozen", True, create=True), \
             patch("ceta_desktop.hardware._run_inventory", return_value="[]") as command:
            self.assertEqual(_isolated_gpu_inventory(), ())
            self.assertEqual(command.call_args.args[0], [sys.executable, "--hardware-gpu-probe"])
            for malformed in ('{}', '[["GPU",true,1]]', '[["GPU",4,5]]', '[["GPU",4,-1]]'):
                command.return_value = malformed
                with self.assertRaises(ValueError):
                    _isolated_gpu_inventory()


if __name__ == "__main__":
    unittest.main()
