import logging
from PyQt5.QtCore import pyqtSignal, QMutexLocker
from .worker_thread import WorkerThread
from datetime import date, timedelta


def build_date_filter_list(days: int) -> list[str]:
    """
    بيرجع List بفلاتر التواريخ بناءً على عدد الأيام الأخيرة:
    بدلاً من إرجاع أيام منفصلة، يُرجع نطاق تاريخ واحد يشمل الفترة كاملة
    """
    today = date.today()
    
    if days <= 0:
        return []
        
    # Create date range from (today - days + 1) to today
    start_date = today - timedelta(days=days - 1)
    
    # Format as range if more than one day
    if days == 1:
        # Single day - just today
        return [f"{today.day:02d}.{today.month:02d}.{today.year}"]
    else:
        # Date range from start_date to today
        start_str = f"{start_date.day:02d}.{start_date.month:02d}.{start_date.year}"
        end_str = f"{today.day:02d}.{today.month:02d}.{today.year}"
        return [f"{start_str}→{end_str}"]


class MegaThreadsWorkerThread(WorkerThread):
    """
    QThread مسؤول عن جلب ومعالجة الميجاثريدز.
    يرث من WorkerThread عشان يدعم pause/cancel.
    """
    update_megathreads = pyqtSignal(str, dict)

    def __init__(self,
                 bot,
                 bot_lock,
                 category_manager,
                 category_name,
                 date_filters,
                 page_from,
                 page_to,
                 mode,
                 gui=None):
        super().__init__(
            bot,
            bot_lock,
            category_manager,
            category_name,
            date_filters,
            page_from,
            page_to,
            mode
        )
        self.gui = gui
        # ربط إشارة التحديث الخاصة بالـ posts إلى إشارة الميجاثريدز
        self.update_threads.connect(self.update_megathreads)

    def run(self):
        try:
            if self.mode == 'Track Once':
                self.track_once()
            else:
                while self._is_running:
                    self.track_once()
                    for _ in range(60):
                        if not self._is_running:
                            break
                        self.msleep(1000)
        finally:
            self.finished.emit(self.category_name)

    def track_once(self):
        logging.info(f"🔍 MegaThreadsWorkerThread: Starting track_once for '{self.category_name}'")
        
        # Check if we're already paused or cancelled to prevent redundant execution
        if hasattr(self, 'is_paused') and self.is_paused:
            logging.info(f"⏸️ Tracking paused for '{self.category_name}', skipping track_once")
            return
        if hasattr(self, 'is_cancelled') and self.is_cancelled:
            logging.info(f"❌ Tracking cancelled for '{self.category_name}', skipping track_once")
            return
            
        with QMutexLocker(self.bot_lock):
            url = self.category_manager.get_category_url(self.category_name)
            if not url:
                logging.warning(f"⚠️ No URL found for category '{self.category_name}'")
                return

            # بناء قائمة الفلاتر—إما من last_days_count أو من self.date_filters
            if hasattr(self, 'last_days_count') and isinstance(self.last_days_count, int):
                logging.info(f"📅 Using last_days_count={self.last_days_count} for '{self.category_name}'")
                df_list = build_date_filter_list(self.last_days_count)
            else:
                if isinstance(self.date_filters, list):
                    df_list = self.date_filters
                else:
                    df_list = self.date_filters.split(',') if self.date_filters else []
                logging.info(f"📅 Using date_filters={df_list} for '{self.category_name}'")

            logging.info(f"🌐 Navigating to megathread category: {url} with filters: {df_list}, pages: {self.page_from}-{self.page_to}")
            
            # ننادي مباشرة على دالة الميجاثريدز اللي بتعمل pagination
            new_versions = self.bot.navigate_to_megathread_category(
                url,
                df_list,
                self.page_from,
                self.page_to
            )

            # نبعت الإصدارات الجديدة إذا وجدت
            if isinstance(new_versions, dict) and new_versions:
                logging.info(f"✅ Found {len(new_versions)} new/updated versions for '{self.category_name}'")
                
                # Log details about each version found
                for title, version_data in new_versions.items():
                    if version_data.get('has_rapidgator'):
                        logging.info(f"🥇 RAPIDGATOR VERSION: '{title}' - Priority update!")
                    elif version_data.get('has_katfile'):
                        logging.info(f"🥈 KATFILE VERSION: '{title}' - Good quality update")
                    elif version_data.get('has_other_known_hosts'):
                        logging.info(f"🥉 KNOWN HOST VERSION: '{title}' - Standard update")
                    else:
                        logging.info(f"📝 MANUAL REVIEW VERSION: '{title}' - Needs attention")
                
                self.update_megathreads.emit(self.category_name, new_versions)
            else:
                logging.info(f"ℹ️ No new/updated versions found for '{self.category_name}' since last check")
