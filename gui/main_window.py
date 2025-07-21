from config.config import DATA_DIR
from workers.download_worker import DownloadWorker
from workers.upload_worker   import UploadWorker
from workers.worker_thread   import WorkerThread
from workers.megathreads_worker import MegaThreadsWorkerThread
from workers.mega_download_worker import MegaDownloadWorker
from .settings_widget import SettingsWidget
from downloaders.katfile import KatfileDownloader as KatfileDownloaderAPI
from PyQt5.QtWidgets import QApplication, QAction
from config.config import save_configuration
from .themes import theme_manager, style_manager
from pathlib import Path
import hashlib
import logging
import random
import re
import time
import subprocess
import shutil
from selenium.common import TimeoutException, ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from .dialogs import DownloadProgressDialog, LinksDialog
from .upload_progress_dialog import UploadProgressDialog
from core.file_processor import FileProcessor
from core.file_monitor import FileMonitor
from workers.login_thread import LoginThread
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QSplitter, QListWidget, QListWidgetItem, QStackedWidget,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QTextEdit, QGroupBox, QProgressBar, QStatusBar,
                             QToolBar, QAction, QMessageBox, QInputDialog, QFileDialog,
                             QTreeWidget, QTreeWidgetItem, QTreeView, QCheckBox, QComboBox, QSpinBox,
                             QTabWidget, QFrame, QScrollArea, QSizePolicy, QTextBrowser,
                             QAbstractItemView, QShortcut, QMenu, QProgressDialog, QDialogButtonBox,
                             QErrorMessage, QDialog, QStyle, QStyledItemDelegate, QStyleOptionViewItem)
from PyQt5.QtGui import QGuiApplication, QScreen
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject, QSize, QMutex, QMutexLocker, QDateTime, Q_ARG, QMetaObject
from PyQt5.QtGui import QIcon, QFont, QPixmap, QStandardItemModel, QStandardItem, QKeySequence, QTextCursor, QBrush, QColor, QPalette

# Import modern UI components
from .components import (
    ModernSidebar, ModernCard, ModernSectionCard, 
    ModernScrollArea, ModernContentContainer
)
from gui.utils.responsive_manager import ResponsiveManager
import webbrowser
from core.selenium_bot import ForumBotSelenium as SeleniumBot
from config.config import load_configuration
from utils import sanitize_filename
from utils.paths import get_data_folder
from core.user_manager import get_user_manager
from core.category_manager import CategoryManager
from gui.advanced_bbcode_editor import AdvancedBBCodeEditor
import os
import sys
import json
import logging
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString
from dotenv import set_key, find_dotenv
from .upload_progress_handler import UploadProgressHandler
from .upload_status_handler import UploadStatusHandler
from .advanced_bbcode_editor import AdvancedBBCodeEditor
from utils import sanitize_filename
from urllib.parse import urlparse, urlunparse
from PyQt5.QtWidgets import QProgressBar, QMessageBox
from utils.paths import get_data_folder

# import the DownloadWorker AGAIN if needed

