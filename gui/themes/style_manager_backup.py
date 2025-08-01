"""Modern Theme Style Manager for PyQt5 Application"""

class StyleManager:
    def __init__(self, theme):
        self.theme = theme
    
    def get_complete_stylesheet(self):
        """Get comprehensive dark theme stylesheet for all PyQt5 widgets"""
        return f"""
        /* === GLOBAL STYLING === */
        * {{
            color: {self.theme.TEXT_PRIMARY} !important;
            font-family: {self.theme.FONT_FAMILY};
            background: transparent;
        }}
        
        QMainWindow, QDialog, QWidget {{
            background-color: {self.theme.BACKGROUND_PRIMARY};
            color: {self.theme.TEXT_PRIMARY} !important;
            font-family: {self.theme.FONT_FAMILY};
            font-size: {self.theme.FONT_SIZE_NORMAL};
        }}
        
        /* === LISTWIDGET (SIDEBAR) === */
        QListWidget {{
            background-color: {self.theme.SURFACE} !important;
            color: {self.theme.TEXT_PRIMARY} !important;
            border: 1px solid {self.theme.BORDER};
            border-radius: {self.theme.RADIUS_MEDIUM};
            font-family: {self.theme.FONT_FAMILY};
            font-size: {self.theme.FONT_SIZE_NORMAL};
            outline: none;
            padding: 4px;
        }}
        
        QListWidget::item {{
            background-color: transparent;
            color: {self.theme.TEXT_PRIMARY} !important;
            padding: 8px 12px;
            border: none;
            border-radius: {self.theme.RADIUS_SMALL};
            margin: 2px;
            min-height: 20px;
        }}
        
        QListWidget::item:hover {{
            background-color: {self.theme.SURFACE_HOVER};
            color: {self.theme.TEXT_PRIMARY} !important;
        }}
        
        QListWidget::item:selected {{
            background-color: {self.theme.PRIMARY};
            color: {self.theme.TEXT_ON_PRIMARY} !important;
        }}
        
        /* === BUTTON STYLING === */
        QPushButton {{
            background-color: {self.theme.BUTTON_BACKGROUND};
            color: {self.theme.TEXT_PRIMARY} !important;
            border: 1px solid {self.theme.BUTTON_BORDER};
            border-radius: {self.theme.RADIUS_SMALL};
            padding: 8px 16px;
            font-family: {self.theme.FONT_FAMILY};
            font-size: {self.theme.FONT_SIZE_NORMAL};
            font-weight: 500;
            min-height: 20px;
        }}
        
        QPushButton:hover {{
            background-color: {self.theme.BUTTON_HOVER};
            border-color: {self.theme.PRIMARY};
        }}
        
        QPushButton:pressed {{
            background-color: {self.theme.BUTTON_PRESSED};
        }}
        
        /* === INPUT STYLING === */
        QLineEdit {{
            background-color: {self.theme.INPUT_BACKGROUND};
            color: {self.theme.TEXT_PRIMARY} !important;
            border: 1px solid {self.theme.INPUT_BORDER};
            border-radius: {self.theme.RADIUS_SMALL};
            padding: 6px 12px;
            font-family: {self.theme.FONT_FAMILY};
            font-size: {self.theme.FONT_SIZE_NORMAL};
            min-height: 16px;
        }}
        
        QLineEdit:focus {{
            border-color: {self.theme.PRIMARY};
        }}
        
        QTextEdit {{
            background-color: {self.theme.INPUT_BACKGROUND};
            color: {self.theme.TEXT_PRIMARY} !important;
            border: 1px solid {self.theme.INPUT_BORDER};
            border-radius: {self.theme.RADIUS_SMALL};
            padding: 8px;
            font-family: {self.theme.FONT_FAMILY};
            font-size: {self.theme.FONT_SIZE_NORMAL};
        }}
        
        QTextEdit:focus {{
            border-color: {self.theme.PRIMARY};
        }}
        
        /* === LABEL STYLING === */
        QLabel {{
            color: {self.theme.TEXT_PRIMARY} !important;
            font-family: {self.theme.FONT_FAMILY};
            font-size: {self.theme.FONT_SIZE_NORMAL};
            background: transparent;
        }}
        
        /* === STATUSBAR STYLING === */
        QStatusBar {{
            background-color: {self.theme.SURFACE};
            color: {self.theme.TEXT_SECONDARY} !important;
            border-top: 1px solid {self.theme.BORDER};
            font-family: {self.theme.FONT_FAMILY};
        }}
        
        /* === MENUBAR STYLING === */
        QMenuBar {{
            background-color: {self.theme.SURFACE};
            color: {self.theme.TEXT_PRIMARY} !important;
            border-bottom: 1px solid {self.theme.BORDER};
            font-family: {self.theme.FONT_FAMILY};
        }}
        
        QMenuBar::item {{
            padding: 6px 12px;
            background-color: transparent;
            color: {self.theme.TEXT_PRIMARY} !important;
        }}
        
        QMenuBar::item:selected {{
            background-color: {self.theme.PRIMARY};
            color: {self.theme.TEXT_ON_PRIMARY} !important;
        }}
        
        /* === SCROLLBAR STYLING === */
        QScrollBar:vertical {{
            background: {self.theme.SCROLLBAR_BACKGROUND};
            width: 12px;
            border-radius: 6px;
            margin: 0;
        }}
        
        QScrollBar::handle:vertical {{
            background: {self.theme.SCROLLBAR_HANDLE};
            border-radius: 6px;
            min-height: 20px;
        }}
        
        QScrollBar::handle:vertical:hover {{
            background: {self.theme.SCROLLBAR_HANDLE_HOVER};
        }}
        
        QScrollBar:horizontal {{
            background: {self.theme.SCROLLBAR_BACKGROUND};
            height: 12px;
            border-radius: 6px;
            margin: 0;
        }}
        
        QScrollBar::handle:horizontal {{
            background: {self.theme.SCROLLBAR_HANDLE};
            border-radius: 6px;
            min-width: 20px;
        }}
        
        QScrollBar::handle:horizontal:hover {{
            background: {self.theme.SCROLLBAR_HANDLE_HOVER};
        }}
        
        /* === SPLITTER STYLING === */
        QSplitter::handle {{
            background-color: {self.theme.BORDER};
            width: 2px;
            height: 2px;
        }}
        
        QSplitter::handle:hover {{
            background-color: {self.theme.PRIMARY};
        }}
        """
