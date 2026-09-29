"""Windows write/delete protection for verified managed runtime/model files.

Handles are acquired before hashing and owned until confirmed worker shutdown.
This is a filesystem sharing boundary, not a sandbox or protection from an
administrator, kernel, or code injected into CETA. Unexpected runtime-directory
entries are detected at admission; directory handles do not prohibit new files.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import threading
from uuid import uuid4

from .runtime_installation import RuntimeInstallError, _plain


class FileInfo(ctypes.Structure):
    _fields_ = [("attributes", ctypes.c_uint32), ("times", ctypes.c_uint32 * 6),
                ("volume", ctypes.c_uint32), ("size_high", ctypes.c_uint32),
                ("size_low", ctypes.c_uint32), ("links", ctypes.c_uint32),
                ("index_high", ctypes.c_uint32), ("index_low", ctypes.c_uint32)]


class ProtectedPath:
    def __init__(self, path, *, directory=False):
        self.handle = None
        if os.name != "nt":
            raise RuntimeInstallError("Managed asset lifetime protection requires Windows.")
        self.path, self.directory = Path(path), directory
        _plain(self.path, directory=directory)
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": ([ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p], ctypes.c_void_p),
            "CloseHandle": ([ctypes.c_void_p], ctypes.c_int),
            "GetFileInformationByHandle": ([ctypes.c_void_p, ctypes.POINTER(FileInfo)], ctypes.c_int),
            "GetFinalPathNameByHandleW": ([ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_uint32),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        # Directories deny rename/delete but permit child creation. Files deny
        # write/delete sharing, including pre-existing incompatible writers.
        handle = self.api.CreateFileW(str(self.path), 0x80 if directory else 0x80000000,
            3 if directory else 1, None, 3, 0x00200000 | (0x02000000 if directory else 0x80), None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = handle
        try:
            self.identity = self.inspect()
        except BaseException:
            self.close()
            raise

    def inspect(self):
        if self.handle is None:
            raise RuntimeInstallError("Managed asset protection was released; restart the runtime.")
        info = FileInfo()
        if not self.api.GetFileInformationByHandle(self.handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if (info.attributes & 0x400 or bool(info.attributes & 0x10) != self.directory or
                (not self.directory and info.links != 1)):
            raise RuntimeInstallError("Managed assets cannot be reparse points or multiply linked files.")
        buffer = ctypes.create_unicode_buffer(32768)
        size = self.api.GetFinalPathNameByHandleW(self.handle, buffer, len(buffer), 0)
        if not size or size >= len(buffer):
            raise RuntimeInstallError("The protected asset's canonical path is unavailable.")
        name = buffer.value
        name = "\\\\" + name[8:] if name.startswith("\\\\?\\UNC\\") else name.removeprefix("\\\\?\\")
        if Path(name) != self.path:
            raise RuntimeInstallError("A managed asset path changed during protection.")
        identity = (info.volume, info.index_high, info.index_low)
        return identity if self.directory else (*identity, info.size_high, info.size_low)

    def check(self):
        if self.inspect() != self.identity:
            raise RuntimeInstallError("The protected asset identity changed; stop and recheck the runtime.")

    def close(self):
        if self.handle is not None:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()


class _Cancellation:
    def __init__(self, closing, supplied):
        self.closing, self.supplied = closing, supplied

    def is_set(self):
        return self.closing.is_set() or (self.supplied is not None and self.supplied.is_set())


class ManagedAssets:
    def __init__(self, installation):
        self.installation = installation
        self.directory = installation.root.parent
        self.session_id = uuid4().hex
        self._paths, self._models = {}, {}
        self._guard = threading.Lock()
        self._closing = threading.Event()
        self.runtime_result = None
        self.runtime_directories = None
        self.job_name = None

    @property
    def closed(self):
        return self._closing.is_set()

    @contextmanager
    def _operation(self):
        if not self._guard.acquire(blocking=False):
            raise RuntimeInstallError("Managed assets are being verified; wait for the active operation.")
        try:
            if self.closed:
                raise RuntimeInstallError("Managed asset protection ended; restart the runtime.")
            yield
        finally:
            if self.closed:
                self._release()
            self._guard.release()

    def _protect(self, paths, cancelled):
        added = []
        try:
            for path in paths:
                path = Path(path)
                if not path.is_relative_to(self.directory):
                    raise RuntimeInstallError("Managed assets must stay inside this CETA data directory.")
                # Construct ancestors without resolving a newly introduced link.
                # Hold the containing directories too: renaming a parent could
                # redirect the absolute paths subsequently opened by workers.
                ancestors = [parent for parent in reversed(self.directory.parents) if parent != parent.parent]
                directories = ancestors + [self.directory / relative for relative in reversed(path.parent.relative_to(self.directory).parents)] + [path.parent]
                for target, directory in [*((p, True) for p in directories), (path, False)]:
                    if cancelled.is_set():
                        raise RuntimeInstallError("Managed asset verification cancelled; no runtime was started.")
                    if target not in self._paths:
                        self._paths[target] = ProtectedPath(target, directory=directory)
                        added.append(target)
            return added
        except BaseException:
            self._rollback(added)
            raise

    def _rollback(self, added):
        for path in reversed(added):
            self._paths.pop(path).close()

    def _tree(self):
        root = self.installation.destination
        found, directories = set(), set()
        def inaccessible(error):
            raise error
        for parent, folders, names in os.walk(root, followlinks=False, onerror=inaccessible):
            _plain(Path(parent), directory=True)
            directories.add(Path(parent))
            for folder in folders:
                _plain(Path(parent) / folder, directory=True)
            for name in names:
                found.add((Path(parent) / name).relative_to(root).as_posix())
        if found != set(self.installation.spec["files"]):
            raise RuntimeInstallError("Managed runtime directory contents changed; stop and recheck the pinned installation.")
        if self.runtime_directories is not None and directories != self.runtime_directories:
            raise RuntimeInstallError("Managed runtime directories changed; stop and recheck the installation.")
        return directories

    def protect_runtime(self, *, cancelled=None, progress=lambda _: None):
        with self._operation():
            if self.runtime_result is not None:
                return self._assert_runtime()
            signal = _Cancellation(self._closing, cancelled)
            paths = [self.installation.destination / name for name in self.installation.spec["files"]]
            added = self._protect(paths, signal)
            try:
                result = self.installation.verify(cancelled=signal, progress=progress)
                self.runtime_directories = self._tree()
                for directory in self.runtime_directories:
                    if directory not in self._paths:
                        self._paths[directory] = ProtectedPath(directory, directory=True)
                        added.append(directory)
                self.runtime_result = {**result, "asset_protection": {"session_id": self.session_id,
                    "files": len(paths), "mode": "Windows write/delete sharing denied while owned workers run"}}
                return self._assert_runtime()
            except BaseException:
                self._rollback(added)
                self.runtime_result = self.runtime_directories = None
                raise

    def _assert_runtime(self, program=None):
        if self.runtime_result is None:
            raise RuntimeInstallError("Protect and verify the managed runtime before starting it.")
        if program is not None and Path(program) != Path(self.runtime_result["executable"]):
            raise RuntimeInstallError("The selected executable differs from the protected runtime.")
        for resource in self._paths.values():
            resource.check()
        self._tree()
        return dict(self.runtime_result)

    def assert_runtime(self, program=None):
        with self._operation():
            return self._assert_runtime(program)

    def bind_job(self, job_name):
        with self._operation():
            self._assert_runtime()
            if self.job_name is not None and self.job_name != job_name:
                raise RuntimeInstallError("Protected assets belong to a different runtime instance.")
            self.job_name = job_name

    def protect_model(self, models, identifier, *, cancelled=None, progress=lambda _: None):
        with self._operation():
            self._assert_runtime()
            if models.root.parent != self.directory:
                raise RuntimeInstallError("The managed model belongs to another data directory.")
            entry = models.entry(identifier)
            if identifier in self._models:
                result = self._models[identifier]
                if result["sha256"] != entry["sha256"]:
                    raise RuntimeInstallError("The model catalog changed; restart and reverify.")
                return dict(result)
            from .model_installation import model_layers
            paths = [models._manifest_path(entry), *[models.blobs / layer["digest"].replace(":", "-") for layer in model_layers(entry)]]
            signal = _Cancellation(self._closing, cancelled)
            added = self._protect(paths, signal)
            try:
                result = models.verify(identifier, cancelled=signal, progress=progress)
                self._assert_runtime()
                result = {**result, "asset_protection": {"session_id": self.session_id, "files": len(paths)}}
                self._models[identifier] = result
                return dict(result)
            except BaseException:
                self._rollback(added)
                raise

    def _release(self):
        for resource in reversed(list(self._paths.values())):
            resource.close()
        self._paths.clear()

    def close(self):
        # Never block the GUI on an in-flight hash. That operation observes this
        # cancellation and releases its handles in _operation's finally block.
        self._closing.set()
        if self._guard.acquire(blocking=False):
            try:
                self._release()
            finally:
                self._guard.release()

    def __del__(self):
        self.close()
