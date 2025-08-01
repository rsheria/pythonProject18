import time
import logging
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QProgressBar, QWidget, QScrollArea, QPushButton)
from PyQt5.QtCore import Qt


class BackupHostUploadWidget(QWidget):
    """Widget to show detailed progress for a single host in backup section."""
    def __init__(self, host_name, parent=None):
        super().__init__(parent)
        self.host_name = host_name
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Host name header
        self.header = QLabel(f"<b>{self.host_name}</b>")
        layout.addWidget(self.header)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_bar)

        # Status info layout
        info_layout = QHBoxLayout()

        # File info
        self.file_label = QLabel("Current File: -")
        info_layout.addWidget(self.file_label)

        # Speed info
        self.speed_label = QLabel("Speed: -")
        info_layout.addWidget(self.speed_label)

        # ETA info
        self.eta_label = QLabel("ETA: -")
        info_layout.addWidget(self.eta_label)

        layout.addLayout(info_layout)

        # Status message
        self.status_label = QLabel("Status: Waiting...")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def update_progress(self, progress, status_msg, current_size=0, total_size=0,
                        speed=0, eta=0, current_file=""):
        try:
            self.progress_bar.setValue(progress)

            if current_file:
                self.file_label.setText(f"File: {current_file}")
            else:
                self.file_label.setText("Current File: -")

            if speed > 0:
                speed_str = self.format_speed(speed)
                self.speed_label.setText(f"Speed: {speed_str}")
            else:
                self.speed_label.setText("Speed: -")

            if eta > 0:
                eta_str = self.format_time(eta)
                self.eta_label.setText(f"ETA: {eta_str}")
            else:
                self.eta_label.setText("ETA: -")

            if total_size > 0:
                size_str = f"{self.format_size(current_size)}/{self.format_size(total_size)}"
                status_msg = f"{status_msg} ({size_str})"

            self.status_label.setText(f"Status: {status_msg}")

        except Exception as e:
            logging.error(f"Error updating host progress widget: {str(e)}")

    @staticmethod
    def format_speed(speed):
        if speed < 1024:
            return f"{speed:.1f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed / (1024 * 1024):.1f} MB/s"

    @staticmethod
    def format_size(size):
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

    @staticmethod
    def format_time(seconds):
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds // 60
            sec = seconds % 60
            return f"{minutes:.0f}m {sec:.0f}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}h {minutes:.0f}m"


class BackupUploadProgressDialog(QDialog):
    """Dialog showing detailed upload progress for backup (no Mega)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.host_widgets = {}
        self.start_times = {}
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Backup Upload Progress")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        layout = QVBoxLayout()

        # Scroll area for host widgets
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Container widget for host progress widgets
        container = QWidget()
        self.hosts_layout = QVBoxLayout(container)

        # Hosts for backup including dedicated Rapidgator account
        hosts = ['Rapidgator-Main', 'Nitroflare', 'DDownload', 'KatFile', 'Rapidgator-Backup']
        for host in hosts:
            widget = BackupHostUploadWidget(host)
            self.host_widgets[host.lower()] = widget
            self.hosts_layout.addWidget(widget)

        scroll.setWidget(container)
        layout.addWidget(scroll)

        # Add close button
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

        self.setLayout(layout)

    def update_host_progress(self, host: str, progress: int, status_msg: str,
                             current_size: int = 0, total_size: int = 0,
                             current_file: str = ""):
        try:
            widget = self.host_widgets.get(host.lower())
            if not widget:
                return

            key = host.lower()

            # Initialize start time if not set and progress > 0
            if progress > 0 and key not in self.start_times:
                self.start_times[key] = time.time()

            # Calculate speed and ETA
            speed = 0
            eta = 0
            if key in self.start_times and current_size > 0:
                elapsed = time.time() - self.start_times[key]
                if elapsed > 0:
                    speed = current_size / elapsed
                    if total_size > 0:
                        remaining = total_size - current_size
                        eta = remaining / speed if speed > 0 else 0

            widget.update_progress(
                progress=progress,
                status_msg=status_msg,
                current_size=current_size,
                total_size=total_size,
                speed=speed,
                eta=eta,
                current_file=current_file
            )

        except Exception as e:
            logging.error(f"Error updating host progress: {str(e)}")