class StatusColorDelegate(QStyledItemDelegate):
    """Paints thread status cells with appropriate colors based on status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status_colors = {}  # Will be updated in init_theme_colors
        self.init_theme_colors()

    def init_theme_colors(self):
        """Initialize theme colors."""
        theme = theme_manager.get_current_theme()
        self.status_colors = {
            'status-pending': theme.SURFACE_VARIANT,
            'status-downloaded': theme.WARNING,
            'status-uploaded': theme.INFO,
            'status-posted': theme.SUCCESS,
            'status-error': theme.ERROR
        }

    def initStyleOption(self, option, index):
        """Initialize the style options with the current theme."""
        super().initStyleOption(option, index)
        # Ensure we have the latest theme colors
        self.init_theme_colors()

    def paint(self, painter, option, index):
        """Paint the item with the appropriate background and text colors."""
        # Get status from item data
        status = index.data(Qt.UserRole) or 'status-pending'

        if status in self.status_colors:
            # Initialize style options
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)  # Pass index, not option
            
            # Get colors for this status
            bg_color = QColor(self.status_colors[status])
            is_highlighted = option.state & QStyle.State_Selected
            is_hovered = option.state & QStyle.State_MouseOver

            # Set background color
            if is_highlighted:
                # Use theme's selection color when selected
                bg_color = QColor(theme_manager.get_current_theme().PRIMARY)
            elif is_hovered:
                # Lighten the color on hover
                bg_color = bg_color.lighter(110)

            # Set text color based on background brightness
            bg_brightness = (bg_color.red() * 299 +
                           bg_color.green() * 587 +
                           bg_color.blue() * 114) / 1000

            text_color = (QColor(theme_manager.get_current_theme().TEXT_ON_PRIMARY)
                        if bg_brightness < 128 or is_highlighted
                        else QColor(theme_manager.get_current_theme().TEXT_PRIMARY))

            # Apply colors
            opt.backgroundBrush = QBrush(bg_color)
            opt.palette.setColor(QPalette.Text, text_color)
            opt.palette.setColor(QPalette.HighlightedText, text_color)

            # Fill background
            painter.save()
            painter.fillRect(option.rect, bg_color)

            # Draw the text
            text_rect = option.rect.adjusted(4, 0, -4, 0)  # Add some padding
            text = opt.text
            text_flags = Qt.AlignVCenter | Qt.AlignLeft | Qt.TextSingleLine

            # Calculate text width for elision
            text_width = opt.fontMetrics.horizontalAdvance(text)
            if text_width > text_rect.width():
                text = opt.fontMetrics.elidedText(text, Qt.ElideRight, text_rect.width())

            painter.setPen(text_color)
            painter.drawText(text_rect, text_flags, text)
            painter.restore()
        else:
            # Fallback to default painting
            super().paint(painter, option, index)
class LinkStatusDelegate(QStyledItemDelegate):
    """Paint Rapidgator link cells green or red based on alive/dead status."""

    def paint(self, painter, option, index):
        status = index.data(Qt.UserRole)
        if status in ("alive", "dead"):
            alive = status == "alive"
            bg = QColor(144, 238, 144) if alive else QColor(255, 99, 71)
            if option.state & QStyle.State_Selected:
                # Darken when selected so text remains readable
                bg = bg.darker(110)
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.setPen(Qt.black)
            painter.drawText(option.rect.adjusted(4, 0, -4, 0),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             index.data())
            painter.restore()
        else:
            super().paint(painter, option, index)
class ForumBotGUI(QMainWindow):
    # Define Qt signals for thread-safe UI updates
    thread_status_updated = pyqtSignal()
    
    # Define supported file extensions
    ARCHIVE_EXTENSIONS = ('.rar', '.zip')
    WINDOWS_FILE_EXTENSIONS = ('.pdf', '.epub', '.docx', '.xlsx', '.pptx', '.txt')  # Add more as needed
    OTHER_ENV_FILE_EXTENSIONS = ('.dmg', '.deb', '.apk', '.exe', '.bin')  # Add more as needed

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.user_manager = get_user_manager()
        self.active_upload_hosts = list(self.config.get('upload_hosts', []))
        if not self.active_upload_hosts:
            env_hosts = os.getenv('UPLOAD_HOSTS', '')
            self.active_upload_hosts = [h.strip() for h in env_hosts.split(',') if h.strip()]
            if self.active_upload_hosts:
                self.config['upload_hosts'] = list(self.active_upload_hosts)

        # Rapidgator backup preference
        self.use_backup_rg = bool(self.config.get('use_backup_rg', False))
        if self.use_backup_rg and 'rapidgator-backup' not in self.active_upload_hosts:
            self.active_upload_hosts.append('rapidgator-backup')
        elif not self.use_backup_rg and 'rapidgator-backup' in self.active_upload_hosts:
            self.active_upload_hosts.remove('rapidgator-backup')
        self.config['upload_hosts'] = list(self.active_upload_hosts)

        # Initialize the handler first
        self.progress_handler = None
        self.upload_handler = UploadStatusHandler()
        self.upload_progress_dialog = None

        # Initialize the bot (without download_dir to defer until user login)
        self.bot = SeleniumBot(
            forum_url=self.config['forum_url'],
            username=self.config['username'],
            password=self.config['password'],
            protected_category=self.config['protected_category'],
            headless=self.config.get('headless', False),
            config=self.config,
            user_manager=self.user_manager
        )
        self.bot.use_backup_rg = self.use_backup_rg
        
        # Initialize Rapidgator token from config
        self.bot.rapidgator_token = self.config.get('rapidgator_api_token', '')
        print(f"🤖 DEBUG: Bot initialized successfully: {self.bot is not None}")
        logging.info(f"🤖 DEBUG: Bot initialized successfully: {self.bot is not None}")

        # Initialize WinRAR path
        self.winrar_exe_path = self.config.get('winrar_exe_path', 'C:/Program Files/WinRAR/WinRAR.exe')

        # Initialize FileProcessor with default download directory
        # Actual download directory will be set after user login based on user settings
        try:
            default_download_dir = os.path.join(os.path.expanduser('~'), 'Downloads', 'ForumBot')
            self.file_processor = FileProcessor(
                download_dir=default_download_dir,
                winrar_path=self.winrar_exe_path
            )
            logging.info(f"FileProcessor initialized with WinRAR path: {self.winrar_exe_path}")
            logging.info("📂 Download directory will be set after user login based on user settings")
        except Exception as e:
            logging.error(f"Error initializing FileProcessor: {e}")
            QMessageBox.critical(self, "Initialization Error",
                                 f"Failed to initialize FileProcessor: {str(e)}\nPlease check your WinRAR installation.")
            raise

        # Initialize CategoryManager
        self.category_manager = CategoryManager(
            self.config['forum_section_url'],
            self.bot.driver,
            self.config['username'],
            self.user_manager
        )

        # Megathreads category manager
        self.megathreads_category_manager = CategoryManager(
            self.config['forum_section_url'],
            self.bot.driver,
            f"{self.config['username']}_megathreads",
            self.user_manager
        )
        self.megathreads_category_manager.load_categories()

        # Data structures
        self.category_threads = {}
        self.category_workers = {}
        self.current_category = None
        self.bot_lock = QMutex()
        self.process_threads = {}
        self.backup_threads = {}
        self.megathreads_workers = {}
        self.megathreads_data = {}
        self.megathreads_process_threads = {}

        # Initialize timers
        self.init_timers()

        # **هنا ننشئ download_progress_bar قبل initUI**
        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setValue(0)
        self.download_progress_bar.setVisible(False)

        # ثم ننادي على initUI
        self.initUI()

        # بعد initUI أصبح بإمكاننا الوصول لـ process_threads_table
        self.progress_handler = UploadProgressHandler(self.process_threads_table)
        
        # Connect the thread status update signal to the UI refresh method  
        self.thread_status_updated.connect(self.refresh_process_threads_table)

        # Initialize empty data structures (don't load files before login)
        self.process_threads = {}
        self.backup_threads = {}
        self.replied_thread_ids = set()
        
        # File monitor
        self.file_monitor = FileMonitor()

        # ربط البوت بالـ upload handler
        self.upload_handler.set_bot(self.bot)

        # Initialize log viewer only (no data loading)
        try:
            self.init_log_viewer()
            self.last_double_click_time = QDateTime.currentDateTime()
            self.backup_threads_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.backup_threads_table.customContextMenuRequested.connect(self.show_backup_threads_context_menu)
            logging.info("GUI initialization completed successfully")
        except Exception as e:
            logging.error(f"Error during GUI initialization: {e}")
            QMessageBox.warning(self, "Initialization Warning",
                                "Some components failed to initialize. The application may have limited functionality.")

        # تحقق من المكونات الحرجة
        self._verify_critical_components()

        # ملء شجرة Megathreads بعد كل شيء
        self.populate_megathreads_category_tree()
        
        # Check if user session was restored but don't auto-load user data
        # Users must explicitly login to see their data (strict data isolation)
        current_user = self.user_manager.get_current_user()
        if current_user:
            logging.info(f"🔄 Session found for user: {current_user}, but data loading deferred until explicit login")
            # Clear any restored session for strict data isolation
            self.user_manager.clear_current_session()
            # Clear all user data from memory to prevent data leakage
            self.clear_user_data_on_logout()
            logging.info("🔒 Session cleared - user must login explicitly to access data")

    # ------------------------- NEW ENHANCEMENT START -------------------------
    def on_theme_toggled(self, checked: bool):
        """
        Toggle between Dark and Light theme.
          checked == True  → Light  mode
          checked == False → Dark   mode
        """
        # 1) Toggle theme in ThemeManager
        if checked:
            theme_manager.switch_theme("light")
            self.theme_toggle_action.setText("☀️ Dark Mode")  # After clicking, can switch back to dark
        else:
            theme_manager.switch_theme("dark")
            self.theme_toggle_action.setText("🌙 Light Mode")

        # 2) Reapply QSS to the entire application
        QApplication.instance().setStyleSheet(style_manager.get_complete_stylesheet())

        # 3) Reapply Palette (for native widgets)
        self.apply_global_theme()

        # 4) Update all widgets with update_style() method (cards, sidebar, etc.)
        for w in self.findChildren(QWidget):
            if hasattr(w, "update_style"):
                try:
                    w.update_style()
                except Exception:
                    pass

        # 5) Save user preference to config file
        self.config["use_dark_mode"] = not checked  # True means dark mode
        save_configuration(self.config)

        # Redraw Process-Threads table to update delegate colors
        if hasattr(self, "process_threads_table"):
            self.process_threads_table.viewport().update()
            
        # Apply responsive layout after theme change
        ResponsiveManager.apply(self)
        
    def resizeEvent(self, event):
        """Handle window resize events to update responsive layouts."""
        super().resizeEvent(event)
        ResponsiveManager.apply(self)

    def init_settings_view(self):
        """
        Initialize the Settings tab and add it to the content_area.
        """
        # استيراد الويجت الخاص بالإعدادات
        from gui.settings_widget import SettingsWidget

        self.settings_tab = SettingsWidget(self.config)
        
        # Connect the download directory changed signal
        self.settings_tab.download_directory_changed.connect(self.on_download_directory_changed)
        
        # Connect the hosts updated signal
        self.settings_tab.hosts_updated.connect(self.on_upload_hosts_updated)

        # Connect Rapidgator backup toggle
        self.settings_tab.use_backup_rg_changed.connect(self.on_use_backup_rg_changed)


        # إضافته لمنطقة المحتوى
        self.content_area.addWidget(self.settings_tab)

    def apply_settings(self):
        # مسار التحميل الجديد
        new_dl = self.config['download_dir']
        self.file_processor.download_dir = new_dl
        self.bot.download_dir = new_dl

        # قائمة المضيفين
        self.active_upload_hosts = list(self.config['upload_hosts'])

        # (اختياري) حدّث أي ويدجت عرض المسار
        # مثلاً لو عندك label لعرض WinRAR path
        self.winrar_exe_label.setText(f"WinRAR Executable: {self.config.get('winrar_exe_path')}")
        
    def on_download_directory_changed(self, new_download_dir):
        """
        Handle download directory changes from settings widget.
        Updates bot and file processor with new download directory.
        """
        try:
            # Update bot's download directory
            self.bot.update_download_directory(new_download_dir)
            
            # Update file processor's download directory
            if hasattr(self, 'file_processor'):
                self.file_processor.download_dir = new_download_dir
                logging.info(f"📁 FileProcessor download directory updated to: {new_download_dir}")
            
            logging.info(f"✅ Download directory successfully updated to: {new_download_dir}")
            
        except Exception as e:
            logging.error(f"❌ Error updating download directory: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update download directory: {str(e)}")
            
    def on_upload_hosts_updated(self, hosts_list):
        """
        Handle upload hosts list changes from settings widget.
        Updates bot and config with new upload hosts list.
        
        Args:
            hosts_list (list): List of upload host names
        """
        try:
            # Sanitize the incoming list to remove empty or invalid entries
            hosts_list = [h for h in hosts_list if isinstance(h, str) and h.strip()]

            # Update the config
            self.config['upload_hosts'] = hosts_list

            # Update the active_upload_hosts list
            self.active_upload_hosts = list(hosts_list)

            # Update the active_upload_hosts list
            if hasattr(self, 'bot') and self.bot:
                self.bot.upload_hosts = list(hosts_list)  # Make a copy to avoid reference issues
                logging.info(f"🔄 Updated upload hosts in bot: {hosts_list}")
                
                # If bot has an uploader, update its hosts too
                if hasattr(self.bot, 'uploader') and self.bot.uploader:
                    self.bot.uploader.upload_hosts = list(hosts_list)
                    logging.info(f"🔄 Updated upload hosts in bot.uploader: {hosts_list}")

            # Persist to .env so next launch uses the same hosts
            dotenv_path = find_dotenv()
            if dotenv_path:
                set_key(dotenv_path, 'UPLOAD_HOSTS', ','.join(hosts_list))
            # Persist to user settings if a user is logged in
            if self.user_manager.get_current_user():
                self.user_manager.set_user_setting('upload_hosts', hosts_list)
                logging.info("🔄 Updated upload hosts in user settings")
            logging.info(f"✅ Upload hosts successfully updated: {hosts_list}")
            
        except Exception as e:
            logging.error(f"❌ Error updating upload hosts: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update upload hosts: {str(e)}")

    def on_use_backup_rg_changed(self, enabled: bool):
        """Handle Rapidgator backup toggle from settings."""
        try:
            self.use_backup_rg = bool(enabled)
            self.config['use_backup_rg'] = self.use_backup_rg

            # Update bot instance if available
            if hasattr(self, 'bot') and self.bot:
                self.bot.use_backup_rg = self.use_backup_rg

            # Ensure host list reflects the setting
            if self.use_backup_rg:
                if 'rapidgator-backup' not in self.active_upload_hosts:
                    self.active_upload_hosts.append('rapidgator-backup')
            else:
                if 'rapidgator-backup' in self.active_upload_hosts:
                    self.active_upload_hosts.remove('rapidgator-backup')

            self.config['upload_hosts'] = list(self.active_upload_hosts)
            if hasattr(self.bot, 'upload_hosts'):
                self.bot.upload_hosts = list(self.active_upload_hosts)

            # Persist user preference
            if self.user_manager.get_current_user():
                self.user_manager.set_user_setting('use_backup_rg', self.use_backup_rg)

            logging.info(
                f"Rapidgator backup uploads {'enabled' if self.use_backup_rg else 'disabled'}"
            )
        except Exception as e:
            logging.error(f"Error updating Rapidgator backup preference: {e}")


    def populate_megathreads_category_tree(self):
        self.megathreads_category_model.clear()
        self.megathreads_category_model.setHorizontalHeaderLabels(['Megathread Category'])
        for category_name, category_url in self.megathreads_category_manager.categories.items():
            item = QStandardItem(category_name)
            item.setData(category_url, Qt.UserRole)
            item.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
            self.megathreads_category_model.appendRow(item)
        self.megathreads_category_tree.expandAll()
    # ------------------------- NEW ENHANCEMENT END ---------------------------

    def add_megathreads_category(self):
        text, ok = QInputDialog.getText(self, 'Add Megathread Category', 'Enter category name:')
        if ok and text:
            url, ok_url = QInputDialog.getText(self, 'Add Category', 'Enter category URL:')
            if ok_url and url:
                success = self.megathreads_category_manager.add_category(text, url)
                if success:
                    QMessageBox.information(self, "Category Added",
                                            f"Category '{text}' added successfully to Megathreads.")
                    self.populate_megathreads_category_tree()
                else:
                    QMessageBox.warning(self, "Already Exists", f"Category '{text}' already exists.")
            else:
                QMessageBox.warning(self, "Invalid URL", "Category URL cannot be empty.")
        else:
            QMessageBox.warning(self, "Invalid Name", "Category name cannot be empty.")

    def _verify_critical_components(self):
        """Verify that all critical components are properly initialized."""
        critical_components = {
            'Bot': self.bot,
            'FileProcessor': self.file_processor,
            'CategoryManager': self.category_manager,
            'Download Directory': self.config.get('download_dir'),
            'WinRAR Path': self.winrar_exe_path
        }

        missing_components = []
        for component_name, component in critical_components.items():
            if component is None:
                missing_components.append(component_name)

        if missing_components:
            error_msg = f"Critical components missing: {', '.join(missing_components)}"
            logging.error(error_msg)
            QMessageBox.critical(self, "Initialization Error", error_msg)
            raise RuntimeError(error_msg)

    def get_sanitized_path(self, category_name, thread_id=None):
        sanitized_category = sanitize_filename(category_name)
        if thread_id is not None:
            sanitized_thread_id = sanitize_filename(str(thread_id))
            return os.path.join(self.bot.download_dir, sanitized_category, sanitized_thread_id)
        return os.path.join(self.bot.download_dir, sanitized_category)

    def find_part1_file(self, download_folder):
        """
        Enhanced method to find the first part of a multi-part archive or any archive file.
        """
        try:
            supported_extensions = ('.rar', '.zip', '.r00', '.part1.rar', '.001')

            # First, look for explicit part1 files
            part1_patterns = [
                r'.*\.part1\.rar$',
                r'.*\.part001\.rar$',
                r'.*\.001$',
                r'.*\.r00$'
            ]

            for pattern in part1_patterns:
                for root, _, files in os.walk(download_folder):
                    for file in files:
                        if re.match(pattern, file, re.IGNORECASE):
                            full_path = os.path.join(root, file)
                            logging.info(f"Found first part of archive: {full_path}")
                            return full_path

            # If no part1 file found, look for any supported archive
            for root, _, files in os.walk(download_folder):
                for file in files:
                    if file.lower().endswith(supported_extensions):
                        full_path = os.path.join(root, file)
                        logging.info(f"Found archive file: {full_path}")
                        return full_path

            logging.warning(f"No archive files found in {download_folder}")
            return None

        except Exception as e:
            logging.error(f"Error while searching for archive file: {e}", exc_info=True)
            return None

    def normalize_link(self, link):
        """
        Normalize a Rapidgator link by replacing 'rg.to' with 'rapidgator.net'.

        Parameters:
        - link (str): The original URL.

        Returns:
        - str: The normalized URL.
        """
        parsed_url = urlparse(link)
        if parsed_url.netloc.lower() == 'rg.to':
            # Replace 'rg.to' with 'rapidgator.net'
            parsed_url = parsed_url._replace(netloc='rapidgator.net')
            new_link = urlunparse(parsed_url)
            logging.info(f"Normalized Rapidgator link: {link} -> {new_link}")
            return new_link
        return link

    def normalize_rapidgator_links(self, links):
        """
        Normalize Rapidgator links in the links dictionary.

        Parameters:
        - links (dict): A dictionary with hosts as keys and list of links as values.

        Returns:
        - dict: A dictionary with normalized links.
        """
        normalized_links = {}
        for host, link_list in links.items():
            # Check if the host is Rapidgator or its shortened version
            if 'rapidgator' in host.lower() or 'rg.to' in host.lower():
                normalized_host = 'rapidgator.net'
                normalized_links.setdefault(normalized_host, [])
                for link in link_list:
                    normalized_link = self.normalize_link(link)
                    normalized_links[normalized_host].append(normalized_link)
            else:
                # For other hosts, retain the original links
                normalized_links[host] = link_list
        return normalized_links

    def prompt_for_password(self, archive_name):
        """
        Prompts user for password when needed.
        Implement this in your GUI class to show a dialog.
        """
        try:
            # Create password dialog
            password, ok = QInputDialog.getText(
                None,
                'Password Required',
                f'Enter password for {archive_name}:',
                QLineEdit.Password
            )
            if ok and password:
                return password
            return None
        except Exception as e:
            logging.error(f"Error prompting for password: {str(e)}")
            return None

    def modify_files_for_hash(self, folder_path):
        """
        Modifies all files to change their hash while preserving functionality.
        Handles any file type.
        """
        try:
            for root, _, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)

                    # Skip if file is too small
                    if os.path.getsize(file_path) < 10:
                        continue

                    try:
                        # Append random bytes to end of file
                        with open(file_path, 'ab') as f:
                            # Add random number of bytes (between 1-32)
                            num_bytes = random.randint(1, 32)
                            f.write(os.urandom(num_bytes))

                        logging.info(f"Modified file hash: {file_path}")
                    except Exception as file_error:
                        logging.error(f"Error modifying file {file_path}: {str(file_error)}")
                        continue

        except Exception as e:
            logging.error(f"Error in modify_files_for_hash: {str(e)}")

    def handle_other_env_file(self, file_path, download_folder):
        """
        Modifies other environment files to change their hash while preserving functionality.
        """
        try:
            # Modify the file by appending a non-functional byte
            with open(file_path, 'ab') as f:
                f.write(b'\0')  # Appending a null byte

            logging.info(f"Modified file to change hash: '{file_path}'.")
        except Exception as e:
            self.handle_exception("handle_other_env_file", e)
            raise e

    def archive_file(self, source_file, archive_path, archive_format='rar'):
        """
        Archives a single file using WinRAR.

        Parameters:
        - source_file (str): Path to the file to archive.
        - archive_path (str): Path where the archive will be created.
        - archive_format (str): 'rar' or 'zip'
        """
        try:
            logging.info(f"Archiving '{source_file}' to '{archive_path}' as {archive_format.upper()}.")

            # Determine the archive format flag
            if archive_format == 'rar':
                format_flag = '-afrar'
            elif archive_format == 'zip':
                format_flag = '-afzip'
            else:
                raise ValueError("Unsupported archive format. Use 'rar' or 'zip'.")

            # Build the WinRAR command
            command = [
                self.winrar_exe_path,
                'a',            # Add to archive
                format_flag,    # Specify archive format
                '-y',           # Assume Yes on all queries
                archive_path,   # Destination archive
                os.path.basename(source_file)  # Source file (relative path)
            ]

            logging.debug(f"Executing command: {' '.join(command)} in directory '{os.path.dirname(source_file)}'")

            # Execute the command in the source file's directory
            result = subprocess.run(command, capture_output=True, text=True, cwd=os.path.dirname(source_file))

            if result.returncode != 0:
                logging.error(f"Archiving failed: {result.stdout} {result.stderr}")
                raise Exception(f"Archiving failed for '{source_file}'.")
            else:
                logging.info(f"Archiving completed successfully for '{source_file}'.")
        except Exception as e:
            self.handle_exception("archive_file", e)
            raise e

    def handle_exception(self, context, exception):
        """
        Centralized exception handling method.

        Parameters:
        - context (str): A description of where the exception occurred.
        - exception (Exception): The exception object.
        """
        logging.error(f"Exception in {context}: {exception}", exc_info=True)
        QMessageBox.critical(self, "Error", f"An error occurred in {context}: {exception}")

    def initUI(self):
        self.setWindowTitle('  🚀 ForumBot Pro - Selenium Enhanced  ')
        
        # Get primary screen's available geometry
        screen = QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        
        # Calculate window size as 85% of screen size
        width = int(screen_geometry.width() * 0.85)
        height = int(screen_geometry.height() * 0.85)
        
        # Set window size and center it on screen
        self.resize(width, height)
        self.move(
            screen_geometry.x() + (screen_geometry.width() - width) // 2,
            screen_geometry.y() + (screen_geometry.height() - height) // 2
        )
        
        # Set window icon using built-in system icons
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        
        # Improve window margins and appearance
        self.setContentsMargins(8, 8, 8, 8)
        
        # Main widget and layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Modern Sidebar with responsive width
        self.sidebar = ModernSidebar(self)
        responsive_width = ResponsiveManager.get_responsive_sidebar_width()
        self.sidebar.setFixedWidth(responsive_width)
        
        # Add sidebar items with modern icons
        self.sidebar.add_item("Posts", "📝")
        self.sidebar.add_item("Backup", "💾")
        self.sidebar.add_item("Process Threads", "⚡")
        self.sidebar.add_item("Megathreads", "🗂️")
        self.sidebar.add_item("Settings", "⚙️")
        
        # Connect sidebar signals
        self.sidebar.item_clicked.connect(self.on_sidebar_item_clicked)
        
        main_layout.addWidget(self.sidebar)

        # Main content splitter
        content_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(content_splitter)
        
        # Content Area (QStackedWidget) - styling handled by global theme
        self.content_area = QStackedWidget()
        content_splitter.addWidget(self.content_area)

        # Adding Widgets to the Content Area
        self.init_posts_view()
        self.init_backup_view()
        self.init_process_threads_view()
        self.init_megathreads_view()  # Initialize the new Megathreads view
        self.init_settings_view()  # Initialize the new Settings view

        # Right Sidebar for Login with modern styling
        self.init_login_section(content_splitter)

        # Set Stretch Factors for Splitter with responsive behavior
        content_splitter.setStretchFactor(0, 3)  # Content Area 
        content_splitter.setStretchFactor(1, 1)  # Login Section
        
        # Set minimum widths for responsive behavior
        self.content_area.setMinimumWidth(400)
        self.sidebar.setMinimumWidth(220)
        
        # Set layout stretch properly
        main_layout.setStretchFactor(self.sidebar, 0)  # Sidebar - fixed width
        main_layout.setStretchFactor(content_splitter, 1)  # Content splitter - flexible

        # Status bar
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.addPermanentWidget(self.download_progress_bar)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(20, 20))  # Smaller icon size for a cleaner look
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        toolbar.addAction(QIcon.fromTheme("document-save"), "Save Data", self.save_data)
        toolbar.addAction(QIcon.fromTheme("view-refresh"), "Refresh Categories", self.refresh_categories)
        toolbar.addAction(QIcon.fromTheme("system-log-out"), "Logout", self.handle_logout)
        start_tracking_action = QAction(QIcon.fromTheme("media-playback-start"), "Start Tracking", self)
        start_tracking_action.triggered.connect(self.start_tracking)
        toolbar.addAction(start_tracking_action)
        # ─── Light / Dark Mode Toggle ─────────────────────────────
        self.theme_toggle_action = QAction("🌙 Light Mode", self)
        self.theme_toggle_action.setCheckable(True)
        self.theme_toggle_action.toggled.connect(self.on_theme_toggled)
        toolbar.addAction(self.theme_toggle_action)

        # Default Selection - set first item as active
        self.sidebar.set_active_item_by_text("Posts")
        self.content_area.setCurrentIndex(0)

        # Setup keyboard shortcuts
        self.setup_shortcuts()
        
        # Apply global modern theme styling AFTER all UI is created
        self.apply_global_theme()
        
        # ── Fade-in effect for the main window ────────────────────────────
        from PyQt5.QtCore import QPropertyAnimation
        # Start with 0 opacity
        self.setWindowOpacity(0.0)
        # Create animation for the opacity property
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(900)      # 900ms duration
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def apply_global_theme(self):
        """Apply modern theme to the entire application"""
        # 1) Get complete stylesheet from StyleManager and apply it
        complete_stylesheet = style_manager.get_complete_stylesheet()
        self.setStyleSheet(complete_stylesheet)

        # 2) Apply responsive behavior using the ResponsiveManager
        ResponsiveManager.apply(self)

        # 3) Dynamic palette based on current theme
        theme = theme_manager.get_current_theme()
        from PyQt5.QtGui import QPalette, QColor
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(theme.BACKGROUND))
        palette.setColor(QPalette.WindowText, QColor(theme.TEXT_PRIMARY))
        palette.setColor(QPalette.Base, QColor(theme.SURFACE))
        palette.setColor(QPalette.AlternateBase, QColor(theme.SURFACE_VARIANT))
        palette.setColor(QPalette.Text, QColor(theme.TEXT_PRIMARY))
        palette.setColor(QPalette.Button, QColor(theme.SURFACE))
        palette.setColor(QPalette.ButtonText, QColor(theme.TEXT_PRIMARY))
        palette.setColor(QPalette.Highlight, QColor(theme.PRIMARY))
        palette.setColor(QPalette.HighlightedText, QColor(theme.TEXT_ON_PRIMARY))
        self.setPalette(palette)

        # 4) Auto-login logic (unchanged)
        current_user = self.user_manager.get_current_user() if self.user_manager else None
        logging.info(f"🔍 DEBUG: Bot is_logged_in: {self.bot.is_logged_in}")
        logging.info(f"🔍 DEBUG: Current user: {current_user}")

        if self.bot.is_logged_in:
            self.statusBar().showMessage(
                'Auto-logged in via saved cookies - Use explicit login to access user data'
            )
            self.login_button.setEnabled(False)
            self.username_input.setEnabled(False)
            self.password_input.setEnabled(False)

            if self.user_manager and self.user_manager.get_current_user():
                logging.info(
                    f"🔄 Auto-login: Loading processed thread IDs for tracking purposes"
                )
                self.bot.update_user_file_paths()
                self.bot.load_processed_thread_ids()
                logging.info(
                    f"✅ Auto-login: Loaded {len(self.bot.processed_thread_ids)} processed thread IDs"
                )
            else:
                logging.warning(
                    f"⚠️ Auto-login: No current user or user_manager not available"
                )

            self.populate_category_tree(load_saved=True)
            winrar_exe_path = self.config.get(
                'winrar_exe_path',
                'C:/Program Files/WinRAR/WinRAR.exe'
            )
            self.winrar_exe_label.setText(f"WinRAR Executable: {winrar_exe_path}")

        else:
            if self.user_manager and self.user_manager.get_current_user():
                logging.info(
                    f"🔄 Startup: Loading processed thread IDs for user session tracking"
                )
                self.bot.update_user_file_paths()
                self.bot.load_processed_thread_ids()
                logging.info(
                    f"✅ Startup: Loaded {len(self.bot.processed_thread_ids)} processed thread IDs"
                )
            else:
                logging.info(
                    f"ℹ️ Startup: No user session found - using global processed thread IDs"
                )

            self.statusBar().showMessage('Please log in.')
    
    def run(self):
        """Show the main window and start the application"""
        self.show()
        self.raise_()
    # === STATUS COLOR MANAGEMENT ===
    def set_thread_status_color(self, tree_item, status):
        """
        Set thread item colors:
          - downloaded => theme.WARNING  (أصفر)
          - uploaded   => theme.INFO     (أزرق)
          - published  => theme.SUCCESS  (أخضر)
          - أي حالة أخرى => theme.SURFACE_VARIANT
        """
        if not tree_item:
            return

        theme = theme_manager.get_current_theme()

        if status == 'downloaded':
            bg_color = theme.WARNING
            fg_color = theme.TEXT_ON_PRIMARY
        elif status == 'uploaded':
            bg_color = theme.INFO
            fg_color = theme.TEXT_ON_PRIMARY
        elif status == 'published':
            bg_color = theme.SUCCESS
            fg_color = theme.TEXT_ON_PRIMARY
        else:
            bg_color = theme.SURFACE_VARIANT
            fg_color = theme.TEXT_PRIMARY

        brush_bg = QBrush(QColor(bg_color))
        brush_fg = QBrush(QColor(fg_color))

        tree_item.setBackground(0, brush_bg)
        tree_item.setForeground(0, brush_fg)
    def set_backup_link_status_color(self, item: QTableWidgetItem, alive: bool) -> None:
        """Color the Rapidgator link cell based on availability."""
        try:
            if not item:
                return
            if alive:
                item.setData(Qt.UserRole, "alive")
                item.setBackground(QColor(144, 238, 144))  # light green
            else:
                item.setData(Qt.UserRole, "dead")
                item.setBackground(QColor(255, 99, 71))  # tomato red
        except Exception as exc:
            logging.error(f"Failed setting backup link color: {exc}")
    def init_megathreads_view(self):
        """Initialize the Megathreads view with categories and threads"""
        # Create the main widget and layout
        megathreads_widget = QWidget()
        megathreads_layout = QVBoxLayout(megathreads_widget)
        megathreads_layout.setContentsMargins(5, 5, 5, 5)
        megathreads_layout.setSpacing(10)

        # Upper Section: Horizontal splitter for Categories and Threads
        upper_splitter = QSplitter(Qt.Horizontal)
        megathreads_layout.addWidget(upper_splitter)

        # Left Pane: Category Tree (for Megathreads)
        mega_categories_widget = QWidget()
        mega_categories_layout = QVBoxLayout(mega_categories_widget)
        mega_categories_label = QLabel("MegaThread Categories")
        mega_categories_label.setFont(QFont("Arial", 12, QFont.Bold))
        mega_categories_layout.addWidget(mega_categories_label)

        self.megathreads_category_tree = QTreeView()
        self.megathreads_category_model = QStandardItemModel()
        self.megathreads_category_tree.setModel(self.megathreads_category_model)
        self.megathreads_category_tree.clicked.connect(self.on_megathreads_category_clicked)
        self.megathreads_category_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        mega_category_controls = QHBoxLayout()
        add_mega_btn = QPushButton("Add Megathread Category")
        add_mega_btn.clicked.connect(self.add_megathread_category)
        mega_category_controls.addWidget(add_mega_btn)
        remove_mega_btn = QPushButton("Remove Megathread Category(s)")
        remove_mega_btn.clicked.connect(lambda: self.remove_megathread_categories(self.megathreads_category_tree.selectedIndexes()))
        mega_category_controls.addWidget(remove_mega_btn)
        mega_categories_layout.addLayout(mega_category_controls)
        mega_categories_layout.addWidget(self.megathreads_category_tree)
        upper_splitter.addWidget(mega_categories_widget)

        # Middle Pane: Megathreads and Versions
        mega_threads_widget = QWidget()
        mega_threads_layout = QVBoxLayout(mega_threads_widget)
        mega_threads_label = QLabel("MegaThreads")
        mega_threads_label.setFont(QFont("Arial", 12, QFont.Bold))
        mega_threads_layout.addWidget(mega_threads_label)


        # Controls Layout for Megathreads (removed tracking inputs)

        # Additional Control Buttons for tracking megathreads
        track_layout = QHBoxLayout()
        self.start_megathreads_tracking_button = QPushButton("Start Tracking Megathreads")
        self.start_megathreads_tracking_button.clicked.connect(self.start_megathreads_tracking)
        track_layout.addWidget(self.start_megathreads_tracking_button)

        self.keep_megathreads_tracking_button = QPushButton("Keep Tracking Megathreads")
        self.keep_megathreads_tracking_button.clicked.connect(self.keep_tracking_megathreads)
        track_layout.addWidget(self.keep_megathreads_tracking_button)
        self.stop_megathreads_tracking_button = QPushButton("Stop Tracking Megathreads")
        self.stop_megathreads_tracking_button.clicked.connect(self.stop_megathreads_tracking)
        track_layout.addWidget(self.stop_megathreads_tracking_button)

        mega_threads_layout.addLayout(track_layout)

        # Instead of a simple list, use a QTreeWidget for hierarchical display of megathreads and their versions
        self.megathreads_tree = QTreeWidget()
        self.megathreads_tree.setColumnCount(1)
        self.megathreads_tree.setHeaderLabels(["Megathread / Versions"])
        self.megathreads_tree.itemClicked.connect(self.on_megathreads_version_selected)
        mega_threads_layout.addWidget(self.megathreads_tree)

        upper_splitter.addWidget(mega_threads_widget)
        upper_splitter.setStretchFactor(0, 1)
        upper_splitter.setStretchFactor(1, 3)

        # Lower Section: BBCode Editor for Megathreads
        mega_bbcode_editor_group = QGroupBox("BBCode Editor")
        mega_bbcode_layout = QVBoxLayout(mega_bbcode_editor_group)
        self.megathreads_bbcode_editor = QTextEdit()
        mega_bbcode_layout.addWidget(self.megathreads_bbcode_editor)
        megathreads_layout.addWidget(mega_bbcode_editor_group)

        self.content_area.addWidget(megathreads_widget)

    def populate_megathreads_tree(self, category_name):
        """Populate the QTreeWidget with Megathreads and their versions for the given category."""
        self.megathreads_tree.clear()
        if category_name not in self.megathreads_data:
            return

        category_data = self.megathreads_data[category_name]
        for megathread_title, versions_list in category_data.items():
            megathread_item = QTreeWidgetItem([megathread_title])
            megathread_item.setExpanded(True)
            self.megathreads_tree.addTopLevelItem(megathread_item)

            for version_info in versions_list:
                version_title = version_info.get('version_title', 'Unknown Version')
                version_item = QTreeWidgetItem([version_title])
                # Store version data in the item
                version_item.setData(0, Qt.UserRole, version_info)
                megathread_item.addChild(version_item)

    def populate_megathreads_tree_from_process_threads(self, proceed_category_name):
        """Populate the QTreeWidget with tracked versions from self.megathreads_process_threads[proceed_category_name]."""
        self.megathreads_tree.clear()
        threads_data = self.megathreads_process_threads.get(proceed_category_name, {})
        if not threads_data:
            return

        for main_thread_title, data in threads_data.items():
            # 'data' should be a dict with 'versions' key
            versions_list = data.get('versions', [])
            if not isinstance(versions_list, list) or not versions_list:
                continue

            # Create a top-level item for the main megathread title
            megathread_item = QTreeWidgetItem([main_thread_title])
            megathread_item.setExpanded(True)
            self.megathreads_tree.addTopLevelItem(megathread_item)

            # versions_list should have 1 or 2 versions max
            # Show them in order they are stored: the newest is last
            for version_info in versions_list:
                version_title = version_info.get('version_title', 'Unknown Version')
                version_item = QTreeWidgetItem([version_title])
                # Store the entire version_info dict in the user data
                version_item.setData(0, Qt.UserRole, version_info)
                megathread_item.addChild(version_item)

        # Expand all to show the versions clearly
        self.megathreads_tree.expandAll()

    def on_megathreads_version_selected(self, item, column):
        """Handle selection of a version node in the Megathreads tree."""
        version_info = item.data(0, Qt.UserRole)
        if version_info and isinstance(version_info, dict):
            bbcode_content = version_info.get('bbcode_content', '')
            self.megathreads_bbcode_editor.setPlainText(bbcode_content)

    def on_sidebar_item_clicked(self, item):
        # Change content area based on sidebar selection
        index = self.sidebar.row(item)
        self.content_area.setCurrentIndex(index)

    # Similar to posts, we define a separate handler for category clicks in megathreads
    def on_megathreads_category_clicked(self, index):
        if not self.bot.is_logged_in:
            QMessageBox.warning(self, "Login Required", "Please log in before accessing megathread categories.")
            return

        item = self.megathreads_category_model.itemFromIndex(index)
        category_name = item.text()
        logging.info(f"Megathreads Category clicked: {category_name}")

        proceed_category_name = f"Megathreads_{category_name}"

        # Use megathreads_process_threads instead of process_threads
        if proceed_category_name in self.megathreads_process_threads and self.megathreads_process_threads[
            proceed_category_name]:
            self.populate_megathreads_tree_from_process_threads(proceed_category_name)
            self.statusBar().showMessage(f'Loaded tracked Megathreads for "{category_name}".')
        else:
            self.megathreads_tree.clear()
            self.megathreads_bbcode_editor.clear()
            QMessageBox.information(self, "No Data",
                                    f"No tracked data for '{category_name}'. Please track this megathread category first.")

    def stop_megathreads_tracking(self):
        """Stop tracking selected megathread categories."""
        indexes = self.megathreads_category_tree.selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection",
                                "Please select at least one megathread category to stop tracking.")
            return

        categories_to_stop = [self.megathreads_category_model.itemFromIndex(index).text() for index in indexes]
        
        for category_name in categories_to_stop:
            worker = self.megathreads_workers.pop(category_name, None)
            if worker:
                logging.info(f"⛔ Stopping megathreads worker for category '{category_name}'")
                
                try:
                    # 🔌 DISCONNECT SIGNALS: Prevent signal conflicts after restart
                    try:
                        worker.update_megathreads.disconnect()
                        worker.finished.disconnect()
                        logging.info(f"🔌 Disconnected megathreads signals for worker '{category_name}'")
                    except Exception as disconnect_error:
                        logging.warning(f"⚠️ Could not disconnect megathreads signals for '{category_name}': {disconnect_error}")
                    
                    # Stop the worker
                    worker.stop()
                    
                    # Wait for worker to stop with increased timeout
                    if not worker.wait(8000):  # Wait max 8 seconds (5+3 from worker timeout)
                        logging.warning(f"⚠️ Megathreads worker for '{category_name}' didn't stop gracefully, forcing termination")
                        worker.terminate()
                        worker.wait(2000)  # Wait 2 seconds for termination
                    
                    logging.info(f"✅ Successfully stopped megathreads monitoring for category '{category_name}'")
                    
                except Exception as e:
                    logging.error(f"❌ Error stopping megathreads worker for '{category_name}': {e}")
                    # Force terminate if there's an error
                    try:
                        worker.terminate()
                    except:
                        pass

        self.statusBar().showMessage(f"Stopped monitoring selected megathread categories.")
        logging.info(f"🏁 Finished stopping megathread categories: {', '.join(categories_to_stop)}")

    def on_megathreads_thread_selected(self, item):
        """Handle thread selection in Megathreads section and display its BBCode in the editor."""
        thread_title = item.text()
        # For now, we can mimic the same logic as posts if needed,
        # or leave it blank until we implement the mega-thread logic.
        self.megathreads_bbcode_editor.setPlainText(f"BBCode content for '{thread_title}' would be displayed here.")

    def update_process_threads_view(self, thread_id=None):
        """Display the saved URLs for a specific thread."""
        # If no thread_id provided, just return without doing anything
        if not thread_id:
            return
            
        if thread_id in self.bot.thread_links:
            thread_info = self.bot.thread_links[thread_id]

            # Build the HTML content for Keeplinks and Mega.nz URLs
            links_html = "<b>Keeplinks URLs:</b><br>"
            for keeplink in thread_info.get('keeplinks_urls', []):
                links_html += f"<a href='{keeplink}' target='_blank'>{keeplink}</a><br>"

            # Add Mega.nz URLs to the view
            links_html += "<br><b>Mega.nz URLs:</b><br>"
            for mega_url in thread_info.get('backup_urls', []):
                links_html += f"<a href='{mega_url}' target='_blank'>{mega_url}</a><br>"

            # Display the links in the QTextBrowser widget
            links_browser = QTextBrowser()
            links_browser.setHtml(links_html)
            links_browser.setOpenExternalLinks(True)

            # Set the content area to display the links
            self.content_area.setCurrentWidget(links_browser)
            logging.info(f"Displayed saved URLs for thread '{thread_id}'.")

        else:
            logging.error(f"Thread ID '{thread_id}' not found.")
            error_html = f"<b>Error:</b> Thread ID '{thread_id}' not found."
            links_browser = QTextBrowser()
            links_browser.setHtml(error_html)
            links_browser.setOpenExternalLinks(True)
            self.content_area.setCurrentWidget(links_browser)

    def init_download_progress(self):
        """Initialize the download progress bar."""
        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setValue(0)
        self.download_progress_bar.setVisible(False)  # Hide initially

    def create_progress_bar(self):
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(True)
        progress_bar.setAlignment(Qt.AlignCenter)
        progress_bar.setFixedHeight(20)

        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #9e9e9e;
                border-radius: 5px;
                text-align: center;
                color: black;
                background-color: #f5f5f5;
                height: 20px;
                margin: 2px;
                padding: 2px;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
                border-radius: 4px;
            }
        """)

        return progress_bar

    def init_login_section(self, parent_splitter):
        # Right Pane: Login Section
        login_widget = QWidget()
        login_layout = QVBoxLayout(login_widget)
        login_widget.setFixedWidth(300)  # Set width for the login section

        # Group Box for Login Information
        login_group = QGroupBox("Login")
        login_group_layout = QVBoxLayout(login_group)
        login_group_layout.addWidget(QLabel('Username:'))
        self.username_input = QLineEdit(self.config['username'])
        login_group_layout.addWidget(self.username_input)
        login_group_layout.addWidget(QLabel('Password:'))
        self.password_input = QLineEdit(self.config['password'])
        self.password_input.setEchoMode(QLineEdit.Password)
        login_group_layout.addWidget(self.password_input)
        self.login_button = QPushButton('Login')
        self.login_button.clicked.connect(self.handle_login)
        login_group_layout.addWidget(self.login_button)
        login_layout.addWidget(login_group)

        # Add Buttons for Thread Management Below Login Bar
        self.remove_thread_button = QPushButton('Remove Selected Thread(s)')
        self.remove_thread_button.clicked.connect(self.remove_selected_threads)
        login_layout.addWidget(self.remove_thread_button)

        self.remove_all_button = QPushButton('Remove All Threads')
        self.remove_all_button.clicked.connect(self.remove_all_threads)
        login_layout.addWidget(self.remove_all_button)



        # Add the Select WinRAR Executable Button
        self.select_winrar_exe_button = QPushButton('Select WinRAR Executable')
        self.select_winrar_exe_button.clicked.connect(self.select_winrar_executable)
        login_layout.addWidget(self.select_winrar_exe_button)

        # Display the Current WinRAR Executable Path
        self.winrar_exe_label = QLabel(
            f"WinRAR Executable: {self.config.get('winrar_exe_path', 'C:/Program Files/WinRAR/WinRAR.exe')}")
        login_layout.addWidget(self.winrar_exe_label)

        # Add stretch to push the buttons to the top
        login_layout.addStretch()

        # Add to Parent Splitter
        parent_splitter.addWidget(login_widget)

    def on_sidebar_item_clicked(self, item_text):
        """Handle modern sidebar item clicks"""
        # Map sidebar items to content area indices
        item_mapping = {
            "Posts": 0,
            "Backup": 1,
            "Process Threads": 2,
            "Megathreads": 3,
            "Settings": 4
        }
        
        if item_text in item_mapping:
            index = item_mapping[item_text]
            self.content_area.setCurrentIndex(index)
            
            # Update status bar
            self.statusBar().showMessage(f'📍 Navigated to {item_text} section')

    def init_posts_view(self):
        """Initialize the 'Posts' view with modern card-based layout"""
        # Create modern container
        posts_container = ModernContentContainer()
        
        # Create main posts card
        posts_card = ModernSectionCard("Posts Management", "📝")
        
        # Content widget for the card
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        # Upper Section: Horizontal splitter for Categories and Threads
        upper_splitter = QSplitter(Qt.Horizontal)
        content_layout.addWidget(upper_splitter)

        # Left Pane: Category Tree
        categories_widget = QWidget()
        categories_layout = QVBoxLayout(categories_widget)
        categories_label = QLabel("Categories")
        categories_label.setFont(QFont("Arial", 12, QFont.Bold))
        categories_layout.addWidget(categories_label)
        self.category_tree = QTreeView()
        self.category_model = QStandardItemModel()
        self.category_tree.setModel(self.category_model)
        self.category_tree.clicked.connect(self.on_category_clicked)
        self.category_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Allow multi-selection
        # Buttons replacing right-click menu for category actions
        category_controls_layout = QHBoxLayout()
        add_category_btn = QPushButton("Add Category")
        add_category_btn.clicked.connect(self.add_category)
        category_controls_layout.addWidget(add_category_btn)
        remove_category_btn = QPushButton("Remove Category(s)")
        remove_category_btn.clicked.connect(lambda: self.remove_categories(self.category_tree.selectedIndexes()))
        category_controls_layout.addWidget(remove_category_btn)
        track_once_btn = QPushButton("Track Once")
        track_once_btn.clicked.connect(lambda: self.start_monitoring(self.category_tree.selectedIndexes(), mode='Track Once'))
        category_controls_layout.addWidget(track_once_btn)
        keep_tracking_btn = QPushButton("Keep Tracking")
        keep_tracking_btn.clicked.connect(lambda: self.start_monitoring(self.category_tree.selectedIndexes(), mode='Keep Tracking'))
        category_controls_layout.addWidget(keep_tracking_btn)
        stop_tracking_btn = QPushButton("Stop Tracking")
        stop_tracking_btn.clicked.connect(lambda: self.stop_monitoring(self.category_tree.selectedIndexes()))
        category_controls_layout.addWidget(stop_tracking_btn)
        categories_layout.addLayout(category_controls_layout)
        categories_layout.addWidget(self.category_tree)
        upper_splitter.addWidget(categories_widget)

        # Middle Pane: Threads and Controls
        threads_widget = QWidget()
        threads_layout = QVBoxLayout(threads_widget)
        threads_label = QLabel("Threads")
        threads_label.setFont(QFont("Arial", 12, QFont.Bold))
        threads_layout.addWidget(threads_label)

        # Controls Layout (removed tracking inputs)

        # Thread List (QListWidget)
        self.thread_list = QListWidget()
        self.thread_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.thread_list.itemClicked.connect(self.on_thread_selected)
        thread_controls_layout = QHBoxLayout()
        fetch_button = QPushButton("Fetch")
        fetch_button.clicked.connect(lambda: self.fetch_thread_content(self.thread_list.currentItem()) if self.thread_list.currentItem() else None)
        thread_controls_layout.addWidget(fetch_button)
        view_links_button = QPushButton("View Links")
        view_links_button.clicked.connect(lambda: self.view_links(self.thread_list.currentItem().data(Qt.UserRole + 2)) if self.thread_list.currentItem() else None)
        thread_controls_layout.addWidget(view_links_button)
        threads_layout.addLayout(thread_controls_layout)
        threads_layout.addWidget(QLabel("Extracted Threads"))
        threads_layout.addWidget(self.thread_list)

        upper_splitter.addWidget(threads_widget)

        # Set Stretch Factors for Upper Splitter
        upper_splitter.setStretchFactor(0, 1)  # Categories
        upper_splitter.setStretchFactor(1, 3)  # Threads

        # Lower Section: BBCode Editor
        bbcode_editor_group = QGroupBox("BBCode Editor")
        bbcode_layout = QVBoxLayout(bbcode_editor_group)
        self.bbcode_editor = QTextEdit()
        bbcode_layout.addWidget(self.bbcode_editor)
        content_layout.addWidget(bbcode_editor_group)

        # Add content to card and container
        posts_card.add_widget(content_widget) 
        posts_container.add_card(posts_card)
        
        # Add container to content_area
        self.content_area.addWidget(posts_container)

    def init_log_viewer(self):
        """Initialize a log viewer within the GUI."""
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)

        log_label = QLabel("Log Output")
        log_label.setFont(QFont("Arial", 12, QFont.Bold))
        log_layout.addWidget(log_label)

        self.log_viewer = QTextBrowser()
        self.log_viewer.setReadOnly(True)
        log_layout.addWidget(self.log_viewer)

        # Load existing log file content
        self.load_log_file()

        # Add the log viewer to the content area as a new tab or section
        self.content_area.addWidget(log_widget)

        # Optionally, set up a timer to refresh the log viewer periodically
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.load_log_file)
        self.log_timer.start(5000)  # Refresh every 5 seconds

    def load_log_file(self):
        log_path = os.path.join(DATA_DIR, 'forum_bot.log')
        if not os.path.exists(log_path):
            # If the log file hasn't been created yet, silently skip loading it
            # rather than spamming the user's log with warnings.
            return

        try:
            with open(log_path, 'r') as log_file:
                content = log_file.read()
                # هنا ضَع الكود الأصلي الذي يعرض المحتوى في الواجهة
                # مثال:
                # self.log_text_edit.setPlainText(content)
        except Exception as e:
            logging.error("Exception in load_log_file: %s", e, exc_info=True)

    def on_thread_selected(self, item):
        """Handle thread selection and display its BBCode in the editor."""
        thread_title = item.text()
        thread_url = item.data(Qt.UserRole)
        thread_id = item.data(Qt.UserRole + 1)
        category_name = self.current_category

        logging.debug(f"Thread selected: {thread_title}, URL: {thread_url}")

        # Retrieve BBCode from process_threads
        thread_info = self.process_threads.get(category_name, {}).get(thread_title, {})
        bbcode_content = thread_info.get('bbcode_content')

        if bbcode_content:
            # Display the saved BBCode directly
            self.bbcode_editor.setPlainText(bbcode_content)
            logging.info(f"Displayed saved BBCode for thread '{thread_title}'.")
        else:
            if thread_url:
                # Fetch and display the thread content, then save BBCode
                self.load_thread_content(thread_title, thread_url)
            else:
                QMessageBox.warning(self, "Invalid Thread", "Thread URL is missing.")
                logging.warning(f"Thread URL missing for '{thread_title}'.")

    def find_backup_thread_row(self, thread_title):
        for r in range(self.backup_threads_table.rowCount()):
            t_title = self.backup_threads_table.item(r, 0).text()
            if t_title == thread_title:
                return r
        return -1

    def reupload_thread_files(self, thread_title, thread_info):
        """Re-upload using Rapidgator backup links instead of Mega.nz."""
        try:
            logging.info(f"Re-uploading files for thread '{thread_title}'")

            # Retrieve Rapidgator backup links
            backup_links = thread_info.get('rapidgator_backup_links', [])
            flat = []
            for l in backup_links:
                if isinstance(l, (list, tuple)):
                    flat.extend(l)
                else:
                    flat.append(l)
            backup_links = [link.strip() for link in flat if link and str(link).strip()]

            if not backup_links:
                logging.error(f"No Rapidgator backup links found for thread '{thread_title}'.")
                QMessageBox.warning(self, "No Backup", "No Rapidgator backup links found.")

                return
            tid = str(thread_info.get('thread_id', ''))
            if not tid:
                logging.error("No thread_id found in thread_info. Cannot determine download directory.")
                QMessageBox.warning(self, "Missing Data", "No thread ID found in backup data.")
                return

            # Store state for multi-link download
            self._reupload_state = {
                'thread_title': thread_title,
                'thread_info': thread_info,
                'thread_id': tid,
                'rg_links': backup_links,
                'current_index': 0,
                'downloaded_files': []
            }

            # Start downloading the first Rapidgator backup link
            self._download_next_rg_link()

        except Exception as e:
            logging.error(f"Error re-uploading files for thread '{thread_title}': {e}", exc_info=True)
            QMessageBox.warning(self, "Re-upload Error", f"An error occurred while re-uploading files: {e}")

    def _download_next_rg_link(self):
        if not hasattr(self, '_reupload_state'):
            return

        state = self._reupload_state
        rg_links = state['rg_links']
        current_index = state['current_index']

        if current_index < len(rg_links):
            rg_link = rg_links[current_index]
            thread_id = state['thread_id']

            logging.info(f"Downloading RG backup link {current_index + 1}/{len(rg_links)}: {rg_link}")

            # NEW: Derive the correct local folder from .env-based download_dir
            # For instance, a "BackupReupload" subfolder + thread_id:
            download_folder = os.path.join(self.bot.download_dir, "BackupReupload", str(thread_id))
            os.makedirs(download_folder, exist_ok=True)

            result = self.bot.download_rapidgator_net(
                rg_link,
                "BackupReupload",
                thread_id,
                state['thread_title'],
                download_dir=download_folder
            )
            if result:
                state['downloaded_files'].append(result)
            else:
                logging.warning(
                    f"Failed to download RG link {current_index + 1}/{len(rg_links)}: {rg_link}"
                )
            state['current_index'] += 1
            self._download_next_rg_link()

        else:
            # All links attempted
            self._start_reupload_process()

    def on_reupload_host_progress(self, row, host_idx, progress, status_msg, current_size, total_size):
        try:
            if hasattr(self, 'backup_upload_progress_dialog') and self.backup_upload_progress_dialog:
                host_name = self.get_host_name(host_idx)
                if host_name:
                    self.backup_upload_progress_dialog.update_host_progress(
                        host=host_name,
                        progress=progress,
                        status_msg=status_msg,
                        current_size=current_size,
                        total_size=total_size
                    )
        except Exception as e:
            logging.error(f"Error updating backup host progress: {str(e)}", exc_info=True)

    def _start_reupload_process(self):
        state = self._reupload_state
        thread_title = state['thread_title']
        thread_info = state['thread_info']
        downloaded_files = state['downloaded_files']

        del self._reupload_state  # cleanup

        if not downloaded_files:
            QMessageBox.warning(self, "Download Failed", "Failed to download files from Rapidgator backup links.")
            return

        # For re-upload, pick whichever folder you want—maybe the folder you used above.
        # If you want a single 'main_file' approach, that’s fine. But ensure you re-derive from .env
        main_file = downloaded_files[0]
        logging.info(f"Proceeding with re-upload using the first downloaded file: {main_file}")

        row = self.find_backup_thread_row(thread_title)
        if row == -1:
            logging.error(f"Thread '{thread_title}' not found in backup_threads_table after download.")
            QMessageBox.warning(self, "Not Found", "Thread not found in backup table.")
            return

        # Close any previously opened backup upload dialog
        if hasattr(self, 'backup_upload_progress_dialog') and self.backup_upload_progress_dialog:
            self.backup_upload_progress_dialog.close()
            self.backup_upload_progress_dialog = None

        # Import dialog from the gui package to ensure the module can be found
        # when running the application from the project root
        from gui.backup_upload_progress_dialog import BackupUploadProgressDialog
        self.backup_upload_progress_dialog = BackupUploadProgressDialog(parent=self)
        self.backup_upload_progress_dialog.show()
        self.backup_upload_progress_dialog.raise_()
        self.backup_upload_progress_dialog.activateWindow()

        thread_id = thread_info.get('thread_id', '')


        # ***INSTEAD OF USING os.path.dirname(main_file)***
        # we rely on the same folder we used for the MegaDownloadWorker:
        # e.g. 'download_folder = os.path.join(self.bot.download_dir, "BackupReupload", str(thread_id))'
        # so that all the downloaded files are definitely there.
        reupload_folder = os.path.join(self.bot.download_dir, "BackupReupload", str(thread_id))
        os.makedirs(reupload_folder, exist_ok=True)

        moved_files = []
        for fpath in downloaded_files:
            dest = os.path.join(reupload_folder, os.path.basename(fpath))
            if os.path.abspath(fpath) != os.path.abspath(dest):
                shutil.move(fpath, dest)
            moved_files.append(dest)

            # Process the downloaded files the same way as regular downloads
        processed_files = self.file_processor.process_downloads(
            Path(reupload_folder), moved_files, thread_title
        )
        if not processed_files:
            QMessageBox.warning(self, "Processing Failed", "Failed to process downloaded files.")
            return

        # Upload only to main hosts (exclude backup RG account)
        hosts = [h for h in self.active_upload_hosts if h != 'rapidgator-backup']
        if not hosts:
            hosts = [h for h in self.active_upload_hosts if h]

        self.current_upload_worker = UploadWorker(
            bot=self.bot,
            row=row,
            folder_path=reupload_folder,
            thread_id=thread_id,
            upload_hosts=hosts,
        )

        self.current_upload_worker.upload_complete.connect(
            lambda r, urls: self.on_reupload_upload_complete(thread_title, thread_info, r, urls)
        )
        self.current_upload_worker.host_progress.connect(
            lambda r, host_idx, prog, status, cur, tot: self.on_reupload_host_progress(r, host_idx, prog, status, cur,
                                                                                       tot)
        )

        self.current_upload_worker.start()

    def on_reupload_upload_complete(self, thread_title, thread_info, row, urls_dict):
        try:
            # 1) Preserve old Keeplinks if not overridden
            old_keeplinks = thread_info.get('keeplinks_link', '')

            # 2) Extract newly uploaded links
            rapidgator_links = urls_dict.get('rapidgator', [])
            backup_rg_urls = urls_dict.get('rapidgator-backup', [])
            if isinstance(backup_rg_urls, str):
                backup_rg_urls = [backup_rg_urls]
            nitroflare_links = urls_dict.get('nitroflare', [])
            ddownload_links = urls_dict.get('ddownload', [])
            katfile_links = urls_dict.get('katfile', [])
            mega_links = urls_dict.get('mega', [])

            # Combined new links
            new_links = rapidgator_links + nitroflare_links + ddownload_links + katfile_links + mega_links

            # If we already had a Keeplinks link for this thread:
            keeplinks_url = urls_dict.get('keeplinks', '') or old_keeplinks
            # So if 'urls_dict' does NOT provide a new keeplinks, we keep the old one.

            if not keeplinks_url:
                QMessageBox.warning(self, "No Keeplinks URL", f"No Keeplinks link found for '{thread_title}'.")
                # Close progress dialog, etc. ...
                return

            # Next: actually update Keeplinks link if you want with the new links
            updated_link = self.bot.update_keeplinks_links(keeplinks_url, new_links)
            if not updated_link:
                QMessageBox.warning(self, "Update Failed", "Could not update Keeplinks link with new links.")
                return
            keeplinks_url = updated_link
            # If success, store them in backup data
            thread_info['keeplinks_link'] = keeplinks_url  # final Keeplinks
            thread_info['rapidgator_links'] = rapidgator_links
            if backup_rg_urls:
                thread_info['rapidgator_backup_links'] = list(backup_rg_urls)
            thread_info['dead_rapidgator_links'] = []  # reset dead links
            # If new mega links were provided, keep them
            if mega_links:
                thread_info['mega_link'] = "\n".join(mega_links)
                thread_info['mega_links'] = mega_links

            self.backup_threads[thread_title] = thread_info
            self.save_backup_threads_data()
            self.populate_backup_threads_table()

            # close the progress dialog if any
            if hasattr(self, 'backup_upload_progress_dialog') and self.backup_upload_progress_dialog:
                self.backup_upload_progress_dialog.close()
                self.backup_upload_progress_dialog = None

            QMessageBox.information(self, "Re-upload Successful",
                                    f"Files re-uploaded and Keeplinks link updated for '{thread_title}'.")
        except Exception as e:
            logging.error(f"Error in on_reupload_upload_complete: {e}", exc_info=True)
            QMessageBox.warning(self, "Error", f"An unexpected error occurred: {e}")
            if hasattr(self, 'backup_upload_progress_dialog') and self.backup_upload_progress_dialog:
                self.backup_upload_progress_dialog.close()
                self.backup_upload_progress_dialog = None

    def reupload_dead_rapidgator_links(self):
        indexes = self.backup_threads_table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a thread to re-upload.")
            return

        row = indexes[0].row()
        thread_title_item = self.backup_threads_table.item(row, 0)
        if not thread_title_item:
            QMessageBox.warning(self, "Error", "Could not retrieve thread title.")
            return

        thread_title = thread_title_item.text()
        thread_info = self.backup_threads.get(thread_title)
        if not thread_info:
            logging.error(f"No backup information found for thread '{thread_title}'.")
            QMessageBox.warning(self, "Error", f"No backup information found for thread '{thread_title}'.")
            return

        dead_links = thread_info.get('dead_rapidgator_links', [])
        if not dead_links:
            QMessageBox.information(self, "No Dead Links", "No dead Rapidgator links to re-upload.")
            return

        reply = QMessageBox.question(
            self, "Re-upload Confirmation",
            f"Do you want to re-upload {len(dead_links)} dead Rapidgator link(s) for '{thread_title}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.reupload_thread_files(thread_title, thread_info)

    def init_backup_view(self) -> None:
        """إنشاء تبويب النسخ الاحتياطى (Backup)."""

        # === الحاوية الرئيسية ==================================================
        backup_widget = QWidget()
        backup_layout = QVBoxLayout(backup_widget)
        backup_layout.setContentsMargins(6, 6, 6, 6)
        backup_layout.setSpacing(10)

        # عنوان القسم
        title_lbl = QLabel("Backup")
        title_lbl.setFont(QFont("Arial", 12, QFont.Bold))
        backup_layout.addWidget(title_lbl)

        # === جدول المواضيع المحتفَظ بها ========================================
        self.backup_threads_table = QTableWidget()
        self.backup_threads_table.setColumnCount(5)
        self.backup_threads_table.setHorizontalHeaderLabels(
            [
                "Thread Title",
                "Thread ID",
                "RG Links",
                "RG-Backup",
                "Keeplinks",
            ]
        )

        # سلوك اختيار الصفوف
        self.backup_threads_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.backup_threads_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.backup_threads_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.backup_threads_table.setAlternatingRowColors(True)
        self.backup_threads_table.setWordWrap(True)
        self.backup_threads_table.setShowGrid(True)
        # Apply custom delegate for per-link coloring
        self.backup_status_delegate = LinkStatusDelegate(self.backup_threads_table)
        self.backup_threads_table.setItemDelegate(self.backup_status_delegate)


        # ألوان مميّزة للـ selection (تعمل فى Light و Dark)
        self.backup_threads_table.setStyleSheet(
            "QTableWidget { gridline-color:#d0d0d0; }"
            "QTableWidget::item:selected { background:#4a90e2; color:white; }"
        )

        # هيدر الأعمدة
        header = self.backup_threads_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.backup_threads_table.verticalHeader().hide()
        self.backup_threads_table.setSortingEnabled(True)

        # أعمدة أطول قليلاً للروابط
        self.backup_threads_table.setColumnWidth(2, 220)
        self.backup_threads_table.setColumnWidth(4, 220)

        # اربط حدث "اختيار صف" لتحديث القائمة
        self.backup_threads_table.itemSelectionChanged.connect(
            self.on_backup_selection_changed
        )

        # قائمة ستُحدَّث تلقائيًا
        self.selected_backup_threads: list[str] = []

        backup_layout.addWidget(self.backup_threads_table)
        self.content_area.addWidget(backup_widget)

        # === أزرار الإجراءات ===================================================
        btn_row = QHBoxLayout()

        self.check_single_thread_button = QPushButton("Check RG Links (Selected)")
        self.check_all_threads_button = QPushButton("Check RG Links (All)")
        self.set_timer_button = QPushButton("Auto Check Interval")
        self.reupload_button = QPushButton("Re‑upload Dead Links")

        for b in (
                self.check_single_thread_button,
                self.check_all_threads_button,
                self.set_timer_button,
                self.reupload_button,
        ):
            btn_row.addWidget(b)

        backup_layout.addLayout(btn_row)

        # اربط الأزرار بالمعالجات
        self.check_single_thread_button.clicked.connect(self.on_check_rapidgator_clicked)
        self.check_all_threads_button.clicked.connect(self.check_rapidgator_links_for_all_threads)
        self.set_timer_button.clicked.connect(self.set_automatic_check_interval)
        self.reupload_button.clicked.connect(self.reupload_dead_rapidgator_links)

    def check_rapidgator_links_for_selected_thread(self):
        """
        Check Rapidgator links for the selected thread and update dead links and status in backup_threads,
        but skip repeated pop-ups if the Rapidgator token is missing.
        """
        selected_items = self.backup_threads_table.selectedItems()
        if not selected_items:
            logging.error("No thread selected for Rapidgator link checking.")
            QMessageBox.warning(self, "No Selection", "Please select a thread to check Rapidgator links.")
            return

        # Ensure a Rapidgator token is available
        if not (self.bot.upload_rapidgator_token or self.bot.rapidgator_token):
            # Try loading from disk or performing API login
            loaded = self.bot.load_token('main') or self.bot.load_token('backup')
            if not loaded and not (self.bot.api_login('main') or self.bot.api_login('backup')):
                logging.warning(
                    "No Rapidgator API token found; skipping link checks for selected thread."
                )
                return

        selected_row = selected_items[0].row()
        thread_id = self.backup_threads_table.item(selected_row, 1).text()
        thread_title = self.backup_threads_table.item(selected_row, 0).text()
        rapidgator_cell_item = self.backup_threads_table.item(selected_row, 2)
        if not rapidgator_cell_item:
            logging.error("Rapidgator cell not found for the selected thread.")
            return

        rapidgator_links = rapidgator_cell_item.text().split("\n")

        if not rapidgator_links or all(link.strip() == '' for link in rapidgator_links):
            logging.error(f"No Rapidgator links found for thread {thread_id}.")
            # If no links, mark status = 'none'
            thread_info = self.backup_threads.get(thread_title, {})
            thread_info['rapidgator_status'] = 'none'
            rapidgator_cell_item.setBackground(QColor(255, 255, 255))
            rapidgator_cell_item.setData(Qt.UserRole, None)
            self.backup_threads[thread_title] = thread_info
            self.save_backup_threads_data()
            return

        thread_info = self.backup_threads.get(thread_title, {})
        if 'dead_rapidgator_links' not in thread_info:
            thread_info['dead_rapidgator_links'] = []
        # Clear existing dead links before re-check
        thread_info['dead_rapidgator_links'].clear()

        dead_found = False
        for link in rapidgator_links:
            link = link.strip()
            if not link:
                continue
            response = self.bot.check_rapidgator_link_status(link)
            if not (response and response.get('status') == "ACCESS"):
                thread_info['dead_rapidgator_links'].append(link)
                dead_found = True

        # Mark table cell color based on result
        if dead_found:
            self.set_backup_link_status_color(rapidgator_cell_item, False)
            thread_info['rapidgator_status'] = 'dead'
        else:
            self.set_backup_link_status_color(rapidgator_cell_item, True)
            thread_info['rapidgator_status'] = 'alive'

        self.backup_threads[thread_title] = thread_info
        self.save_backup_threads_data()
        QApplication.processEvents()
        logging.info(f"Link status updated for thread {thread_id} (dead_found={dead_found}).")

    def check_rapidgator_links(self, thread_id=None):
        """
        Check if Rapidgator links are still active.
        If ``thread_id`` is provided, only check links for that thread.
        Updates ``dead_rapidgator_links`` and ``rapidgator_status``.
        """
        # Ensure a Rapidgator token is available for link checks
        if not (self.bot.upload_rapidgator_token or self.bot.rapidgator_token):
            loaded = self.bot.load_token('main') or self.bot.load_token('backup')
            if not loaded and not (self.bot.api_login('main') or self.bot.api_login('backup')):
                logging.warning("No Rapidgator API token found. Skipping check_rapidgator_links().")
                return

        if thread_id:
            threads_to_check = {
                title: info
                for title, info in self.backup_threads.items()
                if info.get("thread_id") == thread_id
            }
            if not threads_to_check:
                logging.error(f"No backup info found for thread ID '{thread_id}'.")
                return
        else:
            threads_to_check = self.backup_threads

        for title, thread_info in threads_to_check.items():
            if not thread_info:
                logging.error(f"No backup info found for thread '{title}'.")
                continue

            rapidgator_links = thread_info.get('rapidgator_links', [])
            thread_info['dead_rapidgator_links'] = []
            dead_found = False

            for link in rapidgator_links:
                link = link.strip()
                if not link:
                    continue
                is_alive = self.is_link_active(link)  # <--- uses updated is_link_active below
                if not is_alive:
                    logging.warning(f"Rapidgator link is dead: {link}")
                    thread_info['dead_rapidgator_links'].append(link)
                    dead_found = True
                else:
                    logging.info(f"Rapidgator link is alive: {link}")

            if dead_found:
                thread_info['rapidgator_status'] = 'dead'
            else:
                if rapidgator_links:
                    thread_info['rapidgator_status'] = 'alive'
                else:
                    thread_info['rapidgator_status'] = 'none'

            self.backup_threads[title] = thread_info
            # Update the table cell color to reflect new status
            rows = self.backup_threads_table.rowCount()
            for row in range(rows):
                t_title_item = self.backup_threads_table.item(row, 0)
                if t_title_item and t_title_item.text() == title:
                    rapidgator_cell_item = self.backup_threads_table.item(row, 2)
                    if rapidgator_cell_item:
                        if thread_info['rapidgator_status'] == 'dead':
                            self.set_backup_link_status_color(rapidgator_cell_item, False)
                        elif thread_info['rapidgator_status'] == 'alive':
                            self.set_backup_link_status_color(rapidgator_cell_item, True)
                        else:
                            rapidgator_cell_item.setBackground(QColor(255, 255, 255))
                            rapidgator_cell_item.setData(Qt.UserRole, None)
                    break

        self.save_backup_threads_data()
        QApplication.processEvents()
        logging.info("Completed check_rapidgator_links() run.")

    def toggle_upload_host(self, host, state):
        """Toggle a single upload host on/off."""
        enabled = bool(state)
        if enabled and host not in self.active_upload_hosts:
            self.active_upload_hosts.append(host)
        elif not enabled and host in self.active_upload_hosts:
            self.active_upload_hosts.remove(host)

        # حدّث الكنفج و.env
        self.config['upload_hosts'] = self.active_upload_hosts
        dotenv_path = find_dotenv()
        if dotenv_path:
            set_key(dotenv_path, 'UPLOAD_HOSTS', ','.join(self.active_upload_hosts))

        logging.info(f"Active upload hosts: {self.active_upload_hosts}")

    def check_rapidgator_links_for_all_threads(self):
        """
        Check Rapidgator links for ALL threads in backup_threads_table,
        but avoid repeated pop-ups if the Rapidgator token is missing.
        """
        # Ensure a Rapidgator token is available for link checks
        if not (self.bot.upload_rapidgator_token or self.bot.rapidgator_token):
            loaded = self.bot.load_token('main') or self.bot.load_token('backup')
            if not loaded and not (self.bot.api_login('main') or self.bot.api_login('backup')):
                logging.warning("No Rapidgator API token found; skipping Rapidgator link checks for ALL threads.")
                return

        for row in range(self.backup_threads_table.rowCount()):
            thread_title_item = self.backup_threads_table.item(row, 0)
            if not thread_title_item:
                continue

            thread_title = thread_title_item.text()
            rapidgator_cell_item = self.backup_threads_table.item(row, 2)
            if not rapidgator_cell_item:
                continue

            rapidgator_links = [link.strip() for link in rapidgator_cell_item.text().split("\n") if link.strip()]
            thread_info = self.backup_threads.get(thread_title, {})
            thread_info['dead_rapidgator_links'] = []
            dead_found = False

            for link in rapidgator_links:
                response = self.bot.check_rapidgator_link_status(link)
                if not (response and response.get('status') == "ACCESS"):
                    thread_info['dead_rapidgator_links'].append(link)
                    dead_found = True

            if dead_found:
                self.set_backup_link_status_color(rapidgator_cell_item, False)
                thread_info['rapidgator_status'] = 'dead'
            else:
                if rapidgator_links:
                    self.set_backup_link_status_color(rapidgator_cell_item, True)
                    thread_info['rapidgator_status'] = 'alive'
                else:
                    # no links
                    rapidgator_cell_item.setBackground(QColor(255, 255, 255))
                    rapidgator_cell_item.setData(Qt.UserRole, None)
                    thread_info['rapidgator_status'] = 'none'

            self.backup_threads[thread_title] = thread_info
            logging.info(f"Checked Rapidgator links for '{thread_title}' (dead_found={dead_found}).")

        self.save_backup_threads_data()
        QApplication.processEvents()
        logging.info("Finished checking Rapidgator links for all threads.")

    def set_automatic_check_interval(self):
        interval, ok = QInputDialog.getInt(self, "Set Interval", "Enter interval in minutes:", min=1)
        if ok:
            self.check_interval_minutes = interval
            # Set up a QTimer
            if hasattr(self, 'check_timer'):
                self.check_timer.stop()
            self.check_timer = QTimer(self)
            self.check_timer.timeout.connect(self.check_rapidgator_links_for_all_threads)
            self.check_timer.start(self.check_interval_minutes * 60 * 1000)  # Convert minutes to milliseconds
            logging.info(f"Automatic Rapidgator link checking set to every {self.check_interval_minutes} minutes.")



    def select_winrar_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select WinRAR Directory")
        if directory:
            # Update the bot's WinRAR directory
            self.bot.winrar_dir = directory
            # Update the configuration
            self.config['winrar_dir'] = directory
            # Save the configuration to the .env file
            dotenv_path = find_dotenv()
            if dotenv_path:
                set_key(dotenv_path, 'WINRAR_DIR', directory)
                logging.info("WinRAR directory saved to .env file.")
            else:
                logging.warning("No .env file found. WinRAR directory not saved to .env file.")
            # Update the label in the GUI
            self.winrar_dir_label.setText(f"WinRAR Directory: {directory}")
            # Provide feedback to the user
            QMessageBox.information(self, "WinRAR Directory Selected", f"WinRAR directory set to:\n{directory}")
            logging.info(f"WinRAR directory set to: {directory}")

    def select_winrar_executable(self):
        exe_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select WinRAR Executable",
            "C:/Program Files/WinRAR/",
            "Executable Files (*.exe)"
        )
        if exe_path:
            # Verify that the selected file is WinRAR.exe
            if os.path.basename(exe_path).lower() != 'winrar.exe':
                QMessageBox.warning(self, "Invalid Selection", "Please select the 'WinRAR.exe' file.")
                logging.warning(f"User selected an invalid WinRAR executable: {exe_path}")
                return

            # Update the bot's WinRAR executable path
            self.bot.winrar_exe_path = exe_path
            # Update the configuration
            self.config['winrar_exe_path'] = exe_path
            # Save the configuration to the .env file
            dotenv_path = find_dotenv()
            if dotenv_path:
                set_key(dotenv_path, 'WINRAR_EXE_PATH', exe_path)
                logging.info("WinRAR executable path saved to .env file.")
            else:
                logging.warning("No .env file found. WinRAR executable path not saved to .env file.")
            # Update the label in the GUI
            self.winrar_exe_label.setText(f"WinRAR Executable: {exe_path}")
            # Provide feedback to the user
            QMessageBox.information(self, "WinRAR Executable Selected", f"WinRAR executable set to:\n{exe_path}")
            logging.info(f"WinRAR executable set to: {exe_path}")

    def save_configuration(self):
        """Save configuration changes to the .env file."""
        try:
            dotenv_path = find_dotenv()
            if not dotenv_path:
                QMessageBox.critical(self, "Error", "No .env file found.")
                return
            # Update the .env file with the new download directory
            set_key(dotenv_path, 'DOWNLOAD_DIR', self.config['download_dir'])
            logging.info("Configuration saved to .env file.")
        except Exception as e:
            logging.error(f"Error saving configuration: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")

    def on_thread_double_click(self, item):
        try:
            row = item.row()
            # URL was stored under Qt.UserRole+2, not Qt.UserRole
            thread_url = self.process_threads_table.item(row, 0).data(Qt.UserRole + 2)
            if not thread_url:
                QMessageBox.warning(self, "URL Missing", "No main thread URL found for this entry.")
                logging.warning("No main thread URL found for the selected process thread.")
                return

            # Ensure URL has a scheme
            if not thread_url.lower().startswith(("http://", "https://")):
                thread_url = "http://" + thread_url

            # Safely attempt to open in Chrome driver
            if not self.bot or not self.bot.driver:
                QMessageBox.warning(self, "Driver Error", "WebDriver is not available.")
                return

            logging.info(f"Attempting to open main thread URL in Chrome driver: {thread_url}")
            self.bot.driver.get(thread_url)
            logging.info(f"Opened main thread URL in Chrome driver: {thread_url}")

        except Exception as e:
            logging.error(f"Error opening thread URL in WebDriver: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to open thread: {e}")

    def handle_logout(self):
        """Handle user logout and clear session data"""
        try:
            # Clear current user session in UserManager
            current_user = self.user_manager.get_current_user()
            if current_user:
                logging.info(f"🚪 User '{current_user}' logging out")
                self.user_manager.clear_current_user()
            
            # Clear bot session
            if self.bot:
                self.bot.logout()
            
            # Reset login controls
            self.login_button.setEnabled(True)
            self.username_input.setEnabled(True)
            self.password_input.setEnabled(True)
            self.username_input.clear()
            self.password_input.clear()
            
            # Clear UI data
            self.category_model.clear()
            self.megathreads_category_model.clear()
            self.thread_list.clear()
            self.megathreads_tree.clear()
            self.bbcode_editor.clear()
            self.megathreads_bbcode_editor.clear()
            
            # CRITICAL: Save all user data before clearing it
            logging.info("💾 Saving user data before logout...")
            try:
                self.save_process_threads_data()
                self.save_backup_threads_data()
                self.save_replied_thread_ids()
                if hasattr(self, 'megathreads_process_threads') and self.megathreads_process_threads:
                    self.save_megathreads_process_threads_data()
                if hasattr(self, 'bot') and self.bot:
                    self.bot.save_processed_thread_ids()
                logging.info("✅ User data saved successfully before logout")
            except Exception as save_error:
                logging.error(f"❌ Error saving user data before logout: {save_error}", exc_info=True)
            
            # Clear all user-specific data comprehensively
            self.clear_user_data_on_logout()
            
            # Reset config username for backward compatibility
            self.config['username'] = ''
            
            # Update bot file paths back to global folders
            if hasattr(self, 'bot') and self.bot:
                self.bot.update_user_file_paths()
            
            # Refresh settings widget to clear user-specific settings
            if hasattr(self, 'settings_widget'):
                self.settings_widget.reset_settings()
            
            # Reload user-specific data (will load default/empty data when no user logged in)
            self.reload_user_specific_data()
            
            # Update status
            self.statusBar().showMessage('Logged out successfully. Please log in.')
            logging.info("✅ Logout completed successfully")
            
        except Exception as e:
            logging.error(f"Error during logout: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Logout Error", f"Error during logout: {str(e)}")

    def setup_shortcuts(self):
        # Existing shortcuts
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_data)
        QShortcut(QKeySequence("Ctrl+R"), self, self.refresh_categories)
        QShortcut(QKeySequence("Ctrl+L"), self, self.handle_logout)
        QShortcut(QKeySequence("Delete"), self, self.remove_selected_threads)
        QShortcut(QKeySequence("Ctrl+A"), self, self.select_all_threads)
        QShortcut(QKeySequence("Ctrl+C"), self, self.copy_selected_threads)
        QShortcut(QKeySequence("Ctrl+V"), self, self.paste_threads)

        # **New Shortcuts for Process Threads**
        QShortcut(QKeySequence("Ctrl+D"), self, self.start_download_operation)
        QShortcut(QKeySequence("Ctrl+U"), self, self.upload_selected_process_threads)

    def show_category_context_menu(self, position):
        """Show context menu for category tree."""
        indexes = self.category_tree.selectedIndexes()
        if not indexes:
            return

        menu = QMenu()
        add_category_action = menu.addAction("Add Category")
        remove_category_action = menu.addAction("Remove Category(s)")
        track_once_action = menu.addAction("Track Once")
        keep_tracking_action = menu.addAction("Keep Tracking")
        stop_tracking_action = menu.addAction("Stop Tracking")
        action = menu.exec_(self.category_tree.viewport().mapToGlobal(position))

        if action == add_category_action:
            self.add_category()
        elif action == remove_category_action:
            self.remove_categories(indexes)
        elif action == track_once_action:
            self.start_monitoring(indexes, mode='Track Once')
        elif action == keep_tracking_action:
            self.start_monitoring(indexes, mode='Keep Tracking')
        elif action == stop_tracking_action:
            self.stop_monitoring(indexes)

    def show_megathreads_category_context_menu(self, position):
        """Show context menu for megathreads category tree."""
        indexes = self.megathreads_category_tree.selectedIndexes()
        menu = QMenu()

        # Add these two actions specifically for the Megathread category tree
        add_mega_category_action = menu.addAction("Add Megathread Category")
        remove_mega_category_action = menu.addAction("Remove Megathread Category(s)")

        action = menu.exec_(self.megathreads_category_tree.viewport().mapToGlobal(position))

        if action == add_mega_category_action:
            self.add_megathread_category()  # Make sure add_megathread_category method is defined
        elif action == remove_mega_category_action:
            self.remove_megathread_categories(indexes)  # Make sure remove_megathread_categories method is defined

    def add_megathread_category(self):
        text, ok = QInputDialog.getText(self, 'Add Megathread Category', 'Enter megathread category name:')
        if ok and text:
            url, ok_url = QInputDialog.getText(self, 'Add Megathread Category', 'Enter megathread category URL:')
            if ok_url and url:
                success = self.megathreads_category_manager.add_category(text, url)
                if success:
                    QMessageBox.information(self, "Category Added", f"Megathread Category '{text}' added successfully.")
                    # After adding, repopulate the megathreads category tree
                    self.populate_megathreads_category_tree()
                else:
                    QMessageBox.warning(self, "Already Exists", f"Megathread Category '{text}' already exists.")
            else:
                QMessageBox.warning(self, "Invalid URL", "Megathread category URL cannot be empty.")
        else:
            QMessageBox.warning(self, "Invalid Name", "Megathread category name cannot be empty.")

    def remove_megathread_categories(self, indexes):
        categories_to_remove = [self.megathreads_category_model.itemFromIndex(index).text() for index in indexes]
        reply = QMessageBox.question(
            self, 'Remove Megathread Categories',
            f"Are you sure you want to remove the selected megathread category(ies): {', '.join(categories_to_remove)}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for category_name in categories_to_remove:
                self.megathreads_category_manager.remove_category(category_name)
            # After removal, repopulate the megathreads category tree
            self.populate_megathreads_category_tree()
            self.statusBar().showMessage(f"Selected megathread categories removed.")

    def show_thread_context_menu(self, position):
        """Show context menu for thread list."""
        thread_list_widget = self.thread_list
        item = thread_list_widget.itemAt(position)
        if not item:
            return

        menu = QMenu()
        fetch_action = menu.addAction("Fetch")
        view_links_action = menu.addAction("View Links")
        action = menu.exec_(thread_list_widget.viewport().mapToGlobal(position))

        if action == fetch_action:
            self.fetch_thread_content(item)
        elif action == view_links_action:
            thread_title = item.data(Qt.UserRole + 2)  # Retrieve actual thread_title
            self.view_links(thread_title)

    def retry_operation(self, operation, retries=3, delay=5):
        """
        Attempts to execute the given operation multiple times with delays between retries.

        Parameters:
        - operation (callable): The function to execute.
        - retries (int): Number of retry attempts.
        - delay (int): Delay in seconds between retries.

        Returns:
        - The result of the operation if successful.

        Raises:
        - Exception: The exception from the last failed attempt if all retries fail.
        """
        for attempt in range(1, retries + 1):
            try:
                result = operation()
                logging.info(f"Operation succeeded on attempt {attempt}.")
                return result
            except Exception as e:
                logging.warning(f"Attempt {attempt} failed: {e}")
                if attempt < retries:
                    logging.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logging.error(f"All {retries} attempts failed.")
                    raise

    def handle_login(self):
        """Enhanced login handler using threads"""
        # Disable login controls
        self.login_button.setEnabled(False)
        self.username_input.setEnabled(False)
        self.password_input.setEnabled(False)

        # Create and setup login thread
        self.login_thread = LoginThread(
            self.bot,
            self.username_input.text(),
            self.password_input.text()
        )

        # Connect signals
        self.login_thread.login_success.connect(self.on_login_success)
        self.login_thread.login_failed.connect(self.on_login_failed)
        self.login_thread.login_status.connect(self.statusBar().showMessage)

        # Start login process
        self.login_thread.start()

    def on_login_success(self):
        """Handle successful login"""
        # Keep login controls disabled
        self.login_button.setEnabled(False)
        self.username_input.setEnabled(False)
        self.password_input.setEnabled(False)

        # Set current user in UserManager
        username = self.bot.username
        if username:
            self.user_manager.set_current_user(username)
            logging.info(f" User '{username}' logged in successfully")
            
            # Update config with current username for backward compatibility
            self.config['username'] = username
            
            # Migrate legacy data if needed
            self.user_manager.migrate_legacy_data(username)
            
            # Update bot file paths to use user-specific folders
            if hasattr(self, 'bot') and self.bot:
                self.bot.update_user_file_paths()

            # Load persisted upload hosts for the user
            try:
                saved_hosts = self.user_manager.get_user_setting('upload_hosts', [])
                if isinstance(saved_hosts, list):
                    self.active_upload_hosts = list(saved_hosts)
                    self.config['upload_hosts'] = list(saved_hosts)
                    if hasattr(self.bot, 'upload_hosts'):
                        self.bot.upload_hosts = list(saved_hosts)

                    # Ensure backup host toggling matches user preference
                    self.use_backup_rg = bool(
                        self.user_manager.get_user_setting('use_backup_rg', False)
                    )
                    if self.use_backup_rg and 'rapidgator-backup' not in self.active_upload_hosts:
                        self.active_upload_hosts.append('rapidgator-backup')
                    elif not self.use_backup_rg and 'rapidgator-backup' in self.active_upload_hosts:
                        self.active_upload_hosts.remove('rapidgator-backup')
                    self.config['upload_hosts'] = list(self.active_upload_hosts)
            except Exception as e:
                logging.error(f"Error applying user upload hosts: {e}", exc_info=True)
                
        
        # Initialize the application with user-specific data
        self.populate_category_tree(load_saved=True)
        self.reload_user_specific_data()
        self.update_process_threads_view()

        # NEW: Load Megathreads process threads data after login
        self.load_megathreads_process_threads_data()

        # Reload settings from user-specific data so the UI reflects saved values
        if hasattr(self, 'settings_tab'):
            self.settings_tab.load_settings()

        # Update WinRAR path display
        winrar_exe_path = self.config.get('winrar_exe_path', 'C:/Program Files/WinRAR/WinRAR.exe')
        self.winrar_exe_label.setText(f"WinRAR Executable: {winrar_exe_path}")

    def on_login_failed(self, error_msg):
        """Handle failed login"""
        # Re-enable login controls
        self.login_button.setEnabled(True)
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)

    def handle_logout(self):
        """Handle the logout process with enhanced exception handling."""
        reply = QMessageBox.question(self, 'Logout', "Are you sure you want to logout?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                # FIRST: Save all user data BEFORE clearing memory
                logging.info("💾 Saving user data before logout...")
                self.save_process_threads_data()  # Save current process threads to user folder
                self.save_backup_threads_data()   # Save backup threads
                self.save_replied_thread_ids()    # Save replied thread IDs
                self.bot.save_processed_thread_ids()  # Save processed thread IDs
                logging.info("✅ User data saved successfully")
                
                # SECOND: Clear user session and UI
                self.bot.logout()
                
                # Clear user manager session
                if hasattr(self, 'user_manager') and self.user_manager:
                    self.user_manager.clear_session()
                
                # Clear UI elements
                self.statusBar().showMessage('Logged out')
                self.login_button.setEnabled(True)
                self.username_input.setEnabled(True)
                self.password_input.setEnabled(True)
                self.category_model.removeRows(0, self.category_model.rowCount())
                self.thread_list.clear()
                self.bbcode_editor.clear()
                
                # Clear memory data structures (UI only - files are already saved)
                self.process_threads.clear()
                self.backup_threads.clear()
                self.replied_thread_ids.clear()
                self.process_threads_table.setRowCount(0)
                
                # THIRD: Reload with empty/global data for next user
                self.reload_user_specific_data()

                # Clear settings UI since no user is logged in
                if hasattr(self, 'settings_tab'):
                    # Clear settings UI since no user is logged in
                    self.settings_tab.load_settings(initial=True)

                logging.info(" Logout completed successfully")
            except Exception as e:
                self.handle_exception("handle_logout", e)

    def reupload_files(self, thread_title):
        """Re-upload files and update Keeplinks for a thread."""
        thread_info = self.backup_threads.get(thread_title)
        if not thread_info:
            QMessageBox.warning(self, "Thread Not Found", f"Thread '{thread_title}' not found in backups.")
            return

        mega_link = thread_info.get('mega_link')
        if not mega_link:
            QMessageBox.warning(self, "Mega.nz Link Missing", "Cannot re-upload without Mega.nz link.")
            return

        # Download files from Mega.nz
        files_downloaded = self.bot.download_from_mega(mega_link)
        if not files_downloaded:
            logging.error("Failed to download files from Mega.nz.")
            return

        # Re-upload to all file hosts
        new_links = []
        for file_path in files_downloaded:
            file_url = self.bot.initiate_upload_session(file_path)
            if file_url:
                new_links.append(file_url)
                logging.info(f"Re-uploaded '{file_path}'. New link: {file_url}")
            else:
                logging.error(f"Failed to upload '{file_path}'.")

        # Update Keeplinks with new links
        keeplinks_link = thread_info.get('keeplinks_link')
        if not keeplinks_link:
            QMessageBox.warning(self, "Keeplinks Link Missing", "Cannot update Keeplinks without the original link.")
            return

        updated_link = self.bot.update_keeplinks_links(keeplinks_link, new_links)
        if updated_link:
            logging.info("Keeplinks link updated successfully.")
            keeplinks_link = updated_link
            logging.info("Keeplinks link updated successfully.")
            # Update Rapidgator links in backup data
            thread_info['rapidgator_links'] = new_links
            self.save_backup_threads_data()
            self.populate_backup_threads_table()
        else:
            logging.error("Failed to update Keeplinks link.")

    def show_backup_threads_context_menu(self, position):
        menu = QMenu()
        reupload_action = menu.addAction("Re-upload Files")
        action = menu.exec_(self.backup_threads_table.viewport().mapToGlobal(position))

        if action == reupload_action:
            selected_rows = set(index.row() for index in self.backup_threads_table.selectedIndexes())
            for row in selected_rows:
                thread_title = self.backup_threads_table.item(row, 0).text()
                thread_info = self.backup_threads.get(thread_title)
                if thread_info:
                    self.reupload_thread_files(thread_title, thread_info)

    def on_category_clicked(self, index):
        """Handle category selection."""
        # Log detailed state information for debugging
        current_user = self.user_manager.get_current_user() if self.user_manager else None
        logging.info(f"📁 Category clicked - User: {current_user}, Bot login state: {self.bot.is_logged_in}")
        logging.info(f"📁 CategoryManager file path: {self.category_manager.categories_file}")
        
        if not self.bot.is_logged_in:
            logging.warning(f"❌ Category access blocked - bot.is_logged_in = {self.bot.is_logged_in}, current_user = {current_user}")
            QMessageBox.warning(self, "Login Required", "Please log in before accessing categories.")
            return

        item = self.category_model.itemFromIndex(index)
        category_name = item.text()

        logging.info(f"Category clicked: {category_name}")

        self.current_category = category_name

        if category_name not in self.category_threads:
            self.category_threads[category_name] = {}
            self.load_data(category_name)

        # Populate the thread list using QListWidget
        self.populate_thread_list(category_name, self.category_threads[category_name])

        self.statusBar().showMessage(f'Loaded threads for "{category_name}".')

    def populate_category_tree(self, load_saved=False):
        self.category_model.clear()
        self.category_model.setHorizontalHeaderLabels(['Category'])
        if load_saved:
            categories = self.category_manager.categories
        else:
            self.category_manager.extract_categories()
            categories = self.category_manager.categories

        for category_name, category_url in categories.items():
            item = QStandardItem(category_name)
            item.setData(category_url, Qt.UserRole)
            item.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
            self.category_model.appendRow(item)
        self.category_tree.expandAll()

        if categories:
            first_category = list(categories.keys())[0]
            item = self.category_model.findItems(first_category)[0]
            index = self.category_model.indexFromItem(item)
            self.category_tree.setCurrentIndex(index)
            self.on_category_clicked(index)

    def populate_backup_threads_table(self):
        """Populate the Backup Threads table with all backed-up threads."""
        self.backup_threads_table.setRowCount(0)  # Clear existing rows

        for thread_title, thread_info in self.backup_threads.items():
            row_position = self.backup_threads_table.rowCount()
            self.backup_threads_table.insertRow(row_position)

            # Thread Title
            title_item = QTableWidgetItem(thread_title)
            title_item.setData(Qt.UserRole, thread_info.get('thread_url'))
            title_item.setForeground(Qt.blue)
            title_item.setToolTip("Click to select, double-click to open thread in browser")
            title_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            self.backup_threads_table.setItem(row_position, 0, title_item)

            # Thread ID
            thread_id_item = QTableWidgetItem(str(thread_info.get('thread_id', '')))
            thread_id_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.backup_threads_table.setItem(row_position, 1, thread_id_item)

            # Rapidgator Links
            rapidgator_links = thread_info.get('rapidgator_links', [])
            dead_links = thread_info.get('dead_rapidgator_links', [])
            rapidgator_links_text = "\n".join(rapidgator_links)
            rapidgator_item = QTableWidgetItem(rapidgator_links_text)
            rapidgator_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            # Apply color coding based on backup link status using helper method
            rapidgator_status = thread_info.get('rapidgator_status', None)
            if rapidgator_status == 'dead':
                self.set_backup_link_status_color(rapidgator_item, False)  # Red for offline/dead
                rapidgator_item.setToolTip("Some Rapidgator links are dead.")
            elif rapidgator_status == 'alive':
                self.set_backup_link_status_color(rapidgator_item, True)  # Green for online/alive
                rapidgator_item.setToolTip("All Rapidgator links are alive.")
            else:
                # No status set - use neutral styling
                if rapidgator_links:
                    rapidgator_item.setToolTip("Rapidgator links available, status not checked yet.")
                else:
                    rapidgator_item.setToolTip("No Rapidgator links found.")

            self.backup_threads_table.setItem(row_position, 2, rapidgator_item)

            # Rapidgator Backup Link
            rg_backup_links = thread_info.get('rapidgator_backup_links', [])
            flat_links = []
            for link in rg_backup_links:
                if isinstance(link, list):
                    flat_links.extend(link)
                else:
                    flat_links.append(link)
            rg_backup_text = "\n".join(flat_links)
            rg_backup_item = QTableWidgetItem(rg_backup_text)
            rg_backup_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.backup_threads_table.setItem(row_position, 3, rg_backup_item)


            # Keeplinks Link
            keeplinks_link = thread_info.get('keeplinks_link', '')
            keeplinks_item = QTableWidgetItem(keeplinks_link)
            keeplinks_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.backup_threads_table.setItem(row_position, 4, keeplinks_item)

        # Adjust columns
        self.backup_threads_table.resizeColumnsToContents()

    def start_download_button_clicked(self):
        url = self.url_input_field.text().strip()
        # 1) extract file_code
        import re
        m = re.search(r'katfile\.com/([^/]+)/', url)
        if not m:
            QMessageBox.warning(self, "Invalid URL", "Please enter a valid Katfile URL.")
            return
        file_code = m.group(1)

        # 2) get API key
        api_key = self.settings_widget.get_katfile_api_key()
        if not api_key:
            QMessageBox.warning(self, "Missing API Key", "Set your Katfile API key in Settings.")
            return

        # 3) call API
        try:
            api = KatfileDownloaderAPI(api_key)
            info = api.get_direct_download_info(file_code)
            direct_url, size = info['url'], info['size']
        except Exception as e:
            QMessageBox.critical(self, "Katfile Error", str(e))
            return

        # 4) hand off to your existing DownloadWorker
        # Assuming your DownloadWorker takes (url, size, dest_path, ...)
        dest = os.path.join(self.download_dir, file_code)
        self.download_worker = DownloadWorker(direct_url, size, dest)
        self.download_worker.start()
        QMessageBox.information(self, "Download Started",
                                f"Downloading to:\n{dest}\n\nSize: {size} bytes")

    def is_link_active(self, url):
        """
        Check if a Rapidgator link is active using Rapidgator's API.
        Returns True if the link is alive, False otherwise.
        """
        # If token was never set, skip
        result = self.bot.check_rapidgator_link_status(url)
        return bool(result and result.get('status') == 'ACCESS')
    def init_timers(self):
        """Initialize timers for periodic tasks."""
        self.link_check_timer = QTimer()
        self.link_check_timer.timeout.connect(self.check_rapidgator_links)
        self.link_check_timer.start(3600000)  # Check every hour (3600000 ms)

    def on_backup_selection_changed(self) -> None:
        """يملأ self.selected_backup_threads بالـ Thread‑IDs المختارة حالياً."""
        rows = {idx.row() for idx in self.backup_threads_table.selectionModel().selectedRows()}
        self.selected_backup_threads.clear()

        for r in rows:
            id_item = self.backup_threads_table.item(r, 1)  # عمود Thread ID
            if id_item and id_item.text():
                self.selected_backup_threads.append(id_item.text())

        logging.debug(f"Selected backup threads → {self.selected_backup_threads}")

    def on_check_rapidgator_clicked(self):
        """Process all selected Thread-IDs at once."""
        if not getattr(self, "selected_backup_threads", []):
            QMessageBox.information(self, "Info", "Please select at least one thread.")
            return

        for thread_id in self.selected_backup_threads:
            self.check_rapidgator_links(thread_id)

        # Optional: Show success message
        QMessageBox.information(self, "Info", f"Checking Rapidgator links for {len(self.selected_backup_threads)} selected threads...")

    def on_backup_thread_double_click(self, row, column):
        """Open the thread URL when the thread title is double-clicked."""
        if column == 0:  # Ensure only clicks on the Thread Title column are handled
            thread_url = self.backup_threads_table.item(row, column).data(Qt.UserRole)
            if thread_url:
                webbrowser.open(thread_url)
            else:
                QMessageBox.warning(self, "URL Missing", "The selected thread does not have a valid URL.")

    def init_process_threads_view(self):
        """Initialize the 'Process Threads' view in the content area."""
        # Container widget + layout
        process_threads_widget = QWidget()
        process_threads_layout = QVBoxLayout(process_threads_widget)
        process_threads_layout.setContentsMargins(5, 5, 5, 5)
        process_threads_layout.setSpacing(10)

        # Splitter: top = threads management, bottom = BBCode editor
        splitter = QSplitter(Qt.Vertical)
        process_threads_layout.addWidget(splitter)

        # ─── Top Layout: Threads Management ───────────────────────────────────
        threads_management_widget = QWidget()
        threads_management_layout = QVBoxLayout(threads_management_widget)
        threads_management_layout.setContentsMargins(0, 0, 0, 0)
        threads_management_layout.setSpacing(8)

        # Section label
        threads_label = QLabel("Process Threads")
        threads_label.setFont(QFont("Arial", 12, QFont.Bold))
        threads_management_layout.addWidget(threads_label)

        # --- Filter Bar -------------------------------------------------------
        filter_bar = QWidget()
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)

        # Search field
        self.process_filter_input = QLineEdit()
        self.process_filter_input.setPlaceholderText("Search threads…")
        self.process_filter_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        filter_layout.addWidget(self.process_filter_input)

        # Column selector
        self.filter_column_combo = QComboBox()
        self.filter_column_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.filter_column_combo.addItem("All columns", -1)
        for label, idx in [
            ("Title", 0),
            ("Category", 1),
            ("Thread ID", 2),
            ("Rapidgator Links", 3),
            ("RG Backup Link", 4),
            ("Keeplinks Link", 5),
        ]:
            self.filter_column_combo.addItem(label, idx)
        filter_layout.addWidget(self.filter_column_combo)

        # Status checkboxes
        self.status_pending_check = QCheckBox("Pending")
        self.status_downloaded_check = QCheckBox("Downloaded")
        self.status_uploaded_check = QCheckBox("Uploaded")
        self.status_posted_check = QCheckBox("Posted")
        for cb in (
                self.status_pending_check,
                self.status_downloaded_check,
                self.status_uploaded_check,
                self.status_posted_check
        ):
            cb.setChecked(True)
            filter_layout.addWidget(cb)

        threads_management_layout.addWidget(filter_bar)

        # Connect filter signals
        self.process_filter_input.textChanged.connect(self.filter_process_threads)
        self.filter_column_combo.currentIndexChanged.connect(self.filter_process_threads)
        for cb in (
                self.status_pending_check,
                self.status_downloaded_check,
                self.status_uploaded_check,
                self.status_posted_check
        ):
            cb.stateChanged.connect(self.filter_process_threads)

        # --- Action Buttons ---------------------------------------------------
        actions_bar = QWidget()
        actions_layout = QHBoxLayout(actions_bar)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self.process_download_button = QPushButton("Download Selected")
        self.process_download_button.setIcon(QIcon.fromTheme("download"))
        self.process_download_button.clicked.connect(self.start_download_operation)
        actions_layout.addWidget(self.process_download_button)

        self.process_upload_button = QPushButton("Upload")
        self.process_upload_button.setIcon(QIcon.fromTheme("upload"))
        self.process_upload_button.clicked.connect(self.upload_selected_process_threads)
        actions_layout.addWidget(self.process_upload_button)

        self.remove_process_thread_button = QPushButton("Remove Selected Thread(s)")
        self.remove_process_thread_button.setIcon(QIcon.fromTheme("edit-delete"))
        self.remove_process_thread_button.clicked.connect(self.remove_selected_process_threads)
        actions_layout.addWidget(self.remove_process_thread_button)

        self.proceed_template_button = QPushButton("Proceed Template")
        self.proceed_template_button.setIcon(QIcon.fromTheme("edit"))
        self.proceed_template_button.clicked.connect(self.generate_template_for_selected_thread)
        actions_layout.addWidget(self.proceed_template_button)

        self.test_color_button = QPushButton("🧪 Test Colors")
        self.test_color_button.setToolTip("Test thread status color system (Blue→Yellow→Green)")
        self.test_color_button.clicked.connect(self.test_color_status_system)
        self.test_color_button.setStyleSheet(
            "QPushButton { background-color: #ff6b35; color: white; font-weight: bold; }"
        )
        actions_layout.addWidget(self.test_color_button)

        threads_management_layout.addWidget(actions_bar)

        # --- Threads Table ----------------------------------------------------
        self.process_threads_table = QTableWidget()
        self.process_threads_table.setAlternatingRowColors(True)
        self.process_threads_table.setColumnCount(6)
        self.process_threads_table.setHorizontalHeaderLabels([
            "Thread Title", "Category", "Thread ID",
            "Rapidgator Links", "RG Backup Link", "Keeplinks Link"
        ])

        # Table appearance & behavior
        self.process_threads_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.process_threads_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.process_threads_table.setShowGrid(True)
        self.process_threads_table.setGridStyle(Qt.SolidLine)
        self.process_threads_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.process_threads_table.horizontalHeader()
        header.setFont(QFont("Arial", 10, QFont.Bold))
        self.process_threads_table.setFont(QFont("Arial", 10))
        self.process_threads_table.verticalHeader().setDefaultSectionSize(28)
        self.process_threads_table.verticalHeader().hide()
        header.setFixedHeight(30)

        # Column widths and resize modes
        widths = {0: 300, 1: 150, 2: 100, 3: 200, 4: 200, 5: 200}
        for col, w in widths.items():
            self.process_threads_table.setColumnWidth(col, w)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3, 4, 5):
            header.setSectionResizeMode(col, QHeaderView.Interactive)

        # Sorting & delegate & context menu
        self.process_threads_table.setSortingEnabled(True)
        # Create a single instance of StatusColorDelegate and apply it to the table
        self.status_color_delegate = StatusColorDelegate(self.process_threads_table)
        self.process_threads_table.setItemDelegate(self.status_color_delegate)
        self.process_threads_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.process_threads_table.customContextMenuRequested.connect(
            self.show_process_threads_context_menu
        )
        self.process_threads_table.cellClicked.connect(self.on_process_thread_selected)
        self.process_threads_table.itemDoubleClicked.connect(self.on_thread_double_click)

        threads_management_layout.addWidget(self.process_threads_table)
        splitter.addWidget(threads_management_widget)

        # ─── Bottom Layout: Advanced BBCode Editor ─────────────────────────────
        bbcode_editor_group = QGroupBox("Advanced BBCode Editor")
        bbcode_editor_group.setFont(QFont("Arial", 12, QFont.Bold))
        bbcode_layout = QVBoxLayout(bbcode_editor_group)
        self.process_bbcode_editor = AdvancedBBCodeEditor()
        self.process_bbcode_editor.content_changed.connect(self.on_bbcode_content_changed)
        bbcode_layout.addWidget(self.process_bbcode_editor)

        # Reply button
        self.reply_button = QPushButton("Reply (Post BBCode)")
        self.reply_button.setIcon(QIcon.fromTheme("mail-send"))
        self.reply_button.clicked.connect(self.on_reply_button_clicked)
        bbcode_layout.addWidget(self.reply_button)

        splitter.addWidget(bbcode_editor_group)

        # Add the whole Process Threads view into the main content area
        self.content_area.addWidget(process_threads_widget)

    def format_bbcode(self, editor, start_tag, end_tag):
        """Apply BBCode formatting to the selected text in the specified editor."""
        cursor = editor.textCursor()
        selected_text = cursor.selectedText()
        if selected_text:
            formatted_text = f"{start_tag}{selected_text}{end_tag}"
            cursor.insertText(formatted_text)

    def filter_process_threads(self, _=None):
        """Filter the process threads table by search text, selected column, and status checkboxes."""
        # 1) Read filter inputs
        search_text = self.process_filter_input.text().lower().strip()
        column = self.filter_column_combo.currentData()  # -1 = search all columns

        # 2) Read status checkbox states
        show_pending = self.status_pending_check.isChecked()
        show_downloaded = self.status_downloaded_check.isChecked()
        show_uploaded = self.status_uploaded_check.isChecked()
        show_posted = self.status_posted_check.isChecked()

        # If no status is checked, treat as if all are checked
        if not any((show_pending, show_downloaded, show_uploaded, show_posted)):
            show_pending = show_downloaded = show_uploaded = show_posted = True

        table = self.process_threads_table
        row_count = table.rowCount()
        col_count = table.columnCount()

        for row in range(row_count):
            # A) Status filter: get the stored status key from column 0 UserRole
            status_item = table.item(row, 0)
            status_key = status_item.data(Qt.UserRole) if status_item else ""
            status_ok = (
                    (status_key == "status-pending" and show_pending) or
                    (status_key == "status-downloaded" and show_downloaded) or
                    (status_key == "status-uploaded" and show_uploaded) or
                    (status_key == "status-posted" and show_posted)
            )

            # B) Text filter: match empty or appear in the chosen column(s)
            if not search_text:
                text_ok = True
            else:
                text_ok = False
                if column == -1:
                    # Search all columns
                    for c in range(col_count):
                        item = table.item(row, c)
                        if item and search_text in item.text().lower():
                            text_ok = True
                            break
                else:
                    item = table.item(row, column)
                    text_ok = bool(item and search_text in item.text().lower())

            # C) Show row only if both status and text match
            table.setRowHidden(row, not (status_ok and text_ok))

    def on_bbcode_content_changed(self, content):
        """Handle BBCode content changes and save to data structure"""
        try:
            # Get currently selected row
            selected_rows = list({index.row() for index in self.process_threads_table.selectedIndexes()})
            if not selected_rows:
                return
            
            row = selected_rows[0]
            
            # Get thread info
            category_item = self.process_threads_table.item(row, 1)
            title_item = self.process_threads_table.item(row, 0)
            
            if not category_item or not title_item:
                return
                
            category_name = category_item.text()
            thread_title = title_item.text()
            
            # Save BBCode content to data structure
            if (category_name in self.process_threads and 
                thread_title in self.process_threads[category_name]):
                self.process_threads[category_name][thread_title]['bbcode_content'] = content
                logging.debug(f"Updated BBCode content for {category_name}/{thread_title}")
                
        except Exception as e:
            logging.error(f"Error saving BBCode content: {e}", exc_info=True)

    def on_process_thread_selected(self, row, column):
        """Handle thread selection and load BBCode content into editor"""
        try:
            # Get thread info
            category_item = self.process_threads_table.item(row, 1)
            title_item = self.process_threads_table.item(row, 0)
            
            if not category_item or not title_item:
                return
                
            category_name = category_item.text()
            thread_title = title_item.text()
            
            # Load BBCode content from data structure
            if (category_name in self.process_threads and 
                thread_title in self.process_threads[category_name]):
                
                thread_data = self.process_threads[category_name][thread_title]
                bbcode_content = thread_data.get('bbcode_content', '')
                
                # Temporarily disconnect signal to avoid recursive updates
                self.process_bbcode_editor.content_changed.disconnect()
                self.process_bbcode_editor.set_text(bbcode_content)
                self.process_bbcode_editor.content_changed.connect(self.on_bbcode_content_changed)
                
                logging.debug(f"Loaded BBCode content for {category_name}/{thread_title}")
                
        except Exception as e:
            logging.error(f"Error loading BBCode content: {e}", exc_info=True)

    def on_reply_button_clicked(self):
        selected_rows = list({index.row() for index in self.process_threads_table.selectedIndexes()})
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select exactly one thread to reply to.")
            return

        row = selected_rows[0]
        thread_url_item = self.process_threads_table.item(row, 0)
        if not thread_url_item:
            QMessageBox.warning(self, "Error", "Could not retrieve the thread URL from the selected row.")
            return

        thread_url = thread_url_item.data(Qt.UserRole)
        if not thread_url:
            QMessageBox.warning(self, "Missing URL", "No main thread URL found for this thread.")
            return

        bbcode_content = self.process_bbcode_editor.get_text().strip()
        if not bbcode_content:
            QMessageBox.warning(self, "No BBCode", "The BBCode editor is empty.")
            return

        # --- Attempt the reply ---
        success = self.reply_to_forum_thread(thread_url, bbcode_content, row)
        if success:
            QMessageBox.information(self, "Reply Posted", "Your BBCode reply was posted successfully.")

            # 1) Mark row green
            self.mark_process_thread_row_green(row)

            # 2) Get the thread_id from the table
            thread_id_item = self.process_threads_table.item(row, 2)  # 3rd column is "Thread ID"
            thread_id = thread_id_item.text().strip()

            # 3) Add to replied_thread_ids and save
            if thread_id:
                self.replied_thread_ids.add(thread_id)
                self.save_replied_thread_ids()
                logging.info(f"Marked thread ID={thread_id} as replied and turned row green.")

        else:
            QMessageBox.warning(self, "Reply Error", "Failed to post the reply. Check logs or login status.")

    def mark_process_thread_row_green(self, row: int):
        """Mark a row green to indicate a successful reply."""
        theme = theme_manager.get_current_theme()
        bg_brush = QBrush(QColor(theme.SUCCESS))
        fg_brush = QBrush(QColor(theme.TEXT_ON_PRIMARY))
        col_count = self.process_threads_table.columnCount()
        for col in range(col_count):
            item = self.process_threads_table.item(row, col)
            if item:
                item.setBackground(bg_brush)
                item.setForeground(fg_brush)

    def reply_to_forum_thread(self, thread_url: str, bbcode_content: str, row_index: int) -> bool:
        """
        Use the Selenium bot to:
        1) Navigate to the thread URL.
        2) Find the <textarea id="vB_Editor_QR_textarea"> and clear+type BBCode.
        3) Wait for any overlay (ads, etc.) to disappear or remove it if needed.
        4) Click the '#qr_submit' button (Antworten).

        If the reply is successful, mark the table row as 'replied' (green) and save the status.

        Returns True if successful, False otherwise.
        """
        try:
            # 1) Ensure we are logged in
            if not self.bot.is_logged_in:
                QMessageBox.warning(self, "Not Logged In", "Please log in before posting a reply.")
                return False

            # 2) Navigate to the thread
            self.bot.driver.get(thread_url)

            # 3) Locate the BBCode textarea (wait up to 10 seconds)
            textarea = WebDriverWait(self.bot.driver, 10).until(
                EC.presence_of_element_located((By.ID, "vB_Editor_QR_textarea"))
            )
            textarea.clear()
            textarea.send_keys(bbcode_content)

            # 4) Wait for or remove the overlay if present
            try:
                # Attempt to wait for the overlay to go away for up to 5 seconds
                WebDriverWait(self.bot.driver, 5).until(
                    EC.invisibility_of_element_located((By.ID, "dontfoid"))
                )
            except TimeoutException:
                # If still present, remove via JavaScript
                try:
                    overlay = self.bot.driver.find_element(By.ID, "dontfoid")
                    self.bot.driver.execute_script("arguments[0].remove();", overlay)
                    time.sleep(1)
                except:
                    pass

            # 5) Locate and click the "Antworten" (#qr_submit) button
            submit_button = WebDriverWait(self.bot.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#qr_submit"))
            )

            try:
                submit_button.click()
            except ElementClickInterceptedException:
                # If normal click fails (ads in front?), try JS click
                self.bot.driver.execute_script("arguments[0].click();", submit_button)

            # brief wait to confirm the post submission is processed
            time.sleep(2)
            logging.info(f"Posted reply to {thread_url} successfully.")

            # 🎯 Update thread status using new tracking system
            try:
                # Get thread info from table
                title_item = self.process_threads_table.item(row_index, 0)  # Thread Title column
                category_item = self.process_threads_table.item(row_index, 1)  # Category column
                
                if title_item and category_item:
                    thread_title = title_item.text()
                    category_name = category_item.text()
                    self.mark_post_complete(category_name, thread_title)
                    logging.info(f"✅ Marked post complete for: {category_name}/{thread_title}")
                    # 🔄 Refresh the table to show color changes
                    self.populate_process_threads_table(self.process_threads)
                    logging.info("🔄 Process threads table refreshed to show post status")
                else:
                    # Fallback to old system if table data not available
                    self.mark_thread_as_replied(row_index)
            except Exception as e:
                logging.warning(f"Could not update thread status, using fallback: {e}")
                self.mark_thread_as_replied(row_index)

            return True

        except Exception as e:
            logging.error(f"Failed to post reply to {thread_url}: {e}", exc_info=True)
            return False
    def mark_thread_as_replied(self, row: int):
        """
        Colors the given row green and sets row_status='replied' in self.process_threads.
        This ensures that after a restart, it remains green.
        """
        green_brush = QBrush(QColor("#98FB98"))  # Light green

        col_count = self.process_threads_table.columnCount()
        for col in range(col_count):
            item = self.process_threads_table.item(row, col)
            if item:
                item.setBackground(green_brush)

        category_name = self.process_threads_table.item(row, 1).text()
        thread_title = self.process_threads_table.item(row, 0).text()

        if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
            self.process_threads[category_name][thread_title]['row_status'] = 'replied'
            self.save_process_threads_data()  # so it persists on disk

    def start_download_operation(self):
        """
        🔒 Thread-safe download session management
        Start the download process with progress tracking
        """
        # 🔒 Prevent concurrent download sessions - CRITICAL FOR STABILITY
        if hasattr(self, '_download_in_progress') and self._download_in_progress:
            QMessageBox.warning(
                self, 
                "Download In Progress", 
                "⚠️ Another download is already running!\n\n"
                "Please wait for the current download to complete or cancel it first."
            )
            return
            
        # 🔒 Set download lock
        self._download_in_progress = True
        
        try:
            selected_rows = set(index.row() for index in self.process_threads_table.selectedIndexes())
            if not selected_rows:
                self.statusBar().showMessage("Please select at least one thread to download")
                # 🔓 Release lock if no rows selected
                self._download_in_progress = False
                return
            
            # 📋 Track selected threads for status update after completion
            self._current_download_threads = []
            for row in selected_rows:
                try:
                    # Get thread info from table
                    title_item = self.process_threads_table.item(row, 0)  # Thread Title column
                    category_item = self.process_threads_table.item(row, 1)  # Category column
                    
                    if title_item and category_item:
                        thread_title = title_item.text()
                        category_name = category_item.text()
                        self._current_download_threads.append((category_name, thread_title))
                        logging.info(f"📝 Tracking download for: {category_name}/{thread_title}")
                except Exception as e:
                    logging.warning(f"Could not track thread for row {row}: {e}")
                    
            logging.info(f"📋 Tracking {len(self._current_download_threads)} threads for download completion")

            # 🔄 COMPREHENSIVE dialog reset and preparation
            # First, handle old worker cleanup and signal disconnections
            if hasattr(self, 'download_worker') and self.download_worker:
                try:
                    # 📌 COMPREHENSIVE: Disconnect ALL old worker signals to prevent interference
                    self.download_worker.file_created.disconnect()
                    self.download_worker.file_progress_update.disconnect()
                    self.download_worker.status_update.disconnect()
                    self.download_worker.operation_complete.disconnect()
                    # Also disconnect any additional signals if they exist
                    try:
                        self.download_worker.download_success.disconnect()
                        self.download_worker.download_error.disconnect()
                        self.download_worker.file_progress.disconnect()
                    except Exception:
                        pass  # Some signals may not exist or be connected
                    logging.info("🔌 COMPREHENSIVE: Disconnected ALL old download worker signals")
                except TypeError:
                    pass  # No connections to disconnect
                    
            # 🚫 FORCE FRESH DIALOG CREATION to eliminate any synchronization issues
            logging.info("🗑️ DESTROYING any existing dialog to ensure completely fresh state...")
            
            # Step 1: Completely destroy old dialog if it exists
            if hasattr(self, 'download_progress_dialog') and self.download_progress_dialog:
                try:
                    # Disconnect any remaining signals from old dialog
                    try:
                        self.download_progress_dialog.pause_clicked.disconnect()
                        self.download_progress_dialog.continue_clicked.disconnect()
                        self.download_progress_dialog.cancel_clicked.disconnect()
                    except Exception:
                        pass
                    
                    # Close and delete old dialog
                    self.download_progress_dialog.close()
                    self.download_progress_dialog.setParent(None)
                    self.download_progress_dialog.deleteLater()
                    logging.info("🗑️ Old dialog destroyed completely")
                except Exception as e:
                    logging.warning(f"Error destroying old dialog: {e}")
                    
                # Clear the reference
                self.download_progress_dialog = None
            
            # Step 2: Force Qt to process deletion events
            QApplication.processEvents()
            import time
            time.sleep(0.2)  # Give Qt time to fully cleanup old dialog
            
            # Step 3: Create completely fresh dialog
            logging.info("🆕 Creating COMPLETELY FRESH download progress dialog...")
            self.download_progress_dialog = DownloadProgressDialog(self)
            
            # Step 4: Verify fresh state
            widget_count = len(self.download_progress_dialog.file_widgets) if hasattr(self.download_progress_dialog, 'file_widgets') else 0
            logging.info(f"✅ Fresh dialog created successfully (widgets: {widget_count})")

            # 🔄 Since we created a fresh dialog, no reset needed - it's already clean!
            logging.info("✅ Fresh dialog is ready - no reset needed for brand new instance")


            # Connect pause/continue/cancel from the dialog
            self.download_progress_dialog.pause_clicked.connect(self.pause_downloads)
            self.download_progress_dialog.continue_clicked.connect(self.resume_downloads)
            self.download_progress_dialog.cancel_clicked.connect(self.cancel_downloads)
            logging.info("🔗 Connected new dialog control signals")
            
            # Show dialog after all setup is complete
            self.download_progress_dialog.show()
            logging.info("👁️ Dialog shown and ready for new downloads")

            # 🚨 COMPREHENSIVE cleanup for existing download worker
            if hasattr(self, 'download_worker') and self.download_worker:
                try:
                    # Cancel and wait for proper cleanup
                    self.download_worker.cancel_downloads()
                    
                    # Give it a moment to clean up
                    QApplication.processEvents()
                    
                    # 🛡️ Disconnect ALL signals to prevent cross-references and crashes
                    try:
                        self.download_worker.file_created.disconnect()
                        self.download_worker.file_progress_update.disconnect()
                        self.download_worker.download_finished.disconnect()
                        self.download_worker.status_update.disconnect()
                        self.download_worker.operation_complete.disconnect()
                        self.download_worker.file_progress.disconnect()
                        self.download_worker.download_success.disconnect()
                        self.download_worker.download_error.disconnect()
                    except Exception as e:
                        logging.debug(f"Signal disconnection (expected): {e}")
                    
                    # Force immediate cleanup
                    self.download_worker.deleteLater()
                    self.download_worker = None
                    
                    # Additional safety delay
                    QApplication.processEvents()
                    import time
                    time.sleep(0.1)  # Brief pause to allow Qt cleanup
                    
                except Exception as e:
                    logging.warning(f"⚠️ Error cleaning up existing download worker: {e}")
                    self.download_worker = None

            # Create the worker
            self.download_worker = DownloadWorker(
                bot=self.bot,
                file_processor=self.file_processor,
                selected_rows=selected_rows,
                gui=self
            )

            # 🔗 CRITICAL: Connect worker signals to RESET dialog for fresh progress tracking
            dialog_session_id = getattr(self.download_progress_dialog, 'session_id', 'unknown')
            logging.info(f"🔗 Connecting download worker signals to progress dialog (Session: {dialog_session_id})...")
            
            # Connect the primary progress signals for file creation and updates
            self.download_worker.file_created.connect(
                self.download_progress_dialog.create_file_widget
            )
            self.download_worker.file_progress_update.connect(
                self.download_progress_dialog.update_file_progress
            )
            logging.info(f"📊 Connected file progress signals to dialog session {dialog_session_id}")

            # Connect status and completion signals
            self.download_worker.status_update.connect(self.update_download_status)
            self.download_worker.operation_complete.connect(self.on_download_complete)
            self.download_worker.file_progress.connect(self.on_file_progress_update)
            logging.info("📡 Connected status and completion signals")
            
            # ✅ FINAL VALIDATION: Ensure everything is ready for clean download start
            dialog_widgets = len(self.download_progress_dialog.file_widgets) if hasattr(self.download_progress_dialog, 'file_widgets') else 0
            logging.info(f"🚀 READY TO START: Clean download session prepared (dialog widgets: {dialog_widgets})")

            # -------------- NEW: Connect success/error signals to color row --------------
            self.download_worker.download_success.connect(self.on_download_row_success)
            self.download_worker.download_error.connect(self.on_download_row_error)

            # Start the worker
            self.download_worker.start()
            self.statusBar().showMessage("Starting downloads...")
            
        except Exception as e:
            # 😱 Critical error during download setup
            logging.error(f"⚠️ Critical error in download setup: {e}")
            QMessageBox.critical(
                self,
                "Download Setup Error", 
                f"Failed to start download operation:\n{str(e)}"
            )
            # 🔓 Release lock on critical error
            self._download_in_progress = False

    def _update_download_progress_dialog(self, host, progress, status_msg, current_size, total_size, current_file):
        """
        This method acts as a slot for the `host_progress_updated` signal of `DownloadProgressDialog`.
        It is meant to be executed on the main thread to safely update the UI.
        """
        if self.download_progress_dialog:  # Check if dialog is still open
            self.download_progress_dialog._update_host_widget(host, progress, status_msg, current_size, total_size,
                                                              current_file)

    def handle_host_progress(self, row, host_idx, progress, status, current_size, total_size):
        """Handle host progress signal from the upload worker and update the progress dialog."""
        host_name = self.get_host_name(host_idx)
        if self.upload_progress_dialog:  # Check if the dialog is still active
            self.upload_progress_dialog.update_host_progress(
                host=host_name,
                progress=progress,
                status_msg=status,
                current_size=current_size,
                total_size=total_size
            )

    def pause_downloads(self):
        if self.download_worker:
            self.download_worker.pause_downloads()

    def resume_downloads(self):
        if self.download_worker:
            self.download_worker.resume_downloads()

    def cancel_downloads(self):
        """🔒 Cancel downloads and release session lock"""
        if self.download_worker:
            self.download_worker.cancel_downloads()
        
        # 🔓 Release download lock when cancelled
        if hasattr(self, '_download_in_progress'):
            self._download_in_progress = False
            logging.info("🔓 Download session lock released (cancelled)")

    def on_download_complete(self, success, message):
        """🔒 Handle download completion and release session lock"""
        if hasattr(self, 'download_progress_dialog') and self.download_progress_dialog:
            self.download_progress_dialog.close()
            self.download_progress_dialog = None

        if success:
            QMessageBox.information(self, "Download Complete", message)
            
            # 🎯 Update thread status for completed downloads
            if hasattr(self, '_current_download_threads') and self._current_download_threads:
                for category_name, thread_title in self._current_download_threads:
                    self.mark_download_complete(category_name, thread_title)
                    logging.info(f"✅ Marked download complete for: {category_name}/{thread_title}")
                # Clear the tracking list
                self._current_download_threads = []
                # 🔄 Refresh the table to show color changes
                self.populate_process_threads_table(self.process_threads)
                logging.info("🔄 Process threads table refreshed to show download status")
        else:
            QMessageBox.warning(self, "Download Status", message)

        self.statusBar().showMessage(message)
        if self.download_worker:
            self.download_worker.deleteLater()
            self.download_worker = None
            
        # 🔓 Release download lock when operation complete
        if hasattr(self, '_download_in_progress'):
            self._download_in_progress = False
            logging.info("🔓 Download session lock released (completed)")

    def on_download_row_success(self, row: int):
        """Color the row according to 'downloaded' status."""
        theme = theme_manager.get_current_theme()
        bg_brush = QBrush(QColor(theme.WARNING))
        fg_brush = QBrush(QColor(theme.TEXT_ON_PRIMARY))
        col_count = self.process_threads_table.columnCount()
        for col in range(col_count):
            item = self.process_threads_table.item(row, col)
            if item:
                item.setBackground(bg_brush)
                item.setForeground(fg_brush)

        # --- NEW: Update row_status in self.process_threads, then save ---
        category_name = self.process_threads_table.item(row, 1).text()
        thread_title = self.process_threads_table.item(row, 0).text()
        if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
            self.process_threads[category_name][thread_title]['row_status'] = 'downloaded'
            self.save_process_threads_data()  # so next app restart, we remember

    def on_download_row_error(self, row: int, error_msg: str):
        """Color the row RED on download error."""
        theme = theme_manager.get_current_theme()
        bg_brush = QBrush(QColor(theme.ERROR))
        fg_brush = QBrush(QColor(theme.TEXT_ON_PRIMARY))
        col_count = self.process_threads_table.columnCount()
        for col in range(col_count):
            item = self.process_threads_table.item(row, col)
            if item:
                item.setBackground(bg_brush)
                item.setForeground(fg_brush)
        logging.error(f"Download error on row {row}: {error_msg}")
        self.statusBar().showMessage(f"Download error (row {row}): {error_msg}")

        # --- NEW: Update row_status in self.process_threads, then save ---
        category_name = self.process_threads_table.item(row, 1).text()
        thread_title = self.process_threads_table.item(row, 0).text()
        if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
            self.process_threads[category_name][thread_title]['row_status'] = 'error'
            self.save_process_threads_data()

    def on_file_progress_update(self, row, progress):
        # For example, you could update a "Progress" column in the table
        pass

    def update_download_status(self, msg):
        self.statusBar().showMessage(msg)
        logging.info(msg)

    def on_upload_finished(self, success, message, category_name, thread_title):
        """
        Handle the completion of the upload process.

        Parameters:
        - success (bool): Indicates if the upload was successful.
        - message (str): Information or error message.
        - category_name (str): Name of the category.
        - thread_title (str): Title of the thread.
        """
        self.upload_progress_bar.setVisible(False)  # Hide the progress bar
        self.upload_button.setEnabled(True)  # Re-enable the upload button
        if success:
            QMessageBox.information(self, "Upload Complete", message)
            logging.info(message)

            # 🎯 Update thread status for completed upload
            self.mark_upload_complete(category_name, thread_title)
            logging.info(f"✅ Marked upload complete for: {category_name}/{thread_title}")

            # Update links in process_threads to only include the new Rapidgator link
            new_links = self.process_threads[category_name][thread_title].get('links', {})
            rapidgator_links = new_links.get('rapidgator.net', [])

            # Replace existing links with only Rapidgator links
            self.process_threads[category_name][thread_title]['links'] = {'rapidgator.net': rapidgator_links}

            # Save and refresh
            self.save_process_threads_data()
            # 🔄 Refresh the table to show color changes
            self.populate_process_threads_table(self.process_threads)
            logging.info("🔄 Process threads table refreshed to show upload status")
        else:
            QMessageBox.critical(self, "Upload Failed", message)
            logging.error(message)

