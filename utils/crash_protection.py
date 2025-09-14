"""
Crash Protection Utilities - Professional Error Handling Framework
================================================================

This module provides bulletproof error handling, resource management,
and crash prevention utilities for the ForumBot application.

Author: Professional Python Developer
Purpose: Eliminate crashes and ensure smooth operation
"""

import logging
import functools
import threading
import time
import traceback
import psutil
import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union, Tuple
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import sys


class ErrorSeverity(Enum):
    """Error severity levels for categorization."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class ErrorContext:
    """Context information for error tracking."""
    function_name: str
    file_name: str
    line_number: int
    severity: ErrorSeverity
    error_type: str
    error_message: str
    timestamp: float
    thread_id: int
    memory_usage_mb: float
    retry_count: int = 0
    additional_info: Dict[str, Any] = None


class CrashProtectionLogger:
    """Enhanced logging system for crash prevention."""

    def __init__(self):
        self.error_history: List[ErrorContext] = []
        self.max_history = 1000
        self._lock = threading.RLock()
        self._setup_logger()

    def _setup_logger(self):
        """Setup enhanced logger with proper formatting."""
        self.logger = logging.getLogger('CrashProtection')
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(thread)8d | %(name)s:%(lineno)d | %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def log_error(self, error_context: ErrorContext):
        """Log error with context tracking."""
        with self._lock:
            # Add to history
            self.error_history.append(error_context)
            if len(self.error_history) > self.max_history:
                self.error_history.pop(0)

            # Log based on severity
            message = f"[{error_context.severity.value}] {error_context.error_type}: {error_context.error_message}"
            if error_context.additional_info:
                message += f" | Context: {error_context.additional_info}"

            if error_context.severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]:
                self.logger.error(message)
            elif error_context.severity == ErrorSeverity.MEDIUM:
                self.logger.warning(message)
            else:
                self.logger.info(message)

    def get_error_summary(self) -> Dict[str, int]:
        """Get summary of recent errors."""
        with self._lock:
            summary = {}
            for error in self.error_history[-100:]:  # Last 100 errors
                key = f"{error.severity.value}_{error.error_type}"
                summary[key] = summary.get(key, 0) + 1
            return summary


# Global crash protection logger
crash_logger = CrashProtectionLogger()


def safe_execute(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    expected_exceptions: Tuple = (Exception,),
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    default_return: Any = None,
    log_success: bool = False
):
    """
    Decorator for bulletproof function execution with retry logic.

    Args:
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        expected_exceptions: Tuple of expected exception types
        severity: Error severity level
        default_return: Value to return on failure
        log_success: Whether to log successful executions
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    if log_success:
                        crash_logger.logger.info(f"✓ {func.__name__} executed successfully")
                    return result

                except expected_exceptions as e:
                    last_exception = e

                    # Create error context
                    frame = sys._getframe(1)
                    error_context = ErrorContext(
                        function_name=func.__name__,
                        file_name=frame.f_code.co_filename,
                        line_number=frame.f_lineno,
                        severity=severity,
                        error_type=type(e).__name__,
                        error_message=str(e),
                        timestamp=time.time(),
                        thread_id=threading.get_ident(),
                        memory_usage_mb=psutil.Process().memory_info().rss / 1024 / 1024,
                        retry_count=attempt,
                        additional_info={
                            'args': str(args)[:200],
                            'kwargs': str(kwargs)[:200]
                        }
                    )

                    crash_logger.log_error(error_context)

                    if attempt < max_retries:
                        time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                        continue
                    else:
                        # Final failure
                        crash_logger.logger.error(
                            f"✗ {func.__name__} failed after {max_retries + 1} attempts. "
                            f"Returning default: {default_return}"
                        )
                        return default_return

                except Exception as e:
                    # Unexpected exception
                    crash_logger.logger.critical(
                        f"✗ UNEXPECTED EXCEPTION in {func.__name__}: {type(e).__name__}: {e}"
                    )
                    crash_logger.logger.critical(f"Traceback: {traceback.format_exc()}")
                    return default_return

            return default_return
        return wrapper
    return decorator


