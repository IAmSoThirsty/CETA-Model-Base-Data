"""Project-scoped adapters; the runtime owns authority. No OS sandbox is implied."""
from __future__ import annotations

import codecs
import ctypes
import difflib
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from ceta_desktop.workspace import MAX_EDITOR_BYTES, Workspace, WorkspaceError

MAX_SCAN_ENTRIES = 10_000
MAX_CONTEXT_CHARS = 64_000
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 1024 * 1024
_SCAN_SKIP = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__",
                        ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
                        ".cache", "build", "dist", "target"})
_SECRET_NAMES = frozenset({".env", ".ssh", ".aws", ".azure", ".gnupg", "credentials",
                           "credentials.json", "secrets.json", "id_rsa", "id_ed25519"})


class ProjectToolError(ValueError):
    """A project boundary or adapter input could not be validated."""


class ContextStaleError(ProjectToolError):
    """Evidence bound to a compiled context is no longer current."""


class ContextBudgetError(ProjectToolError):
    """Mandatory context cannot fit without losing instructions."""


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_hash(value: Any) -> str:
    return _hash(json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=True).encode("utf-8"))


def _alias(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _root(root: Path | str) -> Path:
    source = Path(os.path.abspath(root))
    if any(_sensitive(part) for part in source.parts):
        raise ProjectToolError("Git internals and sensitive directories cannot be selected as project roots.")
    for current in (source, *source.parents):
        if _alias(current):
            raise ProjectToolError("Project roots must not traverse a symlink or reparse point.")
    resolved = source.resolve(strict=True)
    if not resolved.is_dir():
        raise ProjectToolError("Select an existing project directory.")
    return resolved


def _runtime_artifact(part: str) -> bool:
    name = part.casefold()
    return (name in {"desktop.sqlite3", "desktop.sqlite3-wal", "desktop.sqlite3-shm",
                     "runtime-identity.json", "runtime-identity.json.lock"}
            or name.startswith("desktop.sqlite3.schema-") or name.startswith(".ceta-"))


def _sensitive(part: str) -> bool:
    name = part.casefold()
    return (name == ".git" or name in _SECRET_NAMES or name.startswith(".env.") or _runtime_artifact(name)
            or name.endswith((".pem", ".pfx", ".p12", ".key")))


def _checked(root: Path, path: Path | str, *, allow_new: bool = False) -> Path:
    supplied = Path(path)
    candidate = supplied if supplied.is_absolute() else root / supplied
    candidate = Path(os.path.abspath(candidate))
    if not candidate.is_relative_to(root) or candidate == root:
        raise ProjectToolError("The target must be a file inside the selected project.")
    relative = candidate.relative_to(root)
    if any(_sensitive(part) or ":" in part or (os.name == "nt" and part.endswith((".", " ")))
           for part in relative.parts):
        raise ProjectToolError("Git internals and sensitive files are excluded from project tools.")
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        final = index == len(relative.parts) - 1
        if not current.exists() and not current.is_symlink():
            if final and allow_new:
                break
            raise ProjectToolError("The target or its parent does not exist.")
        if _alias(current):
            raise ProjectToolError("Symlinks and reparse points are excluded from project tools.")
        if not final and (not current.is_dir() or (current / ".git").exists()):
            raise ProjectToolError("The target crosses a nested project or non-directory boundary.")
    if candidate.exists():
        if os.path.normcase(str(candidate.resolve(strict=True))) != os.path.normcase(str(candidate)):
            raise ProjectToolError("Filesystem aliases are excluded from project tools.")
        info = candidate.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ProjectToolError("Select a regular project file.")
        if info.st_nlink > 1:
            raise ProjectToolError("Hard-linked files are excluded to preserve project boundaries.")
    return candidate


def read_file(root: Path | str, path: Path | str) -> dict[str, Any]:
    """Read bounded UTF-8 source; never silently truncate source evidence."""
    root = _root(root)
    target = _checked(root, path)
    if target.stat().st_size > MAX_EDITOR_BYTES:
        raise ProjectToolError("The file exceeds the 4 MiB source limit.")
    with target.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_nlink > 1 or not stat.S_ISREG(before.st_mode):
            raise ProjectToolError("Source must be a regular, unaliased project file.")
        raw = stream.read(MAX_EDITOR_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = _checked(root, path).stat()
    if (current.st_ino, current.st_dev, current.st_mtime_ns, current.st_size) != (
            after.st_ino, after.st_dev, after.st_mtime_ns, after.st_size):
        raise ProjectToolError("The file was replaced during inspection. Read it again.")
    if len(raw) > MAX_EDITOR_BYTES:
        raise ProjectToolError("The file exceeds the 4 MiB source limit.")
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ProjectToolError("The file changed during inspection. Read it again.")
    if b"\x00" in raw:
        raise ProjectToolError("Binary files are excluded from text inspection.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProjectToolError("Source inspection currently supports UTF-8 text.") from exc
    return {"path": target.relative_to(root).as_posix(), "absolute_path": str(target),
            "sha256": _hash(raw), "text": text, "size_bytes": len(raw),
            "encoding": "utf-8", "bom": raw.startswith(codecs.BOM_UTF8)}


def _inventory(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]], bool, int]:
    files: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    pending = [root]
    entries_seen = 0
    truncated = False
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = []
                for entry in iterator:
                    entries_seen += 1
                    if entries_seen > MAX_SCAN_ENTRIES:
                        truncated = True
                        break
                    entries.append(entry)
        except OSError as exc:
            raise ProjectToolError(f"Cannot inspect directory {directory.relative_to(root)}: {exc}") from exc
        for entry in sorted(entries, key=lambda item: item.name.casefold()):
            target = Path(entry.path)
            relative = target.relative_to(root).as_posix()
            reason = None
            if _runtime_artifact(entry.name):
                reason = "ceta_runtime_artifact"
            elif _sensitive(entry.name):
                reason = "sensitive_or_git_internal"
            elif entry.name.casefold() in _SCAN_SKIP:
                reason = "generated_or_dependency_directory"
            elif _alias(target):
                reason = "alias_or_reparse_point"
            elif entry.is_dir(follow_symlinks=False) and (target / ".git").exists():
                reason = "nested_project"
            if reason:
                if len(omitted) < 100:
                    omitted.append({"path": relative, "reason": reason})
                continue
            # Windows DirEntry.stat may report st_nlink=0; query the actual file.
            info = target.lstat()
            if stat.S_ISDIR(info.st_mode):
                pending.append(target)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                files.append({"path": relative, "size_bytes": info.st_size,
                              "mtime_ns": info.st_mtime_ns})
        if truncated:
            break
    return sorted(files, key=lambda item: item["path"]), omitted, truncated, entries_seen


class _GitInspectionLimit(ProjectToolError):
    def __init__(self, reason: str, *, truncated: bool = False):
        super().__init__(reason)
        self.truncated = truncated


def _capture_git(argv: list[str], root: Path, environment: dict[str, str], *,
                 timeout_seconds: float = 15, output_limit: int = MAX_GIT_OUTPUT_BYTES):
    """Capture both Git streams within one byte budget, terminating on overflow."""
    process = subprocess.Popen(argv, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    stopped = threading.Event()
    pending: queue.Queue[tuple[int, bytes | None]] = queue.Queue(maxsize=16)
    readers = []
    streams = [bytearray(), bytearray()]
    started = time.monotonic()

    def read_stream(index, stream):
        try:
            while not stopped.is_set():
                chunk = os.read(stream.fileno(), 4096)
                while not stopped.is_set():
                    try:
                        pending.put((index, chunk or None), timeout=0.05)
                        break
                    except queue.Full:
                        continue
                if not chunk:
                    return
        except (OSError, ValueError):
            while not stopped.is_set():
                try:
                    pending.put((index, None), timeout=0.05)
                    return
                except queue.Full:
                    continue

    try:
        for index, stream in enumerate((process.stdout, process.stderr)):
            reader = threading.Thread(target=read_stream, args=(index, stream), daemon=True,
                                      name=f"ceta-git-inspection-{process.pid}-{index}")
            readers.append(reader)
            reader.start()
        ended = set()
        while len(ended) != 2 or process.poll() is None:
            if time.monotonic() - started >= timeout_seconds:
                raise _GitInspectionLimit("Git inspection exceeded its time budget.")
            try:
                index, chunk = pending.get(timeout=0.05)
            except queue.Empty:
                continue
            if chunk is None:
                ended.add(index)
                continue
            if len(streams[0]) + len(streams[1]) + len(chunk) > output_limit:
                raise _GitInspectionLimit("Git output exceeded its byte budget; state is incomplete.", truncated=True)
            streams[index].extend(chunk)
        return subprocess.CompletedProcess(argv, process.wait(timeout=5),
                                           bytes(streams[0]).decode("utf-8", errors="replace"),
                                           bytes(streams[1]).decode("utf-8", errors="replace"))
    finally:
        stopped.set()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=2)
        process.stdout.close()
        process.stderr.close()


def _git(root: Path) -> dict[str, Any]:
    try:
        return _git_state(root)
    except _GitInspectionLimit as exc:
        return {"kind": "unknown", "available": True, "reason": str(exc),
                "truncated": exc.truncated, "incomplete": True}


def _git_state(root: Path) -> dict[str, Any]:
    executable = shutil.which("git")
    if not executable:
        return {"kind": "unknown" if (root / ".git").exists() else "non_git",
                "available": False, "reason": "git_executable_unavailable"}
    base = [executable, "-c", "core.fsmonitor=false", "-c", "core.hooksPath=",
            "-c", "core.untrackedCache=false", "-C", str(root)]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"

    def query(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            return _capture_git(base + list(args), root, environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProjectToolError(f"Git inspection failed: {exc}") from exc

    top = query("rev-parse", "--show-toplevel")
    if top.returncode:
        if (root / ".git").exists():
            return {"kind": "unknown", "available": True, "reason": top.stderr.strip()[:1000]}
        return {"kind": "non_git", "available": True}
    if Path(top.stdout.strip()).resolve() != root:
        return {"kind": "non_git", "available": True, "reason": "enclosing_repository_outside_selected_root"}
    head = query("rev-parse", "--verify", "HEAD")
    branch = query("symbolic-ref", "--quiet", "--short", "HEAD")
    status = query("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status.returncode:
        raise ProjectToolError(f"Git status failed: {status.stderr.strip()[:1000]}")
    filtered_status = []
    records = iter(status.stdout.split("\x00")[:-1])
    for record in records:
        paths = [record[3:]]
        if "R" in record[:2] or "C" in record[:2]:
            paths.append(next(records, ""))
        if not all(_runtime_artifact(Path(path).name) for path in paths):
            filtered_status.append(record)
            filtered_status.extend(paths[1:])
    return {"kind": "git", "available": True, "branch": branch.stdout.strip() or None,
            "head": head.stdout.strip() if head.returncode == 0 else None,
            "status": filtered_status, "dirty": bool(filtered_status)}


def inspect_project(root: Path | str) -> dict[str, Any]:
    root = _root(root)
    files, omitted, truncated, _count = _inventory(root)
    instructions = []
    for entry in files:
        if Path(entry["path"]).name.casefold() == "agents.md":
            document = read_file(root, entry["path"])
            instructions.append({"path": document["path"], "sha256": document["sha256"]})
    identity = os.path.normcase(str(root))
    return {"schema": "ceta.project-snapshot.v1", "root": str(root),
            "project_id": "project-" + _hash(identity.encode("utf-8")),
            "git": _git(root), "instructions": instructions,
            "inventory_sha256": _json_hash(files), "file_count": len(files),
            "scan_entries": len(files), "scan_truncated": truncated,
            "omitted": [item for item in omitted if item["reason"] != "ceta_runtime_artifact"],
            "excluded_runtime_artifacts": "desktop SQLite journal, identity and CETA temporary files"}


def search_code(root: Path | str, query: str, max_results: int = 100) -> dict[str, Any]:
    """Literal case-sensitive search of bounded, non-secret UTF-8 source."""
    if not isinstance(query, str) or not query or len(query) > 4096:
        raise ProjectToolError("Search requires a nonempty literal query of at most 4096 characters.")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 1000:
        raise ProjectToolError("max_results must be between 1 and 1000.")
    root = _root(root)
    files, omitted, truncated, count = _inventory(root)
    matches = []
    searched = 0
    inspected_bytes = 0
    for entry in files:
        if inspected_bytes + entry["size_bytes"] > 32 * MAX_EDITOR_BYTES:
            truncated = True
            break
        try:
            document = read_file(root, entry["path"])
        except (ProjectToolError, OSError) as exc:
            if len(omitted) < 100:
                omitted.append({"path": entry["path"], "reason": str(exc)})
            continue
        inspected_bytes += document["size_bytes"]
        searched += 1
        for number, line in enumerate(document["text"].splitlines(), 1):
            offset = line.find(query)
            if offset >= 0:
                if len(matches) >= max_results:
                    truncated = True
                    break
                start = max(0, offset - 200)
                matches.append({"path": document["path"], "line": number, "column": offset + 1,
                                "text": line[start:start + 1000], "sha256": document["sha256"],
                                "line_truncated": len(line) > 1000})
        if len(matches) >= max_results:
            truncated = True
            break
    return {"query": query, "matches": matches, "truncated": truncated,
            "scope": {"root": str(root), "literal": True, "case_sensitive": True,
                      "files_searched": searched, "entries_seen": min(count, MAX_SCAN_ENTRIES),
                      "bytes_searched": inspected_bytes, "omitted": omitted}}


def _context_body(context: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key != "fingerprint"}


def compile_project_context(root: Path | str, objective: str, paths: Sequence[Path | str] = (),
                            *, max_context_chars: int = MAX_CONTEXT_CHARS) -> dict[str, Any]:
    if not isinstance(objective, str) or not objective.strip():
        raise ProjectToolError("A task objective is required.")
    if not isinstance(max_context_chars, int) or isinstance(max_context_chars, bool) or max_context_chars < 1:
        raise ContextBudgetError("The context character budget must be positive.")
    root = _root(root)
    snapshot = inspect_project(root)
    if snapshot["scan_truncated"]:
        raise ContextBudgetError("Instruction discovery exceeded the entry budget; select a narrower project root.")
    if snapshot["git"]["kind"] == "unknown":
        raise ProjectToolError("The project's Git state could not be established.")
    selected = sorted({_checked(root, path, allow_new=True).relative_to(root).as_posix() for path in paths})
    # Explicitly selected files may live below a directory omitted by the broad
    # inventory (for example build/). Always check their actual instruction chain.
    scopes = {Path("."), Path(".agents"), Path(".codex")}
    for path in selected:
        scopes.update(Path(path).parents)
    candidates = {scope / "AGENTS.md" for scope in scopes if (root / scope).is_dir()}
    for entry in snapshot["instructions"]:
        instruction = Path(entry["path"])
        if instruction.parent in scopes:
            candidates.add(instruction)
    instruction_candidates = sorted(path.as_posix() for path in candidates)
    applicable = [read_file(root, path) for path in instruction_candidates
                  if (root / path).exists() or (root / path).is_symlink()]
    context: dict[str, Any] = {"schema": "ceta.project-context.v1", "root": str(root),
                               "project_id": snapshot["project_id"], "objective": objective,
                               "project": snapshot, "instructions": applicable, "instruction_candidates": instruction_candidates,
                               "files": [], "new_paths": [],
                               "omitted": [], "budget": {"max_chars": max_context_chars}}
    def size() -> int:
        return len(json.dumps(context, ensure_ascii=True, sort_keys=True)) + 256
    if size() > max_context_chars:
        raise ContextBudgetError("Mandatory project identity, objective, and instructions exceed the context budget.")
    for path in selected:
        if not _checked(root, path, allow_new=True).exists():
            context["new_paths"].append(path)
            if size() > max_context_chars:
                raise ContextBudgetError("New-file precondition records exceed the context budget.")
            continue
        document = read_file(root, path)
        context["files"].append(document)
        if size() > max_context_chars:
            context["files"].pop()
            context["omitted"].append({"path": path, "sha256": document["sha256"],
                                       "reason": "optional_source_exceeds_context_budget"})
            if size() > max_context_chars:
                raise ContextBudgetError("Context omission records exceed the context budget.")
    context["budget"]["used_chars"] = size()
    context["fingerprint"] = _json_hash(_context_body(context))
    return context


def validate_project_context(context: Mapping[str, Any]) -> None:
    if context.get("schema") != "ceta.project-context.v1" or context.get("fingerprint") != _json_hash(_context_body(context)):
        raise ContextStaleError("Context receipt integrity failed.")
    try:
        current = inspect_project(context["root"])
        if current != context["project"] or current["project_id"] != context["project_id"]:
            raise ContextStaleError("Project state or applicable instruction revisions changed.")
        instruction_paths = {document["path"] for document in context["instructions"]}
        for path in context.get("instruction_candidates", []):
            target = _root(context["root"]) / path
            if (target.exists() or target.is_symlink()) != (path in instruction_paths):
                raise ContextStaleError(f"Applicable instruction existence changed: {path}")
        for path in context.get("new_paths", []):
            if _checked(_root(context["root"]), path, allow_new=True).exists():
                raise ContextStaleError(f"Proposed new path now exists: {path}")
        for document in [*context["instructions"], *context["files"], *context["omitted"]]:
            if read_file(context["root"], document["path"])["sha256"] != document["sha256"]:
                raise ContextStaleError(f"Context file changed: {document['path']}")
    except (OSError, KeyError, TypeError, ProjectToolError) as exc:
        if isinstance(exc, ContextStaleError):
            raise
        raise ContextStaleError(f"Context can no longer be validated: {exc}") from exc


def _encoded_edit(text: str, newline: str, bom: bool) -> bytes:
    if not isinstance(text, str):
        raise ProjectToolError("New file contents must be text.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw = normalized.replace("\n", newline).encode("utf-8")
    if bom:
        raw = codecs.BOM_UTF8 + raw
    if len(raw) > MAX_EDITOR_BYTES or b"\x00" in raw:
        raise ProjectToolError("Edits must be nonbinary UTF-8 text within the 4 MiB limit.")
    return raw


def propose_edit(root: Path | str, path: Path | str, new_text: str) -> dict[str, Any]:
    root = _root(root)
    target = _checked(root, path, allow_new=True)
    exists = target.exists()
    if exists:
        document = Workspace(root).open(target)
        old_text, old_hash, newline, bom = document.text, document.digest, document.newline, document.bom
    else:
        old_text, old_hash, newline, bom = "", None, "\n", False
    raw = _encoded_edit(new_text, newline, bom)
    normalized = new_text.replace("\r\n", "\n").replace("\r", "\n")
    relative = target.relative_to(root).as_posix()
    proposal = {"schema": "ceta.file-edit.v1", "root": str(root), "path": relative,
                "expected_exists": exists, "old_sha256": old_hash, "new_sha256": _hash(raw),
                "new_text": normalized, "newline": newline, "bom": bom,
                "diff": "".join(difflib.unified_diff(old_text.splitlines(keepends=True),
                                    normalized.splitlines(keepends=True),
                                    fromfile=relative if exists else "/dev/null", tofile=relative))}
    proposal["proposal_hash"] = _json_hash(proposal)
    return proposal


def apply_edit(root: Path | str, proposal: Mapping[str, Any]) -> dict[str, Any]:
    root = _root(root)
    body = {key: value for key, value in proposal.items() if key != "proposal_hash"}
    if (proposal.get("schema") != "ceta.file-edit.v1" or proposal.get("root") != str(root)
            or proposal.get("proposal_hash") != _json_hash(body)):
        raise ProjectToolError("Edit proposal integrity or project binding failed.")
    target = _checked(root, proposal["path"], allow_new=True)
    raw = _encoded_edit(proposal["new_text"], proposal["newline"], proposal["bom"])
    if _hash(raw) != proposal["new_sha256"]:
        raise ProjectToolError("The proposed bytes no longer match their digest.")
    if proposal["expected_exists"]:
        workspace = Workspace(root)
        document = workspace.open(target)
        if (document.digest != proposal["old_sha256"] or document.newline != proposal["newline"]
                or document.bom != proposal["bom"]):
            raise WorkspaceError("The file changed after the proposal. Reopen it before saving.")
        _checked(root, target)
        workspace.save(document, proposal["new_text"])
    else:
        if proposal["old_sha256"] is not None:
            raise ProjectToolError("A new-file proposal cannot include an existing-file precondition.")
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    result = read_file(root, target)
    if result["sha256"] != proposal["new_sha256"]:
        raise ProjectToolError("Observed file bytes differ after saving; reconciliation is required.")
    return {"path": result["path"], "sha256": result["sha256"], "size_bytes": result["size_bytes"],
            "created": not proposal["expected_exists"], "status": "completed"}


def _executable_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_spec(root: Path | str, command: str | Sequence[str]) -> dict[str, Any]:
    root = _root(root)
    if isinstance(command, str):
        if not command.strip() or "\x00" in command:
            raise ProjectToolError("A nonempty command without NUL characters is required.")
        if os.name == "nt":
            shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            argv = [str(shell), "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            argv = ["/bin/sh", "-c", command]
    else:
        argv = list(command)
        if not argv or any(not isinstance(part, str) or "\x00" in part for part in argv) or not argv[0]:
            raise ProjectToolError("The command must contain valid executable and argument strings.")
    if Path(argv[0]).is_absolute():
        executable = Path(argv[0]).resolve(strict=True)
    elif any(separator in argv[0] for separator in ("/", "\\")):
        executable = (root / argv[0]).resolve(strict=True)
    else:
        found = shutil.which(argv[0])
        if not found:
            raise ProjectToolError(f"Executable was not found: {argv[0]}")
        executable = Path(found).resolve(strict=True)
    if not executable.is_file():
        raise ProjectToolError("Command executable must be a regular file.")
    spec = {"schema": "ceta.command.v1", "executable": str(executable), "args": argv[1:],
            "cwd": str(root), "executable_sha256": _executable_hash(executable),
            "mode": "trusted_local"}
    spec["spec_hash"] = _json_hash(spec)
    return spec


class _WindowsJob:
    """Owned process tree cleanup; this is not resource or security isolation."""

    def __init__(self) -> None:
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel = kernel
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def attach_and_resume(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes
        # Assign the suspended process before its first instruction can spawn children.
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

        class ThreadEntry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                        ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenThread.restype = wintypes.HANDLE
        self.kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        self.kernel.ResumeThread.restype = wintypes.DWORD
        snapshot = self.kernel.CreateToolhelp32Snapshot(4, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = False
        try:
            entry = ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            available = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while available:
                if entry.th32OwnerProcessID == process.pid:
                    handle = self.kernel.OpenThread(2, False, entry.th32ThreadID)
                    if not handle:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self.kernel.ResumeThread(handle) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        resumed = True
                    finally:
                        self.kernel.CloseHandle(handle)
                available = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(snapshot)
        if not resumed:
            raise ProjectToolError("Could not resume the owned command process.")

    def stop(self) -> None:
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run_command(spec: Mapping[str, Any], cancelled: Callable[[], bool] | None = None,
                on_output: Callable[[str], None] | None = None, *, timeout_seconds: float = 300,
                max_output_bytes: int = MAX_OUTPUT_BYTES) -> dict[str, Any]:
    """Run an already-authorized, explicitly trusted-local command."""
    body = {key: value for key, value in spec.items() if key != "spec_hash"}
    if (spec.get("schema") != "ceta.command.v1" or spec.get("mode") != "trusted_local"
            or spec.get("spec_hash") != _json_hash(body)):
        raise ProjectToolError("Command specification integrity failed.")
    root = _root(spec["cwd"])
    if str(root) != spec["cwd"] or _executable_hash(Path(spec["executable"])) != spec["executable_sha256"]:
        raise ProjectToolError("Command working directory or executable changed after authorization.")
    if not 0 < timeout_seconds <= 86_400 or not 1 <= max_output_bytes <= 16 * MAX_OUTPUT_BYTES:
        raise ProjectToolError("Command timeout or output budget is invalid.")
    if cancelled is None:
        cancelled = lambda: False
    elif not callable(cancelled):
        cancelled = getattr(cancelled, "is_set", None)
        if not callable(cancelled):
            raise ProjectToolError("Cancellation must be a callable or an event with is_set().")
    on_output = on_output or (lambda _text: None)
    base_result = {"mode": "trusted_local", "spec_hash": spec["spec_hash"], "cwd": str(root)}
    if cancelled():
        return {**base_result, "status": "cancelled", "exit_code": None, "output": "",
                "output_truncated": False, "output_bytes": 0, "started": False}
    job = _WindowsJob() if os.name == "nt" else None
    process = None
    reader = None
    stop_reader = threading.Event()
    chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=256)
    output = bytearray()
    total_bytes = 0
    started = time.monotonic()
    status = None
    callback_error = None
    decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def stop_tree() -> None:
        if process is None:
            return
        if job is not None:
            job.stop()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    try:
        process = subprocess.Popen([spec["executable"], *spec["args"]], cwd=root,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, shell=False,
                                   creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 4)
                                   if os.name == "nt" else 0,
                                   start_new_session=os.name != "nt")
        if job is not None:
            job.attach_and_resume(process)

        def read_output() -> None:
            try:
                while not stop_reader.is_set():
                    data = os.read(process.stdout.fileno(), 4096)
                    while not stop_reader.is_set():
                        try:
                            chunks.put(data or None, timeout=0.05)
                            break
                        except queue.Full:
                            continue
                    if not data:
                        break
            except (OSError, ValueError):
                if not stop_reader.is_set():
                    try:
                        chunks.put(None, timeout=0.1)
                    except queue.Full:
                        pass

        reader = threading.Thread(target=read_output, name=f"ceta-command-{process.pid}", daemon=True)
        reader.start()
        eof = False
        cleaned_tree = False
        while not eof or process.poll() is None:
            if status is None:
                if cancelled():
                    status = "cancelled"
                    stop_tree()
                    cleaned_tree = True
                elif time.monotonic() - started >= timeout_seconds:
                    status = "timed_out"
                    stop_tree()
                    cleaned_tree = True
            if process.poll() is not None and not cleaned_tree:
                stop_tree()
                cleaned_tree = True
            try:
                chunk = chunks.get(timeout=0.05)
            except queue.Empty:
                if not reader.is_alive() and chunks.empty():
                    eof = True
                continue
            if chunk is None:
                eof = True
                continue
            total_bytes += len(chunk)
            retained = chunk[:max(0, max_output_bytes - len(output))]
            if retained:
                output.extend(retained)
                text = decoder.decode(retained)
                if text and callback_error is None:
                    try:
                        on_output(text)
                    except Exception as exc:
                        callback_error = f"{type(exc).__name__}: {exc}"
                        status = "failed"
                        stop_tree()
                        cleaned_tree = True
        final_text = decoder.decode(b"", final=True)
        if final_text and callback_error is None:
            on_output(final_text)
        exit_code = process.wait(timeout=5)
        status = status or ("completed" if exit_code == 0 else "failed")
        result = {**base_result, "status": status, "exit_code": exit_code,
                  "output": bytes(output).decode("utf-8", errors="replace"),
                  "output_truncated": total_bytes > len(output), "output_bytes": total_bytes,
                  "started": True, "pid": process.pid,
                  "elapsed_seconds": time.monotonic() - started}
        if callback_error:
            result["callback_error"] = callback_error
        return result
    finally:
        stop_reader.set()
        if process is not None:
            try:
                stop_tree()
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                if reader is not None:
                    reader.join(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()
        if job is not None:
            job.close()
