from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import tempfile
import threading
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, Request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class UpdateError(ValueError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise UpdateError("Update redirects are not allowed. Use the publisher's exact HTTPS URL.")


class CetaReleaseRedirects(HTTPRedirectHandler):

    """Permit one CETA installer hop from its signed GitHub URL to GitHub's CDN."""

    def __init__(self, original_url: str, version: str):
        """Bind the only permitted redirect to the signed release and version."""
        super().__init__()
        self.original_url = original_url
        source = urlsplit(verified_https(original_url))
        release_path = (
            r"/IAmSoThirsty/CETA-Model-Base-Data/releases/download/"
            rf"[A-Za-z0-9][A-Za-z0-9._-]*/CETA-{re.escape(version)}-setup\.exe"
        )
        self.eligible = (
            source.hostname == "github.com"
            and source.port in (None, 443)
            and source.username is None
            and source.password is None
            and "?" not in original_url and "#" not in original_url
            and re.fullmatch(release_path, source.path) is not None
        )
        self.redirected = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Validate the unmodified Location and discard original request credentials."""
        if (not self.eligible or self.redirected or code != 302
                or req.full_url != self.original_url or req.get_method() != "GET"):
            raise UpdateError("Only one CETA GitHub release download redirect is allowed.")
        if (not isinstance(newurl, str) or not newurl.isascii() or "#" in newurl):
            raise UpdateError("The CETA release redirect is invalid.")
        if any(
                ord(character) < 32 or ord(character) == 127 for character in newurl):
            raise UpdateError("The CETA release redirect is invalid.")
        target = urlsplit(verified_https(newurl))
        if (target.hostname != "release-assets.githubusercontent.com"
                or target.port not in (None, 443)
                or target.username is not None or target.password is not None):
            raise UpdateError("The CETA release redirect is outside the approved download host.")
        self.redirected = True
        return Request(newurl, headers={"Accept": "application/octet-stream"}, method="GET")

    def http_error_302(self, req, fp, code, msg, headers):
        """Check before urllib normalizes URLs, without reading a redirect response body."""
        try:
            locations = headers.get_all("Location", [])
            if len(locations) != 1:
                raise UpdateError("The CETA release redirect must have one download location.")
            redirected = self.redirect_request(req, fp, code, msg, headers, locations[0])
        finally:
            fp.close()
        try:
            return self.parent.open(redirected, timeout=req.timeout)
        except OSError:
            # CDN URLs carry short-lived authorization. Never expose them in errors.
            raise UpdateError("The CETA release download could not be completed.") from None

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def verified_https(url: str) -> str:
    if not isinstance(url, str) or not url or any(character.isspace() for character in url):
        raise UpdateError("Updates require a valid HTTPS publisher URL.")
    try:
        parsed = urlsplit(url)
        valid_port = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError as exc:
        raise UpdateError("Updates require a valid HTTPS publisher URL.") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or not valid_port:
        raise UpdateError("Updates require an HTTPS publisher URL without embedded credentials.")
    return url


def version_tuple(version: str) -> tuple[int, int, int]:
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}", version):
        raise UpdateError("The update version must have three numeric components.")
    return tuple(int(part) for part in version.split("."))


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "product", "version", "platform", "url", "sha256", "size"}:
        raise UpdateError("Invalid update manifest fields.")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["product"] != "CETA" or manifest["platform"] != "windows-x64":
        raise UpdateError("The update is for a different product, platform, or schema.")
    version_tuple(manifest["version"])
    verified_https(manifest["url"])
    if not isinstance(manifest["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]):
        raise UpdateError("Invalid update checksum.")
    if type(manifest["size"]) is not int or not 0 < manifest["size"] <= 4 * 1024**3:
        raise UpdateError("Invalid update size.")
    return dict(manifest)


def verify_manifest(envelope: dict, public_key: str, current_version: str) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"manifest", "signature"}:
        raise UpdateError("Invalid signed update envelope.")
    manifest = validate_manifest(envelope["manifest"])
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(base64.b64decode(envelope["signature"], validate=True), b"CETA/UPDATE/v1\n" + canonical)
    except (ValueError, InvalidSignature, TypeError) as exc:
        raise UpdateError("The update signature does not match the configured publisher.") from exc
    if version_tuple(manifest["version"]) <= version_tuple(current_version):
        raise UpdateError("The update is not newer than the installed version.")
    return manifest


def check_update(url: str, public_key: str, current_version: str) -> dict:
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirects())
    with opener.open(Request(verified_https(url), headers={"Accept": "application/json"}), timeout=15) as response:
        data = response.read(65537)
    if len(data) > 65536:
        raise UpdateError("The update manifest is too large.")
    return verify_manifest(json.loads(data), public_key, current_version)


def download_update(manifest: dict, destination: Path, cancelled: threading.Event | None = None,
                    progress: Callable[[int, int], None] | None = None) -> Path:
    """Download already-verified metadata; publish only matching complete bytes."""
    manifest = validate_manifest(manifest)

    def check_cancelled():
        if cancelled and cancelled.is_set():
            raise UpdateError("Update download cancelled.")

    check_cancelled()
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"CETA-{manifest['version']}-setup.exe"
    if output.exists():
        raise UpdateError("An update with this name already exists. Choose a different destination folder.")
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()),
                          CetaReleaseRedirects(manifest["url"], manifest["version"]))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination, prefix=".ceta-update-", delete=False) as handle:
            temporary = Path(handle.name)
            digest = hashlib.sha256()
            count = 0
            with opener.open(verified_https(manifest["url"]), timeout=15) as response:
                while block := response.read(256 * 1024):
                    check_cancelled()
                    count += len(block)
                    if count > manifest["size"]:
                        raise UpdateError("Update exceeds its signed size.")
                    digest.update(block)
                    handle.write(block)
                    if progress:
                        progress(count, manifest["size"])
            handle.flush()
            os.fsync(handle.fileno())
        if count != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
            raise UpdateError("The downloaded update failed its signed checksum or size check.")
        check_cancelled()
        # Hard-link publication is atomic and refuses an existing destination.
        os.link(temporary, output)
        return output
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
