from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime
from uuid import uuid4

from PySide6.QtCore import QDir, QSize, QLockFile, QProcess, QProcessEnvironment, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QIcon, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QFileDialog, QFileSystemModel, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QSplitter, QStackedWidget, QTabWidget, QTreeView,
    QVBoxLayout, QWidget,
)

from . import __version__
from .models import LocalModelClient, ModelPacks
from .hardware import (
    ModelOption, assess_model, assess_models, format_hardware,
    inspect_hardware, local_model_option, recommended_model,
)
from .storage import Store, application_directory
from .workspace import Document, Workspace
from .instance import open_application_marker, close_application_marker
from .installation import launch_verified_update
from .editor import CodeEditor
from .theme import APP_STYLESHEET, BrandMark, EmberSidebar, ScenePage, icon
from .chat_widgets import ChatTranscript
from .components import action, card, filter_list, page
from .pages.library import LibraryPage
from .pages.settings import SettingsPage
from .pages.updates import UpdatesPage
from .pages.workloads import WorkloadsPage
from .pages.tasks import TasksPanel
from runtime.tasks import TaskRuntime
from runtime.model_provider import LocalProvider


class BackgroundTask(QThread):
    result = Signal(object)
    failed = Signal(str)
    token = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancelled = threading.Event()

    def run(self):
        try:
            self.result.emit(self.function(self))
        except Exception as exc:
            self.failed.emit(str(exc))



