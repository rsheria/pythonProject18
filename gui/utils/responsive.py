# gui/utils/responsive.py
"""
🔄 Responsive Design Utilities
Dynamic sizing and responsive behavior for the modern UI
"""

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QSize
from ..themes import ModernTheme

class ResponsiveManager:
    """Manages responsive behavior for the application"""
    
    @staticmethod
    def get_screen_size():
        """Get current screen dimensions"""
        screen = QApplication.primaryScreen()
        return screen.size()
    
    @staticmethod
    def get_responsive_font_size(base_size_str):
        """Get font size based on screen size"""
        screen_size = ResponsiveManager.get_screen_size()
        width = screen_size.width()
        
        # Parse base size (remove 'px')
        base_size = int(base_size_str.replace('px', ''))
        
        # Scale factor based on screen width
        if width < 1366:  # Small screens
            scale = 0.9
        elif width < 1920:  # Medium screens
            scale = 1.0
        else:  # Large screens
            scale = 1.1
        
        new_size = int(base_size * scale)
        return f"{new_size}px"
    
    @staticmethod
    def get_responsive_sidebar_width():
        """Get sidebar width based on screen size"""
        screen_size = ResponsiveManager.get_screen_size()
        width = screen_size.width()
        
        if width < 1366:  # Small screens
            return 220
        elif width < 1920:  # Medium screens
            return 260
        else:  # Large screens
            return 280
    
    @staticmethod
    def get_responsive_spacing():
        """Get spacing based on screen size"""
        screen_size = ResponsiveManager.get_screen_size()
        width = screen_size.width()
        
        if width < 1366:  # Small screens
            return {
                'small': 4,
                'medium': 8,
                'large': 12
            }
        elif width < 1920:  # Medium screens
            return {
                'small': 6,
                'medium': 12,
                'large': 18
            }
        else:  # Large screens
            return {
                'small': 8,
                'medium': 16,
                'large': 24
            }
    
    @staticmethod
    def apply_responsive_styling(widget):
        """Apply responsive styling to a widget"""
        # Get responsive values
        font_size = ResponsiveManager.get_responsive_font_size(ModernTheme.FONT_SIZE_NORMAL)
        
        # Apply responsive font
        current_style = widget.styleSheet()
        responsive_style = f"""
        {current_style}
        
        /* Responsive text sizing */
        * {{
            font-size: {font_size};
        }}
        
        /* Responsive margins and padding */
        QWidget {{
            margin: 4px;
            padding: 2px;
        }}
        
        QPushButton {{
            min-height: 28px;
            padding: 6px 12px;
        }}
        
        QLineEdit, QTextEdit {{
            padding: 6px 10px;
            min-height: 14px;
        }}
        """
        
        widget.setStyleSheet(responsive_style)
