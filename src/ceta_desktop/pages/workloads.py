"""Workloads page: audit history of executed workspace commands."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from ..components import action
from ..storage import Store
from ..theme import ScenePage


class WorkloadsPage(ScenePage):
    """Review recorded commands, their exit status, and saved output."""

    def __init__(self, store: Store, navigate_to_projects: Callable[[], None], parent: QWidget | None = None):
        super().__init__(scene="workloads", parent=parent)
        self.store = store
        self.navigate_to_projects = navigate_to_projects

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

        heading = QLabel("Workloads")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)

        description = QLabel("A record of the commands you ran, their results, and what happened next.")
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addWidget(action("Go to project terminal", self.navigate_to_projects, "terminal"), 0, Qt.AlignLeft)

        splitter = QSplitter(Qt.Vertical)
        self.workload_history = QListWidget()
        self.workload_history.setAccessibleName("Workload history")
        self.workload_history.currentItemChanged.connect(self._select_workload)
        splitter.addWidget(self.workload_history)

        self.history_output = QPlainTextEdit()
        self.history_output.setReadOnly(True)
        self.history_output.setFont(QFont("Cascadia Mono", 10))
        self.history_output.setPlaceholderText("Select a command to inspect its saved output. Start commands from Projects.")
        splitter.addWidget(self.history_output)
        splitter.setSizes([260, 450])
        layout.addWidget(splitter, 1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _select_workload(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if item:
            record = item.data(Qt.UserRole)
            if record:
                self.history_output.setPlainText(
                    f"Workspace: {record['workspace']}\n"
                    f"Command: {record['command']}\n"
                    f"Status: {record['status']}\n"
                    f"Exit: {record['exit_code']}\n\n"
                    f"{record['output']}"
                )

    def load_workloads(self) -> None:
        self.workload_history.clear()
        for record in self.store.workloads():
            self.workload_history.addItem(f"{record['status']} · {record['command'][:100]}")
            self.workload_history.item(self.workload_history.count() - 1).setData(Qt.UserRole, record)