class MainWindow(QMainWindow):
    def __init__(self, directory: Path):
        super().__init__()
        self.store = Store(directory)
        self.task_runtime = TaskRuntime(directory)
        self.task_runtime.recover_interrupted()
        self.project_id = None
        self.task_id = None
        self.workload_task = None
        self.pending_edit = None
        self.packs = ModelPacks(directory)
        self.workspace: Workspace | None = None
        self.document: Document | None = None
        self.conversation_id: str | None = None
        self.chat_task: BackgroundTask | None = None
        self.tasks: list[BackgroundTask] = []
        self.client: LocalModelClient | None = None
        self.assistant_text = ""
        self.response_sequence = None
        self.update_task = None
        self.downloaded_update = None
        self.pending_update = None
        self.workload_id = None
        self.workload_output = ""
        self.workload_chunks: list[str] = []
        self.workload_bytes = 0
        self.workload_cancelled = False
        self.pack_download_client = None
        self.hardware_profile = None
        self.hardware_check_running = False
        self.model_probe_running = False
        self.model_action_id = None
        self.model_start_pending = False
        self.pending_model_observations = []
        self.model_process = QProcess(self)
        self.model_process.setProcessChannelMode(QProcess.MergedChannels)
        self.model_process.readyReadStandardOutput.connect(self._model_output)
        self.model_process.started.connect(self._model_started)
        self.model_process.errorOccurred.connect(self._model_error)
        self.model_process.finished.connect(self._model_finished)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._workload_output)
        self.process.finished.connect(self._workload_finished)
        self.process.errorOccurred.connect(self._workload_error)
        self.setWindowTitle(f"CETA · {__version__}")
        self.setWindowIcon(QIcon(str(files("ceta_desktop").joinpath("icon.svg"))))
        self.resize(1540, 940)
        self.setMinimumSize(1100, 720)
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.timeout.connect(self._save_editor_draft)
        self.prompt_timer = QTimer(self)
        self.prompt_timer.setSingleShot(True)
        self.prompt_timer.timeout.connect(self._save_prompt_draft)
        self.chat_render_timer = QTimer(self)
        self.chat_render_timer.setSingleShot(True)
        self.chat_render_timer.timeout.connect(self._render_chat)
        self.response_timer = QTimer(self)
        self.response_timer.setInterval(500)
        self.response_timer.timeout.connect(self._save_response_progress)
        self._build_ui()
        self.conversation_id = self.store.setting("active_conversation")
        self._load_conversations()
        self._restore_prompt_draft()
        self._load_packs()
        self._load_workloads()
        saved_workspace = self.store.setting("workspace")
        if saved_workspace and Path(saved_workspace).is_dir():
            self._set_workspace(Path(saved_workspace))
        self.statusBar().showMessage("Ready · Conversations are saved on this computer")
        self._restore_editor_draft()

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("appShell")
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = EmberSidebar()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(222)
        rail = QVBoxLayout(sidebar)
        rail.setContentsMargins(16, 24, 16, 20)
        rail.setSpacing(24)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        brand_row.addWidget(BrandMark(size=57))
        brand_text = QVBoxLayout()
        brand_text.setSpacing(3)
        name = QLabel("CETA")
        name.setObjectName("brandName")
        brand_text.addWidget(name)
        tagline = QLabel("LOCAL INTELLIGENCE.\nUSER SOVEREIGNTY.")
        tagline.setObjectName("brandTagline")
        brand_text.addWidget(tagline)
        brand_row.addLayout(brand_text)
        rail.addLayout(brand_row)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setAccessibleName("CETA navigation")
        self.navigation.setIconSize(QSize(22, 22))
        self.navigation.setSpacing(5)
        for name, symbol in (("Chat", "chat"), ("Projects", "projects"), ("Library", "library"),
                             ("Models", "models"), ("Workloads", "terminal"),
                             ("Updates", "updates"), ("Settings", "settings")):
            item = QListWidgetItem(icon(symbol), name)
            item.setSizeHint(QSize(180, 47))
            self.navigation.addItem(item)
        rail.addWidget(self.navigation, 1)
        motto = QLabel("Your data.\nYour machine.\nYour intelligence.")
        motto.setObjectName("sidebarMotto")
        rail.addWidget(motto)
        footing = QLabel("A MORE SOVEREIGN\nTOMORROW.")
        footing.setObjectName("brandTagline")
        rail.addWidget(footing)
        self.library_page = LibraryPage(
            self._select_conversation,
            self._export_conversation_id,
            lambda: self.navigation.setCurrentRow(1),
            self.delete_conversation,
        )
        self.library_list = self.library_page.library_list
        self.library_empty = self.library_page.library_empty
        self.library_list.currentItemChanged.connect(self._library_selection_changed)
        self.library_search = self.library_page.library_search

        self.workloads_page = WorkloadsPage(
            self.store,
            lambda: self.navigation.setCurrentRow(1),
        )
        self.workload_history = self.workloads_page.workload_history
        self.history_output = self.workloads_page.history_output

        self.updates_page = UpdatesPage(self._background, self._has_active_work, self.install_update,
                                        application_runner=self._application_action)
        self.updates_page.install_requested.connect(self._on_install_requested)
        self.update_status = self.updates_page.update_status
        self.check_update_button = self.updates_page.check_update_button
        self.download_update_button = self.updates_page.download_update_button
        self.cancel_update_button = self.updates_page.cancel_update_button
        self.install_update_button = self.updates_page.install_update_button
        self.update_channel = self.updates_page.update_channel

        self.settings_page = SettingsPage(self.store, application_runner=self._application_action)
        self.settings_page.preferences_changed.connect(self._apply_editor_preferences)
        self.editor_font_size = self.settings_page.editor_font_size
        self.editor_wrap = self.settings_page.editor_wrap

        self.pages = QStackedWidget()
        self.pages.addWidget(self._chat_page())
        self.pages.addWidget(self._workbench())
        self.pages.addWidget(self.library_page)
        self.pages.addWidget(self._models_page())
        self.pages.addWidget(self.workloads_page)
        self.pages.addWidget(self.updates_page)
        self.pages.addWidget(self.settings_page)
        self._apply_editor_preferences()
        self._connect_model_selectors()
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._models_opened)
        scenes = ("chat", "projects", "library", "models", "workloads", "updates", "settings")
        self.navigation.currentRowChanged.connect(lambda row: self.sidebar.set_scene(scenes[row]) if 0 <= row < len(scenes) else None)
        self.navigation.setCurrentRow(0)
        outer.addWidget(sidebar)
        outer.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.setStyleSheet(APP_STYLESHEET)
        self.setFont(QFont("Segoe UI", 10))
        file_menu = self.menuBar().addMenu("File")
        for label, shortcut, callback in (
            ("Open workspace…", "Ctrl+O", self.choose_workspace),
            ("Save", "Ctrl+S", self.save_document),
            ("New file…", "Ctrl+Shift+N", self.new_file),
            ("Find in file…", "Ctrl+F", self.find_in_file),
            ("New conversation", "Ctrl+N", self.new_conversation),
            ("Export conversation…", "Ctrl+Shift+E", self.export_conversation),
        ):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            file_menu.addAction(action)
        self.statusBar().setSizeGripEnabled(True)
        for label in self.findChildren(QLabel):
            label.setTextFormat(Qt.PlainText)

    def _action(self, text, callback, symbol=None, primary=False):
        return action(text, callback, symbol, primary)

    def _page(self, title, subtitle):
        return page(title, subtitle)

    def _card(self, title, description=None):
        return card(title, description)

    def _chat_page(self):
        page = ScenePage(scene="chat")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.chat_rail = QWidget()
        self.chat_rail.setObjectName("chatRail")
        self.chat_rail.setMinimumWidth(200)
        self.chat_rail.setMaximumWidth(320)
        rail = QVBoxLayout(self.chat_rail)
        rail.setContentsMargins(16, 24, 16, 16)
        rail.setSpacing(14)
        title = QLabel("Conversations")
        title.setObjectName("pageHeader")
        rail.addWidget(title)
        self.conversation_search = QLineEdit()
        self.conversation_search.setPlaceholderText("Search conversations…")
        self.conversation_search.setAccessibleName("Search conversations")
        self.conversation_search.addAction(icon("search"), QLineEdit.LeadingPosition)
        self.conversation_search.textChanged.connect(self._filter_conversations)
        rail.addWidget(self.conversation_search)
        rail.addWidget(self._action("New Chat", self.new_conversation, "plus", primary=True))
        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("conversationList")
        self.conversation_list.setAccessibleName("Saved conversations")
        self.conversation_list.setSpacing(4)
        self.conversation_list.itemClicked.connect(self._select_conversation)
        rail.addWidget(self.conversation_list, 1)
        self.conversation_empty = QLabel("Your conversations will appear here.\nStart a new chat when you are ready.")
        self.conversation_empty.setWordWrap(True)
        self.conversation_empty.setObjectName("muted")
        rail.addWidget(self.conversation_empty)
        rail.addWidget(self._action("Export conversation…", self.export_conversation, "file"))
        self.delete_conversation_button = self._action("Delete conversation", self.delete_conversation)
        rail.addWidget(self.delete_conversation_button)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.chat_rail)
        splitter.addWidget(self._chat_panel())
        splitter.setSizes([270, 870])
        layout.addWidget(splitter)
        return page

    def _chat_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header.setObjectName("chatHeader")
        top = QHBoxLayout(header)
        top.setContentsMargins(28, 20, 28, 18)
        title = QVBoxLayout()
        title.setSpacing(3)
        self.chat_title = QLabel("Chat")
        self.chat_title.setObjectName("pageTitle")
        title.addWidget(self.chat_title)
        subtitle = QLabel("Local AI. Real control. A brighter tomorrow.")
        subtitle.setObjectName("pageSubtitle")
        title.addWidget(subtitle)
        top.addLayout(title, 1)
        self.chat_model_combo = QComboBox()
        self.chat_model_combo.setEditable(True)
        self.chat_model_combo.setMinimumWidth(150)
        self.chat_model_combo.setMaximumWidth(210)
        self.chat_model_combo.setAccessibleName("Chat model")
        self.chat_model_combo.lineEdit().setPlaceholderText("Select model")
        top.addWidget(self.chat_model_combo)
        self.privacy_badge = QLabel("◉  Local · Offline-first")
        self.privacy_badge.setObjectName("privacyBadge")
        self.privacy_badge.setToolTip("CETA connects only to local model endpoints. Separately started runtimes retain their own privacy settings.")
        top.addWidget(self.privacy_badge)
        layout.addWidget(header)
        self.chat_view = ChatTranscript()
        layout.addWidget(self.chat_view, 1)
        composer_margin = QVBoxLayout()
        composer_margin.setContentsMargins(24, 10, 24, 8)
        composer = QFrame()
        composer.setObjectName("composer")
        compose_layout = QVBoxLayout(composer)
        compose_layout.setContentsMargins(12, 8, 12, 10)
        compose_layout.setSpacing(8)
        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("Response role"))
        self.chat_role_combo = QComboBox()
        self.chat_role_combo.setAccessibleName("Response role")
        self.chat_role_combo.addItem("Assistant", None)
        self.chat_role_combo.addItem("Reviewer", "reviewer")
        self.chat_role_combo.addItem("Specialist", "specialist")
        self.chat_role_combo.setToolTip("Uses the selected model and current task. Role responses are proposals; review their supporting evidence before applying changes.")
        role_row.addWidget(self.chat_role_combo)
        role_row.addStretch()
        compose_layout.addLayout(role_row)
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("chatPrompt")
        self.prompt.setMinimumHeight(58)
        self.prompt.setMaximumHeight(125)
        self.prompt.setPlaceholderText("Type a message to CETA…")
        self.prompt.setAccessibleName("Message to CETA")
        self.prompt.textChanged.connect(lambda: self.prompt_timer.start(500))
        compose_layout.addWidget(self.prompt)
        actions = QHBoxLayout()
        attach = self._action("Open file", self.attach_document, "file")
        attach.setObjectName("quietButton")
        attach.setToolTip("Add the currently open editor file to this draft. Nothing is sent until you choose Send.")
        actions.addWidget(attach)
        workspace = self._action("Workspace", lambda: self.navigation.setCurrentRow(1), "folder")
        workspace.setObjectName("quietButton")
        actions.addWidget(workspace)
        actions.addStretch()
        self.composer_model_combo = QComboBox()
        self.composer_model_combo.setEditable(True)
        self.composer_model_combo.setAccessibleName("Message model")
        self.composer_model_combo.setMinimumWidth(130)
        self.composer_model_combo.setMaximumWidth(190)
        self.composer_model_combo.lineEdit().setPlaceholderText("Select model")
        actions.addWidget(self.composer_model_combo)
        self.stop_chat_button = self._action("Stop", self.stop_chat)
        self.stop_chat_button.setEnabled(False)
        actions.addWidget(self.stop_chat_button)
        self.send_button = self._action("Send", self.send_message, "send", primary=True)
        actions.addWidget(self.send_button)
        compose_layout.addLayout(actions)
        composer_margin.addWidget(composer)
        self.chat_status = QLabel("Choose a local model in Models to start chatting.")
        self.chat_status.setObjectName("muted")
        self.chat_status.setWordWrap(True)
        composer_margin.addWidget(self.chat_status)
        privacy = QLabel("Your conversations are saved on your machine.")
        privacy.setObjectName("muted")
        privacy.setAlignment(Qt.AlignCenter)
        composer_margin.addWidget(privacy)
        layout.addLayout(composer_margin)
        return panel

    def _connect_model_selectors(self):
        self.chat_model_combo.setModel(self.model_combo.model())
        self.composer_model_combo.setModel(self.model_combo.model())
        for selector in (self.model_combo, self.chat_model_combo, self.composer_model_combo):
            selector.currentTextChanged.connect(lambda text, source=selector: self._sync_model_selection(source, text))
        self._sync_model_selection(self.model_combo, self.store.setting("model", ""))

    def _sync_model_selection(self, source, text):
        for selector in (self.model_combo, self.chat_model_combo, self.composer_model_combo):
            if selector is not source and selector.currentText() != text:
                was_blocked = selector.blockSignals(True)
                selector.setCurrentText(text)
                selector.blockSignals(was_blocked)

    def _workbench(self):
        page, layout = self._page("Projects", "Your files and tools, together. Open a folder to make it your workspace.")
        top = QHBoxLayout()
        self.workspace_label = QLabel("No workspace open")
        self.workspace_label.setObjectName("muted")
        top.addWidget(self.workspace_label, 1)
        top.addWidget(self._action("Open workspace", self.choose_workspace, "folder"))
        top.addWidget(self._action("New file", self.new_file, "plus"))
        top.addWidget(self._action("Save file", self.save_document, "file", primary=True))
        layout.addLayout(top)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        self.file_model = QFileSystemModel(self)
        self.file_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.tree = QTreeView()
        self.tree.setModel(self.file_model)
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName("Workspace files")
        for index in range(1, 4):
            self.tree.hideColumn(index)
        self.tree.doubleClicked.connect(self.open_document)
        splitter.addWidget(self.tree)
        center = QSplitter(Qt.Vertical)
        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.file_label = QLabel("No file open")
        self.file_label.setObjectName("muted")
        self.editor = CodeEditor()
        self.editor.setFont(QFont("Cascadia Mono", 11))
        self.editor.setPlaceholderText("Open a text file from your workspace. Changes are saved only when you choose Save.")
        self.editor.setEnabled(False)
        self.editor.textChanged.connect(self._editor_changed)
        editor_layout.addWidget(self.file_label)
        editor_layout.addWidget(self.editor)
        center.addWidget(editor_panel)
        terminal, terminal_layout = self._card("Terminal", "Commands run only when you choose Run, with your account's permissions.")
        command_row = QHBoxLayout()
        self.command = QLineEdit()
        self.command.setPlaceholderText("Command to run in this workspace")
        self.command.setAccessibleName("Workspace command")
        self.run_button = self._action("Run", self.run_workload, "terminal", primary=True)
        self.stop_work_button = self._action("Stop", self.stop_workload)
        self.stop_work_button.setEnabled(False)
        command_row.addWidget(self.command, 1)
        command_row.addWidget(self.run_button)
        command_row.addWidget(self.stop_work_button)
        terminal_layout.addLayout(command_row)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(10000)
        self.output.setFont(QFont("Cascadia Mono", 10))
        self.output.setPlaceholderText("Workload output appears here.")
        terminal_layout.addWidget(self.output)
        center.addWidget(terminal)
        center.setSizes([520, 240])
        splitter.addWidget(center)
        splitter.setSizes([240, 850])
        self.project_tabs = QTabWidget()
        self.project_tabs.addTab(splitter, "Files and terminal")
        self.task_panel = TasksPanel(self)
        self.project_tabs.addTab(self.task_panel, "Task and evidence")
        layout.addWidget(self.project_tabs, 1)
        return page

    def _library_page(self):
        return self.library_page

    def _open_library_conversation(self):
        return self.library_page._open_library_conversation()

    def _export_library_conversation(self):
        return self.library_page._export_library_conversation()

    def _filter_conversations(self, query):
        filter_list(self.conversation_list, query)

    def _filter_library(self, query):
        self.library_page._filter_library(query)

    @staticmethod
    def _filter_list(listing, query):
        filter_list(listing, query)

    def _models_page(self):
        page, layout = self._page("Models", "Your intelligence, your choice. Install optional packs or connect to a local runtime.")
        hardware, hardware_layout = self._card(
            "Choose a model for this computer",
            "Local models can help with text, code, drafting, and explanation.",
        )
        self.hardware_summary = QLabel("Open Models to inspect available memory and graphics hardware. No network request is needed.")
        self.hardware_summary.setWordWrap(True)
        self.hardware_summary.setAccessibleName("Local hardware summary")
        hardware_layout.addWidget(self.hardware_summary)
        choices = QHBoxLayout()
        self.hardware_model_combo = QComboBox()
        self.hardware_model_combo.setAccessibleName("Models assessed for this computer")
        self.hardware_model_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.hardware_model_combo.setMinimumContentsLength(18)
        self.hardware_model_combo.currentIndexChanged.connect(self._hardware_selection_changed)
        choices.addWidget(self.hardware_model_combo, 1)
        self.use_suggested_button = self._action("Use suggested model", self.use_suggested_model)
        self.use_suggested_button.setEnabled(False)
        choices.addWidget(self.use_suggested_button)
        self.hardware_refresh_button = self._action("Recheck hardware", self.refresh_hardware, "refresh")
        choices.addWidget(self.hardware_refresh_button)
        hardware_layout.addLayout(choices)
        self.hardware_model_detail = QLabel("Download remains an explicit action. Model fit is assessed for one request with a 4,096-token context.")
        self.hardware_model_detail.setWordWrap(True)
        hardware_layout.addWidget(self.hardware_model_detail)
        layout.addWidget(hardware)
        service, service_layout = self._card("Local model connection", "CETA starts Ollama with cloud features disabled. Services started outside CETA retain their own privacy settings.")
        form = QFormLayout()
        form.setSpacing(12)
        self.endpoint = QLineEdit(self.store.setting("endpoint", "http://127.0.0.1:11434/v1"))
        form.addRow("Local service", self.endpoint)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(self.store.setting("model", ""))
        self.model_combo.setAccessibleName("Active local model")
        self.model_combo.lineEdit().setPlaceholderText("Connect to discover installed models")
        self.model_combo.currentTextChanged.connect(self._model_configuration_changed)
        self.endpoint.textChanged.connect(self._model_configuration_changed)
        form.addRow("Active model", self.model_combo)
        service_layout.addLayout(form)
        controls = QHBoxLayout()
        controls.addWidget(self._action("Connect / refresh models", self.refresh_models, "refresh", primary=True))
        controls.addWidget(self._action("Start installed Ollama", self.start_ollama, "models"))
        self.probe_model_button = self._action("Test selected local model", self.probe_model)
        controls.addStretch()
        service_layout.addLayout(controls)
        service_layout.addWidget(self.probe_model_button, 0, Qt.AlignLeft)
        layout.addWidget(service)
        packs, packs_layout = self._card("Expansion packs", "Model downloads are optional and separate from application updates. No model is bundled with CETA.")
        download_row = QHBoxLayout()
        self.pack_name = QLineEdit()
        self.pack_name.setPlaceholderText("Ollama model name, for example qwen3:4b")
        self.pull_button = self._action("Download pack", self.download_model_pack, "updates", primary=True)
        self.cancel_pull_button = self._action("Cancel download", self.cancel_model_download)
        self.cancel_pull_button.setEnabled(False)
        download_row.addWidget(self.pack_name, 1)
        download_row.addWidget(self.pull_button)
        download_row.addWidget(self.cancel_pull_button)
        packs_layout.addLayout(download_row)
        self.pack_list = QListWidget()
        self.pack_list.setAccessibleName("Installed GGUF model packs")
        packs_layout.addWidget(self.pack_list, 1)
        row = QHBoxLayout()
        self.import_button = self._action("Import GGUF pack…", self.import_model, "folder")
        row.addWidget(self.import_button)
        row.addWidget(self._action("Start selected pack…", self.start_model, "models"))
        row.addWidget(self._action("Stop local model", self.stop_local_model))
        packs_layout.addLayout(row)
        layout.addWidget(packs, 1)
        self.model_status = QLabel("No model download is required to browse or edit your workspace.")
        self.model_status.setObjectName("muted")
        self.model_status.setWordWrap(True)
        layout.addWidget(self.model_status)
        self.model_log = QPlainTextEdit()
        self.model_log.setReadOnly(True)
        self.model_log.setMaximumBlockCount(1000)
        self.model_log.setMaximumHeight(90)
        self.model_log.setPlaceholderText("Local runtime output")
        layout.addWidget(self.model_log)
        return page

    def _models_opened(self, row):
        if row == 3 and self.hardware_profile is None:
            self.refresh_hardware()

    def _model_configuration_changed(self, *_):
        if hasattr(self, "model_status"):
            self.model_status.setText("Model settings changed. Inference is unverified for the current model and endpoint.")

    def _hardware_loaded(self, profile):
        self.hardware_profile = profile
        self.hardware_summary.setText(format_hardware(profile))
        previous = self.hardware_model_combo.currentData()
        preferred = previous.model.tag if previous else None
        suggestion = recommended_model(profile)
        if preferred is None and suggestion:
            preferred = suggestion.model.tag
        self.hardware_model_combo.blockSignals(True)
        self.hardware_model_combo.clear()
        preferred_index = 0
        for assessment in assess_models(profile):
            model = assessment.model
            self.hardware_model_combo.addItem(
                f"{assessment.mode.upper()} · {model.tag} · {model.download_bytes / 1024**3:.1f} GiB download",
                assessment,
            )
            self.hardware_model_combo.setItemData(
                self.hardware_model_combo.count() - 1,
                f"{model.tag}\n{assessment.reason}", Qt.ToolTipRole,
            )
            if model.tag == preferred:
                preferred_index = self.hardware_model_combo.count() - 1
        self.hardware_model_combo.setCurrentIndex(preferred_index)
        self.hardware_model_combo.blockSignals(False)
        self._hardware_selection_changed()

    def _hardware_selection_changed(self, *_):
        assessment = self.hardware_model_combo.currentData()
        if assessment is None:
            return
        self.hardware_model_detail.setText(
            f"{assessment.model.description}\n{assessment.reason}",
        )
        self.hardware_model_combo.setToolTip(self.hardware_model_combo.currentText())
        self.use_suggested_button.setEnabled(assessment.mode in {"cpu", "gpu"})

    def use_suggested_model(self):
        assessment = self.hardware_model_combo.currentData()
        if assessment and assessment.mode in {"cpu", "gpu"}:
            self.pack_name.setText(assessment.model.tag)
            self.model_status.setText("Suggested name filled in. Choose Download pack to request installation.")

    def refresh_hardware(self):
        if self.hardware_check_running:
            return
        self.hardware_check_running = True
        self.hardware_refresh_button.setEnabled(False)
        self.hardware_model_combo.setEnabled(False)
        self.use_suggested_button.setEnabled(False)
        self.hardware_summary.setText("Inspecting this computer's available memory and graphics hardware…")
        task = self._background(lambda _: inspect_hardware(), self._hardware_loaded, self._hardware_check_failed)
        task.finished.connect(self._hardware_check_finished)

    def _hardware_check_failed(self, error):
        self.hardware_profile = None
        self.hardware_model_combo.clear()
        self.use_suggested_button.setEnabled(False)
        self.hardware_summary.setText(f"Hardware inspection unavailable: {error}")
        self.hardware_model_detail.setText("There is no current hardware assessment. Recheck hardware before choosing a suggestion.")

    def _hardware_check_finished(self):
        self.hardware_check_running = False
        self.hardware_refresh_button.setEnabled(True)
        self.hardware_model_combo.setEnabled(True)

    def probe_model(self):
        if self.model_probe_running or self.chat_task:
            self.model_status.setText("Stop the current model request before testing another response.")
            return
        model = self.model_combo.currentText().strip()
        if not model:
            self.model_status.setText("Connect and select an installed local model first.")
            return
        try:
            endpoint = self.endpoint.text().strip()
            client = LocalModelClient(endpoint)
        except ValueError as exc:
            self.model_status.setText(str(exc))
            return
        self.model_probe_running = True
        self.probe_model_button.setEnabled(False)
        self.model_status.setText(f"Testing one short local response from {model}…")

        def verified(result):
            runtime = result.get("runtime") or {}
            residency = ""
            if isinstance(runtime.get("size_vram"), (int, float)):
                residency = f" · runtime-reported VRAM {runtime['size_vram'] / 1024**3:.2f} GiB"
            if self.model_combo.currentText().strip() == model and self.endpoint.text().strip() == endpoint:
                self.model_status.setText(
                    f"Response completed for {result['model']} · runtime reports local inference · "
                    f"{result['elapsed_seconds']:.1f}s{residency}. This short check does not measure general response quality.",
                )
            else:
                self.model_status.setText(f"Test completed for {result['model']} using earlier settings. Current model and endpoint remain unverified.")
            self.model_log.appendPlainText(f"Local test response ({result['model']}):\n{result['response']}")

        def finished():
            self.model_probe_running = False
            self.probe_model_button.setEnabled(True)

        directory = self.store.directory
        def probe(task):
            runtime = TaskRuntime(directory)
            try:
                return runtime.probe_model(client, model, cancelled=task.cancelled)
            finally:
                runtime.close()
        task = self._background(probe, verified,
                                lambda error: self.model_status.setText(f"Local inference not verified: {error}"))
        task.cancelled = client.cancelled
        task.finished.connect(finished)

    def _workloads_page(self):
        page, layout = self._page("Workloads", "A record of the commands you ran, their results, and what happened next.")
        layout.addWidget(self._action("Go to project terminal", lambda: self.navigation.setCurrentRow(1), "terminal"), 0, Qt.AlignLeft)
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
        return page

    def _settings_page(self):
        return self.settings_page

    def _apply_editor_preferences(self, size=None, wrap=None):
        if size is None:
            size = self.editor_font_size.value()
        if wrap is None:
            wrap = self.editor_wrap.isChecked()
        self.editor.setFont(QFont("Cascadia Mono", size))
        self.editor.setStyleSheet(f"QPlainTextEdit {{ font-family: 'Cascadia Mono'; font-size: {size}pt; }}")
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth if wrap else QPlainTextEdit.NoWrap)

    def _save_editor_preferences(self, *_):
        self.settings_page._save_editor_preferences()

    def _load_workloads(self):
        self.workloads_page.load_workloads()

    def _select_workload(self, item, _previous=None):
        self.workloads_page._select_workload(item, _previous)

    def _workloads_page(self):
        return self.workloads_page

    def _updates_page(self):
        return self.updates_page

    def open_dependency_notices(self):
        return self.updates_page.open_dependency_notices()

    def check_for_updates(self):
        return self.updates_page.check_for_updates()

    def save_update(self):
        return self.updates_page.save_update()

    def cancel_update_download(self):
        return self.updates_page.cancel_update_download()

    @property
    def downloaded_update(self):
        if hasattr(self, "updates_page"):
            return self.updates_page.downloaded_update
        return getattr(self, "_downloaded_update", None)

    @downloaded_update.setter
    def downloaded_update(self, value):
        self._downloaded_update = value
        if hasattr(self, "updates_page"):
            self.updates_page.downloaded_update = value

    def _update_saved(self, path, manifest):
        self.updates_page._update_saved(path, manifest)

    def install_update(self):
        if not self.downloaded_update or os.name != "nt":
            return
        if self._has_active_work():
            self.update_status.setText("Stop active conversations, downloads, and workloads before installing the update.")
            return
        answer = QMessageBox.question(
            self, "Install CETA update", "Close CETA and start the verified installer? Any model service started by CETA will stop. Your saved conversations and model packs will remain.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.pending_update = self.downloaded_update
        if not self.close():
            self.pending_update = None

    def _has_active_work(self) -> bool:
        return bool(self.tasks or self.chat_task or self.workload_task or self.process.state() != QProcess.NotRunning)

    def _on_install_requested(self, path, manifest):
        self.pending_update = (path, manifest)
        if not self.close():
            self.pending_update = None

    def _error(self, message):
        self.statusBar().showMessage(str(message))
        QMessageBox.warning(self, "CETA", str(message))

    def _application_action(self, kind, arguments, executor, *, return_action=False):
        runtime = TaskRuntime(self.store.directory)
        try:
            return runtime.application_action(kind, arguments, executor, return_action=return_action)
        finally:
            runtime.close()

    def _observe_model(self, observation):
        if not self.model_action_id:
            if self.model_start_pending:
                self.pending_model_observations.append(observation)
            return
        runtime = TaskRuntime(self.store.directory)
        try:
            runtime.application_observation(self.model_action_id, observation)
        except (ValueError, OSError, RuntimeError) as exc:
            self.model_status.setText(f"Model process evidence could not be saved: {exc}")
        finally:
            runtime.close()

    def _start_owned_model(self):
        self.model_action_id = None
        self.model_start_pending = True
        self.pending_model_observations = []
        try:
            record = self._application_action(
                "model.start", {"program": self.model_process.program(), "arguments": self.model_process.arguments(),
                                "outcome_scope": "Request local process startup; readiness is checked separately"},
                self.model_process.start, return_action=True)
            self.model_action_id = record["action_id"]
            self.model_start_pending = False
            observations = self.pending_model_observations
            self.pending_model_observations = []
            for observation in observations:
                self._observe_model(observation)
            return not any(item.get("phase") == "process_error" for item in observations)
        except (ValueError, OSError, RuntimeError) as exc:
            self.model_status.setText(f"Could not request model startup: {exc}")
            return False
        finally:
            self.model_start_pending = False

    def _model_started(self):
        self._observe_model({"phase": "started", "process_id": int(self.model_process.processId()),
                             "readiness": "not_yet_tested"})

    def _model_error(self, _error):
        self.model_status.setText(self.model_process.errorString())
        self._observe_model({"phase": "process_error", "error": self.model_process.errorString()})

    def _model_finished(self, code, status):
        self.model_status.setText("Local model stopped")
        self._observe_model({"phase": "finished", "exit_code": code, "exit_status": str(status)})
        self.model_action_id = None

    def stop_local_model(self):
        if self.model_process.state() == QProcess.NotRunning:
            return
        try:
            self._application_action("model.stop", {"process_id": int(self.model_process.processId()),
                                                    "start_action_id": self.model_action_id},
                                     lambda: self._stop_process(self.model_process))
        except (ValueError, OSError, RuntimeError) as exc:
            self.model_status.setText(f"Could not stop the owned model process: {exc}")

    def _background(self, function, result, failed=None):
        task = BackgroundTask(function, self)
        self.tasks.append(task)
        task.result.connect(result)
        task.failed.connect(failed or self._error)
        task.finished.connect(lambda: self.tasks.remove(task))
        task.finished.connect(task.deleteLater)
        task.start()
        return task

    def _discard_allowed(self):
        if not self.editor.document().isModified():
            return True
        answer = QMessageBox.question(self, "Unsaved changes", "Save your changes before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self.save_document()
        if answer == QMessageBox.Discard:
            # The following file dialog/open may still be cancelled or fail.
            # Clear the draft only when an actual document switch succeeds.
            return True
        return answer == QMessageBox.Discard

    def choose_workspace(self):
        if self.workload_task or self.chat_task or self.process.state() != QProcess.NotRunning:
            self._error("Stop the current task work before switching workspaces.")
            return
        if not self._discard_allowed():
            return
        folder = QFileDialog.getExistingDirectory(self, "Open workspace")
        if folder:
            try:
                self._set_workspace(Path(folder))
                self._clear_editor_draft()
                self.navigation.setCurrentRow(1)
            except (ValueError, OSError, RuntimeError) as exc:
                self._error(exc)

    def new_file(self):
        if not self.workspace:
            self.statusBar().showMessage("Open a workspace first.")
            return
        if not self._discard_allowed():
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Create a new file", str(self.workspace.root))
        if not destination:
            return
        try:
            path = Path(destination).resolve()
            if not path.is_relative_to(self.workspace.root) or any(part.casefold() == ".git" for part in path.relative_to(self.workspace.root).parts):
                raise ValueError("Create the file inside the workspace, outside Git internal folders.")
            result = self.task_runtime.create_file(self.task_id, str(path))
            if result.get("status") != "completed":
                self.task_panel.show_result("File creation needs attention", result)
                return
            self.task_runtime.read(self.task_id, str(path))
            self.document = self.workspace.open(path)
            self._clear_editor_draft()
            self.editor.setPlainText("")
            self.editor.document().setModified(False)
            self.editor.setEnabled(True)
            self._editor_changed()
        except (ValueError, OSError, RuntimeError) as exc:
            self._error(exc)

    def find_in_file(self):
        query, accepted = QInputDialog.getText(self, "Find in file", "Text to find")
        if accepted and query and not self.editor.find(query):
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            if not self.editor.find(query):
                self.statusBar().showMessage("Text not found in this file.")

    def attach_document(self):
        if not self.document or not self.workspace:
            self.chat_status.setText("Open a text file before attaching it.")
            return
        text = self.editor.toPlainText()
        if len(text) > 80000:
            self.chat_status.setText("This file is too large to attach. Copy the relevant section into your message.")
            return
        relative = self.document.path.relative_to(self.workspace.root).as_posix()
        self.prompt.setPlainText(self.prompt.toPlainText() + f"\n\nFile: {relative}\n```\n{text}\n```\n")
        self.chat_status.setText("File added to your draft. Review the message before sending.")

    def _set_workspace(self, path):
        workspace = Workspace(path)
        if (self.chat_task or self.workload_task) and (not self.workspace or workspace.root != self.workspace.root):
            raise ValueError("Stop the current task work before switching workspaces.")
        project = self.task_runtime.open_project(path)
        previous_project = self.project_id
        changed = previous_project != project["project_id"]
        previous_scope = self.store.conversation_scope(self.conversation_id) if self.conversation_id else None
        initial_legacy = previous_project is None and self.conversation_id is not None and previous_scope is None
        if changed:
            self._save_prompt_draft()
            if previous_project is not None:
                self.store.set_setting("active_conversation:" + previous_project, self.conversation_id)
        self.workspace = workspace
        self.project_id = project["project_id"]
        if previous_project is None and previous_scope and previous_scope["project_id"] == self.project_id:
            self.store.set_setting("active_task:" + self.project_id, previous_scope["task_id"])
            self.store.set_setting("active_conversation:" + self.project_id, self.conversation_id)
        self._resume_project_task()
        self.pending_edit = None
        self.task_panel.apply_button.setEnabled(False)
        if changed and not initial_legacy:
            self.prompt_timer.stop()
            self.conversation_id = self.store.setting("active_conversation:" + self.project_id)
            visible = {row["id"] for row in self.store.conversations()}
            scope = self.store.conversation_scope(self.conversation_id) if self.conversation_id else None
            if (self.conversation_id not in visible or not scope or scope["project_id"] != self.project_id
                    or scope["task_id"] != self.task_id):
                self.conversation_id = None
            self.store.set_setting("active_conversation", self.conversation_id)
            self._restore_prompt_draft()
            self._render_chat()
        elif initial_legacy:
            self.chat_status.setText("This historical conversation is unassigned. Use 'Use conversation for task' before using it as project context.")
            self.chat_title.setText("Unassigned conversation")
        self.store.set_setting("workspace", str(self.workspace.root))
        self.workspace_label.setText(f"Workspace · {self.workspace.root.name}")
        self.workspace_label.setToolTip(str(self.workspace.root))
        self.file_model.setRootPath(str(self.workspace.root))
        self.tree.setRootIndex(self.file_model.index(str(self.workspace.root)))
        self.document = None
        self.editor.clear()
        self.editor.setEnabled(False)
        self.file_label.setText("No file open")

    def open_document(self, index):
        if not self.workspace or self.file_model.isDir(index) or not self._discard_allowed():
            return
        try:
            path = Path(self.file_model.filePath(index))
            self.task_runtime.read(self.task_id, str(path))
            self.document = self.workspace.open(path)
            self._clear_editor_draft()
            self.editor.setPlainText(self.document.text)
            self.editor.document().setModified(False)
            self.editor.setEnabled(True)
            self.file_label.setText(str(self.document.path.relative_to(self.workspace.root)))
        except (ValueError, OSError, RuntimeError) as exc:
            self._error(exc)

    def _editor_changed(self):
        if self.pending_edit:
            self.pending_edit = None
            self.task_panel.apply_button.setEnabled(False)
        if self.document and self.workspace:
            suffix = " *" if self.editor.document().isModified() else ""
            self.file_label.setText(str(self.document.path.relative_to(self.workspace.root)) + suffix)
            if self.editor.document().isModified():
                self.draft_timer.start(500)

    def _save_editor_draft(self):
        if self.document and self.workspace and self.editor.document().isModified():
            self.store.set_setting("editor_draft", {
                "workspace": str(self.workspace.root), "path": str(self.document.path),
                "text": self.editor.toPlainText(), "digest": self.document.digest,
            })

    def _clear_editor_draft(self):
        self.draft_timer.stop()
        self.store.set_setting("editor_draft", None)

    def _restore_editor_draft(self):
        draft = self.store.setting("editor_draft")
        if not draft:
            return
        try:
            self._set_workspace(Path(draft["workspace"]))
            self.task_runtime.read(self.task_id, str(draft["path"]))
            self.document = self.workspace.open(Path(draft["path"]))
            self.document.digest = draft["digest"]
            self.editor.setPlainText(draft["text"])
            self.editor.document().setModified(True)
            self.editor.setEnabled(True)
            self._editor_changed()
            self.statusBar().showMessage("Recovered an unsaved editor draft. Review it before saving.")
        except (ValueError, OSError, RuntimeError, KeyError) as exc:
            self.store.set_setting("editor_draft", draft)
            self.statusBar().showMessage(f"An editor draft is retained in local data but could not be reopened: {exc}")

    def save_document(self):
        if not self.document or not self.workspace:
            return True
        try:
            result = self.task_runtime.save_document(self.task_id, self.document, self.editor.toPlainText())
            if result.get("status") != "completed":
                self.task_panel.show_result("Save needs attention; editor draft retained", result)
                self._save_editor_draft()
                self.statusBar().showMessage("Save did not verify successfully. Review task evidence; the editor draft is retained.")
                return False
            self.document = self.workspace.open(self.document.path)
            self.editor.document().setModified(False)
            self.draft_timer.stop()
            self.store.set_setting("editor_draft", None)
            self._editor_changed()
            self.statusBar().showMessage("File saved")
            return True
        except (ValueError, OSError, RuntimeError) as exc:
            self._error(exc)
            return False

    def _ensure_task(self):
        if not self.project_id:
            project = self.task_runtime.application_project()
            self.project_id = project["project_id"]
            self._resume_project_task()

    def _resume_project_task(self):
        saved = self.store.setting("active_task:" + self.project_id)
        records = self.task_runtime.tasks(self.project_id)
        selected = next((row for row in records if row["task_id"] == saved), None)
        if selected is None:
            objective = "Work in " + self.workspace.root.name if self.workspace else "Conversation with CETA"
            selected = self.task_runtime.start_task(self.project_id, objective)
        self.task_id = selected["task_id"]
        self.store.set_setting("active_task:" + self.project_id, self.task_id)
        self._refresh_task_panel()

    def _refresh_task_panel(self):
        if self.project_id:
            scope = (self.project_id, self.task_id)
            if self.task_panel.displayed_scope != scope:
                self.task_panel.displayed_scope = scope
                self.task_panel.result_title.setText("Task results")
                self.task_panel.results.clear()
            self.task_panel.set_tasks(self.task_runtime.tasks(self.project_id), self.task_id)
            self.task_panel.scope.setText("Project: " + (str(self.workspace.root) if self.workspace else "Application conversation"))

    def start_project_task(self):
        if self.chat_task or self.workload_task:
            self.task_panel.show_error("Stop current task work before starting another task.")
            return
        objective = self.task_panel.objective.text().strip()
        if not objective:
            self.task_panel.show_error("Enter the objective for this task.")
            return
        self._ensure_task()
        self._save_prompt_draft()
        record = self.task_runtime.start_task(self.project_id, objective)
        self.task_id = record["task_id"]
        self.store.set_setting("active_task:" + self.project_id, self.task_id)
        self.pending_edit = None
        self.task_panel.apply_button.setEnabled(False)
        self._switch_conversation(None, save_draft=False)
        self._refresh_task_panel()
        self._render_chat()

    def select_project_task(self, index):
        selected = self.task_panel.task_selector.itemData(index)
        if not selected or selected == self.task_id:
            return
        if self.chat_task or self.workload_task:
            self.task_panel.show_error("Stop current task work before switching tasks.")
            self._refresh_task_panel()
            return
        self._save_prompt_draft()
        self.task_id = selected
        self.store.set_setting("active_task:" + self.project_id, selected)
        self.pending_edit = None
        self.task_panel.apply_button.setEnabled(False)
        conversation = None
        for row in self.store.conversations():
            scope = self.store.conversation_scope(row["id"])
            if scope and scope["project_id"] == self.project_id and scope["task_id"] == selected:
                conversation = row["id"]
                break
        self._switch_conversation(conversation, save_draft=False)
        self._render_chat()

    def bind_current_conversation(self):
        if self.chat_task or not self.conversation_id:
            self.task_panel.show_error("Select an idle conversation first.")
            return
        try:
            self._ensure_task()
            self.store.bind_conversation(self.conversation_id, self.project_id, self.task_id)
            self.task_panel.show_result("Conversation assigned", {"task_id": self.task_id})
            self._render_chat()
        except (ValueError, OSError, RuntimeError) as exc:
            self.task_panel.show_error(str(exc))

    def inspect_project_task(self):
        self._task_read_action("Project inspection", "inspect")

    def search_project_task(self):
        query = self.task_panel.search.text().strip()
        if query:
            self._task_read_action("Search results", "search", query)

    def show_task_context(self):
        self._task_read_action("Current task context", "context")

    def show_task_timeline(self):
        self._task_read_action("Task timeline", "timeline")

    def import_historical_log(self):
        if not self.workspace or not self.project_id or not self.task_id:
            self.task_panel.show_error("Open a project and select a task before importing historical records.")
            return
        if self.chat_task or self.workload_task:
            self.task_panel.show_error("Stop current task work before importing historical records.")
            return
        source, _ = QFileDialog.getOpenFileName(self, "Select historical CETA log", "", "JSON Lines (*.jsonl);;All files (*)")
        if not source:
            return
        try:
            path = Path(source)
            with path.open("rb") as stream:
                raw = stream.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("Historical imports are limited to 16 MiB per file.")
            expected_hash = hashlib.sha256(raw).hexdigest()
            kind, accepted = QInputDialog.getItem(self, "Historical log kind", "Select the CETA log format:",
                ["transition", "authority", "evidence", "identity"], 0, False)
            if not accepted:
                return
            scope, accepted = QInputDialog.getText(self, "Historical import scope",
                "Describe why these selected records belong in this project's history:")
            if not accepted:
                return
            scope = scope.strip()
            if not scope:
                raise ValueError("An explicit project scope statement is required for this import.")
            review = (f"Source: {path}\nKind: {kind}\nProject: {self.workspace.root}\n"
                      f"Task: {self.task_runtime.task(self.task_id)['objective']}\nSHA-256: {expected_hash}\n\n"
                      f"Scope: {scope}\n\nImport as historical records only. Old permits and identities will not become active authority.")
            if QMessageBox.question(self, "Import historical records", review,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            result = self.task_runtime.import_history(self.task_id, path,
                expected_sha256=expected_hash, kind=kind,
                provenance={"source_application": "CETA", "project_id": self.project_id, "scope_statement": scope})
            self.task_panel.show_result("Historical import result", result)
        except (ValueError, OSError, RuntimeError) as exc:
            self.task_panel.show_error(str(exc))

    def _task_read_action(self, title, method, *args):
        try:
            self._ensure_task()
            result = getattr(self.task_runtime, method)(self.task_id, *args)
            self.task_panel.show_result(title, result)
        except (ValueError, OSError, RuntimeError) as exc:
            self.task_panel.show_error(str(exc))

    def review_editor_edit(self):
        if not self.document or not self.workspace:
            self.task_panel.show_error("Open and edit a project file first.")
            return
        try:
            text = self.editor.toPlainText()
            proposal = self.task_runtime.propose_edit(self.task_id, str(self.document.path), text)
            self.pending_edit = {"task_id": self.task_id, "path": str(self.document.path),
                                 "text": text, "proposal_id": proposal["proposal_id"]}
            self.task_panel.show_diff(proposal["diff"])
            self.task_panel.apply_button.setEnabled(True)
        except (ValueError, OSError, RuntimeError) as exc:
            self.task_panel.show_error(str(exc))

    def apply_reviewed_edit(self):
        pending = self.pending_edit
        if not pending or not self.document:
            return
        try:
            if (pending["task_id"] != self.task_id or pending["path"] != str(self.document.path)
                    or pending["text"] != self.editor.toPlainText()):
                raise ValueError("The task or editor changed. Review the new diff before applying.")
            result = self.task_runtime.apply_edit(self.task_id, pending["proposal_id"], actor_id="user")
            if result.get("status") != "completed":
                self.pending_edit = None
                self.task_panel.apply_button.setEnabled(False)
                self._save_editor_draft()
                self.task_panel.show_result("Edit needs attention; editor draft retained", result)
                return
            self.document = self.workspace.open(self.document.path)
            self.editor.document().setModified(False)
            self._clear_editor_draft()
            self.pending_edit = None
            self.task_panel.apply_button.setEnabled(False)
            self.task_panel.show_result("Edit result", result)
            self._editor_changed()
        except (ValueError, OSError, RuntimeError) as exc:
            self.task_panel.show_error(str(exc))

    def _load_conversations(self):
        self.conversation_list.clear()
        self.library_list.clear()
        conversations = self.store.conversations()
        if self.conversation_id not in {record["id"] for record in conversations}:
            self.conversation_id = None
        for record in conversations:
            created = datetime.fromtimestamp(record["created"]).strftime("%b %d · %I:%M %p")
            for listing in (self.conversation_list, self.library_list):
                item = QListWidgetItem(f"{record['title']}\n{created}")
                item.setData(Qt.UserRole, record["id"])
                item.setToolTip(record["title"])
                item.setSizeHint(QSize(220, 65))
                listing.addItem(item)
                if record["id"] == self.conversation_id:
                    listing.setCurrentItem(item)
        if self.conversation_id is None and self.project_id is None and self.conversation_list.count():
            self.conversation_id = self.conversation_list.item(0).data(Qt.UserRole)
            self.conversation_list.setCurrentRow(0)
        self.conversation_empty.setVisible(not conversations)
        self.library_empty.setVisible(not conversations)
        self.library_list.setVisible(bool(conversations))
        self._filter_conversations(self.conversation_search.text())
        self._filter_library(self.library_search.text())
        self._render_chat()

    def _composer_draft_key(self):
        if self.conversation_id:
            return "chat_draft:" + self.conversation_id
        if self.project_id:
            return "chat_draft:new:" + self.project_id + ":" + (self.task_id or "")
        return "chat_draft:new"

    def _save_prompt_draft(self):
        self.store.set_setting(self._composer_draft_key(), self.prompt.toPlainText())

    def _restore_prompt_draft(self):
        self.prompt_timer.stop()
        self.prompt.blockSignals(True)
        self.prompt.setPlainText(self.store.setting(self._composer_draft_key(), ""))
        self.prompt.blockSignals(False)

    def _switch_conversation(self, identifier, *, save_draft=True):
        if save_draft:
            self._save_prompt_draft()
        self.conversation_id = identifier
        self.store.set_setting("active_conversation", identifier)
        scope = self.store.conversation_scope(identifier) if identifier else None
        if scope and scope["project_id"] == self.project_id:
            self.task_id = scope["task_id"]
            self.store.set_setting("active_task:" + self.project_id, self.task_id)
            self._refresh_task_panel()
        if self.project_id:
            self.store.set_setting("active_conversation:" + self.project_id, identifier)
        self._restore_prompt_draft()

    def _render_chat(self):
        records = self.store.messages(self.conversation_id) if self.conversation_id else []
        scope = self.store.conversation_scope(self.conversation_id) if self.conversation_id else None
        self.delete_conversation_button.setText("Archive conversation" if scope else "Delete conversation")
        self.chat_title.setText("Task conversation" if scope else "Chat")
        if scope and self.project_id and scope["project_id"] != self.project_id:
            self.chat_status.setText("This conversation belongs to another project. Open its project before continuing.")
        self.chat_view.render_messages(records, pending_text=self.assistant_text,
                                       model_name=self.model_combo.currentText())

    def new_conversation(self):
        if self.chat_task or self.workload_task:
            self.chat_status.setText("Stop the current task work before starting another conversation.")
            return
        self._switch_conversation(self.store.new_conversation())
        self.assistant_text = ""
        self._load_conversations()
        self.navigation.setCurrentRow(0)
        self.prompt.setFocus()

    def _select_conversation(self, item):
        if self.chat_task or self.workload_task:
            return
        self._switch_conversation(item.data(Qt.UserRole))
        self._render_chat()
        self.navigation.setCurrentRow(0)

    def _library_selection_changed(self, item, _previous=None):
        scope = self.store.conversation_scope(item.data(Qt.UserRole)) if item else None
        self.library_page.delete_button.setText("Archive selected" if scope else "Delete selected")

    def export_conversation(self):
        self._export_conversation_id(self.conversation_id)

    def _export_conversation_id(self, identifier):
        if not identifier:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Export conversation", "conversation.json", "JSON (*.json)")
        if destination:
            try:
                if Path(destination).exists() or Path(destination).is_symlink():
                    raise FileExistsError(17, "File exists", destination)
                records = self.store.messages(identifier)
                def export():
                    with Path(destination).open("x", encoding="utf-8") as handle:
                        json.dump(records, handle, indent=2, ensure_ascii=False)
                    return {"path": str(Path(destination).resolve()), "messages": len(records)}
                self._application_action("conversation.export", {"conversation_id": identifier,
                                         "destination": str(Path(destination).resolve())}, export)
            except (ValueError, OSError, RuntimeError) as exc:
                self._error(exc)

    def delete_conversation(self, identifier: str | None = None):
        target_id = identifier or self.conversation_id
        if not target_id:
            return
        if self.chat_task and target_id == self.conversation_id:
            self.chat_status.setText("Stop the current response before deleting this conversation.")
            return
        scope = self.store.conversation_scope(target_id)
        title = "Archive conversation" if scope else "Delete conversation"
        description = ("Archive this conversation? It will leave the conversation list; its task evidence remains in project history."
                       if scope else "Delete this conversation? Messages cannot be recovered.")
        answer = QMessageBox.question(
            self, title, description,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleting_current = target_id == self.conversation_id
        if scope:
            self.store.archive_conversation(target_id)
        else:
            self.store.delete_conversation(target_id)
        if deleting_current:
            # The old composer's debounce must not save its text under the next
            # selected conversation, or under the unrelated new-chat draft.
            self.prompt_timer.stop()
            self.conversation_id = None
        self._load_conversations()
        if deleting_current:
            self.store.set_setting("active_conversation", self.conversation_id)
            self._restore_prompt_draft()

    def send_message(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt or self.chat_task:
            return
        if self.model_probe_running:
            self.chat_status.setText("Wait for the local model test to finish before sending a message.")
            return
        try:
            client = LocalModelClient(self.endpoint.text().strip())
            model = self.model_combo.currentText().strip()
            if not model:
                self.chat_status.setText("Open Models and connect to an installed model first.")
                return
            if len(prompt) > 100000:
                raise ValueError("This message is too long. Keep it below 100,000 characters.")
        except ValueError as exc:
            self.chat_status.setText(str(exc))
            return
        self.store.set_setting("endpoint", self.endpoint.text().strip())
        self.store.set_setting("model", model)
        records = self.store.messages(self.conversation_id) if self.conversation_id else []
        messages = [{"role": row["role"], "content": row["content"]} for row in records if row["status"] == "complete"]
        messages.append({"role": "user", "content": prompt})
        # Validate before consuming the draft or adding an unsendable message.
        if len(json.dumps(messages)) > 512000:
            self.chat_status.setText("This conversation is too long for one request. Start a new conversation.")
            return
        try:
            self._ensure_task()
            if self.conversation_id:
                scope = self.store.conversation_scope(self.conversation_id)
                if scope and (scope["project_id"] != self.project_id or scope["task_id"] != self.task_id):
                    raise ValueError("This conversation belongs to another task. Select its project and task, or start a new conversation.")
                if not scope and records:
                    raise ValueError("This legacy conversation is unassigned. Use 'Use conversation for task' in Projects before sending it as task context.")
            if not self.conversation_id:
                draft_key = self._composer_draft_key()
                self.conversation_id = self.store.new_conversation()
                self.store.set_setting(draft_key, "")
            self.store.bind_conversation(self.conversation_id, self.project_id, self.task_id)
        except (ValueError, OSError, RuntimeError) as exc:
            self.chat_status.setText(str(exc))
            return
        self.store.set_setting("active_conversation", self.conversation_id)
        self.store.add_message(self.conversation_id, "user", prompt)
        self.prompt.clear()
        self._save_prompt_draft()
        self.assistant_text = ""
        self.response_sequence = self.store.add_message(self.conversation_id, "assistant", "", "generating")
        self._load_conversations()
        self.client = client
        self.send_button.setEnabled(False)
        self.stop_chat_button.setEnabled(True)
        role = self.chat_role_combo.currentData()
        self.chat_role_combo.setEnabled(False)
        self.chat_status.setText(f"Generating with {model}" + (f" as {role}" if role else "") + "…")

        task_id = self.task_id
        directory = self.store.directory

        def generate(task):
            runtime = TaskRuntime(directory)
            try:
                result = runtime.generate(task_id, LocalProvider(client=client, context_length=4096), model, messages,
                                          cancelled=task.cancelled, on_token=task.token.emit, role=role)
                if task.cancelled.is_set() or client.cancelled.is_set() or result.get("status") == "cancelled":
                    return "cancelled"
                if result.get("status", "completed") != "completed":
                    raise RuntimeError(result.get("error") or "The model did not complete its response.")
                return "complete"
            finally:
                runtime.close()

        self.chat_task = BackgroundTask(generate, self)
        self.chat_task.token.connect(self._chat_token)
        self.chat_task.result.connect(self._chat_complete)
        self.chat_task.failed.connect(self._chat_failed)
        self.chat_task.finished.connect(self._chat_finished)
        self.response_timer.start()
        self.chat_task.start()

    def _chat_token(self, token):
        self.assistant_text += token
        if not self.chat_render_timer.isActive():
            self.chat_render_timer.start(50)

    def _save_response_progress(self):
        if self.response_sequence is not None:
            self.store.update_response(self.response_sequence, self.assistant_text, "generating")

    def _chat_complete(self, status):
        self.response_timer.stop()
        self.chat_render_timer.stop()
        if self.response_sequence is not None:
            self.store.update_response(self.response_sequence, self.assistant_text, status)
            self.response_sequence = None
        self.assistant_text = ""
        self.chat_status.setText("Response complete" if status == "complete" else "Response stopped")
        self._render_chat()

    def _chat_failed(self, message):
        status = "cancelled" if self.client and self.client.cancelled.is_set() else "failed"
        self._chat_complete(status)
        self.chat_status.setText("Response stopped" if status == "cancelled" else f"Could not complete the response: {message}")
        self._render_chat()

    def _chat_finished(self):
        task = self.chat_task
        self.chat_task = None
        self.client = None
        self.chat_role_combo.setEnabled(True)
        self.send_button.setEnabled(True)
        self.stop_chat_button.setEnabled(False)
        if task:
            task.deleteLater()

    def stop_chat(self):
        if self.chat_task:
            self.chat_task.cancelled.set()
        if self.client:
            self.client.cancel()
            self.chat_status.setText("Stopping response…")

    def refresh_models(self):
        try:
            endpoint = self.endpoint.text().strip()
            client = LocalModelClient(endpoint)
        except ValueError as exc:
            self.model_status.setText(str(exc))
            return
        self.model_status.setText("Connecting to local model service…")

        def current_endpoint():
            if self.endpoint.text().strip() == endpoint:
                return True
            self.model_status.setText("Connection settings changed. Refresh models for the current endpoint.")
            return False

        def loaded(models):
            if not current_endpoint():
                return
            selected = self.model_combo.currentText()
            self.model_combo.clear()
            self.model_combo.addItems(models)
            if selected in models:
                self.model_combo.setCurrentText(selected)
            self.store.set_setting("endpoint", endpoint)
            skipped = getattr(client, "skipped_models", [])
            excluded = f" · {len(skipped)} remote/cloud model(s) excluded" if skipped else ""
            locality = "runtime-reported local models" if getattr(client, "backend", None) == "ollama" else "inference location unverified"
            self.model_status.setText(f"Connected · {len(models)} available models{excluded} · {locality}. Test a selected model to verify a response.")
            self.chat_status.setText("Model service connected; inference has not yet been tested." if models else "The local service has no eligible installed models.")

        def failed(error):
            if current_endpoint():
                self.model_status.setText(f"Could not connect: {error}")

        self._background(lambda _: client.available_models(), loaded, failed)

    def _load_packs(self):
        self.pack_list.clear()
        try:
            for pack in self.packs.installed():
                self.pack_list.addItem(f"{pack['name']} · {pack['size'] / 1024**3:.2f} GiB")
                self.pack_list.item(self.pack_list.count() - 1).setData(Qt.UserRole, pack)
            if self.packs.problems:
                self.model_status.setText("Some model packs need repair and have been kept on disk:\n" + "\n".join(self.packs.problems))
        except (ValueError, OSError) as exc:
            self.model_status.setText(str(exc))

    def import_model(self):
        source, _ = QFileDialog.getOpenFileName(self, "Install local model expansion", "", "GGUF model (*.gguf)")
        if not source:
            return
        self.import_button.setEnabled(False)
        self.model_status.setText("Installing model pack. Large models may take a few minutes…")

        def installed(record):
            self._load_packs()
            self.model_status.setText(f"Installed {record['name']}")

        task = self._background(lambda task: self._application_action(
            "model.import", {"source": str(Path(source).resolve()), "destination": str(self.store.directory)},
            lambda: self.packs.install(Path(source), task.cancelled)), installed,
            lambda error: self.model_status.setText(error))
        task.finished.connect(lambda: self.import_button.setEnabled(True))

    def start_model(self):
        item = self.pack_list.currentItem()
        if not item:
            self.model_status.setText("Select an installed model pack first.")
            return
        if self.model_process.state() != QProcess.NotRunning:
            self.model_status.setText("Stop the current model before starting another pack.")
            return
        executable, _ = QFileDialog.getOpenFileName(self, "Select your llama-server executable", "", "Executable (*.exe)" if os.name == "nt" else "All files (*)")
        if not executable:
            return
        record = item.data(Qt.UserRole)
        self.model_status.setText("Verifying installed model bytes before starting…")

        def prepare(task):
            profile = inspect_hardware()
            estimate = ModelOption(
                tag=record["name"], download_bytes=record["size"],
                working_bytes=(record["size"] * 5 + 3) // 4 + 1024**3,
                description="Imported GGUF size-based memory estimate",
            )
            assessment = assess_model(profile, estimate)
            if assessment.mode == "insufficient":
                raise ValueError(f"This pack does not fit currently available memory. {assessment.reason} Close other applications or select a smaller model.")
            return self.packs.verify_installed(record["sha256"], task.cancelled), profile, assessment

        def start(prepared):
            verified, profile, assessment = prepared
            self._hardware_loaded(profile)
            if self.model_process.state() != QProcess.NotRunning:
                self.model_status.setText("Another model service is already running.")
                return
            self.model_log.clear()
            self.model_process.setProgram(executable)
            arguments = ["--model", verified["path"], "--host", "127.0.0.1", "--port", "8081", "--ctx-size", "4096"]
            if assessment.mode == "cpu":
                arguments.extend(["--n-gpu-layers", "0"])
            self.model_process.setArguments(arguments)
            if not self._start_owned_model():
                return
            self.endpoint.setText("http://127.0.0.1:8081/v1")
            self.model_status.setText(f"Starting local model ({assessment.mode} memory estimate)… Connect / refresh models when it is ready.")

        self._background(prepare, start,
                         lambda error: self.model_status.setText(str(error)))

    def start_ollama(self):
        if self.model_process.state() != QProcess.NotRunning:
            self.model_status.setText("A model service started by CETA is already running.")
            return
        executable = shutil.which("ollama")
        if not executable and os.name == "nt":
            candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
            if candidate.is_file():
                executable = str(candidate)
        if not executable:
            self.model_status.setText("Install Ollama from ollama.com first, then start its local service here. You can also use a GGUF pack with llama-server.")
            return
        self.model_log.clear()
        self.model_process.setProgram(executable)
        self.model_process.setArguments(["serve"])
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("OLLAMA_HOST", "127.0.0.1:11434")
        environment.insert("OLLAMA_NO_CLOUD", "1")
        environment.insert("OLLAMA_CONTEXT_LENGTH", "4096")
        environment.insert("OLLAMA_NUM_PARALLEL", "1")
        environment.insert("OLLAMA_MAX_LOADED_MODELS", "1")
        self.model_process.setProcessEnvironment(environment)
        if not self._start_owned_model():
            return
        self.endpoint.setText("http://127.0.0.1:11434/v1")
        self.model_status.setText("Starting Ollama with cloud features disabled… Connect / refresh models when it is ready.")

    def download_model_pack(self):
        if self.pack_download_client:
            return
        try:
            client = LocalModelClient(self.endpoint.text().strip())
        except ValueError as exc:
            self.model_status.setText(str(exc))
            return
        name = self.pack_name.text().strip()
        if not name:
            self.model_status.setText("Enter the model name to download. Its size and hardware needs depend on the model.")
            return
        self.pack_download_client = client
        self.pull_button.setEnabled(False)
        self.cancel_pull_button.setEnabled(True)
        self.model_status.setText(f"Requesting {name} from the local Ollama service…")
        endpoint = self.endpoint.text().strip()

        def pull(task):
            profile = inspect_hardware()
            option = local_model_option(name)
            if option:
                assessment = assess_model(profile, option)
                if assessment.mode == "insufficient":
                    raise ValueError(f"This model does not fit currently available memory. {assessment.reason} Close other applications or select a smaller model.")
            else:
                task.token.emit("Custom model: memory fit is unassessed. Requesting the explicit download…")
            if client.cancelled.is_set():
                return "cancelled", profile
            def download():
                for status in client.pull_ollama_model(name):
                    task.token.emit(status)
                return "cancelled" if client.cancelled.is_set() else "installed"
            status = self._application_action("model.download", {"model": name, "endpoint": endpoint}, download)
            return status, profile

        def complete(result):
            status, profile = result
            self._hardware_loaded(profile)
            self.model_status.setText(f"Model pack {status}")
            if status == "installed":
                self.refresh_models()

        task = self._background(pull, complete, lambda error: self.model_status.setText(str(error)))
        task.token.connect(self.model_status.setText)
        task.finished.connect(self._model_download_finished)

    def _model_download_finished(self):
        self.pack_download_client = None
        self.pull_button.setEnabled(True)
        self.cancel_pull_button.setEnabled(False)

    def cancel_model_download(self):
        if self.pack_download_client:
            self.pack_download_client.cancel()
            self.model_status.setText("Cancelling model download…")

    def _model_output(self):
        text = bytes(self.model_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.model_log.appendPlainText(text)

    def run_workload(self):
        command = self.command.text().strip()
        if not self.workspace or not command or self.workload_task:
            self.statusBar().showMessage("Open a workspace and enter a command first.")
            return
        try:
            prepared = self.task_runtime.prepare_command(self.task_id, command)
        except (ValueError, OSError, RuntimeError) as exc:
            self._error(exc)
            return
        self.workload_id = self.store.start_workload(self.workspace.root, command)
        self.store.bind_workload(self.workload_id, self.project_id, self.task_id)
        self.workload_output = ""
        self.workload_chunks = []
        self.workload_bytes = 0
        self.workload_cancelled = False
        self.output.clear()
        self.run_button.setEnabled(False)
        self.stop_work_button.setEnabled(True)
        task_id, directory = self.task_id, self.store.directory

        def run(task):
            runtime = TaskRuntime(directory)
            try:
                return runtime.run_command(task_id, prepared["prepared_id"], cancelled=task.cancelled,
                                           on_output=task.token.emit)
            finally:
                runtime.close()

        self.workload_task = BackgroundTask(run, self)
        self.workload_task.token.connect(self._governed_workload_output)
        self.workload_task.result.connect(self._governed_workload_complete)
        self.workload_task.failed.connect(self._governed_workload_failed)
        self.workload_task.finished.connect(self._governed_workload_finished)
        self.workload_task.start()

    def _governed_workload_output(self, text):
        self.workload_output = (self.workload_output + text)[-2 * 1024 * 1024:]
        self.output.insertPlainText(text)
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def _governed_workload_complete(self, result):
        status = result["status"]
        outcome = "complete" if status == "completed" else status
        self.workload_output = result.get("output", self.workload_output)
        if result.get("error"):
            self.workload_output = (self.workload_output + "\n" + str(result["error"])).lstrip("\n")
        self.output.setPlainText(self.workload_output)
        if self.workload_id:
            self.store.finish_workload(self.workload_id, outcome, result.get("exit_code"), self.workload_output)
            self.workload_id = None
        self.statusBar().showMessage(f"Workload {outcome} · exit {result.get('exit_code')}")
        self.task_panel.show_result("Command result", result)
        self._load_workloads()

    def _governed_workload_failed(self, message):
        self._governed_workload_complete({"status": "needs_reconciliation", "exit_code": None,
                                         "output": self.workload_output + "\n" + message})

    def _governed_workload_finished(self):
        task = self.workload_task
        self.workload_task = None
        self.run_button.setEnabled(True)
        self.stop_work_button.setEnabled(False)
        if task:
            task.deleteLater()

    def _workload_output(self):
        data = bytes(self.process.readAllStandardOutput())
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        self.workload_chunks.append(text)
        self.workload_bytes += len(text)
        if self.workload_bytes > 3 * 1024 * 1024:
            self.workload_output = "".join(self.workload_chunks)[-2 * 1024 * 1024:]
            self.workload_chunks = [self.workload_output]
            self.workload_bytes = len(self.workload_output)
        self.output.insertPlainText(text)
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def _workload_error(self, error):
        if error == QProcess.FailedToStart:
            msg = self.process.errorString()
            self.workload_chunks.append(msg)
            self.output.appendPlainText(msg)
            self._workload_finished(-1, QProcess.CrashExit)

    def _workload_finished(self, code, status):
        self._workload_output()
        if self.workload_chunks:
            self.workload_output = "".join(self.workload_chunks)[-2 * 1024 * 1024:]
            self.workload_chunks = []
            self.workload_bytes = 0
        if self.workload_id:
            outcome = "cancelled" if self.workload_cancelled else ("complete" if code == 0 and status == QProcess.NormalExit else "failed")
            self.store.finish_workload(self.workload_id, outcome, code, self.workload_output)
            self.workload_id = None
            self.statusBar().showMessage(f"Workload {outcome} · exit {code}")
            self._load_workloads()
        self.run_button.setEnabled(True)
        self.stop_work_button.setEnabled(False)

    def _stop_process(self, process):
        if process.state() == QProcess.NotRunning:
            return
        pid = int(process.processId())
        if os.name == "nt" and pid:
            subprocess.run([str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"),
                            "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
        else:
            process.kill()

    def stop_workload(self):
        self.workload_cancelled = True
        if self.workload_task:
            self.workload_task.cancelled.set()
        self._stop_process(self.process)

    def closeEvent(self, event: QCloseEvent):
        if not self._discard_allowed():
            event.ignore()
            return
        if self.chat_task or self.tasks or self.workload_task:
            self.stop_chat()
            self.stop_workload()
            self.cancel_model_download()
            for task in self.tasks:
                task.cancelled.set()
            self.statusBar().showMessage("Stopping background work. Close again when it has finished.")
            event.ignore()
            return
        self.stop_workload()
        self.stop_local_model()
        self.process.waitForFinished(3000)
        self.model_process.waitForFinished(3000)
        self.draft_timer.stop()
        # An unavailable workspace/file leaves its recovery draft in storage.
        # Closing a window with no recovered document must not discard it.
        if self.document is not None:
            self._clear_editor_draft()
        self.prompt_timer.stop()
        self._save_prompt_draft()
        self.task_runtime.close()
        self.store.close()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="CETA native desktop environment")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--merger-self-test", action="store_true", help="Exercise the merged workflow in the explicitly selected test data folder")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    if args.merger_self_test and (not args.smoke_test or args.data_dir is None):
        parser.error("--merger-self-test requires --smoke-test and an explicit --data-dir")
    app = QApplication([sys.argv[0]])
    app.setApplicationName("CETA")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("CETA")
    directory = args.data_dir or application_directory()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.warning(None, "CETA", "CETA is already using this data folder.")
        return 1
    marker = open_application_marker()
    try:
        window = MainWindow(directory)
        window.show()
        if args.merger_self_test:
            def merger_check():
                report_path = directory / ("merger-self-test-" + uuid4().hex + ".json")
                try:
                    from .merger_self_test import run_merger_self_test
                    report = run_merger_self_test(window)
                except Exception as exc:
                    report = {"status": "failed", "error": str(exc)}
                code = 0 if report.get("status") == "passed" else 1
                try:
                    with report_path.open("x", encoding="utf-8") as output:
                        json.dump(report, output, indent=2, ensure_ascii=False, allow_nan=False)
                    if args.screenshot and not window.grab().save(str(args.screenshot)):
                        code = 1
                except (OSError, ValueError, TypeError):
                    code = 1
                window.close()
                app.exit(code)
            QTimer.singleShot(0, merger_check)
        elif args.smoke_test:
            def finish():
                if args.screenshot:
                    window.grab().save(str(args.screenshot))
                window.close()
            QTimer.singleShot(1200, finish)
        result = app.exec()
    finally:
        close_application_marker(marker)
        lock.unlock()
    if window.pending_update:
        try:
            runtime = TaskRuntime(directory)
            try:
                installer, manifest = window.pending_update
                runtime.application_action("update.install", {"installer": str(installer), "manifest": manifest,
                    "outcome_scope": "Installer process launch only; installed version requires later verification"},
                    lambda: launch_verified_update(installer, manifest))
            finally:
                runtime.close()
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(None, "CETA update did not start",
                                f"CETA closed safely, but the update could not start: {exc}\nOpen CETA to continue working or download the update again.")
            return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
