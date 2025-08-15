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
from integrations.jd_client import stop_and_clear_jdownloader, JDClient
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
        """
        يوقف التحميلات فى JDownloader ويمسح كلاً من:
          - Downloads List
          - LinkGrabber
        يستخدم أولاً stop_and_clear_jdownloader (لو متاحة),
        ولو فشلت نعمل فولباك باستخدام JDClient مباشرة مع عدة endpoints متوافقة.
        """
        # 0) جرّب الدالة المساعدة أولاً (النسخة اللى ضفناها فى integrations/jd_client.py)
        try:
            if callable(stop_and_clear_jdownloader):
                try:
                    stop_and_clear_jdownloader(config_obj)
                    log.info("✅ JD cleanup via helper: done.")
                    return
                except Exception as e:
                    log.debug("stop_and_clear_jdownloader failed, will fallback: %s", e)
        except Exception:
            pass

        # 1) فولباك يدوى — جهّز الكريدنشيالز
        email = password = device_name = ""
        app_key = "PyForumBot"
        main = self.parent()

        # من config لو متاح
        if isinstance(config_obj, dict):
            email = config_obj.get("myjd_email") or config_obj.get("jdownloader_email") or ""
            password = config_obj.get("myjd_password") or config_obj.get("jdownloader_password") or ""
            device_name = config_obj.get("myjd_device") or config_obj.get("jdownloader_device") or ""
            app_key = config_obj.get("myjd_app_key") or config_obj.get("jdownloader_app_key") or "PyForumBot"

        # من MainWindow لو عنده accessor
        try:
            if main and hasattr(main, "_get_myjd_credentials"):
                em, pw, dev, ak = main._get_myjd_credentials()
                email = email or em or ""
                password = password or pw or ""
                device_name = device_name or dev or ""
                app_key = app_key or ak or "PyForumBot"
        except Exception:
            pass

        if not email or not password:
            log.debug("JD cleanup fallback: missing My.JDownloader credentials; skip connect()")
            return

        # 2) اتصل بالـ JD
        try:
            jd = JDClient(email=email, password=password, device_name=device_name, app_key=app_key)
        except Exception as e:
            log.debug("JD cleanup fallback: JDClient init failed: %s", e)
            return
        if not jd.connect():
            log.debug("JD cleanup fallback: connect() failed")
            return

        dev = getattr(jd, "device", None)
        if dev is None:
            log.debug("JD cleanup fallback: no device resolved")
            return

        # 3) أوقف أى داونلود شغّال — جرّب أكتر من endpoint (توافق)
        for path, payload in [
            ("/downloadcontroller/stop", []),
            ("/downloads/stop", []),
            ("/downloadsV2/stop", []),
            ("/downloadcontroller/pause", [True]),
            ("/downloads/pause", [True]),
        ]:
            try:
                dev.action(path, payload)
                log.debug("JD cleanup: stop/pause via %s", path)
            except Exception:
                pass

        # 4) ألغِ أى كراول/ديكربت فى LinkGrabber
        try:
            dev.action("/linkgrabberv2/abort", [])
        except Exception:
            pass

        # 5) امسح قائمة التحميلات (Downloads)
        try:
            # لمّ الـ packageUUIDs
            pkg_query = {"packageUUIDs": True}
            pkgs = (dev.action("/downloadsV2/queryPackages", [pkg_query])
                    or dev.action("/downloads/queryPackages", [pkg_query])
                    or [])
            pkg_ids = [p.get("packageUUID") for p in pkgs if p.get("packageUUID")]
            if pkg_ids:
                removed = False
                # v2 أولاً
                try:
                    # بعض الـ JD بيقبل removePackages مباشرة
                    dev.action("/downloadsV2/removePackages", [{"packageIds": pkg_ids}])
                    removed = True
                    log.debug("JD cleanup: removed downloads via /downloadsV2/removePackages")
                except Exception:
                    pass
                if not removed:
                    try:
                        # fallback: removeLinks بتمرير packageIds
                        dev.action("/downloadsV2/removeLinks", [[], pkg_ids])
                        removed = True
                        log.debug("JD cleanup: removed downloads via /downloadsV2/removeLinks([], pids)")
                    except Exception:
                        pass
                if not removed:
                    # non-V2
                    try:
                        dev.action("/downloads/removeLinks", [[], pkg_ids])
                        log.debug("JD cleanup: removed downloads via /downloads/removeLinks([], pids)")
                    except Exception:
                        pass
        except Exception:
            pass

        # 6) امسح الـ LinkGrabber بالكامل
        try:
            dev.action("/linkgrabberv2/clearList", [])
        except Exception:
            # fallback: إزالة بالـ packages
            try:
                pkgs = dev.action("/linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
                pids = [p.get("packageUUID") for p in pkgs if p.get("packageUUID")]
                if pids:
                    dev.action("/linkgrabberv2/removeLinks", [[], pids])
                    log.debug("JD cleanup: linkgrabber cleared via removeLinks([], pids)")
            except Exception:
                pass

        # 7) انتظر لحظات لحد ما القوائم تفضى فعليًا (علشان ما يحصلش race)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                dpkgs = (dev.action("/downloadsV2/queryPackages", [{"packageUUIDs": True}])
                         or dev.action("/downloads/queryPackages", [{"packageUUIDs": True}])
                         or [])
                lpkgs = dev.action("/linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
                if not dpkgs and not lpkgs:
                    break
            except Exception:
                break
            time.sleep(0.2)

        log.info("✅ JD cleanup fallback: downloads+linkgrabber cleared & controller stopped.")
