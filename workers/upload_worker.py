import logging
import os
import queue
import time
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, List, Optional, Tuple

from PyQt5.QtCore import QThread, QThreadPool, QRunnable, pyqtSignal, pyqtSlot
from integrations.jd_client import hard_cancel
from models.operation_status import OperationStatus, OpStage, OpType
from uploaders.ddownload_upload_handler import DDownloadUploadHandler
from uploaders.katfile_upload_handler import KatfileUploadHandler
from uploaders.nitroflare_upload_handler import NitroflareUploadHandler
from uploaders.rapidgator_upload_handler import RapidgatorUploadHandler
from uploaders.uploady_upload_handler import UploadyUploadHandler
class UploadStatus(Enum):
    WAITING = "waiting"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    ERROR = "error"
    QUEUED = "queued"

class HostUploadRunnable(QRunnable):
    """Execute the upload of a single host inside the Qt thread pool."""

    def __init__(self, worker: "UploadWorker", host_idx: int, result_queue: "queue.Queue[tuple]"):
        super().__init__()
        self._worker = worker
        self._host_idx = host_idx
        self._result_queue = result_queue

    def run(self):  # noqa: D401 - matches QRunnable interface
        """Invoke the worker logic for a specific host and report the outcome."""
        try:
            result = self._worker._upload_host_all(self._host_idx)
            outcome = "success" if result == "success" else "failed"
            self._result_queue.put((outcome, self._host_idx, None))
        except Exception as exc:  # pragma: no cover - defensive logging path
            message = str(exc)
            self._worker._register_task_exception(self._host_idx, message)
            self._result_queue.put(("error", self._host_idx, message))


class RetryRunnable(QRunnable):
    """Run the retry logic inside the Qt thread pool to avoid UI blocking."""

    def __init__(self, worker: "UploadWorker"):
        super().__init__()
        self._worker = worker

    def run(self):  # noqa: D401 - matches QRunnable interface
        """Delegate to the worker retry routine."""
        self._worker._retry_in_background()


