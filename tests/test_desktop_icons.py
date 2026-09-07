"""Check CETA's ICO using Qt's decoder independently of the byte encoder."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
desktop_icons = importlib.import_module("scripts.desktop_icons")
ICON_SIZES = desktop_icons.ICON_SIZES
create_windows_icon = desktop_icons.create_windows_icon
verify_ico = desktop_icons.verify_ico

HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
else:
    Qt = QImage = QPainter = QSvgRenderer = None


@unittest.skipUnless(HAS_QT, "Desktop extra is required for SVG/ICO rendering")
class DesktopIconTests(unittest.TestCase):
    """Exercise the encoded Windows frames and preserve existing output files."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.svg = ROOT / "src/ceta_desktop/icon.svg"
        self.icon = self.root / "CETA.ico"

    def test_every_frame_decodes_as_the_original_vector_at_its_native_size(self):
        """Qt decodes every frame with the exact original displayed pixels."""
        self.assertEqual(create_windows_icon(self.svg, self.icon), self.icon)
        self.assertEqual(verify_ico(self.icon), ICON_SIZES)
        raw = self.icon.read_bytes()
        for index, size in enumerate(ICON_SIZES):
            with self.subTest(size=size):
                entry = struct.unpack_from("<BBBBHHII", raw, 6 + index * 16)
                frame = raw[entry[7]:entry[7] + entry[6]]
                single = (struct.pack("<HHH", 0, 1, 1)
                          + struct.pack("<BBBBHHII", *entry[:6], entry[6], 22) + frame)
                decoded = QImage.fromData(single, "ICO").convertToFormat(QImage.Format_RGBA8888)
                self.assertEqual((decoded.width(), decoded.height()), (size, size))
                expected = QImage(size, size, QImage.Format_RGBA8888)
                expected.fill(Qt.transparent)
                painter = QPainter(expected)
                try:
                    painter.setRenderHint(QPainter.Antialiasing)
                    QSvgRenderer(str(self.svg)).render(painter)
                finally:
                    painter.end()
                # Qt's ICO reader premultiplies DIB alpha. Compare displayed
                # pixels without a lossy unpremultiply/re-premultiply roundtrip.
                native = QImage.fromData(single, "ICO")
                display_format = QImage.Format_ARGB32_Premultiplied
                native_display = native.convertToFormat(display_format)
                expected_display = expected.convertToFormat(display_format)
                self.assertEqual(
                    bytes(native_display.constBits()),
                    bytes(expected_display.constBits()),
                )
                self.assertEqual(decoded.pixelColor(0, 0).alpha(), 0)
                self.assertGreater(decoded.pixelColor(size // 2, size // 2).alpha(), 0)
                self.assertEqual(frame.startswith(b"\x89PNG\r\n\x1a\n"), size == 256)

    def test_repeated_rendering_has_identical_bytes_and_responds_to_artwork(self):
        """Identical inputs repeat exactly; changed vector content is respected."""
        create_windows_icon(self.svg, self.icon)
        other = self.root / "again.ico"
        create_windows_icon(self.svg, other)
        self.assertEqual(self.icon.read_bytes(), other.read_bytes())
        fixture = self.root / "fixture.svg"
        fixture.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">'
            '<rect width="256" height="256" fill="#ff8800"/></svg>',
            encoding="utf-8",
        )
        changed = self.root / "changed.ico"
        create_windows_icon(fixture, changed)
        self.assertNotEqual(self.icon.read_bytes(), changed.read_bytes())
        self.assertEqual(verify_ico(changed), ICON_SIZES)

    def test_existing_output_is_preserved(self):
        """Creation refuses an existing target without changing its bytes."""
        sentinel = b"pre-existing output must remain intact"
        self.icon.write_bytes(sentinel)
        with self.assertRaises(FileExistsError):
            create_windows_icon(self.svg, self.icon)
        self.assertEqual(self.icon.read_bytes(), sentinel)

    def test_bad_or_missing_svg_does_not_create_an_output(self):
        """Invalid artwork fails before creating the destination."""
        with self.assertRaises(FileNotFoundError):
            create_windows_icon(self.root / "missing.svg", self.icon)
        self.assertFalse(self.icon.exists())
        invalid = self.root / "invalid.svg"
        invalid.write_text("not SVG artwork", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid SVG"):
            create_windows_icon(invalid, self.icon)
        self.assertFalse(self.icon.exists())

    def test_dib_has_bottom_up_pixels_and_a_padded_legacy_transparency_mask(self):
        """Legacy frames carry aligned masks with the proper transparency bits."""
        create_windows_icon(self.svg, self.icon)
        raw = self.icon.read_bytes()
        for index, size in enumerate(ICON_SIZES[:-1]):
            with self.subTest(size=size):
                entry = struct.unpack_from("<BBBBHHII", raw, 6 + index * 16)
                frame = raw[entry[7]:entry[7] + entry[6]]
                self.assertEqual(
                    struct.unpack_from("<IiiHHI", frame), (40, size, size * 2, 1, 32, 0),
                )
                mask_stride = ((size + 31) // 32) * 4
                mask = frame[40 + size * size * 4:]
                self.assertEqual(len(mask), mask_stride * size)
                # The transparent corner is masked, while the visible orb center is not.
                self.assertTrue(mask[0] & 0x80)
                center_offset = (size // 2) * mask_stride + (size // 2) // 8
                self.assertFalse(mask[center_offset] & (0x80 >> ((size // 2) % 8)))

    def test_missing_wrong_or_corrupt_frames_fail_verification(self):
        """Reject incomplete sizes, invalid masks, corrupt PNG and invalid offsets."""
        create_windows_icon(self.svg, self.icon)
        valid = self.icon.read_bytes()
        first = struct.unpack_from("<BBBBHHII", valid, 6)
        last = struct.unpack_from("<BBBBHHII", valid, 6 + 8 * 16)
        cases = {}
        raw = bytearray(valid)
        struct.pack_into("<H", raw, 4, 8)
        cases["missing frame"] = raw
        raw = bytearray(valid)
        raw[6 + 16] = 16
        cases["wrong frame size"] = raw
        raw = bytearray(valid)
        struct.pack_into("<I", raw, 6 + 12, 0)
        cases["overlapping frame"] = raw
        raw = bytearray(valid)
        struct.pack_into("<i", raw, first[7] + 8, 16)
        cases["wrong doubled DIB height"] = raw
        raw = bytearray(valid)
        raw[first[7] + first[6] - 1] ^= 1
        cases["invalid AND mask padding"] = raw
        raw = bytearray(valid)
        raw[last[7]] = 0
        cases["256 frame is not PNG"] = raw
        raw = bytearray(valid)
        raw[last[7] + 40] ^= 1
        cases["PNG checksum corruption"] = raw
        cases["truncated payload"] = valid[:-1]
        cases["trailing data"] = valid + b"extra"
        for name, raw in cases.items():
            with self.subTest(case=name):
                corrupted = self.root / "corrupt.ico"
                corrupted.write_bytes(raw)
                with self.assertRaises(ValueError):
                    verify_ico(corrupted)

    def test_missing_output_parent_is_not_created_implicitly(self):
        """Callers must explicitly provide the build output directory."""
        output = self.root / "missing" / "CETA.ico"
        with self.assertRaises(FileNotFoundError):
            create_windows_icon(self.svg, output)
        self.assertFalse(output.parent.exists())


if __name__ == "__main__":
    unittest.main()
