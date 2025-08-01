# gui/components/modern_cards.py
"""
🎨 Modern Card Components
Professional card‑based layouts for content sections
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy, QSpacerItem
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush

# ➜ اجلب الثيم الحالى ديناميكيًا
from ..themes.modern_theme import theme_manager


# ----------------------------------------------------------------------
# Helper – ارجع القيم من الثيم الحالى بسرعة
# ----------------------------------------------------------------------
def T():
    """Return current theme (shortcut)."""
    return theme_manager.get_current_theme()


# ----------------------------------------------------------------------
# ModernCard
# ----------------------------------------------------------------------
class ModernCard(QWidget):
    """Modern card widget with shadow and rounded corners"""

    def __init__(self, title: str | None = None, subtitle: str | None = None, parent=None):
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.setup_ui()
        self.update_style()      # ← طبّق الألوان فورًا

    # ---------- UI ----------
    def setup_ui(self):
        self.setObjectName("modern_card")

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        # Header
        if self.title or self.subtitle:
            self._build_header()

        # Content area
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(8)
        self.main_layout.addLayout(self.content_layout)

    def _build_header(self):
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        if self.title:
            title_lbl = QLabel(self.title)
            header_layout.addWidget(title_lbl)
            self.title_lbl = title_lbl   # للحفظ إن أردت تعديل لاحق

        if self.subtitle:
            sub_lbl = QLabel(self.subtitle)
            header_layout.addWidget(sub_lbl)
            self.subtitle_lbl = sub_lbl

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        header_layout.addWidget(sep)

        self.main_layout.addLayout(header_layout)

    # ---------- Styling ----------
    def update_style(self):
        t = T()

        # Card background + border
        self.setStyleSheet(
            f"""
QWidget#modern_card {{
    background:   {t.SURFACE};
    border:       1px solid {t.BORDER};
    border-radius:{t.RADIUS_MEDIUM};
}}
QWidget#modern_card:hover {{
    background:   {t.SURFACE_VARIANT};
    border-color: {t.PRIMARY};
}}"""
        )

        # Labels (if present)
        if hasattr(self, "title_lbl"):
            self.title_lbl.setStyleSheet(
                f"color:{t.TEXT_PRIMARY}; font-family:{t.FONT_FAMILY}; "
                f"font-size:{t.FONT_SIZE_HEADING}; font-weight:600;"
            )
        if hasattr(self, "subtitle_lbl"):
            self.subtitle_lbl.setStyleSheet(
                f"color:{getattr(t,'TEXT_SECONDARY', t.TEXT_PRIMARY)}; "
                f"font-family:{t.FONT_FAMILY}; font-size:{t.FONT_SIZE_NORMAL};"
            )

        # Separator colour
        for child in self.findChildren(QFrame):
            if child.frameShape() == QFrame.HLine:
                child.setStyleSheet(
                    f"background:{getattr(t, 'SEPARATOR', t.BORDER)}; height:1px; border:none;"
                )

    # ---------- Public API ----------
    def add_widget(self, widget):
        self.content_layout.addWidget(widget)

    def add_layout(self, layout):
        self.content_layout.addLayout(layout)


# ----------------------------------------------------------------------
# ModernSectionCard – Card مع أيقونة عنوان
# ----------------------------------------------------------------------
class ModernSectionCard(ModernCard):
    def __init__(self, title: str, icon: str = "📄", parent=None):
        self.icon_char = icon
        super().__init__(title, None, parent)

    def _build_header(self):
        t = T()
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        # Icon
        icon_lbl = QLabel(self.icon_char)
        icon_lbl.setStyleSheet(
            f"font-size:20px; min-width:24px; color:{t.PRIMARY};"
        )
        header_layout.addWidget(icon_lbl)

        # Title
        title_lbl = QLabel(self.title)
        title_lbl.setStyleSheet(
            f"color:{t.TEXT_PRIMARY}; font-family:{t.FONT_FAMILY}; "
            f"font-size:{getattr(t,'FONT_SIZE_TITLE', '16px')}; font-weight:600;"
        )
        header_layout.addWidget(title_lbl)

        # Spacer
        header_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.main_layout.addLayout(header_layout)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        self.main_layout.addWidget(sep)

    # عند تبديل الثيم نعيد استدعاء update_style من الأب


# ----------------------------------------------------------------------
# ModernScrollArea
# ----------------------------------------------------------------------
class ModernScrollArea(QScrollArea):
    """ScrollArea بنمط حديث"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.update_style()

    def setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)

    def update_style(self):
        t = T()
        self.setStyleSheet(
            f"""
QScrollArea {{ background:transparent; border:none; }}
QScrollBar:vertical {{
    background:{t.SURFACE};
    width:10px; border-radius:5px;
}}
QScrollBar::handle:vertical {{
    background:{t.BORDER}; border-radius:5px; min-height:20px; margin:2px;
}}
QScrollBar::handle:vertical:hover {{ background:{t.PRIMARY}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; background:none; border:none; }}
"""
        )


# ----------------------------------------------------------------------
# ModernContentContainer
# ----------------------------------------------------------------------
class ModernContentContainer(QWidget):
    """Container scrolling vertically holding multiple cards"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.update_style()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(12)

        # Scroll area with internal widget
        self.scroll_area  = ModernScrollArea()
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(12)

        # Spacer for push‑down
        self.scroll_layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area)

    def update_style(self):
        t = T()
        self.setStyleSheet(f"background:{t.BACKGROUND};")

    # ---------- API ----------
    def add_card(self, card: QWidget):
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)

    def add_widget(self, widget: QWidget):
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, widget)