class UploadWorker(QThread):
    # Signals
    host_progress = pyqtSignal(int, int, int, str, int, int)
    upload_complete = pyqtSignal(int, dict)
    upload_success = pyqtSignal(int)
    upload_error = pyqtSignal(int, str)
    progress_update = pyqtSignal(OperationStatus)

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
        super().__init__()  # QThread init
        self.bot = bot
        self.row = row
        self.folder_path = Path(folder_path)
        self.thread_id = thread_id
        self.config = bot.config  # Store config reference for quick access
        self.section = section
        self.package_label = package_label
        # إذا كنا نعيد الرفع لروابط موجودة مسبقاً في Keeplinks،
        # نمرّر الرابط القديم كي لا يتم إنشاء رابط جديد.
        self.keeplinks_url = keeplinks_url
        self.keeplinks_sent = False
        # تحكم بالإيقاف والإلغاء
        self.is_cancelled = False
        self.is_paused = False
        self.lock = Lock()
        self.cancel_event = cancel_event
        self.retry_row = None  # Track row for retry operations

        # استرجِع قائمة الهوستات
        if upload_hosts is None:
            upload_hosts = bot.config.get("upload_hosts", [])

        self.hosts = list(upload_hosts)

        # Thread-pool orchestration managed by Qt to avoid mixing runtimes
        self._pool_lock = Lock()
        self._state_lock = Lock()
        self._qt_pool = QThreadPool()
        self._control_pool = QThreadPool()
        self._control_pool.setMaxThreadCount(1)
        self._task_errors: List[Tuple[int, str]] = []
        self._cancelled_during_run = False
        self._active_tasks: List[HostUploadRunnable] = []

        # Ensure pool size tracks available hosts
        max_threads = max(1, min(5, len(self.hosts) or 1))
        self._qt_pool.setMaxThreadCount(max_threads)


        # Handlers (لمستضيفين لا يحتاجون مسار ملف عند الإنشاء)
        self.handlers: dict[str, Any] = {}
        if "nitroflare" in self.hosts:
            self.handlers["nitroflare"] = NitroflareUploadHandler(self.bot)
        if "ddownload" in self.hosts:
            self.handlers["ddownload"] = DDownloadUploadHandler(self.bot)
        if "katfile" in self.hosts:
            self.handlers["katfile"] = KatfileUploadHandler(self.bot)
        if "uploady" in self.hosts:
            self.handlers["uploady"] = UploadyUploadHandler()
        # ملاحظة: Rapidgator handler سيُنشأ لكل ملف على حدة داخل ‎_upload_single

        # جمع الملفات مع حماية من التلف
        try:
            self.explicit_files = []
            if files:
                for f in files:
                    try:
                        # Validate each file path to prevent corruption
                        if f and (isinstance(f, (str, Path))):
                            path_obj = Path(f)
                            if path_obj.exists():
                                self.explicit_files.append(path_obj)
                            else:
                                logging.warning(f"File does not exist: {f}")
                        else:
                            logging.warning(f"Invalid file object: {f}")
                    except Exception as e:
                        logging.error(f"Error processing file {f}: {e}")
                        continue

            self.files = self.explicit_files if self.explicit_files else self._get_files()
            self.total_files = len(self.files) if self.files else 0

            if not self.files:
                logging.warning("UploadWorker: لا توجد ملفات في المجلد %s", folder_path)
        except Exception as e:
            logging.error(f"Critical error in UploadWorker file initialization: {e}")
            self.files = []
            self.explicit_files = []
            self.total_files = 0

        # تهيئة نتائج الرفع
        self.upload_results = {
            idx: {"status": "not_attempted", "urls": []}
            for idx in range(len(self.hosts))
        }

    def _get_files(self) -> List[Path]:
        return sorted(f for f in self.folder_path.iterdir() if f.is_file())

    @pyqtSlot()
    def pause_uploads(self):
        with self.lock:
            self.is_paused = True
        logging.info("UploadWorker: توقفت مؤقتًا")

    @pyqtSlot()
    def resume_uploads(self):
        with self.lock:
            self.is_paused = False
        logging.info("UploadWorker: استأنفت")

    @pyqtSlot()
    def cancel_uploads(self):
        with self.lock:
            self.is_cancelled = True
        if self.cancel_event:
            self.cancel_event.set()
        logging.info("UploadWorker: أُلغي الطلب")
        try:
            jd_downloader = getattr(self.bot, "_shared_jd_downloader", None)
            if jd_downloader and jd_downloader.is_available():
                hard_cancel(jd_downloader.post, logger=logging)
        except Exception:
            logging.exception("JDownloader cleanup failed during upload cancel")

    def _reset_control_for_retry(self):
        """Clear cancellation/paused flags before a retry attempt."""
        with self.lock:
            self.is_cancelled = False
            self.is_paused = False
            if self.cancel_event:
                self.cancel_event.clear()
    def _check_control(self):
        """
        يرفع استثناء لو تم الإلغاء،
        أو ينتظر بلا قفل لو حالتنا paused.
        """
        # أولاً: لو مُلغّى، نوقف فوراً
        with self.lock:
            if self.is_cancelled or (self.cancel_event and self.cancel_event.is_set()):
                raise Exception("Upload cancelled by user")

        # بعدين: لو متوقّف مؤقتاً، نعمل sleep خارج القفل
        while True:
            with self.lock:
                if self.is_cancelled or (self.cancel_event and self.cancel_event.is_set()):
                    raise Exception("Upload cancelled by user")
                paused = self.is_paused
            if not paused:
                break
            time.sleep(0.1)

    # ------------------------------------------------------------------
    # Thread-pool coordination helpers
    # ------------------------------------------------------------------
    def _reset_batch_state(self) -> None:
        with self._state_lock:
            self._cancelled_during_run = False
            self._task_errors = []

    def _register_task_exception(self, host_idx: int, message: str) -> None:
        with self._state_lock:
            self._task_errors.append((host_idx, message))
            if "cancelled" in message.lower():
                self._cancelled_during_run = True

    def _consume_batch_state(self) -> Tuple[bool, List[Tuple[int, str]]]:
        with self._state_lock:
            cancelled = self._cancelled_during_run
            errors = list(self._task_errors)
        return cancelled, errors

    def _configure_pool_for_hosts(self, host_count: int) -> None:
        threads = max(1, min(5, host_count or 1))
        self._qt_pool.setMaxThreadCount(threads)

    def _run_host_batch(self, host_indices: List[int]) -> Tuple[bool, List[Tuple[int, str]]]:
        if not host_indices:
            return False, []

        self._reset_batch_state()
        self._configure_pool_for_hosts(len(host_indices))

        result_queue: "queue.Queue[Tuple[str, int, Optional[str]]]" = queue.Queue()

        with self._pool_lock:
            self._active_tasks = []
            for host_idx in host_indices:
                runnable = HostUploadRunnable(self, host_idx, result_queue)
                self._active_tasks.append(runnable)
                self._qt_pool.start(runnable)

        pending = len(host_indices)
        while pending:
            outcome, host_idx, payload = result_queue.get()
            if outcome == "success":
                self.upload_results[host_idx]["status"] = "success"
            elif outcome == "failed":
                self.upload_results[host_idx]["status"] = "failed"
            elif outcome == "error":
                self.upload_results[host_idx]["status"] = "failed"
                # Message already registered by the runnable, preserve for logging
                if payload:
                    logging.debug(
                        "UploadWorker: host %s reported error: %s",
                        self.hosts[host_idx] if host_idx < len(self.hosts) else host_idx,
                        payload,
                    )
            pending -= 1

        self._qt_pool.waitForDone()
        with self._pool_lock:
            self._active_tasks = []

        return self._consume_batch_state()

    def _raise_if_batch_failed(self, cancelled: bool, errors: List[Tuple[int, str]]):
        if cancelled:
            raise Exception("Upload cancelled by user")
        if errors:
            # Surface the first error; detailed logging already captured
            msg = errors[0][1] if errors[0][1] else "Upload batch failed"
            raise Exception(msg)

    def run(self):
        try:
            if not self.files:
                msg = "لا توجد ملفات للرفع."
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(self.row, {"error": msg})
                return

            self._check_control()

            # إطلاق رفع كل مستضيف بالتوازي بدون إنشاء صف "Batch" في جدول الحالة.
            # سيتم تحديث جدول الحالة فقط لكل مستضيف على حدة أثناء رفع الملفات.
            host_indices = list(range(len(self.hosts)))
            cancelled, errors = self._run_host_batch(host_indices)
            self._raise_if_batch_failed(cancelled, errors)


            # تحضير القاموس النهائي مع Keeplinks
            final = self._prepare_final_urls()

            if "error" in final:
                # Send error completion status
                error_status = OperationStatus(
                    section=self.section,
                    item="Upload batch",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.ERROR,
                    message=final["error"],
                    progress=0,
                    host="",
                )
                self.progress_update.emit(error_status)
                self.upload_error.emit(self.row, final["error"])
            else:
                # Send final completion status for each file to mark them as finished
                for file_path in self.files:
                    success_status = OperationStatus(
                        section=self.section,
                        item=file_path.name,
                        op_type=OpType.UPLOAD,
                        stage=OpStage.FINISHED,
                        message="Upload completed successfully",
                        progress=100,
                        host="",
                        thread_id=self.thread_id,
                    )
                    self.progress_update.emit(success_status)
                self.upload_success.emit(self.row)

            self.upload_complete.emit(self.row, final)

        except Exception as e:
            msg = str(e)
            if "cancelled" in msg.lower():
                self.upload_error.emit(self.row, "أُلغي من المستخدم")
                self.upload_complete.emit(self.row, {"error": "أُلغي من المستخدم"})
            else:
                logging.error("UploadWorker.run crashed: %s", msg, exc_info=True)
                # تلوين كل الصفوف بالأحمر
                for idx in range(len(self.hosts)):
                    self.host_progress.emit(self.row, idx, 0, f"Error: {msg}", 0, 0)
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(self.row, {"error": msg})

    def _upload_host_all(self, host_idx: int) -> str:
        urls = []
        for f in self.files:
            self._check_control()
            u = self._upload_single(host_idx, f)
            if u is None:
                return "failed"
            urls.append(u)
        self.upload_results[host_idx]["urls"] = urls
        return "success"

    # ---------------------------------------------------------------
    # 2) method  _upload_single
    # ---------------------------------------------------------------
    def _upload_single(self, host_idx: int, file_path: Path) -> Optional[str]:
        host = self.hosts[host_idx]

        # ─── Handler لكل مستضيف ─────────────────────────────────────
        if host in ("rapidgator", "rapidgator-backup"):
            if host == "rapidgator":
                token = (
                    self.config.get("rapidgator_api_token", "")
                    or getattr(self.bot, "upload_rapidgator_token", "")
                    or getattr(self.bot, "rg_main_token", "")
                )
                username = os.getenv("UPLOAD_RAPIDGATOR_USERNAME") or os.getenv(
                    "UPLOAD_RAPIDGATOR_LOGIN", ""
                )
                password = os.getenv("UPLOAD_RAPIDGATOR_PASSWORD", "")

            else:  # rapidgator-backup
                token = (
                    self.config.get("rapidgator_backup_api_token", "")
                    or getattr(self.bot, "rg_backup_token", "")
                    or getattr(self.bot, "rapidgator_token", "")
                )
                username = os.getenv("RAPIDGATOR_LOGIN", "")
                password = os.getenv("RAPIDGATOR_PASSWORD", "")
            try:
                # Initialize handler with credentials for the correct account
                handler = RapidgatorUploadHandler(
                    filepath=file_path,
                    username=username,
                    password=password,
                    token=token,
                )
                upload_func = lambda: handler.upload(progress_cb=cb)
            except Exception as e:
                logging.error(
                    f"Failed to initialize Rapidgator handler: {e}", exc_info=True
                )
                self.host_progress.emit(
                    self.row, host_idx, 0, f"Rapidgator init error: {str(e)}", 0, 0
                )
                return None
        else:
            handler = self.handlers.get(host)
            if not handler:
                logging.error("UploadWorker: لا يوجد handler للمستضيف %s", host)
                return None
            upload_func = lambda: handler.upload_file(
                str(file_path), progress_callback=cb
            )


        # ─── Progress callback ──────────────────────────────────────
        size = file_path.stat().st_size
        name = file_path.name
        start = time.time()
        def cb(curr, total):
            self._check_control()
            pct = int(curr / total * 100) if total else 0
            elapsed = time.time() - start
            speed = curr / elapsed if elapsed and curr else 0.0
            eta = (total - curr) / speed if speed and total else 0.0
            status = OperationStatus(
                section=self.section,
                item=name,
                op_type=OpType.UPLOAD,
                stage=OpStage.RUNNING,  # Always keep running until entire upload is done
                message=f"Uploading {name}" if pct < 100 else "Complete",
                progress=pct,
                speed=speed,
                eta=eta,
                host=host,
                thread_id=self.thread_id,
            )
            self.progress_update.emit(status)
            self.host_progress.emit(
                self.row, host_idx, pct, f"Uploading {name}", curr, total
            )

        # ─── رفع الملف ──────────────────────────────────────────────
        try:
            url = upload_func()
            self._check_control()

            if not url:
                status = OperationStatus(
                    section=self.section,
                    item=name,
                    op_type=OpType.UPLOAD,
                    stage=OpStage.ERROR,
                    message=f"Failed {name}",
                    host=host,
                    thread_id=self.thread_id,
                )
                self.progress_update.emit(status)
                self.host_progress.emit(
                    self.row, host_idx, 0, f"Failed {name}", 0, size
                )
                # Don't emit FINISHED status here - this is just one file failing
                # The overall upload operation should continue
                return None

            self.host_progress.emit(
                self.row, host_idx, 100, f"Complete {name}", size, size
            )
            return url

        except Exception as e:
            msg = str(e)
            status = OperationStatus(
                section=self.section,
                item=name,
                op_type=OpType.UPLOAD,
                stage=OpStage.ERROR,
                message=f"Error {name}: {msg}",
                host=host,
                thread_id=self.thread_id,
            )
            self.progress_update.emit(status)
            self.host_progress.emit(
                self.row, host_idx, 0, f"Error {name}: {msg}", 0, size
            )
            logging.error("UploadWorker: خطأ في رفع %s: %s", host, msg, exc_info=True)
            return None

    def _prepare_final_urls(self) -> dict:
        """Combine per-host URLs into one dict and optionally add Keeplinks."""
        self._check_control()

        # إذا أي مستضيف غير mega فشل → نرجع خطأ
        failed = any(
            self.upload_results[i]["status"] == "failed" for i in range(len(self.hosts))
        )
        if failed:
            return {"error": "بعض مواقع الرفع فشلت، يرجى المحاولة مرة أخرى."}

        final = {}
        all_urls = []

        # Include thread_id in final result
        final["thread_id"] = self.thread_id

        for i, host in enumerate(self.hosts):
            urls = self.upload_results[i]["urls"]
            final[host] = urls
            # Exclude Rapidgator-backup links from the Keeplinks list
            if host != "rapidgator-backup":
                all_urls.extend(urls)

        # Add Keeplinks if we have any URLs
        if all_urls:
            if self.keeplinks_url:
                # استخدم الرابط القديم بدون إنشاء رابط جديد
                final["keeplinks"] = self.keeplinks_url
            else:
                keeplink = self.bot.send_to_keeplinks(all_urls)
                if keeplink:
                    final["keeplinks"] = keeplink

        return final

    @pyqtSlot(int)
    def retry_failed_uploads(self, row: int):
        """
        Signal to retry failed uploads - starts background retry process.
        """
        self.retry_row = row
        # Start retry in background Qt thread pool to avoid UI blocking
        self._control_pool.start(RetryRunnable(self))

    def _retry_in_background(self):
        """
        Retry only the hosts that previously failed - runs in background thread.
        """
        try:
            self._reset_control_for_retry()
            to_retry = [
                i for i, res in self.upload_results.items() if res["status"] == "failed"
            ]
            if not to_retry:
                final = self._prepare_final_urls()
                self.upload_complete.emit(self.retry_row, final)
                return

            for i in to_retry:
                self.upload_results[i] = {"status": "not_attempted", "urls": []}

                status = OperationStatus(
                    section=self.section,
                    item=f"Retry {self.hosts[i]}",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.RUNNING,
                    message=f"Retrying {self.hosts[i]}",
                    progress=0,
                    host=self.hosts[i],
                    thread_id=self.thread_id,
                )
                self.progress_update.emit(status)
                self.host_progress.emit(self.retry_row, i, 0, f"Retrying {self.hosts[i]}", 0, 0)

            self._check_control()
            cancelled, errors = self._run_host_batch(to_retry)
            self._raise_if_batch_failed(cancelled, errors)

            final = self._prepare_final_urls()

            # Send completion status for retry
            if "error" in final:
                retry_error_status = OperationStatus(
                    section=self.section,
                    item="Retry batch",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.ERROR,
                    message="Retry failed",
                    progress=0,
                    host="",
                )
                self.progress_update.emit(retry_error_status)
            else:
                # Send final completion status for each file to mark them as finished
                for file_path in self.files:
                    retry_success_status = OperationStatus(
                        section=self.section,
                        item=file_path.name,
                        op_type=OpType.UPLOAD,
                        stage=OpStage.FINISHED,
                        message="Retry completed successfully",
                        progress=100,
                        host="",
                        thread_id=self.thread_id,
                    )
                    self.progress_update.emit(retry_success_status)

            self.upload_complete.emit(self.retry_row, final)
        except Exception as e:
            logging.error("retry_failed_uploads crashed: %s", e, exc_info=True)
            self.upload_complete.emit(self.retry_row, {"error": str(e)})