@contextmanager
def resource_protection(
    resource_name: str,
    cleanup_func: Optional[Callable] = None,
    timeout_seconds: float = 300.0
):
    """
    Context manager for protected resource allocation and cleanup.

    Args:
        resource_name: Name of the resource for logging
        cleanup_func: Function to call for cleanup
        timeout_seconds: Maximum time to hold resource
    """
    start_time = time.time()
    resource_acquired = False

    try:
        crash_logger.logger.info(f"🔒 Acquiring resource: {resource_name}")
        resource_acquired = True
        yield

    except Exception as e:
        crash_logger.logger.error(f"💥 Error in resource {resource_name}: {type(e).__name__}: {e}")
        raise

    finally:
        if resource_acquired:
            elapsed = time.time() - start_time

            # Warn if resource held too long
            if elapsed > timeout_seconds:
                crash_logger.logger.warning(
                    f"⚠️ Resource {resource_name} held for {elapsed:.2f}s (>{timeout_seconds}s)"
                )

            # Execute cleanup
            if cleanup_func:
                try:
                    cleanup_func()
                    crash_logger.logger.info(f"🧹 Cleaned up resource: {resource_name}")
                except Exception as e:
                    crash_logger.logger.error(f"💥 Cleanup failed for {resource_name}: {e}")

            crash_logger.logger.info(f"🔓 Released resource: {resource_name} ({elapsed:.2f}s)")


class SafeProcessManager:
    """Safe subprocess execution with proper cleanup."""

    def __init__(self):
        self._active_processes: Dict[int, subprocess.Popen] = {}
        self._lock = threading.RLock()

    def execute_safe(
        self,
        cmd: List[str],
        timeout: float = 60.0,
        kill_timeout: float = 5.0,
        **kwargs
    ) -> Tuple[bool, str, str]:
        """
        Execute subprocess with bulletproof error handling.

        Returns:
            Tuple of (success: bool, stdout: str, stderr: str)
        """
        process = None
        try:
            # Validate command
            if not cmd or not cmd[0]:
                return False, "", "Empty command provided"

            # Check if executable exists
            if not Path(cmd[0]).exists():
                return False, "", f"Executable not found: {cmd[0]}"

            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **kwargs
            )

            # Track active process
            with self._lock:
                self._active_processes[process.pid] = process

            # Wait with timeout
            stdout, stderr = process.communicate(timeout=timeout)
            return_code = process.returncode

            # Remove from active processes
            with self._lock:
                self._active_processes.pop(process.pid, None)

            success = return_code in [0, 1]  # 0=success, 1=warnings
            return success, stdout or "", stderr or ""

        except subprocess.TimeoutExpired:
            crash_logger.logger.error(f"⏰ Process timeout after {timeout}s: {' '.join(cmd[:3])}")

            # Force kill process
            if process:
                self._force_kill_process(process, kill_timeout)

            return False, "", f"Process timeout after {timeout} seconds"

        except FileNotFoundError as e:
            crash_logger.logger.error(f"📁 Executable not found: {e}")
            return False, "", f"Executable not found: {e}"

        except PermissionError as e:
            crash_logger.logger.error(f"🚫 Permission denied: {e}")
            return False, "", f"Permission denied: {e}"

        except Exception as e:
            crash_logger.logger.error(f"💥 Unexpected process error: {type(e).__name__}: {e}")

            # Emergency cleanup
            if process:
                self._force_kill_process(process, kill_timeout)

            return False, "", f"Unexpected error: {e}"

    def _force_kill_process(self, process: subprocess.Popen, timeout: float):
        """Force kill a process with escalating termination methods."""
        try:
            # First attempt: terminate
            process.terminate()

            try:
                process.wait(timeout=timeout)
                crash_logger.logger.info("✓ Process terminated gracefully")
                return
            except subprocess.TimeoutExpired:
                pass

            # Second attempt: kill
            process.kill()

            try:
                process.wait(timeout=timeout)
                crash_logger.logger.info("✓ Process killed forcefully")
                return
            except subprocess.TimeoutExpired:
                pass

            # Third attempt: OS-level kill (Windows/Unix)
            try:
                if sys.platform == "win32":
                    os.system(f"taskkill /F /PID {process.pid}")
                else:
                    os.kill(process.pid, signal.SIGKILL)
                crash_logger.logger.info("✓ Process killed at OS level")
            except Exception as e:
                crash_logger.logger.error(f"💥 Failed to kill process {process.pid}: {e}")

        except Exception as e:
            crash_logger.logger.error(f"💥 Error during process cleanup: {e}")
        finally:
            # Remove from tracking
            with self._lock:
                self._active_processes.pop(process.pid, None)

    def cleanup_all(self):
        """Emergency cleanup of all active processes."""
        with self._lock:
            processes = list(self._active_processes.values())
            self._active_processes.clear()

        for process in processes:
            self._force_kill_process(process, 2.0)


