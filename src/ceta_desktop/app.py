from __future__ import annotations

import argparse
from importlib.resources import files
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime

from PySide6.QtCore import QDir, QSize, QLockFile, QProcess, QProcessEnvironment, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QFont, QIcon, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QFileDialog, QFileSystemModel, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTreeView,
    QVBoxLayout, QWidget,
)

from . import __version__
from .models import LocalModelClient, ModelPacks
from .storage import Store, application_directory
from .workspace import Document, Workspace
from .updates import check_update, download_update
from .instance import open_application_marker, close_application_marker
from .installation import launch_verified_update
from .editor import CodeEditor
from .theme import APP_STYLESHEET, BrandMark, EmberSidebar, ScenePage, icon
from .chat_widgets import ChatTranscript


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


def button(text, callback):
    result = QPushButton(text)
    result.clicked.connect(callback)
    return result


class MainWindow(QMainWindow):
    def __init__(self, directory: Path):
        super().__init__()
        self.store = Store(directory)
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
        self.workload_cancelled = False
        self.pack_download_client = None
        self.model_process = QProcess(self)
        self.model_process.setProcessChannelMode(QProcess.MergedChannels)
        self.model_process.readyReadStandardOutput.connect(self._model_output)
        self.model_process.errorOccurred.connect(lambda error: self.model_status.setText(self.model_process.errorString()))
        self.model_process.finished.connect(lambda *_: self.model_status.setText("Local model stopped"))
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
        self.pages = QStackedWidget()
        self.pages.addWidget(self._chat_page())
        self.pages.addWidget(self._workbench())
        self.pages.addWidget(self._library_page())
        self.pages.addWidget(self._models_page())
        self.pages.addWidget(self._workloads_page())
        self.pages.addWidget(self._updates_page())
        self.pages.addWidget(self._settings_page())
        self._connect_model_selectors()
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
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
        control = button(text, callback)
        control.setObjectName("primaryButton" if primary else "secondaryButton")
        if symbol:
            control.setIcon(icon(symbol, "#ff943f" if primary else "#c0c7cf"))
        control.setMinimumHeight(38)
        return control

    def _page(self, title, subtitle):
        page = ScenePage(scene=title.lower())
        outer = QVBoxLayout(page)
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
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        description = QLabel(subtitle)
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(description)
        scroll.setWidget(content)
        content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)
        return page, layout

    def _card(self, title, description=None):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        label = QLabel(title)
        label.setObjectName("pageHeader")
        layout.addWidget(label)
        if description:
            body = QLabel(description)
            body.setWordWrap(True)
            body.setObjectName("muted")
            layout.addWidget(body)
        return card, layout

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
        layout.addWidget(splitter, 1)
        return page

    def _library_page(self):
        page, layout = self._page("Library", "Pick up a conversation or export a copy. Your saved work stays on this computer.")
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("Find a saved conversation…")
        self.library_search.setAccessibleName("Search library")
        self.library_search.addAction(icon("search"), QLineEdit.LeadingPosition)
        self.library_search.textChanged.connect(self._filter_library)
        layout.addWidget(self.library_search)
        self.library_list = QListWidget()
        self.library_list.setObjectName("conversationList")
        self.library_list.setAccessibleName("Conversation library")
        self.library_list.itemDoubleClicked.connect(self._select_conversation)
        self.library_empty = QLabel("Your library starts with a conversation.\nSaved chats appear here, ready to continue or export.")
        self.library_empty.setObjectName("emptyBody")
        self.library_empty.setAlignment(Qt.AlignCenter)
        self.library_empty.setWordWrap(True)
        layout.addWidget(self.library_empty, 1)
        layout.addWidget(self.library_list, 1)
        row = QHBoxLayout()
        row.addWidget(self._action("Continue conversation", self._open_library_conversation, "chat", primary=True))
        row.addWidget(self._action("Export selected…", self._export_library_conversation, "file"))
        row.addStretch()
        row.addWidget(self._action("Open project files", lambda: self.navigation.setCurrentRow(1), "folder"))
        layout.addLayout(row)
        return page

    def _open_library_conversation(self):
        item = self.library_list.currentItem()
        if item:
            self._select_conversation(item)

    def _export_library_conversation(self):
        item = self.library_list.currentItem()
        if item:
            self._export_conversation_id(item.data(Qt.UserRole))

    def _filter_conversations(self, query):
        self._filter_list(self.conversation_list, query)

    def _filter_library(self, query):
        self._filter_list(self.library_list, query)

    @staticmethod
    def _filter_list(listing, query):
        for index in range(listing.count()):
            item = listing.item(index)
            item.setHidden(query.casefold() not in item.text().casefold())

    def _models_page(self):
        page, layout = self._page("Models", "Your intelligence, your choice. Install optional packs or connect to a local runtime.")
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
        form.addRow("Active model", self.model_combo)
        service_layout.addLayout(form)
        controls = QHBoxLayout()
        controls.addWidget(self._action("Connect / refresh models", self.refresh_models, "refresh", primary=True))
        controls.addWidget(self._action("Start installed Ollama", self.start_ollama, "models"))
        controls.addStretch()
        service_layout.addLayout(controls)
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
        row.addWidget(self._action("Stop local model", lambda: self._stop_process(self.model_process)))
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
        page, layout = self._page("Settings", "Make CETA feel at home. These preferences are saved on this computer.")
        editor_card, editor_layout = self._card("Editor preferences")
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
        self._apply_editor_preferences()
        layout.addWidget(editor_card)
        privacy, privacy_layout = self._card("Local data & privacy", "Conversations, drafts, command history, and settings are kept in your local application data. CETA does not attach workspace files automatically.")
        path = QLineEdit(str(self.store.directory))
        path.setReadOnly(True)
        path.setAccessibleName("CETA application data folder")
        privacy_layout.addWidget(path)
        privacy_layout.addWidget(self._action("Open data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.directory))), "folder"), 0, Qt.AlignLeft)
        note = QLabel("Local storage uses your Windows account's file permissions. Export conversations only when you choose to share them. Review separately started model runtimes' privacy settings before connecting.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        privacy_layout.addWidget(note)
        layout.addWidget(privacy)
        shortcuts, shortcut_layout = self._card("Keyboard shortcuts")
        shortcut_layout.addWidget(QLabel("Ctrl+N  New chat     ·     Ctrl+O  Open workspace     ·     Ctrl+S  Save file\nCtrl+F  Find in file     ·     Ctrl+Shift+N  New file     ·     Ctrl+Shift+E  Export chat"))
        layout.addWidget(shortcuts)
        layout.addStretch()
        return page

    def _apply_editor_preferences(self):
        size = self.editor_font_size.value()
        self.editor.setFont(QFont("Cascadia Mono", size))
        self.editor.setStyleSheet(f"QPlainTextEdit {{ font-family: 'Cascadia Mono'; font-size: {size}pt; }}")
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth if self.editor_wrap.isChecked() else QPlainTextEdit.NoWrap)

    def _save_editor_preferences(self, *_):
        self.store.set_setting("editor_font_size", self.editor_font_size.value())
        self.store.set_setting("editor_wrap", self.editor_wrap.isChecked())
        self._apply_editor_preferences()


    def _load_workloads(self):
        self.workload_history.clear()
        for record in self.store.workloads():
            self.workload_history.addItem(f"{record['status']} · {record['command'][:100]}")
            self.workload_history.item(self.workload_history.count() - 1).setData(Qt.UserRole, record)

    def _select_workload(self, item, _previous):
        if item:
            record = item.data(Qt.UserRole)
            if record:
                self.history_output.setPlainText(f"Workspace: {record['workspace']}\nCommand: {record['command']}\nStatus: {record['status']}\nExit: {record['exit_code']}\n\n{record['output']}")

    def _updates_page(self):
        page, layout = self._page("Updates", "Keep your workspace moving forward. Updates happen when you choose.")
        release, release_layout = self._card(f"CETA {__version__}", "Windows native desktop · Personal publisher verification")
        self.update_status = QLabel("No public update channel is configured for this development build.")
        self.update_status.setWordWrap(True)
        self.update_status.setObjectName("muted")
        self.update_channel = json.loads(files("ceta_desktop").joinpath("release_channel.json").read_text(encoding="utf-8"))
        if self.update_channel.get("url") and self.update_channel.get("public_key"):
            self.update_status.setText("Ready to check the publisher's signed update channel.")
        self.update_manifest = None
        release_layout.addWidget(self.update_status)
        row = QHBoxLayout()
        self.check_update_button = self._action("Check for updates", self.check_for_updates, "refresh", primary=True)
        self.check_update_button.setEnabled(bool(self.update_channel.get("url") and self.update_channel.get("public_key")))
        row.addWidget(self.check_update_button)
        self.download_update_button = self._action("Download verified update…", self.save_update, "updates")
        self.download_update_button.setEnabled(False)
        row.addWidget(self.download_update_button)
        row.addStretch()
        release_layout.addLayout(row)
        install_row = QHBoxLayout()
        self.cancel_update_button = self._action("Cancel download", self.cancel_update_download)
        self.cancel_update_button.setEnabled(False)
        install_row.addWidget(self.cancel_update_button)
        self.install_update_button = self._action("Install update and close CETA…", self.install_update, "updates", primary=True)
        self.install_update_button.setEnabled(False)
        install_row.addWidget(self.install_update_button)
        install_row.addStretch()
        release_layout.addLayout(install_row)
        layout.addWidget(release)
        security, security_layout = self._card("A signature you can verify", "CETA verifies the publisher's signed update receipt and the installer's exact bytes before offering installation. Application updates are separate from model packs.")
        note = QLabel("This release uses a personal Ed25519 publisher key. Windows may show an unrecognized-publisher warning. Confirm the public-key fingerprint directly with the publisher. No root certificate is installed.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        security_layout.addWidget(note)
        layout.addWidget(security)
        about, about_layout = self._card("Built for your computer", "Conversations, settings, and model packs are retained during updates. Close active work before installing.")
        notice = QLabel("Built with Qt, PySide6, and Shiboken under LGPLv3. License texts and matching library sources accompany this release.")
        notice.setWordWrap(True)
        notice.setObjectName("muted")
        about_layout.addWidget(notice)
        notices = QHBoxLayout()
        notices.addWidget(self._action("About Qt", QApplication.aboutQt))
        notices.addWidget(self._action("Dependency notices", self.open_dependency_notices, "library"))
        notices.addStretch()
        about_layout.addLayout(notices)
        layout.addWidget(about)
        layout.addStretch()
        return page

    def open_dependency_notices(self):
        directory = Path(sys.executable).parent / "ThirdPartyNotices" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "licenses"
        if not directory.is_dir() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            self.update_status.setText(f"Dependency notices: {directory}")

    def check_for_updates(self):
        if self.update_task:
            return
        self.update_manifest = None
        self.downloaded_update = None
        self.install_update_button.setEnabled(False)
        self.download_update_button.setEnabled(False)
        self.check_update_button.setEnabled(False)
        self.update_status.setText("Checking the publisher's signed update information…")

        def found(manifest):
            self.update_manifest = manifest
            self.update_status.setText(f"CETA {manifest['version']} is available. Publisher signature verified.")
            self.download_update_button.setEnabled(True)

        task = self._background(lambda _: check_update(self.update_channel["url"], self.update_channel["public_key"], __version__),
                                found, lambda error: self.update_status.setText(str(error)))
        task.finished.connect(lambda: self.check_update_button.setEnabled(True))

    def save_update(self):
        if not self.update_manifest or self.update_task:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save verified update")
        if not folder:
            return
        self.download_update_button.setEnabled(False)
        self.check_update_button.setEnabled(False)
        self.cancel_update_button.setEnabled(True)
        self.update_status.setText("Downloading and verifying the update…")
        self.downloaded_update = None
        self.install_update_button.setEnabled(False)
        manifest = dict(self.update_manifest)
        task = self._background(lambda task: download_update(manifest, Path(folder), task.cancelled,
                                lambda count, total: task.token.emit(f"Downloading update · {count / total:.0%}")),
                                lambda path: self._update_saved(path, manifest),
                                lambda error: self.update_status.setText(str(error)))
        self.update_task = task
        task.token.connect(self.update_status.setText)
        task.finished.connect(self._update_download_finished)

    def cancel_update_download(self):
        if self.update_task:
            self.update_task.cancelled.set()
            self.cancel_update_button.setEnabled(False)
            self.update_status.setText("Cancelling update download…")

    def _update_download_finished(self):
        self.update_task = None
        self.check_update_button.setEnabled(True)
        self.download_update_button.setEnabled(True)
        self.cancel_update_button.setEnabled(False)

    def _update_saved(self, path, manifest):
        self.downloaded_update = (Path(path), dict(manifest))
        self.install_update_button.setEnabled(os.name == "nt")
        self.update_status.setText(f"Verified update saved to {path}. Choose Install update when ready. Your conversations and model packs are retained.")

    def install_update(self):
        if not self.downloaded_update or os.name != "nt":
            return
        if self.tasks or self.chat_task or self.process.state() != QProcess.NotRunning:
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

    def _error(self, message):
        self.statusBar().showMessage(str(message))
        QMessageBox.warning(self, "CETA", str(message))

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
        if self.process.state() != QProcess.NotRunning:
            self._error("Stop the running workload before switching workspaces.")
            return
        if not self._discard_allowed():
            return
        folder = QFileDialog.getExistingDirectory(self, "Open workspace")
        if folder:
            self._set_workspace(Path(folder))
            self._clear_editor_draft()
            self.navigation.setCurrentRow(1)

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
            with path.open("x", encoding="utf-8"):
                pass
            self.document = self.workspace.open(path)
            self._clear_editor_draft()
            self.editor.setPlainText("")
            self.editor.document().setModified(False)
            self.editor.setEnabled(True)
            self._editor_changed()
        except (ValueError, OSError) as exc:
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
        self.workspace = Workspace(path)
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
            self.document = self.workspace.open(Path(self.file_model.filePath(index)))
            self._clear_editor_draft()
            self.editor.setPlainText(self.document.text)
            self.editor.document().setModified(False)
            self.editor.setEnabled(True)
            self.file_label.setText(str(self.document.path.relative_to(self.workspace.root)))
        except (ValueError, OSError) as exc:
            self._error(exc)

    def _editor_changed(self):
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
            self.document = self.workspace.open(Path(draft["path"]))
            self.document.digest = draft["digest"]
            self.editor.setPlainText(draft["text"])
            self.editor.document().setModified(True)
            self.editor.setEnabled(True)
            self._editor_changed()
            self.statusBar().showMessage("Recovered an unsaved editor draft. Review it before saving.")
        except (ValueError, OSError, KeyError) as exc:
            self.store.set_setting("editor_draft", draft)
            self.statusBar().showMessage(f"An editor draft is retained in local data but could not be reopened: {exc}")

    def save_document(self):
        if not self.document or not self.workspace:
            return True
        try:
            self.workspace.save(self.document, self.editor.toPlainText())
            self.editor.document().setModified(False)
            self.draft_timer.stop()
            self.store.set_setting("editor_draft", None)
            self._editor_changed()
            self.statusBar().showMessage("File saved")
            return True
        except (ValueError, OSError) as exc:
            self._error(exc)
            return False

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
        if self.conversation_id is None and self.conversation_list.count():
            self.conversation_id = self.conversation_list.item(0).data(Qt.UserRole)
            self.conversation_list.setCurrentRow(0)
        self.conversation_empty.setVisible(not conversations)
        self.library_empty.setVisible(not conversations)
        self.library_list.setVisible(bool(conversations))
        self._filter_conversations(self.conversation_search.text())
        self._filter_library(self.library_search.text())
        self._render_chat()

    def _save_prompt_draft(self):
        self.store.set_setting("chat_draft:" + (self.conversation_id or "new"), self.prompt.toPlainText())

    def _restore_prompt_draft(self):
        self.prompt_timer.stop()
        self.prompt.blockSignals(True)
        self.prompt.setPlainText(self.store.setting("chat_draft:" + (self.conversation_id or "new"), ""))
        self.prompt.blockSignals(False)

    def _switch_conversation(self, identifier):
        self._save_prompt_draft()
        self.conversation_id = identifier
        self.store.set_setting("active_conversation", identifier)
        self._restore_prompt_draft()

    def _render_chat(self):
        records = self.store.messages(self.conversation_id) if self.conversation_id else []
        self.chat_view.render_messages(records, pending_text=self.assistant_text,
                                       model_name=self.model_combo.currentText())

    def new_conversation(self):
        if self.chat_task:
            self.chat_status.setText("Stop the current response before starting another conversation.")
            return
        self._switch_conversation(self.store.new_conversation())
        self.assistant_text = ""
        self._load_conversations()
        self.navigation.setCurrentRow(0)
        self.prompt.setFocus()

    def _select_conversation(self, item):
        if self.chat_task:
            return
        self._switch_conversation(item.data(Qt.UserRole))
        self._render_chat()
        self.navigation.setCurrentRow(0)

    def export_conversation(self):
        self._export_conversation_id(self.conversation_id)

    def _export_conversation_id(self, identifier):
        if not identifier:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Export conversation", "conversation.json", "JSON (*.json)")
        if destination:
            try:
                with Path(destination).open("x", encoding="utf-8") as handle:
                    json.dump(self.store.messages(identifier), handle, indent=2, ensure_ascii=False)
            except OSError as exc:
                self._error(exc)

    def send_message(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt or self.chat_task:
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
        if not self.conversation_id:
            self.conversation_id = self.store.new_conversation()
            self.store.set_setting("chat_draft:new", "")
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
        self.chat_status.setText(f"Generating with {model}…")

        def generate(task):
            for token in client.stream(model, messages):
                task.token.emit(token)
            return "cancelled" if client.cancelled.is_set() else "complete"

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
        self.send_button.setEnabled(True)
        self.stop_chat_button.setEnabled(False)
        if task:
            task.deleteLater()

    def stop_chat(self):
        if self.client:
            self.client.cancel()
            self.chat_status.setText("Stopping response…")

    def refresh_models(self):
        try:
            client = LocalModelClient(self.endpoint.text().strip())
        except ValueError as exc:
            self.model_status.setText(str(exc))
            return
        self.model_status.setText("Connecting to local model service…")

        def loaded(models):
            selected = self.model_combo.currentText()
            self.model_combo.clear()
            self.model_combo.addItems(models)
            if selected in models:
                self.model_combo.setCurrentText(selected)
            self.store.set_setting("endpoint", self.endpoint.text().strip())
            self.model_status.setText(f"Connected · {len(models)} available models")
            self.chat_status.setText("Local model connected. Ready to chat." if models else "The local service has no installed models.")

        self._background(lambda _: client.available_models(), loaded,
                         lambda error: self.model_status.setText(f"Could not connect: {error}"))

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

        task = self._background(lambda task: self.packs.install(Path(source), task.cancelled), installed,
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

        def start(verified):
            if self.model_process.state() != QProcess.NotRunning:
                self.model_status.setText("Another model service is already running.")
                return
            self.model_log.clear()
            self.model_process.setProgram(executable)
            self.model_process.setArguments(["--model", verified["path"], "--host", "127.0.0.1", "--port", "8081", "--ctx-size", "8192"])
            self.model_process.start()
            self.endpoint.setText("http://127.0.0.1:8081/v1")
            self.model_status.setText("Starting local model… Connect / refresh models when it is ready.")

        self._background(lambda task: self.packs.verify_installed(record["sha256"], task.cancelled), start,
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
        self.model_process.setProcessEnvironment(environment)
        self.model_process.start()
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

        def pull(task):
            for status in client.pull_ollama_model(name):
                task.token.emit(status)
            return "cancelled" if client.cancelled.is_set() else "installed"

        def complete(status):
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
        if not self.workspace or not command or self.process.state() != QProcess.NotRunning:
            self.statusBar().showMessage("Open a workspace and enter a command first.")
            return
        self.workload_id = self.store.start_workload(self.workspace.root, command)
        self.workload_output = ""
        self.workload_cancelled = False
        self.output.clear()
        self.process.setWorkingDirectory(str(self.workspace.root))
        if os.name == "nt":
            self.process.setProgram(str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"))
            self.process.setArguments(["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command])
        else:
            self.process.setProgram("/bin/sh")
            self.process.setArguments(["-c", command])
        self.run_button.setEnabled(False)
        self.stop_work_button.setEnabled(True)
        self.process.start()

    def _workload_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.workload_output = (self.workload_output + text)[-2 * 1024 * 1024:]
        self.output.insertPlainText(text)
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def _workload_error(self, error):
        if error == QProcess.FailedToStart:
            self.workload_output += self.process.errorString()
            self.output.appendPlainText(self.process.errorString())
            self._workload_finished(-1, QProcess.CrashExit)

    def _workload_finished(self, code, status):
        self._workload_output()
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
        self._stop_process(self.process)

    def closeEvent(self, event: QCloseEvent):
        if not self._discard_allowed():
            event.ignore()
            return
        if self.chat_task or self.tasks:
            self.stop_chat()
            self.cancel_model_download()
            for task in self.tasks:
                task.cancelled.set()
            self.statusBar().showMessage("Stopping background work. Close again when it has finished.")
            event.ignore()
            return
        self.stop_workload()
        self._stop_process(self.model_process)
        self.process.waitForFinished(3000)
        self.model_process.waitForFinished(3000)
        self.draft_timer.stop()
        self._clear_editor_draft()
        self.prompt_timer.stop()
        self._save_prompt_draft()
        self.store.close()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="CETA native desktop environment")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
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
        if args.smoke_test:
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
            launch_verified_update(*window.pending_update)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(None, "CETA update did not start",
                                f"CETA closed safely, but the update could not start: {exc}\nOpen CETA to continue working or download the update again.")
            return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
