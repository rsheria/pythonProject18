"""
StatusIntegration - Seamless Integration with Existing Workers
============================================================

This provides easy integration helpers to transform existing workers
to use our perfect status system without breaking existing code.

Just replace old status calls with our magical new ones!
"""

import logging
from typing import Optional, Callable, Any
from functools import wraps
from datetime import datetime

# Import our perfect system
from core.status_reporter import StatusReporter, create_download_reporter, create_upload_reporter
from core.status_manager import OperationType, OperationStatus
from utils.crash_protection import (
    safe_execute as crash_safe_execute, ErrorSeverity, crash_logger
)

logger = logging.getLogger(__name__)


class WorkerStatusMixin:
    """
    Mixin class to add perfect status reporting to any worker.

    Just inherit from this class and get instant magical status updates!
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_reporter: Optional[StatusReporter] = None
        self.current_section: Optional[str] = None
        self.current_item: Optional[str] = None

    def init_status_reporter(self, worker_type: str = "generic"):
        """Initialize the status reporter for this worker"""
        worker_id = f"{worker_type}_{id(self)}"
        self.status_reporter = StatusReporter(worker_id)
        logger.debug(f"Status reporter initialized for worker: {worker_id}")

    # Convenience methods for easy integration
    def start_download_status(self, section: str, item: str, url: str, **kwargs) -> Optional[str]:
        """Start download status tracking"""
        if not self.status_reporter:
            self.init_status_reporter("download")

        self.current_section = section
        self.current_item = item
        return self.status_reporter.start_download(section, item, url, **kwargs)

    def start_upload_status(self, section: str, item: str, upload_type: OperationType, path: str, **kwargs) -> Optional[str]:
        """Start upload status tracking"""
        if not self.status_reporter:
            self.init_status_reporter("upload")

        self.current_section = section
        self.current_item = item
        return self.status_reporter.start_upload(section, item, upload_type, path, **kwargs)

    def update_progress_status(self, progress: float, details: str = None, **kwargs):
        """Update progress with real-time display"""
        if self.status_reporter:
            return self.status_reporter.update_progress(progress, details, **kwargs)

    def complete_status(self, result: str = None, details: str = None, **kwargs):
        """Complete the current operation"""
        if self.status_reporter:
            return self.status_reporter.complete_operation(result, details or "Completed successfully!", **kwargs)

    def fail_status(self, error: str, details: str = None, **kwargs):
        """Fail the current operation"""
        if self.status_reporter:
            return self.status_reporter.fail_operation(error, details, **kwargs)


def with_status_tracking(
    operation_type: OperationType,
    get_section: Callable = None,
    get_item: Callable = None,
    get_details: Callable = None
):
    """
    Decorator to automatically add status tracking to any function.

    Example:
    @with_status_tracking(
        OperationType.DOWNLOAD,
        get_section=lambda self, url: self.current_section,
        get_item=lambda self, url: os.path.basename(url)
    )
    def download_file(self, url):
        # Your existing download logic
        pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Initialize reporter if needed
            if not hasattr(self, 'status_reporter') or not self.status_reporter:
                worker_type = operation_type.value.lower()
                self.status_reporter = StatusReporter(f"{worker_type}_{id(self)}")

            # Extract operation details
            try:
                section = get_section(self, *args) if get_section else getattr(self, 'current_section', 'Unknown')
                item = get_item(self, *args) if get_item else getattr(self, 'current_item', 'Unknown')
                details = get_details(self, *args) if get_details else f"Starting {operation_type.value.lower()}..."

                # Start operation
                if operation_type == OperationType.DOWNLOAD:
                    url = args[0] if args else kwargs.get('url', '')
                    operation_id = self.status_reporter.start_download(section, item, url)
                else:
                    path = args[0] if args else kwargs.get('file_path', '')
                    operation_id = self.status_reporter.start_upload(section, item, operation_type, path)

                # Execute original function
                result = func(self, *args, **kwargs)

                # Handle result
                if result:
                    self.status_reporter.complete_operation(str(result))
                else:
                    self.status_reporter.fail_operation("Operation returned no result")

                return result

            except Exception as e:
                # Report failure
                if hasattr(self, 'status_reporter') and self.status_reporter:
                    self.status_reporter.fail_operation(str(e))
                raise

        return wrapper
    return decorator


# Legacy compatibility functions for easy migration
class LegacyStatusBridge:
    """
    Bridge to convert old status widget calls to our new perfect system.
    This allows gradual migration without breaking existing code.
    """

    def __init__(self):
        self.operation_mapping = {}  # old_key -> operation_id
        self.default_reporter = StatusReporter("legacy_bridge")

    @crash_safe_execute(max_retries=1, default_return=None, severity=ErrorSeverity.MEDIUM)
    def enqueue_status(self, operation_status_obj):
        """
        Convert old OperationStatus objects to new system.
        This maintains compatibility with existing worker code.
        """
        try:
            # Extract information from old status object
            section = getattr(operation_status_obj, 'section', 'Unknown')
            item = getattr(operation_status_obj, 'item', 'Unknown')
            op_type_str = getattr(operation_status_obj, 'op_type', 'UNKNOWN')
            progress = getattr(operation_status_obj, 'progress', 0.0)
            details = getattr(operation_status_obj, 'details', '')
            thread_id = getattr(operation_status_obj, 'thread_id', None)

            # Convert operation type
            op_type_map = {
                'DOWNLOAD': OperationType.DOWNLOAD,
                'UPLOAD': OperationType.UPLOAD_RAPIDGATOR,  # Default to Rapidgator
                'EXTRACT': OperationType.EXTRACT,
                'COMPRESS': OperationType.COMPRESS
            }
            operation_type = op_type_map.get(op_type_str, OperationType.DOWNLOAD)

            # Create unique key for mapping
            old_key = f"{section}:{item}:{op_type_str}"

            # Check if this is a new operation
            if old_key not in self.operation_mapping:
                # Create new operation
                if operation_type == OperationType.DOWNLOAD:
                    operation_id = self.default_reporter.start_download(
                        section, item, '', details=details
                    )
                else:
                    operation_id = self.default_reporter.start_upload(
                        section, item, operation_type, '', details=details
                    )
                self.operation_mapping[old_key] = operation_id
            else:
                operation_id = self.operation_mapping[old_key]

            # Update progress
            if progress > 0:
                self.default_reporter.update_progress(
                    progress / 100.0 if progress > 1 else progress,
                    details=details,
                    operation_id=operation_id
                )

            return True

        except Exception as e:
            crash_logger.error(f"Legacy status bridge error: {e}")
            return False

    @crash_safe_execute(max_retries=1, default_return=None, severity=ErrorSeverity.LOW)
    def handle_status(self, operation_status_obj):
        """Alternative entry point for immediate processing"""
        return self.enqueue_status(operation_status_obj)


