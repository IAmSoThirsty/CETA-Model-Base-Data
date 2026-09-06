"""Explicit Windows update handoff after the application has closed."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path
import stat
import subprocess

from .updates import UpdateError, validate_manifest


@contextmanager
def locked_installer(path: Path):
    """Keep Windows write/delete sharing disabled through process creation."""
    if os.name != "nt":
        raise UpdateError("Installing application updates is supported on Windows.")
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    # The descriptor owns the Windows handle from this point onward.
    with os.fdopen(descriptor, "rb") as stream:
        yield stream


@contextmanager
def system_dll_search():
    """Launch the external installer without inheriting frozen Qt DLL paths."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    kernel.GetDllDirectoryW.restype = ctypes.c_uint32
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.restype = ctypes.c_int
    required = kernel.GetDllDirectoryW(0, None)
    buffer = ctypes.create_unicode_buffer(required + 1)
    kernel.GetDllDirectoryW(len(buffer), buffer)
    if not kernel.SetDllDirectoryW(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.SetDllDirectoryW(buffer.value or None)


def launch_verified_update(installer: Path, manifest: dict) -> int:
    """
    Recheck signed metadata's bytes, then launch without a command shell.

    The caller supplies metadata already authenticated by verify_manifest and
    must release the application's data lock and running marker first. The
    installer waits for this process to exit before replacing application files.
    """
    manifest = validate_manifest(manifest)
    installer = installer.resolve(strict=True)
    if installer.name != f"CETA-{manifest['version']}-setup.exe":
        raise UpdateError("The installer name does not match the verified update.")
    with locked_installer(installer) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != manifest["size"]:
            raise UpdateError("The saved installer has changed. Download the update again.")
        if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["sha256"]:
            raise UpdateError(
                "The saved installer failed its signed checksum. Download the update again."
            )
        with system_dll_search():
            # Do not wait or use Popen as a context manager: this process must
            # exit before the child installer is allowed to replace its files.
            process = subprocess.Popen(
                [str(installer), f"/WAITPID={os.getpid()}"],
                cwd=installer.parent, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS, close_fds=True,
            )
        return process.pid
