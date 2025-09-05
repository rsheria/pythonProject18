import inspect
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Lock
from urllib.parse import urlparse
# فوق مع الباقى
try:
    from integrations import jd_client
except ImportError:
    import jd_client

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from core.user_manager import get_user_manager
from downloaders.jdownloader import JDownloaderDownloader
from downloaders.katfile import KatfileDownloader
from downloaders.rapidgator import RapidgatorDownloader
from models.operation_status import OperationStatus, OpStage, OpType

from .worker_thread import WorkerThread
from .upload_worker import UploadWorker
from integrations.jd_client import hard_cancel
from utils.sanitize import sanitize_filename

def get_downloader_for(url: str, bot):
    """
    يُرجع الـ Downloader المناسب حسب المضيف:
      - JDownloader (Universal - يدعم جميع المضيفين المعروفين)
      - rapidgator => RapidgatorDownloader (fallback للsingle files)
      - katfile    => KatfileDownloader (fallback للsingle files)
      - المضيفين الجدد (xup.in, f2h.io, filepv.com, filespayouts.com, uploady.io) => JDownloader
      - غير مدعوم  => None
    """
    u = url.lower()
    is_folder_url = "/folder/" in u or "/archive/" in u
    
    # Define supported hosts by JDownloader
    supported_hosts = [
        "rapidgator.net",
        "nitroflare.com",
        "ddownload.com",
        "katfile.com",
        "mega.nz",
        "xup.in",
        "f2h.io",
        "filepv.com",
        "filespayouts.com",
        "uploady.io",  # New hosts
        "keeplinks.org",  # Keeplinks support
    ]
    if bot and hasattr(bot, "known_file_hosts"):
        supported_hosts = list(dict.fromkeys(supported_hosts + bot.known_file_hosts))
    # Check if host is supported
    is_supported_host = any(host in u for host in supported_hosts)
    
    if not is_supported_host:
        logging.warning(f"❌ Unsupported host detected: {url}")
        logging.info(f"💡 Supported hosts: {', '.join(supported_hosts)}")
        return None
    
    # Always use a single shared JDownloader instance for ALL supported hosts
    jd_downloader = None
    if bot is not None:
        jd_downloader = getattr(bot, "_shared_jd_downloader", None)
        if jd_downloader is None or not jd_downloader.is_available():
            jd_downloader = JDownloaderDownloader(bot)
            try:
                bot._shared_jd_downloader = jd_downloader
            except Exception:
                pass

    jd_available = jd_downloader.is_available() if jd_downloader else False
    if jd_available:
        # Identify host name for logging
        host_name = next((host for host in supported_hosts if host in u), "Unknown")
        
        # Special logging for premium hosts
        if "rapidgator" in u:
            logging.info(f"📥 Using JDownloader for RAPIDGATOR: {url}")
        elif "katfile" in u:
            logging.info(f"📥 Using JDownloader for KATFILE: {url}")
        elif any(
                host in u
                for host in [
                    "xup.in",
                    "f2h.io",
                    "filepv.com",
                    "filespayouts.com",
                    "uploady.io",
                ]
            ):
            logging.info(f"🆕 Using JDownloader for NEW HOST ({host_name}): {url}")
        else:
            logging.info(f"📥 Using JDownloader for {host_name.upper()}: {url}")
        
        return jd_downloader
    else:
        # JDownloader not available - no fallback
        logging.error(f"❌ JDownloader not available for: {url}")
        logging.info(f"💡 Please ensure JDownloader is running and connected")
        logging.info(f"🔧 Check JDownloader connection in the application settings")
        return None


