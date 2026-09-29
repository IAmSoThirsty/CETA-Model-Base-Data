"""Windows runtime lifetime control, not a sandbox for untrusted executables.

The child is assigned while suspended. Ordinary descendants inherit the job;
neither breakaway flag is enabled. Brokered/remote work is outside this scope.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
from uuid import uuid4

KILL_ON_CLOSE = 0x2000
BREAKAWAY = 0x800 | 0x1000
NAME = re.compile(r"Local\\CETA-runtime-[0-9a-f]{32}\Z")


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", ctypes.c_uint32), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_limit", ctypes.c_uint32),
                ("affinity", ctypes.c_size_t), ("priority", ctypes.c_uint32),
                ("scheduling", ctypes.c_uint32)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class Accounting(ctypes.Structure):
    _fields_ = [("user_time", ctypes.c_int64), ("kernel_time", ctypes.c_int64),
                ("period_user", ctypes.c_int64), ("period_kernel", ctypes.c_int64),
                ("page_faults", ctypes.c_uint32), ("total", ctypes.c_uint32),
                ("active", ctypes.c_uint32), ("terminated", ctypes.c_uint32)]


def _kernel():
    if os.name != "nt":
        raise OSError("Owned runtime containment is available only on Windows.")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, ctypes.c_wchar_p], ctypes.c_void_p),
        "OpenJobObjectW": ([ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p], ctypes.c_void_p),
        "CloseHandle": ([ctypes.c_void_p], ctypes.c_int),
        "SetInformationJobObject": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
        "QueryInformationJobObject": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p], ctypes.c_int),
        "AssignProcessToJobObject": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
        "TerminateJobObject": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
        "ResumeThread": ([ctypes.c_void_p], ctypes.c_uint32),
        "OpenProcess": ([ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32], ctypes.c_void_p),
        "IsProcessInJob": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)], ctypes.c_int),
        "QueryFullProcessImageNameW": ([ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def _check(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def _snapshot(api, handle):
    limits, accounting = ExtendedLimits(), Accounting()
    _check(api.QueryInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None))
    flags = limits.basic.flags
    if not flags & KILL_ON_CLOSE or flags & BREAKAWAY:
        raise ValueError("Owned runtime job no longer enforces its lifetime limits.")
    _check(api.QueryInformationJobObject(handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None))
    return {"active_processes": accounting.active, "total_processes": accounting.total,
            "kill_on_close": True, "breakaway": False}


def inspect_job(name, owner=None):
    """Observe an existing job and optionally the exact endpoint process in it.

    Only ERROR_FILE_NOT_FOUND means absent. Access denial/invalid limits remain
    unknown, never evidence of completed shutdown. This never creates a job.
    """
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("Invalid owned runtime job identity.")
    api = _kernel()
    handle = api.OpenJobObjectW(4, False, name)  # JOB_OBJECT_QUERY
    if not handle:
        error = ctypes.get_last_error()
        if error == 2:
            return {"job_name": name, "state": "absent", "active_processes": 0}
        raise ctypes.WinError(error)
    try:
        result = {"job_name": name, "state": "present", **_snapshot(api, handle)}
        if owner is not None:
            from .runtime_coordination import process_identity
            if not isinstance(owner, dict) or process_identity(owner.get("pid")) != owner:
                raise ValueError("The runtime endpoint process changed during containment inspection.")
            process = _check(api.OpenProcess(0x1000, False, owner["pid"]))
            try:
                contained = ctypes.c_int()
                _check(api.IsProcessInJob(process, handle, ctypes.byref(contained)))
                if process_identity(owner["pid"]) != owner:
                    raise ValueError("The runtime endpoint exited during containment inspection.")
                result["owner_contained"] = bool(contained.value)
            finally:
                api.CloseHandle(process)
        return result
    finally:
        api.CloseHandle(handle)


def process_image(owner):
    """Inspect the image of an exact live process identity, rejecting PID reuse."""
    from .runtime_coordination import process_identity
    if not isinstance(owner, dict) or process_identity(owner.get("pid")) != owner:
        raise ValueError("The process identity changed before image inspection.")
    api = _kernel()
    process = _check(api.OpenProcess(0x1000, False, owner["pid"]))
    try:
        size = ctypes.c_uint32(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        _check(api.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)))
        if process_identity(owner["pid"]) != owner:
            raise ValueError("The process identity changed during image inspection.")
        return buffer.value
    finally:
        api.CloseHandle(process)


class WindowsJobProcess:
    """A single root and its Windows job, with bounded nonblocking output reads."""
    def __init__(self):
        self.api = _kernel()
        self.name = "Local\\CETA-runtime-" + uuid4().hex
        self.job = self.process = self.output = None
        self.pid = 0
        self.killed = False
        self.last_observation = None
        ctypes.set_last_error(0)
        self.job = _check(self.api.CreateJobObjectW(None, self.name))
        try:
            if ctypes.get_last_error() == 183:
                raise OSError("The randomly named runtime job already exists.")
            limits = ExtendedLimits()
            limits.basic.flags = KILL_ON_CLOSE
            _check(self.api.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            _snapshot(self.api, self.job)
        except BaseException:
            self.close()
            raise

    def start(self, program, arguments, environment, before_resume):
        # CPython's Windows primitive supplies STARTUPINFOEX's explicit handle
        # list. Unlike QProcess's Python binding, it retains the primary thread
        # handle until assignment and durable registration have succeeded.
        import _winapi
        import msvcrt
        if self.process is not None or self.job is None:
            raise ValueError("This owned process cannot be started again.")
        thread = write_handle = None
        try:
            self.output, write_handle = _winapi.CreatePipe(None, 0)
            os.set_handle_inheritable(write_handle, True)
            with open(os.devnull, "rb") as input_file:
                input_handle = msvcrt.get_osfhandle(input_file.fileno())
                os.set_handle_inheritable(input_handle, True)
                startup = subprocess.STARTUPINFO()
                startup.dwFlags = subprocess.STARTF_USESTDHANDLES | subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = subprocess.SW_HIDE
                startup.hStdInput = input_handle
                startup.hStdOutput = startup.hStdError = write_handle
                startup.lpAttributeList = {"handle_list": [input_handle, write_handle]}
                self.process, thread, self.pid, _tid = _winapi.CreateProcess(
                    program, subprocess.list2cmdline([program, *arguments]), None, None, True,
                    0x4 | 0x80000 | subprocess.CREATE_NO_WINDOW, environment, None, startup)
            _check(self.api.AssignProcessToJobObject(self.job, self.process))
            before_resume(self)
            if self.api.ResumeThread(thread) != 1:
                raise OSError("The contained runtime primary thread could not be resumed exactly once.")
        except BaseException:
            if self.process is not None:
                # Assignment may have failed, so terminate the suspended root
                # explicitly as well as closing the job. Never resume on failure.
                _winapi.TerminateProcess(self.process, 1)
                _winapi.WaitForSingleObject(self.process, 3000)
            self.close()
            raise
        finally:
            for handle in (thread, write_handle):
                if handle is not None:
                    _winapi.CloseHandle(handle)

    def read(self):
        import _winapi
        if self.output is None:
            return b""
        try:
            available, _left = _winapi.PeekNamedPipe(self.output, 0)
            return _winapi.ReadFile(self.output, min(available, 65536))[0] if available else b""
        except OSError as exc:
            if exc.winerror == 109:  # All writers closed their pipe handles.
                return b""
            raise

    def stop(self):
        if self.job is not None:
            _check(self.api.TerminateJobObject(self.job, 1))
            self.killed = True

    def poll(self):
        import _winapi
        if self.process is None:
            return None
        state = _winapi.WaitForSingleObject(self.process, 0)
        if state == 258:
            return None
        if state != 0:
            raise OSError("The owned runtime process state could not be observed.")
        observation = _snapshot(self.api, self.job)
        # A root can exit while inference children remain. Keep ownership and
        # stop those children; emit completion only after accounting reaches zero.
        if observation["active_processes"]:
            self.stop()
            return None
        self.last_observation = {"job_name": self.name, **observation}
        return _winapi.GetExitCodeProcess(self.process)

    def close(self):
        for attribute in ("job", "process", "output"):
            handle = getattr(self, attribute, None)
            if handle is not None:
                self.api.CloseHandle(handle)
                setattr(self, attribute, None)

    def __del__(self):
        self.close()