class SafePathManager:
    """Safe path operations with validation and cleanup."""

    @staticmethod
    def validate_path(path: Union[str, Path], max_length: int = 250) -> Path:
        """
        Validate and normalize path with safety checks.

        Args:
            path: Input path
            max_length: Maximum allowed path length

        Returns:
            Validated Path object

        Raises:
            ValueError: If path is invalid or too long
        """
        if not path:
            raise ValueError("Path cannot be empty")

        try:
            path_obj = Path(str(path)).resolve()

            # Check length
            if len(str(path_obj)) > max_length:
                raise ValueError(f"Path too long: {len(str(path_obj))} > {max_length}")

            # Check for dangerous patterns
            path_str = str(path_obj).lower()
            dangerous_patterns = ['..\\', '../', 'con', 'prn', 'aux', 'nul']
            for pattern in dangerous_patterns:
                if pattern in path_str:
                    raise ValueError(f"Dangerous path pattern detected: {pattern}")

            return path_obj

        except Exception as e:
            raise ValueError(f"Invalid path '{path}': {e}")

    @staticmethod
    def safe_create_directory(path: Union[str, Path], exist_ok: bool = True) -> bool:
        """Safely create directory with proper error handling."""
        try:
            validated_path = SafePathManager.validate_path(path)
            validated_path.mkdir(parents=True, exist_ok=exist_ok)
            return True
        except (PermissionError, OSError, ValueError) as e:
            crash_logger.logger.error(f"📁 Failed to create directory {path}: {e}")
            return False

    @staticmethod
    def safe_remove_directory(path: Union[str, Path], max_retries: int = 3) -> bool:
        """Safely remove directory with retries."""
        try:
            validated_path = SafePathManager.validate_path(path)

            if not validated_path.exists():
                return True

            for attempt in range(max_retries):
                try:
                    if validated_path.is_file():
                        validated_path.unlink()
                    else:
                        import shutil
                        shutil.rmtree(validated_path)
                    return True

                except (PermissionError, OSError) as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    crash_logger.logger.error(f"🗑️ Failed to remove {path}: {e}")
                    return False

            return False

        except Exception as e:
            crash_logger.logger.error(f"💥 Error removing directory {path}: {e}")
            return False


# Global safe process manager
safe_process_manager = SafeProcessManager()


def emergency_shutdown():
    """Emergency application shutdown with cleanup."""
    crash_logger.logger.critical("🚨 EMERGENCY SHUTDOWN INITIATED")

    try:
        # Cleanup all processes
        safe_process_manager.cleanup_all()

        # Log final statistics
        error_summary = crash_logger.get_error_summary()
        crash_logger.logger.critical(f"Final error summary: {error_summary}")

        # Force garbage collection
        import gc
        gc.collect()

    except Exception as e:
        print(f"Error during emergency shutdown: {e}")

    crash_logger.logger.critical("🚨 EMERGENCY SHUTDOWN COMPLETED")


# Register emergency shutdown
import atexit
atexit.register(emergency_shutdown)


class CircuitBreaker:
    """Circuit breaker pattern for external service calls."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time = 0
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self._lock = threading.RLock()

    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        with self._lock:
            # Check if we should attempt recovery
            if self.state == 'OPEN':
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = 'HALF_OPEN'
                    crash_logger.logger.info(f"🔄 Circuit breaker half-open for {func.__name__}")
                else:
                    raise Exception(f"Circuit breaker OPEN for {func.__name__}")

            try:
                result = func(*args, **kwargs)

                # Success - reset circuit breaker
                if self.state == 'HALF_OPEN':
                    self.state = 'CLOSED'
                    self.failure_count = 0
                    crash_logger.logger.info(f"✅ Circuit breaker closed for {func.__name__}")

                return result

            except self.expected_exception as e:
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.failure_count >= self.failure_threshold:
                    self.state = 'OPEN'
                    crash_logger.logger.warning(
                        f"⛔ Circuit breaker OPEN for {func.__name__} "
                        f"({self.failure_count} failures)"
                    )

                raise e


def monitor_memory_usage(threshold_mb: float = 500.0):
    """Monitor memory usage and warn if threshold exceeded."""
    try:
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024

        if memory_mb > threshold_mb:
            crash_logger.logger.warning(
                f"🐏 High memory usage: {memory_mb:.1f}MB (>{threshold_mb}MB)"
            )

            # Force garbage collection
            import gc
            gc.collect()

        return memory_mb

    except Exception as e:
        crash_logger.logger.error(f"💥 Memory monitoring error: {e}")
        return 0.0