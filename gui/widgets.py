# gui/widgets.py

import logging
import time
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QScrollArea
)

# ==============================
# HostDownloadWidget (للتحميل)
# ==============================
class HostDownloadWidget(QWidget):
    """
    Widget to show detailed progress for a single download file.
    """
    def __init__(self, host_name, parent=None):
        super().__init__(parent)
        self.host_name = host_name
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Header: اسم الملف أو الرابط
        self.header = QLabel(f"<b>{self.host_name}</b>")
        layout.addWidget(self.header)

        # شريط التقدّم
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_bar)

        # صف المعلومات (اسم الملف، السرعة، المدة المتبقية)
        info_layout = QHBoxLayout()
        self.file_label  = QLabel("File: -")
        self.speed_label = QLabel("Speed: -")
        self.eta_label   = QLabel("ETA: -")
        info_layout.addWidget(self.file_label)
        info_layout.addWidget(self.speed_label)
        info_layout.addWidget(self.eta_label)
        layout.addLayout(info_layout)

        # رسالة الحالة
        self.status_label = QLabel("Status: Waiting...")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def update_progress(self, progress, status_msg,
                        current_size=0, total_size=0,
                        speed=0.0, eta=0.0, current_file=""):
        try:
            # تحديث شريط التقدّم
            self.progress_bar.setValue(progress)

            # اسم الملف
            self.file_label.setText(f"File: {current_file}" if current_file else "File: -")

            # السرعة
            self.speed_label.setText(f"Speed: {self._format_speed(speed)}" if speed > 0 else "Speed: -")

            # ETA
            self.eta_label.setText(f"ETA: {self._format_time(eta)}" if eta > 0 else "ETA: -")

            # إذا كان لدينا حجم إجمالي، نضيفه للرسالة
            if total_size:
                size_str = f"{self._format_size(current_size)}/{self._format_size(total_size)}"
                status_msg = f"{status_msg} ({size_str})"

            self.status_label.setText(f"Status: {status_msg}")
        except Exception as e:
            logging.error(f"HostDownloadWidget.update_progress error: {e}", exc_info=True)

    @staticmethod
    def _format_speed(bps: float) -> str:
        if bps < 1024:
            return f"{bps:.1f} B/s"
        elif bps < 1024**2:
            return f"{bps/1024:.1f} KB/s"
        else:
            return f"{bps/1024**2:.1f} MB/s"

    @staticmethod
    def _format_size(bytes_: int) -> str:
        if bytes_ < 1024:
            return f"{bytes_} B"
        elif bytes_ < 1024**2:
            return f"{bytes_/1024:.1f} KB"
        else:
            return f"{bytes_/1024**2:.1f} MB"

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            m = int(seconds//60); s = int(seconds%60)
            return f"{m}m {s}s"
        else:
            h = int(seconds//3600); m = int((seconds%3600)//60)
            return f"{h}h {m}m"


# ===========================
# HostUploadWidget (للرفع)
# ===========================
class HostUploadWidget(QWidget):
    """
    Widget to show detailed progress for a single upload host.
    """
    def __init__(self, host_name, parent=None):
        super().__init__(parent)
        self.host_name = host_name
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # اسم المستضيف
        self.header = QLabel(f"<b>{self.host_name}</b>")
        layout.addWidget(self.header)

        # شريط التقدّم
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_bar)

        # صف المعلومات
        info_layout = QHBoxLayout()
        self.file_label  = QLabel("File: -")
        self.speed_label = QLabel("Speed: -")
        self.eta_label   = QLabel("ETA: -")
        info_layout.addWidget(self.file_label)
        info_layout.addWidget(self.speed_label)
        info_layout.addWidget(self.eta_label)
        layout.addLayout(info_layout)

        # رسالة الحالة
        self.status_label = QLabel("Status: Waiting...")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def update_progress(self, progress, status_msg,
                        current_size=0, total_size=0,
                        speed=0.0, eta=0.0, current_file=""):
        try:
            self.progress_bar.setValue(progress)
            self.file_label.setText(f"File: {current_file}" if current_file else "File: -")
            self.speed_label.setText(f"Speed: {self._format_speed(speed)}" if speed>0 else "Speed: -")
            self.eta_label.setText(f"ETA: {self._format_time(eta)}" if eta>0 else "ETA: -")
            if total_size:
                size_str = f"{self._format_size(current_size)}/{self._format_size(total_size)}"
                status_msg = f"{status_msg} ({size_str})"
            self.status_label.setText(f"Status: {status_msg}")
        except Exception as e:
            logging.error(f"HostUploadWidget.update_progress error: {e}", exc_info=True)

    @staticmethod
    def _format_speed(bps: float) -> str:
        if bps < 1024:
            return f"{bps:.1f} B/s"
        elif bps < 1024**2:
            return f"{bps/1024:.1f} KB/s"
        else:
            return f"{bps/1024**2:.1f} MB/s"

    @staticmethod
    def _format_size(bytes_: int) -> str:
        if bytes_ < 1024:
            return f"{bytes_} B"
        elif bytes_ < 1024**2:
            return f"{bytes_/1024:.1f} KB"
        else:
            return f"{bytes_/1024**2:.1f} MB"

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            m = int(seconds//60); s = int(seconds%60)
            return f"{m}m {s}s"
        else:
            h = int(seconds//3600); m = int((seconds%3600)//60)
            return f"{h}h {m}m"
