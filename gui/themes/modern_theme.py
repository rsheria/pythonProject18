# gui/themes/modern_theme.py
"""
🎨 Modern Professional Theme System
Inspired by VS Code, Discord, and other modern applications
"""

class ModernTheme:
    """Professional dark theme with modern colors"""

    # === COLORS ===
    # 🏠 Background Colors - Enhanced contrast
    BACKGROUND = '#0f0f0f'              # Deep dark background
    SURFACE = '#1e1e1e'                 # Card/panel background
    SURFACE_ELEVATED = '#2A2A2A'        # Elevated surfaces (menus, dialogs)
    SURFACE_VARIANT = "#2F2F2F"         # Alternative surface color

    # 🔵 Accent Colors
    PRIMARY = '#007acc'                 # Main brand color (VS Code blue)
    PRIMARY_HOVER = '#1177bb'           # Hover state for primary

    # ✅ Semantic Colors
    SUCCESS = "#4caf50"                 # Green for success states
    SUCCESS_LIGHT = "#81c784"           # Light green
    WARNING = "#ff9800"                 # Orange for warnings
    WARNING_LIGHT = "#ffb74d"           # Light orange
    ERROR = "#f44336"                   # Red for errors
    ERROR_LIGHT = "#e57373"             # Light red
    INFO = "#2196f3"                    # Blue for info
    INFO_LIGHT = "#64b5f6"              # Light blue

    # 📝 Text Colors
    TEXT_PRIMARY = "#f5f5f5"        # Off-white for comfort
    TEXT_SECONDARY = "#cccccc"      # Light gray
    TEXT_TERTIARY = "#616161"           # Tertiary text
    TEXT_DISABLED = "#777777"       # Disabled text
    TEXT_ON_PRIMARY = "#ffffff"     # Text on primary colored backgrounds

    # 🔲 Border & Separator Colors
    BORDER = '#3e3e42'                  # Subtle borders
    BORDER_LIGHT = '#454545'            # Lighter borders
    SEPARATOR = '#323233'               # Section separators
    DIVIDER = '#404040'                 # Content dividers

    # 📱 Sidebar Specific Colors - Enhanced visibility
    SIDEBAR_BACKGROUND = "#141414"     # Darker sidebar background
    SIDEBAR_BORDER = "#404040"         # Visible border
    SIDEBAR_ITEM_HOVER = "#2a2a2a"     # Clear hover state
    SIDEBAR_ITEM_ACTIVE = "#007acc"    # Active item background (blue)
    SIDEBAR_ITEM_SELECTED = "#37373d"   # Selected item
    SIDEBAR_ITEM_TEXT = "#f5f5f5"      # Clear text colored item

    # 📊 Status Colors (Discord inspired)
    STATUS_ONLINE = '#43b581'           # Online/active status
    STATUS_IDLE = '#faa61a'             # Idle/warning status
    STATUS_OFFLINE = '#747f8d'          # Offline/inactive status
    STATUS_DND = '#f04747'              # Do not disturb/error status

    # 🎭 Input Colors
    INPUT_BACKGROUND = '#3c3c3c'        # Input field background
    INPUT_BORDER = '#464647'            # Input border
    INPUT_BORDER_FOCUS = '#007acc'      # Focused input border
    INPUT_PLACEHOLDER = '#6a6a6a'       # Placeholder text

    # 🔳 Button Colors
    BUTTON_BACKGROUND = '#0e639c'       # Default button background
    BUTTON_HOVER = '#1177bb'            # Button hover state
    BUTTON_PRESSED = '#005a9e'          # Button pressed state
    BUTTON_DISABLED = '#474747'         # Disabled button
    BUTTON_SECONDARY = '#5a5a5a'        # Secondary button
    BUTTON_SECONDARY_HOVER = '#6a6a6a'  # Secondary button hover
    BUTTON_TEXT_COLOR = TEXT_ON_PRIMARY       # 👈 جديد
    # 📋 Table Colors
    TABLE_HEADER = '#383838'            # Table header background
    TABLE_ROW_EVEN = '#2d2d30'          # Even row background
    TABLE_ROW_ODD = '#252526'           # Odd row background
    TABLE_ROW_HOVER = '#3e3e42'         # Row hover state
    TABLE_ROW_SELECTED = '#094771'      # Selected row

    # 🎪 Progress Colors
    PROGRESS_BACKGROUND = '#404040'     # Progress bar background
    PROGRESS_FILL = '#007acc'           # Progress bar fill
    PROGRESS_SUCCESS = '#4caf50'        # Success progress
    PROGRESS_WARNING = '#ff9800'        # Warning progress
    PROGRESS_ERROR = '#f44336'          # Error progress

    # 🌟 Special Effects
    SHADOW_LIGHT = 'rgba(0, 0, 0, 0.1)' # Light shadow
    SHADOW_MEDIUM = 'rgba(0, 0, 0, 0.2)' # Medium shadow
    SHADOW_HEAVY = 'rgba(0, 0, 0, 0.4)'  # Heavy shadow
    GLOW_PRIMARY = 'rgba(0, 122, 204, 0.3)' # Primary glow effect

    # 📏 Spacing & Sizing
    RADIUS_SMALL = '4px'                # Small border radius
    RADIUS_MEDIUM = '6px'               # Medium border radius
    RADIUS_LARGE = '8px'                # Large border radius
    RADIUS_XLARGE = '12px'              # Extra large border radius

    # 🆔 Typography
    FONT_FAMILY = '"SF Pro Display", "Segoe UI", "Roboto", "Helvetica Neue", Arial, sans-serif'
    FONT_SIZE_SMALL = '11px'
    FONT_SIZE_NORMAL = '13px'
    FONT_SIZE_HEADING = '15px'
    FONT_SIZE_TITLE = '18px'
    FONT_SIZE_LARGE = '20px'

    @classmethod
    def get_color_palette(cls):
        """Get all colors as a dictionary"""
        return {
            'background': cls.BACKGROUND,
            'surface': cls.SURFACE,
            'surface_elevated': cls.SURFACE_ELEVATED,
            'primary': cls.PRIMARY,
            'primary_hover': cls.PRIMARY_HOVER,
            'success': cls.SUCCESS,
            'warning': cls.WARNING,
            'error': cls.ERROR,
            'text_primary': cls.TEXT_PRIMARY,
            'text_secondary': cls.TEXT_SECONDARY,
            'border': cls.BORDER,
            'sidebar_bg': cls.SIDEBAR_BACKGROUND,
            'sidebar_hover': cls.SIDEBAR_ITEM_HOVER,
            'sidebar_active': cls.SIDEBAR_ITEM_ACTIVE,
        }

