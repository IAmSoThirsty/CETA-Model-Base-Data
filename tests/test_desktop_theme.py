"""Render native theme elements without a display server or downloaded artwork."""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout
    from ceta_desktop.theme import APP_STYLESHEET, BrandMark, EmberSidebar, ScenePage, icon


@unittest.skipUnless(HAS_QT, "Desktop extra is required for native theme tests")
class DesktopThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_artwork_renders_and_supplied_artwork_fades_below_controls(self):
        """Optional artwork remains visible without flooding labels or top panels."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = EmberSidebar(asset_path=root / "missing.png")
            missing.resize(220, 700)
            missing.setStyleSheet(APP_STYLESHEET)
            layout = QVBoxLayout(missing)
            label = QLabel("CETA", missing)
            label.setObjectName("brandName")
            layout.addWidget(label)
            layout.addStretch()
            missing.show()
            self.app.processEvents()
            fallback = missing.grab().toImage()
            self.assertGreater(fallback.pixelColor(100, 650).red(), 9)
            self.assertLess(fallback.pixelColor(100, 150).red(), 20)
            self.assertEqual(label.palette().window().color().alpha(), 0)
            missing.close()

            fixture = QImage(300, 500, QImage.Format_ARGB32)
            fixture.fill(QColor("#ff5e00"))
            self.assertTrue(fixture.save(str(root / "ember.png")))
            painted = EmberSidebar(asset_path=root / "ember.png")
            painted.resize(220, 700)
            painted.show()
            self.app.processEvents()
            artwork = painted.grab().toImage()
            self.assertGreater(artwork.pixelColor(100, 650).red(), fallback.pixelColor(100, 650).red() + 40)
            self.assertLess(artwork.pixelColor(100, 150).red(), 20)
            painted.close()

    def test_brand_and_all_icons_render_at_multiple_sizes(self):
        """Public painters must produce visible alpha pixels at native UI scales."""
        names = ("chat", "projects", "library", "models", "updates", "settings",
                 "terminal", "search", "plus", "send", "file", "refresh", "folder")
        for size in (16, 32):
            for name in names:
                with self.subTest(size=size, name=name):
                    result = icon(name, color="#ff9d45", size=size).pixmap(size, size).toImage()
                    self.assertFalse(result.isNull())
                    self.assertTrue(any(result.pixelColor(x, y).alpha() > 0
                                        for x in range(result.width()) for y in range(result.height())))
        mark = BrandMark(size=58)
        mark.show()
        self.app.processEvents()
        orb = mark.grab().toImage()
        self.assertTrue(any(orb.pixelColor(x, y).red() > 180 and orb.pixelColor(x, y).green() > 70
                            for x in range(orb.width()) for y in range(orb.height())))
        self.assertEqual(mark.accessibleName(), "CETA")
        mark.close()

    def test_page_and_sidebar_switch_local_scenes_and_reject_unknown_scene(self):
        """Section changes display their own packaged art without changing files."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets").mkdir()
            fixture = QImage(600, 400, QImage.Format_ARGB32)
            for scene, color in (("chat", "#0055ff"), ("projects", "#ff6600")):
                fixture.fill(QColor(color))
                self.assertTrue(fixture.save(str(root / f"assets/{scene}-landscape.png")))
            with patch("ceta_desktop.theme.files", return_value=root):
                for widget in (ScenePage(scene="chat"), EmberSidebar()):
                    widget.resize(600, 400)
                    widget.show()
                    self.app.processEvents()
                    before = widget.grab().toImage().pixelColor(500, 350)
                    widget.set_scene("projects")
                    self.app.processEvents()
                    after = widget.grab().toImage().pixelColor(500, 350)
                    self.assertGreater(before.blue(), before.red())
                    self.assertGreater(after.red(), after.blue())
                    with self.assertRaisesRegex(ValueError, "Unknown CETA scene"):
                        widget.set_scene("unknown")
                    widget.close()

    def test_stylesheet_has_no_qt_parse_warnings_and_invalid_icons_fail_clearly(self):
        messages = []
        previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
        try:
            sidebar = EmberSidebar()
            sidebar.setStyleSheet(APP_STYLESHEET)
            sidebar.ensurePolished()
            sidebar.close()
        finally:
            qInstallMessageHandler(previous)
        self.assertFalse([message for message in messages if "stylesheet" in message.lower() or "unknown property" in message.lower()])
        with self.assertRaisesRegex(ValueError, "Unknown CETA icon"):
            icon("not-an-icon")
        with self.assertRaises(ValueError):
            icon("chat", size=0)
        with self.assertRaises(ValueError):
            icon("chat", color="invalid-color")


if __name__ == "__main__":
    unittest.main()
