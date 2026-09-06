"""Native, plain-text conversation presentation with explicit code copying."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_EMPTY_HEADING = "A place to think and build."
_EMPTY_COPY = (
    "Connect a local model to start a conversation. "
    "Your workspace is never attached automatically."
)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)$")
_STYLE = """
QScrollArea#chatTranscript { background: transparent; border: none; }
QWidget#chatContent, QWidget#messageRow { background: transparent; }
QFrame#chatBubble { background: rgba(22, 30, 36, 240); border: 1px solid #303b43; border-radius: 13px; }
QFrame#chatBubble[role="user"] { background: rgba(29, 38, 46, 244); border-color: #39444c; }
QLabel#messageText { color: #ededee; background: transparent; border: none; font-size: 13px; }
QLabel#messageMeta { color: #a1a1a7; background: transparent; border: none; font-size: 11px; }
QLabel#senderLabel { color: #dadadd; background: transparent; border: none; font-weight: 600; }
QLabel#assistantAvatar { color: #ffb87d; border: 1px solid #a44920; border-radius: 17px;
    background: qradialgradient(cx:0.38, cy:0.32, radius:0.8,
        stop:0 #ff843a, stop:0.35 #b84717, stop:1 #311b16); font-weight: 700; }
QLabel#userAvatar { color: #d2d2d7; border: 1px solid #45454b;
    border-radius: 17px; background: #343438; font-weight: 600; }
QLabel#emptyOrb { color: #ffd5ad; border: 1px solid #b64b1b; border-radius: 36px;
    background: qradialgradient(cx:0.38, cy:0.30, radius:0.75,
        stop:0 #ffad64, stop:0.30 #e76420, stop:0.62 #7f2d14, stop:1 #271b19);
    font-size: 27px; font-weight: 700; }
QLabel#emptyHeading { color: #eeeeef; background: transparent; font-size: 23px; font-weight: 600; }
QLabel#emptyCopy { color: #a8a8b0; background: transparent; font-size: 13px; }
QFrame#codePanel { background: #171719; border: 1px solid #39393d; border-radius: 8px; }
QPlainTextEdit#codeText { color: #e0e0e7; background: #171719; border: none;
    selection-background-color: #75442e; padding: 5px; }
QPushButton#copyCodeButton { color: #c5c5ca; background: #27272b;
    border: 1px solid #434348; border-radius: 5px; padding: 4px 9px; }
QPushButton#copyCodeButton:hover { color: #fff0e1; border-color: #d16a34; }
QPushButton#copyCodeButton:focus { border: 2px solid #ef803e; }
"""


def _label(text: str, name: str, parent: QWidget | None = None) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    label.setOpenExternalLinks(False)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    return label


def _segments(content: str) -> list[tuple[str, str, str]]:
    """Recognize line fences, retaining every byte of their text interiors."""
    result: list[tuple[str, str, str]] = []
    collected: list[str] = []
    marker = ""
    language = ""
    for line in content.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        fence = _FENCE.fullmatch(bare)
        if not marker and fence:
            if collected:
                result.append(("text", "".join(collected), ""))
                collected = []
            marker, language = fence.groups()
            language = language.strip()
        elif marker and re.fullmatch(
            r" {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*", bare
        ):
            result.append(("code", "".join(collected), language))
            collected, marker, language = [], "", ""
        else:
            collected.append(line)
    if marker or collected:
        result.append(("code" if marker else "text", "".join(collected), language))
    return result


def _timestamp(record: Mapping[str, object]) -> str:
    value = record.get("created", record.get("created_at", record.get("timestamp")))
    try:
        if isinstance(value, datetime):
            moment = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            moment = datetime.fromtimestamp(value).astimezone()
        elif isinstance(value, str) and value.strip():
            moment = datetime.fromisoformat(value)
        else:
            return ""
        return moment.isoformat(sep=" ", timespec="minutes")
    except (ValueError, OverflowError, OSError):
        return ""


def _is_generating(record: Mapping[str, object]) -> bool:
    return record.get("role") == "assistant" and record.get("status") == "generating"


@dataclass(frozen=True)
class _Message:
    role: str
    content: str
    status: str
    timestamp: str
    model: str


class _CodePanel(QFrame):
    def __init__(self, code: str, language: str, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("codePanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._code = code
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 8)
        header = QHBoxLayout()
        self.language = _label(language or "Code", "messageMeta", self)
        self.language.setWordWrap(True)
        header.addWidget(self.language, 1)
        self.copy_button = QPushButton("Copy code", self)
        self.copy_button.setObjectName("copyCodeButton")
        self.copy_button.setAccessibleName("Copy code to clipboard")
        self.copy_button.clicked.connect(self._copy)
        header.addWidget(self.copy_button)
        layout.addLayout(header)
        self.editor = QPlainTextEdit(self)
        self.editor.setObjectName("codeText")
        self.editor.setAccessibleName("Code block")
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.editor)
        self.update_code(code, language)

    def update_code(self, code: str, language: str) -> None:
        """Refresh a changed code block without replacing its native editor."""
        self._code = code
        self.language.setText(language or "Code")
        if self.editor.toPlainText() != code.replace("\r\n", "\n"):
            self.editor.setPlainText(code)
        lines = min(14, max(2, code.count("\n") + 1))
        self.editor.setFixedHeight(lines * self.editor.fontMetrics().lineSpacing() + 28)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._code)


class _MessageRow(QWidget):
    def __init__(self, message: _Message, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("messageRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.message: _Message | None = None
        self.parts: list[tuple[str, QWidget]] = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        user = message.role == "user"
        if user:
            row.addStretch(1)
        avatar = _label("U" if user else "C", "userAvatar" if user else "assistantAvatar", self)
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setAccessibleName("You" if user else "CETA")
        avatar.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        self.column = QWidget(self)
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        column = QVBoxLayout(self.column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(7)
        self.sender = _label("", "senderLabel", self.column)
        self.sender.setWordWrap(True)
        column.addWidget(self.sender)
        self.bubble = QFrame(self.column)
        self.bubble.setObjectName("chatBubble")
        self.bubble.setProperty("role", message.role)
        self.body = QVBoxLayout(self.bubble)
        self.body.setContentsMargins(16, 13, 16, 13)
        self.body.setSpacing(10)
        column.addWidget(self.bubble)
        self.meta = _label("", "messageMeta", self.column)
        self.meta.setWordWrap(True)
        column.addWidget(self.meta)
        row.addWidget(self.column, 4)
        if not user:
            row.addStretch(1)
        self.update_message(message)

    def update_message(self, message: _Message) -> None:
        """Keep unchanged text and code panels intact during streaming."""
        if message == self.message:
            return
        self.message = message
        sender = {"user": "You", "assistant": "CETA", "system": "System"}.get(
            message.role, message.role
        )
        if message.role == "assistant" and message.model:
            sender += "  ·  " + message.model
        self.sender.setText(sender)
        meta = [message.timestamp] if message.timestamp else []
        if message.status and message.status != "complete":
            meta.append(message.status)
        self.meta.setText("  ·  ".join(meta))
        self.meta.setVisible(bool(meta))
        segments = _segments(message.content)
        for index, (kind, content, language) in enumerate(segments):
            if index < len(self.parts) and self.parts[index][0] != kind:
                old = self.parts[index][1]
                self.body.removeWidget(old)
                old.hide()
                old.deleteLater()
                self.parts[index] = (kind, self._part(kind, content, language))
                self.body.insertWidget(index, self.parts[index][1])
            elif index >= len(self.parts):
                part = self._part(kind, content, language)
                self.parts.append((kind, part))
                self.body.addWidget(part)
            else:
                part = self.parts[index][1]
                if isinstance(part, _CodePanel):
                    part.update_code(content, language)
                elif isinstance(part, QLabel):
                    part.setText(content.strip("\r\n"))
        while len(self.parts) > len(segments):
            old = self.parts.pop()[1]
            self.body.removeWidget(old)
            old.hide()
            old.deleteLater()
        self.bubble.setVisible(bool(segments))

    def _part(self, kind: str, content: str, language: str) -> QWidget:
        if kind == "code":
            return _CodePanel(content, language, self.bubble)
        label = _label(content.strip("\r\n"), "messageText", self.bubble)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return label


class ChatTranscript(QScrollArea):
    """Scrollable native messages; content is never interpreted as HTML or code."""

    MAX_MESSAGES = 200

    def __init__(self, parent: QWidget | None = None):
        """Create an empty offline conversation surface."""
        super().__init__(parent)
        self.setObjectName("chatTranscript")
        self.setAccessibleName("Conversation")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(_STYLE)
        self._messages: tuple[_Message, ...] = ()
        self._rows: list[_MessageRow] = []
        self._follow_tail = True
        self._restoring = False
        self._scroll_anchor: tuple[bool, int] | None = None
        self._content = QWidget(self)
        self._content.setObjectName("chatContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(22, 26, 22, 26)
        self._layout.setSpacing(22)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.setWidget(self._content)
        self.viewport().setAutoFillBackground(False)
        self._content.setAutoFillBackground(False)
        self._empty = QWidget(self._content)
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(22, 40, 22, 40)
        empty_layout.setSpacing(17)
        empty_layout.addStretch(1)
        orb = _label("C", "emptyOrb", self._empty)
        orb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        orb.setFixedSize(72, 72)
        empty_layout.addWidget(orb, 0, Qt.AlignmentFlag.AlignHCenter)
        self._empty_labels = []
        for text, name in ((_EMPTY_HEADING, "emptyHeading"), (_EMPTY_COPY, "emptyCopy")):
            label = _label(text, name, self._empty)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setMaximumWidth(440)
            self._empty_labels.append(label)
            empty_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self._layout.addWidget(self._empty)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._restore_scroll)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)

    def render_messages(
        self,
        messages: Sequence[Mapping[str, object]],
        pending_text: str = "",
        model_name: str = "",
    ) -> None:
        """Render at most 200 actual records, replacing the active streamed row."""
        records = list(messages[-self.MAX_MESSAGES:])
        if pending_text:
            active = next((record for record in reversed(records) if _is_generating(record)), {})
            records = [record for record in records if not _is_generating(record)]
            records.append(
                dict(active, role="assistant", content=pending_text, status="generating")
            )
        normalized = tuple(
            _Message(str(record.get("role", "assistant")), str(record.get("content", "")),
                     str(record.get("status", "complete")), _timestamp(record), str(model_name))
            for record in records[-self.MAX_MESSAGES:]
        )
        if normalized == self._messages:
            return
        self._scroll_anchor = (self._follow_tail, self.verticalScrollBar().value())
        self._messages = normalized
        self._empty.setVisible(not normalized)
        for index, message in enumerate(normalized):
            if index < len(self._rows) and self._rows[index].message.role != message.role:
                old = self._rows[index]
                self._layout.removeWidget(old)
                old.hide()
                old.deleteLater()
                self._rows[index] = _MessageRow(message, self._content)
                self._layout.insertWidget(index + 1, self._rows[index])
            elif index >= len(self._rows):
                row = _MessageRow(message, self._content)
                self._rows.append(row)
                self._layout.addWidget(row)
            else:
                self._rows[index].update_message(message)
        while len(self._rows) > len(normalized):
            old = self._rows.pop()
            self._layout.removeWidget(old)
            old.hide()
            old.deleteLater()
        self._size_rows()
        self._scroll_timer.start(0)

    def toPlainText(self) -> str:
        """Provide the original displayed message text for native UI consumers."""
        if not self._messages:
            return _EMPTY_HEADING + "\n\n" + _EMPTY_COPY
        chunks = []
        for message in self._messages:
            title = {"user": "You", "assistant": "Assistant", "system": "System"}.get(
                message.role, message.role
            )
            if message.status and message.status != "complete":
                title += " · " + message.status
            if message.timestamp:
                title += " · " + message.timestamp
            chunks.append(title + "\n" + message.content)
        return "\n\n".join(chunks)

    def resizeEvent(self, event) -> None:
        """Keep bubbles within the conversation viewport."""
        super().resizeEvent(event)
        if hasattr(self, "_empty"):
            self._size_rows()

    def _size_rows(self) -> None:
        width = max(120, min(760, int((self.viewport().width() - 88) * 0.85)))
        for row in self._rows:
            row.column.setMaximumWidth(width)
        self._empty.setMinimumHeight(max(300, self.viewport().height() - 52))
        for label in self._empty_labels:
            width = min(440, max(180, self.viewport().width() - 100))
            label.setFixedWidth(width)
            label.setMinimumHeight(max(28, label.heightForWidth(width)))

    def _scrolled(self, value: int) -> None:
        if not self._restoring and self._scroll_anchor is None:
            self._follow_tail = self.verticalScrollBar().maximum() - value <= 20

    def _range_changed(self, _minimum: int, _maximum: int) -> None:
        if self._scroll_anchor is None and self._follow_tail:
            self._scroll_anchor = (True, 0)
        if self._scroll_anchor is not None:
            self._scroll_timer.start(0)

    def _restore_scroll(self) -> None:
        if self._scroll_anchor is None:
            return
        follow, value = self._scroll_anchor
        self._restoring = True
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() if follow else min(value, scrollbar.maximum()))
        self._restoring = False
        self._follow_tail = follow
        self._scroll_anchor = None
