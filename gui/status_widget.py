
import logging
import os
import threading
import time
from PyQt5.QtCore import QTimer, Qt, QSize, QEvent, QObject, pyqtSignal, QItemSelectionModel, pyqtSlot
from PyQt5.QtGui import QColor, QPalette, QBrush, QKeySequence

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
    QLineEdit,
    QComboBox,
    QHBoxLayout,
    QShortcut,
    QMenu,
)
from core.user_manager import get_user_manager
from integrations.jd_client import hard_cancel
from models.operation_status import OperationStatus, OpStage, OpType
from utils.utils import _normalize_links

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
DEBUG_STATUS_CONTEXT = True


def _dbg(msg: str):
    if DEBUG_STATUS_CONTEXT:
        log.debug(msg)

class StatusWidget(QWidget):
    """
    بانل الحالة:
      - بتعرض العمليات
      - زرار Cancel:
          * بيبعت إشارة إلغاء للـ workers (منطقك الحالى)
          * وبشكل موازى بيعمل Stop + Clear كامل فى JDownloader عشان ما يكمّلش تحميل
    """
    pauseRequested = pyqtSignal(list)
    resumeRequested = pyqtSignal(list)
    cancelRequested = pyqtSignal(list)
    retryRequested = pyqtSignal(list)
    openInJDRequested = pyqtSignal(list)
    copyJDLinkRequested = pyqtSignal(list)
    resumePendingRequested = pyqtSignal(list)
    reuploadAllRequested = pyqtSignal(list)
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        # Filters row -------------------------------------------------
        filter_layout = QHBoxLayout()
        self.search_edit = QLineEdit(self)
        self.section_cb = QComboBox(self)
        self.stage_cb = QComboBox(self)
        self.host_cb = QComboBox(self)
        # ✅ ثبّت قيم افتراضية واضحة للفلاتر
        self.section_cb.addItem("All")
        self.stage_cb.addItems(["All", "Running", "Finished", "Error", "Cancelled"])
        self.host_cb.addItems(["All", "RG", "DDL", "KF", "NF", "RG_BAK"])

        self.btn_clear_finished = QPushButton("Clear Finished", self)
        self.btn_clear_errors = QPushButton("Clear Errors", self)
        self.btn_clear_selected = QPushButton("Clear Selected", self)

        filter_layout.addWidget(self.search_edit)
        filter_layout.addWidget(self.section_cb)
        filter_layout.addWidget(self.stage_cb)
        filter_layout.addWidget(self.host_cb)
        filter_layout.addWidget(self.btn_clear_finished)
        filter_layout.addWidget(self.btn_clear_errors)
        filter_layout.addWidget(self.btn_clear_selected)
        layout.addLayout(filter_layout)

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
        self.table.setSortingEnabled(True)

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

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_ctx_menu, Qt.QueuedConnection)
        # Connect filter widgets
        self.search_edit.textChanged.connect(self.apply_filter, Qt.QueuedConnection)
        self.section_cb.currentIndexChanged.connect(self.apply_filter, Qt.QueuedConnection)
        self.stage_cb.currentIndexChanged.connect(self.apply_filter, Qt.QueuedConnection)
        self.host_cb.currentIndexChanged.connect(self.apply_filter, Qt.QueuedConnection)

        self.btn_clear_finished.clicked.connect(
            lambda: self.clear_finished(ignore_running=not (QApplication.keyboardModifiers() & Qt.AltModifier)),
            Qt.QueuedConnection,
        )
        self.btn_clear_errors.clicked.connect(
            lambda: self.clear_errors(ignore_running=not (QApplication.keyboardModifiers() & Qt.AltModifier)),
            Qt.QueuedConnection,
        )
        self.btn_clear_selected.clicked.connect(
            lambda: self.clear_selected(ignore_running=not (QApplication.keyboardModifiers() & Qt.AltModifier)),
            Qt.QueuedConnection,
        )

        # Shortcuts
        sc_focus = QShortcut(QKeySequence("Ctrl+F"), self)
        sc_focus.activated.connect(self.search_edit.setFocus)
        sc_clear = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc_clear.activated.connect(self._clear_filters)
        sc_clear_finished = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        sc_clear_finished.activated.connect(
            lambda: self.clear_finished(ignore_running=not (QApplication.keyboardModifiers() & Qt.AltModifier))
        )
        sc_clear_errors = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        sc_clear_errors.activated.connect(
            lambda: self.clear_errors(ignore_running=not (QApplication.keyboardModifiers() & Qt.AltModifier))
        )
        sc_clear_selected = QShortcut(QKeySequence(Qt.Key_Delete), self.table)
        sc_clear_selected.activated.connect(
            lambda: self.clear_selected(ignore_running=not (QApplication.keyboardModifiers() & Qt.AltModifier))
        )
        sc_pause = QShortcut(QKeySequence("Ctrl+Alt+P"), self)
        sc_pause.activated.connect(lambda: self._emit_selection("pause"))
        sc_resume = QShortcut(QKeySequence("Ctrl+Alt+R"), self)
        sc_resume.activated.connect(lambda: self._emit_selection("resume"))
        sc_cancel = QShortcut(QKeySequence("Ctrl+Alt+C"), self)
        sc_cancel.activated.connect(lambda: self._emit_selection("cancel"))
        sc_retry = QShortcut(QKeySequence("Ctrl+Alt+Y"), self)
        sc_retry.activated.connect(lambda: self._emit_selection("retry"))
        sc_open = QShortcut(QKeySequence("Ctrl+Alt+O"), self)
        sc_open.activated.connect(lambda: self._emit_selection("open"))
        sc_copy = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        sc_copy.activated.connect(lambda: self._emit_selection("copy"))
        sc_diag = QShortcut(QKeySequence(Qt.Key_F12), self)
        sc_diag.activated.connect(self.diagnose_context_wiring)
        self._sc_focus = sc_focus
        self._sc_clear = sc_clear
        self._sc_clear_finished = sc_clear_finished
        self._sc_clear_errors = sc_clear_errors
        self._sc_clear_selected = sc_clear_selected
        self._dbg_shortcuts = [
            sc_pause,
            sc_resume,
            sc_cancel,
            sc_retry,
            sc_open,
            sc_copy,
            sc_diag,
        ]
        self.cancel_event = threading.Event()
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        layout.addWidget(self.btn_cancel)

        self._row_by_key = {}
        self._row_by_tid: dict[str, int] = {}
        self._row_last_stage = {}
        self._jd_links = {}
        self._upload_meta = {}
        self._thread_steps = {}  # 🆕 تجميع خطوات كل Thread => {(section,item): {(op,host)->state}}
        self._bar_at = {}
        self._pending_by_key = {}
        self._last_progress = {}
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(150)
        self._flush_timer.timeout.connect(self._flush_status, Qt.QueuedConnection)

        self._apply_readability_palette()
        self._row_brushes = self._status_brushes(self.table.palette())
        mgr = self._user_mgr()
        if mgr:
            try:
                mgr.register_login_listener(lambda *_: self._load_status_snapshot())
                if mgr.get_current_user():
                    self._load_status_snapshot()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _clear_filters(self) -> None:
        """Clear all filter widgets and reapply."""
        self.search_edit.setText("")
        self.section_cb.setCurrentIndex(0)
        self.stage_cb.setCurrentIndex(0)
        self.host_cb.setCurrentIndex(0)
        self.apply_filter()

    def _filter_active(self) -> bool:
        """Return True if any filter is active."""
        if self.search_edit.text().strip():
            return True
        return not (
            self.section_cb.currentText() == "All"
            and self.stage_cb.currentText() == "All"
            and self.host_cb.currentText() == "All"
        )

    def _apply_filter_if_active(self) -> None:
        if not self._filter_active():
            return
        self.apply_filter()
        if self._visible_rows_count() == 0:
            self._reset_filters_to_all()
    def apply_filter(self) -> None:
        q = self.search_edit.text().strip().lower()
        section = self.section_cb.currentText()
        stage_txt = self.stage_cb.currentText()
        host = self.host_cb.currentText()

        section = "" if section == "All" else section
        host = "" if host == "All" else host
        stage_filter = None
        if stage_txt != "All":
            stage_filter = self._stage_from_text(stage_txt)

        H = self._col_map
        # 🆕 اعكس خريطة الصفوف -> المفاتيح لتحديد نوع العملية
        inv = {row: key for key, row in self._row_by_key.items()}

        for row in range(self.table.rowCount()):
            visible = True
            if q:
                found = False
                for col in range(self.table.columnCount()):
                    it = self.table.item(row, col)
                    if it and q in it.text().lower():
                        found = True
                        break
                if not found:
                    visible = False

            if visible and section:
                col = H.get("Section")
                it = self.table.item(row, col) if col is not None else None
                if not it or it.text() != section:
                    visible = False

            if visible and stage_filter is not None:
                col = H.get("Stage")
                it = self.table.item(row, col) if col is not None else None
                st = self._stage_from_text(it.text() if it else "")
                if st != stage_filter:
                    visible = False

            # 🆕 فلتر الهوست يطبّق فقط على صفوف UPLOAD
            if visible and host:
                k = inv.get(row)
                if k and len(k) == 3 and k[2] == "UPLOAD":
                    col = H.get(host)
                    if col is None or self._get_progress_value(row, col) <= 0:
                        visible = False
                else:
                    # غير الرفع: تجاهل فلتر الهوست
                    pass

            self.table.setRowHidden(row, not visible)

    # ------------------------------------------------------------------
    def clear_finished(self, ignore_running: bool = True) -> None:
        """Remove all rows with stage FINISHED."""
        stage_col = self._col_map.get("Stage")
        if stage_col is None:
            return
        rows = []
        for row in range(self.table.rowCount()):
            it = self.table.item(row, stage_col)
            stage = self._stage_from_text(it.text() if it else "")
            if stage == OpStage.RUNNING and ignore_running:
                continue
            if stage == OpStage.FINISHED:
                rows.append(row)
        self._remove_rows(rows)

    def clear_errors(self, ignore_running: bool = True) -> None:
        """Remove all rows with stage ERROR."""
        stage_col = self._col_map.get("Stage")
        if stage_col is None:
            return
        rows = []
        for row in range(self.table.rowCount()):
            it = self.table.item(row, stage_col)
            stage = self._stage_from_text(it.text() if it else "")
            if stage == OpStage.RUNNING and ignore_running:
                continue
            if stage == OpStage.ERROR:
                rows.append(row)
        self._remove_rows(rows)

    def clear_selected(self, ignore_running: bool = True) -> None:
        """Remove currently selected rows."""
        sel = self.table.selectionModel()
        if sel is None:
            return
        stage_col = self._col_map.get("Stage")
        rows = []
        for idx in sel.selectedRows():
            row = idx.row()
            if stage_col is not None:
                it = self.table.item(row, stage_col)
                stage = self._stage_from_text(it.text() if it else "")
                if stage == OpStage.RUNNING and ignore_running:
                    continue
            rows.append(row)
        self._remove_rows(rows)

    def _row_section_item(self, row: int) -> tuple[str, str]:
        """Return (section, item) text for row."""
        H = self._col_map
        sec_col = H.get("Section")
        item_col = H.get("Item")
        sec = self.table.item(row, sec_col).text() if sec_col is not None and self.table.item(row, sec_col) else ""
        item = self.table.item(row, item_col).text() if item_col is not None and self.table.item(row, item_col) else ""
        return sec, item

    def _select_row_after_removal(self, start: int) -> None:
        if self.table.rowCount() == 0:
            return
        start = min(start, self.table.rowCount() - 1)
        for r in range(start, self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.selectRow(r)
                self.table.setCurrentCell(r, 0)
                return
        for r in range(start - 1, -1, -1):
            if not self.table.isRowHidden(r):
                self.table.selectRow(r)
                self.table.setCurrentCell(r, 0)
                return
        self.table.clearSelection()

    def _remove_rows(self, rows: list[int]) -> None:
        rows = sorted(set(rows))
        if not rows:
            return
        first = rows[0]
        for row in reversed(rows):
            sec, item = self._row_section_item(row)
            self.table.removeRow(row)
            for key, r in list(self._row_by_key.items()):
                if r == row:
                    del self._row_by_key[key]
                elif r > row:
                    self._row_by_key[key] = r - 1
            for tid, r in list(self._row_by_tid.items()):
                if r == row:
                    del self._row_by_tid[tid]
                elif r > row:
                    self._row_by_tid[tid] = r - 1
            for r in list(self._row_last_stage.keys()):
                if r == row:
                    del self._row_last_stage[r]
                elif r > row:
                    self._row_last_stage[r - 1] = self._row_last_stage.pop(r)
            if sec or item:
                self._thread_steps.pop((sec, item), None)
        self.table.model().layoutChanged.emit()
        self._schedule_status_save()
        self._apply_filter_if_active()
        self._select_row_after_removal(first)

    def on_ctx_menu(self, pos):
        sel = self.table.selectionModel()
        if sel is None:
            return
        inv = {row: key for key, row in self._row_by_key.items()}
        keys = [inv.get(idx.row()) for idx in sel.selectedRows()]
        keys = [k for k in keys if k]
        if not keys:
            return
        types = {k[2] for k in keys}
        _dbg(f"build ctx menu keys={keys} types={types}")
        menu = QMenu(self)
        acts = {}
        upload_actions = []
        running_actions = []
        if "UPLOAD" in types:
            a = menu.addAction("Pause")
            acts[a] = "pause"
            upload_actions.append(a)
            a = menu.addAction("Resume")
            acts[a] = "resume"
            upload_actions.append(a)
            a = menu.addAction("Cancel")
            acts[a] = "cancel"
            upload_actions.append(a)
            a = menu.addAction("Retry")
            acts[a] = "retry"
            upload_actions.append(a)
            a = menu.addAction("Resume Pending")
            acts[a] = "resume_pending"
            upload_actions.append(a)
            running_actions.append(a)
            a = menu.addAction("Re-upload All")
            acts[a] = "reupload_all"
            upload_actions.append(a)
            running_actions.append(a)
            # determine if any selected row is running
        running = False
        stage_col = self._col_map.get("Stage")
        if stage_col is not None:
            for idx in sel.selectedRows():
                it = self.table.item(idx.row(), stage_col)
                stg = self._stage_from_text(it.text() if it else "")
                if stg == OpStage.RUNNING:
                    running = True
                    break
        if "DOWNLOAD" in types:
            if upload_actions:
                menu.addSeparator()
            a = menu.addAction("Open in JD")
            a.setToolTip("Open link in JDownloader")
            acts[a] = "open"
            a = menu.addAction("Copy JD Link")
            a.setToolTip("Copy JD link to clipboard")
            acts[a] = "copy"
        if len(types) > 1:
            for a in upload_actions:
                a.setEnabled(False)
        if running:
            for a in running_actions:
                a.setEnabled(False)
        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if not action or action not in acts:
            return
        which = acts[action]
        _dbg(f"ctx action {which} keys={keys}")
        if which == "pause":
            self.pauseRequested.emit(keys)
        elif which == "resume":
            self.resumeRequested.emit(keys)
        elif which == "cancel":
            self.cancelRequested.emit(keys)
        elif which == "retry":
            self.retryRequested.emit(keys)
        elif which == "resume_pending":
            self.resumePendingRequested.emit(keys)
        elif which == "reupload_all":
            self.reuploadAllRequested.emit(keys)
        elif which == "open":
            self.openInJDRequested.emit(keys)
        elif which == "copy":
            self.copyJDLinkRequested.emit(keys)
        self.apply_filter()
        self._schedule_status_save()

    def _emit_selection(self, which: str):
        sel = self.table.selectionModel()
        if sel is None:
            log.warning("No selection model for %s", which)
            return
        inv = {row: key for key, row in self._row_by_key.items()}
        keys = [inv.get(idx.row()) for idx in sel.selectedRows()]
        keys = [k for k in keys if k]
        if not keys:
            log.warning("No selection for %s", which)
            return
        _dbg(f"shortcut {which} keys={keys}")
        if which == "pause":
            self.pauseRequested.emit(keys)
        elif which == "resume":
            self.resumeRequested.emit(keys)
        elif which == "cancel":
            self.cancelRequested.emit(keys)
        elif which == "retry":
            self.retryRequested.emit(keys)
        elif which == "resume_pending":
            self.resumePendingRequested.emit(keys)
        elif which == "reupload_all":
            self.reuploadAllRequested.emit(keys)
        elif which == "open":
            self.openInJDRequested.emit(keys)
        elif which == "copy":
            self.copyJDLinkRequested.emit(keys)
        self.apply_filter()
        self._schedule_status_save()

    def diagnose_context_wiring(self):
        _dbg("diagnose_context_wiring start")
        up_key = next((k for k in self._row_by_key if k[2] == "UPLOAD"), None)
        if up_key:
            self.table.selectRow(self._row_by_key[up_key])
            self._emit_selection("pause")
            self._emit_selection("resume")
        else:
            log.warning("No UPLOAD row for diagnose_context_wiring")
        down_key = next((k for k in self._row_by_key if k[2] == "DOWNLOAD"), None)
        if down_key:
            self.table.selectRow(self._row_by_key[down_key])
            self._emit_selection("open")
            self._emit_selection("copy")
        else:
            log.warning("No DOWNLOAD row for diagnose_context_wiring")
        _dbg("diagnose_context_wiring done")

    def get_jd_link(self, key):
        return self._jd_links.get(tuple(key))

    def set_jd_link(self, key, link: str) -> None:
        self._jd_links[tuple(key)] = link or ""
        self._schedule_status_save()
    def update_upload_meta(self, key, meta: dict) -> None:
        key = tuple(key)
        cur = self._upload_meta.setdefault(key, {})
        if meta:
            cur.update(meta)
        self._schedule_status_save()

    # ------------------------------------------------------------------
    def populate_links_by_tid(self, tid: str, links: dict, keeplinks: str, meta: dict) -> None:
        """Populate host and Keeplinks columns for a given thread.

        This helper locates the row associated with ``tid`` and updates
        the Rapidgator (RG), rapidgator backup (RG_BAK), ddownload (DDL),
        katfile (KF) and nitroflare (NF) columns based on the provided
        ``links`` mapping.  It also writes the protected URL into a
        Keeplinks/Links column when present.  Nested link structures and
        boolean placeholders are normalised to lists of strings.  Only
        modified cells are updated, and a snapshot save is scheduled
        afterwards.  Upload metadata is persisted when provided.

        Args:
            tid: The thread identifier mapping to ``_row_by_tid``.  If
                missing, a fallback lookup by section and item will be
                attempted (splitting ``tid`` on the first ``:``).
            links: Mapping of host names to one or more URLs.  Supported
                keys include ``rapidgator``, ``rapidgator_bak``,
                ``ddownload``, ``katfile`` and ``nitroflare``.  Values may
                be strings, lists, dicts with ``urls``/``url`` keys, or
                nested combinations thereof.  Any boolean values are
                ignored.
            keeplinks: A single protected URL to be written into the
                Keeplinks column (or ``Links`` column if Keeplinks is not
                defined).
            meta: Optional metadata associated with the upload; if
                provided, it is merged into the internal upload_meta
                mapping for the matching key (section,item,op_type).
        """
        # Resolve the row by thread identifier
        row = self._row_by_tid.get(tid)
        if row is None:
            # Fallback: split tid into section and item.  The tid may be
            # formatted as "Section:Item" when thread_id is absent.
            sec = None
            itm = None
            if isinstance(tid, str) and ":" in tid:
                parts = tid.split(":", 1)
                sec = parts[0]
                itm = parts[1]
            # Find matching row by section and item (any op_type)
            if sec is not None and itm is not None:
                for key, r in self._row_by_key.items():
                    if key[0] == sec and key[1] == itm:
                        row = r
                        break
        # If still no row, nothing to populate
        if row is None:
            return

        def _flatten(value) -> list[str]:
            """Flatten arbitrary link structures into a list of strings.

            Accepts strings, lists, tuples, sets, and dicts with ``urls`` or
            ``url`` keys.  Ignores booleans and None.  Recurses into nested
            containers.
            """
            results: list[str] = []
            def _inner(v):
                if v is None:
                    return
                # Boolean flags are not links
                if isinstance(v, bool):
                    return
                # Strings become single-element lists
                if isinstance(v, str):
                    if v:
                        results.append(v)
                    return
                # Dictionaries may wrap URLs under specific keys
                if isinstance(v, dict):
                    # Common keys: 'urls' (list) or 'url' (single)
                    if 'urls' in v:
                        _inner(v['urls'])
                        return
                    if 'url' in v:
                        _inner(v['url'])
                        return
                    # Otherwise, recurse into all values
                    for vv in v.values():
                        _inner(vv)
                    return
                # Iterable containers (lists, tuples, sets)
                if isinstance(v, (list, tuple, set)):
                    for elem in v:
                        _inner(elem)
                    return
                # Fallback: convert to string
                results.append(str(v))
            _inner(value)
            return results

        model = self.table.model()
        changed = False
        # Collect values for logging for RG and RG_BAK
        log_vals: dict[str, str] = {}
        # Iterate through hosts in the fixed order defined by HOST_COLS
        for host, header in HOST_COLS.items():
            col = self._host_col_index.get(host)
            if col is None:
                continue
            raw_val = None
            if isinstance(links, dict):
                raw_val = links.get(host)
            flattened = _flatten(raw_val) if raw_val else []
            new_text = "\n".join(flattened) if flattened else ""
            it = self.table.item(row, col)
            old_text = it.text() if it else ""
            if old_text != new_text:
                self._ensure_item(row, col).setText(new_text)
                # Set progress to 100% when a link is present, else clear
                if flattened:
                    self._set_progress_cell(row, col, 100)
                else:
                    self._clear_progress_cell(row, col)
                idx = model.index(row, col)
                model.dataChanged.emit(idx, idx, [Qt.DisplayRole])
                changed = True
            # Record values for RG and RG_BAK for debugging
            if header in ("RG", "RG_BAK"):
                log_vals[header] = new_text

        # Handle Keeplinks/Links column
        if keeplinks:
            # Prefer a dedicated 'Keeplinks' column if present; otherwise fall back
            # to a 'Links' column.  If neither exist, skip quietly.
            updated_kl = False
            for col_name in ("Keeplinks", "Links"):
                kl_col = self._col_map.get(col_name)
                if kl_col is None:
                    continue
                it = self.table.item(row, kl_col)
                old_txt = it.text() if it else ""
                if old_txt != keeplinks:
                    self._ensure_item(row, kl_col).setText(keeplinks)
                    idx = model.index(row, kl_col)
                    model.dataChanged.emit(idx, idx, [Qt.DisplayRole])
                    changed = True
                updated_kl = True
                break
            # For logging, treat absence of column as still logged
            log_vals.setdefault("KEEP", keeplinks)
        else:
            # Still include empty keeplinks in log
            log_vals.setdefault("KEEP", "")

        # Emit a debug/info log summarising the changes.  Use .info so it's always visible.
        try:
            rg_val = log_vals.get("RG", "")
            rg_bak_val = log_vals.get("RG_BAK", "")
            keep_val = log_vals.get("KEEP", "")
            log.info("POPULATE-LINKS tid=%s row=%s set RG=%s, RG_BAK=%s, KEEP=%s", tid, row, rg_val, rg_bak_val, keep_val)
        except Exception:
            pass

        # Persist upload metadata, if provided and there is a matching key
        if meta:
            # Identify the key tuple (section,item,op_type) for this row
            key_tuple = None
            for k, r in self._row_by_key.items():
                if r == row:
                    key_tuple = k
                    break
            if key_tuple:
                try:
                    self.update_upload_meta(key_tuple, meta)
                except Exception:
                    pass

        # Schedule a snapshot save if anything changed or metadata was updated
        if changed or meta:
            try:
                self._schedule_status_save()
            except Exception:
                pass

    def get_upload_meta(self, key) -> dict:
        return dict(self._upload_meta.get(tuple(key), {}))
    def _populate_sections(self) -> None:
        """Ensure section combo box contains existing sections."""
        col = self._col_map.get("Section")
        if col is None:
            return
        seen = {self.section_cb.itemText(i) for i in range(self.section_cb.count())}
        for row in range(self.table.rowCount()):
            it = self.table.item(row, col)
            txt = it.text() if it else ""
            if txt and txt not in seen:
                self.section_cb.addItem(txt)
                seen.add(txt)

    def _ensure_section_option(self, section: str) -> None:
        if not section:
            return
        if self.section_cb.findText(section) < 0:
            self.section_cb.addItem(section)
    def reload_from_disk(self, *_):
        """Reload the status snapshot from disk for the current user."""
        self._load_status_snapshot()
        self.table.resizeColumnsToContents()
        self.table.viewport().update()
        types = [k[2] for k in self._row_by_key]
        up = types.count("UPLOAD")
        down = types.count("DOWNLOAD")
        _dbg(
            f"reload_from_disk rows={self.table.rowCount()} map={len(self._row_by_key)} uploads={up} downloads={down}"
        )
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
    def _visible_rows_count(self) -> int:
        c = 0
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                c += 1
        return c

    def _reset_filters_to_all(self):
        # ما نخبطش الإشارات
        for cb, default in ((self.section_cb, "All"), (self.stage_cb, "All"), (self.host_cb, "All")):
            if cb:
                idx = cb.findText(default)
                if idx < 0:
                    cb.addItem(default)
                    idx = cb.findText(default)
                cb.setCurrentIndex(idx)
        if hasattr(self, "search_edit") and self.search_edit:
            self.search_edit.setText("")
        # أعد تطبيق الفلتر
        self.apply_filter()

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
        dark = self._is_dark_palette(pal)

        hl = pal.color(QPalette.Highlight)
        h, s, l, _ = hl.getHsl()

        def from_hue(hue: int, alpha: int) -> QBrush:
            c = QColor()
            c.setHsl(hue, s, l)
            c = c.lighter(130) if dark else c.darker(110)
            c.setAlpha(alpha)
            return QBrush(c)

        brushes[OpStage.FINISHED] = from_hue(120, 175)  # اخضر
        brushes[OpStage.ERROR] = from_hue(0, 165)       # احمر

        # دعم حالة الإلغاء حتى لو الـEnum ما فيهاش CANCELLED
        cancel_brush = from_hue(50, 160)  # اصفر
        brushes["cancelled"] = cancel_brush
        cancelled = getattr(OpStage, "CANCELLED", None)
        if cancelled is not None:
            brushes[cancelled] = cancel_brush

        run_col = pal.color(QPalette.AlternateBase)
        run_col = run_col.lighter(110) if dark else run_col.darker(110)
        run_col.setAlpha(150)
        brushes[OpStage.RUNNING] = QBrush(run_col)

        return brushes

    def _color_row(self, row: int, stage: OpStage, op_type: OpType | None = None) -> None:
        pal = self.table.palette()
        base_role = QPalette.Base if row % 2 == 0 else QPalette.AlternateBase
        base = pal.color(base_role)
        overlay = self._row_brushes.get(stage)
        if overlay is None:
            overlay = self._row_brushes.get(getattr(stage, "name", str(stage)).lower())
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
            "jd_link": self._jd_links.get(tuple(key_tuple)) if key_tuple else "",
        }
        tid = ""
        for t, r in self._row_by_tid.items():
            if r == row:
                tid = t
                break
        if tid:
            snap["thread_id"] = tid
        meta = self._upload_meta.get(tuple(key_tuple)) if key_tuple else None
        if meta:
            meta = dict(meta)
            for k in ("folder", "folder_path"):
                if k in meta:
                    meta[k] = os.path.basename(meta[k])

            snap["upload_meta"] = meta
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
        filters = {
            "q": self.search_edit.text(),
            "section": self.section_cb.currentText(),
            "stage": self.stage_cb.currentText(),
            "host": self.host_cb.currentText(),
        }
        header = self.table.horizontalHeader()
        sort_state = {
            "column": int(header.sortIndicatorSection()),
            "order": int(header.sortIndicatorOrder()),
        }
        col_widths = [int(header.sectionSize(i)) for i in range(self.table.columnCount())]
        scroll = {
            "h": int(self.table.horizontalScrollBar().value()),
            "v": int(self.table.verticalScrollBar().value()),
        }
        sel_keys = []
        sel = self.table.selectionModel()
        if sel:
            inv = {row: key for key, row in self._row_by_key.items()}
            for idx in sel.selectedRows():
                key = inv.get(idx.row())
                if key:
                    sel_keys.append(list(key))
        return {
            "version": 2,
            "rows": rows,
            "filters": filters,
            "sort": sort_state,
            "columns": col_widths,
            "scroll": scroll,
            "selection": sel_keys,
        }

    def _save_status_snapshot(self):
        """يحفظ Snapshot للـSTATUS فى ملف اليوزر (حفظ ذرّى UTF-8)."""
        mgr = self._user_mgr()
        if not mgr or not mgr.get_current_user():
            return
        data = self._table_snapshot()
        try:
            ok = mgr.save_user_data(self._persist_filename, data)  # ← الفعلية
            if ok:
                log.debug("💾 Saved status snapshot (%d rows)", len(data.get("rows", [])))
            else:
                log.warning("STATUS snapshot not saved (save_user_data returned False)")
        except Exception:
            log.error("STATUS snapshot save failed", exc_info=True)

    # --- أضِف داخل class StatusWidget ---
    def _stage_from_text(self, text: str):
        t = (text or "").strip().lower()
        if t in ("finished", "complete", "completed", "done"):
            return OpStage.FINISHED
        if t in ("cancelled", "canceled"):
            cancelled = getattr(OpStage, "CANCELLED", None)
            return cancelled if cancelled is not None else "cancelled"
        if t in ("error", "failed", "failure"):
            return OpStage.ERROR
        return OpStage.RUNNING

    # --- عدّل الدالة بالكامل ---
    def _load_status_snapshot(self):
        """يسترجع Snapshot بشكل محكم مع حجب إشارات الفلاتر وإعادة بناء الخرائط ثم إعادة الفرز والاختيار والتمرير."""
        try:
            mgr = self._user_mgr()
            if not mgr or not mgr.get_current_user():
                return
            data = mgr.load_user_data(self._persist_filename) or {}

            widgets = [self.search_edit, self.section_cb, self.stage_cb, self.host_cb]
            prev_blocks = [w.blockSignals(True) for w in widgets]
            sorting = self.table.isSortingEnabled()
            self.table.setSortingEnabled(False)

            # تفريغ الجداول/الخرائط
            self.table.setRowCount(0)
            self._row_by_key.clear()
            self._row_by_tid.clear()
            self._jd_links.clear()
            self._upload_meta.clear()
            self._thread_steps.clear()
            self._bar_at.clear()

            rows = data.get("rows", []) or []
            filters = data.get("filters", {}) or {}
            sort_state = data.get("sort", {}) or {}
            col_widths = data.get("columns", []) or []
            scroll = data.get("scroll", {}) or {}
            sel_keys = [tuple(k) for k in data.get("selection", []) or []]

            H = self._col_map
            # اضمن قيم الفلاتر الافتراضية
            if self.section_cb.findText("All") < 0:
                self.section_cb.addItem("All")
            if self.stage_cb.count() == 0:
                self.stage_cb.addItems(["All", "Running", "Finished", "Error", "Cancelled"])
            if self.host_cb.count() == 0:
                self.host_cb.addItems(["All", "RG", "DDL", "KF", "NF", "RG_BAK"])

            # بناء الصفوف
            for rdata in rows:
                r = self.table.rowCount()
                self.table.insertRow(r)
                for c in range(self.table.columnCount()):
                    self._ensure_item(r, c)

                self.table.item(r, H["Section"]).setText(rdata.get("section", ""))
                self.table.item(r, H["Item"]).setText(rdata.get("item", ""))
                stage_text = rdata.get("stage", "")
                self.table.item(r, H["Stage"]).setText(stage_text)
                self.table.item(r, H["Message"]).setText(rdata.get("message", ""))
                self.table.item(r, H["Speed"]).setText(rdata.get("speed", "-"))
                self.table.item(r, H["ETA"]).setText(rdata.get("eta", "-"))

                # Progress العام
                g = int(rdata.get("progress") or 0)
                if g > 0:
                    self._set_progress_cell(r, H.get("Progress"), g)
                else:
                    self._clear_progress_cell(r, H.get("Progress"))

                # Progress الهوستات
                hosts = rdata.get("hosts", {}) or {}
                for host, header in HOST_COLS.items():
                    col = H.get(header)
                    if col is None:
                        continue
                    v = int(hosts.get(host) or 0)
                    if v > 0:
                        self._set_progress_cell(r, col, v)
                    else:
                        self._clear_progress_cell(r, col)

                # مفاتيح الخرائط/الروابط/الميتا
                key_list = rdata.get("key")
                if key_list and len(key_list) == 3:
                    key = tuple(key_list)
                    self._row_by_key[key] = r
                    link = rdata.get("jd_link") or ""
                    if link:
                        self._jd_links[key] = link
                    meta = rdata.get("upload_meta") or {}
                    if meta:
                        self._upload_meta[key] = dict(meta)
                tid = rdata.get("thread_id")
                if tid:
                    self._row_by_tid[tid] = r
                # تلوين الصف
                stage = self._stage_from_text(stage_text)
                self._color_row(r, stage)

            # إشعار إعادة رسم شامل (خلفية + نصوص)
            if self.table.rowCount():
                model = self.table.model()
                tl = model.index(0, 0)
                br = model.index(self.table.rowCount() - 1, self.table.columnCount() - 1)
                model.dataChanged.emit(tl, br, [Qt.BackgroundRole, Qt.DisplayRole])

            # أحجام الأعمدة
            header = self.table.horizontalHeader()
            for i, w in enumerate(col_widths):
                try:
                    header.resizeSection(i, int(w))
                except Exception:
                    pass

            # ضمّن كل الأقسام فى الكومبو
            self._populate_sections()

            # استعادة الفلاتر
            def _apply_cb(cb, text, fallback="All"):
                txt = text or fallback
                idx = cb.findText(txt)
                if idx < 0:
                    cb.addItem(txt)
                    idx = cb.findText(txt)
                cb.setCurrentIndex(idx)

            self.search_edit.setText(filters.get("q", ""))
            _apply_cb(self.section_cb, filters.get("section"))
            _apply_cb(self.stage_cb, filters.get("stage"))
            _apply_cb(self.host_cb, filters.get("host"))
            self.apply_filter()

            # استعادة الفرز
            if sort_state:
                try:
                    self.table.sortItems(
                        int(sort_state.get("column", 0)),
                        Qt.SortOrder(int(sort_state.get("order", Qt.AscendingOrder))),
                    )
                except Exception:
                    pass

            # استعادة التمرير والاختيار
            try:
                self.table.verticalScrollBar().setValue(int(scroll.get("v", 0)))
                self.table.horizontalScrollBar().setValue(int(scroll.get("h", 0)))
            except Exception:
                pass
            sel_model = self.table.selectionModel()
            if sel_model:
                sel_model.clearSelection()
                for key in sel_keys:
                    rr = self._row_by_key.get(tuple(key))
                    if rr is not None:
                        idx = self.table.model().index(rr, 0)
                        sel_model.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)

            types = [k[2] for k in self._row_by_key]
            up = types.count("UPLOAD")
            down = types.count("DOWNLOAD")
            _dbg(
                f"_load_status_snapshot rows={self.table.rowCount()} map={len(self._row_by_key)} uploads={up} downloads={down}")
            log.info("Loaded status snapshot (%d rows)", self.table.rowCount())

        except Exception:
            log.error("Failed to load status snapshot", exc_info=True)
        finally:
            # إعادة تفعيل الفرز وإشارات الفلاتر
            try:
                self.table.setSortingEnabled(sorting)
            except Exception:
                pass
            for w, prev in zip(widgets, prev_blocks):
                try:
                    w.blockSignals(prev)
                except Exception:
                    pass
            self.table.viewport().update()

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

        if st.op_type == OpType.UPLOAD:
            steps[skey]["speed_bps"] = float(getattr(st, "speed", 0) or 0)
            steps[skey]["eta_secs"] = float(getattr(st, "eta", 0) or 0)

    def _aggregate_upload_metrics(self, section: str, item: str):
        """Return average speed/ETA for active UPLOAD steps of a thread."""
        steps = self._thread_steps.get((section, item), {})
        speeds = []
        etas = []
        for (op_name, _), info in steps.items():
            if op_name != OpType.UPLOAD.name:
                continue
            if info.get("finished") or info.get("error"):
                continue
            spd = info.get("speed_bps") or 0
            eta = info.get("eta_secs") or 0
            if spd > 0:
                speeds.append(spd)
            if eta > 0:
                etas.append(eta)
        avg_speed = sum(speeds) / len(speeds) if speeds else None
        avg_eta = sum(etas) / len(etas) if etas else None
        return avg_speed, avg_eta

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

    def _clear_text_cell(self, row: int, col: int):
        """يمسح نص الخلية ويبلّغ الموديل بالتغيير."""
        if col is None or col < 0:
            return
        it = self._ensure_item(row, col)
        it.setText("")
        model = self.table.model()
        idx = model.index(row, col)
        model.dataChanged.emit(idx, idx, [Qt.DisplayRole])

    def enqueue_status(self, st: OperationStatus) -> None:
        key = (st.section, st.item, getattr(st.op_type, "name", st.op_type))
        prog = getattr(st, "progress", None)
        if prog is not None:
            now = time.monotonic()
            last = self._last_progress.get(key)
            if last and last[0] == prog and (now - last[1]) < 0.15:
                return
            self._last_progress[key] = (prog, now)
        self._pending_by_key[key] = st
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_status(self) -> None:
        if not self._pending_by_key:
            return
        statuses = list(self._pending_by_key.values())
        self._pending_by_key = {}
        sorting = self.table.isSortingEnabled()
        if sorting:
            self.table.setSortingEnabled(False)
        updated_keys = []
        for st in statuses:
            updated_keys.append(self.handle_status(st))
        if sorting:
            header = self.table.horizontalHeader()
            col = header.sortIndicatorSection()
            order = header.sortIndicatorOrder()
            self.table.setSortingEnabled(True)
            self.table.sortItems(col, order)
            sec_col = self._col_map.get("Section")
            item_col = self._col_map.get("Item")
            stage_col = self._col_map.get("Stage")
            for key in updated_keys:
                sec, item, _ = key
                for r in range(self.table.rowCount()):
                    s = self.table.item(r, sec_col).text() if sec_col is not None else ""
                    it = self.table.item(r, item_col).text() if item_col is not None else ""
                    if s == sec and it == item:
                        self._row_by_key[key] = r
                        break
            self._row_last_stage = {
                r: self._stage_from_text(
                    self.table.item(r, stage_col).text()
                    if stage_col is not None and self.table.item(r, stage_col)
                    else ""
                )
                for r in range(self.table.rowCount())
            }
        if self._filter_active():
            self.apply_filter()
            if self._visible_rows_count() == 0:
                self._reset_filters_to_all()


    def _update_row_from_status(self, st: OperationStatus):
        sec = st.section or ("Uploads" if st.op_type == OpType.UPLOAD else "Downloads")
        key = (sec, st.item, st.op_type.name)
        tid = st.thread_id or f"{sec}:{st.item}"
        row = self._row_by_tid.get(tid)
        if row is None:
            row = self._row_by_key.get(key)
        if row is None and st.links:
            updated = ["Keeplinks"] if st.keeplinks_url else []
            log.info("POPULATE-LINKS tid=%s row=? updated=%s", tid, updated)
            return
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col in range(self.table.columnCount()):
                self._ensure_item(row, col)
            self._row_by_key[key] = row
            self._row_by_tid.setdefault(tid, row)

        self._ensure_section_option(sec)

        stage = self._stage_from_text(getattr(st, "message", ""))
        if stage == OpStage.RUNNING:
            stage = getattr(st, "stage", OpStage.RUNNING)

        txts = [
            sec or "",
            st.item or "",
            (getattr(stage, "name", str(stage)) or "").title(),
            st.message or "",
            self._fmt_speed(getattr(st, "speed", None)),
            self._fmt_eta(getattr(st, "eta", None)),
        ]
        for c, v in enumerate(txts):
            self._ensure_item(row, c).setText(str(v))

        self._record_step(st)

        if st.op_type == OpType.UPLOAD:
            spd, eta = self._aggregate_upload_metrics(sec, st.item)
            model = self.table.model()
            sc = self._col_map.get("Speed")
            sc = self._col_map.get("Speed")
            ec = self._col_map.get("ETA")
            if sc is not None:
                (self._ensure_item(row, sc).setText(self._fmt_speed(spd)) if spd else self._clear_text_cell(row, sc))
                idx = model.index(row, sc)
                idx = model.index(row, sc)
                model.dataChanged.emit(idx, idx, [Qt.DisplayRole])
            if ec is not None:
                (self._ensure_item(row, ec).setText(self._fmt_eta(eta)) if eta else self._clear_text_cell(row, ec))
                idx = model.index(row, ec)
                idx = model.index(row, ec)
                model.dataChanged.emit(idx, idx, [Qt.DisplayRole])

        if self._progress_col is not None:
            if st.op_type == OpType.UPLOAD:
                steps = self._thread_steps.get((sec, st.item), {})
                ups = [s["progress"] for (op_name, _), s in steps.items() if op_name == "UPLOAD"]
                p = int(round(sum(ups) / len(ups))) if ups else int(getattr(st, "progress", 0) or 0)
            else:
                try:
                    p = int(getattr(st, "progress", 0) or 0)
                except Exception:
                    p = 0
            if p > 0:
                self._set_progress_cell(row, self._progress_col, p)
            else:
                self._clear_progress_cell(row, self._progress_col)

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
                    host_col = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())].index(host_name)
                except ValueError:
                    host_col = None
                if host_col is not None:
                    try:
                        hp = int(getattr(st, "progress", 0) or 0)
                    except Exception:
                        hp = 0
                    (self._set_progress_cell(row, host_col, hp) if hp > 0 else self._clear_progress_cell(row, host_col))

        if st.stage == OpStage.FINISHED and st.op_type == OpType.UPLOAD and st.links:
            model = self.table.model()
            updated_hosts: list[str] = []
            for host, header in HOST_COLS.items():
                col = self._host_col_index.get(host)
                if col is None:
                    continue
                lnks = _normalize_links(st.links.get(host))
                if lnks:
                    self._ensure_item(row, col).setText("\n".join(lnks))
                    self._set_progress_cell(row, col, 100)
                    idx = model.index(row, col)
                    model.dataChanged.emit(idx, idx, [Qt.DisplayRole])
                    updated_hosts.append(header)
            if updated_hosts or st.keeplinks_url:
                log_hosts = [h for h in updated_hosts if h in ("RG", "RG_BAK")]
                if st.keeplinks_url:
                    log_hosts.append("Keeplinks")
                log.info("POPULATE-LINKS tid=%s row=%s updated=%s", tid, row, log_hosts)
                link_col = self._col_map.get("Links")
                if link_col is not None:
                    rg = _normalize_links(st.links.get("rapidgator"))
                    self._ensure_item(row, link_col).setText(rg[0] if rg else "")
                    idx = model.index(row, link_col)
                    model.dataChanged.emit(idx, idx, [Qt.DisplayRole])
        changed = False
        if self._row_last_stage.get(row) != stage:
            self._color_row(row, stage, st.op_type)
            self._row_last_stage[row] = stage
            changed = True
        model = self.table.model()
        roles = [Qt.DisplayRole]
        if changed:
            tl = model.index(row, 0)
            br = model.index(row, self.table.columnCount() - 1)
            model.dataChanged.emit(tl, br, [Qt.BackgroundRole])
            roles.append(Qt.BackgroundRole)
        tl = model.index(row, 0)
        br = model.index(row, self.table.columnCount() - 1)
        model.dataChanged.emit(tl, br, roles)
        self.table.viewport().update()
        return key

    def handle_status(self, st: OperationStatus):
        key = self._update_row_from_status(st)
        self._schedule_status_save()
        return key

    def connect_worker(self, worker: QObject) -> None:
        """Only propagate cancel events to workers."""
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

        # علّم الصفوف الجارية كـ "Cancelled" فورًا فى الواجهة
        stage_col = self._col_map.get("Stage")
        if stage_col is not None:
            model = self.table.model()
            for row in range(self.table.rowCount()):
                it = self.table.item(row, stage_col)
                txt = it.text() if it else ""
                if self._stage_from_text(txt) == OpStage.RUNNING:
                    if it is None:
                        it = self._ensure_item(row, stage_col)
                    it.setText("Cancelled")
                    self._color_row(row, "cancelled")
            if self.table.rowCount():
                tl = model.index(0, 0)
                br = model.index(self.table.rowCount() - 1, self.table.columnCount() - 1)

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

    @pyqtSlot(object)
    def on_progress_update(self, op: OperationStatus) -> None:
        """Main-thread slot to handle progress updates from workers.

        The connection to this slot **must** use ``Qt.QueuedConnection`` so
        that all GUI mutations occur on the main thread.  The received
        ``OperationStatus`` is forwarded to the appropriate handler so that the
        QTableWidget reflects the latest state.  If a batching method
        (``_enqueue_status``) exists, it will be used; otherwise it falls back
        to ``handle_status``.  Errors are logged rather than propagated to
        avoid crashing the GUI thread.

        Args:
            op: The OperationStatus instance emitted by a worker.
        """
        try:
            enqueuer = getattr(self, "_enqueue_status", None)
            if callable(enqueuer):
                enqueuer(op)
            else:
                self.handle_status(op)
            # After handling the status update, if this is a completed upload
            # operation then populate the host and keeplinks columns for the
            # corresponding thread.  This ensures that newly generated links
            # (Rapidgator, backup, ddownload, katfile, nitroflare) and the
            # protected Keeplinks URL are written into the table once an
            # upload finishes.  Keep this call inside the queued slot so
            # that UI changes occur on the main thread.
            try:
                from models.operation_status import OpStage, OpType  # local import to avoid circular
                if getattr(op, "stage", None) == OpStage.FINISHED and getattr(op, "op_type", None) == OpType.UPLOAD:
                    # Determine a thread identifier.  Fallback to section:item if none provided.
                    tid = getattr(op, "thread_id", None)
                    if not tid:
                        # Section defaults to Uploads or Downloads based on the operation type
                        sec = op.section or ("Uploads" if getattr(op, "op_type", None) == OpType.UPLOAD else "Downloads")
                        tid = f"{sec}:{op.item}"
                    links = getattr(op, "links", {}) or {}
                    keeplinks = getattr(op, "keeplinks_url", None) or ""
                    # Some workers may embed meta information in different attributes
                    # (upload_meta, meta, payload).  Prefer the first present.
                    meta = {}
                    for attr in ("upload_meta", "meta", "payload"):
                        maybe = getattr(op, attr, None)
                        if isinstance(maybe, dict):
                            meta = maybe
                            break
                    self.populate_links_by_tid(tid, links, keeplinks, meta)
            except Exception:
                # Do not propagate errors from our helper; the main status
                # handling should proceed regardless of link population.
                pass
        except Exception as exc:
            log.error("[StatusWidget] on_progress_update error: %s", exc)

