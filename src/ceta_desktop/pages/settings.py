"""Settings page: user preferences, local data location, and keyboard shortcuts."""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QMessageBox,
    QCheckBox, QFormLayout, QFrame, QLabel, QLineEdit, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..components import action, card
from ..storage import Store
from ..theme import ScenePage


class SettingsPage(ScenePage):
    """Preferences saved on this computer."""

    preferences_changed = Signal(int, bool)

    def __init__(self, store: Store, parent: QWidget | None = None, *, application_runner=None):
        super().__init__(scene="settings", parent=parent)
        self.store = store
        self.application_runner = application_runner

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("pageContent")
        content.setAutoFillBackground(False)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        heading = QLabel("Settings")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)

        description = QLabel("Make CETA feel at home. These preferences are saved on this computer.")
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(description)

        editor_card, editor_layout = card("Editor preferences")
        form = QFormLayout()
        self.editor_font_size = QSpinBox()
        self.editor_font_size.setRange(10, 22)
        saved_size = self.store.setting("editor_font_size", 11)
        self.editor_font_size.setValue(saved_size if type(saved_size) is int and 10 <= saved_size <= 22 else 11)
        self.editor_font_size.setSuffix(" pt")
        form.addRow("Code font size", self.editor_font_size)

        self.editor_wrap = QCheckBox("Wrap long lines in the editor")
        self.editor_wrap.setChecked(self.store.setting("editor_wrap", False) is True)
        form.addRow("Line wrapping", self.editor_wrap)
        editor_layout.addLayout(form)

        self.editor_font_size.valueChanged.connect(self._save_editor_preferences)
        self.editor_wrap.toggled.connect(self._save_editor_preferences)
        layout.addWidget(editor_card)

        privacy, privacy_layout = card(
            "Local data & privacy",
            "Conversations, drafts, command history, and settings are kept in your local application data. "
            "Task conversations include project state and applicable instructions; file excerpts are explicitly selected."
        )
        path = QLineEdit(str(self.store.directory))
        path.setReadOnly(True)
        path.setAccessibleName("CETA application data folder")
        privacy_layout.addWidget(path)
        privacy_layout.addWidget(
            action("Open data folder", self.open_data_folder, "folder"),
            0, Qt.AlignLeft
        )
        note = QLabel(
            "Local storage uses your Windows account's file permissions. Export conversations only when you choose to share them. "
            "Review separately started model runtimes' privacy settings before connecting."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        privacy_layout.addWidget(note)
        layout.addWidget(privacy)

        shortcuts, shortcut_layout = card("Keyboard shortcuts")
        shortcut_layout.addWidget(
            QLabel(
                "Ctrl+N  New chat     ·     Ctrl+O  Open workspace     ·     Ctrl+S  Save file\n"
                "Ctrl+F  Find in file     ·     Ctrl+Shift+N  New file     ·     Ctrl+Shift+E  Export chat"
            )
        )
        layout.addWidget(shortcuts)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def open_data_folder(self):
        try:
            if self.application_runner is None:
                raise ValueError("Application authority is unavailable for this operation.")
            opened = self.application_runner("notice.open", {"path": str(self.store.directory), "purpose": "application_data"},
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.directory))))
            if opened is False:
                raise RuntimeError("The system did not open the application data folder.")
        except (ValueError, OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Could not open data folder", str(exc))

    def _save_editor_preferences(self, *_):
        size = self.editor_font_size.value()
        wrap = self.editor_wrap.isChecked()
        self.store.set_setting("editor_font_size", size)
        self.store.set_setting("editor_wrap", wrap)
        self.preferences_changed.emit(size, wrap)

    @property
    def font_size(self) -> int:
        return self.editor_font_size.value()

    @property
    def line_wrap(self) -> bool:
        return self.editor_wrap.isChecked()
