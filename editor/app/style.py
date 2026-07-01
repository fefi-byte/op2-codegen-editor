from __future__ import annotations

# Catppuccin Mocha palette
BASE     = "#1e1e2e"
SURFACE0 = "#313244"
SURFACE1 = "#45475a"
SURFACE2 = "#585b70"
OVERLAY  = "#6c7086"
TEXT     = "#cdd6f4"
SUBTEXT  = "#bac2de"
BLUE     = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"
PEACH    = "#fab387"
TEAL     = "#94e2d5"
MAUVE    = "#cba6f7"
CRUST    = "#181825"
BORDER   = "#3a3a5c"

ACTION_CATEGORY_COLOR: dict[str, str] = {
    "message":        BLUE,
    "createUnit":     GREEN,
    "createDisaster": PEACH,
    "createTrigger":  MAUVE,
    "recordBuilding": YELLOW,
    "recordTube":     YELLOW,
    "recordWall":     YELLOW,
    "setTargCount":   TEAL,
    "assignToGroup":  TEAL,
    "modVar":         RED,
    "if":             OVERLAY,
    "noop":           SURFACE1,
}


def apply_role(widget, role: str) -> None:
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def build_stylesheet() -> str:
    return f"""
/* === Base === */
QMainWindow, QDialog {{
    background-color: {BASE};
}}
QWidget {{
    background-color: {BASE};
    color: {TEXT};
    font-size: 10pt;
}}

/* === Input fields === */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {SURFACE2};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {BLUE};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {OVERLAY};
    background-color: {BASE};
}}
QLineEdit::placeholder {{
    color: {OVERLAY};
}}

/* === SpinBox === */
QSpinBox, QDoubleSpinBox {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 4px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {BLUE};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {SURFACE1};
    border: none;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {SURFACE2};
}}

/* === ComboBox === */
QComboBox {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 6px;
}}
QComboBox:focus {{
    border-color: {BLUE};
}}
QComboBox:disabled {{
    color: {OVERLAY};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {SURFACE1};
    selection-color: {TEXT};
    outline: none;
}}

/* === Buttons === */
QPushButton {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 10px;
}}
QPushButton:hover {{
    background-color: {SURFACE1};
    border-color: {SURFACE2};
}}
QPushButton:pressed {{
    background-color: {SURFACE2};
}}
QPushButton:disabled {{
    color: {OVERLAY};
    border-color: {SURFACE0};
}}
QPushButton[role="primary"] {{
    background-color: #1a3028;
    color: {GREEN};
    border: 1px solid {GREEN};
}}
QPushButton[role="primary"]:hover {{
    background-color: #243d33;
}}
QPushButton[role="primary"]:pressed {{
    background-color: #2e4d40;
}}
QPushButton[role="danger"] {{
    background-color: #3a1e28;
    color: {RED};
    border: 1px solid {RED};
}}
QPushButton[role="danger"]:hover {{
    background-color: #4a2835;
}}
QPushButton[role="danger"]:pressed {{
    background-color: #5a3040;
}}

/* === CheckBox === */
QCheckBox {{
    color: {TEXT};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {SURFACE2};
    background-color: {SURFACE0};
}}
QCheckBox::indicator:checked {{
    background-color: {BLUE};
    border-color: {BLUE};
}}
QCheckBox::indicator:disabled {{
    background-color: {SURFACE0};
    border-color: {BORDER};
}}

/* === Lists and Trees === */
QListWidget, QTreeWidget {{
    background-color: {BASE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 2px 4px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {SURFACE1};
    color: {TEXT};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {SURFACE0};
}}

/* === Tabs === */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-top: none;
    background-color: {BASE};
}}
QTabBar {{
    background-color: transparent;
}}
QTabBar::tab {{
    background-color: {BASE};
    color: {OVERLAY};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 6px 14px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {SURFACE0};
    color: {TEXT};
    border-top: 2px solid {BLUE};
}}
QTabBar::tab:hover:!selected {{
    color: {SUBTEXT};
    background-color: {SURFACE0};
}}

/* === Splitter === */
QSplitter::handle {{
    background-color: {SURFACE0};
}}
QSplitter::handle:hover {{
    background-color: {SURFACE1};
}}
QSplitter::handle:horizontal {{
    width: 3px;
}}
QSplitter::handle:vertical {{
    height: 3px;
}}

/* === ScrollBar === */
QScrollBar:vertical {{
    background-color: {BASE};
    width: 8px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {SURFACE1};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {SURFACE2};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{
    background-color: {BASE};
    height: 8px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {SURFACE1};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {SURFACE2};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* === ScrollArea === */
QScrollArea {{
    border: none;
}}

/* === Toolbar === */
QToolBar {{
    background-color: {CRUST};
    border-bottom: 1px solid {BORDER};
    padding: 3px 6px;
    spacing: 4px;
}}
QToolBar::separator {{
    background-color: {BORDER};
    width: 1px;
    margin: 4px 2px;
}}
QToolBar QToolButton {{
    background-color: transparent;
    color: {TEXT};
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 10px;
}}
QToolBar QToolButton:hover {{
    background-color: {SURFACE0};
    border-color: {BORDER};
}}
QToolBar QToolButton:pressed {{
    background-color: {SURFACE1};
}}

/* === MenuBar === */
QMenuBar {{
    background-color: {CRUST};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 4px 10px;
    background-color: transparent;
}}
QMenuBar::item:selected {{
    background-color: {SURFACE0};
    border-radius: 3px;
}}
QMenu {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 0;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
}}
QMenu::item:selected {{
    background-color: {SURFACE1};
}}
QMenu::separator {{
    height: 1px;
    background-color: {BORDER};
    margin: 3px 0;
}}

/* === DockWidget === */
QDockWidget {{
    color: {TEXT};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background-color: {CRUST};
    padding: 5px 8px;
    border-bottom: 1px solid {BORDER};
    text-align: left;
}}

/* === Section Labels === */
QLabel[role="section"] {{
    color: {BLUE};
    font-weight: bold;
    font-size: 9pt;
    padding: 4px 4px 2px 4px;
    letter-spacing: 0.5px;
}}

/* === Status Bar === */
QStatusBar {{
    background-color: {CRUST};
    color: {OVERLAY};
    border-top: 1px solid {BORDER};
    font-size: 9pt;
}}

/* === Table === */
QTableWidget {{
    background-color: {BASE};
    color: {TEXT};
    border: 1px solid {BORDER};
    gridline-color: {SURFACE0};
    border-radius: 4px;
    outline: none;
}}
QTableWidget::item:selected {{
    background-color: {SURFACE1};
    color: {TEXT};
}}
QHeaderView::section {{
    background-color: {SURFACE0};
    color: {SUBTEXT};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 4px 8px;
    font-size: 9pt;
}}
QHeaderView::section:last {{
    border-right: none;
}}

/* === Hint labels (gray secondary text) === */
QLabel[secondary="true"] {{
    color: {OVERLAY};
    font-size: 9pt;
}}
"""
