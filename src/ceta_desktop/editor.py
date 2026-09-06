from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class CodeHighlighter(QSyntaxHighlighter):
    """Lightweight visual hints, independent of parsing or execution semantics."""

    RULES = (
        (r"\b(?:class|def|return|import|from|if|else|elif|for|while|try|except|with|as|async|await|const|let|var|function|export|public|private|void|new|switch|case|break|continue|throw|raise|pass)\b", "#bca4ff"),
        (r"\b(?:True|False|None|true|false|null|\d+(?:\.\d+)?)\b", "#f1bf79"),
        (r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", "#89d6ac"),
        (r"(?:#|//).*$", "#8393a8"),
    )

    def highlightBlock(self, text):
        if len(text) > 20000:
            return
        for pattern, color in self.RULES:
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            for match in re.finditer(pattern, text):
                start = len(text[:match.start()].encode("utf-16-le")) // 2
                length = len(match.group().encode("utf-16-le")) // 2
                self.setFormat(start, length, style)


class LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.numbers = LineNumbers(self)
        self.highlighter = CodeHighlighter(self.document())
        self.blockCountChanged.connect(self.update_margins)
        self.updateRequest.connect(self.update_numbers)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.update_margins()

    def number_width(self):
        return 16 + self.fontMetrics().horizontalAdvance("9") * max(2, len(str(self.blockCount())))

    def update_margins(self, *_):
        self.setViewportMargins(self.number_width(), 0, 0, 0)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

    def update_numbers(self, rect, delta):
        if delta:
            self.numbers.scroll(0, delta)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_margins()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        contents = self.contentsRect()
        self.numbers.setGeometry(QRect(contents.left(), contents.top(), self.number_width(), contents.height()))

    def paint_numbers(self, event):
        painter = QPainter(self.numbers)
        painter.fillRect(event.rect(), QColor("#141c27"))
        painter.setPen(QColor("#6e8199"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.drawText(0, top, self.numbers.width() - 8, self.fontMetrics().height(), Qt.AlignRight, str(number + 1))
            top += height
            block = block.next()
            number += 1
