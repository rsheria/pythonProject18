import os
import logging
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from enum import Enum
from typing import List, Optional, Any

from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot

from uploaders.rapidgator_upload_handler import RapidgatorUploadHandler
from uploaders.nitroflare_upload_handler import NitroflareUploadHandler
from uploaders.ddownload_upload_handler import DDownloadUploadHandler
from uploaders.katfile_upload_handler import KatfileUploadHandler

class UploadStatus(Enum):
    WAITING   = "waiting"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    ERROR     = "error"
    QUEUED    = "queued"

class UploadWorker(QThread):
    # Signals
    host_progress    = pyqtSignal(int, int, int, str, int, int)
    upload_complete  = pyqtSignal(int, dict)
    upload_success   = pyqtSignal(int)
    upload_error     = pyqtSignal(int, str)

    def __init__(
            self,
            bot,
            row: int,
            folder_path: str,
            thread_id: str,
            upload_hosts: Optional[List[str]] = None):
        super().__init__()  # QThread init
        self.bot = bot
        self.row = row
        self.folder_path = Path(folder_path)
        self.thread_id = thread_id
        self.config = bot.config  # Store config reference for quick access

        # تحكم بالإيقاف والإلغاء
        self.is_cancelled = False
        self.is_paused = False
        self.lock = Lock()

        # ThreadPool لرفع متوازٍ
        self.thread_pool = ThreadPoolExecutor(max_workers=5)

        # استرجِع قائمة الهوستات
        if upload_hosts is None:
            upload_hosts = bot.config.get('upload_hosts', [])

        self.hosts = list(upload_hosts)


        # Handlers (لمستضيفين لا يحتاجون مسار ملف عند الإنشاء)
        self.handlers: dict[str, Any] = {}
        if 'nitroflare' in self.hosts:
            self.handlers['nitroflare'] = NitroflareUploadHandler(self.bot)
        if 'ddownload' in self.hosts:
            self.handlers['ddownload'] = DDownloadUploadHandler(self.bot)
        if 'katfile' in self.hosts:
            self.handlers['katfile'] = KatfileUploadHandler(self.bot)
        # ملاحظة: Rapidgator handler سيُنشأ لكل ملف على حدة داخل ‎_upload_single

        # جمع الملفات
        self.files = self._get_files()
        self.total_files = len(self.files)
        if not self.files:
            logging.warning("UploadWorker: لا توجد ملفات في المجلد %s", folder_path)

        # تهيئة نتائج الرفع
        self.upload_results = {
            idx: {'status': 'not_attempted', 'urls': []}
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
        logging.info("UploadWorker: أُلغي الطلب")

    def _check_control(self):
        """
        يرفع استثناء لو تم الإلغاء،
        أو ينتظر بلا قفل لو حالتنا paused.
        """
        # أولاً: لو مُلغّى، نوقف فوراً
        with self.lock:
            if self.is_cancelled:
                raise Exception("Upload cancelled by user")

        # بعدين: لو متوقّف مؤقتاً، نعمل sleep خارج القفل
        while True:
            with self.lock:
                if self.is_cancelled:
                    raise Exception("Upload cancelled by user")
                paused = self.is_paused
            if not paused:
                break
            time.sleep(0.1)

    def run(self):
        try:
            if not self.files:
                msg = "لا توجد ملفات للرفع."
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(self.row, {'error': msg})
                return

            self._check_control()

            # إطلاق رفع كل مستضيف بالتوازي
            futures = {}
            for idx, _ in enumerate(self.hosts):
                self._check_control()
                futures[self.thread_pool.submit(self._upload_host_all, idx)] = idx

            # جمع النتائج
            for fut in as_completed(futures):
                self._check_control()
                idx = futures[fut]
                if fut.result() == 'success':
                    self.upload_results[idx]['status'] = 'success'
                else:
                    self.upload_results[idx]['status'] = 'failed'

            # تحضير القاموس النهائي مع Keeplinks
            final = self._prepare_final_urls()

            if 'error' in final:
                self.upload_error.emit(self.row, final['error'])
            else:
                self.upload_success.emit(self.row)

            self.upload_complete.emit(self.row, final)

        except Exception as e:
            msg = str(e)
            if "cancelled" in msg.lower():
                self.upload_error.emit(self.row, "أُلغي من المستخدم")
                self.upload_complete.emit(self.row, {'error': "أُلغي من المستخدم"})
            else:
                logging.error("UploadWorker.run crashed: %s", msg, exc_info=True)
                # تلوين كل الصفوف بالأحمر
                for idx in range(len(self.hosts)):
                    self.host_progress.emit(self.row, idx, 0, f"Error: {msg}", 0, 0)
                self.upload_error.emit(self.row, msg)
                self.upload_complete.emit(self.row, {'error': msg})

    def _upload_host_all(self, host_idx: int) -> str:
        urls = []
        for f in self.files:
            self._check_control()
            u = self._upload_single(host_idx, f)
            if u is None:
                return 'failed'
            urls.append(u)
        self.upload_results[host_idx]['urls'] = urls
        return 'success'

    # ---------------------------------------------------------------
    # 2) method  _upload_single
    # ---------------------------------------------------------------
    def _upload_single(self, host_idx: int, file_path: Path) -> Optional[str]:
        host = self.hosts[host_idx]

        # ─── Handler لكل مستضيف ─────────────────────────────────────
        if host in ('rapidgator', 'rapidgator-backup'):
            if host == 'rapidgator':
                token = (
                    self.config.get('rapidgator_api_token', '')
                    or getattr(self.bot, 'upload_rapidgator_token', '')
                    or getattr(self.bot, 'rg_main_token', '')
                )
                username = os.getenv('UPLOAD_RAPIDGATOR_USERNAME') or \
                           os.getenv('UPLOAD_RAPIDGATOR_LOGIN', '')
                password = os.getenv('UPLOAD_RAPIDGATOR_PASSWORD', '')

            else:  # rapidgator-backup
                token = (
                    self.config.get('rapidgator_backup_api_token', '')
                    or getattr(self.bot, 'rg_backup_token', '')
                    or getattr(self.bot, 'rapidgator_token', '')
                )
                username = os.getenv('RAPIDGATOR_LOGIN', '')
                password = os.getenv('RAPIDGATOR_PASSWORD', '')
            try:
                # Initialize handler with credentials for the correct account
                handler = RapidgatorUploadHandler(
                    filepath=file_path,
                    username=username,
                    password=password,
                    token=token
                )
                upload_func = lambda: handler.upload(progress_cb=cb)
            except Exception as e:
                logging.error(f"Failed to initialize Rapidgator handler: {e}", exc_info=True)
                self.host_progress.emit(self.row, host_idx, 0, f"Rapidgator init error: {str(e)}", 0, 0)
                return None
        else:
            handler = self.handlers.get(host)
            if not handler:
                logging.error("UploadWorker: لا يوجد handler للمستضيف %s", host)
                return None
            upload_func = lambda: handler.upload_file(str(file_path), progress_callback=cb)

        # ─── Progress callback ──────────────────────────────────────
        size = file_path.stat().st_size
        name = file_path.name

        def cb(curr, total):
            self._check_control()
            pct = int(curr / total * 100) if total else 0
            self.host_progress.emit(self.row, host_idx, pct, f"Uploading {name}", curr, total)

        # ─── رفع الملف ──────────────────────────────────────────────
        try:
            url = upload_func()
            self._check_control()

            if not url:
                self.host_progress.emit(self.row, host_idx, 0, f"Failed {name}", 0, size)
                return None

            self.host_progress.emit(self.row, host_idx, 100, f"Complete {name}", size, size)
            return url

        except Exception as e:
            msg = str(e)
            self.host_progress.emit(self.row, host_idx, 0, f"Error {name}: {msg}", 0, size)
            logging.error("UploadWorker: خطأ في رفع %s: %s", host, msg, exc_info=True)
            return None

    def _prepare_final_urls(self) -> dict:
        """Combine per-host URLs into one dict and optionally add Keeplinks."""
        self._check_control()

        # إذا أي مستضيف غير mega فشل → نرجع خطأ
        failed = any(
            self.upload_results[i]['status'] == 'failed'
            for i in range(len(self.hosts))
        )
        if failed:
            return {'error': 'بعض مواقع الرفع فشلت، يرجى المحاولة مرة أخرى.'}

        final = {}
        all_urls = []

        for i, host in enumerate(self.hosts):
            urls = self.upload_results[i]['urls']
            final[host] = urls
            # Exclude Rapidgator-backup links from the Keeplinks list
            if host != 'rapidgator-backup':
                all_urls.extend(urls)

        # Add Keeplinks if we have any URLs
        if all_urls:
            keeplink = self.bot.send_to_keeplinks(all_urls)
            if keeplink:
                final['keeplinks'] = keeplink

        return final

    @pyqtSlot(int)
    def retry_failed_uploads(self, row: int):
        """
        Retry only the hosts that previously فشلوا.
        """
        try:
            self._check_control()
            to_retry = [i for i, res in self.upload_results.items() if res['status'] == 'failed']
            if not to_retry:
                # لا شيء لإعادة المحاولة → أرسل الفواصل النهائية
                final = self._prepare_final_urls()
                self.upload_complete.emit(row, final)
                return

            # reset statuses
            for i in to_retry:
                self.upload_results[i] = {'status': 'not_attempted', 'urls': []}

            # إعادة رفعهم
            futures = {}
            for i in to_retry:
                self._check_control()
                futures[self.thread_pool.submit(self._upload_host_all, i)] = i

            for fut in as_completed(futures):
                self._check_control()
                i = futures[fut]
                if fut.result() == 'success':
                    self.upload_results[i]['status'] = 'success'
                else:
                    self.upload_results[i]['status'] = 'failed'

            final = self._prepare_final_urls()
            self.upload_complete.emit(row, final)
        except Exception as e:
            logging.error("retry_failed_uploads crashed: %s", e, exc_info=True)
            self.upload_complete.emit(row, {'error': str(e)})
