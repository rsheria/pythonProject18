from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QProgressBar, QWidget, QScrollArea, QPushButton)
from PyQt5.QtCore import Qt, pyqtSignal
import time
import logging


class HostUploadWidget(QWidget):
    """Widget to show detailed progress for a single host"""

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
        self.file_label = QLabel("File: -")
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
        """Update all progress information"""
        try:
            self.progress_bar.setValue(progress)

            if current_file:
                self.file_label.setText(f"File: {current_file}")
            else:
                self.file_label.setText("File: -")

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
        """Format speed in bytes/second to human readable format"""
        if speed < 1024:
            return f"{speed:.1f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed / (1024 * 1024):.1f} MB/s"

    @staticmethod
    def format_size(size):
        """Format size in bytes to human readable format"""
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
        """Format seconds to human readable time"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds // 60
            seconds = seconds % 60
            return f"{minutes:.0f}m {seconds:.0f}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}h {minutes:.0f}m"


class UploadProgressDialog(QDialog):
    """Dialog showing detailed upload progress for all hosts"""

    # Signals to control upload state externally
    pause_clicked = pyqtSignal()
    continue_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.host_widgets = {}
        self.start_times = {}
        # Track completion for each host (True when done)
        self.host_completed = {}
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Detailed Upload Progress")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # Main layout
        layout = QVBoxLayout()

        # Scroll area for host widgets
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Container widget for host progress widgets
        container = QWidget()
        self.hosts_layout = QVBoxLayout(container)

        # Create widgets for each host
        hosts = ['Rapidgator-Main', 'Nitroflare', 'DDownload', 'KatFile', 'Rapidgator-Backup']
        for host in hosts:
            widget = HostUploadWidget(host)
            self.host_widgets[host.lower()] = widget
            self.hosts_layout.addWidget(widget)
            # Initialize each as not completed
            self.host_completed[host.lower()] = False

        scroll.setWidget(container)
        layout.addWidget(scroll)

        # Button controls layout
        buttons_layout = QHBoxLayout()

        # Pause button
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.on_pause_clicked)
        buttons_layout.addWidget(self.pause_button)

        # Continue button
        self.continue_button = QPushButton("Continue")
        self.continue_button.clicked.connect(self.on_continue_clicked)
        buttons_layout.addWidget(self.continue_button)

        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        buttons_layout.addWidget(self.cancel_button)

        # Close button
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons_layout.addWidget(self.close_button)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def on_pause_clicked(self):
        """Handle pause button click"""
        self.pause_clicked.emit()

    def on_continue_clicked(self):
        """Handle continue button click"""
        self.continue_clicked.emit()

    def on_cancel_clicked(self):
        """Handle cancel button click"""
        self.cancel_clicked.emit()

    def update_host_progress(self, host: str, progress: int, status_msg: str,
                             current_size: int = 0, total_size: int = 0,
                             current_file: str = ""):
        """Update progress for a specific host"""
        try:
            widget = self.host_widgets.get(host.lower())
            if not widget:
                return

            key = host.lower()

            # Initialize start time if not set
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

            # Update the UI
            widget.update_progress(
                progress=progress,
                status_msg=status_msg,
                current_size=current_size,
                total_size=total_size,
                speed=speed,
                eta=eta,
                current_file=current_file
            )

            # Check if status implies this host is completed
            # (Adjust the check as needed: e.g. "Completed", "Done", "Success" etc.)
            if "complete" in status_msg.lower():
                self.host_completed[key] = True
            else:
                self.host_completed[key] = False

            # If all hosts are completed, close the dialog
            if all(self.host_completed.values()):
                self.close()

        except Exception as e:
            logging.error(f"Error updating host progress: {str(e)}")
