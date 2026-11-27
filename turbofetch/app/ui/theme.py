import sys
from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

DARK_PALETTE: dict[str, str] = {
    "bg_primary": "#0b1220",
    "bg_secondary": "#111a2e",
    "bg_tertiary": "#17233c",
    "text_primary": "#eef4ff",
    "text_secondary": "#93a8cc",
    "accent": "#2563eb",
    "accent_hover": "#3b82f6",
    "accent_pressed": "#1d4ed8",
    "border": "#243659",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "surface": "#1b2947",
    "surface_hover": "#23355c",
}

LIGHT_PALETTE: dict[str, str] = {
    "bg_primary": "#f0f5fc",
    "bg_secondary": "#ffffff",
    "bg_tertiary": "#e6eef9",
    "text_primary": "#0f172a",
    "text_secondary": "#475569",
    "accent": "#1d4ed8",
    "accent_hover": "#2563eb",
    "accent_pressed": "#1e40af",
    "border": "#c7d7ef",
    "success": "#16a34a",
    "warning": "#d97706",
    "error": "#dc2626",
    "surface": "#f7faff",
    "surface_hover": "#e2ecfb",
}


def build_stylesheet(p: dict[str, str]) -> str:
    return f"""
QMainWindow, QDialog, QWidget {{
    background-color: {p["bg_primary"]};
    color: {p["text_primary"]};
}}
QMenuBar {{
    background-color: {p["bg_secondary"]};
    color: {p["text_primary"]};
    border-bottom: 1px solid {p["border"]};
    padding: 3px 6px;
}}
QMenuBar::item {{
    padding: 5px 10px;
    border-radius: 5px;
}}
QMenuBar::item:selected {{
    background-color: {p["surface_hover"]};
}}
QMenu {{
    background-color: {p["bg_secondary"]};
    color: {p["text_primary"]};
    border: 1px solid {p["border"]};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background-color: {p["accent"]};
    color: #ffffff;
}}
QMenu::separator {{
    height: 1px;
    background-color: {p["border"]};
    margin: 4px 8px;
}}
QToolBar {{
    background-color: {p["bg_secondary"]};
    border-bottom: 1px solid {p["border"]};
    spacing: 4px;
    padding: 6px 10px;
}}
QToolButton {{
    background-color: transparent;
    color: {p["text_primary"]};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 8px;
    min-width: 48px;
}}
QToolButton:hover {{
    background-color: {p["surface_hover"]};
    border-color: {p["border"]};
}}
QToolButton:pressed {{
    background-color: {p["bg_tertiary"]};
}}
QToolButton:disabled {{
    color: {p["text_secondary"]};
}}
QToolButton#clearListBtn {{
    background-color: {p["surface"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 5px 12px;
    min-height: 22px;
}}
QToolButton#clearListBtn:hover {{
    background-color: {p["surface_hover"]};
    border-color: {p["accent"]};
}}
QPushButton {{
    background-color: {p["surface"]};
    color: {p["text_primary"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: {p["surface_hover"]};
    border-color: {p["accent"]};
}}
QPushButton:pressed {{
    background-color: {p["bg_tertiary"]};
}}
QPushButton[primary="true"] {{
    background-color: {p["accent"]};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background-color: {p["accent_hover"]};
}}
QPushButton[primary="true"]:pressed {{
    background-color: {p["accent_pressed"]};
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QTimeEdit {{
    background-color: {p["bg_secondary"]};
    color: {p["text_primary"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 5px 10px;
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {p["accent_hover"]};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {p["bg_secondary"]};
    color: {p["text_primary"]};
    border: 1px solid {p["border"]};
    selection-background-color: {p["accent"]};
}}
QTreeWidget, QTableView, QTableWidget, QListWidget {{
    background-color: {p["bg_secondary"]};
    alternate-background-color: {p["bg_tertiary"]};
    color: {p["text_primary"]};
    border: 1px solid {p["border"]};
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: {p["accent"]};
    selection-color: #ffffff;
    outline: none;
}}
QTreeWidget {{
    padding: 4px;
}}
QTreeWidget::item, QListWidget::item {{
    padding: 6px 8px;
    border-radius: 6px;
    margin: 1px 2px;
}}
QTreeWidget::item:hover {{
    background-color: {p["surface_hover"]};
}}
QTreeWidget::item:selected {{
    background-color: {p["accent"]};
    color: #ffffff;
}}
QTableView::item {{
    padding: 4px 8px;
    border-bottom: 1px solid {p["bg_tertiary"]};
}}
QHeaderView::section {{
    background-color: {p["bg_tertiary"]};
    color: {p["text_secondary"]};
    border: none;
    border-right: 1px solid {p["border"]};
    border-bottom: 1px solid {p["border"]};
    padding: 7px 10px;
    font-weight: 600;
}}
QHeaderView::section:last {{
    border-right: none;
}}
QTabWidget::pane {{
    border: 1px solid {p["border"]};
    border-radius: 8px;
    background-color: {p["bg_secondary"]};
    padding: 4px;
}}
QTabBar::tab {{
    background-color: {p["bg_tertiary"]};
    color: {p["text_secondary"]};
    padding: 7px 14px;
    margin-right: 3px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    background-color: {p["bg_secondary"]};
    color: {p["text_primary"]};
    border-bottom: 2px solid {p["accent_hover"]};
}}
QGroupBox {{
    border: 1px solid {p["border"]};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {p["text_secondary"]};
}}
QProgressBar {{
    background-color: {p["bg_tertiary"]};
    border: 1px solid {p["border"]};
    border-radius: 5px;
    text-align: center;
    color: {p["text_primary"]};
}}
QProgressBar::chunk {{
    background-color: {p["accent_hover"]};
    border-radius: 4px;
}}
QStatusBar {{
    background-color: {p["bg_secondary"]};
    color: {p["text_secondary"]};
    border-top: 1px solid {p["border"]};
    padding: 2px 8px;
}}
QSplitter::handle {{
    background-color: {p["border"]};
    width: 1px;
    height: 1px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {p["border"]};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p["accent"]};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p["border"]};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p["accent"]};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0px;
    height: 0px;
}}
"""


