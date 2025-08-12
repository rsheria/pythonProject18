# downloaders/jdownloader.py

import os
import time
import logging
import shutil
import re
from typing import Optional, Dict, Any
from dotenv import load_dotenv

try:
    import myjdapi
    JDOWNLOADER_AVAILABLE = True
except ImportError:
    logging.warning("⚠️ myjdapi not available. JDownloader integration disabled.")
    JDOWNLOADER_AVAILABLE = False

from .base_downloader import BaseDownloader

# Load environment variables
load_dotenv()


class JDownloaderDownloader(BaseDownloader):
    """
    JDownloader API integration for universal downloading
    Falls back gracefully if JDownloader is not available
    """

    def __init__(self, bot):
        super().__init__(bot)
        cfg = getattr(bot, "config", {}) if bot and hasattr(bot, "config") else {}
        # Allow credentials to come from config, MYJD_*, or JDOWNLOADER_* env vars
        self.email = (
            cfg.get("myjd_email")
            or os.getenv("MYJD_EMAIL")
            or os.getenv("JDOWNLOADER_EMAIL", "")
        ).strip()
        self.password = (
            cfg.get("myjd_password")
            or os.getenv("MYJD_PASSWORD")
            or os.getenv("JDOWNLOADER_PASSWORD", "")
        ).strip()
        self.device_name = (
            cfg.get("myjd_device")
            or os.getenv("MYJD_DEVICE")
            or ""
        ).strip()
        self.app_key = (
            cfg.get("myjd_app_key")
            or os.getenv("MYJD_APP_KEY")
            or os.getenv("JDOWNLOADER_APP_KEY", "PyForumBot")
        ).strip()
        self.jd = None
        self.device = None
        self.is_connected = False
        
        # 🆔 SESSION TRACKING: Track current download session to prevent cross-talk
        import time
        self.current_session_id = None
        self.active_downloads = {}  # Track active downloads by session
        
        # Only initialize if JDownloader is available and credentials exist
        if JDOWNLOADER_AVAILABLE and self.email and self.password:
            self._initialize_connection()
    
    def _extract_host_name(self, url: str) -> str:
        """Extract host name from URL for display purposes"""
        try:
            host_map = {
                'rapidgator': 'Rapidgator',
                'katfile': 'Katfile',
                'mega.nz': 'Mega',
                'nitroflare': 'Nitroflare',
                'ddownload': 'DDownload',
                'xup.in': 'Xup.in',
                'f2h.io': 'F2H.io',
                'filepv.com': 'FilePV',
                'filespayouts.com': 'FilesPayouts',
                'uploady.io': 'Uploady',
                'keeplinks.org': 'Keeplinks',
            }

            parsed = re.findall(r"https?://(?:www\.)?([^/]+)/", url)
            if parsed:
                host = parsed[0].lower()
                for key, val in host_map.items():
                    if key in host:
                        return val
                # Generic host display
                host = host.split(':')[0]
                if host.startswith('www.'):
                    host = host[4:]
                return host
            return "JDownloader"
        except Exception:
            return "JDownloader"
    
    def format_progress_display_name(self, package_name: str, host_name: str) -> str:
        """Format progress display name with host information"""
        try:
            # Clean package name (remove common download artifacts)
            clean_name = package_name
            if '.' in clean_name:
                # Remove file extension for cleaner display
                clean_name = clean_name.rsplit('.', 1)[0]
            
            # Limit length for UI display
            if len(clean_name) > 40:
                clean_name = clean_name[:37] + "..."
            
            return f"[{host_name}] {clean_name}"
        except Exception:
            return f"[{host_name}] Download"

    def _initialize_connection(self) -> bool:
        """
        Initialize connection to JDownloader API
        Returns True if successful, False otherwise
        """
        try:
            logging.info("🔗 Initializing JDownloader connection...")
            
            self.jd = myjdapi.Myjdapi()
            self.jd.set_app_key(self.app_key)
            
            # Attempt connection
            if not self.jd.connect(self.email, self.password):
                logging.error("❌ Failed to connect to JDownloader API")
                return False
            
            # Get available devices
            devices = self.jd.list_devices()
            if not devices:
                logging.error("❌ No JDownloader devices found")
                self.jd.disconnect()
                return False

            # Select device: prefer configured name, fallback to first
            target_name = self.device_name or devices[0]['name']
            try:
                self.device = self.jd.get_device(target_name)
                if not self.device:
                    raise ValueError("Device not found")
            except Exception:
                logging.warning(
                    f"⚠️ Specified device '{target_name}' not found, using first available"
                )
                self.device = self.jd.get_device(devices[0]['name'])
            self.is_connected = True

            logging.info(f"✅ Connected to JDownloader device: {self.device.name}")
            return True
            
        except Exception as e:
            logging.error(f"❌ JDownloader connection error: {e}")
            self.is_connected = False
            return False

    def is_available(self) -> bool:
        """
        Check if JDownloader is available and configured
        """
        return (JDOWNLOADER_AVAILABLE and 
                self.email and 
                self.password and 
                self.is_connected)

    def download(
        self,
        url: str,
        category_name: str,
        thread_id: str,
        thread_title: str,
        progress_callback=None,
        download_dir: Optional[str] = None,
        download_info=None
    ) -> bool:
        """
        Download file using JDownloader API
        Returns True if successful, False if failed
        """
        
        # 🆔 CREATE UNIQUE SESSION for this download
        session_id = f"jd_{int(time.time() * 1000)}_{id(self)}"
        self.current_session_id = session_id
        logging.info(f"🆕 JDownloader starting new download session: {session_id}")
        
        # Check if JDownloader is available
        if not self.is_available():
            logging.warning("⚠️ JDownloader not available, will use fallback downloader")
            return False
            
        try:
            # 🧹 CLEAR OLD DOWNLOADS: Remove completed downloads to prevent stale progress
            logging.info(f"🧹 Cleaning up JDownloader queues before new download...")
            try:
                # Clear finished downloads from download list
                self.device.downloads.cleanup("DELETE_FINISHED", "REMOVE_LINKS_AND_DELETE_FILES", "ALL")
                logging.info("✅ Cleared finished downloads")
                
                # Clear linkgrabber entries
                self.device.linkgrabber.clear_list()
                logging.info("✅ Cleared linkgrabber queue")
                
                # ⏳ Wait for cleanup to complete
                time.sleep(2)
                logging.info("⏳ Waited for JDownloader cleanup to complete")
            except Exception as cleanup_error:
                logging.warning(f"⚠️ Could not clean JDownloader queues: {cleanup_error}")
            
            logging.info(f"📥 Starting JDownloader download: {url}")
            
            # Set download directory first if specified
            if download_dir:
                try:
                    # Ensure absolute existing directory for reliability on
                    # different systems
                    download_dir = os.path.abspath(os.path.expanduser(download_dir))
                    os.makedirs(download_dir, exist_ok=True)

                    # For Keeplinks, ensure we use the same download directory as Rapidgator
                    if 'keeplinks.org' in url.lower():
                        # Get the default download directory from settings
                        from config.config import load_configuration
                        config = load_configuration()
                        download_dir = config.get('download_dir', download_dir)
                        logging.info(f"🔗 Keeplinks: Using download directory: {download_dir}")
                    
                    # Try to set download directory for the device
                    try:
                        if hasattr(self.device.config, 'set'):
                            # Set the download directory specifically for this download
                            # This ensures Keeplinks respect the same path as other hosts
                            self.device.config.set(
                                "org.jdownloader.settings.GeneralSettings",
                                "defaultdownloadfolder",
                                download_dir
                            )
                            logging.info(f"📁 Set JDownloader download directory: {download_dir}")
                    except Exception as e:
                        logging.warning(f"⚠️ Could not set JDownloader config: {e}")
                        # Continue with package-based approach as fallback
                except Exception as e:
                    logging.warning(f"⚠️ Could not set download directory: {e}")
                    # Continue anyway, we'll move files later
            
            # Add to linkgrabber - let WinRAR handle password prompts naturally
            links_to_add = [{
                "links": url,
                "autostart": True,
                "downloadPassword": "",
                "extractPassword": "",  # Empty - WinRAR will prompt for password
                "priority": "HIGHEST",
                "packageName": f"{thread_title}_{thread_id}"
            }]
            
            if download_dir:
                links_to_add[0]["destinationFolder"] = download_dir
            
            # Add links to linkgrabber
            self.device.linkgrabber.add_links(links_to_add)
            
            # Wait a moment for processing
            time.sleep(3)
            
            # Monitor download progress and get downloaded files
            downloaded_files = self._monitor_download(url, progress_callback, download_dir)
            
            if downloaded_files:
                # Update download info with new files if provided
                if download_info:
                    # Ensure new_files exists
                    if 'new_files' not in download_info:
                        download_info['new_files'] = []
                    
                    for file_path in downloaded_files:
                        if file_path not in download_info['new_files']:
                            download_info['new_files'].append(file_path)
                            logging.info(f"➕ Added to download info: {file_path}")
                    
                    logging.info(f"📊 Updated info['new_files']: {download_info['new_files']}")
                
                logging.info(f"✅ JDownloader completed with {len(downloaded_files)} files")
                return True
            else:
                logging.error("❌ JDownloader download failed or no files found")
                return False
            
        except Exception as e:
            logging.error(f"❌ JDownloader download error: {e}")
            return False
        finally:
            # 🆔 SESSION CLEANUP: Clear session when download ends
            if hasattr(self, 'current_session_id'):
                logging.info(f"🧹 JDownloader cleaning up session: {self.current_session_id}")
                self.current_session_id = None

    def _monitor_download(self, original_url: str, progress_callback=None, target_dir=None) -> list:
        """
        Monitor download progress with faster, more responsive checking
        """
        try:
            # 🚀 SMART TIMEOUT SYSTEM - Progressive timeout based on activity
            initial_timeout = 900      # 15 minutes to detect if download started (increased for large files)
            max_inactivity_time = 600  # 10 minutes without progress = timeout (increased for large files)
            
            logging.info(f"🔧 Smart timeout config: startup_timeout={initial_timeout}s, inactivity_timeout={max_inactivity_time}s")
            
            # ⚡ Adaptive monitoring - start fast, slow down if needed
            fast_interval = 0.1   # Very fast for first 30 seconds (small files)
            normal_interval = 0.5 # Normal speed after fast phase
            slow_interval = 2.0   # Slower for long downloads
            
            check_interval = fast_interval
            elapsed_time = 0
            last_activity_time = 0     # Last time we saw ANY progress/activity
            last_bytes_loaded = -1     # Track actual download progress
            download_started = False   # Has download actually started?
            
            logging.info(f"🔍 ⚡ Adaptive monitoring download for: {original_url}")
            package_found = False
            last_progress = -1  # Track progress changes
            fast_phase_duration = 30  # First 30 seconds = fast checking
            
            # 🧠 SMART TIMEOUT: Initial timeout OR inactivity timeout
            while True:
                # Check if we should timeout
                if not download_started and elapsed_time >= initial_timeout:
                    logging.warning(f"⏰ No download activity detected after {initial_timeout}s")
                    break
                    
                if download_started and (elapsed_time - last_activity_time) >= max_inactivity_time:
                    logging.warning(f"⏰ No download progress for {max_inactivity_time}s (inactive)")
                    break
                try:
                    # Check downloads with detailed progress
                    downloads_info = self.device.downloads.query_packages()
                    total_progress = 0
                    active_downloads = 0
                    
                    if downloads_info:
                        for package in downloads_info:
                            package_name = package.get('name', '')
                            finished = package.get('finished', False)
                            bytes_loaded = package.get('bytesLoaded', 0)
                            bytes_total = package.get('bytesTotal', 1)  # Avoid division by zero
                            status = package.get('status', 'Unknown')
                            
                            # 🔄 Handle special statuses that shouldn't timeout
                            is_paused = 'paused' in status.lower() or 'pause' in status.lower()
                            is_waiting = 'wait' in status.lower() or 'queue' in status.lower()
                            is_connecting = 'connect' in status.lower() or 'retry' in status.lower()
                            
                            # 🔍 Enhanced package monitoring with host info
                            if bytes_total > 0:
                                package_progress = int((bytes_loaded / bytes_total) * 100)
                                
                                # Extract host name from original URL for display
                                host_name = self._extract_host_name(original_url)
                                display_name = self.format_progress_display_name(package_name, host_name)
                                
                                # 🆔 SESSION VALIDATION: Only send progress for current session
                                if progress_callback and (package_progress > last_progress or package_progress == 100):
                                    # Check if this is still the current session
                                    if hasattr(self, 'current_session_id') and self.current_session_id:
                                        logging.debug(f"📶 JDownloader session {self.current_session_id} sending progress: {display_name} = {package_progress}%")
                                        try:
                                            # Try enhanced callback first
                                            progress_callback(bytes_loaded, bytes_total, display_name, package_progress)
                                            logging.debug(f"📊 {display_name}: {package_progress}%")
                                        except TypeError:
                                            # Fallback to legacy callback
                                            progress_callback(bytes_loaded, bytes_total, display_name)
                                    else:
                                        logging.warning(f"🚫 JDownloader ignoring progress update - no active session")
                                    
                                    last_progress = package_progress
                                
                                logging.info(f"📊 Package '{package_name}': {package_progress}% | Status: {status} | Host: {host_name} | Finished: {finished}")
                                
                                # 🔍 ACTIVITY TRACKING - Monitor download activity
                                if bytes_loaded > 0:
                                    if not download_started:
                                        logging.info(f"🚀 Download STARTED: {package_name} ({bytes_loaded}/{bytes_total} bytes)")
                                        download_started = True
                                        last_activity_time = elapsed_time
                                    
                                    package_found = True
                                    
                                    # Check if progress has changed (bytes downloaded)
                                    if bytes_loaded != last_bytes_loaded:
                                        last_activity_time = elapsed_time  # Update activity timestamp
                                        progress_change = bytes_loaded - (last_bytes_loaded if last_bytes_loaded > 0 else 0)
                                        last_bytes_loaded = bytes_loaded
                                        logging.info(f"🔄 Progress: +{progress_change} bytes | Total: {bytes_loaded}/{bytes_total} ({package_progress}%)")
                                    
                                    # 🔄 Special states also count as activity
                                    elif is_paused or is_waiting or is_connecting:
                                        last_activity_time = elapsed_time  # Keep activity alive for special states
                                        logging.info(f"🔄 Special state activity: {status} - keeping download alive")
                                    
                                    active_downloads += 1
                                
                                # ⚡ Check if package is actually complete but not marked as finished
                                if package_progress >= 100 and not finished:
                                    logging.info(f"📅 Package '{package_name}' is 100% downloaded, attempting file retrieval...")
                                    # ✅ Try to get files with enhanced error handling
                                    try:
                                        downloaded_files = self._get_package_files(package, target_dir)
                                        if downloaded_files:
                                            logging.info(f"✅ SUCCESS: Retrieved {len(downloaded_files)} files from completed package")
                                            if progress_callback:
                                                try:
                                                    progress_callback(bytes_total, bytes_total, display_name, 100)
                                                except (TypeError, Exception) as e:
                                                    logging.debug(f"Progress callback issue: {e}")
                                                    progress_callback(bytes_total, bytes_total, display_name)
                                            return downloaded_files
                                        else:
                                            logging.info(f"🔍 No files found yet, continuing to monitor...")
                                    except Exception as e:
                                        logging.warning(f"⚠️ Error getting package files: {e}")
                            
                            if finished:
                                logging.info(f"✅ ⚡ JDownloader package COMPLETED: {package_name}")
                                
                                # ⚡ Try immediate file check first (no delay!)
                                downloaded_files = self._get_package_files(package, target_dir)
                                
                                if downloaded_files:
                                    # ✅ Files found immediately!
                                    if progress_callback:
                                        host_name = self._extract_host_name(original_url)
                                        display_name = self.format_progress_display_name(package_name, host_name)
                                        try:
                                            progress_callback(100, 100, display_name, 100)
                                        except TypeError:
                                            progress_callback(100, 100, display_name)
                                    logging.info(f"⚡ INSTANT: Found {len(downloaded_files)} files!")
                                    return downloaded_files
                                
                                # ⏱️ Only wait 1 second if files not found immediately
                                logging.info(f"⏱️ Waiting 1s for file finalization...")
                                time.sleep(1)
                                
                                # Second try
                                downloaded_files = self._get_package_files(package, target_dir)
                                if downloaded_files:
                                    if progress_callback:
                                        host_name = self._extract_host_name(original_url)
                                        display_name = self.format_progress_display_name(package_name, host_name)
                                        try:
                                            progress_callback(100, 100, display_name, 100)
                                        except TypeError:
                                            progress_callback(100, 100, display_name)
                                    logging.info(f"⚡ QUICK: Found {len(downloaded_files)} files after 1s!")
                                    return downloaded_files
                                
                                # Try alternative method quickly
                                alt_files = self._find_files_by_package_name(package_name, target_dir)
                                if alt_files:
                                    if progress_callback:
                                        host_name = self._extract_host_name(original_url)
                                        display_name = self.format_progress_display_name(package_name, host_name)
                                        try:
                                            progress_callback(100, 100, display_name, 100)
                                        except TypeError:
                                            progress_callback(100, 100, display_name)
                                    logging.info(f"⚡ ALT METHOD: Found {len(alt_files)} files!")
                                    return alt_files
                                
                                # ⏱️ Final wait (reduced from 10s to 3s)
                                logging.warning(f"⚠️ Package finished but no files found, final 3s wait...")
                                time.sleep(3)
                                final_files = self._get_package_files(package, target_dir)
                                if final_files:
                                    if progress_callback:
                                        host_name = self._extract_host_name(original_url)
                                        display_name = self.format_progress_display_name(package_name, host_name)
                                        try:
                                            progress_callback(100, 100, display_name, 100)
                                        except TypeError:
                                            progress_callback(100, 100, display_name)
                                    logging.info(f"⚡ FINAL: Found {len(final_files)} files after 3s!")
                                    return final_files
                            
                            # Calculate real progress for active downloads
                            if bytes_total > 0:
                                package_progress = int((bytes_loaded / bytes_total) * 100)
                                total_progress += package_progress
                        
                        if finished:
                            logging.info(f"✅ ⚡ JDownloader package COMPLETED: {package_name}")
                            
                            # ⚡ Try immediate file check first (no delay!)
                            downloaded_files = self._get_package_files(package, target_dir)
                            
                            if downloaded_files:
                                # ✅ Files found immediately!
                                if progress_callback:
                                    progress_callback(100, 100, package_name)
                                logging.info(f"⚡ INSTANT: Found {len(downloaded_files)} files!")
                                return downloaded_files
                            
                            # ⏱️ Only wait 1 second if files not found immediately
                            logging.info(f"⏱️ Waiting 1s for file finalization...")
                            time.sleep(1)
                            
                            # Second try
                            downloaded_files = self._get_package_files(package, target_dir)
                            if downloaded_files:
                                if progress_callback:
                                    progress_callback(100, 100, package_name)
                                logging.info(f"⚡ QUICK: Found {len(downloaded_files)} files after 1s!")
                                return downloaded_files
                            
                            # Try alternative method quickly
                            alt_files = self._find_files_by_package_name(package_name, target_dir)
                            if alt_files:
                                if progress_callback:
                                    progress_callback(100, 100, package_name)
                                logging.info(f"⚡ ALT METHOD: Found {len(alt_files)} files!")
                                return alt_files
                            
                            # ⏱️ Final wait (reduced from 10s to 3s)
                            logging.warning(f"⚠️ Package finished but no files found, final 3s wait...")
                            time.sleep(3)
                            final_files = self._get_package_files(package, target_dir)
                            if final_files:
                                if progress_callback:
                                    progress_callback(100, 100, package_name)
                                logging.info(f"⚡ FINAL: Found {len(final_files)} files after 3s!")
                                return final_files
                        
                        # Calculate real progress for active downloads
                        if bytes_total > 0:
                            package_progress = int((bytes_loaded / bytes_total) * 100)
                            total_progress += package_progress
                            active_downloads += 1
                            package_found = True
                            
                            logging.info(f"📊 {package_name}: {package_progress}% ({bytes_loaded}/{bytes_total} bytes)")
                
                    # ⚡ Smart progress reporting (only when changed)
                    if progress_callback and active_downloads > 0:
                        # Calculate actual bytes for progress
                        total_bytes_loaded = sum(pkg.get('bytesLoaded', 0) for pkg in downloads_info)
                        total_bytes_total = sum(pkg.get('bytesTotal', 1) for pkg in downloads_info)
                        
                        if total_bytes_total > 0:
                            # Calculate real progress - allow 100% when downloads complete
                            real_progress = (total_bytes_loaded / total_bytes_total) * 100
                            
                            # 🎯 Only show 100% if bytes are fully loaded OR if we have finished packages
                            if real_progress >= 99.9:  # Almost complete
                                progress_percent = min(real_progress, 98)  # Cap at 98% until files confirmed
                            else:
                                progress_percent = real_progress
                            
                            # 🎯 Only update if progress changed significantly
                            if abs(progress_percent - last_progress) >= 1:  # Update every 1%
                                # 🏷️ Enhanced progress info with filename and host
                                # Get the most active package name for display
                                active_package_name = "JDownloader"
                                for pkg in downloads_info:
                                    if pkg.get('bytesTotal', 0) > 0:
                                        active_package_name = pkg.get('name', 'JDownloader')
                                        break
                                
                                # Format: "Filename.ext - JDownloader" for better user info
                                display_name = f"{active_package_name} - JDownloader"
                                progress_callback(int(progress_percent), 100, display_name)
                                logging.info(f"📊 ⚡ Progress: {int(progress_percent)}% ({total_bytes_loaded}/{total_bytes_total} bytes) - {active_package_name}")
                                last_progress = progress_percent
                            
                            # 🔍 Check if all downloads are actually complete (100% bytes)
                            if real_progress >= 99.9 and active_downloads > 0:
                                logging.info(f"✅ All downloads appear complete at {real_progress:.1f}% - checking for files...")
                                # Try to find files from any completed packages
                                for pkg in downloads_info:
                                    pkg_bytes_loaded = pkg.get('bytesLoaded', 0)
                                    pkg_bytes_total = pkg.get('bytesTotal', 1)
                                    if pkg_bytes_total > 0 and (pkg_bytes_loaded / pkg_bytes_total) >= 0.999:  # 99.9% complete
                                        final_files = self._get_package_files(pkg, target_dir)
                                        if final_files:
                                            logging.info(f"⚡ COMPLETION DETECTED: Found {len(final_files)} files from completed download!")
                                            if progress_callback:
                                                progress_callback(100, 100, pkg.get('name', 'JDownloader'))
                                            return final_files
                    
                    # Check linkgrabber for pending items
                    linkgrabber_info = self.device.linkgrabber.query_packages()
                    
                    if linkgrabber_info and not package_found:
                        for package in linkgrabber_info:
                            package_name = package.get('name', '')
                            logging.info(f"📦 Package in linkgrabber: {package_name}")
                            if progress_callback:
                                progress_callback(1, 100, package_name)  # Starting progress (1%)
                    
                    # ⚡ Adaptive interval adjustment
                    # If we saw progress change, reset activity timer
                    if active_downloads > 0 or package_found:
                        last_activity_time = elapsed_time
                    
                    # Adjust monitoring speed based on phase and activity
                    if elapsed_time < fast_phase_duration:
                        # Fast phase - check every 0.1s for first 30 seconds
                        check_interval = fast_interval
                    elif elapsed_time - last_activity_time < 60:
                        # Active phase - recent activity, check every 0.5s
                        check_interval = normal_interval
                    else:
                        # Slow phase - no recent activity, check every 2s
                        check_interval = slow_interval
                    
                    time.sleep(check_interval)
                    elapsed_time += check_interval
                    
                    # Log progress every 30 seconds with detailed status
                    if int(elapsed_time) % 30 == 0 and elapsed_time > 0:
                        status_msg = "🔍 MONITORING STATUS:\n"
                        status_msg += f"  ⏱️ Elapsed: {elapsed_time:.0f}s\n"
                        status_msg += f"  🚀 Download started: {'YES' if download_started else 'NO'}\n"
                        if download_started:
                            inactivity = elapsed_time - last_activity_time
                            status_msg += f"  🔄 Last activity: {inactivity:.0f}s ago\n"
                            status_msg += f"  📊 Progress: {last_bytes_loaded} bytes\n"
                        status_msg += f"  🔄 Check interval: {check_interval}s\n"
                        status_msg += f"  📈 Active downloads: {active_downloads}"
                        logging.info(status_msg)
                        
                except Exception as e:
                    # 🛡️ Check if it's a deleted object error
                    if "wrapped C/C++ object" in str(e) or "has been deleted" in str(e):
                        logging.info(f"🚫 Download worker deleted, stopping monitoring")
                        break
                    else:
                        logging.error(f"❌ Error in monitoring loop: {e}")
                    time.sleep(check_interval)
                    elapsed_time += check_interval
            
            # 🔍 Detailed timeout message based on what actually happened
            if not download_started:
                logging.warning(f"⏰ JDownloader download STARTUP timeout after {elapsed_time:.0f}s - no download activity detected")
            else:
                inactivity_duration = elapsed_time - last_activity_time
                logging.warning(f"⏰ JDownloader download INACTIVITY timeout after {inactivity_duration:.0f}s without progress (total: {elapsed_time:.0f}s)")
            return []
            
        except Exception as e:
            logging.error(f"❌ Monitor download error: {e}")
            return []

    def _get_package_files(self, package, target_dir=None) -> list:
        """
        Get files from completed package and move them to target directory if needed
        """
        downloaded_files = []
        
        try:
            # Get package UUID and query its links
            package_uuid = package.get('uuid', '')
            if not package_uuid:
                logging.error("❌ No package UUID found")
                return []
            
            logging.info(f"🔍 Getting files for package UUID: {package_uuid}")
            
            # Query links in the package
            try:
                links = self.device.downloads.query_links([{"packageUUID": package_uuid}])
                logging.info(f"📄 Found {len(links)} links in package")
            except Exception as e:
                logging.error(f"❌ Error querying links: {e}")
                return []
            
            for i, link in enumerate(links):
                logging.info(f"🔗 Link {i}: {link}")
                
                # Try different field names for file path
                file_path = None
                for field in ['localFilePath', 'downloadPath', 'filePath', 'path']:
                    file_path = link.get(field, '')
                    if file_path:
                        break
                
                if not file_path:
                    logging.warning(f"⚠️ No file path found in link: {link}")
                    # 🔍 FALLBACK: Try to find file by name in JDownloader's download directory
                    filename = link.get('name', '')
                    if filename:
                        logging.info(f"🔍 TRIGGERING direct filesystem search for: {filename}")
                        found_files = self._search_file_by_name(filename, target_dir)
                        if found_files:
                            downloaded_files.extend(found_files)
                            logging.info(f"⚡ SUCCESS: Found {len(found_files)} files via filesystem search!")
                            # Log each found file
                            for found_file in found_files:
                                logging.info(f"📁 Located: {found_file}")
                        else:
                            logging.error(f"❌ FAILED: Could not locate '{filename}' via filesystem search")
                    else:
                        logging.error(f"❌ No filename provided in link data: {link}")
                    continue
                    
                if os.path.exists(file_path):
                    logging.info(f"📁 Found downloaded file: {file_path}")

                    # If the file still has a temporary '.part' extension, wait
                    # for JDownloader to finish and rename it. Moving a .part
                    # file results in unusable archives, so we give the API
                    # ample time to finalize the download before proceeding.
                    if file_path.endswith('.part'):
                        final_path = file_path[:-5]
                        wait_time = 0
                        max_wait = 300  # up to 5 minutes
                        logging.info(
                            f"⏳ Waiting for JDownloader to finalize: {file_path}")
                        while wait_time < max_wait and not os.path.exists(final_path):
                            time.sleep(1)
                            wait_time += 1

                        if os.path.exists(final_path):
                            file_path = final_path
                            logging.info(f"✅ Finalized file detected: {file_path}")
                        else:
                            logging.error(
                                f"❌ File remained incomplete after {max_wait}s: {file_path}")
                            continue

                    # If target directory is specified and different from current location
                    if target_dir and os.path.dirname(file_path) != target_dir:
                        try:
                            # Ensure target directory exists
                            os.makedirs(target_dir, exist_ok=True)
                            
                            # Move file to target directory
                            filename = os.path.basename(file_path)
                            new_path = os.path.join(target_dir, filename)
                            
                            # Handle file name conflicts
                            counter = 1
                            while os.path.exists(new_path):
                                name, ext = os.path.splitext(filename)
                                new_path = os.path.join(target_dir, f"{name}_{counter}{ext}")
                                counter += 1
                            
                            shutil.move(file_path, new_path)
                            logging.info(f"✅ Moved file to: {new_path}")
                            downloaded_files.append(new_path)
                            
                        except Exception as e:
                            logging.error(f"❌ Error moving file {file_path}: {e}")
                            # Keep original path if move fails
                            downloaded_files.append(file_path)
                    else:
                        # File is already in correct location or no target specified
                        downloaded_files.append(file_path)
                else:
                    logging.warning(f"⚠️ File does not exist: {file_path}")
                        
        except Exception as e:
            logging.error(f"❌ Error getting package files: {e}")
            
        logging.info(f"📊 Total files found: {len(downloaded_files)}")
        return downloaded_files
    
    def _find_files_by_package_name(self, package_name, target_dir=None) -> list:
        """
        Alternative method to find downloaded files by scanning JDownloader's download directory
        """
        downloaded_files = []
        
        try:
            # Common JDownloader download directories
            possible_dirs = [
                os.path.expanduser("~/Downloads"),
                os.path.expanduser("~/Desktop"),
                "C:/Users/Public/Downloads",
                "C:/Downloads"
            ]
            
            # Add target directory to search paths
            if target_dir:
                possible_dirs.insert(0, target_dir)
            
            # Search for files with similar names
            search_terms = package_name.replace('_', ' ').replace('-', ' ').split()
            
            for search_dir in possible_dirs:
                if not os.path.exists(search_dir):
                    continue
                    
                logging.info(f"🔍 Searching in: {search_dir}")
                
                # Look for recently created files
                for root, dirs, files in os.walk(search_dir):
                    for file in files:
                        file_path = os.path.join(root, file)

                        # Skip temporary .part files until they finalize
                        if file.lower().endswith('.part'):
                            final_path = file_path[:-5]
                            wait_time = 0
                            max_wait = 300
                            logging.info(
                                f"⏳ Waiting for JDownloader to finalize: {file_path}")
                            while wait_time < max_wait and not os.path.exists(final_path):
                                time.sleep(1)
                                wait_time += 1

                            if os.path.exists(final_path):
                                file_path = final_path
                                file = os.path.basename(final_path)
                                logging.info(
                                    f"✅ Finalized file detected: {file_path}")
                            else:
                                logging.debug(
                                    f"Skipping incomplete temporary file: {file_path}")
                                continue
                        # Check if file was created recently (within last 10 minutes)
                        try:
                            file_time = os.path.getctime(file_path)
                            current_time = time.time()
                            if current_time - file_time <= 600:  # 10 minutes
                                # Check if filename matches any search terms
                                if any(term.lower() in file.lower() for term in search_terms if len(term) > 3):
                                    logging.info(f"🎯 Found matching file: {file_path}")
                                    
                                    # Move to target directory if needed
                                    if target_dir and os.path.dirname(file_path) != target_dir:
                                        try:
                                            os.makedirs(target_dir, exist_ok=True)
                                            filename = os.path.basename(file_path)
                                            new_path = os.path.join(target_dir, filename)
                                            
                                            # Handle conflicts
                                            counter = 1
                                            while os.path.exists(new_path):
                                                name, ext = os.path.splitext(filename)
                                                new_path = os.path.join(target_dir, f"{name}_{counter}{ext}")
                                                counter += 1
                                            
                                            shutil.move(file_path, new_path)
                                            downloaded_files.append(new_path)
                                            logging.info(f"✅ Moved file to: {new_path}")
                                        except Exception as e:
                                            logging.error(f"❌ Error moving file: {e}")
                                            downloaded_files.append(file_path)
                                    else:
                                        downloaded_files.append(file_path)
                        except Exception as e:
                            continue
                    
                    # Don't go too deep
                    if len(root.split(os.sep)) - len(search_dir.split(os.sep)) > 2:
                        break
                        
        except Exception as e:
            logging.error(f"❌ Error in alternative file search: {e}")
            
        logging.info(f"📊 Alternative search found: {len(downloaded_files)} files")
        return downloaded_files

    def _search_file_by_name(self, filename, target_dir=None) -> list:
        """
        🔍 POWERFUL: Direct file system search by exact filename 
        للبحث المباشر عن الملف في النظام عند فشل JDownloader API
        """
        downloaded_files = []
        
        try:
            # Get JDownloader's actual download directory from settings
            jd_download_dirs = []
            
            # Try to get JDownloader's download directory from config
            try:
                # Common JDownloader paths
                jd_paths = [
                    os.path.expanduser("~/JDownloader/Downloads"),
                    "C:/JDownloader/Downloads", 
                    os.path.expanduser("~/Downloads/JDownloader"),
                    os.path.expanduser("~/Downloads"),
                    os.path.expanduser("~/Desktop"),
                ]
                
                # Add target directory
                if target_dir:
                    jd_paths.insert(0, target_dir)
                
                jd_download_dirs = [d for d in jd_paths if os.path.exists(d)]
                
            except Exception:
                jd_download_dirs = [os.path.expanduser("~/Downloads")]
            
            logging.info(f"🔍 Searching for '{filename}' in {len(jd_download_dirs)} directories...")
            
            # Search in each directory
            for search_dir in jd_download_dirs:
                logging.info(f"📁 Scanning: {search_dir}")
                
                # Search recursively but not too deep
                for root, dirs, files in os.walk(search_dir):
                    # Limit search depth to avoid performance issues
                    level = root.replace(search_dir, '').count(os.sep)
                    if level >= 3:  # Max 3 levels deep
                        continue
                    
                    for file in files:
                        file_path = os.path.join(root, file)

                        # Skip temporary .part files until they finalize
                        if file.lower().endswith('.part'):
                            final_path = file_path[:-5]
                            wait_time = 0
                            max_wait = 300
                            logging.info(
                                f"⏳ Waiting for JDownloader to finalize: {file_path}")
                            while wait_time < max_wait and not os.path.exists(final_path):
                                time.sleep(1)
                                wait_time += 1

                            if os.path.exists(final_path):
                                file_path = final_path
                                file = os.path.basename(final_path)
                                logging.info(
                                    f"✅ Finalized file detected: {file_path}")
                            else:
                                logging.debug(
                                    f"Skipping incomplete temporary file: {file_path}")
                                continue
                        # Exact filename match (case insensitive)
                        if file.lower() == filename.lower():

                            # Check if file was created recently (within last 30 minutes)
                            try:
                                file_time = os.path.getctime(file_path)
                                current_time = time.time()
                                time_diff = current_time - file_time
                                
                                if time_diff <= 1800:  # 30 minutes
                                    logging.info(f"✅ EXACT MATCH found: {file_path} (created {time_diff/60:.1f} min ago)")
                                    
                                    # Move to target directory if needed
                                    if target_dir and root != target_dir:
                                        try:
                                            os.makedirs(target_dir, exist_ok=True)
                                            new_path = os.path.join(target_dir, file)
                                            
                                            # Handle conflicts
                                            counter = 1
                                            while os.path.exists(new_path):
                                                name, ext = os.path.splitext(file)
                                                new_path = os.path.join(target_dir, f"{name}_{counter}{ext}")
                                                counter += 1
                                            
                                            shutil.move(file_path, new_path)
                                            downloaded_files.append(new_path)
                                            logging.info(f"📦 Moved to target: {new_path}")
                                        except Exception as e:
                                            logging.error(f"❌ Move error: {e}")
                                            downloaded_files.append(file_path)
                                    else:
                                        downloaded_files.append(file_path)
                                        
                                    # Found exact match, no need to continue searching this directory
                                    break
                                else:
                                    logging.debug(f"⏰ File too old: {file_path} ({time_diff/60:.1f} min)")
                                    
                            except Exception as e:
                                logging.error(f"❌ Error checking file time: {e}")
                                continue
                
                # If we found files, break from directory search
                if downloaded_files:
                    break
            
            # If no exact match, try partial matching as fallback
            if not downloaded_files:
                logging.info(f"🔍 No exact match for '{filename}', trying partial match...")
                base_name = os.path.splitext(filename)[0].lower()
                
                for search_dir in jd_download_dirs[:2]:  # Only search top 2 directories for partial
                    for root, dirs, files in os.walk(search_dir):
                        level = root.replace(search_dir, '').count(os.sep)
                        if level >= 2:  # Shallower search for partial match
                            continue
                            
                        for file in files:
                            file_base = os.path.splitext(file)[0].lower()

                            # Skip temporary .part files until they finalize
                            file_path = os.path.join(root, file)
                            if file.lower().endswith('.part'):
                                final_path = file_path[:-5]
                                wait_time = 0
                                max_wait = 300
                                logging.info(
                                    f"⏳ Waiting for JDownloader to finalize: {file_path}")
                                while wait_time < max_wait and not os.path.exists(final_path):
                                    time.sleep(1)
                                    wait_time += 1

                                if os.path.exists(final_path):
                                    file_path = final_path
                                    file = os.path.basename(final_path)
                                    file_base = os.path.splitext(file)[0].lower()
                                    logging.info(
                                        f"✅ Finalized file detected: {file_path}")
                                else:
                                    logging.debug(
                                        f"Skipping incomplete temporary file: {file_path}")
                                    continue

                            # Check if base names are similar
                            if base_name in file_base or file_base in base_name:

                                # Check recent creation
                                try:
                                    file_time = os.path.getctime(file_path)
                                    current_time = time.time()
                                    if current_time - file_time <= 1800:  # 30 minutes
                                        logging.info(f"🎯 PARTIAL MATCH: {file_path}")
                                        downloaded_files.append(file_path)
                                        break
                                except Exception:
                                    continue
                    
                    if downloaded_files:
                        break
            
        except Exception as e:
            logging.error(f"❌ Error in file search: {e}")
        
        logging.info(f"🔍 Direct search result: {len(downloaded_files)} files found")
        return downloaded_files

    def disconnect(self):
        """
        Properly disconnect from JDownloader API
        """
        try:
            if self.jd and self.is_connected:
                self.jd.disconnect()
                self.is_connected = False
                logging.info("🔌 Disconnected from JDownloader")
        except Exception as e:
            logging.error(f"❌ Error disconnecting from JDownloader: {e}")

    def __del__(self):
        """
        Ensure proper cleanup
        """
        self.disconnect()
