# -*- coding: utf-8 -*-
import threading
import time
import logging

from PyQt5.QtCore import QObject, Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractScrollArea,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionProgressBar,
    QPushButton,
)

# مهم: الدالة دى لازم تكون اتضافت فى integrations/jd_client.py حسب ما اتفقنا
from integrations.jd_client import hard_cancel
from .status_model import StatusTableModel


log = logging.getLogger(__name__)


class ProgressBarDelegate(QStyledItemDelegate):
    """Display integer progress values as a green progress bar."""
    def paint(self, painter, option, index):  # type: ignore[override]
        value = int(index.data(Qt.DisplayRole) or 0)
        opt = QStyleOptionProgressBar()
        opt.rect = option.rect
        opt.minimum = 0
        opt.maximum = 100
        opt.progress = value
        opt.text = f"{value}%"
        opt.textVisible = True
        opt.textAlignment = Qt.AlignCenter
        opt.state = option.state | QStyle.State_Enabled
        # adapt progress bar colour to theme
        palette = QApplication.palette()
        opt.palette = palette
        base = palette.color(QPalette.Base)
        is_dark = base.lightness() < 128
        bar_color = QColor("#66bb6a") if is_dark else QColor("#2e7d32")
        opt.palette.setColor(QPalette.Highlight, bar_color)
        opt.palette.setColor(QPalette.HighlightedText, QColor("white"))
        QApplication.style().drawControl(QStyle.CE_ProgressBar, opt, painter)


class StatusWidget(QWidget):
    """
    بانل الحالة:
      - بتعرض العمليات
      - زرار Cancel:
          * بيبعت إشارة إلغاء للـ workers (منطقك الحالى)
          * وبشكل موازى بيعمل Stop + Clear كامل فى JDownloader عشان ما يكمّلش تحميل
    """
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = StatusTableModel()
        layout = QVBoxLayout(self)

        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setAlternatingRowColors(True)

        # Improve responsiveness and readability
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        # allow the message column to take remaining space
        header.setSectionResizeMode(5, QHeaderView.Stretch)

        self.table.verticalHeader().setVisible(False)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.table.setSortingEnabled(True)

        # Use a progress bar delegate for the Progress column
        self.table.setItemDelegateForColumn(10, ProgressBarDelegate(self.table))
        layout.addWidget(self.table)

        self.cancel_event = threading.Event()
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        layout.addWidget(self.btn_cancel)

    def connect_worker(self, worker: QObject) -> None:
        # توصيل تحديثات التقدّم بالجدول (منطقك الحالى)
        if hasattr(worker, "progress_update"):
            worker.progress_update.connect(self.model.upsert)
        # لو الووركر بيدعم cancel_event، خلّيه ياخده (اختيارى)
        try:
            if hasattr(worker, "set_cancel_event"):
                worker.set_cancel_event(self.cancel_event)
            elif hasattr(worker, "cancel_event"):
                worker.cancel_event = self.cancel_event
        except Exception:
            pass

    def on_cancel_clicked(self) -> None:
        """
        لما تدوس Cancel:
          1) إشارة إلغاء لكل الووركرز فى البرنامج (منطقك الحالى)
          2) إيقاف فورى للـ JDownloader + تنظيف كامل لقوائم التحميل والـ LinkGrabber
             (فى Thread منفصل عشان الـ UI ما يهنّجش)
        """
        # (1) إلغاء داخلى للووركرز
        self.cancel_event.set()
        parent = self.parent()
        try:
            if parent and hasattr(parent, "cancel_downloads"):
                parent.cancel_downloads()
        except Exception as e:
            log.debug("cancel_downloads call failed: %s", e)

        # (2) تنظيف شامل للـ JD فى Thread منفصل
        try:
            cfg = getattr(parent, "config", None)
            t = threading.Thread(target=self._jd_full_cancel_cleanup, args=(cfg,), daemon=True)
            t.start()
        except Exception as e:
            log.error("Failed to start JD cancel cleanup thread: %s", e)

    # ===== Helper: JD full cleanup =====
    def _jd_full_cancel_cleanup(self, config_obj):
        # جرّب الهارد-كانسيل المحلي أولاً باستخدام جلسة الووركر الحالية
        try:
            parent = self.parent()
            worker = getattr(parent, "download_worker", None)
            if worker and hasattr(worker, "_jd_post") and callable(worker._jd_post):
                from integrations.jd_client import hard_cancel
                hard_cancel(worker._jd_post, logger=log)
                log.info("✅ Local JD hard-cancel done (downloads + linkgrabber cleared).")
                return  # ما تكملش على السحابة لو المحلي نجح
        except Exception as e:
            log.debug("Local hard_cancel failed, will try helper/fallback: %s", e)

        # لا نحاول اتصال جديد – فقط نسجل الفشل
        log.warning("⚠️ No JD session available for cancel cleanup")

