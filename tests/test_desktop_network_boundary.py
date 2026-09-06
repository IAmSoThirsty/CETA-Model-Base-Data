from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.network_boundary import network_import_errors


class DesktopNetworkBoundaryTests(unittest.TestCase):
    def test_only_exact_declared_desktop_transport_imports_are_allowed(self):
        self.assertEqual(network_import_errors(ast.parse("import http.client"), "src/ceta_desktop/models.py"), [])
        self.assertEqual(network_import_errors(ast.parse("from urllib.request import Request"), "src/ceta_desktop/updates.py"), [])
        for path in ("src/runtime/core.py", "src/ceta_desktop/app.py", "src/ceta_desktop/other.py", "scripts/verify_all.py"):
            with self.subTest(path=path):
                self.assertTrue(network_import_errors(ast.parse("import http.client"), path))
        self.assertTrue(network_import_errors(ast.parse("import requests"), "src/ceta_desktop/models.py"))

    def test_from_import_cannot_evade_reference_network_restriction(self):
        for text in ("from http import client", "from urllib import request", "from socket import socket"):
            with self.subTest(text=text):
                self.assertTrue(network_import_errors(ast.parse(text), "src/runtime/core.py"))


if __name__ == "__main__":
    unittest.main()
