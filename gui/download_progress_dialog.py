import logging
import time

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea,
    QWidget, QPushButton, QProgressBar, QLabel
)
from PyQt5.QtCore import Qt, pyqtSignal

class DownloadProgressDialog(QDialog):
    """
    A multi-file download progress dialog that displays:
    - an "Overall Progress" bar at the top
    - a scrollable list of file-specific progress bars below
    - pause/continue/cancel/close buttons
    """

    pause_clicked = pyqtSignal()
    continue_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detailed Download Progress")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # link_id -> HostDownloadWidget
        self.file_widgets = {}
        self.file_completed = {}
        self.total_files = 0
        self.completed_files = 0

        self.main_layout = QVBoxLayout(self)

        # Overall progress bar
        self.overall_label = QLabel("Overall Progress: 0% (0/0)")
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)

        self.main_layout.addWidget(self.overall_label)
        self.main_layout.addWidget(self.overall_progress)

        # Scroll area for multiple file widgets
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.files_layout = QVBoxLayout(self.container)
        self.scroll_area.setWidget(self.container)

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
        logging.info("Cancel clicked (no JDownloader action here).")

    def create_file_widget(self, link_id: str, file_name: str):
        """
        Slot called by the worker's file_created signal => create the HostDownloadWidget for this link.
        """
        widget = HostDownloadWidget("Rapidgator")  # Or just name it "File"
        widget.file_label.setText(f"File: {file_name}")

        self.file_widgets[link_id] = widget
        self.file_completed[link_id] = False
        self.files_layout.addWidget(widget)

        # Increase total files count
        self.total_files += 1
        self.update_overall_label()

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
        Slot called by the worker's file_progress_update signal => update progress for that link's widget.
        """
        widget = self.file_widgets.get(link_id)
        if not widget:
            logging.warning(f"No widget found for link_id={link_id}")
            return

        widget.update_progress(
            progress=progress,
            status_msg=status_msg,
            current_size=current_size,
            total_size=total_size,
            speed=speed,
            eta=eta,
            current_file=current_file
        )

        # If progress == 100 or status says complete => mark that file done
        if progress >= 100 or "complete" in status_msg.lower():
            if not self.file_completed[link_id]:
                self.file_completed[link_id] = True
                self.completed_files += 1
                self.update_overall_label()

            # If all completed, optionally close
            if self.completed_files == self.total_files:
                # auto-close if desired
                # self.close()
                pass

    def reset_for_new_session(self):
        """
        Reset the dialog for a new download session.
        Clear all widgets, counters, and prepare for new downloads.
        """
        # Clear all file widgets
        for widget in self.file_widgets.values():
            widget.setParent(None)
            widget.deleteLater()

        self.file_widgets.clear()
        self.file_completed.clear()
        self.total_files = 0
        self.completed_files = 0

        # Reset overall progress
        self.overall_label.setText("Overall Progress: 0% (0/0)")
        self.overall_progress.setValue(0)

        logging.info(" Progress dialog reset for new download session")

    def update_overall_label(self):
        """
        Called whenever we add a new file or complete a file => update overall % and label.
        """
        if self.total_files > 0:
            progress = int((self.completed_files / self.total_files) * 100)
        else:
            progress = 0

        self.overall_label.setText(f"Overall Progress: {progress}% ({self.completed_files}/{self.total_files})")
        self.overall_progress.setValue(progress)