# gui/themes/modern_theme.py

class LightTheme:
    """Professional light theme (fully featured)"""

    # === SURFACES ===
    BACKGROUND        = "#ffffff"   # صفحة التطبيق
    SURFACE           = "#f7f9fc"   # خلفيّات البطاقات
    SURFACE_ELEVATED  = "#ffffff"
    SURFACE_VARIANT   = "#eceff4"   # درجـة ثلجية للفروق الطفيفة

    # === BRAND / PRIMARY ===
    PRIMARY           = "#0a84ff"   # أزرق هادئ (iOS blue)
    PRIMARY_HOVER     = "#006ddf"

    # === STATUS COLORS ===
    SUCCESS           = "#28a745"
    WARNING           = "#ffc107"
    ERROR             = "#dc3545"
    INFO              = "#17a2b8"

    # === TEXT ===
    TEXT_PRIMARY      = "#212529"
    TEXT_SECONDARY    = "#5f6b7a"
    TEXT_TERTIARY     = "#8c949d"
    TEXT_ON_PRIMARY   = "#ffffff"
    TEXT_DISABLED     = "#9ca3af"

    # === BORDERS & SEPARATORS ===
    BORDER            = "#d0d7de"
    SIDEBAR_BORDER    = "#c9ccd1"
    SEPARATOR         = "#d9dee3"

    # === SIDEBAR ===
    SIDEBAR_BACKGROUND = "#f1f1f1"
    SIDEBAR_ITEM_HOVER = "#e7f0ff"
    SIDEBAR_ITEM_ACTIVE = "#007acc"
    SIDEBAR_ITEM_SELECTED = "#e0e0e0"
    SIDEBAR_ITEM_TEXT   = "#212529"

    # === INPUTS ===
    INPUT_BACKGROUND   = "#ffffff"
    INPUT_BORDER       = "#ced4da"
    INPUT_BORDER_FOCUS = "#80bdff"

    # === BUTTONS ===
    BUTTON_BACKGROUND  = PRIMARY
    BUTTON_HOVER       = PRIMARY_HOVER
    BUTTON_PRESSED     = "#005bb5"
    BUTTON_DISABLED    = "#cfd4da"
    BUTTON_TEXT_COLOR  = TEXT_ON_PRIMARY

    # === PROGRESS BAR ===
    PROGRESS_BACKGROUND = "#e9ecef"
    PROGRESS_FILL       = PRIMARY

    # === SPACING & RADII ===
    RADIUS_SMALL   = "4px"
    RADIUS_MEDIUM  = "6px"
    RADIUS_LARGE   = "8px"
    RADIUS_XLARGE  = "12px"

    # === TYPOGRAPHY ===
    FONT_FAMILY       = '"SF Pro Display", "Segoe UI", "Roboto", "Helvetica Neue", Arial, sans-serif'
    FONT_SIZE_SMALL   = "11px"
    FONT_SIZE_NORMAL  = "13px"
    FONT_SIZE_HEADING = "15px"
    FONT_SIZE_TITLE   = "18px"
    FONT_SIZE_LARGE   = "20px"

    # === TABLE HEADER ===
    TABLE_HEADER = "#f0f2f5"

    # === SHADOWS (للبطاقات إن احتجت) ===
    SHADOW_LIGHT  = "rgba(0, 0, 0, 0.08)"
    SHADOW_MEDIUM = "rgba(0, 0, 0, 0.16)"
    SHADOW_HEAVY  = "rgba(0, 0, 0, 0.32)"


# 🎨 Theme Manager
class ThemeManager:
    """Manage theme switching and application"""

    def __init__(self):
        # keep references so we can toggle back & forth
        self.default_theme = ModernTheme
        self.light_theme = LightTheme
        self.current_theme = self.default_theme
        self.theme_mode = 'dark'  # 'dark' or 'light'

    def get_current_theme(self):
        """Get the currently active theme"""
        return self.current_theme

    def switch_theme(self, mode='dark'):
        """Switch between dark and light themes"""
        if mode == 'dark':
            self.current_theme = ModernTheme
        else:
            self.current_theme = LightTheme
        self.theme_mode = mode

    def get_color(self, color_name):
        """Get a specific color from current theme"""
        return getattr(self.current_theme, color_name.upper(), '#ffffff')

# Global theme instance
theme_manager = ThemeManager()