DARK_STYLESHEET = build_stylesheet(DARK_PALETTE)
LIGHT_STYLESHEET = build_stylesheet(LIGHT_PALETTE)


class ThemeManager:
    def __init__(self, app: Optional[QApplication] = None) -> None:
        self._app = app
        self._theme = "dark"
        self._font_size = 10

    def set_font_size(self, size: int) -> None:
        self._font_size = max(8, min(18, size))
        if self._app is not None:
            font = self._app.font()
            font.setPointSize(self._font_size)
            self._app.setFont(font)

    def set_theme(self, theme: str) -> None:
        self._theme = theme.lower()
        effective = self._detect_system_theme() if self._theme == "system" else self._theme
        self._apply_stylesheet(effective)

    def get_current_theme(self) -> str:
        return self._theme

    def get_effective_palette(self) -> dict[str, str]:
        effective = self._detect_system_theme() if self._theme == "system" else self._theme
        return LIGHT_PALETTE if effective == "light" else DARK_PALETTE

    def _detect_system_theme(self) -> str:
        if sys.platform != "win32":
            return "dark"
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if value == 1 else "dark"
        except OSError:
            return "dark"

    def _apply_stylesheet(self, theme: str) -> None:
        if self._app is None:
            return
        sheet = LIGHT_STYLESHEET if theme == "light" else DARK_STYLESHEET
        self._app.setStyleSheet(sheet)
        font = QFont("Segoe UI", self._font_size)
        self._app.setFont(font)

    def toggle_theme(self) -> str:
        current = self._detect_system_theme() if self._theme == "system" else self._theme
        next_theme = "light" if current == "dark" else "dark"
        self.set_theme(next_theme)
        return next_theme