# ... (rest of the code remains the same)
    def build_links_block(self, category_name: str, thread_title: str) -> str:
        """
        Build a BBCode block containing:
        1) The Keeplinks short link.
        2) Separate lines for each file-host in the order specified in settings.
        """
        # 1) احصل على معلومات الموضوع
        thread_info = self.process_threads.get(category_name, {}).get(thread_title)
        if not thread_info:
            return ""

        links_dict = thread_info.get("links", {})
        if not links_dict:
            return ""

        result_lines = []

        # 2) Keeplinks أولاً
        keeplinks = links_dict.get("keeplinks")
        if keeplinks:
            result_lines.append("[B]Download via Keeplinks (Short Link):[/B]")
            if isinstance(keeplinks, list):
                for url in keeplinks:
                    result_lines.append(f"[url]{url}[/url]")
            else:
                result_lines.append(f"[url]{keeplinks}[/url]")
            result_lines.append("")  # blank line

        # 3) خريطة من اسم المضيف في الإعدادات إلى (key في links_dict، label للعرض)
        host_key_map = {
            "rapidgator": ("rapidgator.net", "Rapidgator"),
            "nitroflare": ("nitroflare.com", "Nitroflare"),
            "ddownload": ("ddownload.com", "DDownload"),
            "katfile": ("katfile.com", "Katfile"),
            "mega": ("mega", "Mega"),
        }

        # 4) لفّ على المضيفات بالترتيب من settings
        for host in self.active_upload_hosts:
            key, label = host_key_map.get(host.lower(), (host.lower(), host.capitalize()))
            direct_links = links_dict.get(key, [])
            if direct_links:
                result_lines.append(f"[B]Download From {label}:[/B]")
                for url in direct_links:
                    result_lines.append(f"[url]{url}[/url]")
                result_lines.append("")  # blank line

        # 5) ارجع النص النهائي
        return "\n".join(line for line in result_lines).strip()

    def generate_template_for_selected_thread(self):
        # IMMEDIATE DEBUG - FIRST LINE TO CONFIRM METHOD IS CALLED AT ALL
        print("\n" + "#"*120)
        print("🔥 CRITICAL DEBUG: METHOD ENTRY CONFIRMED! generate_template_for_selected_thread CALLED!")
        print("🔥 TIMESTAMP:", datetime.now().strftime('%H:%M:%S.%f'))
        print("#"*120 + "\n")
        
        # Also force to file immediately
        with open('debug_method_calls.txt', 'a', encoding='utf-8') as f:
            f.write(f"\n{datetime.now()}: generate_template_for_selected_thread CALLED!\n")
            f.flush()
        
        """
        After user clicks 'Proceed Template':
        1) Get the selected row's thread_id and category.
        2) Retrieve Keeplinks short URL, direct host links from process_threads.
        3) Call send_bbcode_to_gpt_api(...) to transform the original BBCode.
        4) Build a separate links block with short link + direct links.
        5) Append that block to the final BBCode, display in the editor, and save.
        """
        print("\n" + "="*80)
        print("🚀 FASTPIC DEBUG: generate_template_for_selected_thread method STARTED!")
        print("🚀 Time:", datetime.now().strftime('%H:%M:%S'))
        print("🚀 Button clicked successfully - method is being called!")
        print("="*80 + "\n")
        
        logging.info("\n" + "="*80)
        logging.info("🚀 FASTPIC DEBUG: generate_template_for_selected_thread method STARTED!")
        logging.info(f"🚀 Time: {datetime.now().strftime('%H:%M:%S')}")
        logging.info("🚀 Button clicked successfully - method is being called!")
        logging.info("="*80 + "\n")
        
        selected_items = self.process_threads_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Thread Selected", "Please select a thread.")
            return

        thread_id = selected_items[2].text()  # "Thread ID" column
        category_name = selected_items[1].text()  # "Category" column
        thread_title = selected_items[0].text()  # "Thread Title" column

        # 1) Get Keeplinks from backup or process_threads, but we already unify them in process_threads:
        #    If you also store them in backup, you can get from there. We'll assume process_threads is up-to-date.
        thread_info = self.process_threads.get(category_name, {}).get(thread_title, {})
        keeplinks_url = ""
        if "links" in thread_info:
            keeplinks_url = thread_info["links"].get("keeplinks", "")

        if not keeplinks_url:
            QMessageBox.warning(self, "Keeplinks URL Not Found",
                                f"No Keeplinks URL found for Thread-ID {thread_id}.")
            return

        # 2) Original BBCode from the editor:
        original_bbcode = self.process_bbcode_editor.get_text()
        if not original_bbcode.strip():
            QMessageBox.warning(self, "No BBCode", "No BBCode available for formatting.")
            return

        # 3) Call OpenAI to get the main "GPT-formatted" version
        formatted_bbcode = self.send_bbcode_to_gpt_api(original_bbcode, keeplinks_url, category_name)

        if not formatted_bbcode:
            QMessageBox.warning(self, "Formatting Failed",
                                "Could not receive a formatted template from the OpenAI API.")
            return

        # 4) Process images for fastpic.org upload (upload first image to fastpic.org)
        logging.info("🔄 Starting image processing step...")
        logging.info(f"📋 Original BBCode content length: {len(formatted_bbcode)}")
        logging.info(f"🤖 Bot available: {hasattr(self, 'bot') and self.bot is not None}")
        
        try:
            if hasattr(self, 'bot') and self.bot:
                logging.info("🖼️ Processing images for fastpic.org upload...")
                logging.info(f"📝 BBCode before processing: {formatted_bbcode[:200]}...")  # Show first 200 chars
                processed_bbcode = self.bot.process_images_in_content(formatted_bbcode)
                logging.info(f"📝 BBCode after processing: {processed_bbcode[:200]}...")  # Show first 200 chars
                logging.info(f"🔄 Content changed: {formatted_bbcode != processed_bbcode}")
                formatted_bbcode = processed_bbcode
            else:
                logging.warning("⚠️ Bot not available for image processing")
                if not hasattr(self, 'bot'):
                    logging.error("❌ self.bot attribute doesn't exist")
                elif self.bot is None:
                    logging.error("❌ self.bot is None")
        except Exception as e:
            logging.error(f"❌ Error processing images for fastpic.org: {e}")
            import traceback
            logging.error(f"❌ Traceback: {traceback.format_exc()}")
            # Continue with original content if image processing fails

        # 5) Build the link block (Keeplinks short link + direct host links):
        links_block = self.build_links_block(category_name, thread_title)

        # 6) Combine them: place the link block *after* the GPT main body, or you can do it before
        final_bbcode = formatted_bbcode.strip() + "\n\n" + links_block

        # 7) Show in the editor and save
        self.process_bbcode_editor.set_text(final_bbcode)

        # Also update self.process_threads so you don't lose it:
        self.process_threads[category_name][thread_title]['bbcode_content'] = final_bbcode
        self.save_process_threads_data()

        QMessageBox.information(self, "Template Updated",
                                "BBCode has been successfully updated with fastpic.org images + Keeplinks + direct links.")
        logging.info("BBCode updated with fastpic.org image upload and final link block on Proceed Template.")

    def get_keeplinks_url_from_backup(self, thread_id):
        """Retrieve the Keeplinks URL from the backup JSON based on the thread ID."""
        for thread_title, thread_data in self.backup_threads.items():
            if thread_data.get('thread_id') == thread_id:
                return thread_data.get('keeplinks_link')
        return None  # Return None if not found

    def replace_file_host_links_with_keeplinks(self, bbcode, keeplinks_url):
        """Replace file host links with the Keeplinks URL in the BBCode."""
        import re

        # Define a regex pattern to identify the file host links section
        pattern = r"Zitat:.*?(Nitroflare\.com|Turbobit\.net|Rapidgator\.net|Hotlink\.cc).*"

        # Replace the entire section with the Keeplinks link
        replacement = f"Zitat: [url]{keeplinks_url}[/url]"
        updated_bbcode = re.sub(pattern, replacement, bbcode, flags=re.DOTALL)

        return updated_bbcode

    def reload_thread_links(self):
        """Reload the thread links from the saved JSON file."""
        try:
            # Use user-specific path if logged in, otherwise fallback
            if self.user_manager.get_current_user():
                user_folder = self.user_manager.get_user_folder()
                file_path = os.path.join(user_folder, "process_threads.json")
            else:
                file_path = os.path.join(DATA_DIR, "process_threads.json")
            with open(file_path, 'r') as f:
                self.thread_links = json.load(f)
            logging.info(f"Thread links loaded successfully from {file_path}.")
        except FileNotFoundError:
            logging.warning(f"No saved thread links file found at {file_path}.")
            self.thread_links = {}
        except Exception as e:
            logging.error(f"Failed to reload thread links: {e}")
            self.thread_links = {}

    def upload_selected_process_threads(self):
        """رفع المواضيع المحددة إلى المضيفات مع تحكم Pause/Continue/Cancel."""
        try:
            # إنشاء وعرض نافذة التقدم
            self.upload_progress_dialog = UploadProgressDialog(self)
            self.upload_progress_dialog.show()

            # الحصول على الصفوف المحددة في جدول Process Threads
            selected_items = self.process_threads_table.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "تحذير", "يرجى اختيار موضوع واحد على الأقل للرفع.")
                return
            selected_rows = sorted(set(item.row() for item in selected_items))

            # إعداد dict للـ workers إذا لم توجد
            if not hasattr(self, 'upload_workers'):
                self.upload_workers = {}

            for row in selected_rows:
                # قراءة معلومات الموضوع
                thread_title = self.process_threads_table.item(row, 0).text()
                category_name = self.process_threads_table.item(row, 1).text()
                thread_id = self.process_threads_table.item(row, 2).text()
                thread_dir = self.get_sanitized_path(category_name, thread_id)

                # التحقق من وجود المجلد
                if not os.path.isdir(thread_dir):
                    QMessageBox.warning(self, "خطأ", f"لم يتم العثور على مجلد للموضوع '{thread_title}'.")
                    continue

                # التحقق من وجود ملفات داخل المجلد
                files_in_dir = [f for f in os.listdir(thread_dir)
                                if os.path.isfile(os.path.join(thread_dir, f))]
                if not files_in_dir:
                    QMessageBox.warning(
                        self, "خطأ",
                        f"لا توجد ملفات في المجلد للموضوع '{thread_title}'."
                    )
                    continue

                # تعطيل زر الرفع لمنع تشغيل متزامن
                self.process_upload_button.setEnabled(False)

                # تهيئة UploadWorker بالوسائط الصحيحة
                upload_worker = UploadWorker(
                    self.bot,  # كائن البوت
                    row,  # رقم الصف
                    thread_dir,  # مسار المجلد
                    thread_id,  # ID الموضوع
                    upload_hosts=self.active_upload_hosts,  # قائمة المضيفات المفعّلة

                )
                self.upload_workers[row] = upload_worker

                # ربط أزرار Pause/Continue/Cancel في الديالوج بالـ worker
                self.upload_progress_dialog.pause_clicked.connect(upload_worker.pause_uploads)
                self.upload_progress_dialog.continue_clicked.connect(upload_worker.resume_uploads)
                self.upload_progress_dialog.cancel_clicked.connect(upload_worker.cancel_uploads)

                # ربط إشارات التقدم والإنهاء بمعالجات الـ GUI
                upload_worker.host_progress.connect(self.handle_host_progress)
                upload_worker.upload_complete.connect(self.handle_upload_complete)
                upload_worker.upload_success.connect(self.on_upload_row_success)
                upload_worker.upload_error.connect(self.on_upload_row_error)
                upload_worker.finished.connect(lambda *_: self.process_upload_button.setEnabled(True))

                # **هذه الإضافة**: إعادة تمكين زرّ الرفع عند الانتهاء
                upload_worker.upload_complete.connect(lambda *_: self.process_upload_button.setEnabled(True))

                # بدء عملية الرفع
                upload_worker.start()

        except Exception as e:
            logging.error(f"Error starting upload: {e}", exc_info=True)
            QMessageBox.critical(self, "خطأ", f"فشل بدء الرفع: {e}")
            self.process_upload_button.setEnabled(True)

    def handle_host_progress(self, row, host_idx, progress, status, current_size, total_size):
        """Handle host progress signal from the upload worker and update the progress dialog."""
        host_name = self.get_host_name(host_idx)
        self.upload_progress_dialog.update_host_progress(
            host=host_name,
            progress=progress,
            status_msg=status,
            current_size=current_size,
            total_size=total_size
        )

    def handle_upload_complete(self, row, urls_dict):
        try:
            thread_title = self.process_threads_table.item(row, 0).text()
            category_name = self.process_threads_table.item(row, 1).text()
            thread_id = self.process_threads_table.item(row, 2).text()

            # 1) Retrieve existing thread_info
            if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
                thread_info = self.process_threads[category_name][thread_title]

                # 2) Pull out newly-uploaded host links
                rapidgator_links = urls_dict.get('rapidgator', [])
                backup_rg_urls = urls_dict.get('rapidgator-backup', [])
                if isinstance(backup_rg_urls, str):
                    backup_rg_urls = [backup_rg_urls]
                nitroflare_links = urls_dict.get('nitroflare', [])
                ddownload_links = urls_dict.get('ddownload', [])
                katfile_links = urls_dict.get('katfile', [])

                # 3) Preserve old Keeplinks if not overridden
                old_links = thread_info.get('links', {})
                old_keeplinks = old_links.get('keeplinks', '')
                new_keeplinks = urls_dict.get('keeplinks', '') or old_keeplinks

                # 4) Build merged links
                merged_links = {
                    'rapidgator.net': rapidgator_links,
                    'nitroflare.com': nitroflare_links,
                    'ddownload.com': ddownload_links,
                    'katfile.com': katfile_links,
                    'rapidgator-backup': backup_rg_urls,
                    'keeplinks': new_keeplinks,
                }

                # 5) Save back to thread_info
                thread_info['links'] = merged_links

                # 5a) Versions logic: update last version or append a new one
                versions_list = thread_info.setdefault('versions', [])
                if versions_list:
                    versions_list[-1]['links'] = merged_links
                else:
                    versions_list.append({
                        'links': merged_links,
                        'thread_id': thread_id,
                        'bbcode_content': thread_info.get('bbcode_content', ''),
                        'thread_url': thread_info.get('thread_url', ''),
                    })

                # 5b) Mark upload_status = True in both root and latest version
                thread_info['upload_status'] = True
                versions_list[-1]['upload_status'] = True

                # 6) Update the Process Threads table columns
                display_links = rapidgator_links or katfile_links
                self.process_threads_table.item(row, 3).setText("\n".join(display_links))
                self.process_threads_table.item(row, 4).setText("\n".join(backup_rg_urls))
                self.process_threads_table.item(row, 5).setText(new_keeplinks)


                # 7) Persist changes
                self.save_process_threads_data()

                # 8) Also reflect in backup_threads to keep them in sync
                backup_info = self.backup_threads.get(thread_title, {})
                backup_info['thread_id'] = thread_id
                backup_info['rapidgator_links'] = rapidgator_links
                backup_info['rapidgator_backup_links'] = backup_rg_urls
                backup_info['keeplinks_link'] = new_keeplinks

                backup_info['katfile_links'] = katfile_links
                self.backup_threads[thread_title] = backup_info
                self.save_backup_threads_data()
                self.populate_backup_threads_table()

                # 9) Refresh the Process Threads table so new color is applied
                self.populate_process_threads_table(self.process_threads)

            else:
                logging.warning(f"Thread '{thread_title}' not found in category '{category_name}' after upload.")
        except Exception as e:
            logging.error(f"Error in handle_upload_complete: {e}", exc_info=True)
            QMessageBox.critical(self, "Upload Error", str(e))

    def setup_upload_progress_bars(self, row):
        """Set up progress bars for each host with proper organization."""
        try:
            # First ensure we have the correct base columns
            current_cols = self.process_threads_table.columnCount()
            base_cols = 6  # Thread Title, Category, Thread ID, Rapidgator Links, RG Backup Link, Keeplinks Link

            # Add upload progress columns if they don't exist
            progress_cols = [
                ("Rapidgator Progress", "rapidgator-main"),
                ("Nitroflare Progress", "nitroflare"),
                ("DDownload Progress", "ddownload"),
                ("Katfile Progress", "katfile"),
                ("RG Backup Progress", "rapidgator-backup")
            ]

            # Add columns for progress
            for col_name, host in progress_cols:
                col_idx = self.process_threads_table.columnCount()
                self.process_threads_table.insertColumn(col_idx)
                header_item = QTableWidgetItem(col_name)
                self.process_threads_table.setHorizontalHeaderItem(col_idx, header_item)

                # Create progress bar widget
                pbar = QProgressBar()
                pbar.setMinimum(0)
                pbar.setMaximum(100)
                pbar.setValue(0)
                pbar.setTextVisible(True)
                pbar.setFormat("Waiting...")
                pbar.setAlignment(Qt.AlignCenter)
                pbar.setFixedHeight(20)

                # Set initial style
                pbar.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid #CCCCCC;
                        border-radius: 5px;
                        text-align: center;
                        color: black;
                        background-color: #F5F5F5;
                        margin: 2px;
                    }
                    QProgressBar::chunk {
                        background-color: #2196F3;
                        border-radius: 4px;
                    }
                """)

                # Create widget container for progress bar
                container = QWidget()
                layout = QVBoxLayout(container)
                layout.setContentsMargins(2, 2, 2, 2)
                layout.addWidget(pbar)

                self.process_threads_table.setCellWidget(row, col_idx, container)

            # Set column widths
            header = self.process_threads_table.horizontalHeader()
            for i in range(base_cols, self.process_threads_table.columnCount()):
                self.process_threads_table.setColumnWidth(i, 150)  # Fixed width for progress columns
                header.setSectionResizeMode(i, QHeaderView.Fixed)

        except Exception as e:
            logging.error(f"Error setting up progress bars: {str(e)}")

    def cleanup_upload_progress_bars(self, delay_ms=5000):
        """Clean up progress bars after upload with delay."""
        QTimer.singleShot(delay_ms, self._remove_progress_columns)

    def _remove_progress_columns(self):
        """Remove progress bar columns safely."""
        try:
            table = self.process_threads_table

            # Remove progress columns from right to left
            while table.columnCount() > 6:  # Keep the original columns
                table.removeColumn(table.columnCount() - 1)

            # Adjust column sizes
            table.resizeColumnsToContents()

        except Exception as e:
            logging.error(f"Error removing progress columns: {str(e)}")

    def update_host_progress(self, progress_bar, progress, status_msg, current_size=0, total_size=0, success=False,
                             error=False):
        """
        Update host progress bar with enhanced status tracking and visual feedback.
        """
        try:
            if not progress_bar:
                return

            # Update progress value
            progress_bar.setValue(progress)

            # Format size information
            def format_size(size):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if size < 1024:
                        return f"{size:.1f}{unit}"
                    size /= 1024
                return f"{size:.1f}TB"

            current_formatted = format_size(current_size)
            total_formatted = format_size(total_size)

            # Prepare status format
            if error:
                style = """
                    QProgressBar {
                        border: 1px solid #f44336;
                        border-radius: 5px;
                        text-align: center;
                        color: black;
                        background-color: #ffebee;
                        height: 24px;
                        margin: 2px;
                        padding: 2px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #f44336;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                          stop:0 #f44336, stop:1 #ef5350);
                    }
                """
                progress_bar.setFormat(f"Error: {status_msg} - {current_formatted}/{total_formatted}")

            elif success or progress == 100:
                style = """
                    QProgressBar {
                        border: 1px solid #4caf50;
                        border-radius: 5px;
                        text-align: center;
                        color: black;
                        background-color: #e8f5e9;
                        height: 24px;
                        margin: 2px;
                        padding: 2px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #4caf50;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                          stop:0 #4caf50, stop:1 #66bb6a);
                    }
                """
                progress_bar.setFormat(f"Complete: {progress}% - {current_formatted}/{total_formatted}")

            elif progress > 0:
                style = """
                    QProgressBar {
                        border: 1px solid #2196f3;
                        border-radius: 5px;
                        text-align: center;
                        color: black;
                        background-color: #e3f2fd;
                        height: 24px;
                        margin: 2px;
                        padding: 2px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #2196f3;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                          stop:0 #2196f3, stop:1 #64b5f6);
                    }
                """
                progress_bar.setFormat(f"{status_msg} - {progress}% - {current_formatted}/{total_formatted}")

            else:
                style = """
                    QProgressBar {
                        border: 1px solid #9e9e9e;
                        border-radius: 5px;
                        text-align: center;
                        color: black;
                        background-color: #f5f5f5;
                        height: 24px;
                        margin: 2px;
                        padding: 2px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #9e9e9e;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                          stop:0 #9e9e9e, stop:1 #bdbdbd);
                    }
                """
                progress_bar.setFormat(f"{status_msg} - {current_formatted}/{total_formatted}")

            # Apply style and make sure text is visible
            progress_bar.setStyleSheet(style)

            # Set tooltip with detailed status
            progress_bar.setToolTip(
                f"Status: {status_msg}\n"
                f"Progress: {progress}%\n"
                f"Current Size: {current_formatted}\n"
                f"Total Size: {total_formatted}"
            )

            # Force update
            progress_bar.repaint()
            QApplication.processEvents()

        except Exception as e:
            logging.error(f"Error updating progress bar: {str(e)}")

    def get_thread_row(self, thread_title):
        """Find the row index for a thread in the process threads table."""
        for row in range(self.process_threads_table.rowCount()):
            if self.process_threads_table.item(row, 0).text() == thread_title:
                return row
        return -1

    PROGRESS_STYLE_ACTIVE = """
        QProgressBar {
            border: 1px solid #2196F3;
            border-radius: 5px;
            text-align: center;
            height: 20px;
            margin: 2px;
            padding: 2px;
        }
        QProgressBar::chunk {
            background-color: #2196F3;
            border-radius: 4px;
        }
    """

    PROGRESS_STYLE_SUCCESS = """
        QProgressBar {
            border: 1px solid #4CAF50;
            border-radius: 5px;
            text-align: center;
            height: 20px;
            margin: 2px;
            padding: 2px;
        }
        QProgressBar::chunk {
            background-color: #4CAF50;
            border-radius: 4px;
        }
    """

    PROGRESS_STYLE_ERROR = """
        QProgressBar {
            border: 1px solid #f44336;
            border-radius: 5px;
            text-align: center;
            height: 20px;
            margin: 2px;
            padding: 2px;
        }
        QProgressBar::chunk {
            background-color: #f44336;
            border-radius: 4px;
        }
    """

    def create_upload_progress_bar(self, host_name):
        """Create a styled progress bar for upload tracking."""
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_bar.setFormat(f"{host_name}: %p% - %v/%m bytes")
        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 5px;
                text-align: center;
                height: 24px;
                background-color: #f0f0f0;
                margin: 2px;
                padding: 2px;
                font-size: 11px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #2196F3, stop:1 #64B5F6);
            }
        """)
        progress_bar.setAlignment(Qt.AlignCenter)
        progress_bar.setTextVisible(True)
        progress_bar.setFixedHeight(24)
        return progress_bar

    def update_upload_progress(self, row: int, host_idx: int, progress: int, status_msg: str,
                               current_size: int = 0, total_size: int = 0):
        """Update both table progress bar and detailed progress dialog"""
        try:
            # Update table progress bar
            if self.progress_handler:
                self.progress_handler.update_progress(row, host_idx, progress, status_msg,
                                                      current_size, total_size)

            # Update detailed progress dialog
            if self.upload_progress_dialog:
                host_name = self.get_host_name(host_idx)
                self.upload_progress_dialog.update_host_progress(
                    host=host_name,
                    progress=progress,
                    status_msg=status_msg,
                    current_size=current_size,
                    total_size=total_size
                )
        except Exception as e:
            logging.error(f"Error updating upload progress: {str(e)}")

    def get_host_name(self, host_idx: int) -> str:
        """Get host name from index - matches table columns"""
        hosts = [
            'rapidgator-main',
            'nitroflare',
            'ddownload',
            'katfile',
            'rapidgator-backup',
        ]
        return hosts[host_idx] if 0 <= host_idx < len(hosts) else 'unknown'

    def handle_upload_error(self, row: int, host_idx: int, error_msg: str):
        """Handle upload errors in the progress display."""
        if self.progress_handler:
            self.progress_handler.update_progress(
                row,
                host_idx,
                0,  # Reset progress
                f"Error: {error_msg}",
                error=True
            )

    def update_upload_status(self, row: int, host: str, current_part: int, total_parts: int, status: str):
        """Update status text for specific upload."""
        try:
            host_index = {
                'rapidgator': 0,
                'nitroflare': 1,
                'ddownload': 2,
                'katfile': 3,
                'mega': 4
            }.get(host.lower())

            if host_index is not None:
                start_col = self.process_threads_table.columnCount() - 4
                progress_bar = self.process_threads_table.cellWidget(row, start_col + host_index)
                if progress_bar:
                    if status.startswith("Error"):
                        progress_bar.setStyleSheet("""
                            QProgressBar {
                                border: 1px solid #f44336;
                                border-radius: 5px;
                                text-align: center;
                                height: 20px;
                                margin: 2px;
                                padding: 2px;
                            }
                            QProgressBar::chunk {
                                background-color: #f44336;
                                border-radius: 4px;
                            }
                        """)
                    progress_bar.setFormat(f"{host}: {status}")
                    progress_bar.setToolTip(f"Part {current_part}/{total_parts}")

                    # Update status bar
                    self.statusBar().showMessage(f"Uploading to {host}: {status}")

        except Exception as e:
            logging.error(f"Error updating upload status: {str(e)}")

    def on_upload_complete(self, success: bool, message: str, results: dict):
        """Handle completion of upload operation."""
        try:
            # Re-enable upload button
            self.process_upload_button.setEnabled(True)

            if success:
                # Process successful uploads
                for row, result in results.items():
                    thread_info = result.get('thread_info')
                    if thread_info:
                        # Update thread data
                        self.update_thread_links(
                            thread_info['category_name'],
                            thread_info['thread_title'],
                            result.get('urls', [])
                        )

                # Show success message
                QMessageBox.information(self, "Upload Complete",
                                        f"Successfully uploaded {len(results)} threads\n{message}")
            else:
                QMessageBox.warning(self, "Upload Status", message)

            self.statusBar().showMessage(message)

            # Cleanup upload columns after delay
            QTimer.singleShot(5000, self.cleanup_upload_columns)

        except Exception as e:
            logging.error(f"Error handling upload completion: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error completing upload: {str(e)}")
            self.process_upload_button.setEnabled(True)

    def cleanup_upload_columns(self):
        """Remove the upload progress columns after completion."""
        try:
            # Remove the upload progress columns
            num_cols = 4
            for _ in range(num_cols):
                last_col = self.process_threads_table.columnCount() - 1
                self.process_threads_table.removeColumn(last_col)
        except Exception as e:
            logging.error(f"Error cleaning up upload columns: {str(e)}")

    def upload_thread_files(self, category_name, thread_id, thread_title):
        """Enhanced version of upload_thread_files with proper progress tracking."""
        try:
            logging.info(f"Starting upload process for thread '{thread_title}'")
            folder_path = self.get_sanitized_path(category_name, thread_id)

            if not os.path.isdir(folder_path):
                error_msg = f"No files found for thread '{thread_title}'"
                logging.warning(error_msg)
                QMessageBox.warning(self, "No Files", error_msg)
                return

            files_to_upload = [
                os.path.join(folder_path, f) for f in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, f))
            ]

            if not files_to_upload:
                error_msg = f"No valid files to upload for thread '{thread_title}'"
                logging.warning(error_msg)
                QMessageBox.warning(self, "No Files", error_msg)
                return

            # Initialize progress tracking
            row = self.get_thread_row(thread_title)
            host_progress_bars = self.setup_upload_progress_bars(row)
            all_uploaded_urls = []
            mega_url = ''

            for file_path in files_to_upload:
                filename = os.path.basename(file_path)
                logging.info(f"Processing file: {filename}")

                # Handle each host's upload
                upload_results = {}

                # 1. Rapidgator
                rapidgator_url = self.handle_rapidgator_upload(file_path, row, host_progress_bars)
                if rapidgator_url:
                    upload_results['rapidgator'] = rapidgator_url
                    all_uploaded_urls.append(rapidgator_url)

                # 2. Nitroflare
                try:
                    self.update_host_progress(host_progress_bars['nitroflare'], 0, "Uploading...")
                    nitro_url = self.bot.upload_to_nitroflare(file_path)
                    if nitro_url:
                        upload_results['nitroflare'] = nitro_url
                        all_uploaded_urls.append(nitro_url)
                        self.update_host_progress(host_progress_bars['nitroflare'], 100, "Complete", success=True)
                    else:
                        self.update_host_progress(host_progress_bars['nitroflare'], 0, "Failed", error=True)
                except Exception as e:
                    self.update_host_progress(host_progress_bars['nitroflare'], 0, f"Error: {str(e)}", error=True)
                    logging.error(f"Nitroflare upload error: {str(e)}")

                # 3. DDownload
                try:
                    self.update_host_progress(host_progress_bars['ddownload'], 0, "Uploading...")
                    ddown_url = self.bot.upload_to_ddownload(file_path)
                    if ddown_url:
                        upload_results['ddownload'] = ddown_url
                        all_uploaded_urls.append(ddown_url)
                        self.update_host_progress(host_progress_bars['ddownload'], 100, "Complete", success=True)
                    else:
                        self.update_host_progress(host_progress_bars['ddownload'], 0, "Failed", error=True)
                except Exception as e:
                    self.update_host_progress(host_progress_bars['ddownload'], 0, f"Error: {str(e)}", error=True)
                    logging.error(f"DDownload upload error: {str(e)}")

                # 4. KatFile
                try:
                    self.update_host_progress(host_progress_bars['katfile'], 0, "Uploading...")
                    kat_url = self.bot.upload_to_katfile(file_path)
                    if kat_url:
                        upload_results['katfile'] = kat_url
                        all_uploaded_urls.append(kat_url)
                        self.update_host_progress(host_progress_bars['katfile'], 100, "Complete", success=True)
                    else:
                        self.update_host_progress(host_progress_bars['katfile'], 0, "Failed", error=True)
                except Exception as e:
                    self.update_host_progress(host_progress_bars['katfile'], 0, f"Error: {str(e)}", error=True)
                    logging.error(f"KatFile upload error: {str(e)}")

            # Generate Keeplinks if we have URLs
            keeplinks_url = None
            if all_uploaded_urls:
                try:
                    keeplinks_url = self.bot.send_to_keeplinks(all_uploaded_urls)
                    if keeplinks_url:
                        logging.info(f"Generated Keeplinks URL: {keeplinks_url}")
                except Exception as e:
                    logging.error(f"Error generating Keeplinks URL: {str(e)}")

            # Update thread data with all URLs
            if all_uploaded_urls:
                self.update_thread_data_and_ui(
                    category_name,
                    thread_title,
                    thread_id,
                    all_uploaded_urls,
                    keeplinks_url,
                )
                QMessageBox.information(
                    self,
                    "Upload Complete",
                    f"Successfully uploaded files for thread '{thread_title}'"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Upload Failed",
                    f"No files were successfully uploaded for thread '{thread_title}'"
                )

        except Exception as e:
            error_msg = f"Error uploading files: {str(e)}"
            logging.error(error_msg, exc_info=True)
            QMessageBox.critical(self, "Upload Error", error_msg)

    def on_upload_row_success(self, row: int):
        """Color the row BLUE on upload success."""
        theme = theme_manager.get_current_theme()
        bg_brush = QBrush(QColor(theme.INFO))
        fg_brush = QBrush(QColor(theme.TEXT_ON_PRIMARY))
        col_count = self.process_threads_table.columnCount()
        for col in range(col_count):
            item = self.process_threads_table.item(row, col)
            if item:
                item.setBackground(bg_brush)
                item.setForeground(fg_brush)

        # Remove local folder (existing logic)
        thread_title = self.process_threads_table.item(row, 0).text()
        category_name = self.process_threads_table.item(row, 1).text()
        thread_id = self.process_threads_table.item(row, 2).text()

        folder_path = self.get_sanitized_path(category_name, thread_id)
        try:
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                logging.info(f"Deleted local folder after successful upload: {folder_path}")
        except Exception as e:
            logging.error(f"Failed to remove folder '{folder_path}': {e}")

        self.statusBar().showMessage(f"Upload successful. Freed disk space for row {row}.")

        # --- NEW: set row_status='uploaded' in process_threads, then save ---
        if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
            self.process_threads[category_name][thread_title]['row_status'] = 'uploaded'
            self.save_process_threads_data()

    def on_upload_row_error(self, row: int, error_msg: str):
        """Color the row RED on upload error, set row_status='error'."""
        red_brush = QBrush(QColor("#FF9999"))
        col_count = self.process_threads_table.columnCount()
        for col in range(col_count):
            item = self.process_threads_table.item(row, col)
            if item:
                item.setBackground(red_brush)

        logging.error(f"Upload error on row {row}: {error_msg}")
        self.statusBar().showMessage(f"Upload error (row {row}): {error_msg}")

        # --- NEW: set row_status='error' in process_threads, then save ---
        category_name = self.process_threads_table.item(row, 1).text()
        thread_title = self.process_threads_table.item(row, 0).text()
        if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
            self.process_threads[category_name][thread_title]['row_status'] = 'error'
            self.save_process_threads_data()

    def update_thread_data_and_ui(self, category_name, thread_title, thread_id,
                                  uploaded_urls, keeplinks_url, backup_rg_urls=None):
        """Update thread data and UI immediately after upload completion."""
        try:


            # Update process_threads data
            if category_name in self.process_threads:
                thread_data = self.process_threads[category_name][thread_title]
                thread_data['links'] = {
                    'rapidgator.net': [url for url in uploaded_urls if 'rapidgator.net' in url],
                    'nitroflare.com': [url for url in uploaded_urls if 'nitroflare.com' in url],
                    'ddownload.com': [url for url in uploaded_urls if 'ddownload.com' in url],
                    'katfile.com': [url for url in uploaded_urls if 'katfile.com' in url],
                    'rapidgator-backup': list(backup_rg_urls) if backup_rg_urls else [],
                    'keeplinks': keeplinks_url,
                }

            # Update backup threads data, storing all Mega links as newline-separated
            self.backup_threads[thread_title] = {
                'thread_id': thread_id,
                'rapidgator_links': [url for url in uploaded_urls if 'rapidgator.net' in url],
                'rapidgator_backup_links': list(backup_rg_urls) if backup_rg_urls else [],
                'keeplinks_link': keeplinks_url,
            }

            # Save updated data
            self.save_process_threads_data()
            self.save_backup_threads_data()

            # Refresh UI components
            self.populate_process_threads_table(self.process_threads)
            self.populate_backup_threads_table()

            # Ensure the updated row is visible
            row = self.get_thread_row(thread_title)
            if row >= 0:
                self.process_threads_table.scrollToItem(
                    self.process_threads_table.item(row, 0)
                )

            logging.info(f"Thread data and UI updated for '{thread_title}'")

        except Exception as e:
            logging.error(f"Error updating thread data and UI: {str(e)}", exc_info=True)

    def send_bbcode_to_gpt_api(self, original_bbcode, keeplinks_url, category_name):
        """
        We want to:
          1) Preserve original text but remove old [url=...] links, any mention of 'Hoster:' lines, or passwords.
          2) If the top line is a title, turn it into [B][COLOR="SeaGreen"][SIZE="5"]Title[/SIZE][/COLOR][/B].
          3) Wrap entire post in [CENTER]...[/CENTER].
          4) Slightly compress overly large blank gaps (replace multiple blank lines with a single blank line).
          5) Use only [B], [I], [U], [CENTER], [QUOTE], [SPOILER], [SIZE="5"], [COLOR="Red"], [COLOR="SeaGreen"] tags.
          6) No Keeplinks or new links from ChatGPT.
        """

        openai_api_key = self.config.get('openai_api_key', '').strip()
        if not openai_api_key:
            logging.error("OpenAI API key is not configured.")
            return ''

        # The prompt:
        prompt = (
            "Du bist ein BBCode-Assistent. Halte dich strikt an folgende Vorgaben:\n\n"
            "1) Bewahre den originalen Text (Satzbau, Umlaute, Zeilenumbrüche) so weit wie möglich.\n"
            "2) Entferne ALLE alten Links ([url=...][/url] oder 'Hoster:' Zeilen oder Passwörter). "
            "   Lass keinerlei Verweise auf die alten Downloads übrig.\n"
            "3) Wenn das allererste, nicht-leere Textstück wie ein Titel aussieht, formatiere ihn: "
            "   [B][COLOR=\"SeaGreen\"][SIZE=\"5\"]Titel[/SIZE][/COLOR][/B].\n"
            "4) Alles in [CENTER]...[/CENTER] packen.\n"
            "5) Nutze nur diese Tags: [B], [I], [U], [CENTER], [QUOTE], [SPOILER], [SIZE=\"5\"], [COLOR=\"Red\"], [COLOR=\"SeaGreen\"].\n"
            "6) Komprimiere übermäßige Leerzeilen oder riesige Abstände in höchstens eine Leerzeile.\n"
            "7) Schreibe KEINE neuen Links, KEIN 'Keeplinks', KEINE zusätzlichen Host-Zeilen.\n"
            "8) Schreibe nichts auf Englisch. Bleibe beim deutschen Original.\n\n"
            f"Hier das Original-BBCode:\n{original_bbcode}\n"
            "Gib bitte NUR den finalen BBCode zurück, mit obigen Änderungen und KEINEN weiteren Anweisungen."
        )

        import requests
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_api_key}"
        }
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,  # Keep it literal
            "max_tokens": 2048
        }

        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get('choices', [])
            if not choices:
                logging.error("No responses from OpenAI API.")
                return ''
            assistant_message = choices[0]['message']['content'].strip()
            if not assistant_message:
                logging.error("OpenAI API returned an empty response.")
                return ''
            return assistant_message
        except requests.RequestException as e:
            logging.error(f"Error calling OpenAI API: {e}", exc_info=True)
            return ''

    def calculate_file_hash(self, file_path):
        """Calculate MD5 hash of file for duplicate detection."""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def is_file_already_uploaded(self, file_hash):
        """Check if file was already successfully uploaded."""
        return file_hash in getattr(self, '_uploaded_file_hashes', set())

    def mark_file_as_uploaded(self, file_hash):
        """Mark a file as successfully uploaded."""
        if not hasattr(self, '_uploaded_file_hashes'):
            self._uploaded_file_hashes = set()
        self._uploaded_file_hashes.add(file_hash)

    def format_size(self, size):
        """Format file size to human readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def update_thread_data(self, thread_title: str, urls: list, keeplinks_url: str):
        """Update thread data with new URLs, ensuring all Rapidgator and Mega links are included."""
        try:
            # Categorize URLs by host
            host_urls = {
                'rapidgator': [],
                'nitroflare': [],
                'ddownload': [],
                'katfile': [],
            }

            for url in urls:
                lower_url = url.lower()
                if 'rapidgator' in lower_url:
                    host_urls['rapidgator'].append(url)
                elif 'nitroflare' in lower_url:
                    host_urls['nitroflare'].append(url)
                elif 'ddownload' in lower_url:
                    host_urls['ddownload'].append(url)
                elif 'katfile' in lower_url:
                    host_urls['katfile'].append(url)

            # Update process_threads data
            for category in self.process_threads.values():
                if thread_title in category:
                    category[thread_title]['links'] = {
                        'keeplinks': keeplinks_url,
                        'rapidgator.net': host_urls['rapidgator'],
                        'nitroflare.com': host_urls['nitroflare'],
                        'ddownload.com': host_urls['ddownload'],
                        'katfile.com': host_urls['katfile'],
                    }

            # Update backup_threads data as lists, not single strings
            self.backup_threads[thread_title] = {
                'rapidgator_links': host_urls['rapidgator'],
                'keeplinks_link': keeplinks_url,
            }

            # Save updated data
            self.save_process_threads_data()
            self.save_backup_threads_data()

        except Exception as e:
            logging.error(f"Error updating thread data: {str(e)}", exc_info=True)

    def move_thread_to_backup(self, category_name, thread_title):
        """Move a completed thread to the backup section without overwriting updated multi-link data."""
        try:
            # Ensure the thread exists in process_threads
            if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
                thread_info = self.process_threads[category_name][thread_title]

                # If the backup already has this thread_title, merge carefully
                if thread_title in self.backup_threads:
                    backup_data = self.backup_threads[thread_title]
                    # Keep existing data and merge with new info
                    thread_info.update(backup_data)
                
                # Add to backup
                self.backup_threads[thread_title] = thread_info
                
                # Remove from process_threads
                del self.process_threads[category_name][thread_title]
                
                # Save changes
                self.save_process_threads_data()
                self.save_backup_threads_data()
                
                logging.info(f"Thread '{thread_title}' moved from {category_name} to backup")
                return True
        except Exception as e:
            logging.error(f"Error moving thread to backup: {str(e)}", exc_info=True)
            return False

    def move_thread_to_backup(self, category_name, thread_title):
        """Move a completed thread to the backup section without overwriting updated multi-link data."""
        try:
            # Ensure the thread exists in process_threads
            if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
                thread_info = self.process_threads[category_name][thread_title]

                # If the backup already has this thread_title, merge carefully
                if thread_title in self.backup_threads:
                    backup_data = self.backup_threads[thread_title]

                    # Merge only non-link fields so we don't overwrite multi-link arrays
                    for k, v in thread_info.items():
                        # Skip overwriting the multi-link keys
                        if k not in ['rapidgator_links', 'keeplinks_link', 'mega_link']:
                            backup_data[k] = v

                    self.backup_threads[thread_title] = backup_data
                else:
                    # No existing backup, store this info directly.
                    # If update_thread_data() was called before, thread_info should include all multi-links.
                    self.backup_threads[thread_title] = thread_info

                # Remove from process_threads
                del self.process_threads[category_name][thread_title]
                if not self.process_threads[category_name]:
                    del self.process_threads[category_name]

                # Save data and refresh UI
                self.save_process_threads_data()
                self.save_backup_threads_data()
                self.populate_process_threads_table(self.process_threads)
                self.populate_backup_threads_table()

                logging.info(f"Thread '{thread_title}' moved to backup successfully.")

        except Exception as e:
            logging.error(f"Error moving thread to backup: {str(e)}", exc_info=True)

    def populate_backup_threads_table(self):
        """Populate the Backup Threads table with all backed-up threads."""
        self.backup_threads_table.setRowCount(0)  # Clear existing rows

        for thread_title, thread_info in self.backup_threads.items():
            row_position = self.backup_threads_table.rowCount()
            self.backup_threads_table.insertRow(row_position)

            # Thread Title
            title_item = QTableWidgetItem(thread_title)
            title_item.setData(Qt.UserRole, thread_info.get('thread_url'))
            title_item.setForeground(Qt.blue)
            title_item.setToolTip("Double-click to open thread in browser")
            self.backup_threads_table.setItem(row_position, 0, title_item)

            # Thread ID
            thread_id_item = QTableWidgetItem(str(thread_info.get('thread_id', '')))
            self.backup_threads_table.setItem(row_position, 1, thread_id_item)

            # Rapidgator Links (list)
            rapidgator_links = thread_info.get('rapidgator_links', [])
            if isinstance(rapidgator_links, str):
                rapidgator_links = [rapidgator_links]
            rapidgator_links_text = "\n".join(rapidgator_links)
            rapidgator_item = QTableWidgetItem(rapidgator_links_text)

            # Retrieve stored status if any
            rapidgator_status = thread_info.get('rapidgator_status', None)

            if rapidgator_status == 'dead':
                # Dead links present
                self.set_backup_link_status_color(rapidgator_item, False)
                rapidgator_item.setToolTip("Some Rapidgator links are dead.")
            elif rapidgator_status == 'alive':
                # All links alive
                self.set_backup_link_status_color(rapidgator_item, True)
                rapidgator_item.setToolTip("All Rapidgator links are alive.")
            else:
                # No links or no status
                if rapidgator_links:
                    rapidgator_item.setBackground(QColor(255, 255, 255))
                    rapidgator_item.setData(Qt.UserRole, None)
                    rapidgator_item.setToolTip("Rapidgator links available, status not checked yet.")
                else:
                    rapidgator_item.setBackground(QColor(255, 255, 255))
                    rapidgator_item.setData(Qt.UserRole, None)
                    rapidgator_item.setToolTip("No Rapidgator links found.")

            self.backup_threads_table.setItem(row_position, 2, rapidgator_item)

            # Rapidgator Backup Links
            rg_backup_links = thread_info.get('rapidgator_backup_links', [])
            flat_links = []
            for link in rg_backup_links:
                if isinstance(link, list):
                    flat_links.extend(link)
                else:
                    flat_links.append(link)
            rg_backup_text = "\n".join(flat_links)
            rg_backup_item = QTableWidgetItem(rg_backup_text)
            self.backup_threads_table.setItem(row_position, 3, rg_backup_item)

            # Keeplinks Link (single string)
            keeplinks_link = thread_info.get('keeplinks_link', '')
            keeplinks_item = QTableWidgetItem(keeplinks_link)
            self.backup_threads_table.setItem(row_position, 4, keeplinks_item)

        # Adjust columns and rows to show all lines
        self.backup_threads_table.resizeColumnsToContents()
        self.backup_threads_table.resizeRowsToContents()

    def get_backup_threads_filepath(self):
        if self.user_manager.get_current_user():
            user_folder = self.user_manager.get_user_folder()
            os.makedirs(user_folder, exist_ok=True)
            return os.path.join(user_folder, "backup_threads.json")
        else:
            from utils.paths import get_data_folder
            data_dir = get_data_folder()
            return os.path.join(data_dir, "backup_threads.json")

    def save_backup_threads_data(self):
        try:
            if self.user_manager.get_current_user():
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                filename = os.path.join(user_folder, "backup_threads.json")
            else:
                data_dir = get_data_folder()
                os.makedirs(data_dir, exist_ok=True)
                filename = os.path.join(data_dir, "backup_threads.json")

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.backup_threads, f, ensure_ascii=False, indent=4)
            logging.info(f"Backup Threads data saved to {filename}.")
        except Exception as e:
            self.handle_exception("save_backup_threads_data", e)

    def load_backup_threads_data(self):
        try:
            filename = self.get_backup_threads_filepath()
            if not os.path.exists(filename):
                logging.warning(f"No saved Backup Threads data found: {filename}")
                return False

            with open(filename, 'r', encoding='utf-8') as f:
                self.backup_threads = json.load(f)

            # ונעדכן את הטבלה ב-UI
            self.populate_backup_threads_table()
            logging.info(f"Backup Threads data loaded from {filename}.")
            return True
        except Exception as e:
            self.handle_exception("load_backup_threads_data", e)
            return False

    # =================================================
    # דالة بترجع بيانات “Megathreads Process Threads” من data/
    # =================================================
    def load_megathreads_process_threads_data(self):
        try:
            # Use user-specific path if logged in, otherwise fallback
            if self.user_manager.get_current_user():
                user_folder = self.user_manager.get_user_folder()
                filename = os.path.join(user_folder, "megathreads_process_threads.json")
            else:
                data_dir = get_data_folder()
                filename = os.path.join(data_dir, "megathreads_process_threads.json")

            if not os.path.exists(filename):
                logging.warning(f"No saved Megathreads Process Threads data found: {filename}")
                return False

            with open(filename, 'r', encoding='utf-8') as f:
                self.megathreads_process_threads = json.load(f)

            logging.info(f"Megathreads Process Threads data loaded from {filename}.")
            return True
        except Exception as e:
            self.handle_exception("load_megathreads_process_threads_data", e)
            return False

    def update_thread_links(self, category_name, thread_title, new_links):
        """Update the links for a thread in the process_threads data structure."""
        if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
            self.process_threads[category_name][thread_title]['links'] = new_links
            self.save_process_threads_data()
            self.populate_process_threads_table(self.process_threads)
            logging.info(f"Updated links for thread '{thread_title}' in category '{category_name}'")
        else:
            logging.warning(f"Thread '{thread_title}' not found in category '{category_name}'")

    def show_process_threads_context_menu(self, position):
        menu = QMenu()
        
        # Add new actions
        open_browser_action = menu.addAction("Open Thread in Browser")
        copy_url_action = menu.addAction("Copy Thread URL")
        copy_title_action = menu.addAction("Copy Thread Title")
        menu.addSeparator()
        
        # Keep existing actions
        view_links_action = menu.addAction("View Links")
        retry_failed_action = menu.addAction("Retry Failed Uploads")
        remove_action = menu.addAction("Remove Selected Thread(s)")
        
        # Get the selected rows
        selected_rows = sorted(set(index.row() for index in self.process_threads_table.selectedIndexes()))
        if not selected_rows:
            return
            
        # Get the first selected row for single-selection actions
        first_row = selected_rows[0]
        
        # Get thread data
        thread_title_item = self.process_threads_table.item(first_row, 0)
        thread_title = thread_title_item.text() if thread_title_item else ""
        thread_url = thread_title_item.data(Qt.UserRole + 2) if thread_title_item else ""
        
        # Execute the menu and get the selected action
        action = menu.exec_(self.process_threads_table.viewport().mapToGlobal(position))
        if not action:
            return
            
        # Handle the selected action
        if action == open_browser_action and thread_url:
            webbrowser.open(thread_url)
            
        elif action == copy_url_action and thread_url:
            clipboard = QApplication.clipboard()
            clipboard.setText(thread_url)
            self.statusBar().showMessage("Thread URL copied to clipboard", 3000)
            
        elif action == copy_title_action and thread_title:
            clipboard = QApplication.clipboard()
            clipboard.setText(thread_title)
            self.statusBar().showMessage("Thread title copied to clipboard", 3000)
            
        elif action == view_links_action:
            for row in selected_rows:
                thread_title = self.process_threads_table.item(row, 0).text()
                category_name = self.process_threads_table.item(row, 1).text()
                self.view_links(thread_title, from_section='Process Threads', category=category_name)

        elif action == retry_failed_action:
            for row in selected_rows:
                if hasattr(self, 'upload_workers') and row in self.upload_workers:
                    worker = self.upload_workers[row]
                    worker.retry_failed_uploads(row)
                else:
                    QMessageBox.warning(self, "No Upload Worker",
                                     "No upload worker found for the selected thread(s). "
                                     "Please start an upload first.")

        elif action == remove_action:
            self.remove_selected_process_threads()

    def on_process_thread_selected(self, row, column):
        """
        Handle the selection of a thread in the Process Threads table.
        Displays the saved BBCode in the BBCode editor without fetching it again.
        """
        try:
            thread_title = self.process_threads_table.item(row, 0).text()
            category_name = self.process_threads_table.item(row, 1).text()

            # Retrieve thread information from process_threads
            thread_info = self.process_threads.get(category_name, {}).get(thread_title, {})
            bbcode_content = thread_info.get('bbcode_content')

            if bbcode_content:
                # Display the saved BBCode directly
                self.process_bbcode_editor.set_text(bbcode_content)
                logging.info(f"Displayed saved BBCode for thread '{thread_title}' in Process Threads.")
            else:
                # If BBCode is missing, inform the user (do not fetch)
                self.process_bbcode_editor.clear()
                QMessageBox.information(self, "BBCode Not Available",
                                        f"No BBCode available for thread '{thread_title}'.")
                logging.warning(f"BBCode not available for thread '{thread_title}' in category '{category_name}'.")
        except Exception as e:
            self.handle_exception(f"on_process_thread_selected for '{thread_title}' in '{category_name}'", e)

    def on_bbcode_content_changed(self):
        """
        Handle BBCode content changes in the advanced editor.
        Update the process_threads data structure with new content.
        """
        try:
            # Get the currently selected thread
            current_row = self.process_threads_table.currentRow()
            if current_row < 0:
                return  # No thread selected
            
            thread_title = self.process_threads_table.item(current_row, 0).text()
            category_name = self.process_threads_table.item(current_row, 1).text()
            
            # Get BBCode content from the advanced editor
            bbcode_content = self.process_bbcode_editor.get_text()
            
            # Update the process_threads data structure
            if category_name in self.process_threads and thread_title in self.process_threads[category_name]:
                self.process_threads[category_name][thread_title]['bbcode_content'] = bbcode_content
                # Save the updated data
                self.save_process_threads_data()
                logging.debug(f"BBCode content updated for thread '{thread_title}' in category '{category_name}'")
        
        except Exception as e:
            logging.error(f"Error in on_bbcode_content_changed: {e}")

    def on_reply_button_clicked(self):
        """
        Handle reply button click to post BBCode content to forum.
        """
        try:
            # Get the currently selected thread
            current_row = self.process_threads_table.currentRow()
            if current_row < 0:
                QMessageBox.information(self, "No Selection", "Please select a thread to reply to.")
                return

            thread_title = self.process_threads_table.item(current_row, 0).text()
            category_name = self.process_threads_table.item(current_row, 1).text()

            # Get BBCode content from the advanced editor
            bbcode_content = self.process_bbcode_editor.get_text()

            if not bbcode_content.strip():
                QMessageBox.information(self, "No Content", "Please enter BBCode content before posting.")
                return

            # Get thread_info and URL
            thread_info = self.process_threads.get(category_name, {}).get(thread_title, {})
            thread_url = thread_info.get('thread_url')

            if not thread_url:
                QMessageBox.warning(self, "No URL", f"No thread URL found for '{thread_title}'.")
                return

            # Confirm with user before posting
            reply = QMessageBox.question(
                self, 'Post Reply',
                f"Post BBCode reply to thread '{thread_title}'?\n\nContent preview:\n"
                f"{bbcode_content[:200]}{'...' if len(bbcode_content) > 200 else ''}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                # Post the reply using the bot
                success = self.bot.post_reply(thread_url, bbcode_content)

                if success:
                    # --- NEW: mark the data model ---
                    # 1) root flag
                    thread_info['post_status'] = True
                    # 2) versions logic
                    versions_list = thread_info.setdefault('versions', [])
                    if versions_list:
                        versions_list[-1]['post_status'] = True
                    else:
                        versions_list.append({
                            'thread_url': thread_info.get('thread_url', ''),
                            'thread_id': thread_info.get('thread_id', ''),
                            'thread_date': thread_info.get('thread_date', ''),
                            'links': thread_info.get('links', {}),
                            'upload_status': thread_info.get('upload_status', False),
                            'post_status': True,
                        })
                    # 3) persist to disk
                    self.save_process_threads_data()

                    # 4) refresh the table so populate_process_threads_table applies the green color
                    self.populate_process_threads_table(self.process_threads)

                    QMessageBox.information(self, "Success", f"Reply posted successfully to '{thread_title}'!")
                    logging.info(f"Successfully posted reply to thread '{thread_title}' in category '{category_name}'")
                else:
                    QMessageBox.warning(self, "Failed", f"Failed to post reply to '{thread_title}'.")
                    logging.error(f"Failed to post reply to thread '{thread_title}' in category '{category_name}'")

        except Exception as e:
            self.handle_exception("on_reply_button_clicked for thread", e)

    def mark_row_as_processed(self, row):
        """
        Mark a table row as processed by changing its background color to green.
        """
        try:
            for column in range(self.process_threads_table.columnCount()):
                item = self.process_threads_table.item(row, column)
                if item:
                    item.setBackground(QBrush(QColor(144, 238, 144)))  # Light green
        except Exception as e:
            logging.error(f"Error marking row as processed: {e}")

    def load_process_bbcode(self, thread_title, thread_url, category_name):
        try:
            html_content = self.bot.get_page_source(thread_url)
            if html_content:
                bbcode_content = self.html_to_bbcode(html_content)
                self.process_bbcode_editor.set_text(bbcode_content)
                self.process_threads[category_name][thread_title]['bbcode_content'] = bbcode_content
                self.save_process_threads_data()
            else:
                QMessageBox.warning(self, "Empty Content", "No content fetched from the thread.")
        except Exception as e:
            self.handle_exception(f"load_process_bbcode for '{thread_title}' in category '{category_name}'", e)

    def remove_selected_process_threads(self):
        """Remove selected threads from the Process Threads section."""
        selected_rows = sorted(set(index.row() for index in self.process_threads_table.selectedIndexes()), reverse=True)
        if not selected_rows:
            QMessageBox.information(self, "No Selection", "Please select at least one thread to remove.")
            return

        reply = QMessageBox.question(
            self, 'Remove Threads',
            "Are you sure you want to remove the selected thread(s)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for row in selected_rows:
                thread_title = self.process_threads_table.item(row, 0).text()
                category_name = self.process_threads_table.item(row, 1).text()
                thread_id = self.process_threads_table.item(row, 2).text()

                # Remove only from self.process_threads
                if category_name in self.process_threads:
                    self.process_threads[category_name].pop(thread_title, None)
                    if not self.process_threads[category_name]:
                        self.process_threads.pop(category_name)

                # Remove from processed_thread_ids if necessary
                self.bot.processed_thread_ids.discard(thread_id)

                # Remove from the table
                self.process_threads_table.removeRow(row)

            # Save the updated process threads data
            self.save_process_threads_data()
            logging.info("Removed selected threads from Process Threads section.")
            self.statusBar().showMessage(f'Removed {len(selected_rows)} thread(s) from Process Threads.')

    def save_megathreads_process_threads_data(self):
        try:
            # Use user-specific path if logged in, otherwise fallback
            if self.user_manager.get_current_user():
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                filename = os.path.join(user_folder, "megathreads_process_threads.json")
            else:
                from utils.paths import get_data_folder
                data_dir = get_data_folder()
                filename = os.path.join(data_dir, "megathreads_process_threads.json")

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.megathreads_process_threads, f, ensure_ascii=False, indent=4)
            logging.info(f"Megathreads Process Threads data saved to {filename}.")
        except Exception as e:
            self.handle_exception("save_megathreads_process_threads_data", e)

    def ensure_absolute_url(self, url):
        if not url:
            return url
        if url.startswith('/'):
            return self.bot.forum_url.rstrip('/') + url
        elif not url.lower().startswith('http'):
            return self.bot.forum_url.rstrip('/') + '/' + url.lstrip('/')
        return url

    def handle_new_threads(self, category_name, new_threads):
        """
        Handles new regular (non-megathread) threads discovered in a category:
        - Skips threads if thread_id is already in self.replied_thread_ids (so we never re-track those).
        - Adds new threads to `self.category_threads` for viewing in the Posts section.
        - Immediately adds them to `self.process_threads` as well, under a 'versions' key.
        - Fetches BBCode for each thread right away and stores it.
        - Copies bbcode_content, links, and thread_url to top-level keys in `process_threads`.
        - Saves process_threads data and the category-specific thread data immediately, ensuring persistence.
        - Displays the BBCode of the first newly added thread in both Posts and Proceed Threads sections immediately.
        """
        try:
            logging.info(f"Handling {len(new_threads)} new threads for category '{category_name}'.")

            # Make sure we have a dict for this category in category_threads
            if category_name not in self.category_threads:
                self.category_threads[category_name] = {}

            # Make sure we have a dict for this category in process_threads
            if category_name not in self.process_threads:
                self.process_threads[category_name] = {}

            processed_any = False
            first_new_thread_title = None
            first_bbcode_content = ''

            # Loop over each discovered thread
            for thread_id, thread_info in new_threads.items():
                # Extract data from the new dictionary structure
                thread_title = thread_info.get('thread_title', '')
                thread_url = thread_info.get('thread_url', '')
                thread_date = datetime.now().strftime("%d.%m.%Y")  # Current date since we're processing current threads
                file_hosts = thread_info.get('file_hosts', [])
                links_dict = thread_info.get('links', {})
                has_known_hosts = thread_info.get('has_known_hosts', False)
                html_content = thread_info.get('html_content', '')

                # Skip if any crucial info is missing
                if not all([thread_url, thread_title, thread_id]):
                    logging.warning(f"Incomplete thread info for '{thread_title}' (ID: {thread_id}). Skipping.")
                    continue
                
                # Log thread processing status
                hosts_info = f" with {len(file_hosts)} known hosts" if has_known_hosts else " (no known hosts)"
                logging.info(f"📄 Processing thread '{thread_title}'{hosts_info}")

                # NEW: Skip if thread_id is already in replied_thread_ids
                if thread_id in self.replied_thread_ids:
                    logging.info(
                        f"Skipping thread '{thread_title}' (ID: {thread_id}) "
                        "because it was already replied to."
                    )
                    continue

                # Ensure thread_url is absolute
                thread_url = self.ensure_absolute_url(thread_url)

                # Add to category_threads so it appears in "Posts" section
                self.category_threads[category_name][thread_title] = (
                    thread_url,
                    thread_date,
                    thread_id,
                    file_hosts
                )

                # Use stored HTML content to avoid double visit
                if html_content:
                    bbcode_content = self.html_to_bbcode(html_content)
                    logging.info(f"✅ Using stored HTML content for thread '{thread_title}' - NO DOUBLE VISIT!")
                else:
                    bbcode_content = "Could not fetch content."

                # Normalize links if any
                links = links_dict  # Use the links from the new thread structure
                normalized_links = self.normalize_rapidgator_links(links)

                # Build the version_data dict
                version_data = {
                    'thread_url': thread_url,
                    'thread_date': thread_date,
                    'thread_id': thread_id,
                    'file_hosts': file_hosts,
                    'links': normalized_links,
                    'bbcode_content': bbcode_content
                }

                # Store in process_threads: versions + top-level
                self.process_threads[category_name][thread_title] = {
                    'versions': [version_data],
                    'bbcode_content': bbcode_content,
                    'links': normalized_links,
                    'thread_url': thread_url
                }

                # Mark thread_id as processed (so we don't re-fetch in the same session)
                self.bot.processed_thread_ids.add(thread_id)
                # Save immediately to prevent data loss
                self.bot.save_processed_thread_ids()

                # Track if we at least processed one new thread
                if not processed_any:
                    processed_any = True
                    first_new_thread_title = thread_title
                    first_bbcode_content = bbcode_content

            # After adding all new threads, save data
            logging.info(f"💾 About to save process threads data - Current data size: {len(self.process_threads)}")
            for cat, threads in self.process_threads.items():
                logging.info(f"💾 Category '{cat}': {len(threads)} threads")
            
            self.save_process_threads_data()
            
            # Also save the category data so the Posts section persists across restarts
            self.save_category_data(category_name)

            # Refresh the Process Threads table view
            self.populate_process_threads_table(self.process_threads)

            # Display a popup if we actually added threads
            if new_threads:
                QMessageBox.information(
                    self,
                    "New Threads Detected",
                    f"{len(new_threads)} new thread(s) have been added in '{category_name}'."
                )
                logging.info(f"Added {len(new_threads)} new threads to Process Threads.")

            # If at least one new thread was successfully processed, immediately show its BBCode
            if processed_any and first_new_thread_title:
                # 1) Display in the Posts section editor
                self.bbcode_editor.setPlainText(first_bbcode_content)

                # 2) Switch to "Process Threads" tab
                self.sidebar.set_active_item_by_text("Process Threads")
                self.content_area.setCurrentIndex(2)

                # 3) Display in the Process Threads BBCode editor
                self.process_bbcode_editor.set_text(first_bbcode_content)

                logging.info(
                    f"Displayed BBCode for '{first_new_thread_title}' instantly in both sections."
                )

        except Exception as e:
            self.handle_exception(f"handle_new_threads for category '{category_name}'", e)

    def handle_new_threads_process_threads(self, category_name, new_threads):
        try:
            logging.info(f"Handling {len(new_threads)} new threads for Process Threads in category '{category_name}'.")

            if category_name not in self.process_threads:
                self.process_threads[category_name] = {}

            for thread_title, thread_info in new_threads.items():
                try:
                    thread_url, thread_date, thread_id, file_hosts = thread_info

                    # Validate thread information
                    if not all([thread_url, thread_date, thread_id]):
                        logging.warning(
                            f"Incomplete thread info for '{thread_title}' in category '{category_name}'. Skipping.")
                        continue

                    # Ensure thread_url is absolute
                    thread_url = self.ensure_absolute_url(thread_url)

                    # Retrieve links from the bot and normalize them
                    links = self.bot.thread_links.get(thread_title, {})
                    normalized_links = self.normalize_rapidgator_links(links)

                    # **Fetch and Convert BBCode Immediately**
                    logging.info(f"Fetching BBCode for thread '{thread_title}' in category '{category_name}'.")
                    html_content = self.bot.get_page_source(thread_url)
                    if html_content:
                        bbcode_content = self.html_to_bbcode(html_content)
                    else:
                        bbcode_content = "Could not fetch content."

                    # Add to Process Threads with Links and BBCode right away
                    self.process_threads[category_name][thread_title] = {
                        'thread_url': thread_url,
                        'thread_date': thread_date,
                        'thread_id': thread_id,
                        'file_hosts': file_hosts,
                        'links': normalized_links,
                        'bbcode_content': bbcode_content  # Ensure BBCode is saved immediately
                    }

                    # Mark thread as processed
                    self.bot.processed_thread_ids.add(thread_id)
                    # Save immediately to prevent data loss
                    self.bot.save_processed_thread_ids()

                    logging.debug(
                        f"Added thread '{thread_title}' to Process Threads with URL '{thread_url}', "
                        f"links: {normalized_links}, and BBCode fetched.")

                except Exception as thread_e:
                    self.handle_exception(
                        f"processing thread '{thread_title}' for Process Threads in category '{category_name}'",
                        thread_e)
                    continue  # Continue processing other threads

            # Populate the Process Threads table
            self.populate_process_threads_table(self.process_threads)

            # Save the updated process threads data
            self.save_process_threads_data()

            logging.info("Process Threads data saved after new threads were added.")

            if new_threads:
                QMessageBox.information(self, "New Threads Detected in Process Threads",
                                        f"New threads have been added in '{category_name}' to Process Threads.")
                logging.info(f"New threads added in '{category_name}' to Process Threads.")

        except Exception as e:
            self.handle_exception(f"handle_new_threads_process_threads for category '{category_name}'", e)

    def populate_process_threads_table(self, process_threads):
        """Populate the Process Threads table."""
        self.process_threads_table.setRowCount(0)

        # Flatten threads to a list for sorting
        flat_threads = []
        for category, threads in process_threads.items():
            for thread_title, thread_info in threads.items():
                # Get data from thread_info (handle both old and new formats)
                if 'versions' in thread_info and thread_info['versions']:
                    # New format: get latest version
                    latest_version = thread_info['versions'][-1]
                    thread_url = latest_version.get('thread_url', '')
                    thread_date = latest_version.get('thread_date', '')
                    thread_id = latest_version.get('thread_id', '')
                    links = latest_version.get('links', {})
                    # Get status from latest version
                    download_status = latest_version.get('download_status', False)
                    upload_status = latest_version.get('upload_status', False)
                    post_status = latest_version.get('post_status', False)
                else:
                    # Old format: data is directly in thread_info
                    thread_url = thread_info.get('thread_url', '')
                    thread_date = thread_info.get('thread_date', '')
                    thread_id = thread_info.get('thread_id', '')
                    links = thread_info.get('links', {})
                    # Get status from thread_info (initialize as False if not exists)
                    download_status = thread_info.get('download_status', False)
                    upload_status = thread_info.get('upload_status', False)
                    post_status = thread_info.get('post_status', False)

                flat_threads.append({
                    'category': category,
                    'thread_title': thread_title,
                    'thread_url': thread_url,
                    'thread_date': thread_date,
                    'thread_id': thread_id,
                    'links': links,
                    'download_status': download_status,
                    'upload_status': upload_status,
                    'post_status': post_status
                })

        # Sort threads by date if available (descending)
        flat_threads.sort(key=lambda x: x['thread_date'], reverse=True)

        self.process_threads_table.setColumnCount(6)
        self.process_threads_table.setHorizontalHeaderLabels([
            "Thread Title", "Category", "Thread ID",
            "Rapidgator Links", "RG Backup Link", "Keeplinks Link"
        ])

        for thread in flat_threads:
            row_position = self.process_threads_table.rowCount()
            self.process_threads_table.insertRow(row_position)

            # Determine row background color based on status
            download_status = thread.get('download_status', False)
            upload_status = thread.get('upload_status', False)
            post_status = thread.get('post_status', False)

            # 🔍 ENHANCED DEBUG: Log status values for debugging
            thread_title = thread.get('thread_title', 'Unknown')
            category_name = thread.get('category', 'Unknown')
            print(f"\n🔍 COLOR DEBUG - Thread: {thread_title} (Category: {category_name})")
            print(f"📊 Status Values - Download: {download_status} | Upload: {upload_status} | Post: {post_status}")

            # Determine status class name for CSS styling
            status_class = None
            status_tooltip = "Status: Download ○, Upload ○, Post ○"

            if post_status:  # All complete (green)
                status_class = "status-posted"
                status_tooltip = "✅ Status: Download ✓, Upload ✓, Post ✓ (COMPLETED)"
                print(f"🟢 APPLYING status-posted CSS class for {thread_title}")
            elif upload_status:  # Download + Upload complete (orange)
                status_class = "status-uploaded"
                status_tooltip = "🟡 Status: Download ✓, Upload ✓, Post ○ (UPLOADED)"
                print(f"🟠 APPLYING status-uploaded CSS class for {thread_title}")
            elif download_status:  # Only download complete (blue)
                status_class = "status-downloaded"
                status_tooltip = "🔵 Status: Download ✓, Upload ○, Post ○ (DOWNLOADED)"
                print(f"🔵 APPLYING status-downloaded CSS class for {thread_title}")
            else:  # Nothing complete (pending)
                status_class = "status-pending"
                status_tooltip = "⚪ Status: Download ○, Upload ○, Post ○ (PENDING)"
                print(f"⚪ APPLYING status-pending CSS class for {thread_title}")

            # Force logging to ensure it's visible
            logging.info(f"🎨 COLOR SYSTEM: {thread_title} -> CSS Class: {status_class} | Tooltip: {status_tooltip}")

            # Determine status string for filtering (without 'status-' prefix)
            status_str = status_class.replace('status-', '') if status_class else 'pending'
            
            title_item = QTableWidgetItem(thread['thread_title'])
            title_item.setData(Qt.UserRole, status_class)  # ← store CSS class here
            title_item.setData(Qt.UserRole + 1, status_str)  # ← if you still need string for filtering
            title_item.setData(Qt.UserRole + 2, thread['thread_url'])  # Store URL in different role
            title_item.setForeground(QColor(100, 149, 237))  # Cornflower blue - more visible in dark mode
            title_item.setToolTip(f"Click to open thread in browser\n{status_tooltip}")
            self.process_threads_table.setItem(row_position, 0, title_item)

            category_item = QTableWidgetItem(thread['category'])
            category_item.setData(Qt.UserRole, status_class)
            category_item.setData(Qt.UserRole + 1, status_str)
            self.process_threads_table.setItem(row_position, 1, category_item)

            thread_id_item = QTableWidgetItem(str(thread['thread_id']))
            thread_id_item.setData(Qt.UserRole, status_class)
            thread_id_item.setData(Qt.UserRole + 1, status_str)
            self.process_threads_table.setItem(row_position, 2, thread_id_item)

            # Apply background color for status-based styling using DIRECT STYLESHEET (more powerful than CSS)
            if status_class:
                # Define color mapping for different statuses - STRONGER COLORS for dark theme
                status_colors = {
                    'status-pending': "#404040",          # Dark gray - pending
                    'status-downloaded': "#0066CC",      # Strong blue - downloaded
                    'status-uploaded': "#FF8C00",        # Dark orange - uploaded
                    'status-posted': "#32CD32"           # Lime green - posted/completed
                }

                # Get the background color for this status
                bg_color = status_colors.get(status_class, "#FFFFFF")
                text_color = "#FFFFFF" if status_class != 'status-pending' else "#CCCCCC"

                # Apply DIRECT STYLESHEET to each item (overrides ALL CSS)
                item_stylesheet = f"background-color: {bg_color} !important; color: {text_color} !important;"

                # Apply to all items in this row with DIRECT stylesheet
                title_item.setData(Qt.UserRole + 1, item_stylesheet)  # Store for potential future use
                category_item.setData(Qt.UserRole + 1, item_stylesheet)
                thread_id_item.setData(Qt.UserRole + 1, item_stylesheet)

                # ALSO apply setBackground as backup
                bg_qcolor = QColor(bg_color)
                text_qcolor = QColor(text_color)
                background_brush = QBrush(bg_qcolor)
                text_brush = QBrush(text_qcolor)

                title_item.setBackground(background_brush)
                title_item.setForeground(text_brush)
                category_item.setBackground(background_brush)
                category_item.setForeground(text_brush)
                thread_id_item.setBackground(background_brush)
                thread_id_item.setForeground(text_brush)

                print(f"🎨 FORCE APPLIED: {status_class} -> BG: {bg_color}, Text: {text_color} on row {row_position}")
                logging.info(f"🎨 FORCE STYLING: {thread_title} -> {status_class} -> BG: {bg_color}")

            links = thread['links']
            # Rapidgator Links
            # Rapidgator Links أو –إذا مفيهوش– Katfile Links
            rapidgator_links = links.get('rapidgator.net', [])
            if isinstance(rapidgator_links, str):
                rapidgator_links = [rapidgator_links]

            if not rapidgator_links:
                # fallback لروابط Katfile
                katfile_links = links.get('katfile.com', [])
                if isinstance(katfile_links, str):
                    katfile_links = [katfile_links]
                rapidgator_links = katfile_links

            rapidgator_text = "\n".join(rapidgator_links)
            rapidgator_item = QTableWidgetItem(rapidgator_text)
            rapidgator_item.setData(Qt.UserRole, status_str)  # Store status string for filtering
            rapidgator_item.setData(Qt.UserRole + 1, status_class)  # Store status class for styling
            if status_class:
                rapidgator_item.setBackground(background_brush)
            self.process_threads_table.setItem(row_position, 3, rapidgator_item)

            # Rapidgator Backup Link
            rg_backup_links = links.get('rapidgator-backup', [])
            flat_backup = []
            for link in rg_backup_links:
                if isinstance(link, list):
                    flat_backup.extend(link)
                else:
                    flat_backup.append(link)
            rg_backup_text = "\n".join(flat_backup)
            rg_backup_item = QTableWidgetItem(rg_backup_text)
            rg_backup_item.setData(Qt.UserRole, status_str)
            rg_backup_item.setData(Qt.UserRole + 1, status_class)
            if status_class:
                rg_backup_item.setBackground(background_brush)
            self.process_threads_table.setItem(row_position, 4, rg_backup_item)

            # Keeplinks Link
            keeplinks_link = links.get('keeplinks', '')
            if isinstance(keeplinks_link, list):
                keeplinks_link = "\n".join(keeplinks_link)
            keeplinks_item = QTableWidgetItem(keeplinks_link)
            keeplinks_item.setData(Qt.UserRole, status_str)  # Store status string for filtering
            keeplinks_item.setData(Qt.UserRole + 1, status_class)  # Store status class for styling
            if status_class:
                keeplinks_item.setBackground(background_brush)
            self.process_threads_table.setItem(row_position, 5, keeplinks_item)



        self.process_threads_table.resizeColumnsToContents()
        self.process_threads_table.resizeRowsToContents()
        logging.info("Process Threads table populated successfully")

    def migrate_old_links_format(self):
        """Migrate old links format to new dictionary format."""
        try:
            for category in self.process_threads:
                for thread_title in self.process_threads[category]:
                    thread_data = self.process_threads[category][thread_title]
                    if 'links' in thread_data:
                        links = thread_data['links']
                        if isinstance(links, list):
                            # Convert old format to new
                            thread_data['links'] = {
                                'rapidgator.net': [link for link in links if 'rapidgator.net' in link],
                                'rapidgator-backup': [],
                                'keeplinks': ''
                            }

            # Save updated format
            self.save_process_threads_data()
        except Exception as e:
            logging.error(f"Error migrating links format: {str(e)}")

    def open_process_thread_url(self, row, column):
        """Open the thread URL in the default web browser when the Thread Title is clicked."""
        if column == 0:  # Ensure only clicks on the Thread Title column are handled
            thread_url = self.process_threads_table.item(row, column).data(Qt.UserRole + 2)  # URL is now in UserRole + 2
            if thread_url:
                webbrowser.open(thread_url)
                logging.info(f"Opened thread URL: {thread_url}")
            else:
                QMessageBox.warning(self, "URL Missing", "The selected thread does not have a valid URL.")
                logging.warning(f"Thread URL missing for row {row}.")

    def start_megathreads_tracking(self):
        indexes = self.megathreads_category_tree.selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select at least one megathread category to start tracking.")
            return
        self.start_monitoring_megathreads(indexes, mode='Track Once')

    def keep_tracking_megathreads(self):
        indexes = self.megathreads_category_tree.selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select at least one megathread category to keep tracking.")
            return
        self.start_monitoring_megathreads(indexes, mode='Keep Tracking')

    def start_monitoring_megathreads(self, indexes, mode='Track Once'):
        """بدء تتبع الميجاثريدز."""
        for index in indexes:
            item = self.megathreads_category_model.itemFromIndex(index)
            category_name = item.text()
            if category_name in self.megathreads_workers:
                QMessageBox.warning(
                    self, "Already Tracking",
                    f"Already tracking megathread category '{category_name}'."
                )
                continue

            # 1) خذ الفلاتر الفعلية المحولة من النسبية إلى المطلقة
            df_list = self.settings_tab.get_actual_date_filters()
            if not df_list:
                # Fallback to raw filters if no actual filters found
                raw_filters = self.settings_tab.get_date_filters()
                df_list = raw_filters if isinstance(raw_filters, list) else raw_filters.split(',')

            # 2) خذ رينج الصفحات من SettingsWidget برضه
            page_from, page_to = self.settings_tab.get_page_range()

            # 3) ابنِ الـ worker بنفس المعطيات
            worker = MegaThreadsWorkerThread(
                bot=self.bot,
                bot_lock=self.bot_lock,
                category_manager=self.megathreads_category_manager,
                category_name=category_name,
                date_filters=df_list,
                page_from=page_from,
                page_to=page_to,
                mode=mode,
                gui=self
            )

            # 4) وصل الإشارات وشغّل الـ thread
            worker.update_megathreads.connect(self.handle_new_megathreads_versions)
            worker.finished.connect(self.megathreads_monitoring_finished)
            self.megathreads_workers[category_name] = worker
            worker.start()

    def handle_new_megathreads_versions(self, category_name, new_versions):
        """
        Handle new Megathread versions:
        - For each main megathread, append the new version to the 'versions' list.
        - Keep only the last two versions.
        - Immediately save after adding.
        - Store bbcode_content and all data inside each version.
        - After adding each new version to process_threads, copy its fields to top-level keys for immediate UI refresh.
        - Then re-populate the process threads table to show updated BBCode instantly.
        """
        try:
            logging.info(f"🔄 Handling new megathreads versions for '{category_name}': {len(new_versions)} found.")
            
            # Log priority breakdown
            rapidgator_count = sum(1 for v in new_versions.values() if v.get('has_rapidgator'))
            katfile_count = sum(1 for v in new_versions.values() if v.get('has_katfile'))
            other_hosts_count = sum(1 for v in new_versions.values() if v.get('has_other_known_hosts'))
            manual_review_count = len(new_versions) - rapidgator_count - katfile_count - other_hosts_count
            
            logging.info(f"📊 Priority breakdown: 🥇 Rapidgator: {rapidgator_count}, 🥈 Katfile: {katfile_count}, 🥉 Other hosts: {other_hosts_count}, 📝 Manual review: {manual_review_count}")

            proceed_category_name = f"Megathreads_{category_name}"
            if proceed_category_name not in self.megathreads_process_threads:
                self.megathreads_process_threads[proceed_category_name] = {}

            if proceed_category_name not in self.process_threads:
                self.process_threads[proceed_category_name] = {}

            for main_thread_title, version_info in new_versions.items():
                actual_version_title = version_info.get('version_title')
                if not actual_version_title:
                    logging.warning(f"No version_title for '{main_thread_title}', skipping.")
                    continue

                # Log version details with priority info
                priority_score = version_info.get('priority_score', 0)
                post_date = version_info.get('post_date', 'Unknown')
                
                if version_info.get('has_rapidgator'):
                    logging.info(f"🥇 Processing RAPIDGATOR version: '{actual_version_title}' (Score: {priority_score}, Date: {post_date})")
                elif version_info.get('has_katfile'):
                    logging.info(f"🥈 Processing KATFILE version: '{actual_version_title}' (Score: {priority_score}, Date: {post_date})")
                elif version_info.get('has_other_known_hosts'):
                    logging.info(f"🥉 Processing KNOWN HOST version: '{actual_version_title}' (Score: {priority_score}, Date: {post_date})")
                else:
                    logging.info(f"📝 Processing MANUAL REVIEW version: '{actual_version_title}' (Score: {priority_score}, Date: {post_date})")

                new_version_data = {
                    'version_title': actual_version_title,
                    'thread_url': version_info.get('thread_url', ''),
                    'thread_date': version_info.get('thread_date', ''),
                    'thread_id': version_info.get('thread_id', ''),
                    'file_hosts': version_info.get('file_hosts', []),
                    'links': version_info.get('links', {}),
                    'bbcode_content': version_info.get('bbcode_content', ''),
                    'priority_score': priority_score,
                    'post_date': post_date,
                    'has_rapidgator': version_info.get('has_rapidgator', False),
                    'has_katfile': version_info.get('has_katfile', False),
                    'has_other_known_hosts': version_info.get('has_other_known_hosts', False)
                }

                # Append to megathreads_process_threads
                if main_thread_title not in self.megathreads_process_threads[proceed_category_name]:
                    self.megathreads_process_threads[proceed_category_name][main_thread_title] = {'versions': []}

                old_versions = self.megathreads_process_threads[proceed_category_name][main_thread_title]['versions']

                # Check if this version already exists or if it's a priority update
                if old_versions:
                    last_version = old_versions[-1]
                    last_version_title = last_version.get('version_title', '')
                    last_priority_score = last_version.get('priority_score', 0)
                    
                    if actual_version_title == last_version_title:
                        # Same version title, but check if priority improved
                        if priority_score > last_priority_score:
                            logging.info(f"⬆️ PRIORITY UPDATE: '{actual_version_title}' for '{main_thread_title}' - Score improved from {last_priority_score} to {priority_score}")
                            # Remove old version to replace with better one
                            old_versions.pop()
                        else:
                            # Not a new or better version, skip
                            logging.info(f"ℹ️ Version '{actual_version_title}' for '{main_thread_title}' is unchanged (Score: {priority_score}).")
                            continue
                    else:
                        logging.info(f"🆕 NEW VERSION: '{actual_version_title}' for '{main_thread_title}' (replacing '{last_version_title}')")

                # Append the new version
                self.megathreads_process_threads[proceed_category_name][main_thread_title]['versions'].append(
                    new_version_data)
                # Keep only two latest versions
                if len(self.megathreads_process_threads[proceed_category_name][main_thread_title]['versions']) > 2:
                    self.megathreads_process_threads[proceed_category_name][main_thread_title]['versions'].pop(0)

                # Also store in process_threads
                # Use version_title as key since each version is distinct
                self.process_threads[proceed_category_name][actual_version_title] = {
                    'versions': [new_version_data]
                }

                # **Immediate Update for BBCode Display:**
                # Copy latest version fields to top-level for immediate UI reflection
                # Take the last version from the 'versions' list (which is new_version_data)
                latest_version = new_version_data
                # Copy fields to top-level keys for immediate access by UI
                self.process_threads[proceed_category_name][actual_version_title][
                    'bbcode_content'] = latest_version.get('bbcode_content', '')
                self.process_threads[proceed_category_name][actual_version_title]['links'] = latest_version.get('links',
                                                                                                                {})
                self.process_threads[proceed_category_name][actual_version_title]['thread_url'] = latest_version.get(
                    'thread_url', '')
                # If you need any other fields at top-level do the same here

            # Save updated data immediately so it's visible without restart
            self.save_megathreads_process_threads_data()
            self.save_process_threads_data()

            # Refresh the Process Threads table to show the updated BBCode instantly
            self.populate_process_threads_table(self.process_threads)

            # If the currently selected megathread category matches the updated one, refresh Megathreads tree
            indexes = self.megathreads_category_tree.selectedIndexes()
            if indexes:
                selected_item = self.megathreads_category_model.itemFromIndex(indexes[0])
                selected_category_name = selected_item.text()
                if selected_category_name == category_name:
                    proceed_category_name = f"Megathreads_{category_name}"
                    self.populate_megathreads_tree_from_process_threads(proceed_category_name)

            # Create detailed success message
            success_msg = f"Successfully processed {len(new_versions)} version(s) from '{category_name}':\n\n"
            if rapidgator_count > 0:
                success_msg += f"🥇 {rapidgator_count} Rapidgator version(s) (highest priority)\n"
            if katfile_count > 0:
                success_msg += f"🥈 {katfile_count} Katfile version(s) (good quality)\n"
            if other_hosts_count > 0:
                success_msg += f"🥉 {other_hosts_count} other known host version(s)\n"
            if manual_review_count > 0:
                success_msg += f"📝 {manual_review_count} version(s) need manual review\n"
            success_msg += "\nAll versions are now visible in the Process Threads table."
            
            QMessageBox.information(self, "Megathread Versions Updated", success_msg)
            logging.info(f"✅ Successfully processed {len(new_versions)} megathread versions for '{category_name}' with priority-based selection")
        except Exception as e:
            self.handle_exception(f"handle_new_megathreads_versions for category '{category_name}'", e)

    def update_megathread_versions(self, proceed_category_name, main_thread_title, new_version_data):
        """
        Ensures only a genuinely new version is added for a given megathread,
        and maintains only the last two versions.
        """
        if proceed_category_name not in self.megathreads_process_threads:
            self.megathreads_process_threads[proceed_category_name] = {}

        existing_data = self.megathreads_process_threads[proceed_category_name].get(main_thread_title, {'versions': []})
        old_versions = existing_data.get('versions', [])

        actual_version_title = new_version_data.get('version_title', '')
        if old_versions:
            last_known_version_title = old_versions[-1].get('version_title', '')
            if actual_version_title == last_known_version_title:
                # Version unchanged, do nothing
                logging.info(
                    f"No new version for '{main_thread_title}': version '{actual_version_title}' same as last known.")
                return False

        # Append new version
        old_versions.append(new_version_data)
        # Keep only last two
        if len(old_versions) > 2:
            old_versions.pop(0)

        self.megathreads_process_threads[proceed_category_name][main_thread_title] = {'versions': old_versions}
        return True

    def megathreads_monitoring_finished(self, category_name):
        self.statusBar().showMessage(f'Megathreads monitoring finished for {category_name}.')
        logging.info(f"Megathreads monitoring thread finished for category '{category_name}'.")
        self.megathreads_workers.pop(category_name, None)

    def start_monitoring(self, indexes, mode='Track Once'):
        """Start monitoring selected categories."""
        for index in indexes:
            item = self.category_model.itemFromIndex(index)
            category_name = item.text()

            # لو بنعمل تتبع لنفس الكاتيجوري مرتين ما نكررش
            if category_name in self.category_workers:
                QMessageBox.warning(self, "Already Tracking",
                                    f"Already tracking category '{category_name}'.")
                continue

            # اجمع المعطيات من الواجهة - استخدم الفلاتر الفعلية المحولة
            df_list = self.settings_tab.get_actual_date_filters()
            if not df_list:
                # Fallback to raw filters if no actual filters found
                logging.info(f"⚠️ No actual date filters found for '{category_name}', using raw filters as fallback")
                raw_filters = self.settings_tab.get_date_filters()
                df_list = raw_filters if isinstance(raw_filters, list) else raw_filters.split(',') if raw_filters else []
            else:
                logging.info(f"📅 Using actual date filters for '{category_name}': {df_list}")
            
            # Convert list to comma-separated string for WorkerThread
            if isinstance(df_list, list):
                date_filter = ','.join(df_list)
            else:
                date_filter = df_list if df_list else ''
            
            logging.info(f"🎆 Final date filter string for '{category_name}': '{date_filter}'")

            # وخذ منهما أيضاً page_from و page_to كما سبق
            page_from, page_to = self.settings_tab.get_page_range()

            # 🔍 BOT HEALTH CHECK: Verify bot is responsive before creating worker
            logging.info(f"🔍 Checking bot health before starting tracking for '{category_name}'")
            try:
                # Test bot responsiveness
                if hasattr(self.bot, 'driver') and self.bot.driver:
                    current_title = self.bot.driver.title
                    logging.info(f"✅ Bot is responsive for '{category_name}' (current page: {current_title[:30]}...)")
                else:
                    logging.warning(f"⚠️ Bot driver may not be initialized for '{category_name}'")
            except Exception as bot_check_error:
                logging.error(f"⚠️ Bot health check failed for '{category_name}': {bot_check_error}")
                # Continue anyway - let the worker handle bot issues
        
            # 🔐 BOT LOCK STATUS CHECK: Ensure lock is not stuck from previous session
            logging.info(f"🔐 Checking bot_lock status before starting '{category_name}'")
            try:
                # Try to acquire and immediately release the lock to test if it's available
                lock_acquired = self.bot_lock.tryLock(1000)  # Try for 1 second
                if lock_acquired:
                    self.bot_lock.unlock()
                    logging.info(f"✅ Bot lock is available for '{category_name}'")
                else:
                    logging.warning(f"⚠️ Bot lock appears to be stuck - attempting recovery for '{category_name}'")
                    # Force unlock attempt (safer approach)
                    try:
                        self.bot_lock.unlock()
                        logging.info(f"🔓 Forced bot_lock unlock successful for '{category_name}'")
                    except:
                        logging.warning(f"⚠️ Could not force unlock bot_lock for '{category_name}' - worker may hang")
            except Exception as lock_check_error:
                logging.warning(f"⚠️ Bot lock status check failed for '{category_name}': {lock_check_error}")

            # ثم مرّر date_filter كسلسلة إلى WorkerThread
            worker = WorkerThread(
                bot=self.bot,
                bot_lock=self.bot_lock,
                category_manager=self.category_manager,
                category_name=category_name,
                date_filters=date_filter,
                page_from=page_from,
                page_to=page_to,
                mode=mode
            )

            # 2) شبّك الإشارات
            worker.update_threads.connect(self.handle_new_threads)
            worker.finished.connect(self.monitoring_finished)

            # 3) خزّنه علشان ما يتمش حذفه من الـ Python GC
            self.category_workers[category_name] = worker

            # 4) أطلق الثريد بالخلفية
            worker.start()

            # رسالة حالة في الـ status bar
            self.statusBar().showMessage(f'Started monitoring category "{category_name}".')
            logging.info(f"Started monitoring category '{category_name}'.")

    def add_category(self):
        """Add a new category."""
        text, ok = QInputDialog.getText(self, 'Add Category', 'Enter category name:')
        if ok and text:
            url, ok_url = QInputDialog.getText(self, 'Add Category', 'Enter category URL:')
            if ok_url and url:
                self.category_manager.add_category(text, url)
                self.populate_category_tree(load_saved=False)
                QMessageBox.information(self, "Category Added", f"Category '{text}' added successfully.")
                logging.info(f"Added new category '{text}' with URL '{url}'.")
            else:
                QMessageBox.warning(self, "Invalid URL", "Category URL cannot be empty.")
        else:
            QMessageBox.warning(self, "Invalid Name", "Category name cannot be empty.")

    def remove_categories(self, indexes):
        """Remove selected categories."""
        categories_to_remove = [self.category_model.itemFromIndex(index).text() for index in indexes]
        reply = QMessageBox.question(
            self, 'Remove Categories',
            f"Are you sure you want to remove the selected category(ies): {', '.join(categories_to_remove)}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for category_name in categories_to_remove:
                self.category_manager.remove_category(category_name)
                if category_name in self.category_workers:
                    worker = self.category_workers.pop(category_name)
                    worker.stop()
                    worker.wait()
                    logging.info(f"Stopped worker thread for category '{category_name}'.")
            self.populate_category_tree(load_saved=False)
            self.thread_list.clear()
            self.bbcode_editor.clear()
            self.statusBar().showMessage("Selected categories removed.")
            logging.info(f"Removed categories: {', '.join(categories_to_remove)}.")

    def stop_monitoring(self, indexes):
        """Stop monitoring selected categories."""
        categories_to_stop = [self.category_model.itemFromIndex(index).text() for index in indexes]
        
        for category_name in categories_to_stop:
            worker = self.category_workers.pop(category_name, None)
            if worker:
                logging.info(f"⛔ Stopping worker for category '{category_name}'")
                
                try:
                    # 🔌 DISCONNECT SIGNALS: Prevent signal conflicts after restart
                    try:
                        worker.update_threads.disconnect()
                        worker.finished.disconnect()
                        logging.info(f" Disconnected signals for worker '{category_name}'")
                    except Exception as disconnect_error:
                        logging.warning(f" Could not disconnect signals for '{category_name}': {disconnect_error}")
                    
                    # Stop the worker
                    worker.stop()
                    
                    # Wait for worker to stop with increased timeout
                    if not worker.wait(8000):  # Wait max 8 seconds (5+3 from worker timeout)
                        logging.warning(f" Worker for '{category_name}' didn't stop gracefully, forcing termination")
                        worker.terminate()
                        worker.wait(2000)  # Wait 2 seconds for termination
                        
                        logging.info(f" Successfully stopped monitoring for category '{category_name}'")
                        
                except Exception as e:
                    logging.error(f" Error stopping worker for '{category_name}': {e}")
                    # Force terminate if there's an error
                    try:
                        worker.terminate()
                    except:
                        pass
        
        self.statusBar().showMessage(f"Stopped monitoring selected categories.")
        logging.info(f"🏁 Finished stopping categories: {', '.join(categories_to_stop)}")

    def start_tracking(self):
        """Start tracking selected categories."""
        indexes = self.category_tree.selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select at least one category to start tracking.")
            return
        self.start_monitoring(indexes, mode='Keep Tracking')

    def monitoring_finished(self, category_name):
        """Handle the completion of a worker thread."""
        self.statusBar().showMessage(f'Monitoring finished for {category_name}.')
        logging.info(f"Monitoring thread finished for category '{category_name}'.")

    def view_links(self, thread_title, from_section='Posts', category=None):
        if from_section == 'Posts':
            threads = self.category_threads.get(self.current_category, {})
            thread_info = threads.get(thread_title)
            if thread_info:
                links_dict = self.bot.thread_links.get(thread_title, {})
            else:
                QMessageBox.warning(self, "Error", "Thread information not found in Posts section.")
                return
        elif from_section == 'Process Threads':
            if category is None:
                QMessageBox.warning(self, "Error", "Category information is missing for Process Threads.")
                return
            thread_info = self.process_threads.get(category, {}).get(thread_title)
            if thread_info:
                links_dict = thread_info.get('links', {})
            else:
                QMessageBox.warning(self, "Error", "Thread information not found in Process Threads section.")
                return
        else:
            QMessageBox.warning(self, "Error", "Unknown section.")
            return

        if links_dict:
            # Flatten nested lists so dialog receives plain list of strings
            clean_links = {}
            for host, urls in links_dict.items():
                if isinstance(urls, (list, tuple)):
                    flat = []
                    for u in urls:
                        if isinstance(u, (list, tuple)):
                            flat.extend(map(str, u))
                        else:
                            flat.append(str(u))
                    clean_links[host] = flat
                else:
                    clean_links[host] = [str(urls)]

            dialog = LinksDialog(thread_title, clean_links, parent=self)
            dialog.exec_()
        else:
            # إضافة خيارات جديدة للـ threads الفاضية
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("No Links Found")
            msg_box.setText(f"No links found for '{thread_title}'.\n\nWhat would you like to do?")
            
            # إضافة أزرار مخصصة
            add_link_btn = msg_box.addButton("Add Manual Link", QMessageBox.ActionRole)
            create_folder_btn = msg_box.addButton("Create Download Folder", QMessageBox.ActionRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.RejectRole)
            
            msg_box.setDefaultButton(add_link_btn)
            msg_box.exec_()
            
            clicked_button = msg_box.clickedButton()
            if clicked_button == add_link_btn:
                self.add_manual_link(thread_title, from_section, category)
            elif clicked_button == create_folder_btn:
                self.create_manual_folder(thread_title, from_section, category)

    def add_manual_link(self, thread_title, from_section, category):
        """Allow user to manually add a download link for a thread."""
        from PyQt5.QtWidgets import QInputDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QDialog
        
        # Create custom dialog for adding manual link
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Add Manual Link - {thread_title}")
        dialog.setModal(True)
        dialog.resize(500, 200)
        
        layout = QVBoxLayout(dialog)
        
        # Thread title label
        title_label = QLabel(f"Thread: {thread_title}")
        title_label.setStyleSheet("font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # Host selection
        host_layout = QHBoxLayout()
        host_layout.addWidget(QLabel("File Host:"))
        host_combo = QComboBox()
        # Populate combo with the currently active upload hosts so user settings
        # are respected. Fall back to common defaults if list is empty.
        combo_hosts = [
            h if h != "rapidgator" else "rapidgator.net" for h in self.active_upload_hosts
        ]
        if not combo_hosts:
            combo_hosts = ["rapidgator.net", "katfile.com", "nitroflare.com", "ddownload.com"]
        if "rapidgator-backup" in self.active_upload_hosts and "rapidgator-backup" not in combo_hosts:
            combo_hosts.append("rapidgator-backup")
        host_combo.addItems(combo_hosts + ["other"])
        host_layout.addWidget(host_combo)
        layout.addLayout(host_layout)
        
        # Link input
        link_layout = QHBoxLayout()
        link_layout.addWidget(QLabel("Download Link:"))
        link_input = QLineEdit()
        link_input.setPlaceholderText("Enter the download link here...")
        link_layout.addWidget(link_input)
        layout.addLayout(link_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        add_btn = QPushButton("Add Link")
        cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(add_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Connect buttons
        def add_link():
            host = host_combo.currentText()
            link = link_input.text().strip()
            if not link:
                QMessageBox.warning(dialog, "Invalid Input", "Please enter a download link.")
                return
            
            # Add link to thread data
            if from_section == 'Process Threads' and category:
                if category not in self.process_threads:
                    self.process_threads[category] = {}
                if thread_title not in self.process_threads[category]:
                    self.process_threads[category][thread_title] = {'links': {}}
                
                # Add the link
                if 'links' not in self.process_threads[category][thread_title]:
                    self.process_threads[category][thread_title]['links'] = {}
                if host not in self.process_threads[category][thread_title]['links']:
                    self.process_threads[category][thread_title]['links'][host] = []
                
                self.process_threads[category][thread_title]['links'][host].append(link)
                
                # Save data
                self.save_process_threads_data()
                
                # Refresh UI to show the manual link immediately
                self.populate_process_threads_table(self.process_threads)
                
                QMessageBox.information(dialog, "Success", f"Link added successfully to {host}!")
                logging.info(f"Manual link added for thread '{thread_title}' in category '{category}': {host} -> {link}")
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "Error", "Could not add link to this thread.")
        
        add_btn.clicked.connect(add_link)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec_()
    
    def create_manual_folder(self, thread_title, from_section, category):
        """Create a download folder for manually downloaded files using thread_id for consistent naming."""
        import os
        from PyQt5.QtWidgets import QFileDialog
        
        try:
            # Get thread_id from process_threads data structure
            thread_id = None
            if from_section == 'Process Threads' and category:
                thread_info = self.process_threads.get(category, {}).get(thread_title, {})
                if thread_info:
                    # Try to get thread_id from versions or direct storage
                    versions = thread_info.get('versions', [])
                    if versions:
                        thread_id = versions[-1].get('thread_id')  # Get from latest version
                    else:
                        thread_id = thread_info.get('thread_id')  # Direct storage
            
            if not thread_id:
                QMessageBox.warning(self, "Error", "Could not retrieve thread ID for folder creation.")
                return
            
            # Get download path from settings
            download_path = self.config.get('download_dir', os.path.expanduser('~/Downloads'))
            
            # Create folder path using category and thread_id (matching automatic downloads)
            folder_path = os.path.join(download_path, category, str(thread_id))
            
            # Create folder if it doesn't exist
            os.makedirs(folder_path, exist_ok=True)
            
            # Ask user if they want to open the folder
            reply = QMessageBox.question(
                self,
                "Folder Created",
                f"Manual download folder created at:\n{folder_path}\n\nWould you like to open the folder now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                # Open folder in file explorer
                if os.name == 'nt':  # Windows
                    os.startfile(folder_path)
                elif os.name == 'posix':  # macOS and Linux
                    os.system(f'open "{folder_path}"' if sys.platform == 'darwin' else f'xdg-open "{folder_path}"')
            
            # Update thread data to mark as "manual download"
            if from_section == 'Process Threads' and category:
                if category not in self.process_threads:
                    self.process_threads[category] = {}
                if thread_title not in self.process_threads[category]:
                    self.process_threads[category][thread_title] = {}
                
                # Mark as manual download and update folder path
                self.process_threads[category][thread_title]['manual_download'] = True
                self.process_threads[category][thread_title]['download_folder'] = folder_path
                
                # Add manual link entry to links dictionary
                if 'links' not in self.process_threads[category][thread_title]:
                    self.process_threads[category][thread_title]['links'] = {}
                self.process_threads[category][thread_title]['links']['manual'] = [f'Manual folder: {folder_path}']
                
                # Save data
                self.save_process_threads_data()
                
                # Refresh UI to show the manual folder/link immediately
                self.populate_process_threads_table(self.process_threads)
                
                logging.info(f"Manual download folder created for thread '{thread_title}' (ID: {thread_id}) in category '{category}': {folder_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create download folder:\n{str(e)}")
            logging.error(f"Failed to create manual download folder for '{thread_title}': {e}")

    def fetch_thread_content(self, item):
        """Fetch HTML content of the selected thread, convert to BBCode, and display in the editor."""
        thread_title = item.data(Qt.UserRole + 2)  # Retrieve actual thread_title
        thread_url = item.data(Qt.UserRole)
        logging.debug(f"Fetch action triggered for thread: {thread_title}, URL: {thread_url}")

        if thread_url:
            # Fetch and display the thread content
            self.load_thread_content(thread_title, thread_url)
        else:
            QMessageBox.warning(self, "Invalid Thread", "Thread URL is missing.")
            logging.warning(f"Thread URL missing for '{thread_title}'.")

    def load_thread_content(self, thread_title, thread_url):
        try:
            logging.debug(f"Loading content for thread: {thread_title}, URL: {thread_url}")
            # Fetch the HTML content using the bot
            html_content = self.bot.get_page_source(thread_url)
            logging.debug(f"Fetched HTML content for thread '{thread_title}'.")

            if html_content:
                # Convert HTML to BBCode
                bbcode_content = self.html_to_bbcode(html_content)
                logging.debug(f"Converted HTML to BBCode for thread '{thread_title}'.")

                # Display BBCode in the editor
                self.bbcode_editor.setPlainText(bbcode_content)
                logging.info(f"Displayed BBCode for thread '{thread_title}' in editor.")

                # Save BBCode to process_threads
                if self.current_category and thread_title in self.process_threads.get(self.current_category, {}):
                    self.process_threads[self.current_category][thread_title]['bbcode_content'] = bbcode_content
                    self.save_process_threads_data()
                    logging.info(f"Saved BBCode for thread '{thread_title}' in category '{self.current_category}'.")
                else:
                    logging.warning(
                        f"Thread '{thread_title}' not found in process_threads for category '{self.current_category}'.")
            else:
                QMessageBox.warning(self, "Empty Content", "No content fetched from the thread.")
                logging.warning(f"No HTML content fetched for thread '{thread_title}'.")
        except Exception as e:
            self.handle_exception(f"load_thread_content for '{thread_title}'", e)

    def html_to_bbcode(self, html_content):
        """Convert HTML content to BBCode."""
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove unnecessary elements
        for element in soup(['script', 'style', 'head', 'title', 'meta', '[document]']):
            element.decompose()

        # Use regex to find divs with id starting with 'post_message_'
        main_content = soup.find('div', id=re.compile(r'^post_message_'))

        if not main_content:
            logging.warning("Main content not found in HTML. Available divs:")
            for div in soup.find_all('div'):
                logging.warning(f"Div found with classes: {div.get('class')}, id: {div.get('id')}")
            return "Could not extract main content."

        # Initialize BBCode string
        bbcode = ""

        # Recursive function to traverse and convert HTML to BBCode
        def traverse(node):
            nonlocal bbcode
            if isinstance(node, NavigableString):
                # Replace multiple spaces and newlines with single space
                text = re.sub(r'\s+', ' ', node)
                bbcode += text
            elif node.name in ['b', 'strong']:
                bbcode += '[B]'
                for child in node.children:
                    traverse(child)
                bbcode += '[/B]'
            elif node.name in ['i', 'em']:
                bbcode += '[I]'
                for child in node.children:
                    traverse(child)
                bbcode += '[/I]'
            elif node.name == 'u':
                bbcode += '[U]'
                for child in node.children:
                    traverse(child)
                bbcode += '[/U]'
            elif node.name == 'a':
                href = node.get('href', '')
                if href:
                    # Normalize the link before adding
                    normalized_href = self.normalize_link(href)
                    # Only add the link itself
                    bbcode += normalized_href + '\n'
            elif node.name == 'img':
                src = node.get('src', '')
                bbcode += f'[IMG]{src}[/IMG]'
            elif node.name == 'center' or (node.name == 'div' and node.get('align') == 'center'):
                bbcode += '[CENTER]'
                for child in node.children:
                    traverse(child)
                bbcode += '[/CENTER]'
            elif node.name == 'blockquote':
                # For blockquote, add the quote content
                bbcode += '[QUOTE]'
                for child in node.children:
                    traverse(child)
                bbcode += '[/QUOTE]'
            elif node.name in ['code', 'pre']:
                bbcode += '[CODE]'
                for child in node.children:
                    traverse(child)
                bbcode += '[/CODE]'
            elif node.name == 'div' and 'spoiler' in (node.get('class') or []):
                bbcode += '[SPOILER]'
                for child in node.children:
                    traverse(child)
                bbcode += '[/SPOILER]'
            elif node.name == 'br':
                bbcode += '\n'
            elif node.name == 'p':
                bbcode += '\n\n'
            elif node.name == 'table':
                # Optionally handle tables if needed
                for row in node.find_all('tr'):
                    row_text = ' | '.join(cell.get_text(strip=True) for cell in row.find_all(['td', 'th']))
                    bbcode += f"{row_text}\n"
            else:
                # For other tags, traverse their children
                for child in node.children:
                    traverse(child)

        traverse(main_content)

        # Now handle replacing specific text
        # Replace "Zitat: Download über Keeplinks..." with the extracted link
        download_links = main_content.find_all('a')
        for link in download_links:
            href = link.get('href', '')
            if href:
                # Normalize the link before using it
                normalized_href = self.normalize_link(href)
                # Replace the specific text with the href link
                bbcode = re.sub(r'Zitat: Download über Keeplinks.*?', normalized_href, bbcode, count=1)

        # Remove trailing whitespaces and extra newlines
        bbcode = re.sub(r'\s+\n', '\n', bbcode).strip()

        return bbcode

    def select_all_threads(self):
        if not self.current_category:
            return

        thread_list_widget = self.thread_list
        thread_list_widget.selectAll()

    def copy_selected_threads(self):
        if not self.current_category:
            return

        thread_list_widget = self.thread_list
        selected_items = thread_list_widget.selectedItems()
        if not selected_items:
            return

        copied_text = []
        for item in selected_items:
            copied_text.append(item.text())

        if copied_text:
            QApplication.clipboard().setText("\n".join(copied_text))
            self.statusBar().showMessage(f'Copied {len(copied_text)} thread titles to clipboard')

    def paste_threads(self):
        # Placeholder for paste functionality
        self.statusBar().showMessage('Paste functionality not implemented')

    def save_data(self):
        """Save thread data to a JSON file, including links."""
        if not self.current_category:
            QMessageBox.warning(self, "No Category Selected", "Please select a category first.")
            return
        category_name = self.current_category
        threads = self.category_threads.get(category_name, {})
        if not threads:
            QMessageBox.information(self, "No Data", "There are no threads to save.")
            return
        sanitized_name = sanitize_filename(category_name)
        
        # Save to user-specific folder if user is logged in
        if self.user_manager.get_current_user():
            user_folder = self.user_manager.get_user_folder()
            os.makedirs(user_folder, exist_ok=True)
            filename = os.path.join(user_folder, f"threads_{sanitized_name}.json")
        else:
            # Fallback to global data folder
            data_dir = get_data_folder()
            filename = os.path.join(data_dir, f"threads_{sanitized_name}.json")
        try:
            serializable_threads = {}
            for thread_title, thread_info in threads.items():
                thread_url, thread_date, thread_id, file_hosts = thread_info
                links = self.bot.thread_links.get(thread_title, {})
                # Ensure links are unique per host
                unique_links = {}
                for host, link_list in links.items():
                    unique_links[host] = list(set(link_list))
                serializable_threads[thread_title] = {
                    'thread_url': thread_url,
                    'thread_date': thread_date,
                    'thread_id': thread_id,
                    'file_hosts': file_hosts,
                    'links': unique_links  # Include links in the saved data
                }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(serializable_threads, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "Data Saved", f"Thread data saved to {filename}.")
            logging.info(f"Thread data saved to {filename}.")
        except Exception as e:
            self.handle_exception(f"save_data for category '{category_name}'", e)

    def load_data(self, category_name):
        """Load thread data from JSON في فولدر data/."""
        sanitized_name = sanitize_filename(category_name)
        
        # Load from user-specific folder if user is logged in
        if self.user_manager.get_current_user():
            user_folder = self.user_manager.get_user_folder()
            filename = os.path.join(user_folder, f"threads_{sanitized_name}.json")
        else:
            # Fallback to global data folder
            data_dir = get_data_folder()
            filename = os.path.join(data_dir, f"threads_{sanitized_name}.json")
        if not os.path.exists(filename):
            logging.warning(f"No saved data for category: {category_name}")
            return False

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                threads = {}
                for thread_title, thread_info in data.items():
                    thread_url = thread_info['thread_url']
                    thread_date = thread_info['thread_date']
                    thread_id = thread_info['thread_id']
                    file_hosts = thread_info.get('file_hosts', [])
                    links = thread_info.get('links', {})

                    # Normalize the links
                    normalized_links = self.normalize_rapidgator_links(links)

                    threads[thread_title] = (thread_url, thread_date, thread_id, file_hosts)

                    # Add thread ID to processed_thread_ids to avoid reprocessing
                    self.bot.processed_thread_ids.add(thread_id)
                    # Save immediately to prevent data loss
                    self.bot.save_processed_thread_ids()

                    # Load links into bot.thread_links، مع دمج وتفادي التكرار
                    if normalized_links:
                        existing = self.bot.thread_links.get(thread_title, {})
                        for host, link_list in normalized_links.items():
                            existing_links = set(existing.get(host, []))
                            for l in link_list:
                                existing_links.add(l)
                            existing[host] = list(existing_links)
                        self.bot.thread_links[thread_title] = existing

            self.category_threads[category_name] = threads
            logging.info(f"Loaded saved data for category: {category_name} from {filename}")
            return True

        except Exception as e:
            self.handle_exception(f"load_data for category '{category_name}'", e)
            return False

    def remove_selected_threads(self):
        if not self.current_category:
            return

        thread_list_widget = self.thread_list
        selected_items = thread_list_widget.selectedItems()
        if not selected_items:
            return

        reply = QMessageBox.question(self, 'Remove Threads',
                                     "Are you sure you want to remove the selected thread(s)?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for item in selected_items:
                thread_title = item.data(Qt.UserRole + 2)  # Retrieve actual thread_title
                thread_url = item.data(Qt.UserRole)
                thread_id = item.data(Qt.UserRole + 1)
                thread_list_widget.takeItem(thread_list_widget.row(item))
                self.category_threads[self.current_category].pop(thread_title, None)
                self.bot.thread_links.pop(thread_title, None)
                # Remove from processed_thread_ids if necessary
                self.bot.processed_thread_ids.discard(thread_id)

            self.statusBar().showMessage(f'Removed {len(selected_items)} thread(s)')
            logging.info(f"Removed {len(selected_items)} thread(s) from category '{self.current_category}'.")

    def remove_all_threads(self):
        """Remove all threads from the current category and their associated links."""
        if not self.current_category:
            QMessageBox.warning(self, "No Category Selected", "Please select a category first.")
            return
        category_name = self.current_category

        thread_list_widget = self.thread_list
        threads = self.category_threads.pop(category_name, {})
        if not threads:
            QMessageBox.information(self, "No Threads", f"There are no threads to remove in '{category_name}'.")
            return

        reply = QMessageBox.question(self, 'Remove All Threads',
                                     f"Are you sure you want to remove all threads from '{category_name}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            thread_list_widget.clear()
            logging.info(f"Removed all threads from category '{category_name}'.")
            # Remove thread IDs and links from bot's processed_thread_ids and thread_links
            for thread_info in threads.values():
                thread_id = thread_info[2]
                self.bot.processed_thread_ids.discard(thread_id)
            # Remove all links associated with the category
            for thread_title in threads.keys():
                self.bot.thread_links.pop(thread_title, None)

            self.statusBar().showMessage(f'Removed all threads from "{category_name}".')
            logging.info(f"Removed all threads from category '{category_name}'.")

    def refresh_categories(self):
        """Refresh the list of categories."""
        self.statusBar().showMessage('Refreshing categories...')
        if self.category_manager.extract_categories():
            self.statusBar().showMessage('Categories refreshed successfully')
            logging.info("Categories refreshed successfully.")
            self.populate_category_tree(load_saved=False)
        else:
            QMessageBox.warning(self, "Error", "Failed to refresh categories.")
            self.statusBar().showMessage('Failed to refresh categories')
            logging.error("Failed to refresh categories.")

    def save_categories(self):
        """Save the current list of categories."""
        self.category_manager.save_categories()
        QMessageBox.information(self, "Categories Saved", "Categories have been saved successfully.")

    def run(self):
        """Run the GUI."""
        self.show()

    def closeEvent(self, event):
        """Handle the application closing event."""
        logging.info("Closing application. Stopping all worker threads.")
        for category_name, worker in self.category_workers.items():
            worker.stop()
            worker.wait()
            logging.info(f"Stopped worker thread for category '{category_name}'.")
        for category_name in self.category_threads:
            self.save_category_data(category_name)
        self.category_manager.save_categories()
        self.bot.save_processed_thread_ids()  # Save processed thread IDs on close
        self.save_process_threads_data()  # Save Process Threads data
        if hasattr(self, 'process_threads'):
            self.save_process_threads_data()
        if self.bot:
            self.bot.close()
            logging.info("Closed bot connection.")
        logging.info("Application closed.")
        event.accept()

    def get_process_threads_filepath(self):
        """
        إرجاع المسار الكامل لملف Process Threads داخل مجلد المستخدم
        """
        if self.user_manager.get_current_user():
            user_folder = self.user_manager.get_user_folder()
            os.makedirs(user_folder, exist_ok=True)
            return os.path.join(user_folder, "process_threads.json")
        else:
            # Fallback for non-logged users
            data_dir = get_data_folder()
            os.makedirs(data_dir, exist_ok=True)
            return os.path.join(data_dir, "process_threads.json")

    def save_process_threads_data(self):
        """
        حفظ متغير self.process_threads إلى data/<username>_process_threads.json
        """
        try:
            filename = self.get_process_threads_filepath()
            current_user = self.user_manager.get_current_user() if hasattr(self, 'user_manager') else None
            
            logging.info(f"💾 Saving process threads data for user: {current_user}")
            logging.info(f"💾 Target file path: {filename}")
            logging.info(f"💾 Data to save: {len(self.process_threads)} threads")
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.process_threads, f, ensure_ascii=False, indent=4)
            
            # Verify the save by reading back
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    saved_data = json.load(f)
                    logging.info(f"✅ Verification: File saved with {len(saved_data)} threads")
            
            logging.info(f"✅ Process Threads data saved successfully to {filename}")
        except Exception as e:
            logging.error(f"❌ Error in save_process_threads_data: {e}", exc_info=True)
            self.handle_exception("save_process_threads_data", e)

    def load_process_threads_data(self):
        """
        تحميل self.process_threads من مجلد المستخدم أو من الملف القديم
        """
        filename = self.get_process_threads_filepath()
        current_user = self.user_manager.get_current_user() if hasattr(self, 'user_manager') else None
        
        logging.info(f"📂 Loading process threads data for user: {current_user}")
        logging.info(f"📂 Target file path: {filename}")
        
        if not os.path.exists(filename):
            logging.warning(f"❌ No saved Process Threads data found: {filename}")
            self.process_threads = {}  # Initialize empty dict
            return False

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                logging.info(f"📊 Raw loaded data keys: {list(loaded_data.keys()) if loaded_data else 'EMPTY'}")
                logging.info(f"📊 Raw loaded data size: {len(loaded_data) if loaded_data else 0} threads")
                
                self.process_threads = loaded_data
                logging.info(f"📊 self.process_threads after loading: {len(self.process_threads)} threads")
                
            self.populate_process_threads_table(self.process_threads)
            logging.info(f"✅ Process Threads data loaded from {filename} - {len(self.process_threads)} threads")
            return True
        except Exception as e:
            logging.error(f"❌ Error loading Process Threads data: {e}", exc_info=True)
            self.process_threads = {}  # Initialize empty dict on error
            return False

    def save_category_data(self, category_name):
        """
        حفظ بيانات المواضيع self.category_threads[category_name] إلى
        data/<username>_<sanitized_category>_threads.json
        """
        threads = self.category_threads.get(category_name, {})
        if not threads:
            return
        data_dir = get_data_folder()
        sanitized_name = sanitize_filename(category_name)
        filename = os.path.join(data_dir, f"{sanitized_name}_threads.json")

        try:
            serializable_threads = {}
            for title, info in threads.items():
                thread_url, thread_date, thread_id, file_hosts = info
                links = self.bot.thread_links.get(title, {})
                # تأكد إن الروابط فريدة
                unique_links = {
                    host: list(set(lst))
                    for host, lst in links.items()
                }
                serializable_threads[title] = {
                    'thread_url': thread_url,
                    'thread_date': thread_date,
                    'thread_id': thread_id,
                    'file_hosts': file_hosts,
                    'links': unique_links
                }

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(serializable_threads, f, ensure_ascii=False, indent=4)
            logging.info(f"Thread data saved to {filename} for category '{category_name}'.")
        except Exception as e:
            self.handle_exception(f"save_category_data for category '{category_name}'", e)

    # ────────────────────────────────────────────────────────────────
    # NEW: PART 1 - Manage replied_thread_ids
    # ────────────────────────────────────────────────────────────────
    def load_replied_thread_ids(self):
        """
        Load replied_thread_ids from user-specific folder or global data folder
        """
        # Initialize replied_thread_ids first to ensure it always exists
        self.replied_thread_ids = set()
        
        try:
            if self.user_manager.get_current_user():
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                filename = os.path.join(user_folder, "replied_thread_ids.json")
            else:
                data_dir = get_data_folder()
                filename = os.path.join(data_dir, "replied_thread_ids.json")
            
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    arr = json.load(f)
                if isinstance(arr, list):
                    self.replied_thread_ids = set(arr)
                logging.info(f"Loaded replied_thread_ids from {filename}: {len(self.replied_thread_ids)} entries.")
            else:
                logging.warning(f"No existing {filename} found. Starting with empty set.")
        except Exception as e:
            logging.error(f"Error loading replied_thread_ids: {e}", exc_info=True)
            # Ensure replied_thread_ids is always a set even if loading fails
            self.replied_thread_ids = set()

    def save_replied_thread_ids(self):
        """
        Save replied_thread_ids to user-specific folder or global data folder
        """
        try:
            if self.user_manager.get_current_user():
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                filename = os.path.join(user_folder, "replied_thread_ids.json")
            else:
                data_dir = get_data_folder()
                filename = os.path.join(data_dir, "replied_thread_ids.json")
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(list(self.replied_thread_ids), f, ensure_ascii=False, indent=4)
            logging.info(f"replied_thread_ids saved to {filename}.")
        except Exception as e:
            logging.error(f"Error saving replied_thread_ids: {e}", exc_info=True)

    def reload_user_specific_data(self):
        """
        Reload all user-specific data when user switches or logs in.
        This ensures proper data isolation between users.
        """
        try:
            current_user = self.user_manager.get_current_user()
            logging.info(f"🔄 Reloading user-specific data for user: {current_user}")
            
            # Run migration for legacy data files FIRST
            self.migrate_legacy_data_files()
            
            # Update file paths for user-specific data
            self.category_manager.update_user_file_paths() 
            self.megathreads_category_manager.update_user_file_paths()
            
            # Reload categories for both managers
            self.category_manager.load_categories()
            self.megathreads_category_manager.load_categories()
            
            # Reload all user-specific data files
            self.load_process_threads_data()
            self.load_backup_threads_data()
            self.load_replied_thread_ids()
            
            # Run migration for old links format if needed
            self.migrate_old_links_format()
            
            # Load all saved category thread files for tracking continuity
            self.load_all_saved_category_threads()
            
            # Reload bot data (user-specific cookies, tokens, processed thread IDs)
            if hasattr(self, 'bot') and self.bot:
                # Update bot file paths for current user
                self.bot.update_user_file_paths()
                
                # Load user-specific bot data only if user is logged in
                if current_user:
                    # Load cookies and check login status
                    cookies_loaded = self.bot.load_cookies()
                    logging.info(f"🍪 Cookies loaded result: {cookies_loaded}")
                    
                    login_status_verified = False
                    if cookies_loaded:
                        login_status_verified = self.bot.check_login_status()
                        logging.info(f"🔐 Login status verification result: {login_status_verified}")
                    
                    if cookies_loaded and login_status_verified:
                        logging.info("✅ Cookies loaded and login verified for user")
                        self.bot.is_logged_in = True
                    else:
                        logging.info(f"❌ Login verification failed - cookies: {cookies_loaded}, status: {login_status_verified}")
                        self.bot.is_logged_in = False
                    
                    # Load Rapidgator tokens
                    # Load Rapidgator tokens (backup for download, main for upload)
                    self.bot.load_token('backup')
                    self.bot.load_token('main')
                    
                    # Load processed thread IDs
                    self.bot.load_processed_thread_ids()
                    logging.info(f"🔄 Loaded {len(self.bot.processed_thread_ids)} processed thread IDs for user")
                else:
                    # Clear bot data for no user
                    self.bot.processed_thread_ids = set()
                    self.bot.is_logged_in = False
                    self.bot.rapidgator_token = None
                    self.bot.upload_rapidgator_token = None
                    logging.info("Bot data cleared - no user logged in")
            
            # Update download directory based on user settings
            self.update_download_directory_from_user_settings()
            
            # Refresh UI components
            self.populate_process_threads_table(self.process_threads)
            self.populate_backup_threads_table()
            
            # Clear current category selection to force refresh
            self.current_category = None
            
            logging.info(f"🔄 User-specific data reloaded successfully for: {current_user}")
            
        except Exception as e:
            logging.error(f"❌ Failed to reload user-specific data: {e}", exc_info=True)
    
    def load_all_saved_category_threads(self):
        """
        Load all saved category thread JSON files for tracking continuity.
        This ensures that previously tracked categories can resume without reprocessing old threads.
        """
        try:
            current_user = self.user_manager.get_current_user()
            
            # Determine the directory to scan for thread files
            if current_user:
                user_folder = self.user_manager.get_user_folder()
                scan_directory = user_folder
                logging.info(f"📁 Loading saved category threads from user folder: {scan_directory}")
            else:
                data_dir = get_data_folder()
                scan_directory = data_dir
                logging.info(f"📁 Loading saved category threads from global folder: {scan_directory}")
            
            if not os.path.exists(scan_directory):
                logging.info(f"📁 Directory does not exist, no saved threads to load: {scan_directory}")
                return
            
            # Initialize category_threads if not exists
            if not hasattr(self, 'category_threads'):
                self.category_threads = {}
            
            loaded_categories = 0
            loaded_threads_total = 0
            
            # Scan for all threads_*.json files
            for filename in os.listdir(scan_directory):
                if filename.startswith('threads_') and filename.endswith('.json'):
                    # Extract category name from filename
                    sanitized_name = filename[8:-5]  # Remove 'threads_' prefix and '.json' suffix
                    
                    # Find actual category name by matching sanitized names
                    category_name = None
                    for cat in self.category_manager.get_categories():
                        if sanitize_filename(cat) == sanitized_name:
                            category_name = cat
                            break
                    
                    if not category_name:
                        # If no exact match, use the sanitized name as category name
                        category_name = sanitized_name
                        logging.warning(f"⚠️ Could not find exact category match for '{sanitized_name}', using as category name")
                    
                    # Load the thread data for this category
                    try:
                        file_path = os.path.join(scan_directory, filename)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        threads = {}
                        loaded_threads_count = 0
                        
                        for thread_title, thread_info in data.items():
                            thread_url = thread_info['thread_url']
                            thread_date = thread_info['thread_date']
                            thread_id = thread_info['thread_id']
                            file_hosts = thread_info.get('file_hosts', [])
                            links = thread_info.get('links', {})
                            
                            # Normalize the links
                            normalized_links = self.normalize_rapidgator_links(links)
                            
                            threads[thread_title] = (thread_url, thread_date, thread_id, file_hosts)
                            
                            # Add thread ID to processed_thread_ids to avoid reprocessing
                            if hasattr(self, 'bot') and self.bot:
                                self.bot.processed_thread_ids.add(thread_id)
                            
                            # Load links into bot.thread_links
                            if normalized_links and hasattr(self, 'bot') and self.bot:
                                existing = self.bot.thread_links.get(thread_title, {})
                                for host, link_list in normalized_links.items():
                                    existing_links = set(existing.get(host, []))
                                    for l in link_list:
                                        existing_links.add(l)
                                    existing[host] = list(existing_links)
                                self.bot.thread_links[thread_title] = existing
                            
                            loaded_threads_count += 1
                        
                        # Store loaded threads for this category
                        self.category_threads[category_name] = threads
                        loaded_categories += 1
                        loaded_threads_total += loaded_threads_count
                        
                        logging.info(f"✅ Loaded {loaded_threads_count} threads for category '{category_name}' from {filename}")
                        
                    except Exception as e:
                        logging.error(f"❌ Failed to load threads from {filename}: {e}")
            
            # Save processed thread IDs if any were loaded
            if hasattr(self, 'bot') and self.bot and loaded_threads_total > 0:
                self.bot.save_processed_thread_ids()
            
            if loaded_categories > 0:
                logging.info(f"🎉 Successfully loaded {loaded_threads_total} threads from {loaded_categories} categories for tracking continuity")
            else:
                logging.info(f"📁 No saved category thread files found in {scan_directory}")
                
        except Exception as e:
            logging.error(f"❌ Failed to load saved category threads: {e}", exc_info=True)

    def update_download_directory_from_user_settings(self):
        """
        Update download directory for FileProcessor and bot based on user-specific settings.
        This is called after user login to apply user-specific download path.
        """
        try:
            current_user = self.user_manager.get_current_user()
            if not current_user:
                logging.debug("🚫 No user logged in - using default download directory")
                return
            
            # Get user-specific download directory setting
            user_download_dir = self.user_manager.get_user_setting('download_dir')
            if user_download_dir:
                # Update FileProcessor download directory
                if hasattr(self, 'file_processor') and self.file_processor:
                    self.file_processor.download_dir = user_download_dir
                
                # Update bot download directory
                if hasattr(self, 'bot') and self.bot:
                    self.bot.download_dir = user_download_dir
                
                logging.info(f"📂 Download directory updated for user '{current_user}': {user_download_dir}")
            else:
                logging.debug(f"⚠️ No download directory setting found for user '{current_user}', using default")
                
        except Exception as e:
            logging.error(f"❌ Error updating download directory from user settings: {e}")

    def clear_user_data_on_logout(self):
        """
        Clear all user-specific data from memory when user logs out.
        This ensures strict data isolation and no data leakage between users.
        """
        try:
            logging.info("🧹 Clearing user-specific data on logout...")
            
            # Clear process threads data
            self.process_threads = {}
            
            # Clear backup threads data  
            self.backup_threads = {}
            
            # Clear replied thread IDs
            self.replied_thread_ids = set()
            
            # Clear megathreads data
            self.megathreads_process_threads = {}
            
            # Clear category-related data
            self.category_threads = {}
            self.current_category = None
            
            # Clear bot data
            if hasattr(self, 'bot') and self.bot:
                self.bot.processed_thread_ids = set()
                self.bot.is_logged_in = False
                self.bot.rapidgator_token = None
                self.bot.upload_rapidgator_token = None
                # Clear cookies
                if hasattr(self.bot, 'driver') and self.bot.driver:
                    try:
                        self.bot.driver.delete_all_cookies()
                    except Exception:
                        pass  # Ignore if browser is not available
            
            # Clear UI tables
            if hasattr(self, 'process_threads_table'):
                self.process_threads_table.setRowCount(0)
            
            if hasattr(self, 'backup_threads_table'):
                self.backup_threads_table.setRowCount(0)
            
            # Clear thread list
            if hasattr(self, 'thread_list'):
                self.thread_list.clear()
            
            # Reset download directory to default
            default_download_dir = os.path.join(os.path.expanduser('~'), 'Downloads', 'ForumBot')
            if hasattr(self, 'file_processor') and self.file_processor:
                self.file_processor.download_dir = default_download_dir
            if hasattr(self, 'bot') and self.bot:
                self.bot.download_dir = default_download_dir
            
            logging.info("✅ User-specific data cleared successfully on logout")
            
        except Exception as e:
            logging.error(f"❌ Error clearing user data on logout: {e}", exc_info=True)

    def migrate_legacy_data_files(self):
        """
        Migrate legacy data files from global folder to user-specific folder.
        """
        try:
            current_user = self.user_manager.get_current_user()
            if not current_user:
                return  # No migration needed if no user logged in
            
            user_folder = self.user_manager.get_user_folder()
            os.makedirs(user_folder, exist_ok=True)
            
            # List of files to migrate from global data folder to user folder
            files_to_migrate = [
                'cookies.pkl',
                'processed_threads.pkl', 
                'rapidgator_download_token.json',
                'rapidgator_upload_token.json'
            ]
            
            migrated_files = []
            for filename in files_to_migrate:
                global_file = os.path.join(DATA_DIR, filename)
                user_file = os.path.join(user_folder, filename)
                
                # Only migrate if global file exists and user file doesn't exist
                if os.path.exists(global_file) and not os.path.exists(user_file):
                    try:
                        import shutil
                        shutil.copy2(global_file, user_file)
                        migrated_files.append(filename)
                        logging.info(f"📦 Migrated {filename} from global folder to user folder")
                    except Exception as e:
                        logging.error(f"❌ Failed to migrate {filename}: {e}")
            
            if migrated_files:
                logging.info(f"✅ Successfully migrated {len(migrated_files)} legacy files for user {current_user}: {', '.join(migrated_files)}")
            else:
                logging.info(f"ℹ️  No legacy files to migrate for user {current_user}")
                
        except Exception as e:
            logging.error(f"❌ Error during legacy data migration: {e}", exc_info=True)

    def migrate_old_links_format(self):
        """
        Migrate old links format from string to dictionary if needed.
        Also migrate legacy data files from global folder to user folder.
        """
        # First migrate legacy data files if user is logged in
        self.migrate_legacy_data_files()
        try:
            migrated_count = 0
            for thread_id, thread_data in self.process_threads.items():
                if 'versions' in thread_data:
                    for version in thread_data['versions']:
                        # Check if links is a string (old format)
                        if isinstance(version.get('links', ''), str) and version['links']:
                            # Convert string to dictionary format
                            old_links = version['links']
                            version['links'] = {'mixed': [old_links]}
                            migrated_count += 1
                            logging.debug(f"Migrated old links format for thread {thread_id}")
                        
                        # Also check direct links field
                        if 'links' in version and isinstance(version['links'], str) and version['links']:
                            old_links = version['links']
                            version['links'] = {'mixed': [old_links]}
                            migrated_count += 1
            
            if migrated_count > 0:
                logging.info(f"🔄 Migrated {migrated_count} old links format entries to new dictionary format")
                self.save_process_threads_data()  # Save migrated data
                
        except Exception as e:
            logging.error(f"Error migrating old links format: {e}", exc_info=True)

    def populate_thread_list(self, category_name, threads, new_thread_titles=set()):
        """
        تعبئة QListWidget(self.thread_list) بالمواضيع في self.category_threads[category_name]
        """
        if category_name not in self.category_threads:
            logging.warning(f"No threads found for category '{category_name}'.")
            return

        widget = self.thread_list
        widget.clear()

        try:
            sorted_threads = sorted(
                threads.items(),
                key=lambda item: int(item[1][2]),
                reverse=True
            )
        except ValueError as ve:
            logging.error(f"Thread ID is not an integer: {ve}", exc_info=True)
            QMessageBox.critical(self, "Data Error", "Encountered a thread with a non-integer ID.")
            return

        for title, info in sorted_threads:
            thread_url, thread_date, thread_id, file_hosts = info
            display = f"{title} (ID: {thread_id}, Date: {thread_date})"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, thread_url)
            item.setData(Qt.UserRole + 1, thread_id)
            item.setData(Qt.UserRole + 2, title)
            item.setData(Qt.UserRole + 3, file_hosts)

            if title in new_thread_titles:
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)

            tooltip = f"ID: {thread_id}\nDate: {thread_date}\nHosts: {', '.join(file_hosts) or 'None'}"
            item.setToolTip(tooltip)
            widget.addItem(item)

        widget.scrollToTop()
        logging.info(f"Populated thread list for category '{category_name}' with {len(threads)} threads.")

    # ========================================
    # THREAD STATUS TRACKING METHODS
    # ========================================

    def update_thread_status(self, category_name, thread_title, status_type, completed=True):
        """
        Update thread status for download, upload, or post completion.

        Args:
            category_name (str): The category name
            thread_title (str): The thread title
            status_type (str): 'download_status', 'upload_status', or 'post_status'
            completed (bool): True if operation completed, False otherwise
        """
        try:
            if category_name not in self.process_threads:
                logging.warning(f"Category '{category_name}' not found in process_threads")
                return

            if thread_title not in self.process_threads[category_name]:
                logging.warning(f"Thread '{thread_title}' not found in category '{category_name}'")
                return

            thread_info = self.process_threads[category_name][thread_title]

            # Handle both old and new formats
            if 'versions' in thread_info and thread_info['versions']:
                # New format: update latest version
                latest_version = thread_info['versions'][-1]
                latest_version[status_type] = completed
                logging.info(f"🐛 DEBUG - Updated {status_type} = {completed} for thread '{thread_title}' (versions format)")
                logging.info(f"🐛 DEBUG - Latest version data: {latest_version}")
            else:
                # Old format: update directly
                thread_info[status_type] = completed
                logging.info(f"🐛 DEBUG - Updated {status_type} = {completed} for thread '{thread_title}' (direct format)")
                logging.info(f"🐛 DEBUG - Thread info data: {thread_info}")

            # Save the updated data
            self.save_process_threads_data()
            logging.info(f"🐛 DEBUG - Saved updated data for thread '{thread_title}'")

            # Emit signal for thread-safe UI update
            self.thread_status_updated.emit()
            
            logging.info(f"🐛 DEBUG - Emitted thread_status_updated signal for UI refresh")
            logging.info(f"Thread status updated: {category_name}/{thread_title} - {status_type}: {completed}")

        except Exception as e:
            logging.error(f"Error updating thread status: {e}", exc_info=True)

    def refresh_process_threads_table(self):
        """
        Safely refresh the process threads table from the main thread.
        This method is connected to the thread_status_updated signal.
        """
        try:
            logging.info(f"🔄 Refreshing process threads table from main thread")
            self.populate_process_threads_table(self.process_threads)
            
            # Force immediate UI update and repaint
            self.process_threads_table.update()
            self.process_threads_table.repaint()
            QApplication.processEvents()  # Process any pending UI events
            
            logging.info(f"✅ Process threads table refreshed successfully")
        except Exception as e:
            logging.error(f"❌ Error refreshing process threads table: {e}", exc_info=True)
    
    def mark_download_complete(self, category_name, thread_title):
        """
        Mark a thread as download complete.
        """
        self.update_thread_status(category_name, thread_title, 'download_status', True)

    def mark_upload_complete(self, category_name, thread_title):
        """
        Mark a thread as upload complete.
        """
        self.update_thread_status(category_name, thread_title, 'upload_status', True)

    def mark_post_complete(self, category_name, thread_title):
        """
        Mark a thread as post complete.
        """
        self.update_thread_status(category_name, thread_title, 'post_status', True)

    def test_color_status_system(self):
        """
        🧪 TEST FUNCTION - Test the color status system with sample data
        Tests the color progression: Blue → Yellow → Green
        """
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QMessageBox
        
        logging.info("🧪 TESTING - Starting color status system test")
        
        # Get first thread from table for testing
        if self.process_threads_table.rowCount() > 0:
            title_item = self.process_threads_table.item(0, 0)
            category_item = self.process_threads_table.item(0, 1)
            
            if title_item and category_item:
                thread_title = title_item.text()
                category_name = category_item.text()
                
                logging.info(f"🧪 TESTING - Using thread: {category_name}/{thread_title}")
                
                # Reset all statuses first
                self.update_thread_status(category_name, thread_title, 'download_status', False)
                self.update_thread_status(category_name, thread_title, 'upload_status', False)
                self.update_thread_status(category_name, thread_title, 'post_status', False)
                
                # Create a timer for sequenced testing
                self.test_timer = QTimer()
                self.test_step = 0
                self.test_category = category_name
                self.test_thread = thread_title
                
                def run_test_step():
                    if self.test_step == 0:
                        # Step 1: Download complete (BLUE)
                        logging.info("🧪 TESTING - Step 1: Setting download complete (expecting BLUE)")
                        self.update_thread_status(self.test_category, self.test_thread, 'download_status', True)
                        self.statusBar().showMessage("🧪 Testing: Download Complete - Row should be BLUE")
                        
                    elif self.test_step == 1:
                        # Step 2: Upload complete (YELLOW)
                        logging.info("🧪 TESTING - Step 2: Setting upload complete (expecting YELLOW)")
                        self.update_thread_status(self.test_category, self.test_thread, 'upload_status', True)
                        self.statusBar().showMessage("🧪 Testing: Upload Complete - Row should be YELLOW")
                        
                    elif self.test_step == 2:
                        # Step 3: Post complete (GREEN)
                        logging.info("🧪 TESTING - Step 3: Setting post complete (expecting GREEN)")
                        self.update_thread_status(self.test_category, self.test_thread, 'post_status', True)
                        self.statusBar().showMessage("🧪 Testing: Post Complete - Row should be GREEN")
                        
                    elif self.test_step == 3:
                        # Final step: Show completion message
                        self.test_timer.stop()
                        logging.info("🧪 TESTING - Color status system test completed!")
                        self.statusBar().showMessage("🧪 Color status system test completed! Check the logs for details.")
                        QMessageBox.information(self, "Test Complete", 
                                              f"Color status system test completed!\n"
                                              f"Thread: {self.test_thread}\n"
                                              f"Check the table row colors and logs for results.")
                        return
                        
                    self.test_step += 1
                    
                # Start the test sequence
                self.test_timer.timeout.connect(run_test_step)
                self.test_timer.start(2000)  # 2 seconds between each step
                run_test_step()  # Run first step immediately
                
            else:
                logging.warning("🧪 TESTING - No valid thread found for testing")
                QMessageBox.warning(self, "Test Error", "No valid thread found for testing")
        else:
            logging.warning("🧪 TESTING - No threads in table to test")
            QMessageBox.warning(self, "Test Error", "No threads in table to test")

    def mark_download_complete(self, category_name, thread_title):
        """Mark thread as download complete"""
        logging.info(f"🔵 Marking download complete: {category_name}/{thread_title}")
        self.update_thread_status(category_name, thread_title, 'download_status', True)
    
    def mark_upload_complete(self, category_name, thread_title):
        """Mark thread as upload complete"""
        logging.info(f"🟡 Marking upload complete: {category_name}/{thread_title}")
        self.update_thread_status(category_name, thread_title, 'upload_status', True)
    
    def mark_post_complete(self, category_name, thread_title):
        """Mark thread as post complete"""
        logging.info(f"🟢 Marking post complete: {category_name}/{thread_title}")
        self.update_thread_status(category_name, thread_title, 'post_status', True)

    def get_thread_status(self, category_name, thread_title):
        """
        Get the current status of a thread.

        Returns:
            dict: Dictionary with 'download_status', 'upload_status', 'post_status' keys
        """
        try:
            if category_name not in self.process_threads:
                return {'download_status': False, 'upload_status': False, 'post_status': False}

            if thread_title not in self.process_threads[category_name]:
                return {'download_status': False, 'upload_status': False, 'post_status': False}

            thread_info = self.process_threads[category_name][thread_title]

            # Handle both old and new formats
            if 'versions' in thread_info and thread_info['versions']:
                # New format: get from latest version
                latest_version = thread_info['versions'][-1]
                return {
                    'download_status': latest_version.get('download_status', False),
                    'upload_status': latest_version.get('upload_status', False),
                    'post_status': latest_version.get('post_status', False)
                }
            else:
                # Old format: get directly
                return {
                    'download_status': thread_info.get('download_status', False),
                    'upload_status': thread_info.get('upload_status', False),
                    'post_status': thread_info.get('post_status', False)
                }

        except Exception as e:
            logging.error(f"Error getting thread status: {e}", exc_info=True)
            return {'download_status': False, 'upload_status': False, 'post_status': False}

    def reset_thread_status(self, category_name, thread_title):
        """
        Reset all status flags for a thread.
        """
        try:
            self.update_thread_status(category_name, thread_title, 'download_status', False)
            self.update_thread_status(category_name, thread_title, 'upload_status', False)
            self.update_thread_status(category_name, thread_title, 'post_status', False)
            logging.info(f"Reset all status flags for thread: {category_name}/{thread_title}")
        except Exception as e:
            logging.error(f"Error resetting thread status: {e}", exc_info=True)
