from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ceta_desktop.models import LocalModelClient, ModelDeadlineError, ModelError
from ceta_desktop.hardware import GIB, HardwareProfile
from ceta_desktop.runtime_coordination import (RuntimeCoordinationError, RuntimeLease,
                                              endpoint_owner, process_identity)
from runtime.model_provider import LocalProvider
from test_desktop_model_readiness import model_service, NATIVE_COMPLETE


class RuntimeCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture_environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}

    def lease(self, host="127.0.0.1", port=19271, **kwargs):
        return RuntimeLease(host, port, directory=self.directory, **kwargs)

    def test_loopback_aliases_share_a_lease_and_unrelated_ports_do_not(self):
        with self.lease():
            for host in ("localhost", "127.0.0.1", "::1"):
                with self.subTest(host=host), self.assertRaisesRegex(RuntimeCoordinationError, "Another CETA request"):
                    with self.lease(host):
                        self.fail("Duplicate lease admitted")
            with self.lease(port=19272):
                pass
        with self.lease():
            pass

    def test_os_lock_excludes_other_process_and_is_released_on_crash(self):
        code = "from ceta_desktop.runtime_coordination import RuntimeLease; import sys,os;\nwith RuntimeLease('localhost',19271,directory=sys.argv[1]): os._exit(7)"
        with self.lease():
            result = subprocess.run([sys.executable, "-B", "-c", code, str(self.directory)], capture_output=True, timeout=5, env=self.fixture_environment)
            self.assertNotEqual(result.returncode, 7)
            self.assertIn(b"Another CETA request", result.stderr)
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.directory)], capture_output=True, timeout=5, env=self.fixture_environment)
        self.assertEqual(result.returncode, 7)
        with self.lease():
            pass

    def test_dispatch_survives_crash_as_uncertain_without_replaying(self):
        code = "from ceta_desktop.runtime_coordination import RuntimeLease; import sys,os;\nwith RuntimeLease('localhost',19271,directory=sys.argv[1]) as lease:\n lease.begin_dispatch(); os._exit(7)"
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.directory)], capture_output=True, timeout=5, env=self.fixture_environment)
        self.assertEqual(result.returncode, 7, result.stderr.decode())
        with self.assertRaisesRegex(RuntimeCoordinationError, "uncertain"):
            with self.lease():
                pass
        with self.lease(allow_uncertain=True) as lease:
            self.assertEqual(lease.record["state"], "uncertain")
            with self.assertRaisesRegex(RuntimeCoordinationError, "no observable process identity"):
                lease.reconcile()

    def test_terminal_observation_clears_dispatch_but_metadata_failure_does_not_create_one(self):
        with self.lease() as lease:
            lease.begin_dispatch()
            lease.observe_terminal()
        with self.lease() as lease:
            self.assertEqual(lease.record["state"], "idle")
        try:
            with self.lease():
                raise ValueError("metadata failure before transmission")
        except ValueError:
            pass
        with self.lease() as lease:
            self.assertEqual(lease.record["state"], "idle")

    def test_corrupt_state_is_preserved_and_never_treated_as_idle(self):
        lease = self.lease()
        lease.path.write_text("broken state", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeCoordinationError, "damaged"):
            with lease:
                pass
        self.assertEqual(lease.path.read_text(), "broken state")

    def test_live_or_unobservable_original_process_cannot_be_cleared(self):
        original = {"pid": 100, "created_100ns": 123, "source": "Windows process times"}
        with patch("ceta_desktop.runtime_coordination.endpoint_owner", return_value=original):
            with self.lease() as lease:
                lease.begin_dispatch()
        with self.lease(allow_uncertain=True) as lease:
            with patch("ceta_desktop.runtime_coordination.process_identity", return_value=original):
                with self.assertRaisesRegex(RuntimeCoordinationError, "still alive"):
                    lease.reconcile()
            with patch("ceta_desktop.runtime_coordination.process_identity", side_effect=OSError("inaccessible")):
                with self.assertRaises(OSError):
                    lease.reconcile()
        self.assertEqual(json.loads(lease.path.read_text())["state"], "uncertain")

    @unittest.skipUnless(os.name == "nt", "Windows endpoint/process identity lane")
    def test_native_listener_exit_is_observed_without_certifying_worker_termination(self):
        code = "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(30)"
        child = subprocess.Popen([sys._base_executable, "-B", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            # Read a bounded child announcement; all cleanup owns this child.
            announced = []
            ready = threading.Event()
            def read_port():
                announced.append(child.stdout.readline())
                ready.set()
            reader = threading.Thread(target=read_port, daemon=True)
            reader.start()
            self.assertTrue(ready.wait(5))
            port = int(announced[0])
            owner = endpoint_owner("127.0.0.1", port)
            self.assertEqual(owner, process_identity(child.pid))
            with self.lease(port=port) as lease:
                lease.begin_dispatch()
            child.terminate()
            child.wait(timeout=3)
            with self.lease(port=port, allow_uncertain=True) as recovery:
                result = recovery.reconcile()
                self.assertEqual(result["method"], "original_service_process_ended")
                self.assertEqual(result["original_owner"], owner)
                self.assertEqual(result["state"], "uncertain")
            with self.assertRaisesRegex(RuntimeCoordinationError, "uncertain"):
                with self.lease(port=port):
                    pass
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
            child.stdout.close()
            child.stderr.close()

    @unittest.skipUnless(os.name == "nt", "Windows endpoint/process identity lane")
    def test_native_ipv6_listener_identity(self):
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(("::1", 0))
            except OSError as exc:
                self.skipTest("IPv6 loopback unavailable: " + str(exc))
            listener.listen()
            self.assertEqual(endpoint_owner("::1", listener.getsockname()[1]), process_identity(os.getpid()))


class CoordinatedTransportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("ceta_desktop.models.inspect_hardware", return_value=HardwareProfile(16 * GIB, 12 * GIB, 8)))

    def test_same_client_overlap_cannot_erase_the_active_terminal_observation(self):
        entered, release = threading.Event(), threading.Event()
        def busy(_):
            entered.set()
            release.wait(3)
            return NATIVE_COMPLETE
        with model_service({("POST", "/api/chat"): busy}) as (client, requests):
            results = []
            worker = threading.Thread(target=lambda: results.append(LocalProvider(client).stream("local:4b", [])))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                second = LocalProvider(client).stream("local:4b", [])
                self.assertEqual(second["status"], "failed")
                self.assertIn("client is already handling", second["error"])
                with self.assertRaisesRegex(ModelError, "client is already handling"):
                    client.request_profile("local:4b")
            finally:
                release.set()
                worker.join(3)
            self.assertEqual(results[0]["status"], "completed")
            self.assertEqual(results[0]["backend_state"]["state"], "idle")
            self.assertTrue(results[0]["backend_state"]["terminal_observed"])
            self.assertEqual(sum(path == "/api/chat" for _, path, _ in requests), 1)

    def test_transport_deadline_is_timed_out_even_before_monitor_poll(self):
        with model_service() as (client, requests), patch.object(client, "_request", side_effect=ModelDeadlineError("deadline")):
            result = LocalProvider(client).stream("local:4b", [])
            self.assertEqual(result["status"], "timed_out")
            self.assertEqual(result["backend_state"]["state"], "idle")
            self.assertEqual(requests, [])

    def test_cancelled_server_continues_but_next_client_is_blocked_across_restart(self):
        entered, release = threading.Event(), threading.Event()
        def still_generating(_):
            entered.set()
            release.wait(5)
            return NATIVE_COMPLETE
        with model_service({("POST", "/api/chat"): still_generating}) as (client, requests):
            results = []
            worker = threading.Thread(target=lambda: results.append(LocalProvider(client, context_length=4096).stream("local:4b", [])))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                client.cancel()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results[0]["status"], "cancelled")
                self.assertEqual(results[0]["backend_state"]["state"], "uncertain")
                replacement = LocalModelClient(f"http://localhost:{client.port}/v1", coordination_directory=client.coordination_directory)
                with self.assertRaisesRegex(ModelError, "uncertain"):
                    list(replacement.stream("local:4b", []))
                with self.assertRaisesRegex(RuntimeCoordinationError, "still alive"):
                    replacement.reconcile_runtime()
                self.assertEqual(sum(path == "/api/chat" for _, path, _ in requests), 1)
            finally:
                release.set()
                worker.join(3)

    def test_distinct_provider_and_probe_cannot_over_admit_same_runtime(self):
        entered, release = threading.Event(), threading.Event()
        def busy(_):
            entered.set()
            release.wait(5)
            return NATIVE_COMPLETE
        with model_service({("POST", "/api/chat"): busy}) as (client, requests):
            results = []
            worker = threading.Thread(target=lambda: results.append(LocalProvider(client).stream("local:4b", [])))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                second = LocalModelClient(f"http://localhost:{client.port}/other-prefix", coordination_directory=client.coordination_directory)
                blocked = LocalProvider(second).stream("local:4b", [])
                self.assertEqual(blocked["status"], "failed")
                self.assertIn("Another CETA request", blocked["error"])
                with self.assertRaisesRegex(ModelError, "Another CETA request"):
                    second.probe_local_model("local:4b")
            finally:
                release.set()
                worker.join(3)
            self.assertEqual(results[0]["backend_state"]["state"], "idle")
            self.assertEqual(sum(path == "/api/chat" for _, path, _ in requests), 1)

    def test_absolute_deadline_bounds_stalled_metadata_without_marking_dispatch(self):
        release = threading.Event()
        def stalled(_):
            release.wait(3)
            return {"models": []}
        with model_service({("GET", "/api/tags"): stalled}) as (client, _):
            before = time.monotonic()
            try:
                result = LocalProvider(client, timeout_seconds=.15).stream("local:4b", [])
                self.assertEqual(result["status"], "timed_out")
                self.assertLess(time.monotonic() - before, 1.5)
                self.assertFalse(result["backend_state"]["dispatched"])
                self.assertEqual(result["backend_state"]["state"], "idle")
            finally:
                release.set()


if __name__ == "__main__":
    unittest.main()
