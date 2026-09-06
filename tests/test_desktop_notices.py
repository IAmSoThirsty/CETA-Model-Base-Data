from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.desktop_notices import checked_sources, collect_source_notices


class DesktopNoticeTests(unittest.TestCase):
    def archive(self, path, members):
        with tarfile.open(path, "w:xz") as archive:
            for name, content in members.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, BytesIO(content))

    def test_collects_licenses_and_attribution_references_without_extracting_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.xz"
            self.archive(archive, {
                "source/LICENSES/LGPL-3.0-only.txt": b"license fixture",
                "source/vendor/qt_attribution.json": b'{"LicenseFile":"README", "Description":"multi\nline"}',
                "source/vendor/README": b"vendor copyright and permission fixture",
                "source/vendor/library.c": b"code fixture",
            })
            output = root / "notices"
            self.assertEqual(collect_source_notices(archive, output), 3)
            index_path = next(output.glob("*/INDEX.json"))
            index = json.loads(index_path.read_text())["notices"]
            readme = next(name for name, source in index.items() if source == "source/vendor/README")
            self.assertEqual((index_path.parent / readme).read_bytes(), b"vendor copyright and permission fixture")
            self.assertNotIn("source/vendor/library.c", index.values())

    def test_refuses_notice_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.xz"
            self.archive(archive, {"../LICENSE": b"fixture"})
            with self.assertRaises(ValueError):
                collect_source_notices(archive, root / "notices")
            self.assertFalse((root / "LICENSE").exists())

    def test_only_matching_source_archive_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "licenses").mkdir()
            source = root / "source.tar.xz"
            source.write_bytes(b"original archive fixture")
            specification = {"archives": [{"filename": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}
            (root / "licenses/desktop-sources.json").write_text(json.dumps(specification))
            with patch("scripts.desktop_notices.ROOT", root):
                self.assertEqual(checked_sources(root), [source])
                source.write_bytes(b"changed archive")
                with self.assertRaises(ValueError):
                    checked_sources(root)


if __name__ == "__main__":
    unittest.main()
