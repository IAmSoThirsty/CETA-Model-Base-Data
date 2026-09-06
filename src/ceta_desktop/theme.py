"""CETA's native ember palette, painted sidebar, and resolution-aware line icons."""

from __future__ import annotations

from importlib.resources import files
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QPolygonF, QRadialGradient,
)
from PySide6.QtWidgets import QWidget


APP_STYLESHEET = """
QWidget {
    color: #e6ebef;
    font-family: "Segoe UI";
    font-size: 14px;
}
QMainWindow, QWidget#appShell, QStackedWidget { background: #0b1014; }
QDialog, QMessageBox, QInputDialog, QFileDialog { background: #11171d; }
QLabel { background: transparent; }
QWidget#sidebar { border: none; }
QWidget#chatRail { background: #0c1115; border-right: 1px solid #252d34; }
QWidget#chatHeader {
    background: #0d1216;
    border-bottom: 1px solid #242c33;
}
QWidget#pageContent { background: transparent; }
QLabel#pageHeader { background: transparent; border: none; font-size: 18px; font-weight: 600; }
QLabel#brandName { color: #f7f8fa; font-size: 27px; font-weight: 600; }
QLabel#brandTagline { color: #99a4ae; font-size: 10px; }
QLabel#sidebarMotto { color: #c0c8cf; font-size: 14px; font-style: italic; }
QLabel#pageTitle { color: #f4f6f8; font-size: 25px; font-weight: 600; }
QLabel#pageSubtitle { color: #a1acb7; font-size: 13px; }
QLabel#eyebrow { color: #acb6bf; font-size: 11px; font-weight: 600; }
QLabel#muted { color: #9aa6b2; font-size: 12px; }
QLabel#emptyTitle { color: #f0f2f5; font-size: 25px; font-weight: 600; }
QLabel#emptyBody { color: #a2afb9; font-size: 14px; }
QLabel#privacyBadge {
    color: #86e9aa;
    background: #11211c;
    border: 1px solid #29463b;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
}
QWidget#card, QFrame#card {
    background: rgba(20, 27, 33, 235);
    border: 1px solid #2a353e;
    border-radius: 11px;
}
QWidget#composer {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #151d24, stop:1 #11191f);
    border: 1px solid #3a4650;
    border-radius: 12px;
}
QWidget#composer QPlainTextEdit, QWidget#composer QTextEdit {
    background: transparent;
    border: none;
    padding: 10px 12px;
}
QWidget#composer QPlainTextEdit:focus, QWidget#composer QTextEdit:focus {
    background: #171f25;
    border: 1px solid #ca742e;
    border-radius: 7px;
}
QListWidget, QTreeView, QTableView, QPlainTextEdit, QTextEdit, QTextBrowser,
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {
    background: #10171d;
    color: #e6ebef;
    border: 1px solid #2c3740;
    border-radius: 7px;
    padding: 8px;
    selection-background-color: #604027;
    selection-color: #ffffff;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {
    min-height: 22px;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus,
QTextBrowser:focus, QTreeView:focus, QTableView:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {
    border-color: #ed913f;
}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
    color: #7b8791;
    background: #10151a;
    border-color: #242c33;
}
QComboBox { padding-right: 30px; }
QComboBox QLineEdit { padding: 0 3px; border: none; background: transparent; min-height: 0; }
QComboBox::drop-down {
    width: 27px;
    border: none;
    border-left: 1px solid #2a353d;
}
QComboBox QAbstractItemView {
    background: #182028;
    color: #edf0f3;
    border: 1px solid #3a4650;
    selection-background-color: #48301f;
    padding: 5px;
}
QListWidget::item, QTreeView::item, QTableView::item { padding: 7px 6px; }
QListWidget::item:hover, QTreeView::item:hover, QTableView::item:hover {
    background: #1b252d;
}
QListWidget::item:selected, QTreeView::item:selected, QTableView::item:selected {
    background: #30251d;
    color: #ffbb79;
}
QListWidget#navigation {
    background: transparent;
    border: none;
    padding: 0;
}
QListWidget#navigation::item {
    color: #bcc7d0;
    min-height: 24px;
    padding: 10px 13px;
    margin: 3px 0;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    border-radius: 7px;
}
QListWidget#navigation::item:hover { background: #151b20; color: #ffffff; }
QListWidget#navigation::item:selected {
    color: #ff9d45;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #362115, stop:1 #171715);
    border-left: 3px solid #ff912d;
}
QListWidget#navigation::item:focus { border-top-color: #985c2f; border-bottom-color: #985c2f; }
QListWidget#conversationList {
    background: transparent;
    border: none;
    padding: 0;
}
QListWidget#conversationList::item {
    color: #dfe5ea;
    padding: 11px 10px;
    margin: 2px 0;
    border: 1px solid transparent;
    border-left: 2px solid transparent;
    border-radius: 7px;
}
QListWidget#conversationList::item:hover { background: #151c22; }
QListWidget#conversationList::item:selected {
    background: #1b242b;
    color: #ffffff;
    border-left: 2px solid #f38b32;
}
QListWidget#conversationList::item:focus { border-top-color: #985c2f; border-bottom-color: #985c2f; }
QPushButton, QToolButton {
    color: #dfe6ec;
    background: #18222b;
    border: 1px solid #35414a;
    border-radius: 7px;
    padding: 9px 14px;
    min-height: 20px;
}
QPushButton:hover, QToolButton:hover { background: #24303a; border-color: #586673; }
QPushButton:pressed, QToolButton:pressed { background: #111b22; }
QPushButton:focus, QToolButton:focus { border-color: #ffab60; }
QPushButton:disabled, QToolButton:disabled {
    color: #74818c;
    background: #141b21;
    border-color: #283139;
}
QPushButton#primaryButton, QToolButton#primaryButton {
    color: #fff0e2;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #633316, stop:1 #3d2313);
    border: 1px solid #f38c32;
    font-weight: 600;
}
QPushButton#primaryButton:hover, QToolButton#primaryButton:hover {
    background: #75401d;
    border-color: #ffb264;
}
QPushButton#primaryButton:pressed, QToolButton#primaryButton:pressed { background: #3e2516; }
QPushButton#primaryButton:focus, QToolButton#primaryButton:focus { border: 2px solid #ffd0a0; padding: 8px 13px; }
QPushButton#primaryButton:disabled, QToolButton#primaryButton:disabled {
    background: #2a231e;
    border-color: #60472f;
    color: #a4978a;
}
QPushButton#secondaryButton, QToolButton#secondaryButton {
    background: #1b1814;
    border: 1px solid #cf762d;
    color: #ffad68;
}
QPushButton#secondaryButton:hover, QToolButton#secondaryButton:hover { background: #36271c; }
QPushButton#secondaryButton:focus, QToolButton#secondaryButton:focus { border-color: #ffd0a0; }
QPushButton#secondaryButton:disabled, QToolButton#secondaryButton:disabled { border-color: #554331; color: #928374; }
QPushButton#quietButton, QToolButton#quietButton {
    background: transparent;
    border: 1px solid transparent;
    color: #bcc7d0;
    padding: 7px 10px;
}
QPushButton#quietButton:hover, QToolButton#quietButton:hover { background: #222c34; color: #ffffff; }
QPushButton#quietButton:focus, QToolButton#quietButton:focus { border-color: #f4a35b; }
QPushButton#quietButton:disabled, QToolButton#quietButton:disabled { color: #6f7b85; }
QMenuBar, QMenu { background: #11181e; color: #dbe3e9; }
QMenuBar { border-bottom: 1px solid #252e36; }
QMenuBar::item { padding: 6px 11px; background: transparent; }
QMenuBar::item:selected, QMenu::item:selected { background: #3b291c; color: #ffbd80; }
QMenu { border: 1px solid #39434d; padding: 5px; }
QMenu::item { padding: 8px 28px 8px 14px; border-radius: 4px; }
QMenu::item:disabled { color: #73808b; }
QMenu::separator { height: 1px; background: #303b44; margin: 5px 8px; }
QToolTip { background: #202a33; color: #f0f3f6; border: 1px solid #66727d; padding: 7px; }
QStatusBar { background: #0c1115; color: #97a4af; border-top: 1px solid #252e36; font-size: 11px; }
QStatusBar::item { border: none; }
QSplitter::handle { background: #232d35; }
QSplitter::handle:hover { background: #805632; }
QTabWidget::pane { background: #10171d; border: 1px solid #2a353e; border-radius: 7px; }
QTabBar::tab {
    background: #121b22;
    color: #a7b3bd;
    padding: 10px 16px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover { background: #202930; color: #edf1f4; }
QTabBar::tab:selected { background: #271e17; color: #ffaf68; border-bottom-color: #f3913b; }
QTabBar::tab:focus { border-top: 1px solid #f3913b; }
QGroupBox { border: 1px solid #303b44; border-radius: 8px; margin-top: 12px; padding: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #dce4ea; }
QCheckBox, QRadioButton { spacing: 9px; padding: 5px; }
QCheckBox:focus, QRadioButton:focus { color: #ffb875; }
QCheckBox::indicator, QRadioButton::indicator { width: 17px; height: 17px; }
QProgressBar { background: #10171d; border: 1px solid #33404a; border-radius: 6px; text-align: center; min-height: 14px; }
QProgressBar::chunk { background: #d77c31; border-radius: 5px; }
QHeaderView::section { background: #182129; color: #aebac4; border: none; border-bottom: 1px solid #34404a; padding: 8px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #38454f; min-height: 32px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #5c6a75; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #38454f; min-width: 32px; border-radius: 4px; }
QScrollBar::handle:horizontal:hover { background: #5c6a75; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


_SCENE_COLORS = {
    "chat": "#183440",
    "projects": "#46331e",
    "library": "#332342",
    "models": "#153b3d",
    "workloads": "#42251c",
    "updates": "#21354a",
    "settings": "#303441",
}


def _load_artwork(resource):
    artwork = QPixmap()
    try:
        artwork.loadFromData(resource.read_bytes())
    except OSError:
        # Illustration resources are optional; the application remains usable.
        pass
    return artwork


def _scene_artwork(scene):
    if scene not in _SCENE_COLORS:
        raise ValueError(f"Unknown CETA scene: {scene}")
    return _load_artwork(files("ceta_desktop").joinpath(f"assets/{scene}-landscape.png"))


class ScenePage(QWidget):
    """A section-specific landscape beneath readable native page content."""

    def __init__(self, parent=None, scene: str = "chat"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._scaled_artwork = QPixmap()
        self._scaled_size = QSize()
        self._artwork = QPixmap()
        self._scene = "chat"
        self.set_scene(scene)

    def set_scene(self, scene: str):
        """Switch to a packaged scene without a network or filesystem write."""
        artwork = _scene_artwork(scene)
        self._scene = scene
        self._artwork = artwork
        self._scaled_size = QSize()
        self.update()

    def paintEvent(self, event):
        """Cover the page with art, then shade text areas without hiding edges."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#0b1014"))
        if not self._artwork.isNull():
            size = self.size()
            if size != self._scaled_size:
                self._scaled_artwork = self._artwork.scaled(
                    size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                )
                self._scaled_size = size
            art = self._scaled_artwork
            crop = QRectF((art.width() - self.width()) / 2,
                          (art.height() - self.height()) / 2,
                          self.width(), self.height())
            painter.drawPixmap(QRectF(self.rect()), art, crop)
        else:
            fallback = QLinearGradient(0, 0, self.width(), self.height())
            fallback.setColorAt(0, QColor("#0b1014"))
            fallback.setColorAt(1, QColor(_SCENE_COLORS[self._scene]))
            painter.fillRect(self.rect(), fallback)
        center = QLinearGradient(0, 0, self.width(), 0)
        center.setColorAt(0, QColor(8, 13, 18, 180))
        center.setColorAt(0.42, QColor(8, 13, 18, 175))
        center.setColorAt(1, QColor(8, 13, 18, 105))
        painter.fillRect(self.rect(), center)
        vertical = QLinearGradient(0, 0, 0, self.height())
        vertical.setColorAt(0, QColor(8, 13, 18, 150))
        vertical.setColorAt(0.38, QColor(8, 13, 18, 30))
        vertical.setColorAt(1, QColor(8, 13, 18, 65))
        painter.fillRect(self.rect(), vertical)
        painter.end()


