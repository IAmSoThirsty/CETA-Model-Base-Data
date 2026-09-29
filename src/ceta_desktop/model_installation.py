"""Content-pinned model acquisition for CETA's private Ollama 0.34.3 store.

Installation is an asset operation, not an inference or capability test. The
runtime manifest is published only after every referenced blob has been verified.
"""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4
import zipfile

from .hardware import GIB, ModelOption, assess_model
from .runtime_installation import RuntimeInstallError, _check, _digest, _directory, _plain, asset_lock


class ModelInstallError(RuntimeInstallError):
    pass


def model_layers(entry):
    manifest = json.loads(entry["manifest"])
    return [manifest["config"], *manifest["layers"]]


def model_name(entry):
    return f"ceta-{entry['id']}:{entry['sha256']}"


def model_option(entry):
    size = sum(layer["size"] for layer in model_layers(entry))
    return ModelOption(model_name(entry), size, math.ceil(size * 1.25) + GIB, entry["description"])


def recommended_entry(entries, profile):
    """Prefer a fitting balanced candidate, not the largest memory allocation."""
    for mode in ("gpu", "cpu"):
        for identifier in ("qwen3-4b", "qwen3-17b", "qwen3-06b"):
            for entry in entries:
                if entry["id"] == identifier and assess_model(profile, model_option(entry)).mode == mode:
                    return entry
    return None


