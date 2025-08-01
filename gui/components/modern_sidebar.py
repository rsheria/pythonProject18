# gui/components/modern_sidebar.py
"""
🎨 Modern Professional Sidebar Navigation
يشمل:
  • ModernStatusIndicator      (دائرة ملونة للحالة)
  • ModernSidebarItem          (زر عنصر بالقائمة)
  • ModernSidebarSection       (تجميعة عناصر)
  • ModernSidebar              (الحاوية الكاملة)
يدعم Light / Dark Theme عبر theme_manager.update_style().
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSpacerItem
)
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush

from ..themes.modern_theme import theme_manager   # 👈 الثيم


# ----------------------------------------------------------------------
# Helper لاختصار الوصول إلى الثيم الحالى
# ----------------------------------------------------------------------
def T():
    return theme_manager.get_current_theme()


# ----------------------------------------------------------------------
# دائرة حالة صغيرة
# ----------------------------------------------------------------------
class ModernStatusIndicator(QWidget):
    """مؤشّر دائرى ملوّن (success / info / error …)"""

    def __init__(self, color_name: str = "SUCCESS", diameter: int = 10, parent=None):
        super().__init__(parent)
        self.color_name = color_name.upper()
        self.diameter   = diameter
        self.setFixedSize(diameter, diameter)

    def paintEvent(self, _evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = getattr(T(), self.color_name, T().PRIMARY)
        p.setBrush(QBrush(QColor(color)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRect(0, 0, self.diameter, self.diameter))

    def update_style(self):
        self.update()


# ----------------------------------------------------------------------
# عنصر الشريط الجانبى
# ----------------------------------------------------------------------
class ModernSidebarItem(QPushButton):
    clicked_text = pyqtSignal(str)   # يرسل نص العنصر عند الضغط

    def __init__(self, text: str, icon: str = "📄", parent=None):
        super().__init__(parent)
        self.icon = icon
        self.txt  = text
        self.active = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setObjectName("sidebar_item")
        self.setText(f"{self.icon}  {self.txt}")

        # إشارة الضغط
        self.clicked.connect(lambda: self.clicked_text.emit(self.txt))
        self.update_style()

    # --- Active state ---
    def set_active(self, state: bool):
        self.active = state
        self.setProperty("active", state)
        self.style().unpolish(self)
        self.style().polish(self)

    # --- Dynamic style ---
    def update_style(self):
        t = T()
        hover = getattr(t, "SIDEBAR_ITEM_HOVER", t.SIDEBAR_ITEM_ACTIVE)
        self.setStyleSheet(f"""
