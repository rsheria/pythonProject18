import logging
import time
from typing import Optional
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QProgressBar, QApplication


class UploadProgressHandler:
    def __init__(self, table):
        self.table = table
        self.progress_bars = {}
        self.upload_states = {}
        self.start_times = {}

        # Update STYLES dictionary to include 'default'
        self.STYLES = {
            'default': """
                QProgressBar {
                    border: 1px solid #CCCCCC;
                    border-radius: 5px;
                    text-align: center;
                    background-color: #F5F5F5;
                    height: 20px;
                    margin: 2px;
                    padding: 2px;
                    color: black;
                }
                QProgressBar::chunk {
                    background-color: #2196F3;
                    border-radius: 4px;
                }
            """,
            'uploading': """
                QProgressBar {
                    border: 1px solid #2196F3;
                    border-radius: 5px;
                    text-align: center;
                    background-color: #E3F2FD;
                    height: 20px;
                    margin: 2px;
                    padding: 2px;
                    color: black;
                }
                QProgressBar::chunk {
                    background-color: #2196F3;
                    border-radius: 4px;
                }
            """,
            'completed': """
                QProgressBar {
                    border: 1px solid #4CAF50;
                    border-radius: 5px;
                    text-align: center;
                    background-color: #E8F5E9;
                    height: 20px;
                    margin: 2px;
                    padding: 2px;
                    color: black;
                }
                QProgressBar::chunk {
                    background-color: #4CAF50;
                    border-radius: 4px;
                }
            """,
            'error': """
                QProgressBar {
                    border: 1px solid #F44336;
                    border-radius: 5px;
                    text-align: center;
                    background-color: #FFEBEE;
                    height: 20px;
                    margin: 2px;
                    padding: 2px;
                    color: black;
                }
                QProgressBar::chunk {
                    background-color: #F44336;
                    border-radius: 4px;
                }
            """
        }

    def update_progress(self, row: int, host_idx: int, progress: int, status_msg: str,
                       current_size: int = 0, total_size: int = 0):
        """Update progress with size, speed and time information."""
        try:
            progress_bar = self.get_progress_bar(row, host_idx)
            if not progress_bar:
                return

            key = f"{row}:{host_idx}"
            
            # Handle waiting state
            if status_msg.lower() == "waiting":
                progress_bar.setStyleSheet(self.STYLES['default'])
                progress_bar.setValue(0)
                progress_bar.setFormat("Waiting...")
                QApplication.processEvents()
                return
                
            # Handle disabled state
            if status_msg.lower() == "disabled":
                progress_bar.setStyleSheet(self.STYLES['error'])
                progress_bar.setValue(0)
                progress_bar.setFormat("Disabled")
                QApplication.processEvents()
                return

            # Initialize start time if not set
            if key not in self.start_times and progress > 0:
                self.start_times[key] = time.time()

            # Calculate speed and ETA
            if key in self.start_times and current_size > 0 and total_size > 0:
                elapsed_time = time.time() - self.start_times[key]
                if elapsed_time > 0:
                    speed = current_size / elapsed_time  # bytes per second
                    eta = (total_size - current_size) / speed if speed > 0 else 0
                    
                    # Format speed and ETA
                    speed_str = self.format_speed(speed)
                    eta_str = self.format_time(eta)
                    
                    # Update progress bar format
                    if progress == 100:
                        status_msg = "Completed"
                        progress_bar.setStyleSheet(self.STYLES['completed'])
                    elif status_msg.lower().startswith('error'):
                        progress_bar.setStyleSheet(self.STYLES['error'])
                    else:
                        status_msg = f"{status_msg} - {speed_str} - ETA: {eta_str}"
                        progress_bar.setStyleSheet(self.STYLES['uploading'])
            
            # Set progress and status
            progress_bar.setValue(progress)
            if progress == 100:
                progress_bar.setFormat("100% - Completed")
            else:
                progress_bar.setFormat(f"{progress}% - {status_msg}")
            
            # Force UI update
            QApplication.processEvents()

        except Exception as e:
            logging.error(f"Error updating progress: {str(e)}")

    def get_progress_bar(self, row: int, host_idx: int) -> Optional[QProgressBar]:
        """Get the progress bar for a specific host."""
        try:
            # Calculate actual column index based on base columns
            base_cols = 7  # Thread Title, Category, Thread ID, Rapidgator Links, RG Backup Link, Keeplinks Link, Password
            col = base_cols + host_idx

            # Get the container widget
            container = self.table.cellWidget(row, col)
            if container:
                # Get the progress bar from the container's layout
                layout = container.layout()
                if layout and layout.count() > 0:
                    return layout.itemAt(0).widget()

            return None

        except Exception as e:
            logging.error(f"Error getting progress bar: {str(e)}")
            return None

    @staticmethod
    def format_size(size):
        """Format size in bytes to human readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}GB"

    @staticmethod
    def format_speed(speed):
        """Format speed in bytes/second to human readable format."""
        speed = speed / 1024  # Convert to KB/s
        if speed < 1024:
            return f"{speed:.1f}KB/s"
        speed /= 1024  # Convert to MB/s
        if speed < 1024:
            return f"{speed:.1f}MB/s"
        speed /= 1024  # Convert to GB/s
        return f"{speed:.1f}GB/s"

    @staticmethod
    def format_time(seconds):
        """Format seconds to human readable time."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            seconds = int(seconds % 60)
            return f"{minutes}m {seconds}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"

    def mark_complete(self, row: int, host_idx: int, success_msg: str = "Upload Complete"):
        """Explicitly mark an upload as complete."""
        try:
            start_col = self.table.columnCount() - 5
            col = start_col + host_idx

            progress_bar = self.get_progress_bar(row, col)
            if progress_bar:
                progress_bar.setValue(100)
                progress_bar.setFormat(success_msg)
                progress_bar.setStyleSheet(self.STYLES['complete'])
                key = f"{row}:{host_idx}"
                self.upload_states[key] = 'complete'
                progress_bar.repaint()

        except Exception as e:
            logging.error(f"Error marking upload complete: {str(e)}")

    def mark_error(self, row: int, host_idx: int, error_msg: str):
        """Explicitly mark an upload as failed."""
        try:
            start_col = self.table.columnCount() - 5
            col = start_col + host_idx

            progress_bar = self.get_progress_bar(row, col)
            if progress_bar:
                progress_bar.setValue(0)
                progress_bar.setFormat(f"Error: {error_msg}")
                progress_bar.setStyleSheet(self.STYLES['error'])
                key = f"{row}:{host_idx}"
                self.upload_states[key] = 'error'
                progress_bar.repaint()

        except Exception as e:
            logging.error(f"Error marking upload error: {str(e)}")


    def create_progress_bar(self) -> QProgressBar:
        """Create a new progress bar with default styling."""
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_bar.setAlignment(Qt.AlignCenter)
        progress_bar.setStyleSheet(self.STYLES['default'])
        return progress_bar

    def update_performance_metrics(self, progress_key: str, current_progress: int):
        """Calculate and update performance metrics."""
        if progress_key in self.start_times:
            elapsed_time = time.time() - self.start_times[progress_key]
            if elapsed_time > 0:
                speed = current_progress / elapsed_time
                self.upload_speeds[progress_key].append(speed)

    def format_status_message(self, base_msg: str, progress_key: str, progress: int) -> str:
        """Format status message with performance information."""
        if progress_key in self.upload_speeds and self.upload_speeds[progress_key]:
            avg_speed = sum(self.upload_speeds[progress_key]) / len(self.upload_speeds[progress_key])
            estimated_remaining = (100 - progress) / avg_speed if avg_speed > 0 else 0

            return (f"{base_msg}\n"
                    f"Speed: {self.format_speed(avg_speed)}\n"
                    f"ETA: {self.format_time(estimated_remaining)}")
        return base_msg

    def is_upload_complete(self, row: int, host_idx: int) -> bool:
        """Check if a specific upload is marked as complete."""
        progress_key = f"{row}:{host_idx}"
        return self.completion_states.get(progress_key, False)

    def mark_upload_complete(self, row: int, host_idx: int, success_msg: str = "Complete"):
        """Mark an upload as complete and update its appearance."""
        self.update_progress(row, host_idx, 100, success_msg, complete=True)

    def reset_progress(self, row: int, host_idx: int):
        """Reset progress tracking for a specific upload."""
        progress_key = f"{row}:{host_idx}"
        if progress_key in self.progress_cache:
            del self.progress_cache[progress_key]
        if progress_key in self.start_times:
            del self.start_times[progress_key]
        if progress_key in self.upload_speeds:
            del self.upload_speeds[progress_key]
        if progress_key in self.error_counts:
            del self.error_counts[progress_key]
        if progress_key in self.completion_states:
            del self.completion_states[progress_key]