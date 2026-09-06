"""Native navigation integration with isolated data and mocked model discovery."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPlainTextEdit, QPushButton

    from ceta_desktop.app import MainWindow


@unittest.skipUnless(HAS_QT, "Desktop extra is required for native navigation tests")
class DesktopNavigationTests(unittest.TestCase):
    """Verify controls through actual Qt signals without starting local runtimes."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data = self.root / "app-data"
        self.window = MainWindow(self.data)
        self.window.show()
        self._settle()

    def tearDown(self):
        self._close_window()

    def _settle(self):
        for _ in range(3):
            self.app.processEvents()
            QTest.qWait(10)

    def _close_window(self):
        if self.window is not None:
            self.window.editor.document().setModified(False)
            self.assertTrue(self.window.close())
            self.window.deleteLater()
            self.window = None
            self._settle()

    def _button(self, text):
        matches = [control for control in self.window.findChildren(QPushButton)
                   if control.text() == text]
        self.assertEqual(len(matches), 1, text)
        return matches[0]

    def _item(self, listing, identifier):
        matches = [listing.item(index) for index in range(listing.count())
                   if listing.item(index).data(Qt.ItemDataRole.UserRole) == identifier]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def _visible_ids(self, listing):
        return {listing.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(listing.count()) if not listing.item(index).isHidden()}

    def _seed_conversations(self):
        first = self.window.store.new_conversation("Alpha coding plan")
        second = self.window.store.new_conversation("Beta writing plan")
        for identifier, text in ((first, "Actual stored alpha fixture"),
                                 (second, "Actual stored beta fixture")):
            self.window.store.add_message(identifier, "user", text)
            self.window.store.add_message(identifier, "assistant", "Saved reply: " + text)
        self.window._load_conversations()
        self.window._select_conversation(self._item(self.window.conversation_list, first))
        return first, second

    def _discover_models(self, names):
        with patch("ceta_desktop.app.LocalModelClient", autospec=True) as client:
            client.return_value.available_models.return_value = names
            with patch.object(
                self.window, "_background",
                side_effect=lambda operation, loaded, _failed=None: loaded(operation(None)),
            ):
                self.window.refresh_models()
            client.return_value.available_models.assert_called_once_with()
        self._settle()

    def test_all_seven_pages_and_their_scenes_are_reachable_by_navigation(self):
        """Each visible navigation entry opens its own page and sidebar scene."""
        names = ("Chat", "Projects", "Library", "Models", "Workloads", "Updates", "Settings")
        self.assertEqual(self.window.navigation.count(), len(names))
        self.assertEqual(self.window.pages.count(), len(names))
        with patch("ceta_desktop.app.LocalModelClient", autospec=True) as client:
            for index, name in enumerate(names):
                with self.subTest(page=name):
                    item = self.window.navigation.item(index)
                    self.assertEqual(item.text(), name)
                    QTest.mouseClick(
                        self.window.navigation.viewport(), Qt.MouseButton.LeftButton,
                        pos=self.window.navigation.visualItemRect(item).center(),
                    )
                    self._settle()
                    self.assertEqual(self.window.pages.currentIndex(), index)
                    self.assertTrue(self.window.pages.currentWidget().isVisible())
                    self.assertEqual(self.window.pages.currentWidget()._scene, name.lower())
                    self.assertEqual(self.window.sidebar._scene, name.lower())
            client.assert_not_called()

    def test_model_choices_synchronize_in_all_three_directions(self):
        """Header, composer and Models share discovered choices and editable selection."""
        names = ["fixture-local-alpha", "fixture-local-beta", "fixture-local-gamma"]
        self._discover_models(names)
        selectors = (self.window.model_combo, self.window.chat_model_combo,
                     self.window.composer_model_combo)
        for selector in selectors:
            self.assertEqual([selector.itemText(i) for i in range(selector.count())], names)
        for source, selected in zip(selectors, names, strict=True):
            with self.subTest(source=source.accessibleName()):
                source.setCurrentIndex(names.index(selected))
                self._settle()
                self.assertEqual([selector.currentText() for selector in selectors], [selected] * 3)
        self.window.composer_model_combo.lineEdit().setText("fixture-manually-entered")
        self.assertEqual([selector.currentText() for selector in selectors],
                         ["fixture-manually-entered"] * 3)

    def test_model_refresh_preserves_available_selection_in_every_control(self):
        """Refreshing a reordered list must not silently select a different model."""
        self._discover_models(["fixture-alpha", "fixture-beta"])
        self.window.chat_model_combo.setCurrentText("fixture-beta")
        self._discover_models(["fixture-gamma", "fixture-beta", "fixture-alpha"])
        for selector in (self.window.model_combo, self.window.chat_model_combo,
                         self.window.composer_model_combo):
            self.assertEqual(selector.currentText(), "fixture-beta")

    def test_search_hides_only_nonmatches_without_changing_saved_content(self):
        """Chat and Library searches are independent views of the same stored records."""
        first, second = self._seed_conversations()
        before = {identifier: self.window.store.messages(identifier)
                  for identifier in (first, second)}
        self.window.prompt.setPlainText("Unsent alpha draft")
        self.window.conversation_search.setText("ALPHA")
        self.assertEqual(self._visible_ids(self.window.conversation_list), {first})
        self.assertEqual(self._visible_ids(self.window.library_list), {first, second})
        self.window.library_search.setText("bEtA")
        self.assertEqual(self._visible_ids(self.window.library_list), {second})
        self.assertEqual(self._visible_ids(self.window.conversation_list), {first})
        self.window.conversation_search.setText("no matching conversation")
        self.assertEqual(self._visible_ids(self.window.conversation_list), set())
        self.assertEqual(self.window.conversation_id, first)
        self.assertEqual(self.window.prompt.toPlainText(), "Unsent alpha draft")
        self.window.conversation_search.clear()
        self.window.library_search.clear()
        self.assertEqual(self._visible_ids(self.window.conversation_list), {first, second})
        self.assertEqual(self._visible_ids(self.window.library_list), {first, second})
        self.assertEqual({identifier: self.window.store.messages(identifier)
                          for identifier in (first, second)}, before)

    def test_selecting_search_results_preserves_each_conversation_draft(self):
        """Switching through filtered chat rows restores the corresponding unsent text."""
        first, second = self._seed_conversations()
        self.window.prompt.setPlainText("Draft belonging to alpha")
        for identifier, query, expected, new_draft in (
            (second, "beta", "", "Draft belonging to beta"),
            (first, "alpha", "Draft belonging to alpha", "Draft belonging to alpha"),
            (second, "beta", "Draft belonging to beta", "Draft belonging to beta"),
        ):
            self.window.conversation_search.setText(query)
            self._settle()
            item = self._item(self.window.conversation_list, identifier)
            QTest.mouseClick(
                self.window.conversation_list.viewport(), Qt.MouseButton.LeftButton,
                pos=self.window.conversation_list.visualItemRect(item).center(),
            )
            self.assertEqual(self.window.conversation_id, identifier)
            self.assertEqual(self.window.prompt.toPlainText(), expected)
            self.assertEqual(self.window.store.setting("active_conversation"), identifier)
            self.window.prompt.setPlainText(new_draft)

    def test_library_continue_opens_selected_conversation_and_retains_active_draft(self):
        """Continue uses the Library selection even when a different chat is active."""
        first, second = self._seed_conversations()
        self.window.prompt.setPlainText("Retained alpha draft")
        self.window.store.set_setting("chat_draft:" + second, "Restored beta draft")
        self.window.navigation.setCurrentRow(2)
        self.window.library_list.setCurrentItem(self._item(self.window.library_list, second))
        self._settle()
        QTest.mouseClick(self._button("Continue conversation"), Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.conversation_id, second)
        self.assertEqual(self.window.pages.currentIndex(), 0)
        self.assertEqual(self.window.prompt.toPlainText(), "Restored beta draft")
        self.assertEqual(self.window.store.setting("chat_draft:" + first), "Retained alpha draft")
        self.assertIn("Actual stored beta fixture", self.window.chat_view.toPlainText())
        self.assertNotIn("Actual stored alpha fixture", self.window.chat_view.toPlainText())

    def test_library_export_uses_selected_id_and_refuses_overwrite(self):
        """Export writes only the selected transcript and preserves an existing destination."""
        first, second = self._seed_conversations()
        self.window.prompt.setPlainText("Unsent active draft stays local")
        self.window.navigation.setCurrentRow(2)
        self.window.library_list.setCurrentItem(self._item(self.window.library_list, second))
        self._settle()
        destination = self.root / "selected-transcript.json"
        with patch("ceta_desktop.app.QFileDialog.getSaveFileName",
                   return_value=(str(destination), "JSON (*.json)")) as dialog:
            QTest.mouseClick(self._button("Export selected…"), Qt.MouseButton.LeftButton)
            dialog.assert_called_once()
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")),
                         self.window.store.messages(second))
        self.assertEqual(self.window.conversation_id, first)
        self.assertEqual(self.window.prompt.toPlainText(), "Unsent active draft stays local")
        existing = destination.read_bytes()
        with patch("ceta_desktop.app.QFileDialog.getSaveFileName",
                   return_value=(str(destination), "JSON (*.json)")), \
                patch.object(self.window, "_error") as error:
            QTest.mouseClick(self._button("Export selected…"), Qt.MouseButton.LeftButton)
            error.assert_called_once()
            self.assertIsInstance(error.call_args.args[0], FileExistsError)
        self.assertEqual(destination.read_bytes(), existing)
        with patch("ceta_desktop.app.QFileDialog.getSaveFileName", return_value=("", "")), \
                patch.object(self.window, "_error") as error:
            QTest.mouseClick(self._button("Export selected…"), Qt.MouseButton.LeftButton)
            error.assert_not_called()
        self.assertEqual(destination.read_bytes(), existing)

    def test_editor_font_size_and_wrap_apply_and_persist_across_restart(self):
        """Preferences must affect the actual editor and survive closing and reopening."""
        self.window.navigation.setCurrentRow(6)
        self.window.editor_font_size.setValue(18)
        self.window.editor_wrap.setChecked(True)
        self._settle()
        self.assertEqual(self.window.editor.font().pointSize(), 18)
        self.assertEqual(self.window.editor.lineWrapMode(), QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.assertEqual(self.window.store.setting("editor_font_size"), 18)
        self.assertIs(self.window.store.setting("editor_wrap"), True)
        self._close_window()
        self.window = MainWindow(self.data)
        self.window.show()
        self._settle()
        self.assertEqual(self.window.editor_font_size.value(), 18)
        self.assertTrue(self.window.editor_wrap.isChecked())
        self.assertEqual(self.window.editor.font().pointSize(), 18)
        self.assertEqual(self.window.editor.lineWrapMode(), QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.window.editor_wrap.setChecked(False)
        self.assertEqual(self.window.editor.lineWrapMode(), QPlainTextEdit.LineWrapMode.NoWrap)


if __name__ == "__main__":
    unittest.main()