QPushButton#sidebar_item {{
    background: transparent;
    color: {t.TEXT_SECONDARY};
    border: none;
    border-radius: 6px;
    padding: 0 16px;
    text-align: left;
    font-family: {t.FONT_FAMILY};
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#sidebar_item:hover {{
    background: {hover};
    color: {t.TEXT_PRIMARY};
}}
QPushButton#sidebar_item[active="true"] {{
    background: {t.SIDEBAR_ITEM_ACTIVE};
    color: {t.TEXT_ON_PRIMARY};
    font-weight: 600;
}}
QPushButton#sidebar_item[active="true"]:hover {{
    background: {t.PRIMARY_HOVER};
}}""")

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.active:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(T().PRIMARY), 3))
            p.drawLine(2, 8, 2, self.height() - 8)


# ----------------------------------------------------------------------
# قسم يحتوى على مجموعة عناصر
# ----------------------------------------------------------------------
class ModernSidebarSection(QWidget):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.items = []
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 12, 8, 8)
        self.layout.setSpacing(4)

        if title:
            self.title_lbl = QLabel(title.upper())
            self.layout.addWidget(self.title_lbl)

        self.items_layout = QVBoxLayout()
        self.items_layout.setSpacing(2)
        self.layout.addLayout(self.items_layout)
        self.update_style()

    # إضافة عنصر للقسم
    def add_item(self, text: str, icon="📄") -> ModernSidebarItem:
        item = ModernSidebarItem(text, icon, self)
        self.items.append(item)
        self.items_layout.addWidget(item)
        return item

    def update_style(self):
        t = T()
        if hasattr(self, "title_lbl"):
            self.title_lbl.setStyleSheet(
                f"color:{t.TEXT_TERTIARY}; font-family:{t.FONT_FAMILY}; "
                f"font-size:10px; font-weight:600; letter-spacing:1px;"
            )
        for it in self.items:
            it.update_style()


# ----------------------------------------------------------------------
# الـ Sidebar الكامل
# ----------------------------------------------------------------------
class ModernSidebar(QWidget):
    item_clicked = pyqtSignal(str)    # يرسل نص العنصر الفعال

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sections = []
        self.active_item = None
        self._build_ui()
        self.update_style()

    # ---------- Build UI ----------
    def _build_ui(self):
        self.setObjectName("modern_sidebar")

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ـــ Header (Logo + Title) ـــ
        header = QWidget()
        header.setFixedHeight(72)
        hbox = QVBoxLayout(header)
        hbox.setContentsMargins(12, 8, 12, 8)
        hbox.setSpacing(2)

        self.logo_lbl = QLabel("🤖")  # (اختياري: استبدله بصورة)
        self.logo_lbl.setAlignment(Qt.AlignCenter)
        self.logo_lbl.setFixedHeight(28)
        hbox.addWidget(self.logo_lbl)

        self.title_lbl = QLabel("ForumBot")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        hbox.addWidget(self.title_lbl)

        main.addWidget(header)

        # ـــ Scroll Area ـــ
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.setObjectName("sidebar_scroll")

        cw = QWidget()
        self.content_layout = QVBoxLayout(cw)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(2)
        self.content_layout.setAlignment(Qt.AlignTop)
        sc.setWidget(cw)
        main.addWidget(sc)

        self.scroll_area = sc

    # ---------- API ----------
    def add_section(self, title: str = "") -> ModernSidebarSection:
        sec = ModernSidebarSection(title, self)
        self.sections.append(sec)
        self.content_layout.addWidget(sec)
        return sec

    def add_item(self, text: str, icon="📄") -> ModernSidebarItem:
        """اختصار لإضافة عنصر فى أول قسم (أو قسم افتراضى)."""
        if not self.sections:
            self.add_section("")
        item = self.sections[0].add_item(text, icon)
        item.clicked_text.connect(self._on_item_clicked)
        return item

    def set_active_by_text(self, text: str):
        """فعّل العنصر الذى يطابق نصّه."""
        for it in self.findChildren(ModernSidebarItem):
            if it.txt == text:
                self._activate(it)
                break

    # alias للتماشى مع أسماء قديمة
    def set_active_item_by_text(self, text: str):
        self.set_active_by_text(text)

    # ---------- Signals ----------
    def _on_item_clicked(self, txt: str):
        for it in self.findChildren(ModernSidebarItem):
            if it.txt == txt:
                self._activate(it)
                break

    def _activate(self, item: ModernSidebarItem):
        if self.active_item:
            self.active_item.set_active(False)
        self.active_item = item
        item.set_active(True)
        self.item_clicked.emit(item.txt)

    # ---------- Theme ----------
    def update_style(self):
        t = T()
        # خلفية وحدود
        self.setStyleSheet(
            f"QWidget#modern_sidebar{{background:{t.SIDEBAR_BACKGROUND}; "
            f"border-right:1px solid {t.SIDEBAR_BORDER};}}"
        )
        # Logo & Title
        self.logo_lbl.setStyleSheet("font-size:28px;")
        self.title_lbl.setStyleSheet(
            f"color:{t.TEXT_PRIMARY}; font-family:{t.FONT_FAMILY}; "
            f"font-size:14px; font-weight:600;"
        )
        # ScrollBar colours
        self.scroll_area.setStyleSheet(
            f"QScrollBar:vertical{{background:{t.SIDEBAR_BACKGROUND}; width:8px; border:none;}}"
            f"QScrollBar::handle:vertical{{background:{t.SURFACE_VARIANT}; border-radius:4px; min-height:20px; margin:2px;}}"
            f"QScrollBar::handle:vertical:hover{{background:{t.PRIMARY};}}"
        )
        # Sections & items
        for sec in self.sections:
            sec.update_style()
