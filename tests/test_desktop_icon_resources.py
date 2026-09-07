"""Exercise the release icon gate against real Windows executable resources."""
from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_desktop import installer_script
from desktop_icon_resources import uninstaller_icon_finalize, verify_pe_icons
from desktop_icons import create_windows_icon


@unittest.skipUnless(os.name == "nt", "Windows PyInstaller executable resources")
class DesktopIconResourceTests(unittest.TestCase):
    def setUp(self):
        import PyInstaller
        from PyInstaller.config import CONF
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(CONF, {"workpath": str(self.root)}))
        self.icon = create_windows_icon(ROOT / "src/ceta_desktop/icon.svg", self.root / "CETA.ico")
        self.executable = self.root / "CETA.exe"
        loader = Path(PyInstaller.__file__).parent / "bootloader" / PyInstaller.PLATFORM / "runw.exe"
        shutil.copyfile(loader, self.executable)

    def test_generic_executable_is_rejected_and_complete_ceta_resources_pass(self):
        from PyInstaller.utils.win32.icon import CopyIcons
        with self.assertRaises(ValueError):
            verify_pe_icons(self.executable, self.icon)
        CopyIcons(str(self.executable), [str(self.icon)])
        report = verify_pe_icons(self.executable, self.icon)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual({frame["size"] for frame in report["frames"]},
                         {16, 20, 24, 32, 40, 48, 64, 128, 256})
        self.assertEqual(next(frame["encoding"] for frame in report["frames"] if frame["size"] == 256), "PNG")

    def test_correct_sizes_with_wrong_artwork_are_rejected(self):
        from PyInstaller.utils.win32.icon import CopyIcons
        other_svg = self.root / "different.svg"
        other_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">'
                             '<rect width="256" height="256" fill="blue"/></svg>', encoding="utf-8")
        other_icon = create_windows_icon(other_svg, self.root / "different.ico")
        CopyIcons(str(self.executable), [str(other_icon)])
        with self.assertRaisesRegex(ValueError, "differs"):
            verify_pe_icons(self.executable, self.icon)

    def test_nsis_uses_custom_icons_before_modern_ui_macros(self):
        hook = uninstaller_icon_finalize(self.icon, self.root / "uninstaller-icons.json")
        script = installer_script(self.root, self.root / "setup.exe", "0.3.3",
                                  icon_path=self.icon, icon_check=hook)
        for define in ("MUI_ICON", "MUI_UNICON"):
            self.assertIn(f'!define {define} "{self.icon}"', script)
            self.assertLess(script.index(f"!define {define}"), script.index("!insertmacro MUI_PAGE"))
        self.assertIn(hook, script)
        self.assertIn('"DisplayIcon" \'$\\"$INSTDIR\\CETA.exe$\\",0\'', script)
        self.assertIn('CreateShortcut "$SMPROGRAMS\\CETA.lnk" "$INSTDIR\\CETA.exe" "" "$INSTDIR\\CETA.exe" 0', script)

    def test_uninstaller_icon_gate_preserves_separate_signing_hook(self):
        hook = uninstaller_icon_finalize(self.icon, self.root / "uninstaller-icons.json")
        signing_hook = '!uninstfinalize "independent signing fixture" = 0'
        script = installer_script(self.root, self.root / "setup.exe", "0.3.3", signing_hook, icon_check=hook)
        self.assertIn(hook, script)
        self.assertIn(signing_hook, script)
        self.assertTrue(hook.endswith(" = 0"))
        with self.assertRaises(ValueError):
            uninstaller_icon_finalize(self.root / "%EXPANSION%.ico", self.root / "report.json")


if __name__ == "__main__":
    unittest.main()
