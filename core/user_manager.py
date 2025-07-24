"""
User Management System
======================

This module provides centralized user management with:
- User-specific data storage and isolation
- Settings management per user
- Session persistence
- Data migration utilities

Author: Cascade AI Assistant
"""

import os
import json, pathlib
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Set
from utils import sanitize_filename
from config.config import DATA_DIR
from utils.paths import get_data_folder
import browser_cookie3
import requests

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
CHROME_PROFILE = (
    r"C:\Users\rsher\AppData\Local\Google\Chrome\User Data\Profile 1"
)

class UserManager:
    """
    Centralized user management system that handles:
    - User-specific data storage
    - Settings persistence per user
    - Data isolation between users
    - Session management
    """
    
    def __init__(self):
        self.current_user: Optional[str] = None
        self.user_data_dir: Optional[str] = None
        self.user_settings: Dict[str, Any] = {}
        self._site_sessions: Dict[str, requests.Session] = {}
        self.data_dir = get_data_folder()
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load last logged-in user if exists
        self._load_last_session()
    
    def set_current_user(self, username: str) -> bool:
        """
        Set the current active user and initialize their data directory.
        
        Args:
            username: The username to set as current
            
        Returns:
            bool: True if user was set successfully
        """
        try:
            if not username or not username.strip():
                raise ValueError("Username cannot be empty")
            
            self.current_user = sanitize_filename(username.strip())
            self.user_data_dir = os.path.join(self.data_dir, f"user_{self.current_user}")
            
            # Create user-specific data directory
            os.makedirs(self.user_data_dir, exist_ok=True)
            
            # Load user-specific settings
            self._load_user_settings()
            
            # Save as last session
            self._save_last_session()
            # clear previous site sessions when switching user
            self._site_sessions.clear()
            
            logging.info(f"✅ User session initialized for: {self.current_user}")
            logging.info(f"📁 User data directory: {self.user_data_dir}")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to set current user '{username}': {e}")
            return False
    
    def get_current_user(self) -> Optional[str]:
        """Get the current active username."""
        return self.current_user
    
    def get_user_folder(self) -> str:
        """Get the current user's data folder path."""
        if not self.current_user:
            raise ValueError("No user is currently logged in")
        
        if not self.user_data_dir:
            raise ValueError("User data directory not initialized")
        
        return self.user_data_dir
    
    def clear_current_user(self) -> bool:
        """Clear the current user session and reset state."""
        try:
            if self.current_user:
                logging.info(f"🚪 Clearing user session for: {self.current_user}")
            
            # Clear session data
            self.current_user = None
            self.user_data_dir = None
            self.user_settings = {}
            
            # Clear last session file
            session_file = os.path.join(self.data_dir, 'last_session.json')
            if os.path.exists(session_file):
                os.remove(session_file)
                logging.info("🗑️ Last session file cleared")
            
            logging.info("✅ User session cleared successfully")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to clear user session: {e}")
            return False
    
    def get_user_data_path(self, filename: str) -> str:
        """
        Get the full path for a user-specific data file.
        
        Args:
            filename: The filename (without user prefix)
            
        Returns:
            str: Full path to user-specific file
        """
        if not self.current_user:
            raise ValueError("No user is currently logged in")
        
        if not self.user_data_dir:
            raise ValueError("User data directory not initialized")
        
        return os.path.join(self.user_data_dir, filename)
    
    def save_user_data(self, filename: str, data: Any) -> bool:
        """
        Save data to a user-specific file.
        
        Args:
            filename: The filename (without user prefix)
            data: The data to save (will be JSON serialized)
            
        Returns:
            bool: True if saved successfully
        """
        try:
            filepath = self.get_user_data_path(filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            
            logging.debug(f"💾 Saved user data to: {filepath}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to save user data '{filename}': {e}")
            return False
    
    def load_user_data(self, filename: str, default=None) -> Any:
        """
        Load data from a user-specific file.
        
        Args:
            filename: The filename (without user prefix)
            default: Default value if file doesn't exist
            
        Returns:
            Any: The loaded data or default value
        """
        try:
            filepath = self.get_user_data_path(filename)
            
            if not os.path.exists(filepath):
                logging.debug(f"📄 User data file not found: {filepath}")
                return default
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logging.debug(f"📂 Loaded user data from: {filepath}")
            return data
            
        except Exception as e:
            logging.error(f"❌ Failed to load user data '{filename}': {e}")
            return default
    
    def get_user_setting(self, key: str, default=None) -> Any:
        """Get a user-specific setting value."""
        return self.user_settings.get(key, default)
    
    def set_user_setting(self, key: str, value: Any) -> bool:
        """Set a user-specific setting value."""
        try:
            self.user_settings[key] = value
            return self._save_user_settings()
        except Exception as e:
            logging.error(f"❌ Failed to set user setting '{key}': {e}")
            return False
    
    def update_user_settings(self, settings: Dict[str, Any]) -> bool:
        """Update multiple user settings at once."""
        try:
            self.user_settings.update(settings)
            return self._save_user_settings()
        except Exception as e:
            logging.error(f"❌ Failed to update user settings: {e}")
            return False
    
    def get_all_user_settings(self) -> Dict[str, Any]:
        """Get all user settings as a dictionary."""
        return self.user_settings.copy()
    
    def list_users(self) -> Set[str]:
        """
        List all users that have data directories.
        
        Returns:
            Set[str]: Set of usernames that have data
        """
        try:
            users = set()
            
            if not os.path.exists(self.data_dir):
                return users
            
            for item in os.listdir(self.data_dir):
                item_path = os.path.join(self.data_dir, item)
                if os.path.isdir(item_path) and item.startswith('user_'):
                    username = item[5:]  # Remove 'user_' prefix
                    users.add(username)
            
            return users
            
        except Exception as e:
            logging.error(f"❌ Failed to list users: {e}")
            return set()
    
    def delete_user_data(self, username: str) -> bool:
        """
        Delete all data for a specific user.
        
        Args:
            username: The username whose data to delete
            
        Returns:
            bool: True if deleted successfully
        """
        try:
            sanitized_username = sanitize_filename(username)
            user_dir = os.path.join(self.data_dir, f"user_{sanitized_username}")
            
            if os.path.exists(user_dir):
                import shutil
                shutil.rmtree(user_dir)
                logging.info(f"🗑️ Deleted user data for: {username}")
                return True
            else:
                logging.warning(f"⚠️ No data found for user: {username}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Failed to delete user data for '{username}': {e}")
            return False
    
    def migrate_legacy_data(self, username: str) -> bool:
        """
        Migrate legacy data files (with hardcoded 'your_username' prefix) to user-specific storage.
        
        Args:
            username: The username to migrate data for
            
        Returns:
            bool: True if migration was successful
        """
        try:
            if not self.current_user:
                self.set_current_user(username)
            
            legacy_files = [
                'your_username_process_threads.json',
                'your_username_megathreads_process_threads.json',
                'your_username_backup_threads.json'
            ]
            
            # Also migrate category-specific thread files
            for file in os.listdir(self.data_dir):
                if file.endswith('_threads.json') and not file.startswith('threads_'):
                    legacy_files.append(file)
            
            migrated_count = 0
            
            for legacy_file in legacy_files:
                legacy_path = os.path.join(self.data_dir, legacy_file)
                
                if os.path.exists(legacy_path):
                    # Determine new filename based on file type
                    if legacy_file.startswith('your_username_'):
                        new_filename = legacy_file.replace('your_username_', '')
                    elif legacy_file.endswith('_threads.json') and not legacy_file.startswith('threads_'):
                        # Convert category_threads.json to threads_category.json
                        category_name = legacy_file.replace('_threads.json', '')
                        new_filename = f'threads_{category_name}.json'
                    else:
                        new_filename = legacy_file
                    
                    try:
                        # Load legacy data
                        with open(legacy_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        # Save to user-specific location
                        if self.save_user_data(new_filename, data):
                            # Remove legacy file after successful migration
                            os.remove(legacy_path)
                            migrated_count += 1
                            logging.info(f"📦 Migrated: {legacy_file} → {new_filename}")
                        
                    except Exception as e:
                        logging.error(f"❌ Failed to migrate {legacy_file}: {e}")
            
            if migrated_count > 0:
                logging.info(f"✅ Migration completed: {migrated_count} files migrated for user '{username}'")
            else:
                logging.info(f"ℹ️ No legacy files found to migrate for user '{username}'")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Migration failed for user '{username}': {e}")
            return False
    
    def clear_current_session(self):
        """Clear the current user session."""
        self.current_user = None
        self.user_data_dir = None
        self.user_settings.clear()
        self._site_sessions.clear()
        
        # Clear last session file
        last_session_file = os.path.join(self.data_dir, '.last_session')
        if os.path.exists(last_session_file):
            try:
                os.remove(last_session_file)
            except Exception as e:
                logging.error(f"❌ Failed to clear last session: {e}")
        
        logging.info("🔄 User session cleared")
    
    def _load_user_settings(self):
        """Load user-specific settings from their data directory."""
        try:
            settings_file = 'user_settings.json'
            self.user_settings = self.load_user_data(settings_file, {})
            
            # Set default settings if not present
            env_upload_hosts = os.getenv('UPLOAD_HOSTS', '')
            default_upload_hosts = [h.strip() for h in env_upload_hosts.split(',') if h.strip()] or [
                'rapidgator', 'nitroflare', 'ddownload', 'katfile'
            ]

            env_priority = os.getenv('DOWNLOAD_HOSTS_PRIORITY', '')
            default_priority = [h.strip() for h in env_priority.split(',') if h.strip()] or [
                'rapidgator.net', 'katfile.com', 'nitroflare.com', 'ddownload.com',
                'mega.nz', 'xup.in', 'f2h.io', 'filepv.com', 'filespayouts.com',
                'uploady.io'
            ]

            default_settings = {
                'download_dir': os.path.join(os.path.expanduser('~'), 'Downloads', 'ForumBot'),
                'upload_hosts': default_upload_hosts,
                'download_hosts_priority': default_priority,
                'use_backup_rg': False,
                'page_from': 1,
                'page_to': 5,
                'katfile_api_key': '',
                'date_filters': ['Last 3 days'],
                'stats_target': {
                    'daily_downloads': 0,
                    'daily_revenue': 0.0,
                },
                'sites': {
                    'rapidgator': [
                        {
                            'username': os.getenv('UPLOAD_RAPIDGATOR_USERNAME',
                                                  os.getenv('UPLOAD_RAPIDGATOR_LOGIN', '')),
                            'password': os.getenv('UPLOAD_RAPIDGATOR_PASSWORD', ''),
                            'is_main': True,
                        }
                    ],
                    'nitroflare': {
                        'username': os.getenv('NITROFLARE_LOGIN', ''),
                        'password': os.getenv('NITROFLARE_PASSWORD', ''),
                    },
                    'dddownload': {
                        'username': os.getenv('DDOWNLOAD_LOGIN', ''),
                        'password': os.getenv('DDOWNLOAD_PASSWORD', ''),
                    },
                    'katfile': {
                        'username': os.getenv('KATFILE_LOGIN', ''),
                        'password': os.getenv('KATFILE_PASSWORD', ''),
                    },
                    'keeplinks': {
                        'username': os.getenv('KEEP_LINKS_USERNAME', ''),
                        'password': os.getenv('KEEP_LINKS_PASSWORD', ''),
                    },
                },
            }
            
            # Update with defaults for missing keys
            for key, value in default_settings.items():
                if key not in self.user_settings:
                    self.user_settings[key] = value
            # Sanitize upload hosts list in case older files stored null entries
            upload_hosts = self.user_settings.get('upload_hosts', [])
            if not isinstance(upload_hosts, list):
                upload_hosts = []
            upload_hosts = [h for h in upload_hosts if isinstance(h, str) and h.strip()]
            if not upload_hosts:
                upload_hosts = list(default_upload_hosts)
            self.user_settings['upload_hosts'] = upload_hosts
            
            # Save updated settings
            self._save_user_settings()
            
        except Exception as e:
            logging.error(f"❌ Failed to load user settings: {e}")
            self.user_settings = {}
    
    def _save_user_settings(self) -> bool:
        """Save user-specific settings to their data directory."""
        try:
            settings_file = 'user_settings.json'
            return self.save_user_data(settings_file, self.user_settings)
        except Exception as e:
            logging.error(f"❌ Failed to save user settings: {e}")
            return False
    
    def _load_last_session(self):
        """Load the last logged-in user from session file."""
        try:
            last_session_file = os.path.join(self.data_dir, '.last_session')
            
            if os.path.exists(last_session_file):
                with open(last_session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                
                last_user = session_data.get('last_user')
                if last_user:
                    logging.info(f"🔄 Restoring last session for user: {last_user}")
                    self.set_current_user(last_user)
        
        except Exception as e:
            logging.error(f"❌ Failed to load last session: {e}")
    
    def _save_last_session(self):
        """Save the current user as the last session."""
        try:
            if not self.current_user:
                return
            
            last_session_file = os.path.join(self.data_dir, '.last_session')
            session_data = {
                'last_user': self.current_user,
                'timestamp': datetime.now().isoformat()
            }
            
            with open(last_session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=4)
        
        except Exception as e:
            logging.error(f"❌ Failed to save last session: {e}")

    # ------------------------------------------------------------------
    # Stats helpers
    # ------------------------------------------------------------------
    def get_main_account(self, site: str) -> Optional[Dict[str, Any]]:
        """Return credentials dict for the given site.

        For Rapidgator multiple accounts may exist; the one with
        ``is_main`` set to ``True`` is returned.
        """
        sites = self.user_settings.get("sites", {})
        creds = sites.get(site)
        if site == "rapidgator" and isinstance(creds, list):
            for acc in creds:
                if acc.get("is_main"):
                    return acc
            return creds[0] if creds else None
        if isinstance(creds, dict):
            return creds
        # Fallback to environment variables if not configured in settings
        env_map = {
            "rapidgator": (
                os.getenv("UPLOAD_RAPIDGATOR_USERNAME")
                or os.getenv("UPLOAD_RAPIDGATOR_LOGIN", ""),
                os.getenv("UPLOAD_RAPIDGATOR_PASSWORD", ""),
            ),
            "nitroflare": (
                os.getenv("NITROFLARE_LOGIN", ""),
                os.getenv("NITROFLARE_PASSWORD", ""),
            ),
            "dddownload": (
                os.getenv("DDOWNLOAD_LOGIN", ""),
                os.getenv("DDOWNLOAD_PASSWORD", ""),
            ),
            "katfile": (
                os.getenv("KATFILE_LOGIN", ""),
                os.getenv("KATFILE_PASSWORD", ""),
            ),
            "keeplinks": (
                os.getenv("KEEP_LINKS_USERNAME", ""),
                os.getenv("KEEP_LINKS_PASSWORD", ""),
            ),
        }
        if site in env_map:
            user, pwd = env_map[site]
            if user and pwd:
                return {"username": user, "password": pwd}
        return None

    def _is_logged_in(self, site: str, session: requests.Session) -> bool:
        """Check whether *session* is currently authenticated for *site*."""
        try:
            if site == "rapidgator":
                r = session.get("https://rapidgator.net/profile", timeout=15)
                return r.status_code == 200 and "Premium status" in r.text
            if site == "nitroflare":
                r = session.get("https://nitroflare.com/member", timeout=15)
                return "logout" in r.text.lower()
            if site == "dddownload":
                r = session.get("https://dddownload.com/?op=my_reports&ajax=1", timeout=15)
                ct = r.headers.get("Content-Type", "").lower()
                return ct.startswith("application/json")
            if site == "katfile":
                r = session.get("https://katfile.com/?op=my_reports&ajax=1", timeout=15)
                ct = r.headers.get("Content-Type", "").lower()
                return ct.startswith("application/json")
            if site == "keeplinks":
                r = session.get("https://www.keeplinks.org/earnings", timeout=15)
                return "Today's Earnings" in r.text
        except Exception as exc:
            logging.debug("Login check failed for %s: %s", site, exc)
        return False

    def _inject_json_cookies(self, sess: requests.Session, site: str):
            """Load shared JSON cookie file from /data/ and add to *sess*."""
            file_map = {
                "rapidgator": "cookies_rapidgator.json",
                "nitroflare": "cookies_nitroflare.json",
                "dddownload": "cookies_dddownload.json",
                "katfile": "cookies_katfile.json",
                "keeplinks": "cookies_keeplinks.json",
            }
            fname = file_map.get(site)
            if not fname:
                return
            path = DATA_DIR / fname
            if not path.exists():
                return
            try:
                for c in json.load(path.open(encoding="utf-8")):
                    sess.cookies.set(
                        c["name"], c["value"],
                        domain=c.get("domain", ""), path=c.get("path", "/"),
                    )
                logging.info("✅ JSON cookies injected for %s", site)
            except Exception as exc:
                logging.error("❌ Failed to inject cookies for %s: %s", site, exc)
    # ------------------------------------------------------------------
    def get_session(self, site: str) -> Optional[requests.Session]:
        """Return an authenticated `requests.Session` for *site*.

        يحاول أولاً إعادة جلسة مُخزَّنة؛
        وإلا يحمِّل كوكى المتصفّح (Chrome/Firefox) لهذا الدومين.
        """
        # 1) Session مخزَّنة بالفعل؟
        sess = self._site_sessions.get(site)
        if sess and self._is_logged_in(site, sess):
            return sess

        # 2) نحتاج جلسة جديدة
        sess = requests.Session()
        self._inject_json_cookies(sess, site)
        if self._is_logged_in(site, sess):
            self._site_sessions[site] = sess
            return sess

        domain_map = {
            "rapidgator": ".rapidgator.net",
            "nitroflare": ".nitroflare.com",
            "dddownload": ".dddownload.com",
            "katfile":    ".katfile.com",
            "keeplinks":  ".keeplinks.org",
        }
        domain = domain_map.get(site)
        if not domain:
            logging.error("Unsupported site '%s' for get_session()", site)
            return None

        # 3) تحميل كوكى المتصفّح
        try:
            cookies = browser_cookie3.chrome(
                domain_name=domain.lstrip("."),
                profile=r"C:\Users\rsher\AppData\Local\Google\Chrome\User Data\Profile 1",
            )
        except Exception as exc:
            logging.error("❌ Failed to load cookies for %s: %s", site, exc)
            return None
        sess.cookies.update(cookies)

        # 4) فحص أن الكوكى فعّالة (مُسجَّلة الدخول)
        if self._is_logged_in(site, sess):
            self._site_sessions[site] = sess
            logging.info("✅ Session loaded from browser cookies for %s", site)
            return sess

        logging.error("❌ Browser cookies invalid or expired for %s", site)
        return None

    def clear_session(self):
        """Clear the current user session and reset state."""
        logging.info(f"🔄 Clearing session for user: {self.current_user}")
        
        # Clear current user and data directory
        self.current_user = None
        self.user_data_dir = None
        self.user_settings.clear()
        
        # Remove last session file
        try:
            last_session_file = os.path.join(self.data_dir, '.last_session')
            if os.path.exists(last_session_file):
                os.remove(last_session_file)
                logging.info("🗑️ Removed last session file")
        except Exception as e:
            logging.error(f"❌ Failed to remove last session file: {e}")
        
        logging.info("✅ Session cleared successfully")


# Global user manager instance
user_manager = UserManager()


def get_user_manager() -> UserManager:
    """Get the global user manager instance."""
    return user_manager
