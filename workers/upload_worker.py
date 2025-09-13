# workers/upload_worker.py
import logging
import os
import time
import re
import gc
import weakref
import threading
import tempfile
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from enum import Enum
from pathlib import Path
from threading import Lock, RLock, Event, Condition, Barrier
from typing import Any, List, Optional, Dict, Set, Tuple, Union, Callable
from queue import Queue, Empty
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections import defaultdict, deque
import psutil
import sys

from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer, QObject
from integrations.jd_client import hard_cancel
from models.operation_status import OperationStatus, OpStage, OpType

# Enhanced imports with fallbacks
try:
    from utils.utils import _normalize_links
except Exception:  # pragma: no cover - fallback for tests
    def _normalize_links(urls):
        return [u for u in urls if isinstance(u, str)]

from uploaders.ddownload_upload_handler import DDownloadUploadHandler
from uploaders.katfile_upload_handler import KatfileUploadHandler
from uploaders.nitroflare_upload_handler import NitroflareUploadHandler
from uploaders.rapidgator_upload_handler import RapidgatorUploadHandler


class UploadStatus(Enum):
    """Enhanced status tracking with more granular states"""
    WAITING = "waiting"
    INITIALIZING = "initializing"
    UPLOADING = "uploading"
    RETRYING = "retrying"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"
    QUEUED = "queued"
    PAUSED = "paused"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


