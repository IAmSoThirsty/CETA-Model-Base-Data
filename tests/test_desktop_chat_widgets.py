"""Native transcript behavior, plain-text boundaries, copying and scrolling."""

from __future__ import annotations

import copy
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton

    from ceta_desktop.chat_widgets import ChatTranscript, _segments


@unittest.skipUnless(HAS_QT, "Desktop extra is required for native UI tests")
class DesktopChatWidgetTests(unittest.TestCase):
    """Exercise isolated chat widgets without models, files or network access."""
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = ChatTranscript()
        self.widget.resize(800, 500)
        self.widget.show()
        QTest.qWait(20)

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        QTest.qWait(20)

    def render(self, messages, **kwargs):
        self.widget.render_messages(messages, **kwargs)
        # Layout requests and scrollbar updates arrive in separate Qt event turns.
        for _ in range(4):
            self.app.processEvents()
            QTest.qWait(10)

    def test_empty_state_has_no_invented_conversation(self):
        self.assertEqual(
            self.widget.toPlainText(),
            "A place to think and build.\n\nConnect a local model to start a conversation. "
            "Your workspace is never attached automatically.",
        )
        self.assertEqual(len(self.widget.findChildren(QPushButton)), 0)

    def test_untrusted_markup_and_model_name_are_literal_plain_text(self):
        content = '<script>alert(1)</script>\n<img src="https://invalid.test/a"> & <b>plain</b>'
        model = '<a href="file:///secret">model</a>'
        self.render([{"role": "assistant", "content": content}], model_name=model)
        self.assertIn(content, self.widget.toPlainText())
        label = self.widget.findChild(QLabel, "messageText")
        self.assertEqual(label.text(), content)
        for label in self.widget.findChildren(QLabel):
            self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)
            self.assertFalse(label.openExternalLinks())
        self.assertIn(model, self.widget.findChild(QLabel, "senderLabel").text())

    def test_fences_preserve_code_and_streaming_unclosed_fence(self):
        self.assertEqual(
            _segments("Before `inline`\n````python\n```\n<img>\n````\nAfter"),
            [("text", "Before `inline`\n", ""), ("code", "```\n<img>\n", "python"),
             ("text", "After", "")],
        )
        self.assertEqual(_segments("~~~sh\nprintf 'hello'\n"),
                         [("code", "printf 'hello'\n", "sh")])

    def test_clipboard_changes_only_on_explicit_copy_and_preserves_code(self):
        clipboard = self.app.clipboard()
        old_text = clipboard.text()
        try:
            clipboard.setText("untouched sentinel")
            code = 'print("<script>")\r\n  # exact spacing\r\n'
            content = "Example:\n```python\r\n" + code + "```"
            self.render([{"role": "assistant", "content": content}])
            self.assertEqual(clipboard.text(), "untouched sentinel")
            self.assertIn(content, self.widget.toPlainText())
            editor = self.widget.findChild(QPlainTextEdit, "codeText")
            self.assertTrue(editor.isReadOnly())
            self.assertIn('<script>', editor.toPlainText())
            button = self.widget.findChild(QPushButton, "copyCodeButton")
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.assertEqual(clipboard.text(), code)
        finally:
            clipboard.setText(old_text)

    def test_pending_message_replaces_generating_row_without_changing_input(self):
        records = [
            {"role": "user", "content": "Question", "status": "complete"},
            {"role": "assistant", "content": "stored partial", "status": "generating"},
        ]
        before = copy.deepcopy(records)
        self.render(records, pending_text="Current streamed text")
        plain = self.widget.toPlainText()
        self.assertEqual(plain.count("Assistant"), 1)
        self.assertIn("Current streamed text", plain)
        self.assertNotIn("stored partial", plain)
        self.assertEqual(records, before)

    def test_only_latest_200_messages_are_rendered(self):
        self.render([{"role": "user", "content": f"Message[{i}]"} for i in range(205)])
        plain = self.widget.toPlainText()
        self.assertNotIn("Message[4]", plain)
        self.assertIn("Message[5]", plain)
        self.assertIn("Message[204]", plain)
        self.assertEqual(len(self.widget.findChildren(QLabel, "messageText")), 200)

    def test_unchanged_messages_keep_widgets_and_code_selection(self):
        records = [{"role": "assistant", "content": "```python\nprint('hello')\n```"}]
        self.render(records)
        editor = self.widget.findChild(QPlainTextEdit, "codeText")
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cursor)
        selection = editor.textCursor().selectedText()
        self.render(records)
        self.assertIs(self.widget.findChild(QPlainTextEdit, "codeText"), editor)
        self.assertEqual(editor.textCursor().selectedText(), selection)
        self.render(records + [{"role": "user", "content": "Next question"}])
        self.assertIs(self.widget.findChild(QPlainTextEdit, "codeText"), editor)
        self.assertEqual(editor.textCursor().selectedText(), selection)

    def test_streaming_code_keeps_the_existing_code_panel(self):
        self.render([], pending_text="```python\nprint(")
        editor = self.widget.findChild(QPlainTextEdit, "codeText")
        self.render([], pending_text="```python\nprint('complete')\n```")
        self.assertIs(self.widget.findChild(QPlainTextEdit, "codeText"), editor)
        self.assertEqual(editor.toPlainText(), "print('complete')\n")

    def test_scroll_position_is_preserved_and_tail_follows_when_at_bottom(self):
        records = [{"role": "user", "content": f"Message {i}\n" + "Line\n" * 5}
                   for i in range(30)]
        self.render(records)
        bar = self.widget.verticalScrollBar()
        self.assertGreater(bar.maximum(), 500)
        self.assertEqual(bar.value(), bar.maximum())
        anchor = bar.maximum() // 3
        bar.setValue(anchor)
        self.render(records, pending_text="A streamed answer\n" * 15)
        self.assertEqual(bar.value(), anchor)
        self.render(records, pending_text="A longer streamed answer\n" * 25)
        self.assertEqual(bar.value(), anchor)
        bar.setValue(bar.maximum())
        self.render(records, pending_text="An even longer answer\n" * 35)
        self.assertEqual(bar.value(), bar.maximum())

    def test_only_real_parseable_timestamps_are_shown(self):
        self.render([
            {"role": "user", "content": "Timestamp", "created_at": "2026-09-06T10:12:00"},
            {"role": "assistant", "content": "No timestamp"},
            {"role": "assistant", "content": "Invalid", "created": "not-a-date"},
        ])
        self.assertEqual(self.widget.toPlainText().count("2026-09-06 10:12"), 1)
        shown = [label.text() for label in self.widget.findChildren(QLabel, "messageMeta")
                 if not label.isHidden()]
        self.assertEqual(shown, ["2026-09-06 10:12"])

    def test_empty_generating_message_has_truthful_status(self):
        self.render([{"role": "assistant", "content": "", "status": "generating"}])
        self.assertIn("Assistant · generating", self.widget.toPlainText())
        self.assertNotIn("A place to think", self.widget.toPlainText())
        self.assertEqual(self.widget.findChild(QLabel, "messageMeta").text(), "generating")

    def test_returning_to_empty_state_removes_old_messages(self):
        self.render([{"role": "user", "content": "Old question"}])
        self.render([])
        self.assertNotIn("Old question", self.widget.toPlainText())
        self.assertEqual(self.widget.findChildren(QLabel, "messageText"), [])
        self.assertFalse(self.widget.findChild(QLabel, "emptyHeading").isHidden())


if __name__ == "__main__":
    unittest.main()
