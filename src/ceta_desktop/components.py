"""Shared UI component builders and layout helpers for CETA desktop pages."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QFrame, QLabel, QListWidget, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .theme import ScenePage, icon


def button(text: str, callback: Callable) -> QPushButton:
    control = QPushButton(text)
    control.clicked.connect(callback)
    return control


def action(text: str, callback: Callable, symbol: str | None = None, primary: bool = False) -> QPushButton:
    control = button(text, callback)
    control.setObjectName("primaryButton" if primary else "secondaryButton")
    if symbol:
        control.setIcon(icon(symbol, "#ff943f" if primary else "#c0c7cf"))
    control.setMinimumHeight(38)
    return control


def page(title: str, subtitle: str) -> tuple[ScenePage, QVBoxLayout]:
    scenepage = ScenePage(scene=title.lower())
    outer = QVBoxLayout(scenepage)
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
    return scenepage, layout


def card(title: str, description: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
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
    return frame, layout


def filter_list(listing: QListWidget, query: str) -> None:
    for index in range(listing.count()):
        item = listing.item(index)
        item.setHidden(query.casefold() not in item.text().casefold())
