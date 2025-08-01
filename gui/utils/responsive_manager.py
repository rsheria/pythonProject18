# gui/utils/responsive_manager.py
from PyQt5.QtWidgets import QHeaderView, QWidget
from PyQt5.QtGui import QGuiApplication

class ResponsiveManager:
    """
    Adjusts columns, trees, and any widgets that need updating after resizing or theme changes.
    """
    
    @staticmethod
    def get_responsive_sidebar_width():
        """
        Calculate responsive width for the sidebar based on screen size.
        Returns:
            int: Width in pixels for the sidebar
        """
        # Get the primary screen
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return 250  # Default width if screen not available
            
        # Get screen width
        screen_width = screen.availableGeometry().width()
        
        # Calculate responsive width (15% of screen width, but between 200 and 300 pixels)
        responsive_width = int(screen_width * 0.15)
        return max(200, min(responsive_width, 300))
    
    @staticmethod
    def apply(root: QWidget):
        """
        Apply responsive layout adjustments to the given root widget and its children.
        
        Args:
            root: The root widget to apply responsive styling to
        """
        try:
            # Get all tables that are the same type as process_threads_table
            if hasattr(root, 'process_threads_table'):
                table_type = type(root.process_threads_table)
                for table in root.findChildren(table_type):
                    hdr = table.horizontalHeader()
                    if hdr:
                        hdr.setSectionResizeMode(QHeaderView.Stretch)

            # Handle category trees
            if hasattr(root, 'category_tree'):
                tree_type = type(root.category_tree)
                for tree in root.findChildren(tree_type):
                    header = tree.header()
                    if header:
                        header.setSectionResizeMode(QHeaderView.ResizeToContents)

            # Update any widgets with an update_style method
            for widget in root.findChildren(QWidget):
                if hasattr(widget, 'update_style') and callable(widget.update_style):
                    try:
                        widget.update_style()
                    except Exception as e:
                        import logging
                        logging.warning(f"Error updating style for {widget}: {e}")
                        
        except Exception as e:
            import logging
            logging.error(f"Error in ResponsiveManager: {e}")
            raise
