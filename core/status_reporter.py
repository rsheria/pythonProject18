"""
StatusReporter - Direct Worker-to-Status Communication
=====================================================

This eliminates the laggy Orchestrator middle-man and provides:
- INSTANT status updates from workers to UI
- NO more batching delays
- Direct real-time progress reporting
- Bulletproof error handling
- Thread-safe from any worker

Workers just call simple methods and the UI updates INSTANTLY!
"""

import logging
from typing import Optional, Any, Dict
from datetime import datetime
from PyQt5.QtCore import QObject

# Import our perfect status manager
from core.status_manager import get_status_manager, OperationType, OperationStatus
from utils.crash_protection import (
    safe_execute as crash_safe_execute, resource_protection,
    ErrorSeverity, crash_logger
)

logger = logging.getLogger(__name__)


class StatusReporter:
    """
    🎯 DIRECT WORKER-TO-STATUS COMMUNICATION

    This is what workers use to report status directly to the UI.
    NO MORE DELAYS, NO MORE BATCHING, NO MORE LAG!

    Workers just call:
    - reporter.start_download()
    - reporter.update_progress(0.5)
    - reporter.complete_operation()

    And the UI updates INSTANTLY with perfect synchronization!
    """

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or "unknown_worker"
        self.status_manager = get_status_manager()
        self.current_operation_id: Optional[str] = None

        logger.debug(f"StatusReporter initialized for worker: {self.worker_id}")

    # ==========================================
    # OPERATION LIFECYCLE METHODS
    # ==========================================

    @crash_safe_execute(max_retries=2, default_return=None, severity=ErrorSeverity.CRITICAL)
    def start_download(
        self,
        section: str,
        item: str,
        download_url: str,
        target_path: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """
        Start a download operation with INSTANT UI feedback.
        Returns operation_id for tracking.
        """
        with resource_protection("StatusReporter_StartDownload", timeout_seconds=2.0):
            # Ensure we don't have duplicate details
            # Auto-detect operation type based on section
            if section.lower() == "tracking":
                operation_type = OperationType.TRACKING
            else:
                operation_type = OperationType.DOWNLOAD

            operation_kwargs = {
                'section': section,
                'item': item,
                'operation_type': operation_type,
                'download_url': download_url,
                'target_path': target_path,
                'worker_id': self.worker_id,
                **kwargs
            }
            # Set default details if not provided
            if 'details' not in operation_kwargs:
                operation_kwargs['details'] = "Preparing download..."

            operation_id = self.status_manager.create_operation(**operation_kwargs)

            self.current_operation_id = operation_id
            logger.info(f"Download started: {section}:{item} -> {operation_id}")
            return operation_id

    @crash_safe_execute(max_retries=2, default_return=None, severity=ErrorSeverity.CRITICAL)
    def start_upload(
        self,
        section: str,
        item: str,
        operation_type: OperationType,
        source_path: str,
        **kwargs
    ) -> Optional[str]:
        """
        Start an upload operation with INSTANT UI feedback.
        """
        with resource_protection("StatusReporter_StartUpload", timeout_seconds=2.0):
            operation_id = self.status_manager.create_operation(
                section=section,
                item=item,
                operation_type=operation_type,
                source_path=source_path,
                worker_id=self.worker_id,
                details=f"Preparing {operation_type.value.lower()}...",
                **kwargs
            )

            self.current_operation_id = operation_id
            logger.info(f"Upload started: {section}:{item} ({operation_type.value}) -> {operation_id}")
            return operation_id

    @crash_safe_execute(max_retries=2, default_return=None, severity=ErrorSeverity.CRITICAL)
    def start_file_operation(
        self,
        section: str,
        item: str,
        operation_type: OperationType,
        source_path: Optional[str] = None,
        target_path: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """
        Start a file operation (extract, compress) with INSTANT UI feedback.
        """
        with resource_protection("StatusReporter_StartFileOperation", timeout_seconds=2.0):
            operation_id = self.status_manager.create_operation(
                section=section,
                item=item,
                operation_type=operation_type,
                source_path=source_path,
                target_path=target_path,
                worker_id=self.worker_id,
                details=f"Preparing {operation_type.value.lower()}...",
                **kwargs
            )

            self.current_operation_id = operation_id
            logger.info(f"File operation started: {section}:{item} ({operation_type.value}) -> {operation_id}")
            return operation_id

    # ==========================================
    # REAL-TIME PROGRESS UPDATES
    # ==========================================

    @crash_safe_execute(max_retries=3, default_return=False, severity=ErrorSeverity.HIGH)
    def update_progress(
        self,
        progress: float,
        details: Optional[str] = None,
        operation_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Update progress with INSTANT UI synchronization.
        Progress: 0.0 to 1.0
        UI updates IMMEDIATELY - no delays!
        """
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            logger.warning("No operation ID available for progress update")
            return False

        # Prepare update data
        update_data = {
            'progress': max(0.0, min(1.0, progress)),  # Clamp to valid range
            'status': OperationStatus.RUNNING,
            **kwargs
        }

        if details:
            update_data['details'] = details

        # INSTANT update - no batching!
        return self.status_manager.update_operation(target_op_id, **update_data)

    @crash_safe_execute(max_retries=3, default_return=False, severity=ErrorSeverity.HIGH)
    def update_transfer_progress(
        self,
        bytes_transferred: int,
        total_bytes: int,
        transfer_speed: Optional[float] = None,
        details: Optional[str] = None,
        operation_id: Optional[str] = None
    ) -> bool:
        """
        Update transfer progress with speed and ETA calculations.
        """
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            return False

        # Calculate progress
        progress = bytes_transferred / total_bytes if total_bytes > 0 else 0.0

        # Build update data
        update_data = {
            'progress': progress,
            'bytes_transferred': bytes_transferred,
            'total_bytes': total_bytes,
            'status': OperationStatus.RUNNING
        }

        if transfer_speed is not None:
            update_data['transfer_speed'] = transfer_speed

        if details:
            update_data['details'] = details
        else:
            # Generate smart details
            if total_bytes > 0:
                percent = int(progress * 100)
                mb_transferred = bytes_transferred / (1024 * 1024)
                mb_total = total_bytes / (1024 * 1024)

                if transfer_speed and transfer_speed > 0:
                    remaining_bytes = total_bytes - bytes_transferred
                    eta_seconds = remaining_bytes / transfer_speed
                    eta_mins = int(eta_seconds / 60)
                    update_data['details'] = f"{percent}% ({mb_transferred:.1f}/{mb_total:.1f} MB) - ETA: {eta_mins}m"
                else:
                    update_data['details'] = f"{percent}% ({mb_transferred:.1f}/{mb_total:.1f} MB)"

        return self.status_manager.update_operation(target_op_id, **update_data)

    # ==========================================
    # STATUS UPDATES
    # ==========================================

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.HIGH)
    def update_status(
        self,
        status: OperationStatus,
        details: Optional[str] = None,
        operation_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Update operation status with INSTANT UI feedback.
        """
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            return False

        update_data = {'status': status, **kwargs}
        if details:
            update_data['details'] = details

        return self.status_manager.update_operation(target_op_id, **update_data)

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.MEDIUM)
    def set_initializing(self, details: str = "Initializing...", operation_id: Optional[str] = None) -> bool:
        """Set operation to initializing state"""
        return self.update_status(OperationStatus.INITIALIZING, details, operation_id)

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.MEDIUM)
    def set_running(self, details: str = "Running...", operation_id: Optional[str] = None) -> bool:
        """Set operation to running state"""
        return self.update_status(OperationStatus.RUNNING, details, operation_id)

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.MEDIUM)
    def set_paused(self, details: str = "Paused", operation_id: Optional[str] = None) -> bool:
        """Set operation to paused state"""
        return self.update_status(OperationStatus.PAUSED, details, operation_id)

    # ==========================================
    # COMPLETION HANDLING
    # ==========================================

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.CRITICAL)
    def complete_operation(
        self,
        result_url: Optional[str] = None,
        details: str = "Completed successfully!",
        operation_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Mark operation as completed with INSTANT UI update.
        """
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            return False

        update_data = {
            'status': OperationStatus.COMPLETED,
            'progress': 1.0,
            'details': details,
            **kwargs
        }

        if result_url:
            # Determine if it's upload or download result
            operation = self.status_manager.get_operation(target_op_id)
            if operation and operation.operation_type == OperationType.DOWNLOAD:
                update_data['target_path'] = result_url
            else:
                update_data['upload_url'] = result_url

        success = self.status_manager.update_operation(target_op_id, **update_data)

        if success and target_op_id == self.current_operation_id:
            self.current_operation_id = None  # Clear current operation

        logger.info(f"Operation completed: {target_op_id}")
        return success

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.HIGH)
    def fail_operation(
        self,
        error_message: str,
        details: Optional[str] = None,
        operation_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Mark operation as failed with error details.
        """
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            return False

        update_data = {
            'status': OperationStatus.FAILED,
            'error_message': error_message,
            'details': details or f"Failed: {error_message}",
            **kwargs
        }

        success = self.status_manager.update_operation(target_op_id, **update_data)

        if success and target_op_id == self.current_operation_id:
            self.current_operation_id = None

        logger.error(f"Operation failed: {target_op_id} - {error_message}")
        return success

    @crash_safe_execute(max_retries=1, default_return=False, severity=ErrorSeverity.MEDIUM)
    def cancel_operation(
        self,
        details: str = "Cancelled by user",
        operation_id: Optional[str] = None
    ) -> bool:
        """
        Cancel the operation.
        """
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            return False

        success = self.status_manager.update_operation(
            target_op_id,
            status=OperationStatus.CANCELLED,
            details=details
        )

        if success and target_op_id == self.current_operation_id:
            self.current_operation_id = None

        logger.info(f"Operation cancelled: {target_op_id}")
        return success

    # ==========================================
    # MULTI-HOST UPLOAD SUPPORT
    # ==========================================

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.HIGH)
    def start_multi_upload(
        self,
        section: str,
        item: str,
        source_path: str,
        hosts: list,
        **kwargs
    ) -> Optional[str]:
        """
        Start multi-host upload with clear progress tracking.
        """
        operation_id = self.status_manager.create_operation(
            section=section,
            item=item,
            operation_type=OperationType.UPLOAD_MULTI,
            source_path=source_path,
            worker_id=self.worker_id,
            total_hosts=len(hosts),
            current_host=0,
            details=f"Starting upload to {len(hosts)} hosts...",
            **kwargs
        )

        self.current_operation_id = operation_id
        return operation_id

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.HIGH)
    def update_multi_upload_progress(
        self,
        host_index: int,
        host_name: str,
        host_progress: float,
        host_details: Optional[str] = None,
        operation_id: Optional[str] = None
    ) -> bool:
        """
        Update progress for multi-host upload.
        """
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            return False

        # Get operation to calculate overall progress
        operation = self.status_manager.get_operation(target_op_id)
        if not operation:
            return False

        # Update host results
        host_results = operation.host_results.copy()
        host_results[host_name] = f"{int(host_progress * 100)}%"

        # Calculate overall progress
        total_hosts = operation.total_hosts
        overall_progress = (host_index + host_progress) / total_hosts

        # Build details
        if host_details:
            details = f"Host {host_index + 1}/{total_hosts} ({host_name}): {host_details}"
        else:
            details = f"Host {host_index + 1}/{total_hosts} ({host_name}): {int(host_progress * 100)}%"

        return self.status_manager.update_operation(
            target_op_id,
            progress=overall_progress,
            current_host=host_index + 1,
            host_results=host_results,
            details=details
        )

    # ==========================================
    # UTILITY METHODS
    # ==========================================

    def get_current_operation_id(self) -> Optional[str]:
        """Get the current operation ID"""
        return self.current_operation_id

    def has_active_operation(self) -> bool:
        """Check if this reporter has an active operation"""
        if not self.current_operation_id:
            return False

        operation = self.status_manager.get_operation(self.current_operation_id)
        return operation and operation.is_active if operation else False

    @crash_safe_execute(max_retries=1, default_return={}, severity=ErrorSeverity.LOW)
    def get_operation_stats(self, operation_id: Optional[str] = None) -> dict:
        """Get operation statistics"""
        target_op_id = operation_id or self.current_operation_id
        if not target_op_id:
            return {}

        operation = self.status_manager.get_operation(target_op_id)
        if not operation:
            return {}

        return {
            'operation_id': operation.operation_id,
            'progress_percentage': operation.progress_percentage,
            'duration_seconds': operation.duration.total_seconds() if operation.duration else 0,
            'is_active': operation.is_active,
            'is_finished': operation.is_finished,
            'status': operation.status.value
        }

    # ==========================================
    # SPECIALIZED OPERATION METHODS
    # ==========================================

    @crash_safe_execute(max_retries=2, default_return=None, severity=ErrorSeverity.CRITICAL)
    def start_tracking(
        self,
        section: str,
        item: str,
        **kwargs
    ) -> Optional[str]:
        """Start a tracking operation with proper operation type"""
        operation_kwargs = {
            'section': section,
            'item': item,
            'operation_type': OperationType.TRACKING,
            'worker_id': self.worker_id,
            'details': "Starting tracking...",
            **kwargs
        }

        operation_id = self.status_manager.create_operation(**operation_kwargs)
        self.current_operation_id = operation_id
        logger.info(f"Tracking started: {section}:{item} -> {operation_id}")
        return operation_id

    @crash_safe_execute(max_retries=2, default_return=None, severity=ErrorSeverity.CRITICAL)
    def start_posting(
        self,
        section: str,
        item: str,
        **kwargs
    ) -> Optional[str]:
        """Start a posting operation with proper operation type"""
        operation_kwargs = {
            'section': section,
            'item': item,
            'operation_type': OperationType.POSTING,
            'worker_id': self.worker_id,
            'details': "Starting posting...",
            **kwargs
        }

        operation_id = self.status_manager.create_operation(**operation_kwargs)
        self.current_operation_id = operation_id
        logger.info(f"Posting started: {section}:{item} -> {operation_id}")
        return operation_id

    @crash_safe_execute(max_retries=2, default_return=None, severity=ErrorSeverity.CRITICAL)
    def start_backup(
        self,
        section: str,
        item: str,
        **kwargs
    ) -> Optional[str]:
        """Start a backup operation with proper operation type"""
        operation_kwargs = {
            'section': section,
            'item': item,
            'operation_type': OperationType.BACKUP,
            'worker_id': self.worker_id,
            'details': "Starting backup...",
            **kwargs
        }

        operation_id = self.status_manager.create_operation(**operation_kwargs)
        self.current_operation_id = operation_id
        logger.info(f"Backup started: {section}:{item} -> {operation_id}")
        return operation_id

    @crash_safe_execute(max_retries=2, default_return=None, severity=ErrorSeverity.CRITICAL)
    def start_reupload(
        self,
        section: str,
        item: str,
        **kwargs
    ) -> Optional[str]:
        """Start a reupload operation with proper operation type"""
        operation_kwargs = {
            'section': section,
            'item': item,
            'operation_type': OperationType.REUPLOAD,
            'worker_id': self.worker_id,
            'details': "Starting reupload...",
            **kwargs
        }

        operation_id = self.status_manager.create_operation(**operation_kwargs)
        self.current_operation_id = operation_id
        logger.info(f"Reupload started: {section}:{item} -> {operation_id}")
        return operation_id


# ==========================================
# CONVENIENCE FUNCTIONS FOR WORKERS
# ==========================================

def create_download_reporter(worker_id: str = None) -> StatusReporter:
    """Create a reporter specifically for download operations"""
    return StatusReporter(worker_id or "download_worker")


def create_upload_reporter(worker_id: str = None) -> StatusReporter:
    """Create a reporter specifically for upload operations"""
    return StatusReporter(worker_id or "upload_worker")


def create_file_reporter(worker_id: str = None) -> StatusReporter:
    """Create a reporter specifically for file operations"""
    return StatusReporter(worker_id or "file_worker")