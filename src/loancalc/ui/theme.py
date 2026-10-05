"""Shared visual language for the whole application.

Widgets opt into styles via Qt properties (`role="title"`, `variant="primary"`)
instead of per-widget stylesheets, so the look stays consistent as new panels
are added.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

# --- palette --------------------------------------------------------------- #
BG = "#F4F5F6"
SURFACE = "#FFFFFF"
BORDER = "#D6DADE"
BORDER_STRONG = "#B6BCC2"
TEXT = "#1E2429"
TEXT_MUTED = "#6B7480"
ACCENT = "#367C2B"
ACCENT_HOVER = "#2D6824"
ACCENT_PRESSED = "#23521C"
ACCENT_SOFT = "#E9F1E7"
HOVER = "#EAECEE"
PRESSED = "#DFE2E5"
WARN = "#B0450B"
DANGER = "#A32020"
INFO = "#1F6FB2"

# --- chart palette --------------------------------------------------------- #
CHART_GRID = "#E3E6E9"
CHART_SERIES = (
    "#367C2B", "#1F6FB2", "#B0450B", "#7D5BA6", "#2A9D8F",
    "#C9922A", "#4C6D8C", "#8C4B4B", "#5B8C3A", "#A0548B",
    "#3F7F7F", "#9C6B3F",
)
CHART_PRINCIPAL = ACCENT
CHART_INTEREST = WARN
CHART_FEES = "#7D5BA6"
CHART_ASSET = INFO
CHART_EQUITY = "#2A9D8F"

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Segoe UI Variable", sans-serif;
    font-size: 13px;
}}

QLabel {{
    background: transparent;
}}
QLabel[role="hero"] {{
    font-size: 22px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel[role="title"] {{
    font-size: 17px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel[role="section"] {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    color: {TEXT_MUTED};
}}
QLabel[role="subtitle"] {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QLabel[role="field"] {{
    font-size: 12px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel[role="status"] {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QLabel[role="metric"] {{
    font-size: 12px;
    font-weight: 600;
    color: {ACCENT};
}}
QLabel[role="metricLabel"] {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: {TEXT_MUTED};
}}
QLabel[role="metricValue"] {{
    font-size: 24px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel[role="metricValue"][tone="accent"] {{ color: {ACCENT}; }}
QLabel[role="metricValue"][tone="warn"] {{ color: {WARN}; }}
QLabel[role="metricValue"][tone="info"] {{ color: {INFO}; }}
QLabel[role="metricNote"] {{
    font-size: 11px;
    color: {TEXT_MUTED};
}}
QLabel[role="metricNote"][tone="good"] {{ color: {ACCENT}; font-weight: 600; }}
QLabel[role="metricNote"][tone="bad"] {{ color: {DANGER}; font-weight: 600; }}
QLabel[role="warn"] {{
    font-size: 12px;
    font-weight: 600;
    color: {WARN};
}}

QFrame[role="separator"] {{
    background-color: {BORDER};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QFrame[role="card"] {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame[role="card"] QLabel {{
    background: transparent;
}}
QFrame[role="banner"] {{
    background-color: {ACCENT_SOFT};
    border: 1px solid {ACCENT};
    border-radius: 6px;
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QDateEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 9px;
    min-height: 18px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover {{
    border-color: {BORDER_STRONG};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {HOVER};
    color: {TEXT_MUTED};
}}
QDoubleSpinBox[scale="large"] {{
    font-size: 19px;
    font-weight: 600;
    padding: 8px 10px;
}}

QPlainTextEdit {{
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 16px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {TEXT_MUTED};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_MUTED};
}}

QTabWidget::pane {{
    background-color: {BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    padding: 8px 18px;
    margin-right: 2px;
    color: {TEXT_MUTED};
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {TEXT};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:focus {{
    outline: none;
}}

QRadioButton, QCheckBox {{
    background: transparent;
    spacing: 8px;
    padding: 3px 0;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER_STRONG};
    background-color: {SURFACE};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator {{
    border-radius: 3px;
}}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border: 4px solid {SURFACE};
    outline: 1px solid {ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    width: 0;
    height: 0;
    margin-right: 9px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_MUTED};
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    outline: none;
    padding: 2px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}

QPushButton {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 14px;
    min-height: 18px;
    color: {TEXT};
}}
QPushButton:hover {{
    background-color: {HOVER};
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{
    background-color: {PRESSED};
}}
QPushButton:disabled {{
    background-color: {HOVER};
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}
QPushButton[variant="primary"] {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[variant="primary"]:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton[variant="primary"]:disabled {{
    background-color: {BORDER_STRONG};
    border-color: {BORDER_STRONG};
    color: {SURFACE};
}}
QPushButton[variant="quiet"] {{
    background-color: transparent;
    border-color: transparent;
    color: {TEXT_MUTED};
    font-weight: 600;
}}
QPushButton[variant="quiet"]:hover {{
    background-color: {HOVER};
    color: {TEXT};
}}

QListWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    outline: none;
    padding: 2px;
}}
QListWidget::item {{
    padding: 5px 6px;
    border-radius: 3px;
    color: {TEXT};
}}
QListWidget::item:hover {{
    background-color: {ACCENT_SOFT};
}}
QListWidget::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT};
}}

QTableView, QTableWidget {{
    background-color: {SURFACE};
    alternate-background-color: #FAFBFB;
    border: 1px solid {BORDER};
    border-radius: 4px;
    gridline-color: {BORDER};
    outline: none;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QTableView::item, QTableWidget::item {{
    padding: 5px 8px;
    border: none;
}}
QTableView::item:selected, QTableWidget::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT};
}}
QHeaderView {{
    background-color: {SURFACE};
}}
QHeaderView::section {{
    background-color: {SURFACE};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QHeaderView::section:last {{
    border-right: none;
}}
QTableCornerButton::section {{
    background-color: {SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER};
}}

QMenuBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {BORDER};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 11px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT};
}}
QMenu {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 14px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT};
}}
QMenu::separator {{
    height: 1px;
    background-color: {BORDER};
    margin: 4px 8px;
}}

QStatusBar {{
    background-color: {SURFACE};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QStatusBar::item {{
    border: none;
}}

QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding: 14px 14px 12px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}

QSplitter::handle {{
    background-color: transparent;
}}

QProgressBar {{
    background-color: {PRESSED};
    border: none;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background-color: #C4C9CE;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: #A9B0B6;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background-color: #C4C9CE;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QToolTip {{
    background-color: {TEXT};
    color: #FFFFFF;
    border: none;
    padding: 5px 8px;
}}

QMessageBox {{
    background-color: {SURFACE};
}}
QMessageBox QLabel {{
    color: {TEXT};
}}
"""


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)


# --- widget helpers -------------------------------------------------------- #
def _labeled(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    return label


def hero(text: str) -> QLabel:
    return _labeled(text, "hero")


def title(text: str) -> QLabel:
    return _labeled(text, "title")


def section(text: str) -> QLabel:
    return _labeled(text.upper(), "section")


def subtitle(text: str) -> QLabel:
    label = _labeled(text, "subtitle")
    label.setWordWrap(True)
    return label


def field(text: str) -> QLabel:
    return _labeled(text, "field")


def status(text: str) -> QLabel:
    return _labeled(text, "status")


def metric(text: str) -> QLabel:
    return _labeled(text, "metric")


def warn(text: str) -> QLabel:
    label = _labeled(text, "warn")
    label.setWordWrap(True)
    return label


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("role", "separator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    return line


def card() -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "card")
    return frame


def primary(button: QPushButton) -> QPushButton:
    button.setProperty("variant", "primary")
    return button


def quiet(button: QPushButton) -> QPushButton:
    button.setProperty("variant", "quiet")
    return button


def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
