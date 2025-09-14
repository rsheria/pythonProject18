"""
StatusManager - The Single Source of Truth for All Status Operations
===================================================================

This is the central authority that eliminates all status widget chaos:
- ONE operation ID maps to ONE row (no more conflicts!)
- Real-time updates without batching delays
- Complete operation state in one place
- Thread-safe with minimal locking
- Automatic cleanup and memory management

Professional status tracking that just works!
"""

import uuid
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable, Any, List
from dataclasses import dataclass, field
from enum import Enum
from PyQt5.QtCore import QObject, pyqtSignal, QMutex, QTimer
import logging

# Import crash protection
from utils.crash_protection import (
    safe_execute as crash_safe_execute, resource_protection,
    ErrorSeverity, crash_logger
)

logger = logging.getLogger(__name__)


class OperationType(Enum):
    """Operation types for perfect categorization"""
    TRACKING = "TRACKING"
    POSTING = "POSTING"
    BACKUP = "BACKUP"
    REUPLOAD = "REUPLOAD"
    DOWNLOAD = "DOWNLOAD"
    UPLOAD_RAPIDGATOR = "UPLOAD_RAPIDGATOR"
    UPLOAD_KATFILE = "UPLOAD_KATFILE"
    UPLOAD_NITROFLARE = "UPLOAD_NITROFLARE"
    UPLOAD_DDOWNLOAD = "UPLOAD_DDOWNLOAD"
    UPLOAD_UPLOADY = "UPLOAD_UPLOADY"
    UPLOAD_MULTI = "UPLOAD_MULTI"
    EXTRACT = "EXTRACT"
    COMPRESS = "COMPRESS"


