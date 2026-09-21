"""Library page: browse, continue, and export saved conversations."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..components import action, filter_list
from ..theme import ScenePage, icon


class LibraryPage(ScenePage):
    """Browse saved local conversations, resume them, or export copies."""

    def __init__(
        self,
        select_conversation: Callable[[QListWidgetItem], None],
        export_conversation: Callable[[str], None],
        navigate_to_projects: Callable[[], None],
        delete_conversation: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(scene="library", parent=parent)
        self.select_conversation = select_conversation
        self.export_conversation = export_conversation
        self.navigate_to_projects = navigate_to_projects
        self.delete_conversation = delete_conversation

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("pageContent")
        content.setAutoFillBackground(False)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        heading = QLabel("Library")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)

        description = QLabel("Pick up a conversation or export a copy. Your saved work stays on this computer.")
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("Find a saved conversation…")
        self.library_search.setAccessibleName("Search library")
        self.library_search.addAction(icon("search"), QLineEdit.LeadingPosition)
        self.library_search.textChanged.connect(self._filter_library)
        layout.addWidget(self.library_search)

        self.library_list = QListWidget()
        self.library_list.setObjectName("conversationList")
        self.library_list.setAccessibleName("Conversation library")
        self.library_list.itemDoubleClicked.connect(self._on_item_double_clicked)

        self.library_empty = QLabel("Your library starts with a conversation.\nSaved chats appear here, ready to continue or export.")
        self.library_empty.setObjectName("emptyBody")
        self.library_empty.setAlignment(Qt.AlignCenter)
        self.library_empty.setWordWrap(True)

        layout.addWidget(self.library_empty, 1)
        layout.addWidget(self.library_list, 1)

        row = QHBoxLayout()
        row.addWidget(action("Continue conversation", self._open_library_conversation, "chat", primary=True))
        row.addWidget(action("Export selected…", self._export_library_conversation, "file"))
        if self.delete_conversation:
            self.delete_button = action("Delete selected", self._delete_library_conversation)
            row.addWidget(self.delete_button)
        row.addStretch()
        row.addWidget(action("Open project files", self.navigate_to_projects, "folder"))
        layout.addLayout(row)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self.select_conversation(item)

    def _open_library_conversation(self) -> None:
        item = self.library_list.currentItem()
        if item:
            self.select_conversation(item)

    def _export_library_conversation(self) -> None:
        item = self.library_list.currentItem()
        if item:
            self.export_conversation(item.data(Qt.UserRole))

    def _delete_library_conversation(self) -> None:
        item = self.library_list.currentItem()
        if item and self.delete_conversation:
            self.delete_conversation(item.data(Qt.UserRole))

    def _filter_library(self, query: str) -> None:
        filter_list(self.library_list, query)
