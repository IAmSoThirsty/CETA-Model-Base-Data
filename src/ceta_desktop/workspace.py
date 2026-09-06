from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ctypes
import os
from pathlib import Path
import tempfile

MAX_EDITOR_BYTES = 4 * 1024 * 1024


class WorkspaceError(ValueError):
    pass


@dataclass
class Document:
    path: Path
    text: str
    digest: str
    newline: str
    bom: bool


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceError("Select a workspace folder.")

    def checked_path(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self.root / path
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(self.root):
            raise WorkspaceError("The file is outside the selected workspace.")
        if any(part.casefold() == ".git" for part in resolved.relative_to(self.root).parts):
            raise WorkspaceError("Git internal files cannot be edited here.")
        if not resolved.is_file():
            raise WorkspaceError("Select a regular file.")
        return resolved

    def open(self, path: Path) -> Document:
        path = self.checked_path(path)
        if path.stat().st_size > MAX_EDITOR_BYTES:
            raise WorkspaceError("This file exceeds the editor's 4 MiB limit.")
        with path.open("rb") as handle:
            raw = handle.read(MAX_EDITOR_BYTES + 1)
        if len(raw) > MAX_EDITOR_BYTES:
            raise WorkspaceError("This file exceeds the editor's 4 MiB limit.")
        if b"\x00" in raw:
            raise WorkspaceError("Binary files cannot be edited as text.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise WorkspaceError("The editor currently supports UTF-8 text files.") from exc
        without_crlf = text.replace("\r\n", "")
        endings = [ending for ending, present in (("\r\n", "\r\n" in text),
                   ("\n", "\n" in without_crlf), ("\r", "\r" in without_crlf)) if present]
        if len(endings) > 1:
            raise WorkspaceError("This file has mixed line endings. Normalize them in another editor first.")
        newline = endings[0] if endings else "\n"
        return Document(path, text.replace("\r\n", "\n").replace("\r", "\n"), hashlib.sha256(raw).hexdigest(), newline,
                        raw.startswith(b"\xef\xbb\xbf"))

    def save(self, document: Document, text: str) -> None:
        path = self.checked_path(document.path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != document.digest:
            raise WorkspaceError("The file changed on disk. Reopen it before saving to preserve those changes.")
        data = text.replace("\n", document.newline).encode("utf-8")
        if document.bom:
            data = b"\xef\xbb\xbf" + data
        if len(data) > MAX_EDITOR_BYTES:
            raise WorkspaceError("The edited file exceeds the editor's 4 MiB limit. Split it before saving.")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ceta-save-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, path.stat().st_mode)
            # Check again after preparing the replacement.
            if hashlib.sha256(path.read_bytes()).hexdigest() != document.digest:
                raise WorkspaceError("The file changed during save; your edit has not replaced it.")
            if os.name == "nt":
                # ReplaceFile preserves the existing file's Windows ACL and metadata.
                replace = ctypes.windll.kernel32.ReplaceFileW
                replace.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                    ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
                replace.restype = ctypes.c_int
                if not replace(str(path), str(temporary), None, 0, None, None):
                    raise ctypes.WinError()
            else:
                os.replace(temporary, path)
            document.text = text
            document.digest = hashlib.sha256(data).hexdigest()
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