def validate_model_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get("schema") != "ceta.managed-model-catalog.v1":
        raise ModelInstallError("Unsupported managed model catalog.")
    entries = catalog.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise ModelInstallError("Invalid managed model catalog size.")
    ids = set()
    for entry in entries:
        if not isinstance(entry, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,48}", entry.get("id", "")) or entry["id"] in ids:
            raise ModelInstallError("Invalid or duplicate managed model identifier.")
        ids.add(entry["id"])
        if entry.get("repository") != "library/qwen3" or entry.get("runtime_version") != "0.34.3":
            raise ModelInstallError("The model requires an unsupported registry or runtime layout.")
        raw = entry.get("manifest")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 65536:
            raise ModelInstallError("Invalid pinned model manifest.")
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != entry.get("sha256"):
            raise ModelInstallError("The model manifest does not match its pinned identity.")
        manifest = json.loads(raw)
        if (manifest.get("schemaVersion") != 2 or
                manifest.get("mediaType") != "application/vnd.docker.distribution.manifest.v2+json" or
                set(manifest) != {"schemaVersion", "mediaType", "config", "layers"} or
                not isinstance(manifest["layers"], list) or not 1 <= len(manifest["layers"]) <= 16):
            raise ModelInstallError("Unsupported model manifest structure.")
        kinds, digests = [], set()
        for layer in model_layers(entry):
            if (not isinstance(layer, dict) or set(layer) != {"mediaType", "digest", "size"} or
                    not isinstance(layer.get("digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", layer["digest"]) or
                    type(layer.get("size")) is not int or not 0 < layer["size"] <= 64 * GIB):
                raise ModelInstallError("Invalid pinned model layer.")
            if layer["digest"] in digests:
                raise ModelInstallError("Duplicate model layer identity.")
            digests.add(layer["digest"]); kinds.append(layer["mediaType"])
            if layer["mediaType"] == "application/vnd.ollama.image.license":
                notice = catalog.get("licenses", {}).get(layer["digest"])
                if (not isinstance(notice, str) or len(notice.encode()) != layer["size"] or
                        hashlib.sha256(notice.encode()).hexdigest() != layer["digest"][7:]):
                    raise ModelInstallError("The pinned model license is missing or changed.")
        allowed = {"application/vnd.docker.container.image.v1+json", *("application/vnd.ollama.image." + kind
                    for kind in ("model", "template", "params", "license", "system"))}
        if (any(kind not in allowed for kind in kinds) or kinds[0] != "application/vnd.docker.container.image.v1+json" or
                kinds.count("application/vnd.ollama.image.model") != 1 or "application/vnd.ollama.image.license" not in kinds):
            raise ModelInstallError("Unsupported model content or missing model license.")
        if sum(layer["size"] for layer in model_layers(entry)) > 65 * GIB:
            raise ModelInstallError("The model exceeds the supported asset size.")
    hosts = catalog.get("registry_blob_redirect_hosts")
    if not isinstance(hosts, list) or not hosts or any(not isinstance(host, str) or not re.fullmatch(r"[0-9a-f]{32}\.r2\.cloudflarestorage\.com", host) for host in hosts):
        raise ModelInstallError("Missing approved model asset hosts.")
    return catalog


def bundled_models():
    return validate_model_catalog(json.loads(files("ceta_desktop").joinpath("model_catalog.json").read_text(encoding="utf-8")))


class _BlobRedirect(HTTPRedirectHandler):
    def __init__(self, original, digest, hosts):
        super().__init__()
        self.original, self.digest, self.hosts, self.used = original, digest, set(hosts), False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        path = f"/ollama/docker/registry/v2/blobs/sha256/{self.digest[:2]}/{self.digest}/data"
        if (self.used or req.full_url != self.original or code not in {302, 307} or req.get_method() != "GET" or
                parsed.scheme != "https" or parsed.hostname not in self.hosts or parsed.port not in (None, 443) or
                parsed.path != path or parsed.username or parsed.password or parsed.fragment or
                not newurl.isascii() or any(c.isspace() or ord(c) < 32 for c in newurl)):
            raise ModelInstallError("The model download left the approved registry asset hosts or identity.")
        self.used = True
        headers = {"User-Agent": "CETA-model-setup", "Accept-Encoding": "identity"}
        if req.get_header("Range"):
            headers["Range"] = req.get_header("Range")
        return Request(newurl, headers=headers)

    def http_error_302(self, req, fp, code, msg, headers):
        try:
            locations = headers.get_all("Location", [])
            if len(locations) != 1:
                raise ModelInstallError("The model download has an ambiguous redirect.")
            target = self.redirect_request(req, fp, code, msg, headers, locations[0])
        finally:
            fp.close()
        return self.parent.open(target, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _open_blob(entry, layer, hosts, offset):
    url = f"https://registry.ollama.ai/v2/{entry['repository']}/blobs/{layer['digest']}"
    headers = {"User-Agent": "CETA-model-setup", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), _BlobRedirect(url, layer["digest"][7:], hosts))
    return opener.open(Request(url, headers=headers), timeout=5)


class ManagedModels:
    def __init__(self, data_directory, catalog=None):
        self.catalog = validate_model_catalog(catalog if catalog is not None else bundled_models())
        base = Path(data_directory).resolve()
        base.mkdir(parents=True, exist_ok=True)
        self.root = _directory(base / "managed-models")
        self.downloads = _directory(self.root / "downloads")
        self.store = _directory(_directory(base / "managed-runtime-state") / "models")
        self.blobs = _directory(self.store / "blobs")

    def entry(self, identifier):
        for entry in self.catalog["entries"]:
            if entry["id"] == identifier:
                return entry
        raise ModelInstallError("Choose a model from this installation's pinned catalog.")

    def _manifest_path(self, entry):
        path = self.store
        for part in ("manifests", "registry.ollama.ai", "library", "ceta-" + entry["id"]):
            path = _directory(path / part)
        return path / entry["sha256"]

    def _verify_blob(self, path, layer, cancelled, deadline):
        if _plain(path).st_size != layer["size"]:
            raise ModelInstallError("A model file has the wrong size. Existing files were preserved.")
        with path.open("rb") as stream:
            digest, _ = _digest(stream, cancelled, deadline, limit=layer["size"])
        if digest != layer["digest"][7:]:
            raise ModelInstallError("A model file failed its pinned checksum. Existing files were preserved.")

    def _verify(self, entry, cancelled, deadline, progress):
        manifest = self._manifest_path(entry)
        if not manifest.exists():
            raise ModelInstallError("Install or import this managed model first.")
        _plain(manifest)
        if manifest.stat().st_size != len(entry["manifest"].encode()) or manifest.read_bytes() != entry["manifest"].encode():
            raise ModelInstallError("The installed model manifest differs from the pinned catalog.")
        for layer in model_layers(entry):
            progress("Verifying " + entry["label"] + " model files")
            self._verify_blob(self.blobs / layer["digest"].replace(":", "-"), layer, cancelled, deadline)
        return {"schema": "ceta.managed-model-installation.v1", "model": model_name(entry), "catalog_id": entry["id"],
                "sha256": entry["sha256"], "files_verified": len(model_layers(entry)), "observed_at": time.time(),
                "bytes": sum(layer["size"] for layer in model_layers(entry)), "inference": "not_tested"}

    def verify(self, identifier, *, cancelled=None, progress=lambda _: None):
        with asset_lock(self.root):
            return self._verify(self.entry(identifier), cancelled, time.monotonic() + 1800, progress)

    def _download(self, entry, layer, target, cancelled, deadline, progress):
        offset = _plain(target).st_size if target.exists() else 0
        if offset > layer["size"]:
            raise ModelInstallError("A partial model download exceeds its pinned size. It was preserved.")
        if offset == layer["size"]:
            return
        response = None
        try:
            response = _open_blob(entry, layer, self.catalog["registry_blob_redirect_hosts"], offset)
            expected_range = f"bytes {offset}-{layer['size'] - 1}/{layer['size']}"
            if (response.status not in {200, 206} or (offset and response.status != 206) or
                    (response.status == 206 and response.headers.get("Content-Range") != expected_range) or
                    response.headers.get("Content-Encoding", "identity") != "identity" or
                    response.headers.get("Content-Length", str(layer["size"]-offset)) != str(layer["size"]-offset)):
                raise ModelInstallError("The model response does not match the pinned byte range or size.")
            with target.open("ab" if target.exists() else "xb") as writer:
                count, last = offset, 0.0
                while count < layer["size"]:
                    _check(cancelled, deadline)
                    block = response.read(min(256 * 1024, layer["size"] - count))
                    if not block:
                        raise ModelInstallError("Model download interrupted. Download again to resume the saved partial files.")
                    writer.write(block); count += len(block)
                    if time.monotonic() - last >= .2:
                        progress(f"Downloading {entry['label']}: {count / 1024**2:.1f} / {layer['size'] / 1024**2:.1f} MiB in this file")
                        last = time.monotonic()
                _check(cancelled, deadline)
                if response.read(1):
                    raise ModelInstallError("The model response exceeded the pinned size.")
                writer.flush(); os.fsync(writer.fileno())
        except HTTPError as exc:
            exc.close()
            raise ModelInstallError("The model registry could not complete the download. Partial files were preserved.") from None
        except (URLError, OSError):
            raise ModelInstallError("Model download interrupted. Retry to resume the preserved partial files.") from None
        finally:
            if response is not None:
                response.close()

    def _archive(self, source, entry):
        size = _plain(Path(source)).st_size
        # A CETA model ZIP has no comment and a tiny central directory, including
        # ZIP64 models. Bound directory allocation before zipfile parses input.
        if not 22 <= size <= sum(row["size"] for row in model_layers(entry)) + 1024**2:
            raise ModelInstallError("The model ZIP has an unsupported size.")
        with Path(source).open("rb") as stream:
            stream.seek(-22, 2)
            signature, disk, cd_disk, count_disk, count, cd_size, cd_offset, comment = struct.unpack("<4sHHHHIIH", stream.read(22))
            if signature != b"PK\x05\x06" or disk or cd_disk or comment or count_disk != count:
                raise ModelInstallError("Use an unmodified CETA model ZIP without split volumes or comments.")
            if cd_offset == 0xffffffff or cd_size == 0xffffffff or count == 0xffff:
                if size < 98:
                    raise ModelInstallError("Invalid model ZIP64 directory.")
                stream.seek(-42, 2)
                signature, disk, offset, disks = struct.unpack("<4sIQI", stream.read(20))
                if signature != b"PK\x06\x07" or disk or disks != 1 or not 0 <= offset <= size - 98:
                    raise ModelInstallError("Invalid model ZIP64 locator.")
                stream.seek(offset)
                values = struct.unpack("<4sQHHIIQQQQ", stream.read(56))
                if values[0] != b"PK\x06\x06" or values[1] != 44 or values[4] or values[5] or values[6] != values[7]:
                    raise ModelInstallError("Invalid model ZIP64 directory.")
                count, cd_size, cd_offset = values[7:]
            if not 1 <= count <= 20 or not 0 < cd_size <= 65536 or not 0 <= cd_offset <= size - cd_size:
                raise ModelInstallError("The model ZIP directory exceeds its bounds.")
        archive = zipfile.ZipFile(source)
        try:
            expected = {"manifest.json": len(entry["manifest"].encode()),
                        **{"blobs/" + row["digest"].replace(":", "-"): row["size"] for row in model_layers(entry)}}
            members = archive.infolist()
            if len(members) != len(expected) or {row.filename for row in members} != set(expected):
                raise ModelInstallError("This model ZIP does not contain exactly the selected model's pinned files.")
            for member in members:
                if (member.file_size != expected[member.filename] or member.flag_bits & 1 or
                        stat.S_IFMT(member.external_attr >> 16) not in {0, stat.S_IFREG}):
                    raise ModelInstallError("Unsupported or incorrectly sized member in the model ZIP.")
            if archive.read("manifest.json") != entry["manifest"].encode():
                raise ModelInstallError("The imported model manifest differs from the pinned catalog.")
            return archive
        except BaseException:
            archive.close()
            raise

    def acquire(self, identifier, *, source=None, cancelled=None, progress=lambda _: None):
        entry, deadline = self.entry(identifier), time.monotonic() + 8 * 3600
        with asset_lock(self.root):
            _check(cancelled, deadline)
            _plain(self.blobs, directory=True); _plain(self.downloads, directory=True)
            missing = [row for row in model_layers(entry) if not (self.blobs / row["digest"].replace(":", "-")).exists()]
            needed = sum(row["size"] for row in missing) + 128 * 1024**2
            if source is None:
                for row in missing:
                    partial = self.downloads / (row["digest"][7:] + ".part")
                    if partial.exists():
                        needed -= min(row["size"], _plain(partial).st_size)
            if shutil.disk_usage(self.store).free < needed:
                raise ModelInstallError("There is not enough free disk space to install this model.")
            archive = self._archive(source, entry) if source is not None else None
            try:
                for layer in model_layers(entry):
                    _check(cancelled, deadline)
                    destination = self.blobs / layer["digest"].replace(":", "-")
                    if destination.exists():
                        self._verify_blob(destination, layer, cancelled, deadline)
                        continue
                    target = self.downloads / (layer["digest"][7:] + ".part")
                    if archive is None:
                        self._download(entry, layer, target, cancelled, deadline, progress)
                    else:
                        target = self.downloads / (layer["digest"][7:] + ".import-" + uuid4().hex)
                        progress("Importing " + entry["label"])
                        with archive.open("blobs/" + layer["digest"].replace(":", "-")) as reader, target.open("xb") as writer:
                            count = 0
                            while True:
                                _check(cancelled, deadline)
                                block = reader.read(1024 * 1024)
                                if not block:
                                    break
                                count += len(block)
                                if count > layer["size"]:
                                    raise ModelInstallError("The imported model exceeds its pinned size.")
                                writer.write(block)
                            writer.flush(); os.fsync(writer.fileno())
                    self._verify_blob(target, layer, cancelled, deadline)
                    target.rename(destination)
                _check(cancelled, deadline)
                manifest = self._manifest_path(entry)
                if not manifest.exists():
                    temporary = self.root / (".manifest-" + uuid4().hex)
                    with temporary.open("xb") as stream:
                        stream.write(entry["manifest"].encode()); stream.flush(); os.fsync(stream.fileno())
                    temporary.rename(manifest)
                return self._verify(entry, cancelled, deadline, progress)
            finally:
                if archive is not None:
                    archive.close()

    def export(self, identifier, destination, *, cancelled=None, progress=lambda _: None):
        entry, deadline = self.entry(identifier), time.monotonic() + 8 * 3600
        destination = Path(destination)
        with asset_lock(self.root):
            self._verify(entry, cancelled, deadline, progress)
            if shutil.disk_usage(destination.parent).free < sum(row["size"] for row in model_layers(entry)) + 128 * 1024**2:
                raise ModelInstallError("There is not enough disk space for the offline model ZIP.")
            with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                archive.writestr("manifest.json", entry["manifest"].encode())
                for layer in model_layers(entry):
                    name = "blobs/" + layer["digest"].replace(":", "-")
                    progress("Exporting " + entry["label"])
                    digest, count = hashlib.sha256(), 0
                    with (self.blobs / layer["digest"].replace(":", "-")).open("rb") as reader, archive.open(name, "w", force_zip64=True) as writer:
                        while True:
                            _check(cancelled, deadline)
                            block = reader.read(1024 * 1024)
                            if not block:
                                break
                            count += len(block)
                            if count > layer["size"]:
                                raise ModelInstallError("The model changed while exporting.")
                            digest.update(block); writer.write(block)
                    if count != layer["size"] or digest.hexdigest() != layer["digest"][7:]:
                        raise ModelInstallError("The model changed during export; this partial ZIP must not be used.")
            return {"model": model_name(entry), "sha256": entry["sha256"], "path": str(destination), "status": "exported"}
