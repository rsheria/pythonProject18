# downloaders/base_downloader.py

from abc import ABC, abstractmethod

class BaseDownloader(ABC):
    """
    واجهة (interface) لكل محمّل (Downloader).  
    يُرث منها كل downloader (Rapidgator, Katfile، إلخ).
    """
    
    def __init__(self, bot):
        """
        Initialize the downloader with bot instance
        """
        self.bot = bot

    @abstractmethod
    def download(
        self,
        url: str,
        category_name: str,
        thread_id: str,
        thread_title: str,
        progress_callback=None,
        download_dir=None
    ) -> bool:
        """
        تنزل الملف من الـ URL المعطى.  
        ترجع True لو نجح، False لو فشل.
        """
        pass
        
    def sanitize_filename(self, filename: str) -> str:
        """
        Clean filename for safe filesystem storage
        """
        import unicodedata
        import re
        nf = unicodedata.normalize("NFKD", filename)
        b = nf.encode("ascii", "ignore")
        s = b.decode("ascii", "ignore")
        return re.sub(r'[<>:"/\\|?*]', "", s).replace(" ", "_").strip()
    
    def get_adaptive_intervals(self):
        """
        Get adaptive monitoring intervals for all downloaders
        Returns: (fast_interval, normal_interval, slow_interval, fast_phase_duration)
        """
        return (
            0.1,   # Very fast for first 30 seconds (small files)
            0.5,   # Normal speed after fast phase  
            2.0,   # Slower for long downloads
            30     # First 30 seconds = fast checking
        )
    
    def calculate_adaptive_interval(self, elapsed_time: float, last_activity_time: float) -> float:
        """
        Calculate the appropriate monitoring interval based on elapsed time and activity
        """
        fast_interval, normal_interval, slow_interval, fast_phase_duration = self.get_adaptive_intervals()
        
        if elapsed_time < fast_phase_duration:
            # Fast phase - check every 0.1s for first 30 seconds
            return fast_interval
        elif elapsed_time - last_activity_time < 60:
            # Active phase - recent activity, check every 0.5s
            return normal_interval
        else:
            # Slow phase - no recent activity, check every 2s
            return slow_interval
    
    def format_progress_display_name(self, filename: str, host_name: str) -> str:
        """
        Format progress display name consistently across all downloaders
        Format: "Filename.ext - HostName"
        """
        if not filename or filename.strip() == "":
            return host_name
        
        # Clean filename for display
        clean_filename = filename.strip()
        if len(clean_filename) > 50:  # Truncate very long filenames
            clean_filename = clean_filename[:47] + "..."
        
        return f"{clean_filename} - {host_name}"