# Global instances for easy access
_legacy_bridge = None
_global_reporters = {}

def get_legacy_bridge() -> LegacyStatusBridge:
    """Get global legacy bridge instance"""
    global _legacy_bridge
    if _legacy_bridge is None:
        _legacy_bridge = LegacyStatusBridge()
    return _legacy_bridge


def get_worker_reporter(worker_id: str, worker_type: str = "generic") -> StatusReporter:
    """Get or create a status reporter for a specific worker"""
    global _global_reporters

    if worker_id not in _global_reporters:
        _global_reporters[worker_id] = StatusReporter(f"{worker_type}_{worker_id}")

    return _global_reporters[worker_id]


# Convenience functions for quick integration
def report_download_start(section: str, item: str, url: str, worker_id: str = "default") -> Optional[str]:
    """Quick download start reporting"""
    reporter = get_worker_reporter(worker_id, "download")
    return reporter.start_download(section, item, url)

def report_upload_start(section: str, item: str, operation_type: OperationType,
                       path: str, worker_id: str = "default") -> Optional[str]:
    """Quick upload start reporting"""
    reporter = get_worker_reporter(worker_id, "upload")
    return reporter.start_upload(section, item, operation_type, path)

def report_progress(progress: float, details: str = None, worker_id: str = "default") -> bool:
    """Quick progress reporting"""
    reporter = get_worker_reporter(worker_id)
    return reporter.update_progress(progress, details)

def report_completion(result: str = None, details: str = None, worker_id: str = "default") -> bool:
    """Quick completion reporting"""
    reporter = get_worker_reporter(worker_id)
    return reporter.complete_operation(result, details)

def report_failure(error: str, details: str = None, worker_id: str = "default") -> bool:
    """Quick failure reporting"""
    reporter = get_worker_reporter(worker_id)
    return reporter.fail_operation(error, details)


# Monkey patch helper for seamless integration
def monkey_patch_status_widget(status_widget_class):
    """
    Monkey patch existing StatusWidget to use our perfect system.
    This allows zero-code-change integration!
    """
    original_enqueue = getattr(status_widget_class, 'enqueue_status', None)
    original_handle = getattr(status_widget_class, 'handle_status', None)

    bridge = get_legacy_bridge()

    if original_enqueue:
        status_widget_class.enqueue_status = lambda self, status: bridge.enqueue_status(status)

    if original_handle:
        status_widget_class.handle_status = lambda self, status: bridge.handle_status(status)

    logger.info(f"Monkey patched {status_widget_class.__name__} for seamless integration")


# Context manager for automatic status tracking
class StatusContext:
    """
    Context manager for automatic status tracking.

    Example:
    with StatusContext(OperationType.DOWNLOAD, section, item, url) as ctx:
        # Do your work here
        ctx.update_progress(0.5, "Halfway done...")
        result = do_download()
        ctx.set_result(result)
    """

    def __init__(self, operation_type: OperationType, section: str, item: str,
                 path_or_url: str, worker_id: str = "context"):
        self.operation_type = operation_type
        self.section = section
        self.item = item
        self.path_or_url = path_or_url
        self.worker_id = worker_id
        self.reporter = get_worker_reporter(worker_id)
        self.operation_id = None
        self.result = None
        self.error = None

    def __enter__(self):
        """Start the operation"""
        if self.operation_type == OperationType.DOWNLOAD:
            self.operation_id = self.reporter.start_download(
                self.section, self.item, self.path_or_url
            )
        else:
            self.operation_id = self.reporter.start_upload(
                self.section, self.item, self.operation_type, self.path_or_url
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Complete or fail the operation"""
        if exc_type is not None:
            # Exception occurred
            self.reporter.fail_operation(str(exc_val), operation_id=self.operation_id)
        elif self.error:
            # Manual error
            self.reporter.fail_operation(self.error, operation_id=self.operation_id)
        else:
            # Success
            details = f"Completed successfully!"
            if self.result:
                details += f" Result: {self.result}"
            self.reporter.complete_operation(self.result, details, operation_id=self.operation_id)

        return False  # Don't suppress exceptions

    def update_progress(self, progress: float, details: str = None):
        """Update operation progress"""
        self.reporter.update_progress(progress, details, operation_id=self.operation_id)

    def set_result(self, result: str):
        """Set operation result"""
        self.result = result

    def set_error(self, error: str):
        """Set operation error"""
        self.error = error

    def update_details(self, details: str):
        """Update operation details"""
        self.reporter.update_status(
            OperationStatus.RUNNING, details, operation_id=self.operation_id
        )