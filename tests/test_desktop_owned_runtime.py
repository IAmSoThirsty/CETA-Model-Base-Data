from __future__ import annotations

import json
import importlib.util
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ceta_desktop.runtime_coordination import RuntimeLease, RuntimeCoordinationError, endpoint_owner, process_identity
from ceta_desktop.windows_job import WindowsJobProcess, inspect_job


@unittest.skipUnless(os.name == "nt", "Windows job containment requires Windows")
class OwnedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture_environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        self.process = WindowsJobProcess()
        self.addCleanup(self.process.close)

    def start(self, script, callback=lambda job: None):
        self.process.start(sys._base_executable, ["-u", "-c", script], dict(os.environ), callback)

    def until(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = condition()
            if result:
                return result
            time.sleep(0.01)
        self.fail("Timed out waiting for the contained fixture")

    def test_assignment_and_registration_precede_first_child_instruction(self):
        marker = self.root / "ran.txt"
        observations = []
        def registered(job):
            time.sleep(0.04)
            self.assertFalse(marker.exists())
            observations.append(inspect_job(job.name, process_identity(job.pid)))
        self.start(f"from pathlib import Path; Path({str(marker)!r}).write_text('executed')", registered)
        self.until(marker.exists)
        self.until(lambda: self.process.poll() is not None)
        self.assertTrue(observations[0]["owner_contained"])
        self.assertEqual(self.process.last_observation["active_processes"], 0)

    def test_failed_registration_never_executes_child(self):
        marker = self.root / "must-not-run.txt"
        def rejected(job):
            raise OSError("durable registration failed")
        with self.assertRaisesRegex(OSError, "registration failed"):
            self.start(f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')", rejected)
        self.assertFalse(marker.exists())
        self.assertEqual(inspect_job(self.process.name)["state"], "absent")

    def test_assignment_failure_never_executes_child(self):
        marker = self.root / "must-not-run.txt"
        with patch.object(self.process.api, "AssignProcessToJobObject", return_value=0), self.assertRaises(OSError):
            self.start(f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')")
        self.assertFalse(marker.exists())

    def test_root_exit_does_not_report_finished_until_grandchild_ended(self):
        grandchild = "import time; time.sleep(30)"
        child = ("import subprocess,sys,json; "
                 f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
                 "print(json.dumps({'grandchild':p.pid}),flush=True)")
        self.start("import subprocess,sys; " + f"p=subprocess.Popen([sys.executable,'-u','-c',{child!r}]); p.wait()")
        data = bytearray()
        def output():
            data.extend(self.process.read())
            return b"\n" in data
        self.until(output)
        grandchild_pid = json.loads(data)["grandchild"]
        identity = process_identity(grandchild_pid)
        self.assertIsNotNone(identity)
        self.until(lambda: self.process.poll() is not None)
        self.assertIsNone(process_identity(grandchild_pid))
        self.assertGreaterEqual(self.process.last_observation["total_processes"], 3)
        self.assertEqual(self.process.last_observation["active_processes"], 0)

    def test_explicit_stop_terminates_root_and_child(self):
        child = "import time; time.sleep(30)"
        self.start("import subprocess,sys,time; " + f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
                   "print(p.pid,flush=True); time.sleep(30)")
        data = bytearray()
        def output():
            data.extend(self.process.read())
            return b"\n" in data
        self.until(output)
        child_pid = int(data)
        self.process.stop()
        self.until(lambda: self.process.poll() is not None)
        self.assertIsNone(process_identity(child_pid))
        self.assertIsNone(process_identity(self.process.pid))

    def test_owner_crash_closes_last_job_handle_and_ends_children(self):
        record = self.root / "job.json"
        runtime = "import time; time.sleep(30)"
        helper = ("import json,os,sys; from pathlib import Path; "
                  "from ceta_desktop.windows_job import WindowsJobProcess; "
                  "p=WindowsJobProcess(); "
                  f"p.start(sys.executable,['-c',{runtime!r}],dict(os.environ),lambda _:None); "
                  f"Path({str(record)!r}).write_text(json.dumps({{'pid':p.pid,'job':p.name}})); "
                  "sys.stdin.readline(); os._exit(0)")
        owner = subprocess.Popen([sys._base_executable, "-c", helper], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW, env=self.fixture_environment)
        self.addCleanup(self.cleanup_child, owner)
        self.until(record.exists)
        result = json.loads(record.read_text())
        self.assertIsNotNone(process_identity(result["pid"]))
        out, err = owner.communicate(b"exit\n", timeout=5)
        self.assertEqual(owner.returncode, 0, (out, err))
        self.until(lambda: process_identity(result["pid"]) is None)
        self.assertEqual(inspect_job(result["job"])["state"], "absent")

    def test_membership_rejects_unrelated_process_and_invalid_names(self):
        self.assertFalse(inspect_job(self.process.name, process_identity(os.getpid()))["owner_contained"])
        with self.assertRaises(ValueError):
            inspect_job("arbitrary-other-job")

    def free_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    def start_registered(self, port):
        with RuntimeLease("127.0.0.1", port, directory=self.root, allow_uncertain=True) as lease:
            lease.prepare_owned_start()
            self.start("import socket,time; s=socket.socket(); "
                       f"s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(30)", lease.register_owned)
        self.until(lambda: endpoint_owner("127.0.0.1", port))

    def test_uncertainty_clears_only_after_owned_workers_end(self):
        port = self.free_port()
        self.start_registered(port)
        with RuntimeLease("127.0.0.1", port, directory=self.root) as lease:
            lease.begin_dispatch()
            self.assertTrue(lease.record["dispatch_job"]["owner_contained"])
        with RuntimeLease("127.0.0.1", port, directory=self.root, allow_uncertain=True) as lease:
            with self.assertRaisesRegex(RuntimeCoordinationError, "workers are still alive"):
                lease.reconcile()
        self.process.stop()
        self.until(lambda: self.process.poll() is not None)
        # Reopen the durable state through a new lease, as after app restart.
        with RuntimeLease("localhost", port, directory=self.root, allow_uncertain=True) as lease:
            observed = lease.reconcile()
            self.assertEqual(observed["method"], "owned_job_ended")
            self.assertEqual(observed["job"]["active_processes"], 0)
            self.assertEqual(lease.record["state"], "idle")
        with RuntimeLease("127.0.0.1", port, directory=self.root):
            pass

    def test_endpoint_replacement_cannot_inherit_owned_dispatch(self):
        port = self.free_port()
        self.start_registered(port)
        with RuntimeLease("127.0.0.1", port, directory=self.root) as lease:
            with patch("ceta_desktop.runtime_coordination.endpoint_owner", return_value=process_identity(os.getpid())):
                with self.assertRaisesRegex(RuntimeCoordinationError, "not served by the runtime"):
                    lease.begin_dispatch()
            self.assertFalse(lease.dispatched)
            self.assertEqual(lease.record["state"], "idle")

    def test_second_start_and_occupied_external_port_are_rejected(self):
        port = self.free_port()
        self.start_registered(port)
        with RuntimeLease("localhost", port, directory=self.root, allow_uncertain=True) as lease:
            with self.assertRaisesRegex(RuntimeCoordinationError, "already starting or running"):
                lease.prepare_owned_start()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            other = listener.getsockname()[1]
            with RuntimeLease("127.0.0.1", other, directory=self.root, allow_uncertain=True) as lease:
                with self.assertRaisesRegex(RuntimeCoordinationError, "already occupied"):
                    lease.prepare_owned_start()

    def test_query_failure_keeps_uncertainty(self):
        port = self.free_port()
        self.start_registered(port)
        with RuntimeLease("127.0.0.1", port, directory=self.root) as lease:
            lease.begin_dispatch()
        with RuntimeLease("127.0.0.1", port, directory=self.root, allow_uncertain=True) as lease:
            with patch("ceta_desktop.windows_job.inspect_job", side_effect=OSError("access denied")):
                with self.assertRaisesRegex(OSError, "access denied"):
                    lease.reconcile()
            self.assertEqual(lease.record["state"], "uncertain")

    def test_crashed_owner_dispatch_is_recoverable_from_saved_job_identity(self):
        record = self.root / "crash-ready.json"
        port = self.free_port()
        runtime = ("import socket,time; s=socket.socket(); "
                   f"s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(30)")
        helper = f"""
import json,os,sys,time
from pathlib import Path
from ceta_desktop.windows_job import WindowsJobProcess
from ceta_desktop.runtime_coordination import RuntimeLease,endpoint_owner
p=WindowsJobProcess()
with RuntimeLease('127.0.0.1',{port},directory={str(self.root)!r},allow_uncertain=True) as lease:
    lease.prepare_owned_start()
    p.start(sys.executable,['-c',{runtime!r}],dict(os.environ),lease.register_owned)
deadline=time.monotonic()+5
while not endpoint_owner('127.0.0.1',{port}):
    if time.monotonic()>deadline: raise TimeoutError('fixture listener did not start')
    time.sleep(.01)
with RuntimeLease('127.0.0.1',{port},directory={str(self.root)!r}) as lease:
    lease.begin_dispatch()
    Path({str(record)!r}).write_text(json.dumps({{'pid':p.pid,'job':p.name}}))
    sys.stdin.readline()
    os._exit(0)
"""
        owner = subprocess.Popen([sys._base_executable, "-c", helper], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW, env=self.fixture_environment)
        self.addCleanup(self.cleanup_child, owner)
        self.until(record.exists)
        saved = json.loads(record.read_text())
        out, err = owner.communicate(b"crash\n", timeout=5)
        self.assertEqual(owner.returncode, 0, (out, err))
        self.until(lambda: process_identity(saved["pid"]) is None)
        with RuntimeLease("127.0.0.1", port, directory=self.root, allow_uncertain=True) as lease:
            self.assertEqual(lease.record["state"], "uncertain")
            result = lease.reconcile()
            self.assertEqual(result["method"], "owned_job_ended")
            self.assertEqual(result["job"]["state"], "absent")

    @staticmethod
    def cleanup_child(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    from ceta_desktop.owned_process import OwnedModelProcess


@unittest.skipUnless(os.name == "nt" and HAS_QT, "Native Windows desktop extra required")
class OwnedQtProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.process = OwnedModelProcess(coordination_directory=self.root)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.process.setEndpoint("127.0.0.1", self.port)
        self.process.setProgram(sys._base_executable)

    def tearDown(self):
        self.process.kill()
        self.assertTrue(self.process.waitForFinished(3000))
        self.process.deleteLater()
        self.application.processEvents()

    def test_native_signals_output_and_worker_shutdown(self):
        events, output = [], bytearray()
        self.process.started.connect(lambda: events.append("started"))
        self.process.errorOccurred.connect(lambda error: events.append(str(error)))
        self.process.finished.connect(lambda code, status: events.append((code, status)))
        self.process.readyReadStandardOutput.connect(lambda: output.extend(bytes(self.process.readAllStandardOutput())))
        self.process.setArguments(["-u", "-c", "import time; print('ready',flush=True); time.sleep(30)"])
        self.process.start()
        self.assertEqual(events, ["started"])
        self.assertEqual(self.process.state(), QProcess.Running)
        deadline = time.monotonic() + 3
        while not output and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(.01)
        self.assertEqual(output, b"ready\r\n")
        self.process.kill()
        self.assertTrue(self.process.waitForFinished(3000))
        self.assertEqual(self.process.state(), QProcess.NotRunning)
        self.assertEqual(self.process.last_observation["active_processes"], 0)
        self.assertEqual(len(events), 2)

    def test_failed_start_has_no_started_or_finished_success(self):
        events = []
        self.process.started.connect(lambda: events.append("started"))
        self.process.finished.connect(lambda *_: events.append("finished"))
        self.process.errorOccurred.connect(lambda _: events.append("error"))
        self.process.setProgram(str(self.root / "missing.exe"))
        self.process.start()
        self.assertEqual(events, ["error"])
        self.assertEqual(self.process.state(), QProcess.NotRunning)
        self.assertTrue(self.process.errorString())


if __name__ == "__main__":
    unittest.main()
