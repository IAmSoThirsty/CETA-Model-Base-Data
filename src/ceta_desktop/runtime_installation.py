"""Pinned, per-installation runtime acquisition. No executable is run here.

The bundled catalog is the trust anchor for both archive and extracted files.
Receipts and a previous successful install are never accepted as integrity proof.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4
import zipfile


class RuntimeInstallError(ValueError):
    pass


class RuntimeInstallCancelled(RuntimeInstallError):
    pass


def _check(cancelled, deadline):
    if cancelled is not None and cancelled.is_set():
        raise RuntimeInstallCancelled("Runtime setup paused. Verified files and partial downloads are preserved.")
    if time.monotonic() >= deadline:
        raise RuntimeInstallError("Runtime setup exceeded its deadline. Retry to resume the download.")


def _member_path(name):
    if not isinstance(name, str) or not name or len(name) > 240 or not name.isascii():
        raise RuntimeInstallError("Invalid runtime archive path.")
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if any(not p or p in {".", ".."} or p.endswith((".", " ")) or
           re.search(r'[<>:"\\|?*\x00-\x1f\x7f]', p) or p.split(".")[0].upper() in reserved for p in parts):
        raise RuntimeInstallError("Unsafe runtime archive path.")
    return PurePosixPath(name)


def _plain(path, *, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise RuntimeInstallError("Runtime assets must be ordinary files and directories, without links or reparse points.")
    return info


def _directory(path):
    path.mkdir(exist_ok=True)
    _plain(path, directory=True)
    return path


@contextmanager
def asset_lock(root):
    """OS-released lock for cooperating acquisitions in one private asset store."""
    _plain(root, directory=True)
    path = root / ".acquisition.lock"
    if path.exists():
        _plain(path)
    stream = path.open("a+b")
    try:
        if stream.tell() == 0:
            stream.write(b"\0"); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeInstallError("Another CETA process is acquiring or checking these assets.") from None
        yield
    finally:
        stream.close()


def _digest(stream, cancelled=None, deadline=float("inf"), *, limit=None):
    digest, count = hashlib.sha256(), 0
    while True:
        _check(cancelled, deadline)
        block = stream.read(1024 * 1024)
        if not block:
            break
        count += len(block)
        if limit is not None and count > limit:
            raise RuntimeInstallError("Runtime file exceeds its pinned size.")
        digest.update(block)
    return digest.hexdigest(), count


def validate_runtime_spec(spec):
    """Validate bundled data before it can name a URL, local path or executable."""
    if not isinstance(spec, dict) or spec.get("schema") != "ceta.managed-runtime.v1":
        raise RuntimeInstallError("Unsupported managed runtime catalog.")
    if spec.get("backend") != "ollama" or spec.get("platform") != "windows-x64":
        raise RuntimeInstallError("Unsupported managed runtime platform.")
    version = spec.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise RuntimeInstallError("Invalid pinned runtime version.")
    archive = spec.get("archive", {})
    expected_url = f"https://github.com/ollama/ollama/releases/download/v{version}/ollama-windows-amd64.zip"
    if archive.get("url") != expected_url:
        raise RuntimeInstallError("Managed runtimes must use the pinned official release URL.")
    entries = spec.get("files")
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 4096:
        raise RuntimeInstallError("The runtime catalog must pin all extracted files.")
    folded = set()
    for name, record in [("archive", archive), *entries.items()]:
        if not isinstance(record, dict) or type(record.get("size")) is not int or not 0 < record["size"] <= 8 * 1024**3:
            raise RuntimeInstallError("Invalid pinned runtime size.")
        if not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise RuntimeInstallError("Invalid pinned runtime checksum.")
        if name != "archive":
            _member_path(name)
            if name.casefold() in folded:
                raise RuntimeInstallError("Colliding runtime archive paths.")
            folded.add(name.casefold())
    for name in entries:
        if any(str(parent).casefold() in folded for parent in PurePosixPath(name).parents if str(parent) != "."):
            raise RuntimeInstallError("Runtime file and directory names collide.")
    if spec.get("entrypoint") != "ollama.exe" or "ollama.exe" not in entries:
        raise RuntimeInstallError("The pinned Ollama executable is missing.")
    if sum(record["size"] for record in entries.values()) > 12 * 1024**3:
        raise RuntimeInstallError("Runtime extraction exceeds the supported size.")
    if not isinstance(spec.get("license"), dict) or not spec["license"].get("notice"):
        raise RuntimeInstallError("Runtime license information is missing.")
    return spec


def bundled_runtime():
    return validate_runtime_spec(json.loads(files("ceta_desktop").joinpath("runtime_catalog.json").read_text(encoding="utf-8")))


def require_supported_platform():
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeInstallError("The managed runtime currently supports Windows x64. Use an existing local runtime on other platforms.")


def managed_environment(data_directory, executable, inherited):
    """Build a child-only environment with a private model store and profile."""
    state = _directory(Path(data_directory).resolve() / "managed-runtime-state")
    profile = _directory(state / "profile")
    models = _directory(state / "models")
    local = _directory(state / "local")
    roaming = _directory(state / "roaming")
    temporary = _directory(state / "temporary")
    allowed = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "OS", "PATHEXT", "NUMBER_OF_PROCESSORS",
               "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION"}
    environment = {key: value for key, value in inherited.items() if key.upper() in allowed}
    system = Path(inherited.get("SystemRoot", inherited.get("SYSTEMROOT", r"C:\Windows")))
    environment.update({"USERPROFILE": str(profile), "HOME": str(profile), "LOCALAPPDATA": str(local),
                        "APPDATA": str(roaming), "TEMP": str(temporary), "TMP": str(temporary),
                        "OLLAMA_MODELS": str(models), "OLLAMA_NO_CLOUD": "1", "OLLAMA_NOPRUNE": "1",
                        "OLLAMA_HOST": "127.0.0.1:11435", "OLLAMA_CONTEXT_LENGTH": "4096",
                        "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1",
                        "PATH": os.pathsep.join((str(Path(executable).parent), str(system / "System32"), str(system)))})
    return environment


class _ReleaseRedirect(HTTPRedirectHandler):
    def __init__(self, original):
        super().__init__()
        self.original, self.used = original, False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (self.used or code != 302 or req.full_url != self.original or req.get_method() != "GET" or
                parsed.scheme != "https" or parsed.hostname != "release-assets.githubusercontent.com" or
                parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment or
                not newurl.isascii() or any(c.isspace() or ord(c) < 32 for c in newurl)):
            raise RuntimeInstallError("The runtime download left the approved official release hosts.")
        self.used = True
        # Preserve only our byte range, never cookies, credentials or proxy headers.
        headers = {"User-Agent": "CETA-runtime-setup", "Accept-Encoding": "identity"}
        if req.get_header("Range"):
            headers["Range"] = req.get_header("Range")
        return Request(newurl, headers=headers)

    def http_error_302(self, req, fp, code, msg, headers):
        try:
            locations = headers.get_all("Location", [])
            if len(locations) != 1:
                raise RuntimeInstallError("The runtime download has an ambiguous redirect.")
            target = self.redirect_request(req, fp, code, msg, headers, locations[0])
        finally:
            fp.close()
        return self.parent.open(target, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _open_release(url, offset):
    headers = {"User-Agent": "CETA-runtime-setup", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    # No ambient proxy credentials, cookies or arbitrary redirect destinations.
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), _ReleaseRedirect(url))
    return opener.open(Request(url, headers=headers), timeout=5)


class RuntimeInstallation:
    def __init__(self, data_directory: Path, spec=None):
        self.spec = validate_runtime_spec(spec if spec is not None else bundled_runtime())
        base = Path(data_directory).resolve()
        base.mkdir(parents=True, exist_ok=True)
        self.root = _directory(base / "managed-runtimes")
        self.downloads = _directory(self.root / "downloads")
        self.identifier = f"ollama-{self.spec['version']}-{self.spec['archive']['sha256'][:16]}"
        self.destination = self.root / self.identifier

    @contextmanager
    def _lease(self):
        _plain(self.root, directory=True)
        _plain(self.downloads, directory=True)
        with asset_lock(self.root):
            yield

    def _verify_tree(self, cancelled, deadline, progress):
        _plain(self.destination, directory=True)
        found = set()
        for parent, folders, filenames in os.walk(self.destination, followlinks=False):
            for folder in folders:
                _plain(Path(parent) / folder, directory=True)
            for filename in filenames:
                path = Path(parent) / filename
                relative = path.relative_to(self.destination).as_posix()
                expected = self.spec["files"].get(relative)
                if expected is None:
                    raise RuntimeInstallError(f"Unexpected runtime file: {relative}. Existing files were preserved.")
                if _plain(path).st_size != expected["size"]:
                    raise RuntimeInstallError(f"Runtime size mismatch: {relative}. Restore the pinned archive.")
                progress(f"Verifying {relative}")
                with path.open("rb") as stream:
                    digest, _ = _digest(stream, cancelled, deadline, limit=expected["size"])
                if digest != expected["sha256"]:
                    raise RuntimeInstallError(f"Runtime checksum mismatch: {relative}. Existing files were preserved.")
                found.add(relative)
        if found != set(self.spec["files"]):
            raise RuntimeInstallError("The managed runtime is incomplete. Existing files were preserved.")
        _check(cancelled, deadline)
        return {"schema": "ceta.runtime-installation.v1", "backend": "ollama", "version": self.spec["version"],
                "archive_sha256": self.spec["archive"]["sha256"], "files_verified": len(found),
                "executable": str(self.destination / self.spec["entrypoint"]), "verified_at": time.time(),
                "inference": "not_tested", "scope": "Pinned runtime bytes; device support and inference require separate checks."}

    def verify(self, *, cancelled=None, progress=lambda _: None):
        with self._lease():
            if not self.destination.exists():
                raise RuntimeInstallError("Install or import the pinned runtime archive before starting it.")
            return self._verify_tree(cancelled, time.monotonic() + 600, progress)

    def _archive_matches(self, path, cancelled, deadline):
        expected = self.spec["archive"]
        if _plain(path).st_size != expected["size"]:
            raise RuntimeInstallError("The archive size does not match the pinned runtime release.")
        with path.open("rb") as stream:
            digest, _ = _digest(stream, cancelled, deadline, limit=expected["size"])
        if digest != expected["sha256"]:
            raise RuntimeInstallError("The archive checksum does not match the pinned runtime release. The file was preserved.")

    def _extract(self, archive_path, cancelled, deadline, progress):
        if self.destination.exists():
            return self._verify_tree(cancelled, deadline, progress)
        staging = self.root / (".staging-" + uuid4().hex)
        staging.mkdir()
        # Staging remains on failure for diagnosis; no unknown files are deleted.
        with zipfile.ZipFile(archive_path) as archive:
            members, seen = [], set()
            for member in archive.infolist():
                name = member.filename.rstrip("/") if member.is_dir() else member.filename
                _member_path(name)
                mode = member.external_attr >> 16
                if member.flag_bits & 1 or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise RuntimeInstallError("The runtime archive contains an unsupported member.")
                if name.casefold() in seen:
                    raise RuntimeInstallError("The runtime archive contains duplicate paths.")
                seen.add(name.casefold())
                if member.is_dir():
                    continue
                expected = self.spec["files"].get(name)
                if expected is None or member.file_size != expected["size"]:
                    raise RuntimeInstallError("Runtime archive members do not match the bundled catalog.")
                members.append(member)
            if {m.filename for m in members} != set(self.spec["files"]):
                raise RuntimeInstallError("The runtime archive is missing pinned files.")
            for member in members:
                _check(cancelled, deadline)
                progress(f"Installing {member.filename}")
                destination = staging.joinpath(*PurePosixPath(member.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest, count = hashlib.sha256(), 0
                with archive.open(member) as reader, destination.open("xb") as writer:
                    while True:
                        _check(cancelled, deadline)
                        block = reader.read(1024 * 1024)
                        if not block:
                            break
                        count += len(block)
                        if count > member.file_size:
                            raise RuntimeInstallError("An extracted runtime file exceeded its pinned size.")
                        digest.update(block); writer.write(block)
                    writer.flush(); os.fsync(writer.fileno())
                expected = self.spec["files"][member.filename]
                if count != expected["size"] or digest.hexdigest() != expected["sha256"]:
                    raise RuntimeInstallError("An extracted runtime file failed its pinned checksum.")
        _check(cancelled, deadline)
        staging.rename(self.destination)
        return self._verify_tree(cancelled, deadline, progress)

    def acquire(self, *, source=None, cancelled=None, progress=lambda _: None):
        """Download/resume or import a pinned archive, then verify and publish it.

        Local import never requests the network. Acquisition never starts a runtime.
        """
        require_supported_platform()
        deadline = time.monotonic() + 4 * 60 * 60
        with self._lease():
            _check(cancelled, deadline)
            if self.destination.exists():
                return self._verify_tree(cancelled, deadline, progress)
            required = sum(row["size"] for row in self.spec["files"].values()) + 256 * 1024**2
            expected = self.spec["archive"]
            target = self.downloads / (expected["sha256"] + ".part")
            if target.exists():
                _plain(target)
            offset = target.stat().st_size if target.exists() else 0
            if offset > expected["size"]:
                raise RuntimeInstallError("The partial runtime download exceeds the pinned size. It was preserved for inspection.")
            archive_space = expected["size"] if source is not None else max(0, expected["size"] - offset)
            if shutil.disk_usage(self.root).free < required + archive_space:
                raise RuntimeInstallError("There is not enough free disk space for the archive and extracted runtime.")
            if source is not None:
                source = Path(source)
                progress("Checking the selected offline archive")
                self._archive_matches(source, cancelled, deadline)
                # Copy into CETA's staging so later source edits cannot alter extraction.
                target = self.downloads / (expected["sha256"] + ".import-" + uuid4().hex)
                with source.open("rb") as reader, target.open("xb") as writer:
                    count = 0
                    while True:
                        _check(cancelled, deadline)
                        block = reader.read(1024 * 1024)
                        if not block:
                            break
                        count += len(block)
                        if count > expected["size"]:
                            raise RuntimeInstallError("The imported archive changed while copying.")
                        writer.write(block)
                    writer.flush(); os.fsync(writer.fileno())
            elif offset < expected["size"]:
                self._download(target, offset, cancelled, deadline, progress)
            progress("Verifying the complete runtime archive")
            self._archive_matches(target, cancelled, deadline)
            return self._extract(target, cancelled, deadline, progress)

    def _download(self, target, offset, cancelled, deadline, progress):
        expected = self.spec["archive"]
        response = None
        try:
            response = _open_release(expected["url"], offset)
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise RuntimeInstallError("The runtime download has unexpected content encoding.")
            if response.status == 206:
                expected_range = f"bytes {offset}-{expected['size'] - 1}/{expected['size']}"
                if response.headers.get("Content-Range") != expected_range:
                    raise RuntimeInstallError("The resumed download range does not match the pinned archive.")
            elif response.status == 200 and offset == 0:
                pass
            else:
                raise RuntimeInstallError("The server did not honor the download resume range. The partial file was preserved.")
            length = response.headers.get("Content-Length")
            if length is not None and length != str(expected["size"] - offset):
                raise RuntimeInstallError("The runtime download length differs from the pinned release.")
            with target.open("ab" if target.exists() else "xb") as writer:
                count, last = offset, 0.0
                while count < expected["size"]:
                    _check(cancelled, deadline)
                    block = response.read(min(256 * 1024, expected["size"] - count))
                    if not block:
                        raise RuntimeInstallError("Runtime download interrupted. Retry to resume the preserved partial file.")
                    writer.write(block); count += len(block)
                    if time.monotonic() - last >= .2:
                        progress(f"Downloading runtime: {count / 1024**2:.1f} / {expected['size'] / 1024**2:.1f} MiB")
                        last = time.monotonic()
                _check(cancelled, deadline)
                if response.read(1):
                    raise RuntimeInstallError("The download exceeded the pinned archive size.")
                writer.flush(); os.fsync(writer.fileno())
        except (HTTPError, URLError, OSError):
            # Redirect URLs can contain credentials; never expose their exception text.
            raise RuntimeInstallError("Runtime download interrupted or unavailable. Retry to resume; the partial file is preserved.") from None
        finally:
            if response is not None:
                response.close()
