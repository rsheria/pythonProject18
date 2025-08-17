
import logging
import os
import threading
from PyQt5.QtCore import QTimer, Qt, QSize, QEvent, QObject
from PyQt5.QtGui import QColor, QPalette, QBrush
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QProgressBar,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyle,
    QApplication,
)
from core.user_manager import get_user_manager
from integrations.jd_client import hard_cancel
from models.operation_status import OperationStatus, OpStage, OpType


class ProgressBarDelegate(QStyledItemDelegate):
    """ProgressBar يحترم الـPalette الحالية ويرفع التباين تلقائيًا فى الدارك."""
    @staticmethod
    def _is_dark(pal: QPalette) -> bool:
        c = pal.color(QPalette.Window)
        # تقدير إضاءة اللون (0=داكن)
        lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
        return lum < 0.5

    def paint(self, painter, option, index):
        # نرسم البار فقط لو فيه قيمة فى UserRole
        val = index.data(Qt.UserRole)
        if val is None:
            return QStyledItemDelegate.paint(self, painter, option, index)

        try:
            value = int(val)
        except Exception:
            value = 0
        value = max(0, min(100, value))

        # ارسم الخلفية الافتراضية (سيليكشن/رو باكجراوند)
        QStyledItemDelegate.paint(self, painter, option, index)

        pal = QPalette(option.palette)
        dark = self._is_dark(pal)

        # خلفية البروجريس (مشتقة من Base بلا ألوان ثابتة)
        base_bg = pal.color(QPalette.Base)
        btn_bg = base_bg.lighter(115) if dark else base_bg.darker(102)

        # لون الشريط (Highlight) مُحسّن للتباين
        chunk = pal.color(QPalette.Highlight)
        chunk = chunk.lighter(130) if dark else chunk.darker(100)

        # لون النص على الشريط
        text_col = pal.color(QPalette.HighlightedText)
        if dark and text_col.lightnessF() > 0.85:
            text_col = pal.color(QPalette.BrightText)
        if (not dark) and text_col.lightnessF() < 0.15:
            text_col = pal.color(QPalette.WindowText)

        pal.setColor(QPalette.Button, btn_bg)
        pal.setColor(QPalette.Window, btn_bg)
        pal.setColor(QPalette.Highlight, chunk)
        pal.setColor(QPalette.HighlightedText, text_col)

        opt = QStyleOptionProgressBar()
        opt.rect = option.rect.adjusted(2, 6, -2, -6)  # padding بسيط
        opt.minimum = 0
        opt.maximum = 100
        opt.progress = value
        opt.text = f"{value}%"
        opt.textVisible = True
        opt.textAlignment = Qt.AlignCenter
        opt.state = option.state
        opt.palette = pal

        QApplication.style().drawControl(QStyle.CE_ProgressBar, opt, painter)

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        return QSize(sz.width(), max(sz.height(), 22))





