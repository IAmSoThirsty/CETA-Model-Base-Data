from __future__ import annotations

import base64
import hashlib
import json
from email.message import Message
from io import BytesIO
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import traceback
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import build_opener, HTTPSHandler, ProxyHandler, Request
from urllib.response import addinfourl

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ceta_desktop import __version__
from ceta_desktop.updates import (
    UpdateError, verify_manifest, download_update, check_update, verified_https,
    NoRedirects, CetaReleaseRedirects,
)


class DesktopUpdateTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public_key = base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.manifest = {"schema_version": 1, "product": "CETA", "version": "0.3.1", "platform": "windows-x64",
                         "url": "https://example.invalid/CETA-0.3.1-setup.exe", "sha256": hashlib.sha256(b"fixture").hexdigest(), "size": 7}

    def signed(self):
        data = json.dumps(self.manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return {"manifest": dict(self.manifest), "signature": base64.b64encode(self.key.sign(b"CETA/UPDATE/v1\n" + data)).decode()}

    def test_accepts_correct_publisher_signature(self):
        self.assertEqual(verify_manifest(self.signed(), self.public_key, "0.3.0"), self.manifest)

    def test_signing_command_produces_an_update_accepted_by_ceta(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = root / "CETA-0.3.1-setup.exe"
            installer.write_bytes(b"fixture")
            key = root / "test-only-private.pem"
            key.write_bytes(self.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            output = root / "channel.json"
            subprocess.run([sys.executable, "-B", str(ROOT / "scripts/sign_desktop_update.py"),
                            "--installer", str(installer), "--version", "0.3.1",
                            "--url", self.manifest["url"], "--private-key", str(key),
                            "--output", str(output)], check=True, capture_output=True, text=True)
            self.assertEqual(verify_manifest(json.loads(output.read_text()), self.public_key, "0.3.0"), self.manifest)

    def test_other_product_and_signature_domain_are_rejected(self):
        self.manifest["product"] = "ThirstyAI"
        with self.assertRaises(UpdateError):
            verify_manifest(self.signed(), self.public_key, "0.3.0")
        self.manifest["product"] = "CETA"
        data = json.dumps(self.manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        envelope = {"manifest": self.manifest,
                    "signature": base64.b64encode(self.key.sign(b"THIRSTYAI/UPDATE/v1\n" + data)).decode()}
        with self.assertRaises(UpdateError):
            verify_manifest(envelope, self.public_key, "0.3.0")

    def test_rejects_modified_payload_and_untrusted_publisher(self):
        envelope = self.signed()
        envelope["manifest"]["url"] = "https://example.invalid/tampered.exe"
        with self.assertRaises(UpdateError):
            verify_manifest(envelope, self.public_key, "0.3.0")
        other_key = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        with self.assertRaises(UpdateError):
            verify_manifest(self.signed(), other_key, "0.3.0")

    def test_rejects_downgrade_wrong_platform_and_insecure_download(self):
        for field, value in (("version", "0.2.0"), ("platform", "other"), ("product", "other"),
                             ("url", "http://example.invalid/update.exe"), ("size", -1), ("sha256", "invalid")):
            original = self.manifest[field]
            self.manifest[field] = value
            with self.subTest(field=field), self.assertRaises(UpdateError):
                verify_manifest(self.signed(), self.public_key, "0.3.0")
            self.manifest[field] = original

    def test_rejects_malformed_metadata_and_urls(self):
        for value in (None, [], "manifest", 1):
            with self.subTest(value=value), self.assertRaises(UpdateError):
                verify_manifest(value, self.public_key, "0.3.0")
        for value in (None, "https://example.invalid:99999/x", "https://example.invalid:0/x",
                      "https://example.invalid/\nx", "https://[broken/x", "https://user:secret@example.invalid/x"):
            with self.subTest(value=value), self.assertRaises(UpdateError):
                verified_https(value)
        self.manifest["schema_version"] = True
        with self.assertRaises(UpdateError):
            verify_manifest(self.signed(), self.public_key, "0.3.0")

    def test_verified_download_publishes_only_complete_matching_bytes(self):
        with tempfile.TemporaryDirectory() as directory, patch("ceta_desktop.updates.build_opener") as factory:
            factory.return_value.open.return_value = BytesIO(b"fixture")
            progress = []
            target = download_update(self.manifest, Path(directory), progress=lambda count, total: progress.append((count, total)))
            self.assertEqual(target.read_bytes(), b"fixture")
            self.assertEqual(target.name, "CETA-0.3.1-setup.exe")
            self.assertEqual(progress, [(7, 7)])
            self.assertEqual(list(Path(directory).iterdir()), [target])
            with self.assertRaises(UpdateError):
                download_update(self.manifest, Path(directory))
            self.assertEqual(target.read_bytes(), b"fixture")

    def test_failed_and_cancelled_downloads_leave_no_partial_installer(self):
        for payload in (b"wrong!!", b"short", b"fixture plus extra"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory, patch("ceta_desktop.updates.build_opener") as factory:
                factory.return_value.open.return_value = BytesIO(payload)
                with self.assertRaises(UpdateError):
                    download_update(self.manifest, Path(directory))
                self.assertEqual(list(Path(directory).iterdir()), [])
        with tempfile.TemporaryDirectory() as directory, patch("ceta_desktop.updates.build_opener") as factory:
            factory.return_value.open.return_value = BytesIO(b"fixture")
            cancelled = threading.Event()
            # Cancellation after the final chunk must still prevent publication.
            with self.assertRaises(UpdateError):
                download_update(self.manifest, Path(directory), cancelled, lambda *_: cancelled.set())
            self.assertEqual(list(Path(directory).iterdir()), [])
            factory.reset_mock()
            with self.assertRaises(UpdateError):
                download_update(self.manifest, Path(directory), cancelled)
            factory.assert_not_called()

    def test_download_rejects_path_injection_before_creating_files(self):
        self.manifest["version"] = "../../escape"
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(UpdateError):
            download_update(self.manifest, Path(directory) / "absent")
        with self.assertRaises(UpdateError):
            NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://example.invalid/other")

    def test_check_update_reads_signed_envelope_and_bounds_manifest_size(self):
        with patch("ceta_desktop.updates.build_opener") as factory:
            factory.return_value.open.return_value = BytesIO(json.dumps(self.signed()).encode())
            self.assertEqual(check_update("https://example.invalid/channel.json", self.public_key, "0.3.0"), self.manifest)
            factory.return_value.open.return_value = BytesIO(b"x" * 65537)
            with self.assertRaises(UpdateError):
                check_update("https://example.invalid/channel.json", self.public_key, "0.3.0")

    def test_manifest_transport_receives_truthful_application_identity(self):
        """Send CETA's running version while preserving the JSON request and signature check."""
        endpoint = "https://example.invalid/channel.json"
        network = FixtureHTTPSHandler({endpoint: (200, [], json.dumps(self.signed()).encode())})
        with patch("ceta_desktop.updates.build_opener", side_effect=network.opener):
            self.assertEqual(check_update(endpoint, self.public_key, "0.3.0"), self.manifest)
        self.assertEqual(len(network.requests), 1)
        self.assertEqual(network.requests[0].get_header("User-agent"), f"CETA/{__version__}")
        self.assertEqual(network.requests[0].get_header("Accept"), "application/json")


class FixtureHTTPSHandler(HTTPSHandler):

    """Exercise urllib response and redirect handlers without a real network."""

    def __init__(self, responses):
        """Record requests against an exact fixture response map."""
        super().__init__()
        self.responses = responses
        self.requests = []

    def https_open(self, req):
        """Supply fixture HTTP responses to the standard urllib handler chain."""
        self.requests.append(req)
        response = self.responses[req.full_url]
        if isinstance(response, Exception):
            raise response
        status, locations, payload = response
        headers = Message()
        for location in locations:
            headers.add_header("Location", location)
        result = addinfourl(BytesIO(payload), headers, req.full_url, status)
        result.msg = "fixture"
        return result

    def opener(self, *handlers):
        """Keep real response handlers while replacing HTTPS transport and proxies."""
        redirects = [handler for handler in handlers if not isinstance(handler, HTTPSHandler)]
        return build_opener(ProxyHandler({}), self, *redirects)


class CetaReleaseRedirectTests(unittest.TestCase):

    """Cover the one-hop GitHub boundary through urllib's actual handler flow."""

    def setUp(self):
        self.release = (
            "https://github.com/IAmSoThirsty/CETA-Model-Base-Data/releases/download/"
            "desktop-v0.3.1/CETA-0.3.1-setup.exe"
        )
        self.cdn = (
            "https://release-assets.githubusercontent.com/github-production-release-asset/"
            "1345269779/test-asset?test-only-authorization=preserve-exactly%2Bvalue"
        )
        self.manifest = {
            "schema_version": 1, "product": "CETA", "version": "0.3.1",
            "platform": "windows-x64", "url": self.release,
            "sha256": hashlib.sha256(b"fixture").hexdigest(), "size": 7,
        }

    def transport(self, payload=b"fixture"):
        """Create the observed GitHub-to-CDN response flow with tiny fixture bytes."""
        return FixtureHTTPSHandler({
            self.release: (302, [self.cdn], b""),
            self.cdn: (200, [], payload),
        })

    def test_one_github_redirect_preserves_query_and_publishes_verified_bytes(self):
        """Accept the approved hop without changing GitHub's signed query."""
        network = self.transport()
        with tempfile.TemporaryDirectory() as directory, patch(
                "ceta_desktop.updates.build_opener", side_effect=network.opener):
            target = download_update(self.manifest, Path(directory))
            self.assertEqual(target.read_bytes(), b"fixture")
            self.assertEqual(list(Path(directory).iterdir()), [target])
        self.assertEqual([request.full_url for request in network.requests],
                         [self.release, self.cdn])
        for request in network.requests:
            self.assertEqual(request.get_header("User-agent"), f"CETA/{__version__}")

    def test_direct_github_download_still_works(self):
        """Accept direct release responses without requiring a redirect."""
        network = FixtureHTTPSHandler({self.release: (200, [], b"fixture")})
        with tempfile.TemporaryDirectory() as directory, patch(
                "ceta_desktop.updates.build_opener", side_effect=network.opener):
            self.assertEqual(download_update(self.manifest, Path(directory)).read_bytes(),
                             b"fixture")
        self.assertEqual(len(network.requests), 1)
        self.assertEqual(network.requests[0].get_header("User-agent"), f"CETA/{__version__}")

    def test_redirect_discards_original_authentication_and_host_headers(self):
        """Do not leak credentials or reuse the original Host on the CDN request."""
        network = self.transport()
        opener = network.opener(CetaReleaseRedirects(self.release, "0.3.1"))
        request = Request(self.release, headers={
            "Authorization": "test-only credential", "Cookie": "test-only cookie",
            "Host": "github.com", "Referer": "https://example.invalid/private",
        })
        with opener.open(request) as response:
            self.assertEqual(response.read(), b"fixture")
        redirected = network.requests[1]
        headers = {name.lower(): value for name, value in redirected.header_items()}
        for name in ("authorization", "cookie", "referer"):
            self.assertNotIn(name, headers)
        self.assertEqual(headers["host"], "release-assets.githubusercontent.com")
        self.assertEqual(headers["accept"], "application/octet-stream")
        self.assertEqual(headers["user-agent"], f"CETA/{__version__}")
        self.assertEqual(redirected.get_method(), "GET")

    def test_unapproved_original_release_urls_cannot_redirect(self):
        """Refuse redirects outside the exact versioned CETA installer source."""
        invalid = [
            self.release.replace("IAmSoThirsty", "another-owner"),
            self.release.replace("CETA-Model-Base-Data", "another-repository"),
            self.release.replace("download/desktop-v0.3.1", "latest/download"),
            self.release.replace("CETA-0.3.1-setup.exe", "CETA-0.3.2-setup.exe"),
            self.release.replace("desktop-v0.3.1", "../desktop-v0.3.1"),
            self.release.replace("desktop-v0.3.1", "tag%2Fother"),
            self.release.replace("github.com", "github.com.evil.invalid"),
            self.release.replace("github.com", "github.com:444"),
            self.release.replace("github.com", "@github.com"),
            self.release + "?redirect=elsewhere",
            self.release + "?", self.release + "#",
            "https://example.invalid/CETA-0.3.1-setup.exe",
        ]
        for original in invalid:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                manifest = {**self.manifest, "url": original}
                # urllib removes an empty fragment before sending the original request.
                network = FixtureHTTPSHandler({
                    Request(original).full_url: (302, [self.cdn], b""),
                })
                with patch("ceta_desktop.updates.build_opener", side_effect=network.opener):
                    with self.assertRaises(UpdateError):
                        download_update(manifest, Path(directory))
                self.assertEqual(len(network.requests), 1)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_malicious_locations_fail_before_any_onward_request(self):
        """Reject host, scheme, authority, fragment, and control-character attacks."""
        invalid = [
            self.cdn.replace("https:", "http:"),
            self.cdn.replace("https:", "ftp:"),
            "file:///C:/test-only.exe", "//release-assets.githubusercontent.com/asset",
            self.cdn.replace("release-assets.", "evil.release-assets."),
            self.cdn.replace(".com/", ".com.evil.invalid/"),
            self.cdn.replace(".com/", ".com./"),
            self.cdn.replace(".com/", ".com:444/"),
            self.cdn.replace("https://", "https://test-only:credential@"),
            self.cdn.replace("https://", "https://@"),
            self.cdn.replace("release-assets.githubusercontent.com", "127.0.0.1"),
            self.cdn.replace("release-assets", "rele\u0430se-assets"),
            self.cdn + "#fragment", self.cdn + "#", self.cdn + "\u00e9",
            self.cdn + "\x00", self.cdn + "\x7f",
            self.cdn + "\r\n", self.cdn + " ",
        ]
        for location in invalid:
            with self.subTest(location=location), tempfile.TemporaryDirectory() as directory:
                network = FixtureHTTPSHandler({self.release: (302, [location], b"")})
                with patch("ceta_desktop.updates.build_opener", side_effect=network.opener):
                    with self.assertRaises(UpdateError):
                        download_update(self.manifest, Path(directory))
                self.assertEqual(len(network.requests), 1)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_multiple_missing_or_wrong_status_redirects_are_rejected(self):
        """Allow only a 302 with one Location header."""
        cases = [(302, []), (302, [self.cdn, self.cdn])]
        cases.extend((status, [self.cdn]) for status in (301, 303, 307, 308))
        for status, locations in cases:
            with self.subTest(status=status, locations=locations):
                network = FixtureHTTPSHandler({self.release: (status, locations, b"")})
                opener = network.opener(CetaReleaseRedirects(self.release, "0.3.1"))
                with self.assertRaises(UpdateError):
                    opener.open(self.release)
                self.assertEqual(len(network.requests), 1)

    def test_second_hop_and_redirect_loops_are_rejected(self):
        """Stop all onward CDN redirects before a third request occurs."""
        for destination in (self.cdn, self.release, "https://example.invalid/installer"):
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as directory:
                network = self.transport()
                network.responses[self.cdn] = (302, [destination], b"")
                with patch("ceta_desktop.updates.build_opener", side_effect=network.opener):
                    with self.assertRaises(UpdateError):
                        download_update(self.manifest, Path(directory))
                self.assertEqual(len(network.requests), 2)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_redirected_integrity_failures_and_cancellation_leave_no_installer(self):
        """Keep integrity checks and cleanup active after the permitted redirect."""
        for payload in (b"wrong!!", b"short", b"fixture plus extra"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                network = self.transport(payload)
                with patch("ceta_desktop.updates.build_opener", side_effect=network.opener):
                    with self.assertRaises(UpdateError):
                        download_update(self.manifest, Path(directory))
                self.assertEqual(list(Path(directory).iterdir()), [])
        network = self.transport()
        cancelled = threading.Event()
        with tempfile.TemporaryDirectory() as directory, patch(
                "ceta_desktop.updates.build_opener", side_effect=network.opener):
            with self.assertRaises(UpdateError):
                download_update(self.manifest, Path(directory), cancelled,
                                lambda *_: cancelled.set())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cdn_network_errors_do_not_expose_authorization_query(self):
        """Sanitize transport failures and discard the incomplete installer."""
        network = self.transport()
        network.responses[self.cdn] = URLError("test-only network failure at " + self.cdn)
        with tempfile.TemporaryDirectory() as directory, patch(
                "ceta_desktop.updates.build_opener", side_effect=network.opener):
            try:
                download_update(self.manifest, Path(directory))
            except UpdateError:
                self.assertNotIn("test-only-authorization", traceback.format_exc())
            else:
                self.fail("The network failure should reject the download.")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_manifest_fetch_rejects_even_the_approved_cdn_redirect(self):
        """Keep manifest retrieval outside the installer redirect exception."""
        network = self.transport()
        with patch("ceta_desktop.updates.build_opener", side_effect=network.opener):
            with self.assertRaises(UpdateError):
                check_update(self.release, "unused-test-only-key", "0.3.0")
        self.assertEqual(len(network.requests), 1)


if __name__ == "__main__":
    unittest.main()
