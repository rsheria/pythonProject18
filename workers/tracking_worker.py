# tracking_worker.py
import logging
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from datetime import datetime

class WorkerThread(QThread):
    update_threads = pyqtSignal(str, dict)
    users_updated = pyqtSignal(object)
    finished = pyqtSignal(str)

    def __init__(self, bot, bot_lock, category_manager, category_name, date_filter, page_from, page_to, mode):
        super().__init__()
        self.bot = bot
        self.bot_lock = bot_lock
        self.category_manager = category_manager
        self.category_name = category_name
        self.date_filter = date_filter
        self.page_from = page_from
        self.page_to = page_to
        self.mode = mode
        self._is_running = True

    def run(self):
        try:
            if self.mode == 'Track Once':
                self.track_once()
            elif self.mode == 'Keep Tracking':
                while self._is_running:
                    self.keep_tracking()
                    self.sleep(60)  # Sleep for 60 seconds before the next tracking cycle
        except Exception as e:
            logging.error(f"Exception in WorkerThread for category '{self.category_name}': {e}", exc_info=True)
        finally:
            self.finished.emit(self.category_name)

    def navigate_to_category(self, page_from, page_to):
        logging.info(f"WorkerThread: Navigating to category '{self.category_name}'.")
        with QMutexLocker(self.bot_lock):
            category_url = self.category_manager.get_category_url(self.category_name)
            logging.info(f"WorkerThread: Navigating to URL '{category_url}'")
            if not category_url:
                logging.warning(f"WorkerThread: URL for category '{self.category_name}' not found.")
                return False

            try:
                success = self.bot.navigate_to_url(category_url, self.date_filter, page_from, page_to)
                if success:
                    new_threads = self.bot.extracted_threads.copy()
                    logging.debug(
                        f"WorkerThread: New threads fetched for category '{self.category_name}': {new_threads}")
                    return new_threads
                else:
                    logging.warning(f"WorkerThread: Failed to navigate to category '{self.category_name}'.")
                    return None
            except Exception as e:
                logging.error(f"Exception during navigation for category '{self.category_name}': {e}", exc_info=True)
                return None

    def track_once(self):
        logging.info(f"WorkerThread: Tracking once for category '{self.category_name}'.")
            new_threads = self.navigate_to_category(self.page_from, self.page_to)
            if new_threads:
                self.update_threads.emit(self.category_name, new_threads)
                delta = self._build_user_delta(new_threads)
                if delta:
                    self.users_updated.emit(delta)

    def keep_tracking(self):
        logging.info(f"WorkerThread: Keeping track for category '{self.category_name}'.")
        while self._is_running:
            new_threads = self.navigate_to_category(1, 1)
            if new_threads:
                self.update_threads.emit(self.category_name, new_threads)
                delta = self._build_user_delta(new_threads)
                if delta:
                    self.users_updated.emit(delta)
            self.sleep(60)

    def stop(self):
        self._is_running = False

    # ------------------------------------------------------------------
    def _build_user_delta(self, threads: dict) -> dict:
        """Return a templab-compatible delta for ``threads``."""
        delta = {}
        for info in threads.values():
            username = info.get("author")
            if not username:
                continue
            thread_obj = {
                "id": info.get("thread_id"),
                "url": info.get("thread_url"),
                "title": info.get("thread_title") or info.get("title"),
                "date": info.get("thread_date", ""),
            }
            cat = self.category_name
            cat_map = delta.setdefault(cat, {})
            user_entry = cat_map.setdefault(
                username,
                {"threads": [], "last_seen": datetime.utcnow().isoformat()},
            )
            user_entry["threads"].append(thread_obj)
        return delta
