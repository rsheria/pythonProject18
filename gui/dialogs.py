# gui/dialogs.py
import logging


from workers.download_worker import DownloadWorker
from workers.upload_worker   import UploadWorker
import os
import re
import time
import shutil
import subprocess
import hashlib
import random
from datetime import timedelta, datetime
from pathlib import Path
from random import randint

from .widgets import HostDownloadWidget, HostUploadWidget



from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit,
    QDialogButtonBox, QProgressDialog, QProgressBar, QPushButton, QScrollArea, QWidget, QHBoxLayout
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QProgressBar, QLabel,
    QPushButton, QDialogButtonBox
)

# ====================================
# LinksDialog: عرْض الروابط بعد الرفع
# ====================================
class LinksDialog(QDialog):
    def __init__(self, thread_title, links_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Links for {thread_title}")
        layout = QVBoxLayout(self)

        # حاول نقرأ ترتيب الـ hosts من الأب
        if parent and hasattr(parent, 'active_upload_hosts'):
            host_order = parent.active_upload_hosts.copy()
        else:
            host_order = []

        # Display Keeplinks URL first, if موجود
        keeplinks_url = links_dict.get('keeplinks')
        if keeplinks_url:
            layout.addWidget(QLabel("<b>Keeplinks URL:</b>"))
            keeplinks_edit = QTextEdit()
            if isinstance(keeplinks_url, (list, tuple)):
                keeplinks_edit.setPlainText('\n'.join(str(u) for u in keeplinks_url))
            else:
                keeplinks_edit.setPlainText(str(keeplinks_url))
            keeplinks_edit.setReadOnly(True)
            layout.addWidget(keeplinks_edit)

        # بناء لائحة العرض بالترتيب:
        # 1) mega / mega.nz
        # 2) hosts من host_order
        # 3) أي hosts أخرى
        order = []
        if 'mega' in links_dict:
            order.append('mega')
        elif 'mega.nz' in links_dict:
            order.append('mega.nz')

        for host in host_order:
            if host in links_dict and host not in order:
                order.append(host)

        for host in links_dict:
            if host not in order and host != 'keeplinks':
                order.append(host)

        # أضف كل host بحسب الترتيب
        for host in order:
            urls = links_dict.get(host)
            if not urls:
                continue
            # Label
            layout.addWidget(QLabel(f"<b>{host.capitalize()} URLs:</b>"))
            edit = QTextEdit()
            # لو القيم ليست لائحة، حوّلها
            if isinstance(urls, (list, tuple)):
                edit.setPlainText('\n'.join(urls))
            else:
                edit.setPlainText(str(urls))
            edit.setReadOnly(True)
            layout.addWidget(edit)

        # زرّ الإغلاق
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


# ===================================================
# DownloadProgressDialog: نافذة متابعة تنزيل ومعالجة
# ===================================================
class DownloadProgressDialog(QDialog):
    """
    نافذة متابعة تنزيل متعدد الملفات:
    - شريط تقدّم عام في الأعلى
    - قائمة قابلة للتمرير من شُرُوط تقدّم الملفات الفردية
    - أزرار Pause/Continue/Cancel/Close
    """
    pause_clicked    = pyqtSignal()
    continue_clicked = pyqtSignal()
    cancel_clicked   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 🆕 UNIQUE SESSION ID for this dialog instance
        import uuid
        import time
        self.session_id = str(uuid.uuid4())[:8]
        self.creation_time = time.time()
        
        logging.info(f"🆕 DownloadProgressDialog CREATED with session_id={self.session_id}")
        
        self.setWindowTitle(f"Download Progress [ID: {self.session_id}]")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # 🔒 Thread safety lock for UI operations
        from threading import Lock
        self._ui_lock = Lock()
        self._is_destroyed = False

        # dict: link_id -> HostDownloadWidget
        self.file_widgets = {}
        self.file_completed = {}
        self.total_files = 0
        self.completed_files = 0
        
        logging.info(f"📋 Dialog {self.session_id} initialized with CLEAN STATE (0 widgets)")

        self.main_layout = QVBoxLayout(self)

        # Overall progress
        self.overall_label = QLabel("Overall Progress: 0% (0/0)")
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.main_layout.addWidget(self.overall_label)
        self.main_layout.addWidget(self.overall_progress)

        # Scroll area for file widgets
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.files_layout = QVBoxLayout(container)
        self.scroll_area.setWidget(container)
        self.main_layout.addWidget(self.scroll_area)

        # Buttons row
        btn_layout = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.on_pause_clicked)
        btn_layout.addWidget(self.pause_button)

        self.continue_button = QPushButton("Continue")
        self.continue_button.clicked.connect(self.on_continue_clicked)
        btn_layout.addWidget(self.continue_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        btn_layout.addWidget(self.cancel_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        btn_layout.addWidget(self.close_button)

        self.main_layout.addLayout(btn_layout)

    def on_pause_clicked(self):
        self.pause_clicked.emit()

    def on_continue_clicked(self):
        self.continue_clicked.emit()

    def on_cancel_clicked(self):
        self.cancel_clicked.emit()

    def create_file_widget(self, link_id: str, file_name: str):
        """
        🔒 Thread-safe file widget creation
        تُستدعى عند انشاء ملف جديد من قبل الـ worker
        => تضيف HostDownloadWidget للملف.
        """
        with self._ui_lock:
            try:
                # 🆔 SESSION VALIDATION: Log widget creation request
                logging.debug(f"🆕 Dialog {self.session_id} received create_file_widget request for {link_id}: {file_name}")
                
                # 🛡️ Check if dialog is destroyed or invalid
                if self._is_destroyed or not hasattr(self, 'file_widgets') or not hasattr(self, 'files_layout'):
                    logging.debug(f"🚫 Dialog {self.session_id} not ready for widget creation (link_id={link_id})")
                    return
                    
                # 🚫 STRICT validation: Skip if widget already exists (indicates reset issue)
                if link_id in self.file_widgets:
                    logging.error(f"❌ DUPLICATE WIDGET DETECTED in dialog {self.session_id} for link_id={link_id} - POSSIBLE CROSS-SESSION SIGNAL!")
                    logging.error(f"Dialog {self.session_id} current widgets: {list(self.file_widgets.keys())}")
                    # Remove the old widget to prevent duplicates
                    old_widget = self.file_widgets[link_id]
                    try:
                        self.files_layout.removeWidget(old_widget)
                        old_widget.setParent(None)
                        old_widget.deleteLater()
                        del self.file_widgets[link_id]
                        logging.warning(f"🧨 Cleaned up duplicate widget for {link_id}")
                    except Exception as cleanup_error:
                        logging.error(f"Failed to cleanup duplicate widget: {cleanup_error}")

                # 🆕 Create fresh widget with proper initialization
                logging.info(f"🆕 Dialog {self.session_id}: Creating NEW file widget for: {file_name[:30]}... (link_id={link_id})")
                logging.info(f"🔍 Dialog {self.session_id}: Current widgets before creation: {list(self.file_widgets.keys())}")
                widget = HostDownloadWidget("File")
                
                # Set file name with length limit for UI
                display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
                widget.file_label.setText(f"File: {display_name}")
                
                # 🔄 Initialize widget with CLEAN slate - 0% progress
                widget.update_progress(
                    progress=0,
                    status_msg="Initializing download...",
                    current_size=0,
                    total_size=0,
                    speed=0.0,
                    eta=0.0,
                    current_file=file_name
                )

                # 📝 Register widget in tracking dictionaries
                self.file_widgets[link_id] = widget
                self.file_completed[link_id] = False
                
                # 🎨 Add widget to UI layout
                self.files_layout.addWidget(widget)
                
                # 📈 Update counters and overall progress
                self.total_files += 1
                self.update_overall_label()
                
                logging.info(f"✅ CREATED file widget successfully: {file_name[:30]}... (Total: {self.total_files})")
                logging.debug(f"Active widgets: {list(self.file_widgets.keys())}")
                
            except Exception as e:
                logging.debug(f"File widget creation error (non-critical): {e}")

    def update_file_progress(self,
                             link_id: str,
                             progress: int,
                             status_msg: str,
                             current_size: int,
                             total_size: int,
                             current_file: str,
                             speed: float = 0.0,
                             eta: float = 0.0):
        """
        🔒 Thread-safe progress update method
        تُستدعى عند تحديث تقدّم ملف من قبل الـ worker
        => تُحدّث شريط التقدم في الـ HostDownloadWidget المناسب.
        """
        with self._ui_lock:
            try:
                # 🆔 SESSION VALIDATION: Log signal reception for debugging
                logging.debug(f"📶 Dialog {self.session_id} received progress update for {link_id} (Progress: {progress}%)")
                
                # 🛡️ Check if dialog is destroyed or invalid
                if self._is_destroyed or not hasattr(self, 'file_widgets') or not self.file_widgets:
                    logging.debug(f"🚫 Ignoring progress update - dialog {self.session_id} is destroyed")
                    return
                    
                # 🔍 Find target widget for this progress update
                widget = self.file_widgets.get(link_id)
                if not widget:
                    logging.warning(f"⚠️ PROGRESS UPDATE IGNORED: No widget found for link_id={link_id}")
                    logging.debug(f"Available widgets: {list(self.file_widgets.keys())}")
                    return

                # 🛡️ Verify widget is still properly attached to UI
                if widget.parent() is None:
                    logging.warning(f"Widget for {link_id} has no parent - cleaning up orphaned entry")
                    # Clean up orphaned widget from tracking
                    try:
                        del self.file_widgets[link_id]
                        if link_id in self.file_completed:
                            del self.file_completed[link_id]
                    except Exception:
                        pass
                    return

                # 📈 Apply progress update to widget
                logging.debug(f"Dialog {self.session_id}: Updating progress for {link_id}: {progress}% - {status_msg[:30]}...")
                logging.debug(f"Dialog {self.session_id}: Current widgets: {list(self.file_widgets.keys())}")
                widget.update_progress(
                    progress=progress,
                    status_msg=status_msg,
                    current_size=current_size,
                    total_size=total_size,
                    speed=speed,
                    eta=eta,
                    current_file=current_file
                )

                # 🏁 Handle completion detection
                if progress >= 100 or "complete" in status_msg.lower():
                    if link_id in self.file_completed and not self.file_completed[link_id]:
                        self.file_completed[link_id] = True
                        self.completed_files += 1
                        logging.info(f"🏆 File completed: {current_file[:30]}... ({self.completed_files}/{self.total_files})")
                        self.update_overall_label()
                        
            except Exception as e:
                logging.debug(f"Progress update error (non-critical): {e}")

    def reset_for_new_session(self):
        """
        🔒 Thread-safe session reset
        إعادة تعيين النافذة لجلسة تحميل جديدة.
        مسح جميع الـ widgets والعدّاتات والاستعداد لتحميل جديد.
        """
        with self._ui_lock:
            try:
                logging.info("🧹 STARTING comprehensive dialog reset for new download session...")
                
                # Reset destroyed flag
                self._is_destroyed = False
                
                # 🚫 STEP 1: Force hide dialog during reset to prevent visual glitches
                was_visible = self.isVisible()
                if was_visible:
                    self.hide()
                    logging.debug("👁️ Dialog temporarily hidden during reset")
                
                # 🧨 STEP 2: AGGRESSIVE widget cleanup - Remove ALL file widgets
                widget_count = len(self.file_widgets) if hasattr(self, 'file_widgets') else 0
                logging.info(f"🗑️ Cleaning up {widget_count} existing file widgets...")
                
                if hasattr(self, 'file_widgets') and self.file_widgets:
                    for link_id, widget in list(self.file_widgets.items()):
                        try:
                            if widget and not widget.parent() is None:
                                # Remove from layout first
                                if hasattr(self, 'files_layout') and self.files_layout:
                                    self.files_layout.removeWidget(widget)
                                # Disconnect any signals if present
                                try:
                                    widget.disconnect()
                                except Exception:
                                    pass
                                # Delete widget
                                widget.setParent(None)
                                widget.deleteLater()
                                logging.debug(f"🗑️ Cleaned widget for {link_id}")
                        except Exception as e:
                            logging.debug(f"Widget cleanup error for {link_id}: {e}")
                
                # 🧨 STEP 3: Clear layout completely - remove any orphaned items
                if hasattr(self, 'files_layout') and self.files_layout:
                    layout_count = self.files_layout.count()
                    if layout_count > 0:
                        logging.info(f"🧹 Cleaning {layout_count} remaining layout items...")
                        for i in range(layout_count):
                            try:
                                child = self.files_layout.takeAt(0)
                                if child and child.widget():
                                    child.widget().deleteLater()
                            except Exception as e:
                                logging.debug(f"Layout cleanup error: {e}")
                        
                # 🧹 STEP 4: Reset ALL tracking dictionaries and counters
                logging.info("📊 Resetting progress tracking data...")
                if hasattr(self, 'file_widgets'):
                    self.file_widgets.clear()
                else:
                    self.file_widgets = {}
                    
                if hasattr(self, 'file_completed'):
                    self.file_completed.clear() 
                else:
                    self.file_completed = {}
                    
                self.total_files = 0
                self.completed_files = 0
                
                # 🔄 STEP 5: Force Qt event processing for complete cleanup
                from PyQt5.QtWidgets import QApplication
                QApplication.processEvents()
                
                # Brief delay to ensure Qt finishes all deletions
                import time
                time.sleep(0.1)  # 100ms for thorough cleanup
                
                # 🛡️ STEP 6: Reset UI elements to initial state
                if hasattr(self, 'overall_label'):
                    self.overall_label.setText("Overall Progress: 0% (0/0)")
                if hasattr(self, 'overall_progress'):
                    self.overall_progress.setValue(0)
                    self.overall_progress.setRange(0, 100)
                    
                # 🔄 STEP 7: Force final UI refresh
                QApplication.processEvents()
                
                # 👁️ STEP 8: Show dialog again if it was visible
                if was_visible:
                    self.show()
                    logging.debug("👁️ Dialog restored to visible state")
                
                logging.info("✅ COMPLETE: Dialog reset successfully for fresh download session")
                
            except Exception as e:
                logging.error(f"❌ CRITICAL ERROR during dialog reset: {e}", exc_info=True)
                # Emergency recovery - force reinitialize ALL attributes
                try:
                    self.file_widgets = {}
                    self.file_completed = {}
                    self.total_files = 0
                    self.completed_files = 0
                    if hasattr(self, 'overall_label'):
                        self.overall_label.setText("Overall Progress: 0% (0/0)")
                    if hasattr(self, 'overall_progress'):
                        self.overall_progress.setValue(0)
                    # Force show dialog if it was hidden during failed reset
                    if hasattr(self, 'show'):
                        self.show()
                    logging.warning("⚠️ Emergency recovery completed")
                except Exception as recovery_error:
                    logging.error(f"❌ Recovery failed: {recovery_error}")

    def update_overall_label(self):
        """
        يُستدعى عند إضافة ملف جديد أو اكتمال أحدها
        => يُحدّث الشريط العام والنسبة في العنوان.
        """
        if self.total_files > 0:
            overall_pct = int((self.completed_files / self.total_files) * 100)
            self.overall_progress.setValue(overall_pct)
            self.overall_label.setText(
                f"Overall Progress: {overall_pct}% ({self.completed_files}/{self.total_files})"
            )
            
    def closeEvent(self, event):
        """
        🔒 Thread-safe dialog close event
        تعيّن فلاج التدمير لمنع محاولة تحديث UI بعد إغلاق النافذة
        """
        with self._ui_lock:
            self._is_destroyed = True
        super().closeEvent(event)


# ==================================
# UploadProgressDialog: متابعة الرفع
# ==================================
class UploadProgressDialog(QDialog):
    """Dialog showing detailed upload progress for all hosts"""

    # إشارات للتحكم في الرفع من الخارج
    pause_clicked    = pyqtSignal()
    continue_clicked = pyqtSignal()
    cancel_clicked   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detailed Upload Progress")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # قاموس لحفظ ويدجت لكل مستضيف
        self.host_widgets   = {}  # host_name.lower() -> HostUploadWidget
        self.start_times    = {}  # لحساب السرعة/ETA
        self.host_completed = {}  # host_name.lower() -> bool

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # منطقة التمرير لويدجتات المستضيفين
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        self.hosts_layout = QVBoxLayout(container)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        # إنشاء ويدجت لكل مستضيف
        # تأكد من أن الترتيب مطابق لترتيب الـ host_idx
        for host in ['Rapidgator', 'Nitroflare', 'DDownload', 'KatFile', 'Mega']:
            w = HostUploadWidget(host)
            key = host.lower()
            self.host_widgets[key]   = w
            self.host_completed[key] = False
            self.hosts_layout.addWidget(w)

        # أزرار التحكم بالرفع
        btn_layout = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.on_pause_clicked)
        btn_layout.addWidget(self.pause_button)

        self.continue_button = QPushButton("Continue")
        self.continue_button.clicked.connect(self.on_continue_clicked)
        btn_layout.addWidget(self.continue_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        btn_layout.addWidget(self.cancel_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        btn_layout.addWidget(self.close_button)

        layout.addLayout(btn_layout)

    def on_pause_clicked(self):
        """Emit pause signal"""
        self.pause_clicked.emit()

    def on_continue_clicked(self):
        """Emit continue signal"""
        self.continue_clicked.emit()

    def on_cancel_clicked(self):
        """Emit cancel signal"""
        self.cancel_clicked.emit()

    def update_host_progress(self,
                             host: str,
                             progress: int,
                             status_msg: str,
                             current_size: int = 0,
                             total_size: int = 0,
                             current_file: str = ""):
        """
        تحدّث التقدّم لويدجت المستضيف المعني:
        - host: اسم المستضيف (rapidgator, nitroflare, ...)
        - progress: 0..100
        - status_msg: نص الحالة ("Uploading X", "Complete X", ...)
        - current_size, total_size: للأرقام ١٠/٢٠ ميغابايت
        - current_file: اسم الملف الجاري رفعه
        """
        try:
            key = host.lower()
            widget = self.host_widgets.get(key)
            if not widget:
                return

            # تسجيل زمن البداية لحساب السرعة
            if progress > 0 and key not in self.start_times:
                self.start_times[key] = time.time()

            # حساب السرعة والـ ETA
            speed = 0.0
            eta   = 0.0
            if key in self.start_times and current_size > 0:
                elapsed = time.time() - self.start_times[key]
                if elapsed > 0:
                    speed = current_size / elapsed
                    if total_size > 0:
                        remaining = total_size - current_size
                        eta = remaining / speed if speed > 0 else 0

            # حدّث الويجت
            widget.update_progress(
                progress=progress,
                status_msg=status_msg,
                current_size=current_size,
                total_size=total_size,
                speed=speed,
                eta=eta,
                current_file=current_file
            )

            # لو انتهى المستضيف من الرفع، علّمه
            if "complete" in status_msg.lower():
                self.host_completed[key] = True
            else:
                self.host_completed[key] = False

            # إذا كلهم اكتملوا، أقفل النافذة
            if all(self.host_completed.values()):
                self.close()

        except Exception as e:
            logging.error(f"Error updating host progress: {e}", exc_info=True)

