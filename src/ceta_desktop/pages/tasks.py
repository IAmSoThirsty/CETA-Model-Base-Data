from __future__ import annotations

import json
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from ..components import action


class TasksPanel(QWidget):
    """Reviewable controls for the active project task and its recorded results."""

    def __init__(self, owner):
        super().__init__()
        self.displayed_scope = None
        layout = QVBoxLayout(self)
        self.scope = QLabel("Open a project, or start an application conversation.")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        row = QHBoxLayout()
        self.task_selector = QComboBox()
        self.task_selector.setAccessibleName("Project task")
        self.task_selector.currentIndexChanged.connect(owner.select_project_task)
        row.addWidget(self.task_selector, 1)
        row.addWidget(action("Use conversation for task", owner.bind_current_conversation))
        layout.addLayout(row)
        self.access_status = QLabel("Task access has not been inspected.")
        self.access_status.setWordWrap(True)
        layout.addWidget(self.access_status)
        recovery_row = QHBoxLayout()
        self.resume_button = action("Resume task", owner.resume_task_access)
        self.resume_button.setEnabled(False)
        recovery_row.addWidget(self.resume_button)
        recovery_row.addWidget(action("Inspect recovery", owner.show_task_recovery))
        self.recovery_action = QComboBox()
        self.recovery_action.setAccessibleName("Uncertain operation")
        recovery_row.addWidget(self.recovery_action, 1)
        recovery_row.addWidget(action("Recheck edit outcome", owner.recheck_edit_outcome))
        layout.addLayout(recovery_row)
        objective_row = QHBoxLayout()
        self.objective = QLineEdit()
        self.objective.setPlaceholderText("What should this task accomplish?")
        self.objective.setAccessibleName("Task objective")
        objective_row.addWidget(self.objective, 1)
        objective_row.addWidget(action("Start task", owner.start_project_task))
        layout.addLayout(objective_row)
        inspect_row = QHBoxLayout()
        inspect_row.addWidget(action("Inspect project", owner.inspect_project_task))
        inspect_row.addWidget(action("Current context", owner.show_task_context))
        inspect_row.addWidget(action("Timeline", owner.show_task_timeline))
        inspect_row.addWidget(action("Import historical log…", owner.import_historical_log))
        inspect_row.addStretch()
        layout.addLayout(inspect_row)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search project code")
        self.search.setAccessibleName("Search project code")
        self.search.returnPressed.connect(owner.search_project_task)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(action("Search", owner.search_project_task))
        layout.addLayout(search_row)
        edit_row = QHBoxLayout()
        edit_row.addWidget(action("Review editor diff", owner.review_editor_edit))
        self.apply_button = action("Apply reviewed edit", owner.apply_reviewed_edit)
        self.apply_button.setEnabled(False)
        edit_row.addWidget(self.apply_button)
        edit_row.addStretch()
        layout.addLayout(edit_row)
        self.result_title = QLabel("Task results")
        layout.addWidget(self.result_title)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setAccessibleName("Task results and evidence")
        self.results.setPlaceholderText("Inspect, search or open the timeline to see recorded task results.")
        layout.addWidget(self.results, 1)

    def set_tasks(self, records, selected):
        self.task_selector.blockSignals(True)
        self.task_selector.clear()
        for row in records:
            self.task_selector.addItem(row["objective"] + " · " + row["status"], row["task_id"])
        index = self.task_selector.findData(selected)
        self.task_selector.setCurrentIndex(index)
        self.task_selector.blockSignals(False)

    def show_result(self, title, result):
        self.result_title.setText(title)
        self.results.setPlainText(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    def show_diff(self, diff):
        self.result_title.setText("Review this diff before choosing Apply reviewed edit")
        self.results.setPlainText(diff or "No file content changes.")

    def show_error(self, message):
        self.result_title.setText("Action did not complete")
        self.results.setPlainText(message)
