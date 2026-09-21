from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ceta_desktop.storage import Store


class ConversationLifecycleTests(unittest.TestCase):
    def test_deleting_active_conversation_removes_its_draft_and_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            try:
                removed = store.new_conversation("Remove")
                retained = store.new_conversation("Retain")
                store.add_message(removed, "user", "Removed message")
                store.add_message(retained, "user", "Retained message")
                store.set_setting("active_conversation", removed)
                store.set_setting("chat_draft:" + removed, "Removed draft")
                store.set_setting("chat_draft:" + retained, "Retained draft")
                store.set_setting("chat_draft:new", "New conversation draft")

                store.delete_conversation(removed)

                self.assertEqual(store.messages(removed), [])
                self.assertIsNone(store.setting("chat_draft:" + removed))
                self.assertIsNone(store.setting("active_conversation"))
                self.assertEqual(store.setting("chat_draft:" + retained), "Retained draft")
                self.assertEqual(store.setting("chat_draft:new"), "New conversation draft")
                self.assertEqual(store.messages(retained)[0]["content"], "Retained message")
            finally:
                store.close()

    def test_deleting_another_conversation_preserves_active_selection_and_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            try:
                active = store.new_conversation("Active")
                removed = store.new_conversation("Remove")
                store.set_setting("active_conversation", active)
                store.set_setting("chat_draft:" + active, "Active draft")
                store.set_setting("chat_draft:" + removed, "Removed draft")

                store.delete_conversation(removed)

                self.assertEqual(store.setting("active_conversation"), active)
                self.assertEqual(store.setting("chat_draft:" + active), "Active draft")
                self.assertIsNone(store.setting("chat_draft:" + removed))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
