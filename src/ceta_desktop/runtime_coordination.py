"""Cross-process local runtime admission and durable uncertain-dispatch state."""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import time
from uuid import uuid4


class RuntimeCoordinationError(ValueError):
    pass


def default_directory():
    # Stable across --data-dir choices, scoped to cooperating CETA processes in
    # this OS account. Other clients and other users are outside this lease.
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) if os.name == "nt" else \
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "CETA" / "runtime-coordination"


def process_identity(pid):
    """Windows PID plus creation time, or None when that process no longer exists.

    Inaccessible/unsupported observation raises; it never means the process died.
    """
    if os.name != "nt":
        raise RuntimeCoordinationError("Service process identity is not implemented on this platform.")
    if type(pid) is not int or pid <= 0:
        raise RuntimeCoordinationError("Invalid service process ID.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: PID is no longer present.
            return None
        raise OSError(error, "Cannot inspect service process identity")
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_uint64)] * 4
    try:
        state = kernel.WaitForSingleObject(handle, 0)
        if state == 0:
            return None
        if state != 258:
            raise OSError("Cannot determine whether the service process is alive")
        created, exited, system, user = (ctypes.c_uint64() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"pid": pid, "created_100ns": created.value, "source": "Windows process times"}
    finally:
        kernel.CloseHandle(handle)


def endpoint_owner(host, port):
    return _socket_owner(host, port)


def connection_owner(host, port, client_port):
    return _socket_owner(host, port, client_port)


def _tcp_rows(host, *, connections=False):
    if os.name != "nt":
        raise RuntimeCoordinationError("Local endpoint ownership is not implemented on this platform.")
    ipv6 = host == "::1"
    family = 23 if ipv6 else 2
    api = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int,
                    ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    api.restype = ctypes.c_uint32
    size = ctypes.c_uint32()
    table_class = 4 if connections else 3  # OWNER_PID_CONNECTIONS / LISTENER
    code = api(None, ctypes.byref(size), False, family, table_class, 0)
    if code not in {0, 122}:
        raise OSError(code, "Cannot inspect local runtime listener")
    for _ in range(3):
        if not 4 <= size.value <= 8 * 1024 * 1024:
            raise RuntimeCoordinationError("Invalid local listener table size.")
        buffer = ctypes.create_string_buffer(size.value)
        code = api(buffer, ctypes.byref(size), False, family, table_class, 0)
        if code != 122:
            break
    if code:
        raise OSError(code, "Cannot inspect local runtime listener")
    raw = buffer.raw
    count = struct.unpack_from("<I", raw)[0]
    width = 56 if ipv6 else 24
    if count > (len(raw) - 4) // width:
        raise RuntimeCoordinationError("Malformed local listener table.")
    rows = []
    for index in range(count):
        row = raw[4 + index * width:4 + (index + 1) * width]
        address = row[:16] if ipv6 else row[4:8]
        raw_port = struct.unpack_from("<I", row, 20 if ipv6 else 8)[0]
        remote_port = struct.unpack_from("<I", row, 44 if ipv6 else 16)[0]
        remote_address = row[24:40] if ipv6 else row[12:16]
        rows.append({"address": address, "port": socket.ntohs(raw_port & 0xffff),
                     "remote_address": remote_address, "remote_port": socket.ntohs(remote_port & 0xffff),
                     "pid": struct.unpack_from("<I", row, 52 if ipv6 else 20)[0]})
    return rows


def loopback_listeners():
    """Read IPv4 loopback listeners without opening connections to any of them."""
    return [{"host": "127.0.0.1", "port": row["port"], "pid": row["pid"]}
            for row in _tcp_rows("127.0.0.1") if row["address"] == socket.inet_aton("127.0.0.1")]


def _socket_owner(host, port, client_port=None):
    target = socket.inet_pton(socket.AF_INET6 if host == "::1" else socket.AF_INET, host)
    pids = set()
    for row in _tcp_rows(host, connections=client_port is not None):
        if client_port is not None and (row["remote_port"] != client_port or row["remote_address"] != target):
            continue
        if row["port"] == port and row["address"] in (target, bytes(len(target))):
            pids.add(row["pid"])
    if not pids:
        return None
    if len(pids) != 1:
        raise RuntimeCoordinationError("The local endpoint has ambiguous process ownership.")
    return process_identity(pids.pop())