class DownloadWorker(QThread):
    """
    QThread مسؤول عن إدارة التحميلات المتزامنة
    """
    status_update = pyqtSignal(str)
    file_progress = pyqtSignal(int, int)
    operation_complete = pyqtSignal(bool, str)
    file_created = pyqtSignal(str, str)
    file_progress_update = pyqtSignal(str, int, str, int, int, str, float, float)
    download_success = pyqtSignal(int)
    download_error = pyqtSignal(int, str)
    progress_update = pyqtSignal(object)  # OperationStatus

    def __init__(self, bot, file_processor, selected_rows, gui, cancel_event=None):
        super().__init__()
        self.bot = bot
        self.file_processor = file_processor
        self.selected_rows = selected_rows
        self.gui = gui

        self.is_cancelled = False
        self.is_paused = False
        self.cancel_event = cancel_event
        self.base_download_dir = Path(self.bot.download_dir)

        # الحد “المنطقي” الداخلي لو مش هنستخدم JD
        self.max_concurrent = 4
        # حد تغذية كبير عند توافر JDownloader (يغذي كل اللينكات)
        self.jd_bulk_limit = 256

        self.download_queue = Queue()
        self.active_link_downloads = {}
        self.thread_info_map = {}
        self.lock = Lock()

        # نخلي الـ executor على الحد الكبير؛ الجدولة هتتحكم بعدد المهام حسب وجود JD
        self.thread_pool = ThreadPoolExecutor(max_workers=self.jd_bulk_limit)

        # Get user manager for reading priority settings
        self.user_manager = get_user_manager()

        # 🆔 Session tracking to prevent cross-talk between download sessions
        import time
        self.worker_session_id = f"worker_{int(time.time() * 1000)}_{id(self)}"
        logging.info(
            f"🆕 DownloadWorker created with session ID: {self.worker_session_id}"
        )

        logging.debug(
            "DownloadWorker initialized, max_concurrent=%d", self.max_concurrent
        )

    # داخل الكلاس DownloadWorker
    def attach_jd_post(self, jd_post):
        """اربط نفس post() المستخدمة في الإضافة/المتابعة علشان الكانسيل يضرب نفس السيشن"""
        self._jd_post = jd_post

    def _is_cancelled(self):
        return self.is_cancelled or (self.cancel_event and self.cancel_event.is_set())
    def get_download_hosts_priority(self):
        """Get download hosts priority from user settings with fallback to defaults"""
        default_priority = [
            "rapidgator.net",  # Premium #1
            "katfile.com",  # Premium #2
            "nitroflare.com",  # Premium/Fast
            "ddownload.com",  # Fast/Free
            "mega.nz",  # Free/Fast
            "xup.in",  # New hosts in priority order
            "f2h.io",
            "filepv.com",
            "filespayouts.com",
            "uploady.io",
            "keeplinks.org",  # Keeplinks as fallback
        ]
        # Include any dynamically added hosts from the bot at the end of the priority list
        extra_hosts = []
        if self.bot and hasattr(self.bot, "known_file_hosts"):
            for h in self.bot.known_file_hosts:
                h = re.sub(r"^www\.", "", h.lower())
                if h not in default_priority and h not in extra_hosts:
                    extra_hosts.append(h)
        try:
            # Get priority from user settings
            priority = self.user_manager.get_user_setting(
                "download_hosts_priority", default_priority
            )
            if not isinstance(priority, list) or not priority:
                logging.warning(
                    "⚠️ Invalid download_hosts_priority in settings, using defaults"
                )
                priority = list(default_priority)

            # Append any extra hosts that aren't already in the priority list
            for h in extra_hosts:
                if h not in priority:
                    priority.append(h)
            
            logging.info(
                f"📋 Using custom download hosts priority: {priority[:3]}{'...' if len(priority) > 3 else ''}"
            )
            return priority
        except Exception as e:
            logging.error(
                f"❌ Error reading download_hosts_priority: {e}, using defaults"
            )
            return list(default_priority) + [
                h for h in extra_hosts if h not in default_priority
            ]

    def run(self):
        try:
            logging.info("DownloadWorker run() started")
            self.status_update.emit("Initializing downloads...")
            self.initialize_download_queue()

            # ===== JD pre-start cleanup (hard-cancel إن وُجد، وإلا helper مع فحص نتيجة) =====
            try:
                jd_post = getattr(self, "_jd_post", None)
                if not jd_post and getattr(self.bot, "_shared_jd_downloader", None):
                    dl = self.bot._shared_jd_downloader
                    if dl and dl.is_available():
                        jd_post = dl.post

                if jd_post:
                    logging.info("🛑 Hard-cancel (pre-start): stop/remove/clear")
                    hard_cancel(jd_post, logger=logging)

                    t0 = time.time()
                    while time.time() - t0 < 6.0:
                        dlnk = jd_post("downloadsV2/queryLinks", [{"maxResults": 1, "uuid": True}]) or []
                        lgk = jd_post("linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
                        if not dlnk and not lgk:
                            break
                        time.sleep(0.2)
                    logging.info("✅ JD cleanup before start done.")
                else:
                    logging.warning("⚠️ No JD session available for cleanup")

            except Exception as e:
                logging.warning("⚠️ pre-start cleanup failed: %s", e)

            total_threads = len(self.selected_rows)
            processed_threads = 0

            while not self._is_cancelled():
                # سلامة الووركر
                try:
                    if not hasattr(self, "active_link_downloads"):
                        logging.info("DownloadWorker: Object deleted, stopping execution")
                        break
                except RuntimeError:
                    logging.info("DownloadWorker: C++ object deleted, stopping execution")
                    break

                if self.cancel_event.is_set():
                    logging.info("⛔ Cancel detected inside loop, breaking out")
                    break

                # شغّل تحميلات جديدة — لو JD متاح: غذّي كل اللينكات (حتى 256)
                jd_available = False
                try:
                    dl = getattr(self.bot, "_shared_jd_downloader", None)
                    jd_available = (dl is not None and dl.is_available())
                except Exception:
                    jd_available = False

                limit = self.jd_bulk_limit if jd_available else self.max_concurrent

                while (
                        len(self.active_link_downloads) < limit
                        and not self.download_queue.empty()
                        and not self.cancel_event.is_set()
                ):
                    item = self.download_queue.get()
                    self.start_link_download(item)

                # لمّ المنتهى منهم (thread-safe)
                with self.lock:
                    finished = [lid for lid, info in self.active_link_downloads.items() if info.get("completed")]
                    for lid in finished:
                        try:
                            info = self.active_link_downloads.pop(lid)
                            tid = info["thread_id"]
                            if tid in self.thread_info_map:
                                self.thread_info_map[tid]["done_count"] += 1
                            for f in info["new_files"]:
                                if f not in self.thread_info_map[tid]["downloaded_files"]:
                                    self.thread_info_map[tid]["downloaded_files"].append(f)
                            if self.thread_info_map[tid]["done_count"] == self.thread_info_map[tid]["total_links"]:
                                processed_threads += 1
                                self.process_thread_files(tid)
                        except (KeyError, TypeError) as e:
                            logging.warning(f"⚠️ Error processing finished download {lid}: {e}")

                # تحديث التقدم العام
                if total_threads:
                    pct = int((processed_threads / total_threads) * 100)
                    self.status_update.emit(f"Overall Progress: {pct}% ({processed_threads}/{total_threads})")

                # خلّصنا؟
                if (
                        processed_threads == total_threads
                        and self.download_queue.empty()
                        and not self.active_link_downloads
                ):
                    break

                while self.is_paused and not self._is_cancelled():
                    time.sleep(0.1)
                if self.cancel_event.is_set():
                    logging.info("⛔ Cancel detected before sleep, exiting loop")
                    break

                time.sleep(0.1)

            # finish up
            if self._is_cancelled() or self.cancel_event.is_set():
                self.operation_complete.emit(False, "Operation cancelled.")
            else:
                self.operation_complete.emit(True, f"Completed {processed_threads}/{total_threads} threads")
        except Exception as e:
            logging.error("DownloadWorker crashed: %s", e, exc_info=True)
            self.operation_complete.emit(False, str(e))
        finally:
            self.thread_pool.shutdown(wait=False)
            logging.info("DownloadWorker: thread_pool shut down")

    def cancel_downloads(self):
        """✅ Cancel downloads in worker AND force-stop JDownloader sessions"""
        self.is_cancelled = True

        # أبلغ الواجهه وفعّل إشارة الإلغاء
        try:
            if getattr(self, "cancel_event", None):
                self.cancel_event.set()
                logging.info("🔒 cancel_event set, worker will stop ASAP")
        except Exception:
            pass
        try:
            self.status_update.emit("Cancelling downloads...")
        except Exception:
            pass
        logging.info("DownloadWorker: cancel_downloads invoked")

        # 1) JD force stop + cleanup (جرّب direct hard-cancel أولاً)
        did_force = False
        try:
            jd_post = getattr(self, "_jd_post", None)
            if not jd_post and getattr(self.bot, "_shared_jd_downloader", None):
                dl = self.bot._shared_jd_downloader
                if dl and dl.is_available():
                    jd_post = dl.post
            if jd_post:
                logging.info("🛑 Hard-cancel (user): stop/remove/clear")
                hard_cancel(jd_post, logger=logging)

                t0 = time.time()
                while time.time() - t0 < 6.0:
                    dlnk = jd_post("downloadsV2/queryLinks", [{"maxResults": 1, "uuid": True}]) or []
                    lgk = jd_post("linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
                    if not dlnk and not lgk:
                        break
                    time.sleep(0.2)
                did_force = True
            else:
                logging.warning("⚠️ No JD session available for cancel cleanup")
        except Exception as e:
            logging.error(f"⚠️ JD force cancel failed: {e}")

        # 2) نظّف الـ executors والـ queues محليًا
        try:
            if not hasattr(self, "lock") or self.lock is None:
                from threading import Lock
                self.lock = Lock()
            with self.lock:
                if hasattr(self, "thread_pool") and self.thread_pool:
                    try:
                        self.thread_pool.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        self.thread_pool.shutdown(wait=False)
                    self.thread_pool = None
                if hasattr(self, "executor") and self.executor:
                    try:
                        self.executor.shutdown(wait=False)
                    except Exception:
                        pass
                    self.executor = None
                # Clear active downloads map if present.  Use getattr
                # instead of hasattr with an extra argument (which raises TypeError)
                active_links = getattr(self, "active_link_downloads", None)
                if active_links is not None:
                    try:
                        active_links.clear()
                    except Exception:
                        # Ignore if already cleared or invalid
                        pass

                # Drain the download queue safely
                queue_obj = getattr(self, "download_queue", None)
                if queue_obj:
                    try:
                        while not queue_obj.empty():
                            try:
                                queue_obj.get_nowait()
                            except Exception:
                                break
                    except Exception:
                        pass
        except Exception as e:
            logging.warning(f"⚠️ Error during download cleanup: {e}")

        # 3) فولباك أخير لو مافيش direct post ولسه JD مش واقف
        if not did_force:
            logging.warning("⚠️ JD cleanup fallback skipped (no session)")

    def pause_downloads(self):
        self.is_paused = True
        self.status_update.emit("Downloads Paused")

    def resume_downloads(self):
        self.is_paused = False
        self.status_update.emit("Resuming Downloads")

    def initialize_download_queue(self):
        logging.debug("Selected rows: %s", self.selected_rows)
        logging.debug("Available categories: %s", list(self.gui.process_threads.keys()))

        for row in self.selected_rows:
            title_item = self.gui.process_threads_table.item(row, 0)
            cat_item = self.gui.process_threads_table.item(row, 1)
            id_item = self.gui.process_threads_table.item(row, 2)
            if not title_item or not cat_item or not id_item:
                logging.warning("Row %s missing table items, skipping", row)
                continue

            thread_title = title_item.text()
            category_name = cat_item.text()
            thread_id = id_item.text()
            logging.debug(
                "Row %d => title=%r, category=%r, id=%r",
                row,
                thread_title,
                category_name,
                thread_id,
            )

            if not thread_id:
                logging.warning("Empty thread_id at row %d, skipping", row)
                continue

            data = self.gui.process_threads.get(category_name, {})
            links_dict = data.get(thread_title, {}).get("links", {})
            logging.debug("links for '%s': %s", thread_title, links_dict)

            # Smart priority system from user settings
            priority_hosts = self.get_download_hosts_priority()

            # Organize links by priority
            organized_links = {}
            for host, lst in links_dict.items():
                h_lower = host.lower()
                for priority_host in priority_hosts:
                    if priority_host in h_lower:
                        if priority_host not in organized_links:
                            organized_links[priority_host] = []
                        organized_links[priority_host].extend(lst)
                        break

            # Select primary links based on priority
            primary = []
            selected_host = None
            for priority_host in priority_hosts:
                if priority_host in organized_links:
                    primary = organized_links[priority_host]
                    selected_host = priority_host
                    logging.info(
                        f"📥 Selected {priority_host} for '{thread_title}' (Priority #{priority_hosts.index(priority_host) + 1})"
                    )
                    break

            if not primary:
                msg = f"❌ No supported hosts found for '{thread_title}'. Available: {list(links_dict.keys())}"
                logging.warning(msg)
                self.status_update.emit(msg)
                continue

            # Set fallback links (all other available hosts)
            fallback = []
            for priority_host in priority_hosts:
                if priority_host in organized_links and priority_host != selected_host:
                    fallback.extend(organized_links[priority_host])

            self.thread_info_map[thread_id] = {
                "row": row,
                "category_name": category_name,
                "thread_title": thread_title,
                "downloaded_files": [],
                "total_links": len(primary),
                "done_count": 0,
            }
            thread_dir = Path(self._save_to_for(category_name, thread_id))

            for link in primary:
                link_id = str(uuid.uuid4())
                item = {
                    "link_id": link_id,
                    "row": row,
                    "thread_id": thread_id,
                    "category_name": category_name,
                    "thread_title": thread_title,
                    "link": link,
                    "fallback_links": fallback,
                    "thread_dir": thread_dir,
                    "completed": False,
                    "new_files": [],
                }
                logging.debug("Queueing link: %s", link)
                self.download_queue.put(item)

    def start_link_download(self, info):
        link_id = info["link_id"]
        self.active_link_downloads[link_id] = info

        # ✅ Better filename extraction for display
        filename = os.path.basename(info["link"])
        if not filename or filename.startswith("?") or len(filename) < 3:
            # Use thread title if URL filename is unclear
            filename = f"{info['thread_title'][:50]}... (from {info['link'][:30]}...)"
        elif len(filename) > 80:
            # Truncate very long filenames
            filename = filename[:77] + "..."

        # 🆔 Session-aware signal emission to prevent cross-talk
        logging.debug(
            f"📶 Emitting file_created signal (Session: {self.worker_session_id}, File: {filename})"
        )
        self.file_created.emit(link_id, filename)

        def download_job():
            logging.debug("Download job started for link_id=%s", link_id)
            start = time.time()

            def progress_cb(cur, tot, fn, *args):
                """🛡️ Protected progress callback with error handling"""
                try:
                    if self._is_cancelled():
                        return
                    while self.is_paused and not self._is_cancelled():
                        time.sleep(0.1)

                    # 🛡️ Validate inputs
                    if not hasattr(self, "file_progress") or cur is None or tot is None:
                        return

                    # Handle enhanced callback format from improved downloaders
                    if len(args) > 0 and isinstance(args[0], (int, float)):
                        # New format: progress_cb(cur, tot, display_name, progress_percent)
                        display_name = fn if fn else "Unknown"
                        progress_percent = args[0]
                        pct = max(0, min(100, int(progress_percent)))
                    else:
                        # Legacy format: progress_cb(cur, tot, filename)
                        display_name = fn if fn else "Unknown"
                        pct = max(0, min(100, int((cur / tot) * 100) if tot > 0 else 0))

                    # 🛡️ Safe signal emission
                    if hasattr(self, "file_progress") and "row" in info:
                        self.file_progress.emit(info["row"], pct)

                    # Calculate speed and ETA
                    elapsed = time.time() - start
                    speed = cur / elapsed if elapsed and cur else 0.0
                    eta = (tot - cur) / speed if speed and tot else 0.0
                    # Emit detailed OperationStatus for status table only when the
                    # download actually starts (progress > 0). This avoids showing
                    # an intermediate "waiting" row before JDownloader begins the
                    # real download.
                    if pct > 0:
                        host = urlparse(info.get("link", "")).hostname or "-"
                        status = OperationStatus(
                            section="Downloads",
                            item=info.get("thread_title", display_name),
                            op_type=OpType.DOWNLOAD,
                            stage=OpStage.RUNNING if pct < 100 else OpStage.FINISHED,
                            message="Downloading" if pct < 100 else "Complete",
                            progress=pct,
                            speed=speed,
                            eta=eta,
                            host=host,
                        )
                        self.progress_update.emit(status)
                    # 🛡️ Protected signal emission with session tracking
                    if hasattr(self, "file_progress_update"):
                        logging.debug(
                            f"📊 Emitting progress update (Session: {self.worker_session_id}, File: {display_name}, Progress: {pct}%)"
                        )
                        self.file_progress_update.emit(
                            link_id,
                            pct,
                            "Downloading",
                            cur,
                            tot,
                            display_name,
                            speed,
                            eta,
                        )

                except Exception as e:
                    logging.debug(f"Progress callback error (non-critical): {e}")

            url = info["link"]

            # unified download logic for all hosts (including Katfile)
            dl = get_downloader_for(url, self.bot)
            if not dl:
                err = f"No downloader for {url}"
                logging.error(err)

                # 🛡️ Protected error signal
                try:
                    if hasattr(self, "download_error"):
                        self.download_error.emit(info["row"], err)
                except Exception as e:
                    logging.debug(f"Error signal emission failed: {e}")

                info["completed"] = True
                return

            # Provide worker reference to downloader for JD hard cancel support
            try:
                dl.worker = self
            except Exception:
                pass
            # Try calling with download_info first
            try:
                sig = inspect.signature(dl.download)
                if "download_info" in sig.parameters:
                    success = dl.download(
                        url,
                        info["category_name"],
                        info["thread_id"],
                        info["thread_title"],
                        progress_callback=progress_cb,
                        download_dir=str(info["thread_dir"]),
                        download_info=info,

                    )
                else:
                    success = dl.download(
                        url,
                        info["category_name"],
                        info["thread_id"],
                        info["thread_title"],
                        progress_callback=progress_cb,
                        download_dir=str(info["thread_dir"]),
                    )
            except Exception as e:
                # Fallback to standard call
                success = dl.download(
                    url,
                    info["category_name"],
                    info["thread_id"],
                    info["thread_title"],
                    progress_callback=progress_cb,
                    download_dir=str(info["thread_dir"]),
                )

            # fallback attempts
            if not success:
                for alt in info.get("fallback_links", []):
                    self.status_update.emit(f"Fallback attempt: {alt}")
                    alt_dl = get_downloader_for(alt, self.bot)
                    if alt_dl:
                        try:
                            sig = inspect.signature(alt_dl.download)
                            if "download_info" in sig.parameters:
                                fallback_success = alt_dl.download(
                                    alt,
                                    info["category_name"],
                                    info["thread_id"],
                                    info["thread_title"],
                                    progress_callback=progress_cb,
                                    download_dir=str(info["thread_dir"]),
                                    download_info=info,
                                )
                            else:
                                fallback_success = alt_dl.download(
                                    alt,
                                    info["category_name"],
                                    info["thread_id"],
                                    info["thread_title"],
                                    progress_callback=progress_cb,
                                    download_dir=str(info["thread_dir"]),
                                )
                        except Exception:
                            # Basic fallback call
                            fallback_success = alt_dl.download(
                                alt,
                                info["category_name"],
                                info["thread_id"],
                                info["thread_title"],
                                progress_callback=progress_cb,
                                download_dir=str(info["thread_dir"]),
                            )

                        if fallback_success:
                            success = True
                            break

            if not success:
                err = f"Download failed => {url}"
                logging.error(err)

                # 🛡️ Protected error signal
                try:
                    if hasattr(self, "download_error"):
                        self.download_error.emit(info["row"], err)
                except Exception as e:
                    logging.debug(f"Error signal emission failed: {e}")

                info["completed"] = True
                return

            # record new files - check if JDownloader already populated new_files
            files_before_scan = len(info["new_files"])
            for f in info["thread_dir"].glob("*"):
                if f.is_file():
                    fp = str(f)
                    if fp not in info["new_files"]:
                        info["new_files"].append(fp)

                files_after_scan = len(info["new_files"])
            if files_after_scan > files_before_scan:
                logging.info(
                    f"📁 Found {files_after_scan - files_before_scan} additional files in thread directory"
                )
            elif files_before_scan > 0:
                logging.info(
                    f"📁 Using {files_before_scan} files from downloader (JDownloader)"
                )

            info["completed"] = True

            # 🛡️ Protected completion signals
            try:
                if hasattr(self, "file_progress_update") and info["new_files"]:
                    filename = (
                        os.path.basename(info["new_files"][-1])
                        if info["new_files"]
                        else "Unknown"
                    )
                    self.file_progress_update.emit(
                        link_id, 100, "Complete", 0, 0, filename, 0.0, 0.0
                    )

                if hasattr(self, "download_success"):
                    self.download_success.emit(info["row"])

            except Exception as e:
                logging.debug(f"Completion signal error (non-critical): {e}")

            logging.debug("Download job completed for link_id=%s", link_id)

        self.thread_pool.submit(download_job)

    def process_thread_files(self, thread_id):
        if self._is_cancelled():
            return
        info = self.thread_info_map[thread_id]
        row = info["row"]
        
        # Check both downloaded_files (legacy) and new_files (JDownloader)
        files = info.get("downloaded_files", []) or info.get("new_files", [])
        
        # Sync both for consistency
        if files:
            info["downloaded_files"] = files
            info["new_files"] = files
            
        if not files:
            self.status_update.emit(f"No files for '{info['thread_title']}', skipping.")
            return

        self.status_update.emit(f"Processing '{info['thread_title']}'")
        proc_status = OperationStatus(
            section="Downloads",
            item=info["thread_title"],
            op_type=OpType.DOWNLOAD,
            stage=OpStage.RUNNING,
            message="Processing files",
        )
        self.progress_update.emit(proc_status)
        try:
            td = Path(self._save_to_for(info["category_name"], thread_id))
            password = (
                self.gui.process_threads.get(info["category_name"], {})
                .get(info["thread_title"], {})
                .get("password")
            )
            processed = self.file_processor.process_downloads(
                td,
                files,
                info["thread_title"],
                password,
            )
            # Normalize processing result => List[Path]
            produced_paths: list[Path] = []
            if processed:
                if isinstance(processed, tuple):
                    root_dir, produced_files = processed
                    try:
                        produced_paths = [Path(p) for p in produced_files]
                    except Exception:
                        produced_paths = [Path(str(p)) for p in produced_files]
                elif isinstance(processed, (list, tuple, set)):
                    produced_paths = [Path(p) for p in processed]
                    root_dir = td
                elif isinstance(processed, (str, Path)):
                    produced_paths = [Path(processed)]
                    root_dir = td
                else:
                    produced_paths = []

            if produced_paths:
                # Choose main (largest) for persistence
                try:
                    main_path = max(produced_paths, key=lambda p: p.stat().st_size if p.exists() else -1)
                except ValueError:
                    main_path = produced_paths[0]
                self.file_progress.emit(row, 100)
                entry = self.gui.process_threads[info["category_name"]][
                    info["thread_title"]
                ]
                if main_path:
                    entry.update({"file_name": os.path.basename(str(main_path)), "file_path": str(main_path)})
                self.gui.save_process_threads_data()
                logging.info(
                    "Processed files for '%s': %d", info["thread_title"], len(produced_paths)
                )
                # Do NOT auto-upload here in normal Download flow.
                # Upload is triggered explicitly by the user or by Auto-Process.
                proc_status.stage = OpStage.FINISHED
                proc_status.message = "Processing complete"
                proc_status.progress = 100
                self.progress_update.emit(proc_status)
                self.download_success.emit(row)
            else:
                logging.warning("No processed output for '%s'", info["thread_title"])
                proc_status.stage = OpStage.ERROR
                proc_status.message = "Processing failed"
                self.progress_update.emit(proc_status)

        except Exception as e:
            err = f"Error processing '{info['thread_title']}': {e}"
            logging.error(err, exc_info=True)
            self.status_update.emit(err)
            proc_status.stage = OpStage.ERROR
            proc_status.message = err
            self.progress_update.emit(proc_status)
            self.download_error.emit(row, err)

    def _enqueue_links(self, links, job) -> bool:
        """Send links to JDownloader with a sanitized download path.

        Handles JD API quirks by trying ``downloadPath`` first and falling
        back to ``destinationFolder`` if necessary. Returns ``True`` on
        success, ``False`` otherwise.
        """

        # Resolve JD POST function
        jd_post = getattr(self, "_jd_post", None)
        if not jd_post:
            try:
                dl = getattr(self.bot, "_shared_jd_downloader", None)
                if dl and dl.is_available():
                    jd_post = dl.post
            except Exception:
                jd_post = None

        if not jd_post:
            logging.error("⚠️ No JDownloader session available for enqueue")
            return False

        save_to = self._save_to_for(job["category_name"], job["thread_id"])
        payload = {
            "links": "\n".join(links),
            "packageName": f'{job["thread_title"]}_{job["thread_id"]}',
            "downloadPath": save_to,
            "overwritePackagizerRules": True,
            "autostart": True,
        }

        logging.info(f"📁 JD enqueue downloadPath: {save_to}")
        res = jd_post("linkgrabberv2/addLinks", [payload])
        if not res:
            # Some JD versions reject 'downloadPath'; retry with 'destinationFolder'
            payload.pop("downloadPath", None)
            payload["destinationFolder"] = save_to
            logging.info(
                f"📁 JD enqueue retry with destinationFolder: {save_to}"
            )
            res = jd_post("linkgrabberv2/addLinks", [payload])
        return bool(res)

    def _save_to_for(self, category_name: str, thread_id: str) -> str:
        """Return the sanitized download path for a thread and ensure it exists."""
        cat = sanitize_filename(category_name)
        tid = sanitize_filename(thread_id)
        folder = self.base_download_dir / cat / tid
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder)