class OperationStatus(Enum):
    """Clear, unambiguous operation states"""
    PENDING = "PENDING"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class OperationState:
    """
    Complete operation state in ONE object - no more scattered data!
    This is the single source of truth for any operation.
    """
    operation_id: str
    section: str
    item: str
    operation_type: OperationType
    status: OperationStatus = OperationStatus.PENDING
    progress: float = 0.0  # 0.0 to 1.0
    details: str = ""
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None

    # File/URL information
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    download_url: Optional[str] = None
    upload_url: Optional[str] = None

    # Progress details
    bytes_transferred: int = 0
    total_bytes: int = 0
    transfer_speed: float = 0.0  # bytes/sec

    # Multi-host upload specifics
    current_host: int = 0
    total_hosts: int = 1
    host_results: Dict[str, str] = field(default_factory=dict)

    # Error information
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    # Worker information
    worker_id: Optional[str] = None
    thread_id: Optional[str] = None

    def update(self, **kwargs):
        """Thread-safe update of operation state"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning(f"Unknown operation state field: {key}")

    @property
    def duration(self) -> Optional[timedelta]:
        """Calculate operation duration"""
        if self.end_time:
            return self.end_time - self.start_time
        return datetime.now() - self.start_time

    @property
    def progress_percentage(self) -> int:
        """Get progress as percentage (0-100)"""
        return int(self.progress * 100)

    @property
    def is_active(self) -> bool:
        """Check if operation is currently active"""
        return self.status in [OperationStatus.INITIALIZING, OperationStatus.RUNNING]

    @property
    def is_finished(self) -> bool:
        """Check if operation is finished (completed/failed/cancelled)"""
        return self.status in [OperationStatus.COMPLETED, OperationStatus.FAILED, OperationStatus.CANCELLED]


class StatusManager(QObject):
    """
    🎯 THE SINGLE SOURCE OF TRUTH FOR ALL STATUS OPERATIONS

    This eliminates ALL the chaos by being the ONE central authority:
    - Creates operations with unique IDs
    - Manages ALL operation state
    - Emits real-time updates
    - Handles cleanup automatically
    - Thread-safe and bulletproof

    NO MORE:
    - Multiple row mappings
    - Empty rows
    - Scattered thread steps
    - Batching delays
    - Row conflicts
    """

    # Real-time signals for perfect UI synchronization
    operation_created = pyqtSignal(str, dict)  # operation_id, operation_data
    operation_updated = pyqtSignal(str, dict)  # operation_id, changes
    operation_completed = pyqtSignal(str, dict)  # operation_id, final_data
    operation_removed = pyqtSignal(str)  # operation_id

    def __init__(self):
        super().__init__()

        # THE single source of truth - ONE mapping system!
        self._operations: Dict[str, OperationState] = {}

        # Thread safety with minimal locking
        self._lock = QMutex()

        # Automatic cleanup timer - run more frequently to remove completed operations
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._cleanup_completed_operations)
        self._cleanup_timer.start(10000)  # Cleanup every 10 seconds for faster removal

        # Statistics tracking
        self._stats = {
            'total_created': 0,
            'total_completed': 0,
            'total_failed': 0,
            'active_operations': 0
        }

        logger.info("StatusManager initialized - Single Source of Truth ready!")

    @crash_safe_execute(max_retries=1, default_return=None, severity=ErrorSeverity.CRITICAL)
    def create_operation(
        self,
        section: str,
        item: str,
        operation_type: OperationType,
        **kwargs
    ) -> str:
        """
        Create a new operation with COMPLETE information from the start.

        NO MORE EMPTY ROWS! Every operation starts with full data.
        Returns unique operation_id that maps to exactly ONE row.
        """
        with resource_protection("StatusManager_CreateOperation", timeout_seconds=5.0):
            # Generate unique operation ID - NO CONFLICTS POSSIBLE!
            operation_id = str(uuid.uuid4())

            # Handle details parameter to avoid conflicts
            details = kwargs.pop('details', f"Initializing {operation_type.value.lower()}...")

            # Create complete operation state IMMEDIATELY
            operation = OperationState(
                operation_id=operation_id,
                section=section,
                item=item,
                operation_type=operation_type,
                status=OperationStatus.INITIALIZING,
                details=details,
                **kwargs
            )

            # Thread-safe storage
            self._lock.lock()
            try:
                self._operations[operation_id] = operation
                self._stats['total_created'] += 1
                self._stats['active_operations'] += 1
            finally:
                self._lock.unlock()

            # Emit creation signal with COMPLETE data
            operation_data = self._serialize_operation(operation)
            self.operation_created.emit(operation_id, operation_data)

            logger.info(f"Operation created: {operation_id} ({operation_type.value} - {section}:{item})")
            return operation_id

    @crash_safe_execute(max_retries=2, default_return=False, severity=ErrorSeverity.HIGH)
    def update_operation(self, operation_id: str, **changes) -> bool:
        """
        Update operation with real-time UI synchronization.

        Changes are applied immediately and UI is updated instantly.
        NO MORE BATCHING DELAYS!
        """
        with resource_protection("StatusManager_UpdateOperation", timeout_seconds=2.0):
            self._lock.lock()
            try:
                if operation_id not in self._operations:
                    logger.warning(f"Attempted to update unknown operation: {operation_id}")
                    return False

                operation = self._operations[operation_id]
                old_status = operation.status

                # Convert status strings to enum before applying changes
                if 'status' in changes:
                    new_status = changes['status']
                    if not isinstance(new_status, OperationStatus):
                        try:
                            new_status = OperationStatus(new_status)
                        except Exception:
                            logger.warning(f"Unknown status value: {new_status}")
                            new_status = operation.status
                    changes['status'] = new_status

                # Normalise progress values and auto-promote status
                if 'progress' in changes:
                    progress = changes['progress']
                    # Some callers still send 0-100 values - normalise to 0-1
                    if isinstance(progress, (int, float)) and progress > 1:
                        progress = progress / 100.0
                    progress = max(0.0, min(1.0, float(progress)))
                    changes['progress'] = progress

                    # Determine the current status considering incoming changes
                    current_status = changes.get('status', operation.status)

                    # If progress is reported but status is still initializing,
                    # automatically switch to RUNNING for a proper stage flow
                    if current_status in (OperationStatus.PENDING, OperationStatus.INITIALIZING) and progress > 0:
                        changes['status'] = OperationStatus.RUNNING

                    # If progress reaches 100% and no explicit status provided,
                    # mark the operation as completed to avoid lingering RUNNING state
                    if progress >= 1.0 and 'status' not in changes and operation.status == OperationStatus.RUNNING:
                        changes['status'] = OperationStatus.COMPLETED

                # Apply changes to operation state
                operation.update(**changes)

                # Handle status transitions
                if 'status' in changes:
                    new_status = changes['status']

                    # Update statistics on status changes
                    if old_status in [OperationStatus.INITIALIZING, OperationStatus.RUNNING] and new_status in [OperationStatus.COMPLETED, OperationStatus.FAILED, OperationStatus.CANCELLED]:
                        self._stats['active_operations'] -= 1
                        if new_status == OperationStatus.COMPLETED:
                            self._stats['total_completed'] += 1
                            operation.end_time = datetime.now()
                        elif new_status == OperationStatus.FAILED:
                            self._stats['total_failed'] += 1
                            operation.end_time = datetime.now()

            finally:
                self._lock.unlock()

            # Emit update signal with changes IMMEDIATELY
            self.operation_updated.emit(operation_id, changes)

            # Check for completion
            if operation.is_finished:
                self._handle_operation_completion(operation_id)

            return True

    @crash_safe_execute(max_retries=1, default_return=None, severity=ErrorSeverity.MEDIUM)
    def get_operation(self, operation_id: str) -> Optional[OperationState]:
        """Get complete operation state - thread-safe"""
        self._lock.lock()
        try:
            return self._operations.get(operation_id)
        finally:
            self._lock.unlock()

    @crash_safe_execute(max_retries=1, default_return=[], severity=ErrorSeverity.LOW)
    def get_all_operations(self) -> List[OperationState]:
        """Get all operations - thread-safe"""
        self._lock.lock()
        try:
            return list(self._operations.values())
        finally:
            self._lock.unlock()

    @crash_safe_execute(max_retries=1, default_return=[], severity=ErrorSeverity.LOW)
    def get_active_operations(self) -> List[OperationState]:
        """Get only active operations"""
        self._lock.lock()
        try:
            return [op for op in self._operations.values() if op.is_active]
        finally:
            self._lock.unlock()

    def _handle_operation_completion(self, operation_id: str):
        """Handle operation completion with proper cleanup timing"""
        operation = self.get_operation(operation_id)
        if not operation:
            return

        # Emit completion signal
        operation_data = self._serialize_operation(operation)
        self.operation_completed.emit(operation_id, operation_data)

        logger.info(f"Operation completed: {operation_id} ({operation.operation_type.value}) - "
                   f"Status: {operation.status.value}, Duration: {operation.duration}")

    def _cleanup_completed_operations(self):
        """Automatic cleanup of old completed operations"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=2)  # Keep completed ops for 2 minutes
            operations_to_remove = []

            self._lock.lock()
            try:
                for op_id, operation in self._operations.items():
                    if (operation.is_finished and
                        operation.end_time and
                        operation.end_time < cutoff_time):
                        operations_to_remove.append(op_id)
            finally:
                self._lock.unlock()

            # Remove old operations
            for op_id in operations_to_remove:
                self.remove_operation(op_id)

            if operations_to_remove:
                logger.info(f"Cleaned up {len(operations_to_remove)} completed operations")

        except Exception as e:
            crash_logger.error(f"Error during operation cleanup: {e}")

    @crash_safe_execute(max_retries=1, default_return=False, severity=ErrorSeverity.MEDIUM)
    def remove_operation(self, operation_id: str) -> bool:
        """Remove operation and emit cleanup signal"""
        self._lock.lock()
        try:
            if operation_id in self._operations:
                operation = self._operations[operation_id]
                if operation.is_active:
                    self._stats['active_operations'] -= 1
                del self._operations[operation_id]

                # Emit removal signal for UI cleanup
                self.operation_removed.emit(operation_id)
                logger.debug(f"Operation removed: {operation_id}")
                return True
            return False
        finally:
            self._lock.unlock()

    def _serialize_operation(self, operation: OperationState) -> dict:
        """Convert operation to dictionary for signals"""
        return {
            'operation_id': operation.operation_id,
            'section': operation.section,
            'item': operation.item,
            'operation_type': operation.operation_type.value,
            'status': operation.status.value,
            'progress': operation.progress,
            'progress_percentage': operation.progress_percentage,
            'details': operation.details,
            'start_time': operation.start_time.isoformat(),
            'end_time': operation.end_time.isoformat() if operation.end_time else None,
            'bytes_transferred': operation.bytes_transferred,
            'total_bytes': operation.total_bytes,
            'transfer_speed': operation.transfer_speed,
            'current_host': operation.current_host,
            'total_hosts': operation.total_hosts,
            'error_message': operation.error_message,
            'retry_count': operation.retry_count,
            'duration_seconds': operation.duration.total_seconds() if operation.duration else 0,
            'is_active': operation.is_active,
            'is_finished': operation.is_finished
        }

    def get_statistics(self) -> dict:
        """Get current statistics"""
        self._lock.lock()
        try:
            return {
                **self._stats,
                'current_operations': len(self._operations)
            }
        finally:
            self._lock.unlock()

    def shutdown(self):
        """Clean shutdown of StatusManager"""
        logger.info("StatusManager shutting down...")
        self._cleanup_timer.stop()

        # Final cleanup
        self._lock.lock()
        try:
            active_count = len([op for op in self._operations.values() if op.is_active])
            if active_count > 0:
                logger.warning(f"Shutting down with {active_count} active operations")
            self._operations.clear()
        finally:
            self._lock.unlock()

        logger.info("StatusManager shutdown complete")


# Global StatusManager instance - THE single source of truth
_status_manager_instance: Optional[StatusManager] = None
_manager_lock = threading.Lock()


def get_status_manager() -> StatusManager:
    """Get the global StatusManager instance (singleton pattern)"""
    global _status_manager_instance

    if _status_manager_instance is None:
        with _manager_lock:
            if _status_manager_instance is None:
                _status_manager_instance = StatusManager()

    return _status_manager_instance


def shutdown_status_manager():
    """Shutdown the global StatusManager"""
    global _status_manager_instance

    if _status_manager_instance is not None:
        with _manager_lock:
            if _status_manager_instance is not None:
                _status_manager_instance.shutdown()
                _status_manager_instance = None