class RuntimeLease:
    def __init__(self, host, port, *, directory=None, allow_uncertain=False):
        if host not in {"localhost", "127.0.0.1", "::1"} or type(port) is not int or not 1 <= port <= 65535:
            raise RuntimeCoordinationError("Runtime coordination requires a loopback endpoint.")
        # Prefix and loopback spelling cannot create independent capacity leases.
        self.key = f"loopback:{port}"
        self.host, self.port = ("127.0.0.1" if host == "localhost" else host), port
        self.directory = Path(directory) if directory is not None else default_directory()
        self.identity = hashlib.sha256(self.key.encode()).hexdigest()
        self.path = self.directory / (self.identity + ".json")
        self.allow_uncertain = allow_uncertain
        self.descriptor = None
        self.record = {"schema": "ceta.runtime-state.v1", "runtime": self.key, "state": "idle"}
        self.dispatched = False
        self.terminal = False
        self.busy = False

    def _write(self):
        temporary = self.path.with_name(self.path.name + ".next-" + uuid4().hex)
        data = json.dumps(self.record, sort_keys=True, allow_nan=False).encode()
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.descriptor = os.open(str(self.directory / (self.identity + ".lock")), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.descriptor)
            self.descriptor = None
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                self.busy = True
                raise RuntimeCoordinationError("Another CETA request is using this local runtime. Wait for it to finish.") from exc
            raise
        try:
            if self.path.exists():
                if self.path.stat().st_size > 32768:
                    raise RuntimeCoordinationError("Runtime state is too large; preserve it for recovery.")
                try:
                    self.record = json.loads(self.path.read_text(encoding="utf-8"))
                except (ValueError, UnicodeError) as exc:
                    raise RuntimeCoordinationError("Runtime state is damaged; preserve it for recovery.") from exc
                if not isinstance(self.record, dict) or self.record.get("schema") != "ceta.runtime-state.v1" or \
                        self.record.get("runtime") != self.key or self.record.get("state") not in {"idle", "in_flight", "uncertain"}:
                    raise RuntimeCoordinationError("Runtime state is unsupported; preserve it for recovery.")
            if self.record["state"] == "in_flight":
                self.record.update(state="uncertain", reason="request_process_ended_without_terminal_observation")
                self._write()
            if self.record["state"] == "uncertain" and not self.allow_uncertain:
                raise RuntimeCoordinationError("Backend state is uncertain after an interrupted request. Use Recheck runtime to inspect the original service; residency or server restart alone cannot prove worker termination.")
            return self
        except BaseException:
            self._release()
            raise

    def begin_dispatch(self, *, client_port=None, operation="generation"):
        if self.descriptor is None or self.dispatched:
            raise RuntimeCoordinationError("The runtime lease cannot admit another dispatch.")
        try:
            owner = endpoint_owner(self.host, self.port) if client_port is None else connection_owner(self.host, self.port, client_port)
            observation_error = None
        except (OSError, ValueError) as exc:
            owner, observation_error = None, str(exc)
        owned = self.record.get("owned_runtime")
        dispatch_job = None
        if owned is not None:
            from .windows_job import inspect_job
            if not isinstance(owned, dict) or not owner:
                raise RuntimeCoordinationError("The owned runtime endpoint identity is unavailable; generation was not sent.")
            observation = inspect_job(owned.get("job_name"), owner)
            if not observation.get("owner_contained"):
                raise RuntimeCoordinationError("This endpoint is not served by the runtime CETA started. Recheck or restart the owned runtime.")
            dispatch_job = observation
        self.record = {**self.record, "state": "in_flight", "request_id": uuid4().hex, "operation": operation,
                       "started_at": time.time(), "owner": owner, "owner_error": observation_error,
                       "dispatch_job": dispatch_job}
        self._write()  # Persist uncertainty before sending any generation bytes.
        self.dispatched = True

    def observe_terminal(self):
        if self.dispatched:
            self.terminal = True

    def prepare_owned_start(self):
        if self.descriptor is None or not self.allow_uncertain:
            raise RuntimeCoordinationError("Owned startup requires an exclusive recovery lease.")
        if self.record["state"] != "idle":
            self.reconcile()
            if self.record["state"] != "idle":
                raise RuntimeCoordinationError("Resolve the interrupted runtime before starting another on this endpoint.")
        owned = self.record.get("owned_runtime")
        if owned:
            from .windows_job import inspect_job
            if inspect_job(owned.get("job_name"))["active_processes"]:
                raise RuntimeCoordinationError("A CETA-owned runtime is already starting or running on this endpoint.")
        if endpoint_owner(self.host, self.port) is not None:
            raise RuntimeCoordinationError("The runtime port is already occupied. Connect to that service explicitly or stop it before starting CETA's runtime.")

    def register_owned(self, process):
        if self.descriptor is None or self.record["state"] != "idle":
            raise RuntimeCoordinationError("Owned startup is not admitted by this lease.")
        from .windows_job import inspect_job
        owner = process_identity(process.pid)
        observation = inspect_job(process.name, owner)
        if not owner or not observation.get("owner_contained"):
            raise RuntimeCoordinationError("The suspended runtime could not be bound to its Windows job.")
        self.record.update(owned_runtime={**observation, "root_owner": owner,
                                          "registered_at": time.time(), "scope": "Windows job members"})
        self._write()  # Failure prevents ResumeThread; the child cannot execute.

    def reconcile(self):
        if not self.allow_uncertain or self.descriptor is None:
            raise RuntimeCoordinationError("Runtime reconciliation requires an exclusive recovery lease.")
        job = self.record.get("dispatch_job") if self.record["state"] != "idle" else self.record.get("owned_runtime")
        if job is not None:
            from .windows_job import inspect_job
            if not isinstance(job, dict) or not job.get("kill_on_close") or job.get("breakaway") is not False:
                raise RuntimeCoordinationError("The saved containment observation is incomplete; preserve it for recovery.")
            observed = inspect_job(job.get("job_name"))
            if observed["active_processes"]:
                if self.record["state"] != "idle":
                    raise RuntimeCoordinationError("Owned runtime workers are still alive. Use Stop local model, then Recheck runtime.")
            else:
                observation = {"state": "idle", "method": "owned_job_ended", "job": observed,
                               "prior_request_id": self.record.get("request_id"), "observed_at": time.time(),
                               "reason": "The recorded Windows job has no remaining workers. Start the owned runtime again before sending a request.",
                               "scope": "Job members only; brokered or remote work is outside this lifetime control."}
                self.record.update(state="idle", reason="owned_job_ended", last_reconciliation=observation)
                self.record.pop("owned_runtime", None)
                self.record.pop("dispatch_job", None)
                self._write()
                return observation
        if self.record["state"] == "idle":
            return {"state": "idle", "reason": "No unresolved CETA dispatch is recorded; model readiness remains separate."}
        original = self.record.get("owner")
        if not isinstance(original, dict) or type(original.get("pid")) is not int or type(original.get("created_100ns")) is not int:
            raise RuntimeCoordinationError("The interrupted service had no observable process identity. This uncertainty cannot be cleared by acknowledgment; use a separately owned runtime endpoint.")
        current = process_identity(original["pid"])
        if current == original:
            raise RuntimeCoordinationError("The original service process is still alive. Stop/restart that service before rechecking; an idle model list is insufficient.")
        replacement = endpoint_owner(self.host, self.port)
        observation = {"state": "uncertain", "method": "original_service_process_ended",
                       "prior_request_id": self.record.get("request_id"), "original_owner": original,
                       "current_owner": replacement, "observed_at": time.time(),
                       "reason": "The original service process ended, but separate model workers may survive. Worker termination is unverified; use a separately owned runtime endpoint."}
        # Ollama and generic services can run inference in child or remote
        # workers. A listener PID disappearing is not proof those workers stopped.
        self.record.update(last_reconciliation=observation, reason="service_ended_worker_termination_unverified")
        self._write()
        return observation

    def _release(self):
        if self.descriptor is not None:
            os.close(self.descriptor)  # OS releases the lock, including after process death.
            self.descriptor = None

    def __exit__(self, exc_type, exc, traceback):
        try:
            if self.dispatched:
                self.record.update(state="idle" if self.terminal else "uncertain", ended_at=time.time(),
                                   reason="terminal_response_observed" if self.terminal else "dispatch_without_terminal_observation")
                self._write()
        finally:
            self._release()
