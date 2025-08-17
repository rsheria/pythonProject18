
import logging
import os
import threading
from PyQt5.QtCore import QObject
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QProgressBar,
)
from integrations.jd_client import hard_cancel
from models.operation_status import OperationStatus, OpStage, OpType

HOST_COLS = {
    "rapidgator": "RG",
    "ddownload": "DDL",
    "katfile": "KF",
    "nitroflare": "NF",
    "mega": "MEGA",
}

log = logging.getLogger(__name__)

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
        layout = QVBoxLayout(self)
        self.table = QTableWidget(self)
        headers = [
            "Section",
            "Item",
            "Stage",
            "Message",
            "Speed",
            "ETA",
            "Progress",
            "RG",
            "DDL",
            "KF",
            "NF",
            "MEGA",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self._host_col_index = {host: headers.index(label) for host, label in HOST_COLS.items()}
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.table.verticalHeader().setVisible(False)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        layout.addWidget(self.table)

        self.cancel_event = threading.Event()
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        layout.addWidget(self.btn_cancel)

        self._row_by_key = {}
        self._bar_at = {}

    # Helpers -------------------------------------------------------------
    @staticmethod
    def _fmt_speed(bps: float) -> str:
        if bps <= 0:
            return "-"
        units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
        idx = 0
        while bps >= 1024 and idx < len(units) - 1:
            bps /= 1024.0
            idx += 1
        return f"{bps:.1f} {units[idx]}"

    @staticmethod
    def _fmt_eta(sec: float) -> str:
        if sec <= 0:
            return "-"
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:d}:{s:02d}"

    def _color_row(self, row: int, stage: OpStage) -> None:
        overlays = {
            OpStage.RUNNING: QColor(255, 255, 0, 60),
            OpStage.FINISHED: QColor(0, 255, 0, 60),
            OpStage.ERROR: QColor(255, 0, 0, 60),
        }
        overlay = overlays.get(stage)
        if not overlay:
            return
        pal = self.table.palette()
        base_role = QPalette.Base if row % 2 == 0 else QPalette.AlternateBase
        base = pal.color(base_role)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, col, item)
            color = QColor(
                (base.red() * (255 - overlay.alpha()) + overlay.red() * overlay.alpha()) // 255,
                (base.green() * (255 - overlay.alpha()) + overlay.green() * overlay.alpha()) // 255,
                (base.blue() * (255 - overlay.alpha()) + overlay.blue() * overlay.alpha()) // 255,
            )
            item.setBackground(color)

    # Status handling -----------------------------------------------------
    def _ensure_bar(self, row: int, col: int) -> QProgressBar:
        key = (row, col)
        bar = self._bar_at.get(key)
        if bar is None:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setFormat("%p%")
            self.table.setCellWidget(row, col, bar)
            self._bar_at[key] = bar
        return bar

    def handle_status(self, st: OperationStatus) -> None:
        key = (st.section, st.item, st.op_type.name)
        row = self._row_by_key.get(key)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col in range(self.table.columnCount()):
                self.table.setItem(row, col, QTableWidgetItem(""))
            self._row_by_key[key] = row

        data = [
            st.section,
            st.item,
            st.stage.name.title(),
            st.message,
            self._fmt_speed(st.speed),
            self._fmt_eta(st.eta),
        ]
        for col, value in enumerate(data):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, col, item)
            item.setText(str(value))

        if st.op_type == OpType.UPLOAD:
            host = (st.host or "").lower()
            col = self._host_col_index.get(host)
            if col is not None:
                bar = self._ensure_bar(row, col)
                bar.setValue(max(0, min(100, int(st.progress))))
        else:
            bar = self._ensure_bar(row, 6)
            bar.setValue(max(0, min(100, int(st.progress))))

        self._color_row(row, st.stage)
    def connect_worker(self, worker: QObject) -> None:
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
        """Perform full JDownloader cancel/cleanup.

        Tries to reuse the current worker session first. If unavailable,
        establishes a temporary connection using credentials from ``config_obj``
        or environment variables (MYJD_*) and runs ``hard_cancel``.
        """
        # 1) جرّب الهارد-كانسيل المحلي أولاً باستخدام جلسة الووركر الحالية
        try:
            parent = self.parent()
            worker = getattr(parent, "download_worker", None)
            if worker and hasattr(worker, "_jd_post") and callable(worker._jd_post):
                ok = hard_cancel(worker._jd_post, logger=log)
                if ok:
                    log.info(
                        "✅ Local JD hard-cancel done (downloads + linkgrabber cleared.)"
                    )
                    return  # ما تكملش على السحابة لو المحلي نجح
                else:
                    log.warning("❌ JD hard-cancel failed to clean device")
        except Exception as e:
            log.debug("Local hard_cancel failed, will try helper/fallback: %s", e)

        # 2) لو مفيش جلسة موجودة، افتح واحدة مؤقتة باستخدام بيانات الإعدادات/البيئة
        try:
            cfg = config_obj or {}
            email = (
                cfg.get("myjd_email")
                or os.getenv("MYJD_EMAIL")
                or ""
            ).strip()
            password = (
                cfg.get("myjd_password")
                or os.getenv("MYJD_PASSWORD")
                or ""
            ).strip()
            device_name = (
                cfg.get("myjd_device")
                or os.getenv("MYJD_DEVICE")
                or ""
            ).strip()
            app_key = (
                cfg.get("myjd_app_key")
                or os.getenv("MYJD_APP_KEY")
                or "PyForumBot"
            ).strip()
            if email and password:
                from integrations.jd_client import JDClient

                jd = JDClient(email, password, device_name, app_key)
                if jd.connect():
                    def _jd_post(path, payload=None):
                        return jd.device.action(
                            "/" + path if not path.startswith("/") else path,
                            [] if payload is None else payload,
                        )

                    if hard_cancel(_jd_post, logger=log):
                        log.info("✅ JD cancel cleanup via new session done")
                        return
                    else:
                        log.warning("❌ JD cancel cleanup via new session failed")
            else:
                log.warning("⚠️ Missing JD credentials for cancel cleanup")
        except Exception as e:
            log.warning(f"⚠️ JD fallback cleanup failed: {e}")

        # 3) لو كل المحاولات فشلت
        log.warning("⚠️ No JD session available for cancel cleanup")