@dataclass
class UploadMetrics:
    """Enhanced metrics tracking for uploads"""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    bytes_uploaded: int = 0
    total_bytes: int = 0
    upload_speed: float = 0.0
    retry_count: int = 0
    error_count: int = 0
    last_progress_time: float = field(default_factory=time.time)
    host: str = ""
    file_name: str = ""

    @property
    def duration(self) -> float:
        end = self.end_time or time.time()
        return max(0.1, end - self.start_time)

    @property
    def progress_percent(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return min(100, int((self.bytes_uploaded / self.total_bytes) * 100))


@dataclass
class CircuitBreakerState:
    """Circuit breaker pattern implementation for network failures"""
    failure_count: int = 0
    last_failure_time: float = 0.0
    success_count: int = 0
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    failure_threshold: int = 5
    recovery_timeout: float = 300.0  # 5 minutes
    success_threshold: int = 3


class ResourceManager:
    """Enhanced resource management with automatic cleanup"""

    def __init__(self, max_connections: int = 10):
        self.max_connections = max_connections
        self.active_connections: Set[object] = set()
        self.connection_pool: Queue = Queue()
        self.lock = RLock()
        self.cleanup_timer = None
        self._setup_cleanup_timer()

    def _setup_cleanup_timer(self):
        """Setup periodic cleanup timer"""
        try:
            self.cleanup_timer = QTimer()
            self.cleanup_timer.timeout.connect(self.cleanup_resources)
            self.cleanup_timer.start(30000)  # Cleanup every 30 seconds
        except Exception as e:
            logging.warning(f"Failed to setup cleanup timer: {e}")

    @contextmanager
    def acquire_connection(self):
        """Context manager for connection acquisition"""
        connection = None
        try:
            with self.lock:
                if len(self.active_connections) < self.max_connections:
                    connection = object()  # Placeholder for real connection
                    self.active_connections.add(connection)

            if connection is None:
                raise Exception("Maximum connections exceeded")

            yield connection

        finally:
            if connection:
                with self.lock:
                    self.active_connections.discard(connection)

    def cleanup_resources(self):
        """Cleanup stale resources"""
        try:
            with self.lock:
                # Clean up any stale connections
                stale_connections = [conn for conn in self.active_connections
                                     if not hasattr(conn, '_last_used') or
                                     time.time() - getattr(conn, '_last_used', 0) > 300]

                for conn in stale_connections:
                    self.active_connections.discard(conn)

                logging.debug(f"Cleaned up {len(stale_connections)} stale connections")

        except Exception as e:
            logging.error(f"Error during resource cleanup: {e}")

    def shutdown(self):
        """Shutdown resource manager"""
        try:
            if self.cleanup_timer:
                self.cleanup_timer.stop()
                self.cleanup_timer = None

            with self.lock:
                self.active_connections.clear()

        except Exception as e:
            logging.error(f"Error during resource manager shutdown: {e}")


class MemoryManager:
    """Memory management and monitoring"""

    def __init__(self, max_memory_mb: int = 1024):
        self.max_memory_mb = max_memory_mb
        self.process = psutil.Process()
        self.initial_memory = self.get_memory_usage()

    def get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            return self.process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0

    def check_memory_usage(self) -> bool:
        """Check if memory usage is within limits"""
        current = self.get_memory_usage()
        if current > self.max_memory_mb:
            logging.warning(f"High memory usage: {current:.2f} MB")
            self.force_garbage_collection()
            return False
        return True

    def force_garbage_collection(self):
        """Force garbage collection"""
        try:
            collected = gc.collect()
            logging.debug(f"Garbage collection freed {collected} objects")
        except Exception as e:
            logging.error(f"Error during garbage collection: {e}")


class SafeProgressTracker:
    """Thread-safe progress tracking with throttling"""

    def __init__(self, throttle_interval: float = 0.1):
        self.throttle_interval = throttle_interval
        self.last_emit_time = 0.0
        self.last_progress = -1
        self.lock = Lock()
        self.total_bytes = 0
        self.current_bytes = 0

    def should_emit(self, progress: int) -> bool:
        """Check if progress update should be emitted"""
        with self.lock:
            now = time.time()
            progress_changed = progress != self.last_progress
            time_elapsed = now - self.last_emit_time >= self.throttle_interval
            is_complete = progress >= 100

            if progress_changed and (time_elapsed or is_complete):
                self.last_emit_time = now
                self.last_progress = progress
                return True
            return False

    def update(self, current: int, total: int) -> Tuple[int, bool]:
        """Update progress and return (percentage, should_emit)"""
        with self.lock:
            self.current_bytes = current
            self.total_bytes = total
            progress = int((current / total * 100)) if total > 0 else 0
            return progress, self.should_emit(progress)


class UploadWorker(QThread):
    """Enhanced, crash-resistant upload worker with comprehensive error handling"""

    # Signals - maintain same interface
    host_progress = pyqtSignal(int, int, int, str, int, int)
    upload_complete = pyqtSignal(int, dict)
    upload_success = pyqtSignal(int)
    upload_error = pyqtSignal(int, str)
    progress_update = pyqtSignal(object)  # OperationStatus

    # Class-level resource management
    _global_resource_manager = None
    _global_memory_manager = None
    _circuit_breakers: Dict[str, CircuitBreakerState] = {}
    _class_lock = RLock()

    @classmethod
    def get_resource_manager(cls) -> ResourceManager:
        """Get global resource manager instance"""
        with cls._class_lock:
            if cls._global_resource_manager is None:
                cls._global_resource_manager = ResourceManager()
            return cls._global_resource_manager

    @classmethod
    def get_memory_manager(cls) -> MemoryManager:
        """Get global memory manager instance"""
        with cls._class_lock:
            if cls._global_memory_manager is None:
                cls._global_memory_manager = MemoryManager()
            return cls._global_memory_manager

    @classmethod
    def get_circuit_breaker(cls, host: str) -> CircuitBreakerState:
        """Get circuit breaker for host"""
        with cls._class_lock:
            if host not in cls._circuit_breakers:
                cls._circuit_breakers[host] = CircuitBreakerState()
            return cls._circuit_breakers[host]

    def __init__(
            self,
            bot,
            row: int,
            folder_path: str,
            thread_id: str,
            upload_hosts: Optional[List[str]] = None,
            section: str = "Uploads",
            keeplinks_url: Optional[str] = None,
            cancel_event=None,
            files: Optional[List[str]] = None,
            package_label: str = "audio",
    ):
        """Enhanced initialization with comprehensive error handling"""

        super().__init__()  # QThread init first

        # Initialize safety mechanisms early
        self._initialization_lock = RLock()
        self._shutdown_event = Event()
        self._emergency_stop = Event()
        self._state_lock = RLock()
        self._progress_trackers: Dict[str, SafeProgressTracker] = {}
        self._upload_metrics: Dict[int, UploadMetrics] = {}
        self._retry_delays = [1, 2, 4, 8, 16, 32]  # Exponential backoff
        self._max_retries = len(self._retry_delays)

        # Resource managers
        self.resource_manager = self.get_resource_manager()
        self.memory_manager = self.get_memory_manager()

        # Initialize with comprehensive error handling
        with self._initialization_lock:
            try:
                self._init_basic_parameters(bot, row, thread_id, section, package_label)
                self._init_folder_path(folder_path)
                self._init_configuration()
                self._init_control_settings(keeplinks_url, cancel_event)
                self._init_upload_hosts(upload_hosts)
                self._init_file_management(files)
                self._init_handlers_and_results()
                self._init_monitoring()

                logging.info(f"🔧 Enhanced UploadWorker initialized successfully")
                logging.info(f"   - Files: {self.total_files}")
                logging.info(f"   - Hosts: {len(self.hosts)}")
                logging.info(f"   - Handlers: {len(self.handlers)}")
                logging.info(f"   - Memory: {self.memory_manager.get_memory_usage():.2f} MB")

            except Exception as init_error:
                logging.error(f"❌ Critical initialization failure: {init_error}", exc_info=True)
                self._init_fallback_state()
                raise

    def _init_basic_parameters(self, bot, row, thread_id, section, package_label):
        """Initialize basic parameters with validation"""
        try:
            self.bot = bot
            self.row = max(0, int(row) if row is not None else 0)
            self.thread_id = str(thread_id) if thread_id else f"worker_{id(self)}"
            self.config = getattr(bot, 'config', {}) if bot else {}
            self.section = str(section) if section else "Uploads"
            self.package_label = str(package_label) if package_label else "audio"

            logging.info(f"🔧 Basic parameters initialized for row {self.row}, thread {self.thread_id}")

        except Exception as e:
            logging.error(f"❌ Basic parameter initialization failed: {e}")
            # Safe fallbacks
            self.bot = bot
            self.row = 0
            self.thread_id = f"fallback_{int(time.time())}"
            self.config = {}
            self.section = "Uploads"
            self.package_label = "audio"

    def _init_folder_path(self, folder_path):
        """Initialize folder path with comprehensive validation"""
        try:
            self.folder_path = Path(str(folder_path)).resolve()

            # Validate and create if necessary
            if not self.folder_path.exists():
                logging.warning(f"⚠️ Folder path does not exist: {folder_path}")
                try:
                    self.folder_path.mkdir(parents=True, exist_ok=True)
                    logging.info(f"✅ Created missing folder: {self.folder_path}")
                except Exception as mkdir_e:
                    logging.error(f"❌ Cannot create folder: {mkdir_e}")
                    # Use temporary directory as fallback
                    temp_dir = Path(tempfile.gettempdir()) / f"upload_{self.thread_id}"
                    temp_dir.mkdir(exist_ok=True)
                    self.folder_path = temp_dir
                    logging.info(f"🔄 Using temp folder: {self.folder_path}")

            # Validate folder accessibility
            test_file = self.folder_path / f".test_{int(time.time())}.tmp"
            try:
                test_file.touch()
                test_file.unlink()
                logging.debug(f"✅ Folder write access verified: {self.folder_path}")
            except Exception as access_e:
                logging.warning(f"⚠️ Folder access issue: {access_e}")

        except Exception as path_e:
            logging.error(f"❌ Folder path processing failed: {path_e}")
            # Ultimate fallback
            self.folder_path = Path(tempfile.gettempdir()) / "upload_fallback"
            self.folder_path.mkdir(exist_ok=True)

    def _init_configuration(self):
        """Initialize configuration with validation"""
        try:
            # Upload cooldown with validation
            cooldown = self.config.get("upload_cooldown_seconds", 30)
            self.upload_cooldown = max(5, min(300, int(cooldown)))  # 5-300 seconds range

            # Thread pool size based on host count and system resources
            cpu_count = os.cpu_count() or 4
            max_workers = min(len(self.hosts) if hasattr(self, 'hosts') else 5, cpu_count, 8)
            self.max_workers = max(1, max_workers)

            # Timeout settings
            self.network_timeout = self.config.get("network_timeout", 300)  # 5 minutes
            self.upload_timeout = self.config.get("upload_timeout", 3600)  # 1 hour

            logging.debug(f"Configuration: cooldown={self.upload_cooldown}s, workers={self.max_workers}")

        except Exception as e:
            logging.error(f"❌ Configuration initialization failed: {e}")
            # Safe defaults
            self.upload_cooldown = 30
            self.max_workers = 3
            self.network_timeout = 300
            self.upload_timeout = 3600

    def _init_control_settings(self, keeplinks_url, cancel_event):
        """Initialize control settings with thread safety"""
        try:
            self.keeplinks_url = str(keeplinks_url) if keeplinks_url else None
            self.keeplinks_sent = False
            self.is_cancelled = False
            self.is_paused = False
            self.pause_condition = Condition(self._state_lock)
            self.cancel_event = cancel_event

            # Enhanced control mechanisms
            self.operation_start_time = time.time()
            self.last_heartbeat = time.time()
            self.heartbeat_interval = 10.0  # 10 seconds

        except Exception as e:
            logging.error(f"❌ Control settings initialization failed: {e}")
            # Safe defaults
            self.keeplinks_url = None
            self.keeplinks_sent = False
            self.is_cancelled = False
            self.is_paused = False
            self.pause_condition = Condition(self._state_lock)
            self.cancel_event = None
            self.operation_start_time = time.time()
            self.last_heartbeat = time.time()
            self.heartbeat_interval = 10.0

    def _init_upload_hosts(self, upload_hosts):
        """Initialize upload hosts with validation"""
        try:
            if upload_hosts is None:
                upload_hosts = self.config.get("upload_hosts", ["rapidgator", "katfile"])

            # Supported hosts with validation
            supported_hosts = {
                "rapidgator": "rapidgator",
                "rapidgator-backup": "rapidgator-backup",
                "katfile": "katfile",
                "nitroflare": "nitroflare",
                "ddownload": "ddownload",
                "uploady": "uploady"
            }

            # Validate and normalize hosts
            valid_hosts = []
            for host in upload_hosts:
                if isinstance(host, str):
                    normalized = host.lower().strip()
                    if normalized in supported_hosts:
                        valid_hosts.append(supported_hosts[normalized])
                    else:
                        logging.warning(f"⚠️ Unsupported host: {host}")
                else:
                    logging.warning(f"⚠️ Invalid host type: {host} ({type(host)})")

            if not valid_hosts:
                logging.warning("⚠️ No valid hosts found, using defaults")
                valid_hosts = ["rapidgator", "katfile"]

            # Remove duplicates while preserving order
            seen = set()
            self.hosts = []
            for host in valid_hosts:
                if host not in seen:
                    self.hosts.append(host)
                    seen.add(host)

            logging.info(f"✅ Upload hosts configured: {self.hosts}")

        except Exception as e:
            logging.error(f"❌ Hosts configuration failed: {e}")
            self.hosts = ["rapidgator", "katfile"]  # Safe fallback

    def _init_file_management(self, files):
        """Initialize file management with comprehensive validation"""
        try:
            self.explicit_files = None

            if files:
                validated_files = []
                for f in files:
                    try:
                        file_path = Path(str(f))
                        if file_path.exists() and file_path.is_file():
                            # Comprehensive file validation
                            stat_info = file_path.stat()
                            if stat_info.st_size > 0:  # Not empty
                                # Additional checks
                                if self._is_valid_upload_file(file_path):
                                    validated_files.append(file_path)
                                    logging.debug(f"✅ Validated file: {file_path.name} ({stat_info.st_size} bytes)")
                                else:
                                    logging.warning(f"⚠️ Invalid file type skipped: {f}")
                            else:
                                logging.warning(f"⚠️ Empty file skipped: {f}")
                        else:
                            logging.warning(f"⚠️ File not found or not a file: {f}")
                    except Exception as file_e:
                        logging.error(f"❌ Error processing file {f}: {file_e}")
                        continue

                if validated_files:
                    self.explicit_files = validated_files
                    logging.info(f"✅ {len(validated_files)} explicit files validated")
                else:
                    logging.warning("⚠️ No valid explicit files, will scan folder")

            # Get final file list
            self.files = self.explicit_files or self._get_files_safe()
            self.total_files = len(self.files)

            if not self.files:
                logging.warning(f"⚠️ No files found in {self.folder_path}")
            else:
                total_size = sum(f.stat().st_size for f in self.files)
                logging.info(f"📁 Found {self.total_files} files, total size: {total_size / (1024 * 1024):.2f} MB")

        except Exception as e:
            logging.error(f"❌ File management initialization failed: {e}")
            self.explicit_files = None
            self.files = []
            self.total_files = 0

    def _init_handlers_and_results(self):
        """Initialize upload handlers and result tracking"""
        try:
            # Initialize thread pool with resource limits
            self.thread_pool = ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix=f"upload-{self.thread_id}"
            )

            # Initialize handlers for supported hosts
            self.handlers = {}
            for host in self.hosts:
                try:
                    if host == "nitroflare":
                        self.handlers[host] = NitroflareUploadHandler(self.bot)
                    elif host == "ddownload":
                        self.handlers[host] = DDownloadUploadHandler(self.bot)
                    elif host == "katfile":
                        self.handlers[host] = KatfileUploadHandler(self.bot)
                    elif host == "uploady":
                        from uploaders.uploady_upload_handler import UploadyUploadHandler
                        self.handlers[host] = UploadyUploadHandler()
                    # Note: rapidgator handlers created in _upload_single for better credential management

                    if host in self.handlers:
                        logging.info(f"✅ Handler initialized for {host}")

                except Exception as handler_e:
                    logging.error(f"❌ Failed to initialize handler for {host}: {handler_e}")
                    continue

            # Initialize result tracking
            self.upload_results = {
                idx: {"status": "not_attempted", "urls": [], "error": None, "retry_count": 0}
                for idx in range(len(self.hosts))
            }
            self._host_results = {}

            # Initialize progress tracking
            for idx, host in enumerate(self.hosts):
                self._progress_trackers[f"{idx}-{host}"] = SafeProgressTracker()
                self._upload_metrics[idx] = UploadMetrics(host=host)

            logging.info(f"🔧 Handlers and results initialized: {len(self.handlers)} handlers")

        except Exception as e:
            logging.error(f"❌ Handlers initialization failed: {e}")
            # Fallback initialization
            try:
                self.thread_pool = ThreadPoolExecutor(max_workers=2)
                self.handlers = {}
                self.upload_results = {}
                self._host_results = {}
            except:
                pass

    def _init_monitoring(self):
        """Initialize monitoring and health checking"""
        try:
            # Health check timer
            self.health_check_timer = QTimer()
            self.health_check_timer.timeout.connect(self._health_check)
            self.health_check_timer.start(30000)  # Every 30 seconds

            # Memory monitoring
            self.memory_check_interval = 60.0  # 1 minute
            self.last_memory_check = time.time()

            # Performance metrics
            self.performance_metrics = {
                'uploads_started': 0,
                'uploads_completed': 0,
                'uploads_failed': 0,
                'total_bytes_uploaded': 0,
                'average_speed': 0.0
            }

            logging.debug("✅ Monitoring systems initialized")

        except Exception as e:
            logging.error(f"❌ Monitoring initialization failed: {e}")
            self.health_check_timer = None
            self.performance_metrics = {}

    def _init_fallback_state(self):
        """Initialize minimal fallback state for emergency situations"""
        try:
            self.bot = None
            self.row = 0
            self.thread_id = f"emergency_{int(time.time())}"
            self.config = {}
            self.section = "Uploads"
            self.package_label = "audio"
            self.folder_path = Path(tempfile.gettempdir()) / "emergency_upload"
            self.folder_path.mkdir(exist_ok=True)
            self.hosts = ["rapidgator"]
            self.files = []
            self.total_files = 0
            self.thread_pool = ThreadPoolExecutor(max_workers=1)
            self.handlers = {}
            self.upload_results = {}
            self._host_results = {}

            logging.warning("⚠️ Fallback state initialized due to critical error")

        except Exception as fallback_e:
            logging.critical(f"💥 Even fallback initialization failed: {fallback_e}")
            raise

    def _is_valid_upload_file(self, file_path: Path) -> bool:
        """Validate if file is suitable for upload"""
        try:
            # Check file size (not too small, not too large)
            size = file_path.stat().st_size
            if size < 1024:  # Less than 1KB
                return False
            if size > 10 * 1024 * 1024 * 1024:  # More than 10GB
                logging.warning(f"⚠️ Very large file: {file_path.name} ({size / (1024 * 1024 * 1024):.2f} GB)")

            # Check if file is readable
            try:
                with open(file_path, 'rb') as f:
                    f.read(1024)  # Try to read first 1KB
            except Exception:
                return False

            # Check file extension (basic validation)
            dangerous_extensions = {'.exe', '.bat', '.cmd', '.scr', '.com', '.pif'}
            if file_path.suffix.lower() in dangerous_extensions:
                logging.warning(f"⚠️ Potentially dangerous file extension: {file_path}")
                return False

            return True

        except Exception as e:
            logging.error(f"❌ File validation error for {file_path}: {e}")
            return False

    def _get_files_safe(self) -> List[Path]:
        """Safely scan folder for files with comprehensive error handling"""
        try:
            if not self.folder_path.exists():
                logging.error(f"❌ Folder does not exist: {self.folder_path}")
                return []

            if not os.access(self.folder_path, os.R_OK):
                logging.error(f"❌ No read permission for folder: {self.folder_path}")
                return []

            files = []
            scanned_count = 0

            for item in self.folder_path.iterdir():
                scanned_count += 1
                if scanned_count > 10000:  # Prevent infinite loops
                    logging.warning("⚠️ Too many items in folder, limiting scan")
                    break

                try:
                    if item.is_file() and self._is_valid_upload_file(item):
                        files.append(item)
                except Exception as item_e:
                    logging.warning(f"⚠️ Error checking file {item}: {item_e}")
                    continue

            # Sort files by size (largest first) for better upload scheduling
            files.sort(key=lambda f: f.stat().st_size, reverse=True)

            logging.info(f"📁 Scanned {scanned_count} items, found {len(files)} valid files")
            return files

        except Exception as e:
            logging.error(f"❌ Error scanning folder {self.folder_path}: {e}")
            return []

    def _health_check(self):
        """Perform health checks and maintenance"""
        try:
            current_time = time.time()

            # Update heartbeat
            self.last_heartbeat = current_time

            # Check memory usage
            if current_time - self.last_memory_check > self.memory_check_interval:
                if not self.memory_manager.check_memory_usage():
                    logging.warning("⚠️ High memory usage detected")
                self.last_memory_check = current_time

            # Check for stalled operations
            if hasattr(self, 'operation_start_time'):
                operation_duration = current_time - self.operation_start_time
                if operation_duration > self.upload_timeout:
                    logging.error(f"❌ Operation timeout ({operation_duration:.1f}s)")
                    self._emergency_stop.set()

            # Update circuit breakers
            for host, breaker in self._circuit_breakers.items():
                if (breaker.state == "OPEN" and
                        current_time - breaker.last_failure_time > breaker.recovery_timeout):
                    breaker.state = "HALF_OPEN"
                    logging.info(f"🔄 Circuit breaker for {host} moved to HALF_OPEN")

        except Exception as e:
            logging.error(f"❌ Health check failed: {e}")

    def _host_from_url(self, url: str) -> str:
        """Extract hostname from URL without www prefix - thread safe"""
        try:
            from urllib.parse import urlparse
            if not isinstance(url, str) or not url.strip():
                return ""

            host = (urlparse(url.strip()).netloc or "").lower()
            return host[4:] if host.startswith("www.") else host
        except Exception as e:
            logging.warning(f"⚠️ Error parsing URL {url}: {e}")
            return ""

    def _ext_from_name(self, name: str) -> str:
        """Return file extension without leading dot - safe"""
        try:
            return Path(str(name)).suffix.lower().lstrip(".")
        except Exception:
            return ""

    def _kind_from_name(self, name: str) -> str:
        """Classify filename into book/audio/other kinds - safe"""
        try:
            ext = self._ext_from_name(name)

            # Direct book formats
            if ext in {"pdf", "epub", "mobi", "azw3", "cbz", "cbr", "djvu", "fb2"}:
                return "book"

            # Direct audio formats  
            if ext in {"m4b", "mp3", "flac", "aac", "ogg", "m4a", "wav", "wma", "opus"}:
                return "audio"

            # Video formats
            if ext in {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm"}:
                return "video"

            # Archives: use package_label as hint
            if ext in {"rar", "zip", "7z", "tar", "gz", "bz2"}:
                return getattr(self, 'package_label', 'other')

            return "other"

        except Exception as e:
            logging.warning(f"⚠️ Error classifying file {name}: {e}")
            return "other"

    @pyqtSlot()
    def pause_uploads(self):
        """Pause uploads with proper synchronization"""
        try:
            with self._state_lock:
                self.is_paused = True
                with self.pause_condition:
                    self.pause_condition.notify_all()
            logging.info("⏸️ UploadWorker paused")
        except Exception as e:
            logging.error(f"❌ Error pausing uploads: {e}")

    @pyqtSlot()
    def resume_uploads(self):
        """Resume uploads with proper synchronization"""
        try:
            with self._state_lock:
                self.is_paused = False
                with self.pause_condition:
                    self.pause_condition.notify_all()
            logging.info("▶️ UploadWorker resumed")
        except Exception as e:
            logging.error(f"❌ Error resuming uploads: {e}")

    @pyqtSlot()
    def cancel_uploads(self):
        """Cancel uploads with comprehensive cleanup"""
        try:
            with self._state_lock:
                self.is_cancelled = True
                self.is_paused = False  # Ensure we don't stay paused

            # Set cancel events
            if self.cancel_event:
                self.cancel_event.set()
            self._emergency_stop.set()

            # Notify waiting threads
            with self.pause_condition:
                self.pause_condition.notify_all()

            logging.info("🛑 UploadWorker cancellation requested")

            # JDownloader cleanup
            try:
                jd_downloader = getattr(self.bot, "_shared_jd_downloader", None)
                if jd_downloader and hasattr(jd_downloader, 'is_available') and jd_downloader.is_available():
                    hard_cancel(jd_downloader.post, logger=logging)
            except Exception as jd_e:
                logging.warning(f"⚠️ JDownloader cleanup failed: {jd_e}")

        except Exception as e:
            logging.error(f"❌ Error cancelling uploads: {e}")

    def _reset_control_for_retry(self):
        """Reset control state for retry operations"""
        try:
            with self._state_lock:
                self.is_cancelled = False
                self.is_paused = False

            # Reset events
            if self.cancel_event:
                try:
                    self.cancel_event.clear()
                except Exception:
                    pass

            if hasattr(self, '_emergency_stop'):
                self._emergency_stop.clear()

            # Reset operation start time
            self.operation_start_time = time.time()

            logging.debug("🔄 Control state reset for retry")

        except Exception as e:
            logging.error(f"❌ Error resetting control state: {e}")
            # Force reset
            self.is_cancelled = False
            self.is_paused = False

    def _check_control(self):
        """Enhanced control checking with proper exception handling"""
        try:
            # Check for emergency stop first
            if self._emergency_stop.is_set():
                raise Exception("Emergency stop activated")

            # Check cancellation
            with self._state_lock:
                if self.is_cancelled or (self.cancel_event and self.cancel_event.is_set()):
                    raise Exception("Upload cancelled by user")

            # Handle pause state with timeout
            while True:
                with self._state_lock:
                    if self.is_cancelled or (self.cancel_event and self.cancel_event.is_set()):
                        raise Exception("Upload cancelled by user")
                    if not self.is_paused:
                        break

                # Wait for resume with timeout
                try:
                    with self.pause_condition:
                        self.pause_condition.wait(timeout=1.0)
                except Exception:
                    pass  # Timeout is expected

                # Check for emergency conditions during pause
                if time.time() - self.operation_start_time > self.upload_timeout:
                    raise Exception("Operation timeout during pause")

        except Exception as e:
            if "cancelled" not in str(e).lower() and "timeout" not in str(e).lower():
                logging.error(f"❌ Control check failed: {e}")
            raise

    def run(self):
        """Main worker execution with comprehensive error handling"""
        try:
            self.operation_start_time = time.time()
            logging.info(f"🚀 Starting upload from {self.folder_path} with {self.total_files} files")

            # Pre-flight checks
            if not self._pre_flight_checks():
                return

            self._check_control()

            # Execute uploads with enhanced monitoring
            success = self._execute_uploads()

            if success:
                self._handle_successful_completion()
            else:
                self._handle_failed_completion()

        except Exception as e:
            self._handle_critical_error(e)
        finally:
            self._cleanup_resources()

    def _pre_flight_checks(self) -> bool:
        """Perform comprehensive pre-flight checks"""
        try:
            # Check if we have files
            if not self.files:
                msg = "لا توجد ملفات للرفع"
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(self.row, {
                    "error": msg,
                    "host_results": self._host_results
                })
                return False

            # Check memory
            if not self.memory_manager.check_memory_usage():
                logging.warning("⚠️ High memory usage before upload")

            # Check circuit breakers
            available_hosts = []
            for idx, host in enumerate(self.hosts):
                breaker = self.get_circuit_breaker(host)
                if breaker.state != "OPEN":
                    available_hosts.append((idx, host))
                else:
                    logging.warning(f"⚠️ Host {host} circuit breaker is OPEN")

            if not available_hosts:
                msg = "جميع المضيفين غير متاحين حاليًا"
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(self.row, {
                    "error": msg,
                    "host_results": self._host_results
                })
                return False

            # Update available hosts
            self.available_hosts = available_hosts

            return True

        except Exception as e:
            logging.error(f"❌ Pre-flight checks failed: {e}")
            self.upload_error.emit(self.row, f"Pre-flight check failed: {str(e)}")
            return False

    def _execute_uploads(self) -> bool:
        """Execute uploads with enhanced error handling and monitoring"""
        try:
            # Submit upload tasks for all available hosts
            futures = {}
            for idx, host in self.available_hosts:
                self._check_control()

                if self.upload_results.get(idx, {}).get("status") != "not_attempted":
                    continue

                future = self.thread_pool.submit(self._upload_host_all_safe, idx)
                futures[future] = idx

                # Stagger submissions to avoid overwhelming
                time.sleep(0.1)

            if not futures:
                logging.warning("⚠️ No upload tasks submitted")
                return False

            # Monitor completion with timeout
            completed = 0
            total = len(futures)
            start_time = time.time()

            for future in as_completed(futures, timeout=self.upload_timeout):
                try:
                    self._check_control()
                    idx = futures[future]

                    result = future.result(timeout=30)  # 30 second timeout for result

                    if result == "success":
                        self.upload_results[idx]["status"] = "success"
                        self.performance_metrics['uploads_completed'] += 1
                    else:
                        self.upload_results[idx]["status"] = "failed"
                        self.performance_metrics['uploads_failed'] += 1

                    completed += 1

                    # Progress update
                    progress = int((completed / total) * 100)
                    logging.info(f"📊 Upload progress: {completed}/{total} ({progress}%)")

                    # Memory check periodically
                    if completed % max(1, total // 4) == 0:
                        self.memory_manager.check_memory_usage()

                except Exception as future_e:
                    idx = futures[future]
                    logging.error(f"❌ Upload future failed for host {idx}: {future_e}")
                    self.upload_results[idx]["status"] = "failed"
                    self.upload_results[idx]["error"] = str(future_e)
                    completed += 1

            # Check if any uploads succeeded
            success_count = sum(1 for r in self.upload_results.values() if r.get("status") == "success")

            logging.info(f"📈 Upload execution completed: {success_count}/{len(self.upload_results)} succeeded")

            return success_count > 0

        except Exception as e:
            logging.error(f"❌ Upload execution failed: {e}")
            return False

    def _upload_host_all_safe(self, host_idx: int) -> str:
        """Upload all files to a host with comprehensive error handling"""
        host = self.hosts[host_idx]

        try:
            logging.info(f"🔄 Starting upload to {host} (index {host_idx})")

            # Check circuit breaker
            breaker = self.get_circuit_breaker(host)
            if breaker.state == "OPEN":
                logging.warning(f"⚠️ Circuit breaker OPEN for {host}, skipping")
                return "failed"

            # Initialize metrics
            self._upload_metrics[host_idx] = UploadMetrics(host=host)

            urls = []
            file_count = len(self.files)

            for file_idx, file_path in enumerate(self.files):
                try:
                    self._check_control()

                    logging.info(f"📤 Uploading file {file_idx + 1}/{file_count}: {file_path.name} to {host}")

                    # Update metrics
                    metrics = self._upload_metrics[host_idx]
                    metrics.file_name = file_path.name
                    metrics.retry_count = 0

                    # Upload single file with retry logic
                    url = self._upload_single_with_retry(host_idx, file_path)

                    if url is None:
                        logging.error(f"❌ Failed to upload {file_path.name} to {host}")
                        breaker.failure_count += 1
                        breaker.last_failure_time = time.time()

                        if breaker.failure_count >= breaker.failure_threshold:
                            breaker.state = "OPEN"
                            logging.warning(
                                f"⚠️ Circuit breaker OPEN for {host} after {breaker.failure_count} failures")

                        return "failed"

                    urls.append(url)

                    # Update circuit breaker on success
                    breaker.success_count += 1
                    if breaker.state == "HALF_OPEN" and breaker.success_count >= breaker.success_threshold:
                        breaker.state = "CLOSED"
                        breaker.failure_count = 0
                        logging.info(f"✅ Circuit breaker CLOSED for {host} after successful uploads")

                    # Collect upload results by host and file type
                    self._collect_upload_result(host, host_idx, file_path, url)

                    # Rate limiting between files
                    if file_idx < file_count - 1:
                        self._apply_rate_limiting(host, host_idx)

                except Exception as file_e:
                    logging.error(f"❌ Error uploading file {file_path.name} to {host}: {file_e}")
                    breaker.failure_count += 1
                    breaker.last_failure_time = time.time()
                    return "failed"

            # Store results
            self.upload_results[host_idx]["urls"] = urls

            logging.info(f"✅ Successfully uploaded {len(urls)} files to {host}")
            return "success"

        except Exception as e:
            logging.error(f"❌ Host upload failed for {host}: {e}", exc_info=True)
            breaker = self.get_circuit_breaker(host)
            breaker.failure_count += 1
            breaker.last_failure_time = time.time()
            return "failed"

    def _upload_single_with_retry(self, host_idx: int, file_path: Path) -> Optional[str]:
        """Upload single file with exponential backoff retry"""
        host = self.hosts[host_idx]
        max_retries = min(self._max_retries, 5)  # Limit retries

        for attempt in range(max_retries + 1):
            try:
                self._check_control()

                if attempt > 0:
                    delay = self._retry_delays[min(attempt - 1, len(self._retry_delays) - 1)]
                    logging.info(
                        f"🔄 Retry attempt {attempt}/{max_retries} for {file_path.name} on {host} after {delay}s")
                    time.sleep(delay)

                # Update metrics
                metrics = self._upload_metrics[host_idx]
                metrics.retry_count = attempt

                # Perform upload
                url = self._upload_single_safe(host_idx, file_path)

                if url:
                    if attempt > 0:
                        logging.info(f"✅ Upload succeeded on retry {attempt} for {file_path.name}")
                    return url
                else:
                    logging.warning(f"⚠️ Upload attempt {attempt} failed for {file_path.name} on {host}")
                    metrics.error_count += 1

            except Exception as retry_e:
                logging.error(f"❌ Retry attempt {attempt} error for {file_path.name}: {retry_e}")

                # Check if it's a cancellation
                if "cancelled" in str(retry_e).lower():
                    raise

                # Check for permanent failures
                error_str = str(retry_e).lower()
                if any(perm in error_str for perm in ["authentication", "forbidden", "invalid token"]):
                    logging.error(f"❌ Permanent error, stopping retries: {retry_e}")
                    break

        logging.error(f"❌ All retry attempts failed for {file_path.name} on {host}")
        return None

    def _upload_single_safe(self, host_idx: int, file_path: Path) -> Optional[str]:
        """Upload single file with comprehensive safety checks"""
        host = self.hosts[host_idx]

        try:
            # Pre-upload validation
            if not file_path.exists():
                raise Exception(f"File no longer exists: {file_path}")

            file_size = file_path.stat().st_size
            if file_size == 0:
                raise Exception(f"Empty file: {file_path}")

            # Memory check before upload
            if not self.memory_manager.check_memory_usage():
                logging.warning(f"⚠️ High memory usage before uploading {file_path.name}")

            # Initialize progress tracker
            tracker_key = f"{host_idx}-{host}"
            if tracker_key not in self._progress_trackers:
                self._progress_trackers[tracker_key] = SafeProgressTracker()

            progress_tracker = self._progress_trackers[tracker_key]

            # Create upload handler
            handler, upload_func = self._create_upload_handler(host, file_path)

            if not handler or not upload_func:
                raise Exception(f"Failed to create handler for {host}")

            # Progress callback with safety
            start_time = time.time()

            def safe_progress_callback(current, total):
                try:
                    self._check_control()

                    progress, should_emit = progress_tracker.update(current, total)

                    if should_emit:
                        elapsed = time.time() - start_time
                        speed = current / elapsed if elapsed > 0 else 0.0
                        eta = (total - current) / speed if speed > 0 and total > current else 0.0

                        # Update metrics
                        metrics = self._upload_metrics[host_idx]
                        metrics.bytes_uploaded = current
                        metrics.total_bytes = total
                        metrics.upload_speed = speed

                        # Emit status
                        status = OperationStatus(
                            section=self.section,
                            item=file_path.name,
                            op_type=OpType.UPLOAD,
                            stage=OpStage.RUNNING if progress < 100 else OpStage.FINISHED,
                            message=f"Uploading {file_path.name}" if progress < 100 else "Complete",
                            progress=progress,
                            speed=speed,
                            eta=eta,
                            host=host,
                        )
                        self.progress_update.emit(status)
                        self.host_progress.emit(
                            self.row, host_idx, progress,
                            f"Uploading {file_path.name}" if progress < 100 else "Complete",
                            current, total
                        )

                except Exception as cb_e:
                    logging.warning(f"⚠️ Progress callback error: {cb_e}")

            # Perform upload with resource management
            with self.resource_manager.acquire_connection():
                url = upload_func(safe_progress_callback)

            self._check_control()

            if not url:
                raise Exception("Upload returned empty URL")

            # Validate URL
            if not isinstance(url, str) or not url.strip():
                raise Exception("Invalid URL returned from upload")

            # Final progress update
            self.host_progress.emit(
                self.row, host_idx, 100, f"Complete {file_path.name}",
                file_size, file_size
            )

            # Update performance metrics
            self.performance_metrics['total_bytes_uploaded'] += file_size

            logging.info(f"✅ Successfully uploaded {file_path.name} to {host}: {url}")
            return url.strip()

        except Exception as e:
            error_msg = str(e)
            logging.error(f"❌ Upload failed for {file_path.name} on {host}: {error_msg}")

            # Emit error status
            try:
                status = OperationStatus(
                    section=self.section,
                    item=file_path.name,
                    op_type=OpType.UPLOAD,
                    stage=OpStage.ERROR,
                    message=f"Error {file_path.name}: {error_msg}",
                    host=host,
                )
                self.progress_update.emit(status)
                self.host_progress.emit(
                    self.row, host_idx, 0, f"Error {file_path.name}: {error_msg}",
                    0, file_size
                )
            except Exception as emit_e:
                logging.warning(f"⚠️ Failed to emit error status: {emit_e}")

            return None

    def _create_upload_handler(self, host: str, file_path: Path):
        """Create upload handler for specific host with enhanced error handling"""
        try:
            if host in ("rapidgator", "rapidgator-backup"):
                return self._create_rapidgator_handler(host, file_path)
            elif host in self.handlers:
                handler = self.handlers[host]
                upload_func = lambda cb: handler.upload_file(str(file_path), progress_callback=cb)
                return handler, upload_func
            else:
                logging.error(f"❌ No handler available for host: {host}")
                return None, None

        except Exception as e:
            logging.error(f"❌ Failed to create upload handler for {host}: {e}")
            return None, None

    def _create_rapidgator_handler(self, host: str, file_path: Path):
        """Create Rapidgator handler with proper credential management"""
        try:
            # Get credentials based on host type
            if host == "rapidgator":
                token = (
                        self.config.get("rapidgator_api_token", "") or
                        getattr(self.bot, "upload_rapidgator_token", "") or
                        getattr(self.bot, "rg_main_token", "")
                )
                username = os.getenv("UPLOAD_RAPIDGATOR_USERNAME") or os.getenv("UPLOAD_RAPIDGATOR_LOGIN", "")
                password = os.getenv("UPLOAD_RAPIDGATOR_PASSWORD", "")
            else:  # rapidgator-backup
                token = (
                        self.config.get("rapidgator_backup_api_token", "") or
                        getattr(self.bot, "rg_backup_token", "") or
                        getattr(self.bot, "rapidgator_token", "")
                )
                username = os.getenv("RAPIDGATOR_LOGIN", "")
                password = os.getenv("RAPIDGATOR_PASSWORD", "")

            if not token and not (username and password):
                raise Exception(f"No credentials available for {host}")

            # Create handler with enhanced error handling
            handler = RapidgatorUploadHandler(
                filepath=file_path,
                username=username,
                password=password,
                token=token,
            )

            upload_func = lambda cb: handler.upload(progress_cb=cb)

            return handler, upload_func

        except Exception as e:
            logging.error(f"❌ Failed to create Rapidgator handler for {host}: {e}")
            raise

    def _collect_upload_result(self, host: str, host_idx: int, file_path: Path, url: str):
        """Collect and organize upload results by host and file type"""
        try:
            # Extract host from URL for consistency
            detected_host = self._host_from_url(url)

            # Use explicit host if URL parsing fails
            if not detected_host:
                detected_host = host.replace("-", "_").replace("rapidgator_backup", "rapidgator-backup")

            # Handle backup host naming
            if host == "rapidgator-backup":
                detected_host = "rapidgator-backup"

            if detected_host:
                kind = self._kind_from_name(file_path.name)
                ext = self._ext_from_name(file_path.name)

                # Create host bucket
                bucket = self._host_results.setdefault(detected_host, {"by_type": {}})

                # Mark backup host
                if host == "rapidgator-backup":
                    bucket["is_backup"] = True

                # Organize by file type and extension
                by_type = bucket.setdefault("by_type", {})
                type_bucket = by_type.setdefault(kind, {})

                if ext:
                    ext_list = type_bucket.setdefault(ext, [])
                    if url not in ext_list:  # Avoid duplicates
                        ext_list.append(url)

        except Exception as e:
            logging.error(f"❌ Error collecting upload result: {e}")

    def _apply_rate_limiting(self, host: str, host_idx: int):
        """Apply intelligent rate limiting between uploads"""
        try:
            # Base cooldown
            base_delay = self.upload_cooldown

            # Adjust delay based on circuit breaker state
            breaker = self.get_circuit_breaker(host)
            if breaker.failure_count > 0:
                # Increase delay if there have been recent failures
                multiplier = min(2.0, 1.0 + (breaker.failure_count * 0.2))
                base_delay = int(base_delay * multiplier)

            # Apply jitter to avoid thundering herd
            jitter = base_delay * 0.1  # 10% jitter
            delay = base_delay + (time.time() % jitter)

            logging.debug(f"⏱️ Rate limiting: {delay:.1f}s delay before next file on {host}")

            # Interruptible sleep
            end_time = time.time() + delay
            while time.time() < end_time:
                self._check_control()  # Allow cancellation during delay
                time.sleep(min(0.1, end_time - time.time()))

        except Exception as e:
            if "cancelled" not in str(e).lower():
                logging.warning(f"⚠️ Rate limiting error: {e}")
            raise

    def _prepare_final_urls(self) -> dict:
        """Prepare final URLs with comprehensive error handling"""
        try:
            self._check_control()

            # Check for failures
            failed_hosts = [
                i for i, result in self.upload_results.items()
                if result.get("status") == "failed"
            ]

            if failed_hosts:
                failed_host_names = [self.hosts[i] for i in failed_hosts]
                error_msg = f"بعض مواقع الرفع فشلت: {', '.join(failed_host_names)}"
                logging.error(f"❌ {error_msg}")
                return {"error": error_msg}

            # Organize URLs by host
            links = {
                "rapidgator": [],
                "ddownload": [],
                "katfile": [],
                "nitroflare": [],
                "uploady": [],
                "rapidgator_bak": [],
            }

            all_urls = []
            backup_pattern = re.compile(r"(bak|backup)$", re.IGNORECASE)

            for i, host in enumerate(self.hosts):
                result = self.upload_results.get(i, {})
                urls = _normalize_links(result.get("urls", []))

                if not urls:
                    continue

                # Determine host category
                norm_host = host.lower().replace("-", "").replace("_", "")
                is_rg_backup = "rapidgator" in norm_host and bool(backup_pattern.search(norm_host))

                # Map to standard key
                key = "rapidgator_bak" if is_rg_backup else host.lower().replace("-", "_")

                if key in links:
                    links[key] = urls

                # Add to all_urls if not backup
                if not is_rg_backup:
                    all_urls.extend(urls)

            # Handle Keeplinks
            keeplink = self.keeplinks_url or ""
            all_success = all(
                res.get("status") == "success"
                for res in self.upload_results.values()
            )

            if all_urls and all_success and not self.keeplinks_sent:
                if not keeplink and hasattr(self.bot, 'send_to_keeplinks'):
                    try:
                        logging.debug(f"📤 Sending {len(all_urls)} links to Keeplinks")
                        keeplink = self.bot.send_to_keeplinks(all_urls)
                        if keeplink:
                            self.keeplinks_url = keeplink
                    except Exception as kl_e:
                        logging.warning(f"⚠️ Keeplinks failed: {kl_e}")

                self.keeplinks_sent = True

            # Build canonical response
            canonical = {}

            # Map hosts to canonical names
            host_mappings = {
                "rapidgator": "rapidgator.net",
                "ddownload": "ddownload.com",
                "katfile": "katfile.com",
                "nitroflare": "nitroflare.com",
                "uploady": "uploady.io",
                "rapidgator_bak": "rapidgator-backup"
            }

            for key, urls in links.items():
                if urls and key in host_mappings:
                    canonical_key = host_mappings[key]
                    canonical[canonical_key] = {
                        "urls": urls,
                        "is_backup": (key == "rapidgator_bak")
                    }

                    # Remove is_backup for non-backup hosts
                    if key != "rapidgator_bak":
                        canonical[canonical_key].pop("is_backup", None)

            # Add keeplink if available
            if keeplink:
                canonical["keeplinks"] = keeplink

            # Add metadata
            canonical.update({
                "thread_id": str(getattr(self, "thread_id", "")),
                "package": self.package_label,
            })

            return canonical

        except Exception as e:
            error_msg = f"خطأ في تحضير الروابط النهائية: {str(e)}"
            logging.error(f"❌ {error_msg}", exc_info=True)
            return {"error": error_msg}

    def _handle_successful_completion(self):
        """Handle successful completion of uploads"""
        try:
            # Prepare final results
            final_result = self._prepare_final_urls()

            # Update host results with keeplinks
            keeplink = final_result.get("keeplinks")
            if keeplink and "keeplinks" not in self._host_results:
                if isinstance(keeplink, dict):
                    urls = keeplink.get("urls") or keeplink.get("url") or []
                    urls = [urls] if isinstance(urls, str) else list(urls)
                else:
                    urls = [keeplink] if isinstance(keeplink, str) else []

                if urls:
                    self._host_results["keeplinks"] = {"urls": urls}

            # Check for errors
            if "error" in final_result:
                self.upload_error.emit(self.row, final_result["error"])
                self.upload_complete.emit(self.row, {
                    **final_result,
                    "host_results": self._host_results
                })
                return

            # Emit final status updates
            self._emit_final_statuses(self.row)

            # Build links payload for OperationStatus
            links_payload = {}
            canonical_to_internal = {
                "rapidgator.net": "rapidgator",
                "ddownload.com": "ddownload",
                "katfile.com": "katfile",
                "nitroflare.com": "nitroflare",
                "uploady.io": "uploady",
                "rapidgator-backup": "rapidgator_bak"
            }

            for canonical_key, internal_key in canonical_to_internal.items():
                host_data = final_result.get(canonical_key, {})
                if isinstance(host_data, dict):
                    links_payload[internal_key] = host_data.get("urls", [])
                else:
                    links_payload[internal_key] = []

            # Final operation status
            status = OperationStatus(
                section=self.section,
                item=self.files[0].name if self.files else "",
                op_type=OpType.UPLOAD,
                stage=OpStage.FINISHED,
                message="Complete",
                progress=100,
                thread_id=final_result.get("thread_id", ""),
                links=links_payload,
                keeplinks_url=final_result.get("keeplinks", ""),
            )

            self.progress_update.emit(status)
            self.upload_success.emit(self.row)
            self.upload_complete.emit(self.row, {
                **final_result,
                "host_results": self._host_results
            })

            # Log performance metrics
            total_files = len(self.files)
            duration = time.time() - self.operation_start_time

            logging.info(f"✅ Upload completed successfully!")
            logging.info(f"   📊 Files: {total_files}")
            logging.info(f"   ⏱️ Duration: {duration:.1f}s")
            logging.info(f"   📈 Performance: {self.performance_metrics}")

        except Exception as e:
            logging.error(f"❌ Error in successful completion handler: {e}", exc_info=True)
            self._handle_critical_error(e)

    def _handle_failed_completion(self):
        """Handle failed completion of uploads"""
        try:
            error_msg = "فشلت جميع عمليات الرفع"

            # Collect specific error information
            errors = []
            for idx, result in self.upload_results.items():
                if result.get("error"):
                    host = self.hosts[idx] if idx < len(self.hosts) else f"Host {idx}"
                    errors.append(f"{host}: {result['error']}")

            if errors:
                error_msg += f" - {'; '.join(errors[:3])}"  # Limit to first 3 errors
                if len(errors) > 3:
                    error_msg += f" (و {len(errors) - 3} أخطاء أخرى)"

            self.upload_error.emit(self.row, error_msg)
            self.upload_complete.emit(self.row, {
                "error": error_msg,
                "host_results": self._host_results
            })

            logging.error(f"❌ Upload failed: {error_msg}")

        except Exception as e:
            logging.error(f"❌ Error in failed completion handler: {e}")
            self._handle_critical_error(e)

    def _handle_critical_error(self, error: Exception):
        """Handle critical errors with comprehensive cleanup"""
        try:
            error_msg = str(error)

            if "cancelled" in error_msg.lower():
                self.upload_error.emit(self.row, "ألغي من المستخدم")
                self.upload_complete.emit(self.row, {
                    "error": "ألغي من المستخدم",
                    "host_results": self._host_results
                })
            else:
                logging.error(f"💥 UploadWorker critical error: {error_msg}", exc_info=True)

                # Color all hosts red in UI
                for idx in range(len(self.hosts)):
                    self.host_progress.emit(self.row, idx, 0, f"Error: {error_msg}", 0, 0)

                self.upload_error.emit(self.row, error_msg)
                self.upload_complete.emit(self.row, {
                    "error": error_msg,
                    "host_results": self._host_results
                })

        except Exception as handler_e:
            logging.critical(f"💥💥 Critical error handler failed: {handler_e}")

    def _emit_final_statuses(self, row: int):
        """Emit final status for each host with proper error handling"""
        try:
            cancel_stage = getattr(OpStage, "CANCELLED", OpStage.ERROR)
            item_name = self.files[0].name if self.files else ""

            for i, host in enumerate(self.hosts):
                try:
                    result = self.upload_results.get(i, {})
                    status = result.get("status", "not_attempted")

                    if status == "success":
                        stage = OpStage.FINISHED
                        msg = "Complete"
                        prog = 100
                    elif status == "failed":
                        stage = OpStage.ERROR
                        error = result.get("error", "Unknown error")
                        msg = f"Failed: {error}" if len(error) < 50 else "Failed"
                        prog = 0
                    elif status == "cancelled":
                        stage = cancel_stage
                        msg = "Cancelled"
                        prog = 0
                    else:
                        continue  # Skip unknown statuses

                    op_status = OperationStatus(
                        section=self.section,
                        item=item_name,
                        op_type=OpType.UPLOAD,
                        stage=stage,
                        message=msg,
                        progress=prog,
                        host=host,
                    )

                    self.progress_update.emit(op_status)
                    self.host_progress.emit(row, i, prog, msg, 0, 0)

                except Exception as emit_e:
                    logging.warning(f"⚠️ Failed to emit status for host {i}: {emit_e}")

        except Exception as e:
            logging.error(f"❌ Error emitting final statuses: {e}")

    def _cleanup_resources(self):
        """Comprehensive resource cleanup"""
        try:
            logging.debug("🧹 Starting resource cleanup")

            # Stop health check timer
            if hasattr(self, 'health_check_timer') and self.health_check_timer:
                try:
                    self.health_check_timer.stop()
                    self.health_check_timer.deleteLater()
                    self.health_check_timer = None
                except Exception as timer_e:
                    logging.warning(f"⚠️ Timer cleanup failed: {timer_e}")

            # Shutdown thread pool
            if hasattr(self, 'thread_pool') and self.thread_pool:
                try:
                    self.thread_pool.shutdown(wait=False)
                except Exception as pool_e:
                    logging.warning(f"⚠️ Thread pool cleanup failed: {pool_e}")

            # Clear handlers
            if hasattr(self, 'handlers'):
                for host, handler in self.handlers.items():
                    try:
                        if hasattr(handler, 'cleanup'):
                            handler.cleanup()
                    except Exception as handler_e:
                        logging.warning(f"⚠️ Handler cleanup failed for {host}: {handler_e}")
                self.handlers.clear()

            # Clear tracking data
            if hasattr(self, '_progress_trackers'):
                self._progress_trackers.clear()

            if hasattr(self, '_upload_metrics'):
                self._upload_metrics.clear()

            # Force garbage collection
            if hasattr(self, 'memory_manager'):
                self.memory_manager.force_garbage_collection()

            logging.debug("✅ Resource cleanup completed")

        except Exception as cleanup_e:
            logging.error(f"❌ Resource cleanup failed: {cleanup_e}")

    # Enhanced retry methods with comprehensive error handling
    @pyqtSlot(int)
    def retry_failed_uploads(self, row: int):
        """Retry failed uploads with enhanced error handling"""
        try:
            logging.info(f"🔄 Retrying failed uploads for row {row}")

            # Reset control state
            self._reset_control_for_retry()
            self._check_control()

            max_attempts = 3
            attempt = 0

            while attempt < max_attempts:
                # Find failed hosts
                failed_hosts = [
                    i for i, result in self.upload_results.items()
                    if result.get("status") == "failed"
                ]

                if not failed_hosts:
                    break

                logging.info(f"🔄 Retry attempt {attempt + 1}/{max_attempts}, failed hosts: {len(failed_hosts)}")

                # Reset failed hosts
                for i in failed_hosts:
                    self.upload_results[i] = {
                        "status": "not_attempted",
                        "urls": [],
                        "error": None,
                        "retry_count": attempt + 1
                    }

                    # Emit retry status
                    try:
                        status = OperationStatus(
                            section=self.section,
                            item=self.files[0].name if self.files else "",
                            op_type=OpType.UPLOAD,
                            stage=OpStage.RUNNING,
                            message="Retrying",
                            progress=0,
                            host=self.hosts[i],
                        )
                        self.progress_update.emit(status)
                        self.host_progress.emit(row, i, 0, "Retrying", 0, 0)
                    except Exception as emit_e:
                        logging.warning(f"⚠️ Failed to emit retry status: {emit_e}")

                # Execute retries
                futures = {}
                for i in failed_hosts:
                    try:
                        self._check_control()
                        future = self.thread_pool.submit(self._upload_host_all_safe, i)
                        futures[future] = i
                    except Exception as submit_e:
                        logging.error(f"❌ Failed to submit retry for host {i}: {submit_e}")
                        self.upload_results[i]["status"] = "failed"
                        self.upload_results[i]["error"] = str(submit_e)

                # Wait for completion
                for future in as_completed(futures, timeout=self.upload_timeout):
                    try:
                        self._check_control()
                        i = futures[future]
                        result = future.result(timeout=30)

                        self.upload_results[i]["status"] = (
                            "success" if result == "success" else "failed"
                        )

                    except Exception as future_e:
                        i = futures[future]
                        logging.error(f"❌ Retry future failed for host {i}: {future_e}")
                        self.upload_results[i]["status"] = "failed"
                        self.upload_results[i]["error"] = str(future_e)

                attempt += 1

                # Check if any failures remain
                remaining_failures = [
                    i for i, result in self.upload_results.items()
                    if result.get("status") == "failed"
                ]

                if not remaining_failures:
                    break

                # Brief pause between retry attempts
                if attempt < max_attempts:
                    time.sleep(2)

            # Finalize results
            final_result = self._prepare_final_urls()
            self._update_keeplinks_in_host_results(final_result)
            self._emit_final_statuses(row)

            if "error" not in final_result:
                self._emit_completion_status(final_result)

            self.upload_complete.emit(row, {
                **final_result,
                "host_results": self._host_results
            })

            logging.info("✅ Retry operation completed")

        except Exception as e:
            logging.error(f"❌ Retry failed uploads crashed: {e}", exc_info=True)
            self.upload_complete.emit(row, {
                "error": str(e),
                "host_results": self._host_results
            })

    @pyqtSlot(int)
    def resume_pending_uploads(self, row: int):
        """Resume pending uploads with comprehensive error handling"""
        try:
            logging.info(f"▶️ Resuming pending uploads for row {row}")

            self._reset_control_for_retry()

            # Find hosts to resume
            to_retry = [
                i for i, result in self.upload_results.items()
                if result.get("status") in ("failed", "cancelled", "not_attempted")
            ]

            if not to_retry:
                logging.info("ℹ️ No uploads to resume, finalizing current state")
                self._finalize_current_state(row)
                return

            logging.info(f"🔄 Resuming {len(to_retry)} uploads")

            # Reset hosts to resume
            for i in to_retry:
                self.upload_results[i] = {
                    "status": "not_attempted",
                    "urls": [],
                    "error": None,
                    "retry_count": 0
                }

                # Emit resuming status
                self._emit_resuming_status(row, i)

            # Execute uploads
            futures = {}
            for i in to_retry:
                try:
                    self._check_control()
                    future = self.thread_pool.submit(self._upload_host_all_safe, i)
                    futures[future] = i
                except Exception as submit_e:
                    logging.error(f"❌ Failed to submit resume for host {i}: {submit_e}")
                    self.upload_results[i]["status"] = "failed"
                    self.upload_results[i]["error"] = str(submit_e)

            # Wait for completion
            for future in as_completed(futures, timeout=self.upload_timeout):
                try:
                    self._check_control()
                    i = futures[future]
                    result = future.result(timeout=30)

                    self.upload_results[i]["status"] = (
                        "success" if result == "success" else "failed"
                    )

                except Exception as future_e:
                    i = futures[future]
                    logging.error(f"❌ Resume future failed for host {i}: {future_e}")
                    self.upload_results[i]["status"] = "failed"
                    self.upload_results[i]["error"] = str(future_e)

            # Finalize
            self._finalize_resume_results(row)

        except Exception as e:
            logging.error(f"❌ Resume pending uploads crashed: {e}", exc_info=True)
            self.upload_complete.emit(row, {
                "error": str(e),
                "host_results": self._host_results
            })

    @pyqtSlot(int)
    def reupload_all(self, row: int):
        """Reupload all files with comprehensive error handling"""
        try:
            logging.info(f"🔄 Reuploading all files for row {row}")

            self._reset_control_for_retry()

            # Reset all uploads
            for i in range(len(self.hosts)):
                self.upload_results[i] = {
                    "status": "not_attempted",
                    "urls": [],
                    "error": None,
                    "retry_count": 0
                }

                # Emit reuploading status
                self._emit_reuploading_status(row, i)

            # Execute all uploads
            futures = {}
            for i in range(len(self.hosts)):
                try:
                    self._check_control()
                    future = self.thread_pool.submit(self._upload_host_all_safe, i)
                    futures[future] = i
                except Exception as submit_e:
                    logging.error(f"❌ Failed to submit reupload for host {i}: {submit_e}")
                    self.upload_results[i]["status"] = "failed"
                    self.upload_results[i]["error"] = str(submit_e)

            # Wait for completion
            for future in as_completed(futures, timeout=self.upload_timeout):
                try:
                    self._check_control()
                    i = futures[future]
                    result = future.result(timeout=30)

                    self.upload_results[i]["status"] = (
                        "success" if result == "success" else "failed"
                    )

                except Exception as future_e:
                    i = futures[future]
                    logging.error(f"❌ Reupload future failed for host {i}: {future_e}")
                    self.upload_results[i]["status"] = "failed"
                    self.upload_results[i]["error"] = str(future_e)

            # Finalize
            self._finalize_reupload_results(row)

        except Exception as e:
            logging.error(f"❌ Reupload all crashed: {e}", exc_info=True)
            self.upload_complete.emit(row, {
                "error": str(e),
                "host_results": self._host_results
            })

    # Helper methods for retry operations
    def _update_keeplinks_in_host_results(self, final_result: dict):
        """Update host results with keeplinks information"""
        try:
            keeplink = final_result.get("keeplinks")
            if keeplink and "keeplinks" not in self._host_results:
                if isinstance(keeplink, dict):
                    urls = keeplink.get("urls") or keeplink.get("url") or []
                    urls = [urls] if isinstance(urls, str) else list(urls)
                else:
                    urls = [keeplink] if isinstance(keeplink, str) else []

                if urls:
                    self._host_results["keeplinks"] = {"urls": urls}
        except Exception as e:
            logging.warning(f"⚠️ Failed to update keeplinks: {e}")

    def _emit_completion_status(self, final_result: dict):
        """Emit completion status with proper links payload"""
        try:
            # Build links payload using canonical host keys
            links_payload = {}
            canonical_mappings = {
                "rapidgator.net": "rapidgator",
                "ddownload.com": "ddownload",
                "katfile.com": "katfile",
                "nitroflare.com": "nitroflare",
                "uploady.io": "uploady",
                "rapidgator-backup": "rapidgator_bak"
            }

            for canonical_key, internal_key in canonical_mappings.items():
                host_data = final_result.get(canonical_key, {})
                if isinstance(host_data, dict):
                    links_payload[internal_key] = host_data.get("urls", [])
                else:
                    links_payload[internal_key] = []

            status = OperationStatus(
                section=self.section,
                item=self.files[0].name if self.files else "",
                op_type=OpType.UPLOAD,
                stage=OpStage.FINISHED,
                message="Complete",
                progress=100,
                thread_id=final_result.get("thread_id", ""),
                links=links_payload,
                keeplinks_url=final_result.get("keeplinks", ""),
            )

            self.progress_update.emit(status)

        except Exception as e:
            logging.warning(f"⚠️ Failed to emit completion status: {e}")

    def _finalize_current_state(self, row: int):
        """Finalize current state without new uploads"""
        try:
            final_result = self._prepare_final_urls()
            self._update_keeplinks_in_host_results(final_result)
            self._emit_final_statuses(row)

            if "error" not in final_result:
                self._emit_completion_status(final_result)

            self.upload_complete.emit(row, {
                **final_result,
                "host_results": self._host_results
            })
        except Exception as e:
            logging.error(f"❌ Failed to finalize current state: {e}")

    def _emit_resuming_status(self, row: int, host_idx: int):
        """Emit resuming status for a host"""
        try:
            status = OperationStatus(
                section=self.section,
                item=self.files[0].name if self.files else "",
                op_type=OpType.UPLOAD,
                stage=OpStage.RUNNING,
                message="Resuming",
                progress=0,
                host=self.hosts[host_idx],
            )
            self.progress_update.emit(status)
            self.host_progress.emit(row, host_idx, 0, "Resuming", 0, 0)
        except Exception as e:
            logging.warning(f"⚠️ Failed to emit resuming status: {e}")

    def _emit_reuploading_status(self, row: int, host_idx: int):
        """Emit reuploading status for a host"""
        try:
            status = OperationStatus(
                section=self.section,
                item=self.files[0].name if self.files else "",
                op_type=OpType.UPLOAD,
                stage=OpStage.RUNNING,
                message="Re-uploading",
                progress=0,
                host=self.hosts[host_idx],
            )
            self.progress_update.emit(status)
            self.host_progress.emit(row, host_idx, 0, "Re-uploading", 0, 0)
        except Exception as e:
            logging.warning(f"⚠️ Failed to emit reuploading status: {e}")

    def _finalize_resume_results(self, row: int):
        """Finalize resume operation results"""
        try:
            final_result = self._prepare_final_urls()
            self._update_keeplinks_in_host_results(final_result)
            self._emit_final_statuses(row)

            if "error" not in final_result:
                self._emit_completion_status(final_result)

            self.upload_complete.emit(row, {
                **final_result,
                "host_results": self._host_results
            })

            logging.info("✅ Resume operation finalized")

        except Exception as e:
            logging.error(f"❌ Failed to finalize resume results: {e}")

    def _finalize_reupload_results(self, row: int):
        """Finalize reupload operation results"""
        try:
            final_result = self._prepare_final_urls()
            self._update_keeplinks_in_host_results(final_result)
            self._emit_final_statuses(row)

            if "error" not in final_result:
                self._emit_completion_status(final_result)

            self.upload_complete.emit(row, {
                **final_result,
                "host_results": self._host_results
            })

            logging.info("✅ Reupload operation finalized")

        except Exception as e:
            logging.error(f"❌ Failed to finalize reupload results: {e}")

    def __del__(self):
        """Enhanced destructor with comprehensive cleanup"""
        try:
            self._cleanup_resources()
        except Exception as e:
            logging.warning(f"⚠️ Destructor cleanup failed: {e}")