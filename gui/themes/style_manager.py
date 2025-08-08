# gui/themes/style_manager.py
from .modern_theme import theme_manager

class StyleManager:
    def get_complete_stylesheet(self) -> str:
        t = theme_manager.get_current_theme()

        btn_fg   = getattr(t, "BUTTON_TEXT_COLOR", t.TEXT_ON_PRIMARY)
        btn_dis  = getattr(t, "BUTTON_DISABLED", t.BUTTON_BACKGROUND)
        txt_dis  = getattr(t, "TEXT_DISABLED",   t.TEXT_PRIMARY)
        sb_hover = getattr(t, "SIDEBAR_ITEM_HOVER", t.SURFACE_VARIANT)

        dark_block = "" if theme_manager.theme_mode == "light" else f"""
QMainWindow, QDialog, QScrollArea, QFrame,
QTabWidget, QStackedWidget, QListWidget, QTreeWidget {{
    background: {t.BACKGROUND};
}}"""

        return f"""
/* === ROOT === */
QWidget {{
    background: {t.BACKGROUND};
    color:      {t.TEXT_PRIMARY};
    font-family:{t.FONT_FAMILY};
    font-size:  {t.FONT_SIZE_NORMAL};
}}
{dark_block}

/* ========== SIDEBAR ========== */
QListWidget {{
    background: {t.SIDEBAR_BACKGROUND};
    border-right: 1px solid {t.SIDEBAR_BORDER};
}}
QListWidget::item         {{ padding:6px 10px; color:{t.SIDEBAR_ITEM_TEXT}; }}
QListWidget::item:hover   {{ background:{sb_hover}; }}
QListWidget::item:selected{{ background:{t.SIDEBAR_ITEM_ACTIVE}; color:{t.TEXT_ON_PRIMARY}; }}

/* ========== TOOL BAR ========== */
QToolBar {{
    background: {t.SURFACE_ELEVATED};
    border-bottom: 1px solid {t.BORDER};
}}
QToolButton {{
    background: transparent;
    color: {t.TEXT_PRIMARY};
    padding: 4px 10px;
    border: none;
}}
QToolButton:hover {{
    background: {sb_hover};
}}

/* ========== BUTTONS ========== */
QPushButton {{
    background: {t.BUTTON_BACKGROUND};
    color:      {btn_fg};
    border: 1px solid {t.BORDER};
    border-radius:{t.RADIUS_SMALL};
    padding:6px 12px;
    font-weight:600;
}}
QPushButton:hover   {{ background:{t.BUTTON_HOVER}; }}
QPushButton:pressed {{ background:{t.BUTTON_PRESSED}; }}
QPushButton:disabled{{ background:{btn_dis}; color:{txt_dis}; }}

/* ========== TAB WIDGET ========== */
QTabWidget::pane {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: {t.RADIUS_MEDIUM};
}}
QTabBar::tab {{
    background: {t.SURFACE_VARIANT};
    color: {t.TEXT_SECONDARY};
    padding: 6px 12px;
    margin: 2px;
    border-radius: {t.RADIUS_SMALL};
    font-family: {t.FONT_FAMILY};
}}
QTabBar::tab:selected {{
    background: {t.PRIMARY};
    color: {t.TEXT_ON_PRIMARY};
}}
QTabBar::tab:hover {{
    background: {t.SURFACE_ELEVATED};
    color: {t.TEXT_PRIMARY};
}}


/* ========== INPUTS ========== */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background:{t.INPUT_BACKGROUND};
    color:{t.TEXT_PRIMARY};
    border:1px solid {t.INPUT_BORDER};
    border-radius:{t.RADIUS_SMALL};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color:{t.INPUT_BORDER_FOCUS};
}}

/* ========== TABLES & PROCESS THREADS ========== */
QTableView, QTableWidget,
QTreeView,  QTreeWidget {{
    background:                {t.SURFACE};
    alternate-background-color:{t.SURFACE_VARIANT};
    selection-background-color:{t.PRIMARY};
    selection-color:           {t.TEXT_ON_PRIMARY};
    gridline-color:            {t.BORDER};
    border: 1px solid {t.BORDER};
    outline: 0;
}}

/* No default background for items - let the delegate handle it */
QTableView::item, QTableWidget::item {{
    padding: 4px;
}}

/* Column headers */
QHeaderView::section {{
    background: {getattr(t,'TABLE_HEADER', t.SURFACE_ELEVATED)};
    color: {t.TEXT_PRIMARY};
    border: 1px solid {t.BORDER};
    padding: 6px;
    font-weight: 600;
}}

/* Status colors will be handled by StatusColorDelegate */


/* خلايا عادية */
QTableView::item, QTableWidget::item {{
    background:{t.SURFACE};
    color:{t.TEXT_PRIMARY};
}}
QTableView::item:hover, QTableWidget::item:hover {{
    background:{sb_hover};
}}
/* رؤوس الأعمدة */
QHeaderView::section {{
    background:{getattr(t,'TABLE_HEADER', t.SURFACE_ELEVATED)};
    color:{t.TEXT_PRIMARY};
    border:1px solid {t.BORDER};
    padding:4px;
    font-weight:600;
}}
/* خلايا الحالة */
QTableWidgetItem#status-pending    {{background:{t.SURFACE_VARIANT}; color:{t.TEXT_PRIMARY};}}
QTableWidgetItem#status-downloaded {{background:{t.WARNING};         color:{t.TEXT_ON_PRIMARY};}}
QTableWidgetItem#status-uploaded   {{background:{t.INFO};            color:{t.TEXT_ON_PRIMARY};}}
QTableWidgetItem#status-posted     {{background:{t.SUCCESS};         color:{t.TEXT_ON_PRIMARY};}}
QTableWidgetItem#status-error      {{background:{t.ERROR};           color:{t.TEXT_ON_PRIMARY};}}

/* ========== CARDS (Posts Management) ========== */
QFrame#ModernCard, QFrame#ModernSectionCard {{
    background:{t.SURFACE};
    border:1px solid {t.BORDER};
    border-radius:{t.RADIUS_MEDIUM};
}}
QFrame#ModernCard:hover{{ border-color:{t.PRIMARY}; }}

/* ========== SCROLL BARS ========== */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border: none;
    width: 6px;
    height: 6px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {t.BORDER};
    border-radius: 3px;
    margin: 2px;
    min-height: 16px;
    min-width: 16px;
}}
QScrollBar::handle:hover {{
    background: {t.PRIMARY};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    background: none;
    border: none;
    height: 0px;
    width: 0px;
}}

/* ========== SPIN BOXES (QSpinBox / QDoubleSpinBox) ========== */
QAbstractSpinBox {{
    background: {t.INPUT_BACKGROUND};
    border: 1px solid {t.INPUT_BORDER};
    border-radius: {t.RADIUS_SMALL};
    padding-right: 20px;               /* مساحة للأسهم */
}}
QAbstractSpinBox:focus {{
    border-color: {t.INPUT_BORDER_FOCUS};
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: right;
    width: 18px;
    border-left: 1px solid {t.INPUT_BORDER};
}}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: {t.SIDEBAR_ITEM_HOVER};
}}
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{
    width:  7px;
    height: 7px;
}}
QAbstractSpinBox::up-arrow {{
    image: url(:/qt-project.org/styles/commonstyle/images/arrow_up.png);
}}
QAbstractSpinBox::down-arrow {{
    image: url(:/qt-project.org/styles/commonstyle/images/arrow_down.png);
}}

/* ========== PROGRESS BAR ========== */
QProgressBar {{
    background:{t.PROGRESS_BACKGROUND};
    border:1px solid {t.BORDER};
    border-radius:{t.RADIUS_SMALL};
    text-align:center;
    color:{t.TEXT_PRIMARY};
}}
QProgressBar::chunk {{
    background:{t.PRIMARY};
    border-radius:{t.RADIUS_SMALL};
}}
"""


style_manager = StyleManager()