HOST_COLS = {
    "rapidgator": "RG",
    "rapidgator_bak": "RG_BAK",
    "ddownload": "DDL",
    "katfile": "KF",
    "nitroflare": "NF",
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
            "Section", "Item", "Stage", "Message", "Speed", "ETA",
            "Progress", "RG", "DDL", "KF", "NF", "RG_BAK",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        # أعمدة البروجريس
        try:
            self._progress_col = [self.table.horizontalHeaderItem(i).text() for i in
                                  range(self.table.columnCount())].index("Progress")
        except ValueError:
            self._progress_col = None

        # أعمدة الهوستات بالترتيب الثابت
        host_header_names = ["RG", "DDL", "KF", "NF", "RG_BAK"]  # ثابتة زى ما انت محدد
        self._host_cols = []
        for name in host_header_names:
            try:
                idx = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())].index(name)
                self._host_cols.append(idx)
            except ValueError:
                pass

        # ثبت الـDelegate
        self._progress_delegate = ProgressBarDelegate(self.table)
        if self._progress_col is not None:
            self.table.setItemDelegateForColumn(self._progress_col, self._progress_delegate)
        for c in self._host_cols:
            self.table.setItemDelegateForColumn(c, self._progress_delegate)

        self._host_col_index = {host: headers.index(label) for host, label in HOST_COLS.items()}

        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        # خرائط الأعمدة بالاسم (لازم تكون نفس رؤوس الجدول)
        self._col_map = {self.table.horizontalHeaderItem(i).text(): i for i in range(self.table.columnCount())}

        # إعداد الحفظ المؤجل (debounce) عشان مانكتبش الملف مع كل tick
        self._persist_filename = "status_snapshot.json"
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)  # ms
        self._save_timer.timeout.connect(self._save_status_snapshot, Qt.QueuedConnection)

        self.table.verticalHeader().setVisible(False)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        layout.addWidget(self.table)

        self.cancel_event = threading.Event()
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        layout.addWidget(self.btn_cancel)

        self._row_by_key = {}
        self._thread_steps = {}  # 🆕 تجميع خطوات كل Thread => {(section,item): {(op,host)->state}}
        self._bar_at = {}

        self._apply_readability_palette()
        self._row_brushes = self._status_brushes(self.table.palette())

    def reload_from_disk(self, *_):
        """Reload the status snapshot from disk for the current user."""
        self.table.setRowCount(0)
        self._row_by_key.clear()
        self._thread_steps.clear()
        self._bar_at.clear()
        self._load_status_snapshot()
        self.table.resizeColumnsToContents()
        self.table.viewport().update()
    def changeEvent(self, event):
        if event.type() == QEvent.PaletteChange:
            # لو المستخدم بدّل Light/Dark نعيد ضبط الألوان المشتقة
            self._apply_readability_palette()
            self._row_brushes = self._status_brushes(self.table.palette())
            model = self.table.model()
            stage_col = self._col_map.get("Stage")
            for row in range(self.table.rowCount()):
                txt = self.table.item(row, stage_col).text() if stage_col is not None and self.table.item(row, stage_col) else ""
                stage = self._stage_from_text(txt)
                self._color_row(row, stage)
            if self.table.rowCount():
                tl = model.index(0, 0)
                br = model.index(self.table.rowCount() - 1, self.table.columnCount() - 1)
                model.dataChanged.emit(tl, br, [Qt.BackgroundRole])
            self.table.viewport().update()
        super().changeEvent(event)

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

    def _status_brushes(self, pal: QPalette) -> dict:
        """توليد فرش ملوّنة مشتقة من الـPalette الحالى."""
        brushes = {}
        hl = pal.color(QPalette.Highlight)
        alt = pal.color(QPalette.AlternateBase)
        base = pal.color(QPalette.Base)

        c = QColor(hl)
        c.setAlpha(160)
        brushes[OpStage.FINISHED] = QBrush(c)

        c = QColor(alt)
        c.setAlpha(120)
        brushes[OpStage.RUNNING] = QBrush(c)

        c = QColor(hl.darker(140))
        c.setAlpha(160)
        brushes[OpStage.ERROR] = QBrush(c)

        cancelled = getattr(OpStage, 'CANCELLED', None)
        if cancelled is not None:
            c = QColor(base.darker(115))
            c.setAlpha(140)
            brushes[cancelled] = QBrush(c)
        return brushes

    def _color_row(self, row: int, stage: OpStage, op_type: OpType | None = None) -> None:
        pal = self.table.palette()
        base_role = QPalette.Base if row % 2 == 0 else QPalette.AlternateBase
        base = pal.color(base_role)
        overlay = self._row_brushes.get(stage)
        if overlay is not None:
            oc = overlay.color()
            a = oc.alpha()
            color = QColor(
                (base.red() * (255 - a) + oc.red() * a) // 255,
                (base.green() * (255 - a) + oc.green() * a) // 255,
                (base.blue() * (255 - a) + oc.blue() * a) // 255,
            )
        else:
            color = base
        brush = QBrush(color)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, col, item)
            item.setBackground(brush)
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

    # 🆕 Thread aggregation helpers --------------------------------------
    # ---------- Persistence Helpers (per-user) ----------
    def _user_mgr(self):
        try:
            return get_user_manager()
        except Exception:
            return None

    def _schedule_status_save(self):
        """ابدأ/جدّد المؤقت لحفظ Snapshot قريبًا."""
        if hasattr(self, "_save_timer") and self._save_timer:
            self._save_timer.start()

    def _get_progress_value(self, row: int, col: int) -> int:
        """يقرأ قيمة البروجريس من الخلية سواء Delegate(UserRole) أو QProgressBar."""
        # 1) Delegate/UserRole
        it = self.table.item(row, col)
        if it is not None:
            val = it.data(Qt.UserRole)
            if val is not None:
                try:
                    return int(val)
                except Exception:
                    pass
        # 2) Widget-based progress bar (إن وُجد)
        try:
            from PyQt5.QtWidgets import QProgressBar
            w = self.table.cellWidget(row, col)
            if isinstance(w, QProgressBar):
                return int(w.value())
        except Exception:
            pass
        # 3) نص محتمل
        try:
            return int(self.table.item(row, col).text().strip().strip('%'))
        except Exception:
            return 0

    def _set_progress_visual(self, row: int, col: int, value: int):
        """يضبط البروجريس فى الخلية بأى آلية متوفرة (Delegate أو Bar)."""
        value = max(0, min(100, int(value or 0)))
        # لو عندك دالة _set_progress_cell (Delegate)، استخدمها
        if hasattr(self, "_set_progress_cell"):
            self._set_progress_cell(row, col, value)
            return
        # وإلا استخدم الـQProgressBar القديم
        if hasattr(self, "_ensure_bar"):
            bar = self._ensure_bar(row, col)
            bar.setValue(value)
        else:
            it = self.table.item(row, col)
            if it is None:
                it = QTableWidgetItem("")
                self.table.setItem(row, col, it)
            it.setData(Qt.UserRole, value)
            model = self.table.model()
            idx = model.index(row, col)
            model.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.UserRole])

    def _row_snapshot(self, row: int, key_tuple=None) -> dict:
        """يمثّل صف الجدول كـ dict جاهز للحفظ."""
        H = self._col_map
        get = lambda name: self.table.item(row, H[name]).text() if name in H and self.table.item(row, H[name]) else ""
        prog = lambda name: self._get_progress_value(row, H[name]) if name in H else 0
        snap = {
            "section": get("Section"),
            "item": get("Item"),
            "stage": get("Stage"),
            "message": get("Message"),
            "speed": get("Speed"),
            "eta": get("ETA"),
            "progress": prog("Progress"),
            "hosts": {
                "rapidgator": prog("RG"),
                "ddownload": prog("DDL"),
                "katfile": prog("KF"),
                "nitroflare": prog("NF"),
                "rapidgator_bak": prog("RG_BAK"),
            },
            "key": list(key_tuple) if key_tuple else None,  # (section,item,op_type)
        }
        return snap

    def _table_snapshot(self) -> dict:
        """ياخد Snapshot لكل الصفوف الحالية keyed بنفس مفاتيحك الداخلية."""
        rows = []
        # لو عندك self._row_by_key: استفد منه عشان نحفظ الـop_type
        if hasattr(self, "_row_by_key") and isinstance(self._row_by_key, dict):
            # نقلب الماب: row -> key
            inv = {row: key for key, row in self._row_by_key.items()}
            for row in range(self.table.rowCount()):
                rows.append(self._row_snapshot(row, inv.get(row)))
        else:
            for row in range(self.table.rowCount()):
                rows.append(self._row_snapshot(row, None))
        return {"version": 1, "rows": rows}

    def _save_status_snapshot(self):
        """يحفظ Snapshot للـSTATUS فى ملف اليوزر."""
        mgr = self._user_mgr()
        if not mgr or not mgr.get_current_user():
            return  # مافيش يوزر مُسجّل
        data = self._table_snapshot()
        try:
            ok = mgr.save_user_data(self._persist_filename, data)
            if not ok:
                logging.warning("STATUS snapshot not saved (save_user_data returned False)")
        except Exception as e:
            logging.warning(f"STATUS snapshot save failed: {e}")

    # --- أضِف داخل class StatusWidget ---
    def _stage_from_text(self, text: str):
        t = (text or "").strip().lower()
        if t in ("finished", "complete", "completed", "done"):
            return OpStage.FINISHED
        if t in ("cancelled", "canceled"):
            return getattr(OpStage, "CANCELLED", OpStage.ERROR)
        if t in ("error", "failed", "failure"):
            return OpStage.ERROR
        return OpStage.RUNNING

    # --- عدّل الدالة بالكامل ---
    def _load_status_snapshot(self):
        try:
            from core.user_manager import get_user_manager
            um = get_user_manager()
            if not um or not um.get_current_user():
                return
            path = um.get_user_data_path(self._persist_filename)
            if not os.path.exists(path):
                return

            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            rows = data.get("rows", [])
            H = self._col_map  # خريطة الأعمدة بالاسم
            for row_data in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                for c in range(self.table.columnCount()):
                    self.table.setItem(row, c, QTableWidgetItem(""))

                # نصوص أساسية
                self.table.item(row, H["Section"]).setText(row_data.get("section", ""))
                self.table.item(row, H["Item"]).setText(row_data.get("item", ""))
                stage_text = row_data.get("stage", "")
                self.table.item(row, H["Stage"]).setText(stage_text)
                self.table.item(row, H["Message"]).setText(row_data.get("message", ""))
                self.table.item(row, H["Speed"]).setText(row_data.get("speed", "-"))
                self.table.item(row, H["ETA"]).setText(row_data.get("eta", "-"))

                # البروجريس العام: اعرض فقط لو > 0
                g = int(row_data.get("progress") or 0)
                if g > 0:
                    self._set_progress_visual(row, H["Progress"], g)
                else:
                    self._clear_progress_cell(row, H["Progress"])

                # بروجريس الهوستات: اعرض فقط لو > 0
                hosts = row_data.get("hosts", {}) or {}
                for name in ("RG", "DDL", "KF", "NF", "RG_BAK"):
                    col = H.get(name)
                    if col is None:
                        continue
                    v = int(hosts.get(name) or 0)
                    if v > 0:
                        self._set_progress_visual(row, col, v)
                    else:
                        self._clear_progress_cell(row, col)

                # لون الصف من الـStage
                stage = self._stage_from_text(stage_text)
                self._color_row(row, stage)
                model = self.table.model()
                tl = model.index(row, 0)
                br = model.index(row, self.table.columnCount() - 1)
                model.dataChanged.emit(tl, br, [Qt.BackgroundRole])

            self.table.resizeColumnsToContents()
            self.table.viewport().update()
        except Exception as e:
            log.error("Failed to load status snapshot", exc_info=True)

    def _normalize_host(self, host_raw: str) -> str:
        h = (host_raw or "").lower()
        if not h or h == "-":
            return ""
        if "rapidgator" in h and ("bak" in h or "backup" in h or "secondary" in h):
            return "rapidgator_bak"
        if h.startswith("rapidgator"):
            return "rapidgator"
        for base in ("ddownload", "katfile", "nitroflare"):
            if h.startswith(base):
                return base
        return h

    def _step_key(self, st: OperationStatus) -> tuple:
        """Unique key per step inside a thread."""
        if st.op_type == OpType.UPLOAD:
            return (st.op_type.name, self._normalize_host(st.host))
        return (st.op_type.name, None)

    def _record_step(self, st: OperationStatus) -> None:
        """Persist last known state for each step under the thread."""
        th_key = (st.section, st.item)
        steps = self._thread_steps.setdefault(th_key, {})
        skey = self._step_key(st)
        steps[skey] = {
            "progress": max(0, min(100, int(getattr(st, "progress", 0) or 0))),
            "finished": st.stage == OpStage.FINISHED,
            "error": st.stage == OpStage.ERROR,
            "host": self._normalize_host(st.host) if st.op_type == OpType.UPLOAD else "",
        }

    def _is_dark_palette(self, pal: QPalette) -> bool:
        c = pal.color(QPalette.Window)
        lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
        return lum < 0.5

    def _apply_readability_palette(self):
        """تحسين تباين صفوف الجدول (بدون ألوان ثابتة)."""
        pal = QPalette(self.table.palette())
        dark = self._is_dark_palette(pal)
        base = pal.color(QPalette.Base)
        # AlternateBase أوضح شوية من Base
        alt = base.lighter(112) if dark else base.darker(104)
        pal.setColor(QPalette.AlternateBase, alt)
        self.table.setPalette(pal)
        self.table.setAlternatingRowColors(True)


    def _ensure_item(self, row: int, col: int):
        it = self.table.item(row, col)
        if it is None:
            it = QTableWidgetItem("")
            # نخلى الستايل النصى شفاف لأن الـDelegate هيرسم
            it.setData(Qt.DisplayRole, "")
            self.table.setItem(row, col, it)
        return it

    def _set_progress_cell(self, row: int, col: int, value: int):
        """يحدّث خلية بروجريس (0..100) ويعمل dataChanged للـModel."""
        if col is None or col < 0:
            return
        value = 0 if value is None else int(max(0, min(100, value)))
        it = self._ensure_item(row, col)
        it.setData(Qt.UserRole, value)
        model = self.table.model()
        idx = model.index(row, col)
        # نبعث إشارة تغيير البيانات عشان الـDelegate يرسم فورًا
        model.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.UserRole])

    def _clear_progress_cell(self, row: int, col: int):
        """يمسح أى Progress من الخلية (فتطلع فاضية من غير 0%)."""
        if col is None or col < 0:
            return
        it = self._ensure_item(row, col)
        it.setData(Qt.UserRole, None)
        model = self.table.model()
        idx = model.index(row, col)
        model.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.UserRole])

    def handle_status(self, st: OperationStatus) -> None:
        # صف العملية: (section, item, op_type)
        key = (st.section, st.item, st.op_type.name)
        row = self._row_by_key.get(key)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col in range(self.table.columnCount()):
                self._ensure_item(row, col)
            self._row_by_key[key] = row

        # نصوص الأعمدة الأساسية
        txts = [
            st.section or "",
            st.item or "",
            (getattr(st.stage, "name", str(st.stage)) or "").title(),
            st.message or "",
            self._fmt_speed(getattr(st, "speed", None)),
            self._fmt_eta(getattr(st, "eta", None)),
        ]
        for c, v in enumerate(txts):
            self._ensure_item(row, c).setText(str(v))

        # سجّل الخطوة (نحتاجه لحساب متوسط رفع متعدد الهوستات)
        self._record_step(st)

        # ✅ Progress العمومى:
        if hasattr(self, "_progress_col") and self._progress_col is not None:
            if st.op_type == OpType.UPLOAD:
                # متوسط كل هوستات الرفع تحت نفس الثريد
                steps = self._thread_steps.get((st.section, st.item), {})
                ups = [s["progress"] for (op_name, _h), s in steps.items() if op_name == "UPLOAD"]
                avg_up = int(round(sum(ups) / len(ups))) if ups else int(getattr(st, "progress", 0) or 0)
                self._set_progress_cell(row, self._progress_col, avg_up)
            else:
                # Download/Extract/Compress/... استخدم قيمة العملية نفسها
                try:
                    self._set_progress_cell(row, self._progress_col, int(getattr(st, "progress", 0) or 0))
                except Exception:
                    self._set_progress_cell(row, self._progress_col, 0)

        # ✅ لو Upload: حدِّث عمود الهوست الخاص بيه، غير كده سيب أعمدة الهوست فاضية
        if st.op_type == OpType.UPLOAD:
            host_raw = (getattr(st, "host", "") or "").lower()
            if "rapidgator" in host_raw and any(x in host_raw for x in ("bak", "backup", "secondary")):
                host_name = "RG_BAK"
            elif host_raw.startswith("rapidgator"):
                host_name = "RG"
            elif host_raw.startswith("ddownload"):
                host_name = "DDL"
            elif host_raw.startswith("katfile"):
                host_name = "KF"
            elif host_raw.startswith("nitroflare"):
                host_name = "NF"
            else:
                host_name = ""

            if host_name:
                try:
                    host_col = [self.table.horizontalHeaderItem(i).text() for i in
                                range(self.table.columnCount())].index(host_name)
                except ValueError:
                    host_col = None

                if host_col is not None:
                    try:
                        self._set_progress_cell(row, host_col, int(getattr(st, "progress", 0) or 0))
                    except Exception:
                        self._set_progress_cell(row, host_col, 0)

        # تلوين الصف حسب المرحلة
        stage = getattr(st, "stage", None)
        self._color_row(row, stage, st.op_type)
        model = self.table.model()
        tl = model.index(row, 0)
        br = model.index(row, self.table.columnCount() - 1)
        model.dataChanged.emit(tl, br, [Qt.BackgroundRole])

        self._schedule_status_save()

    def connect_worker(self, worker: QObject) -> None:
        # لو الووركر بيدعم cancel_event، خلّيه ياخده (اختيارى)
        try:
            if hasattr(worker, "progress_update"):
                worker.progress_update.connect(self.handle_status, Qt.QueuedConnection)
            elif hasattr(worker, "file_progress_update"):
                def _adapter(link_id, pct, stage, cur, tot, name, speed, eta):
                    status = OperationStatus(
                        section="Downloads",
                        item=name,
                        op_type=OpType.DOWNLOAD,
                        stage=OpStage.RUNNING if pct < 100 else OpStage.FINISHED,
                        message=stage,
                        progress=pct,
                        speed=speed,
                        eta=eta,
                        host="",
                    )
                    self.handle_status(status)
                worker.file_progress_update.connect(_adapter, Qt.QueuedConnection)
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

