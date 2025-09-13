import logging
import os
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from integrations.jd_client import hard_cancel
from models.operation_status import OperationStatus, OpStage, OpType
from utils.utils import _normalize_links
from uploaders.ddownload_upload_handler import DDownloadUploadHandler
from uploaders.katfile_upload_handler import KatfileUploadHandler
from uploaders.nitroflare_upload_handler import NitroflareUploadHandler
from uploaders.rapidgator_upload_handler import RapidgatorUploadHandler
class UploadStatus(Enum):
    WAITING = "waiting"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    ERROR = "error"
    QUEUED = "queued"

class UploadWorker(QThread):
    # Signals
    host_progress = pyqtSignal(int, int, int, str, int, int)
    upload_complete = pyqtSignal(int, dict)
    upload_success = pyqtSignal(int)
    upload_error = pyqtSignal(int, str)
    progress_update = pyqtSignal(object)  # OperationStatus

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
        # ThreadPool لرفع متوازٍ
        self.thread_pool = ThreadPoolExecutor(max_workers=5)

        # استرجِع قائمة الهوستات
        if upload_hosts is None:
            upload_hosts = bot.config.get("upload_hosts", [])

        self.hosts = list(upload_hosts)


        # Handlers (لمستضيفين لا يحتاجون مسار ملف عند الإنشاء)
        self.handlers: dict[str, Any] = {}
        if "nitroflare" in self.hosts:
            self.handlers["nitroflare"] = NitroflareUploadHandler(self.bot)
        if "ddownload" in self.hosts:
            self.handlers["ddownload"] = DDownloadUploadHandler(self.bot)
        if "katfile" in self.hosts:
            self.handlers["katfile"] = KatfileUploadHandler(self.bot)
        # ملاحظة: Rapidgator handler سيُنشأ لكل ملف على حدة داخل ‎_upload_single

        # جمع الملفات
        self.explicit_files = [Path(f) for f in files] if files else None
        self.files = self.explicit_files or self._get_files()
        self.total_files = len(self.files)
        if not self.files:
            logging.warning("UploadWorker: لا توجد ملفات في المجلد %s", folder_path)

        # تهيئة نتائج الرفع
        self.upload_results = {
            idx: {"status": "not_attempted", "urls": []}
            for idx in range(len(self.hosts))
        }
        self._host_results: dict = {}

    def _get_files(self) -> List[Path]:
        return sorted(f for f in self.folder_path.iterdir() if f.is_file())

    def _host_from_url(self, url: str) -> str:
        """Extract hostname from *url* without ``www`` prefix."""
        try:
            from urllib.parse import urlparse
            host = (urlparse(url).netloc or "").lower()
            return host[4:] if host.startswith("www.") else host
        except Exception:
            return ""

    def _ext_from_name(self, name: str) -> str:
        """Return file extension without leading dot."""
        return Path(name).suffix.lower().lstrip(".")

    def _kind_from_name(self, name: str) -> str:
        """Classify filename into book/audio/other kinds."""
        ext = self._ext_from_name(name)
        # 1. Direct book formats
        if ext in {"pdf", "epub", "mobi", "azw3", "cbz", "cbr"}:
            return "book"
        # 2. Direct audio formats
        if ext in {"m4b", "mp3", "flac", "aac", "ogg", "m4a", "wav"}:
            return "audio"
        # 3. Archives: use the package_label as a hint
        if ext in {"rar", "zip", "7z"}:
            # If the worker was created with the 'audio' or 'book' label, assume archives are that type.
            if self.package_label == "audio":
                return "audio"
            if self.package_label == "book":
                return "book"
        # 4. Fallback
        return "other"

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
        with self.lock:
            self.is_cancelled = False
            self.is_paused = False
        if self.cancel_event:
            try:
                self.cancel_event.clear()
            except Exception:
                pass

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

    def run(self):
        try:
            logging.info(
                "Uploading from %s with %d files", self.folder_path, self.total_files
            )
            if not self.files:
                msg = "لا توجد ملفات للرفع."
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(
                    self.row, {"error": msg, "host_results": self._host_results}
                )
                return

            self._check_control()

            # إطلاق رفع كل مستضيف بالتوازي بدون إنشاء صف "Batch" في جدول الحالة.
            # سيتم تحديث جدول الحالة فقط لكل مستضيف على حدة أثناء رفع الملفات.

            # إطلاق رفع كل مستضيف بالتوازي
            futures = {}
            for idx, _ in enumerate(self.hosts):
                self._check_control()
                if self.upload_results.get(idx, {}).get("status") != "not_attempted":
                    continue
                futures[self.thread_pool.submit(self._upload_host_all, idx)] = idx

            # جمع النتائج
            completed = 0
            total = len(futures)
            for fut in as_completed(futures):
                self._check_control()
                idx = futures[fut]
                if fut.result() == "success":
                    self.upload_results[idx]["status"] = "success"
                else:
                    self.upload_results[idx]["status"] = "failed"
                completed += 1


            # Prepare final URLs dict using canonical schema
            final = self._prepare_final_urls()

            kl = final.get("keeplinks")
            if kl and "keeplinks" not in self._host_results:
                if isinstance(kl, dict):
                    urls = kl.get("urls") or kl.get("url") or []
                    urls = [urls] if isinstance(urls, str) else list(urls)
                else:
                    urls = [kl]
                if urls:
                    self._host_results["keeplinks"] = {"urls": urls}

            if "error" in final:
                self.upload_error.emit(self.row, final["error"])
                self.upload_complete.emit(
                    self.row, {**final, "host_results": self._host_results}
                )
                return

            # Update host progress/finish statuses
            self._emit_final_statuses(self.row)

            # Build links payload for OperationStatus using canonical keys
            def _get_urls(key: str) -> list:
                val = final.get(key)
                if isinstance(val, dict):
                    return val.get("urls", [])
                return val or []

            links_payload = {
                "rapidgator": _get_urls("rapidgator.net"),
                "ddownload": _get_urls("ddownload.com"),
                "katfile": _get_urls("katfile.com"),
                "nitroflare": _get_urls("nitroflare.com"),
                "rapidgator_bak": _get_urls("rapidgator-backup"),
            }
            status = OperationStatus(
                section=self.section,
                item=self.files[0].name if self.files else "",
                op_type=OpType.UPLOAD,
                stage=OpStage.FINISHED,
                message="Complete",
                progress=100,
                thread_id=final.get("thread_id", ""),
                links=links_payload,
                keeplinks_url=final.get("keeplinks", ""),
            )
            self.progress_update.emit(status)
            self.upload_success.emit(self.row)
            # Emit canonical final result
            self.upload_complete.emit(
                self.row, {**final, "host_results": self._host_results}
            )
            logging.info(
                "Finished uploading from %s with %d files",
                self.folder_path,
                self.total_files,
            )
        except Exception as e:
            msg = str(e)
            if "cancelled" in msg.lower():
                self.upload_error.emit(self.row, "أُلغي من المستخدم")
                self.upload_complete.emit(
                    self.row,
                    {"error": "أُلغي من المستخدم", "host_results": self._host_results},
                )
            else:
                logging.error("UploadWorker.run crashed: %s", msg, exc_info=True)
                # تلوين كل الصفوف بالأحمر
                for idx in range(len(self.hosts)):
                    self.host_progress.emit(self.row, idx, 0, f"Error: {msg}", 0, 0)
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(
                    self.row, {"error": msg, "host_results": self._host_results}
                )

    def _upload_host_all(self, host_idx: int) -> str:
        urls = []
        for f in self.files:
            self._check_control()
            u = self._upload_single(host_idx, f)
            if u is None:
                return "failed"
            urls.append(u)
            upload_host = self.hosts[host_idx]
            host = self._host_from_url(u)
            # Preserve explicit backup host instead of the generic rapidgator.net
            if upload_host == "rapidgator-backup":
                host = "rapidgator-backup"
            if host:
                kind = self._kind_from_name(f.name)
                ext = self._ext_from_name(f.name)
                bucket = self._host_results.setdefault(host, {"by_type": {}})
                if upload_host == "rapidgator-backup":
                    bucket["is_backup"] = True
                by_type = bucket.setdefault("by_type", {})
                type_bucket = by_type.setdefault(kind, {})
                if ext:
                    lst = type_bucket.setdefault(ext, [])
                    if u not in lst:
                        lst.append(u)
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
        # Throttle state: only emit progress updates at most every 100 ms
        last_emit_time = 0.0
        last_pct = -1
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
                stage=OpStage.RUNNING if pct < 100 else OpStage.FINISHED,
                message=f"Uploading {name}" if pct < 100 else "Complete",
                progress=pct,
                speed=speed,
                eta=eta,
                host=host,
            )
            # Emit progress updates throttled to reduce UI load
            nonlocal last_emit_time, last_pct
            now = time.time()
            # Only emit if progress changed and at least 100ms elapsed, or at completion
            if pct != last_pct and (now - last_emit_time >= 0.1 or pct >= 100):
                self.progress_update.emit(status)
                self.host_progress.emit(
                    self.row,
                    host_idx,
                    pct,
                    f"Uploading {name}" if pct < 100 else "Complete",
                    curr,
                    total,
                )
                last_emit_time = now
                last_pct = pct

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
                )
                self.progress_update.emit(status)
                self.host_progress.emit(
                    self.row, host_idx, 0, f"Failed {name}", 0, size
                )
                status = OperationStatus(
                    section=self.section,
                    item=name,
                    op_type=OpType.UPLOAD,
                    stage=OpStage.FINISHED,
                    message=f"Complete {name}",
                    progress=100,
                    host=host,
                )
                self.progress_update.emit(status)
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
            )
            self.progress_update.emit(status)
            self.host_progress.emit(
                self.row, host_idx, 0, f"Error {name}: {msg}", 0, size
            )
            logging.error("UploadWorker: خطأ في رفع %s: %s", host, msg, exc_info=True)
            return None

    def _prepare_final_urls(self) -> dict:
        """Normalize collected upload URLs into a stable payload."""
        self._check_control()
        failed = any(
            self.upload_results[i]["status"] == "failed" for i in range(len(self.hosts))
        )
        if failed:
            return {"error": "بعض مواقع الرفع فشلت، يرجى المحاولة مرة أخرى."}

        links: dict[str, list[str]] = {
            "rapidgator": [],
            "ddownload": [],
            "katfile": [],
            "nitroflare": [],
            "rapidgator_bak": [],
        }
        all_urls: list[str] = []
        backup_pattern = re.compile(r"(bak|backup)$", re.IGNORECASE)

        for i, host in enumerate(self.hosts):
            urls = _normalize_links(self.upload_results[i]["urls"])
            norm = host.lower().replace("-", "").replace("_", "")
            is_rg_backup = "rapidgator" in norm and bool(backup_pattern.search(norm))
            key = "rapidgator_bak" if is_rg_backup else host.lower().replace("-", "_")
            if key in links:
                links[key] = urls
            if not is_rg_backup:
                all_urls.extend(urls)

        keeplink = self.keeplinks_url or ""
        all_success = all(res["status"] == "success" for res in self.upload_results.values())
        if all_urls and all_success and not self.keeplinks_sent:
            if not keeplink:
                logging.debug("Sending %d links to Keeplinks", len(all_urls))
                k = self.bot.send_to_keeplinks(all_urls)
                if k:
                    keeplink = k
                    self.keeplinks_url = k
            self.keeplinks_sent = True

        # Assemble canonical mapping: host -> {'urls': [...], 'is_backup': bool}
        canonical: dict[str, dict] = {}
        # Main Rapidgator
        if links["rapidgator"]:
            canonical["rapidgator.net"] = {
                "urls": links["rapidgator"],
                "is_backup": False,
            }
        # DDownload
        if links["ddownload"]:
            canonical["ddownload.com"] = {
                "urls": links["ddownload"],
            }
        # Katfile
        if links["katfile"]:
            canonical["katfile.com"] = {
                "urls": links["katfile"],
            }
        # Nitroflare
        if links["nitroflare"]:
            canonical["nitroflare.com"] = {
                "urls": links["nitroflare"],
            }
        # Rapidgator backup
        if links["rapidgator_bak"]:
            canonical["rapidgator-backup"] = {
                "urls": links["rapidgator_bak"],
                "is_backup": True,
            }
        # Attach Keeplinks as string if available
        if keeplink:
            canonical["keeplinks"] = keeplink

        return {
            "thread_id": str(getattr(self, "thread_id", "")),
            "package": self.package_label,
            **canonical,
        }

    def _emit_final_statuses(self, row: int) -> None:
        """Emit final OperationStatus for each host so the UI recolors."""
        cancel_stage = getattr(OpStage, "CANCELLED", OpStage.ERROR)
        item_name = self.files[0].name if self.files else ""
        for i, host in enumerate(self.hosts):
            res = self.upload_results.get(i, {}).get("status")
            if res == "success":
                stage = OpStage.FINISHED
                msg = "Complete"
                prog = 100
            elif res == "failed":
                stage = OpStage.ERROR
                msg = "Failed"
                prog = 0
            elif res == "cancelled":
                stage = cancel_stage
                msg = "Cancelled"
                prog = 0
            else:
                continue

            status = OperationStatus(
                section=self.section,
                item=item_name,
                op_type=OpType.UPLOAD,
                stage=stage,
                message=msg,
                progress=prog,
                host=host,
            )
            self.progress_update.emit(status)
            self.host_progress.emit(row, i, prog, msg, 0, 0)

    # anchor: class UploadWorker, method retry_failed_uploads
    @pyqtSlot(int)
    def retry_failed_uploads(self, row: int):
        """
        Retry only the hosts that previously failed.
        """
        try:
            # Reset any pause/cancel flags before starting
            try:
                self._reset_control_for_retry()
            except Exception:
                self.is_cancelled = False
                self.is_paused = False
            self._check_control()

            attempt = 0
            max_attempts = 3
            # Continue retrying failed hosts until none remain or attempts exhausted
            while attempt < max_attempts:
                to_retry = [i for i, res in self.upload_results.items() if res.get("status") == "failed"]
                if not to_retry:
                    break

                # Reset statuses for hosts to retry
                for i in to_retry:
                    self.upload_results[i] = {"status": "not_attempted", "urls": []}
                    # Emit a RUNNING status for UI recolor
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

                # Submit uploads for hosts to retry
                futures = {}
                for i in to_retry:
                    self._check_control()
                    futures[self.thread_pool.submit(self._upload_host_all, i)] = i

                # Wait for all hosts to finish
                for fut in as_completed(futures):
                    self._check_control()
                    i = futures[fut]
                    self.upload_results[i]["status"] = (
                        "success" if fut.result() == "success" else "failed"
                    )

                # After this attempt, check if more failures remain
                attempt += 1
                remaining_failures = [
                    i for i, res in self.upload_results.items() if res.get("status") == "failed"
                ]
                if not remaining_failures:
                    break

            # Build final URLs and emit statuses
            final = self._prepare_final_urls()
            kl = final.get("keeplinks")
            if kl and "keeplinks" not in self._host_results:
                if isinstance(kl, dict):
                    urls = kl.get("urls") or kl.get("url") or []
                    urls = [urls] if isinstance(urls, str) else list(urls)
                else:
                    urls = [kl]
                if urls:
                    self._host_results["keeplinks"] = {"urls": urls}
            self._emit_final_statuses(row)
            # Emit a finished status if no error
            if "error" not in final:
                links_payload = {
                    "rapidgator": final.get("rapidgator", []),
                    "ddownload": final.get("ddownload", []),
                    "katfile": final.get("katfile", []),
                    "nitroflare": final.get("nitroflare", []),
                    "rapidgator_bak": final.get("rapidgator_backup", []),
                }
                status = OperationStatus(
                    section=self.section,
                    item=self.files[0].name if self.files else "",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.FINISHED,
                    message="Complete",
                    progress=100,
                    thread_id=final.get("thread_id", ""),
                    links=links_payload,
                    keeplinks_url=final.get("keeplinks", ""),
                )
                self.progress_update.emit(status)
            self.upload_complete.emit(row, {**final, "host_results": self._host_results})
        except Exception as e:
            logging.error("retry_failed_uploads crashed: %s", e, exc_info=True)
            self.upload_complete.emit(row, {"error": str(e), "host_results": self._host_results})

    @pyqtSlot(int)
    def resume_pending_uploads(self, row: int):
        try:
            self._reset_control_for_retry()
            to_retry = [
                i for i, res in self.upload_results.items() if res["status"] in ("failed", "cancelled")
            ]
            if not to_retry:
                final = self._prepare_final_urls()
                kl = final.get("keeplinks")
                if kl and "keeplinks" not in self._host_results:
                    if isinstance(kl, dict):
                        urls = kl.get("urls") or kl.get("url") or []
                        urls = [urls] if isinstance(urls, str) else list(urls)
                    else:
                        urls = [kl]
                    if urls:
                        self._host_results["keeplinks"] = {"urls": urls}
                self._emit_final_statuses(row)
                if "error" not in final:
                    # Build links payload using canonical host keys
                    links_payload = {
                        "rapidgator": (final.get("rapidgator.net") or {}).get("urls", []),
                        "ddownload": (final.get("ddownload.com") or {}).get("urls", []),
                        "katfile": (final.get("katfile.com") or {}).get("urls", []),
                        "nitroflare": (final.get("nitroflare.com") or {}).get("urls", []),
                        "rapidgator_bak": (final.get("rapidgator-backup") or {}).get("urls", []),
                    }
                    status = OperationStatus(
                        section=self.section,
                        item=self.files[0].name if self.files else "",
                        op_type=OpType.UPLOAD,
                        stage=OpStage.FINISHED,
                        message="Complete",
                        progress=100,
                        thread_id=final.get("thread_id", ""),
                        links=links_payload,
                        keeplinks_url=final.get("keeplinks", ""),
                    )
                    self.progress_update.emit(status)
                self.upload_complete.emit(row, {**final, "host_results": self._host_results})
                return
            for i in to_retry:
                self.upload_results[i] = {"status": "not_attempted", "urls": []}
                status = OperationStatus(
                    section=self.section,
                    item=self.files[0].name if self.files else "",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.RUNNING,
                    message="Resuming",
                    progress=0,
                    host=self.hosts[i],
                )
                self.progress_update.emit(status)
                self.host_progress.emit(row, i, 0, "Resuming", 0, 0)
            futures = {}
            for i in to_retry:
                self._check_control()
                futures[self.thread_pool.submit(self._upload_host_all, i)] = i
            for fut in as_completed(futures):
                self._check_control()
                i = futures[fut]
                if fut.result() == "success":
                    self.upload_results[i]["status"] = "success"
                else:
                    self.upload_results[i]["status"] = "failed"
            final = self._prepare_final_urls()
            kl = final.get("keeplinks")
            if kl and "keeplinks" not in self._host_results:
                if isinstance(kl, dict):
                    urls = kl.get("urls") or kl.get("url") or []
                    urls = [urls] if isinstance(urls, str) else list(urls)
                else:
                    urls = [kl]
                if urls:
                    self._host_results["keeplinks"] = {"urls": urls}
            self._emit_final_statuses(row)
            if "error" not in final:
                # Build links payload using canonical host keys
                links_payload = {
                    "rapidgator": (final.get("rapidgator.net") or {}).get("urls", []),
                    "ddownload": (final.get("ddownload.com") or {}).get("urls", []),
                    "katfile": (final.get("katfile.com") or {}).get("urls", []),
                    "nitroflare": (final.get("nitroflare.com") or {}).get("urls", []),
                    "rapidgator_bak": (final.get("rapidgator-backup") or {}).get("urls", []),
                }
                status = OperationStatus(
                    section=self.section,
                    item=self.files[0].name if self.files else "",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.FINISHED,
                    message="Complete",
                    progress=100,
                    thread_id=final.get("thread_id", ""),
                    links=links_payload,
                    keeplinks_url=final.get("keeplinks", ""),
                )
                self.progress_update.emit(status)
            self.upload_complete.emit(row, {**final, "host_results": self._host_results})
        except Exception as e:
            logging.error("resume_pending_uploads crashed: %s", e, exc_info=True)
            self.upload_complete.emit(row, {"error": str(e), "host_results": self._host_results})

    @pyqtSlot(int)
    def reupload_all(self, row: int):
        try:
            self._reset_control_for_retry()
            for i in range(len(self.hosts)):
                self.upload_results[i] = {"status": "not_attempted", "urls": []}
                status = OperationStatus(
                    section=self.section,
                    item=self.files[0].name if self.files else "",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.RUNNING,
                    message="Re-uploading",
                    progress=0,
                    host=self.hosts[i],
                )
                self.progress_update.emit(status)
                self.host_progress.emit(row, i, 0, "Re-uploading", 0, 0)
            futures = {}
            for i in range(len(self.hosts)):
                self._check_control()
                futures[self.thread_pool.submit(self._upload_host_all, i)] = i
            for fut in as_completed(futures):
                self._check_control()
                i = futures[fut]
                if fut.result() == "success":
                    self.upload_results[i]["status"] = "success"
                else:
                    self.upload_results[i]["status"] = "failed"
                final = self._prepare_final_urls()
                kl = final.get("keeplinks")
                if kl and "keeplinks" not in self._host_results:
                    if isinstance(kl, dict):
                        urls = kl.get("urls") or kl.get("url") or []
                        urls = [urls] if isinstance(urls, str) else list(urls)
                    else:
                        urls = [kl]
                    if urls:
                        self._host_results["keeplinks"] = {"urls": urls}
                self._emit_final_statuses(row)
            if "error" not in final:
                # Build links payload using canonical host keys
                links_payload = {
                    "rapidgator": (final.get("rapidgator.net") or {}).get("urls", []),
                    "ddownload": (final.get("ddownload.com") or {}).get("urls", []),
                    "katfile": (final.get("katfile.com") or {}).get("urls", []),
                    "nitroflare": (final.get("nitroflare.com") or {}).get("urls", []),
                    "rapidgator_bak": (final.get("rapidgator-backup") or {}).get("urls", []),
                }
                status = OperationStatus(
                    section=self.section,
                    item=self.files[0].name if self.files else "",
                    op_type=OpType.UPLOAD,
                    stage=OpStage.FINISHED,
                    message="Complete",
                    progress=100,
                    thread_id=final.get("thread_id", ""),
                    links=links_payload,
                    keeplinks_url=final.get("keeplinks", ""),
                )
                self.progress_update.emit(status)
            self.upload_complete.emit(row, {**final, "host_results": self._host_results})
        except Exception as e:
            logging.error("reupload_all crashed: %s", e, exc_info=True)
            self.upload_complete.emit(row, {"error": str(e), "host_results": self._host_results})