class EmberSidebar(QWidget):
    """Paint optional local landscape art beneath transparent native controls."""

    def __init__(self, parent=None, asset_path: str | Path | None = None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._scaled_artwork = QPixmap()
        self._scaled_size = QSize()
        self._scene = "chat"
        if asset_path is not None:
            self._artwork = _load_artwork(Path(asset_path))
        else:
            self._artwork = _scene_artwork("chat")
            if self._artwork.isNull():
                self._artwork = _load_artwork(files("ceta_desktop").joinpath("assets/ember-landscape.png"))

    def set_scene(self, scene: str):
        """Follow navigation with the selected scene's subtle lower artwork."""
        artwork = _scene_artwork(scene)
        self._scene = scene
        self._artwork = artwork
        self._scaled_size = QSize()
        self.update()

    def paintEvent(self, event):
        """Keep text areas dark while allowing the landscape to emerge below."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#090e12"))
        art_height = min(self.height(), max(300, round(self.height() * 0.55)))
        art_top = self.height() - art_height
        target = QRectF(0, art_top, self.width(), art_height)
        if not self._artwork.isNull():
            size = QSize(max(1, self.width()), max(1, art_height))
            if size != self._scaled_size:
                self._scaled_artwork = self._artwork.scaled(
                    size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                )
                self._scaled_size = size
            art = self._scaled_artwork
            crop = QRectF((art.width() - self.width()) / 2, art.height() - art_height,
                          self.width(), art_height)
            painter.drawPixmap(target, art, crop)
        else:
            fallback = QLinearGradient(0, art_top, self.width(), self.height())
            fallback.setColorAt(0, QColor("#090e12"))
            fallback.setColorAt(0.62, QColor("#151317"))
            fallback.setColorAt(1, QColor(_SCENE_COLORS[self._scene]))
            painter.fillRect(target, fallback)
        fade = QLinearGradient(0, art_top, 0, self.height())
        fade.setColorAt(0, QColor(9, 14, 18, 255))
        fade.setColorAt(0.26, QColor(9, 14, 18, 225))
        fade.setColorAt(0.60, QColor(9, 14, 18, 90))
        fade.setColorAt(1, QColor(9, 14, 18, 140))
        painter.fillRect(target, fade)
        painter.setPen(QPen(QColor("#293038"), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        painter.end()


class BrandMark(QWidget):
    """A native painted volcanic orb, with no external artwork dependency."""

    def __init__(self, parent=None, size: int = 58):
        super().__init__(parent)
        if not 12 <= size <= 512:
            raise ValueError("Brand mark size must be between 12 and 512 pixels.")
        self.setFixedSize(size, size)
        self.setAccessibleName("CETA")
        self.setFocusPolicy(Qt.NoFocus)

    def sizeHint(self):
        return QSize(self.width(), self.height())

    def paintEvent(self, event):
        """Use gradients and deterministic fractures for a crisp scaled sphere."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 64, self.height() / 64)
        glow = QRadialGradient(QPointF(31, 31), 31)
        glow.setColorAt(0, QColor(255, 114, 13, 0))
        glow.setColorAt(0.70, QColor(255, 100, 10, 0))
        glow.setColorAt(0.82, QColor(255, 93, 7, 95))
        glow.setColorAt(1, QColor(255, 87, 6, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, 62, 62))
        rim = QLinearGradient(11, 8, 52, 58)
        rim.setColorAt(0, QColor("#ffd08a"))
        rim.setColorAt(0.23, QColor("#ff7917"))
        rim.setColorAt(0.52, QColor("#6c250c"))
        rim.setColorAt(0.82, QColor("#e76a0c"))
        rim.setColorAt(1, QColor("#ffc16a"))
        painter.setBrush(rim)
        painter.drawEllipse(QRectF(6, 6, 51, 51))
        body = QRadialGradient(QPointF(23, 20), 42)
        body.setColorAt(0, QColor("#28343c"))
        body.setColorAt(0.44, QColor("#121d23"))
        body.setColorAt(0.82, QColor("#050a0e"))
        body.setColorAt(1, QColor("#020406"))
        painter.setBrush(body)
        painter.drawEllipse(QRectF(8, 8, 47, 47))
        clip = QPainterPath()
        clip.addEllipse(QRectF(8, 8, 47, 47))
        painter.save()
        painter.setClipPath(clip)
        painter.setBrush(Qt.NoBrush)
        fissures = (
            ((9, 16), (17, 20), (19, 27), (14, 34), (20, 38), (19, 46), (25, 53)),
            ((18, 20), (25, 17), (27, 9), (34, 5)),
            ((20, 38), (29, 35), (35, 41), (44, 39), (51, 46)),
            ((42, 6), (39, 16), (44, 21), (40, 29), (47, 32), (56, 30)),
            ((39, 16), (32, 22), (33, 27)),
            ((9, 43), (13, 47), (12, 54)),
        )
        for points in fissures:
            path = _polyline(points)
            painter.setPen(QPen(QColor(237, 77, 6, 85), 3.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            painter.setPen(QPen(QColor("#bc4810"), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            painter.setPen(QPen(QColor(255, 166, 57, 175), 0.48, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
        painter.restore()
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#ffd79b"), 1.2, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(QRectF(6.5, 6.5, 50, 50), 70 * 16, 66 * 16)
        painter.setPen(QPen(QColor("#ff8628"), 1.4, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(QRectF(6.5, 6.5, 50, 50), 202 * 16, 65 * 16)
        painter.end()


def _polyline(points, closed=False):
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    if closed:
        path.closeSubpath()
    return path


_ICON_LINES = {
    "projects": (((3, 7), (3, 5), (9, 5), (11, 8), (21, 8), (21, 20), (3, 20), (3, 7)),),
    "folder": (((3, 7), (3, 5), (9, 5), (11, 8), (21, 8), (21, 20), (3, 20), (3, 7)),),
    "library": (((3, 5), (8, 4), (12, 6), (16, 4), (21, 5), (21, 19), (16, 18), (12, 20), (8, 18), (3, 19), (3, 5)), ((12, 6), (12, 20))),
    "models": (((12, 2.5), (21, 7.5), (21, 17), (12, 22), (3, 17), (3, 7.5), (12, 2.5)), ((3, 7.5), (12, 12.5), (21, 7.5)), ((12, 12.5), (12, 22)), ((7.5, 5), (16.5, 10))),
    "updates": (((12, 6), (12, 16)), ((8, 12), (12, 16), (16, 12))),
    "terminal": (((6, 8), (10, 12), (6, 16)), ((13, 16), (18, 16))),
    "search": (((15.5, 15.5), (21, 21)),),
    "plus": (((12, 4), (12, 20)), ((4, 12), (20, 12))),
    "send": (((3, 10), (21, 3), (14, 21), (11, 13), (3, 10)), ((11, 13), (21, 3))),
    "file": (((5, 3), (14, 3), (19, 8), (19, 21), (5, 21), (5, 3)), ((14, 3), (14, 8), (19, 8))),
    "refresh": (((16, 3), (20, 7), (15, 8)),),
    "chat": (),
    "settings": (),
}


def icon(name: str, color: str = "#aab2bd", size: int = 20) -> QIcon:
    """Draw one of CETA's named line icons with a crisp high-DPI pixmap."""
    if name not in _ICON_LINES:
        raise ValueError(f"Unknown CETA icon: {name}")
    ink = QColor(color)
    if not ink.isValid() or not 8 <= size <= 256:
        raise ValueError("Icons require a valid color and a size between 8 and 256 pixels.")
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size * 2 / 24, size * 2 / 24)
    painter.setPen(QPen(ink, 1.65, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    for points in _ICON_LINES[name]:
        painter.drawPath(_polyline(points))
    if name == "updates":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
    elif name == "search":
        painter.drawEllipse(QRectF(3, 3, 13, 13))
    elif name == "terminal":
        painter.drawRoundedRect(QRectF(2, 4, 20, 16), 2, 2)
    elif name == "refresh":
        painter.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 285 * 16)
    elif name == "chat":
        outline = QPainterPath(QPointF(7, 4))
        outline.lineTo(17, 4)
        outline.quadTo(21, 4, 21, 8)
        outline.lineTo(21, 13)
        outline.quadTo(21, 17, 17, 17)
        outline.lineTo(9, 17)
        outline.lineTo(4, 21)
        outline.lineTo(4, 15)
        outline.quadTo(3, 14, 3, 12)
        outline.lineTo(3, 8)
        outline.quadTo(3, 4, 7, 4)
        painter.drawPath(outline)
        painter.drawLine(QPointF(8, 10), QPointF(16, 10))
    elif name == "settings":
        teeth = []
        for step in range(32):
            angle = math.pi * 2 * step / 32
            radius = 9 if step % 4 in (0, 1) else 7
            teeth.append(QPointF(12 + math.cos(angle) * radius, 12 + math.sin(angle) * radius))
        painter.drawPolygon(QPolygonF(teeth))
        painter.drawEllipse(QRectF(8.8, 8.8, 6.4, 6.4))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
