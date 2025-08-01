# downloaders/rapidgator.py

import time
import logging
from .base_downloader import BaseDownloader
from core.selenium_bot import ForumBotSelenium


class RapidgatorDownloader(BaseDownloader):
    """
    Enhanced Rapidgator downloader with adaptive progress monitoring
    """

    def __init__(self, bot: ForumBotSelenium):
        super().__init__()
        self.bot = bot
        self.host_name = "Rapidgator"

    def download(
        self,
        url: str,
        category_name: str,
        thread_id: str,
        thread_title: str,
        progress_callback=None,
        download_dir=None
    ) -> str | None:
        """
        Enhanced download with adaptive progress monitoring and display names
        """
        if not progress_callback:
            # Use bot's original method if no progress callback
            return self.bot.download_rapidgator_net(
                url, category_name, thread_id, thread_title,
                progress_callback=None, download_dir=download_dir
            )
        
        # Enhanced progress wrapper with adaptive monitoring
        start_time = time.time()
        last_progress = -1
        last_activity_time = start_time
        
        def enhanced_progress_callback(downloaded, total, filename):
            nonlocal last_progress, last_activity_time
            
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Calculate progress percentage
            if total > 0:
                progress_percent = (downloaded / total) * 100
            else:
                progress_percent = 0
            
            # Only report significant changes (≥1% or every 5 seconds)
            progress_change = abs(progress_percent - last_progress)
            time_since_last = current_time - last_activity_time
            
            if progress_change >= 1.0 or time_since_last >= 5.0 or progress_percent >= 100:
                # Format display name with host info
                display_name = self.format_progress_display_name(filename, self.host_name)
                
                # Call enhanced progress callback
                try:
                    progress_callback(downloaded, total, display_name, progress_percent)
                    logging.debug(f"📊 Rapidgator progress: {progress_percent:.1f}% - {display_name}")
                except TypeError:
                    # Fallback to legacy callback format
                    progress_callback(downloaded, total, display_name)
                
                last_progress = progress_percent
                last_activity_time = current_time
        
        # Use bot's method with enhanced callback
        return self.bot.download_rapidgator_net(
            url, category_name, thread_id, thread_title,
            progress_callback=enhanced_progress_callback,
            download_dir=download_dir
        )
