from config.config import DATA_DIR
import glob
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
from collections import defaultdict
from email.parser import HeaderParser
import hashlib
import logging
import mimetypes
import sys
import time
import re
import json
import pickle
import os
import threading
from pathlib import Path
from collections import defaultdict
from typing import Optional
from urllib.parse import unquote, urljoin
import unicodedata
import requests
from datetime import datetime, date, timedelta
from urllib.parse import urlparse, quote
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common import WebDriverException, TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from utils import sanitize_filename
import deathbycaptcha
from uploaders.rapidgator_upload_handler import RapidgatorUploadHandler
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
import difflib
import xml.etree.ElementTree as ET
import os, logging, requests
from urllib.parse import urlparse

def extract_version_title(post_element, main_thread_title):
    """
    Extracts the version title from a given post element with enhanced version detection.

    Steps:
    1. Try to find a <b> tag that looks like a version title.
    2. Prioritize lines that contain version numbers (v1.01, Version 1.5, etc.)
    3. If no version numbers found, use similarity matching with main thread title.
    4. Enhanced filtering to avoid generic terms.
    """
    import re
    import difflib
    
    # First, try bold tags
    bold_tags = post_element.find_all('b')
    version_candidate = None
    if bold_tags:
        for bold_tag in bold_tags:
            candidate_text = bold_tag.get_text(strip=True)
            # Check if it contains version info and isn't too generic
            if (candidate_text and len(candidate_text) > 4 and 
                candidate_text.lower() not in ['download', 'links', 'rapidgator', 'nitroflare', 'katfile', 'mega'] and
                not candidate_text.lower().startswith('http')):
                
                # Prioritize if it contains version numbers
                if re.search(r'(?:v|version\s*|ver\s*)?[0-9]+(?:\.[0-9]+)+(?![0-9])', candidate_text, re.IGNORECASE):
                    return candidate_text
                elif not version_candidate:  # Keep first good candidate
                    version_candidate = candidate_text

    if version_candidate:
        return version_candidate

    # Fallback: scan all lines with version number priority
    text_content = post_element.get_text("\n").strip()
    lines = [line.strip() for line in text_content.split('\n') if line.strip()]

    # First pass: look for lines with version numbers
    for line in lines:
        if (len(line) > 4 and 
            re.search(r'(?:v|version\s*|ver\s*)?[0-9]+(?:\.[0-9]+)+(?![0-9])', line, re.IGNORECASE) and
            not line.lower().startswith('http') and
            line.lower() not in ['download', 'links', 'rapidgator', 'nitroflare', 'katfile', 'mega']):
            return line
    
    # Second pass: similarity matching
    best_line = None
    best_ratio = 0.0
    for line in lines:
        if (len(line) > 4 and 
            not line.lower().startswith('http') and
            line.lower() not in ['download', 'links', 'rapidgator', 'nitroflare', 'katfile', 'mega']):
            
            ratio = difflib.SequenceMatcher(None, main_thread_title.lower(), line.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_line = line

    if best_line and best_ratio > 0.3:
        return best_line

    return main_thread_title


class ForumBotSelenium:
    def __init__(self, forum_url, username, password, protected_category, headless=False, config=None, user_manager=None, download_dir=None):
        self.forum_url = forum_url.rstrip('/')
        self.username = username
        self.password = password
        self.protected_category = protected_category.strip('/')
        self.headless = headless
        self.config = config  # Store the config
        self.user_manager = user_manager  # Store user_manager reference
        self.is_logged_in = False
        
        # Initialize download directory - will be set properly after user login
        if download_dir:
            self.download_dir = download_dir
        else:
            # Use a default directory that will be updated after user login
            self.download_dir = os.getenv('DOWNLOAD_DIR', 'downloads')
        if not self.download_dir:
            self.download_dir = 'downloads'  # Fallback
        
        # Note: Download directory will be configured based on user settings after login
        logging.debug(f"📥 Default download directory set to: {self.download_dir} (will be updated after user login)")
        
        # Set user-specific file paths based on user session
        if self.user_manager and self.user_manager.get_current_user():
            try:
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                
                # Set user-specific file paths
                self.cookies_file = os.path.join(user_folder, "cookies.pkl")
                self.processed_threads_file = os.path.join(user_folder, "processed_threads.pkl")
                self.rapidgator_token_file = os.path.join(user_folder, "rapidgator_download_token.json")
                self.upload_rapidgator_token_file = os.path.join(user_folder, "rapidgator_upload_token.json")
                
            except (ValueError, AttributeError):
                # Fallback to global data folder
                self.cookies_file = os.path.join(DATA_DIR, "cookies.pkl")
                self.processed_threads_file = os.path.join(DATA_DIR, "processed_threads.pkl")
                self.rapidgator_token_file = os.path.join(DATA_DIR, "rapidgator_download_token.json")
                self.upload_rapidgator_token_file = os.path.join(DATA_DIR, "rapidgator_upload_token.json")
        else:
            # Fallback to global data folder
            self.cookies_file = os.path.join(DATA_DIR, "cookies.pkl")
            self.processed_threads_file = os.path.join(DATA_DIR, "processed_threads.pkl")
            self.rapidgator_token_file = os.path.join(DATA_DIR, "rapidgator_download_token.json")
            self.upload_rapidgator_token_file = os.path.join(DATA_DIR, "rapidgator_upload_token.json")
        self.extracted_threads = {}
        self.thread_links = {}  # Attribute to store links per thread
        self.processed_thread_ids = set()  # Set to store processed thread IDs
        self.known_file_hosts = [
            'rapidgator.net',
            'turbobit.net',
            'nitroflare.com',
            'ddownload.com',
            'rg.to',
            'katfile.com',
            'mega.nz',  # Added to match extract_known_hosts priority list
            # New hosts added
            'xup.in',
            'f2h.io',
            'filepv.com',
            'filespayouts.com',
            'uploady.io',
            # Add more known file hosts here
        ]
        self.use_backup_rg = self.config.get('use_backup_rg', False) if self.config else False

        # Initialize download directory
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir, exist_ok=True)
            logging.info(f"Download directory created: {self.download_dir}")

            # Initialize banned files directory
            self.banned_files_dir = os.path.join(self.download_dir, "banned_files")
            os.makedirs(self.banned_files_dir, exist_ok=True)

            logging.info(f"Banned files directory initialized at: {self.banned_files_dir}")

        # Load environment variables for DeathByCaptcha and Hosts configurations
        load_dotenv()  # Ensure this is called before accessing env variables
        self.dbc_username = os.getenv('DBC_USERNAME')
        self.dbc_password = os.getenv('DBC_PASSWORD')
        if not self.dbc_username or not self.dbc_password:
            raise ValueError("DeathByCaptcha credentials are not set in the environment variables.")

        self.dbc_client = deathbycaptcha.SocketClient(self.dbc_username, self.dbc_password)

        self.rapidgator_username = os.getenv('RAPIDGATOR_LOGIN')
        self.rapidgator_password = os.getenv('RAPIDGATOR_PASSWORD')
        self.upload_username = (
            os.getenv('UPLOAD_RAPIDGATOR_USERNAME')
            or os.getenv('UPLOAD_RAPIDGATOR_LOGIN')
        )
        self.upload_password = os.getenv('UPLOAD_RAPIDGATOR_PASSWORD')

        if not self.rapidgator_username or not self.rapidgator_password:
            raise ValueError("Rapidgator credentials are not set in the environment variables.")

        # Load Hosts Configurations from .env # NEW
        self.download_hosts = self.load_hosts('DOWNLOAD_HOSTS')
        self.upload_hosts = self.load_hosts('UPLOAD_HOSTS')
        self.backup_host = self.load_backup_host()
        self.keep_links_credentials = self.load_keep_links_credentials()
        self.image_host_config = self.load_image_host_config()

        # Set up logging with UTF-8 and replace errors for unsupported characters
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )

        # Override the default encoding for the handler to replace unsupported characters
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.StreamHandler):
                try:
                    handler.setStream(
                        open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1, errors='replace'))
                except Exception as e:
                    self.handle_exception("setting stream encoding", e)

        # Initialize WebDriver with retries
        self.headless = headless  # Ensure headless attribute is set before initialization
        if not self.initialize_driver_with_retries():
            raise RuntimeError("WebDriver initialization failed after multiple attempts.")

        # Initialize processed thread IDs
        self.processed_thread_ids = set()

        # Initialize data structures (don't load files before user login)
        self.processed_thread_ids = set()
        self.is_logged_in = False

        # Rapidgator API Tokens - initialize only (don't load before user login)
        self.rg_backup_token = None
        self.rg_main_token = None
        # Token expiry times
        self.rg_backup_token_expiry = 0  # Token expiry time for backup account
        self.rg_main_token_expiry = 0  # Token expiry time for main account

        # Backwards compatibility aliases
        self.rapidgator_token = self.rg_backup_token
        self.upload_rapidgator_token = self.rg_main_token
        self.rapidgator_token_expiry = self.rg_backup_token_expiry
        self.upload_rapidgator_token_expiry = self.rg_main_token_expiry

        # Initialize a lock for thread safety
        self.lock = threading.Lock()

    def update_user_file_paths(self):
        """Update file paths for current user when user switches."""
        if hasattr(self, 'user_manager') and self.user_manager:
            current_user = self.user_manager.get_current_user()
            if current_user:
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                
                # Update cookies file path
                self.cookies_file = os.path.join(user_folder, "cookies.pkl")
                
                # Update processed threads file path
                self.processed_threads_file = os.path.join(user_folder, "processed_threads.pkl")
                
                # Update Rapidgator token file paths
                self.rapidgator_token_file = os.path.join(user_folder, "rapidgator_download_token.json")
                self.upload_rapidgator_token_file = os.path.join(user_folder, "rapidgator_upload_token.json")
                
                logging.info(f"Updated bot file paths for user: {current_user}")
            else:
                # No user logged in - use global data folder
                data_dir = DATA_DIR
                os.makedirs(data_dir, exist_ok=True)
                
                self.cookies_file = os.path.join(data_dir, "cookies.pkl")
                self.processed_threads_file = os.path.join(data_dir, "processed_threads.pkl")
                self.rapidgator_token_file = os.path.join(data_dir, "rapidgator_download_token.json")
                self.upload_rapidgator_token_file = os.path.join(data_dir, "rapidgator_upload_token.json")
                
                logging.info("Updated bot file paths for no user (global folder)")

    def check_login_status(self):
        """Check if the user is still logged in by verifying forum access."""
        try:
            if not hasattr(self, 'driver') or not self.driver:
                logging.warning("No driver available for login status check")
                return False
                
            # Navigate to the main forum page to check login status
            current_url = self.driver.current_url
            
            self.driver.get(self.forum_url)
            time.sleep(2)
            
            # Check if we're redirected to login page or see login elements
            if "login" in self.driver.current_url.lower():
                logging.info("Login status check: Redirected to login page - User not logged in")
                return False
                
            # Look for login form elements
            if self.driver.find_elements(By.NAME, "vb_login_username"):
                logging.info("Login status check: Login form found - User not logged in")
                return False
            
            # Look for user-specific elements that indicate logged in status
            # Check for logout link or user menu
            logout_elements = self.driver.find_elements(By.PARTIAL_LINK_TEXT, "Logout")
            user_menu = self.driver.find_elements(By.CLASS_NAME, "usermenu")
            
            if logout_elements or user_menu:
                logging.info("Login status check: User menu/logout found - User logged in")
                # Navigate back to original URL if needed
                if current_url and current_url != self.forum_url:
                    self.driver.get(current_url)
                return True
            
            logging.info("Login status check: No clear login indicators - assuming not logged in")
            return False
            
        except Exception as e:
            logging.error(f"Error checking login status: {e}", exc_info=True)
            return False

    def load_token(self, account_type='backup'):
        """Load Rapidgator token from file."""
        try:
            if account_type == 'main':
                token_file = self.upload_rapidgator_token_file
                token_attr = 'rg_main_token'
                expiry_attr = 'rg_main_token_expiry'
            else:
                token_file = self.rapidgator_token_file
                token_attr = 'rg_backup_token'
                expiry_attr = 'rg_backup_token_expiry'
                
            if os.path.exists(token_file):
                with open(token_file, 'r') as f:
                    token_data = json.load(f)
                    
                setattr(self, token_attr, token_data.get('token'))
                setattr(self, expiry_attr, token_data.get('expiry', 0))
                if account_type == 'main':
                    self.upload_rapidgator_token = self.rg_main_token
                    self.upload_rapidgator_token_expiry = self.rg_main_token_expiry
                else:
                    self.rapidgator_token = self.rg_backup_token
                    self.rapidgator_token_expiry = self.rg_backup_token_expiry
                
                logging.info(f"Loaded {account_type} token from {token_file}")
                return True
            else:
                logging.info(f"No {account_type} token file found at {token_file}")
                setattr(self, token_attr, None)
                setattr(self, expiry_attr, 0)
                return False
                
        except Exception as e:
            logging.error(f"Error loading {account_type} token: {e}")
            setattr(self, token_attr, None)
            setattr(self, expiry_attr, 0)
            return False

    def upload_file_and_notify(self, file_path, category_name, thread_id):
        """Upload the file to Keeplinks and optionally to Mega.nz, and store URLs with thread data."""

        # Upload to Keeplinks
        keeplinks_url = self.upload_file_to_keeplinks(file_path)
        logging.debug(f"Received Keeplinks URL: {keeplinks_url}")

        backup_rg_url = None  # Backup Rapidgator URL

        # Update thread links data
        if thread_id not in self.thread_links:
            self.thread_links[thread_id] = {
                'backup_rg_url': '',
                'keeplinks_urls': [],
                'file_paths': [],
                'timestamp': str(datetime.now())
            }

        if backup_rg_url:
            self.thread_links[thread_id]['backup_rg_url'] = backup_rg_url
            logging.info(f"Rapidgator backup URL added for thread {thread_id}: {backup_rg_url}")

        if keeplinks_url:
            self.thread_links[thread_id]['keeplinks_urls'].append(keeplinks_url)
            logging.info(f"Keeplinks URL added for thread {thread_id}: {keeplinks_url}")

        self.thread_links[thread_id]['file_paths'].append(file_path)

        # Save the thread data after upload
        self.save_thread_links_to_file()
        self.processed_thread_ids.add(thread_id)
        # Save immediately to prevent data loss
        self.save_processed_thread_ids()

        logging.info(f"Upload process completed for thread {thread_id}.")

    def format_links_for_keeplinks(grouped_links):
        """Format grouped links into a string for Keeplinks."""
        formatted = []
        for host, links in grouped_links.items():
            encoded_links = [quote(link, safe=':/') for link in links]  # Proper URL encoding
            formatted.append(f"{host}: " + ', '.join(encoded_links))
        return '\n'.join(formatted)

    def group_links_by_host(self, urls):
        """Group URLs by their host."""
        grouped_links = defaultdict(list)
        for url in urls:
            host = url.split('/')[2]  # Extract host from URL
            grouped_links[host].append(url)
        return grouped_links

    def format_links_for_keeplinks(self, grouped_links):
        """Format the grouped links to ensure links from the same host are listed together."""
        formatted_links = []
        for host, links in grouped_links.items():
            formatted_links.extend(links)  # Add all links for the same host together
        return formatted_links

    def sanitize_url(self, url):
        """Sanitize a URL to ensure it's properly formatted for API calls."""
        return quote(url, safe=':/')

    def send_to_keeplinks(self, urls):
        """
        Send a list of URLs to Keeplinks API and get a shortened Keeplinks URL.
        Includes timeout handling and retries.

        Enhancements:
        - For Rapidgator URLs, send only the base URL up to the file ID.
        - Ensure URLs are encoded only once to prevent double encoding.
        """
        try:
            import xml.etree.ElementTree as ET  # <-- Make sure ET is imported so we can parse XML without error

            api_url = "https://www.keeplinks.org/api.php"
            api_hash = str(self.config.get('keeplinks_api_hash', '') or '').strip()
            logging.debug(f"Keeplinks API Hash: '{api_hash}'")

            if not api_hash:
                logging.error("Keeplinks API hash is not configured.")
                return ''

            from urllib.parse import urlparse, quote

            def extract_base_rapidgator_url(url):
                parsed = urlparse(url)
                if parsed.netloc.lower() == 'rapidgator.net' and parsed.path.startswith('/file/'):
                    path_parts = parsed.path.split('/')
                    if len(path_parts) >= 3:
                        base_path = '/'.join(path_parts[:3]) + '/'
                        base_url = f"{parsed.scheme}://{parsed.netloc}{base_path}"
                        return base_url
                return url

            # Process URLs: extract base Rapidgator URLs
            processed_urls = [extract_base_rapidgator_url(url) for url in urls]

            # Sanitize URLs before sending to Keeplinks
            sanitized_urls = [self.sanitize_url(url) for url in processed_urls]

            # Encode URLs to handle special characters; ensure it's only encoded once
            encoded_urls = [quote(u, safe=':/?=&,') for u in sanitized_urls]

            # Group and format URLs for Keeplinks
            grouped_links = self.group_links_by_host(encoded_urls)
            formatted_links = self.format_links_for_keeplinks(grouped_links)

            # Combine formatted URLs into a single string
            all_urls_string = ','.join(formatted_links)

            api_params = {
                'apihash': api_hash,
                'link-to-protect': all_urls_string,
                'output': 'xml',
                'captcha': 'on',
                'captchatype': 'Re',
            }
            logging.debug(f"API Params: {api_params}")

            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/xml'
            }

            # Add timeout and retry mechanism
            max_retries = 3
            timeout = 30  # seconds
            retry_delay = 5  # seconds

            for attempt in range(max_retries):
                try:
                    # Send the request with timeout
                    response = requests.post(
                        api_url,
                        data=api_params,
                        headers=headers,
                        timeout=timeout
                    )
                    response.raise_for_status()
                    response_text = response.text.strip()
                    logging.debug(f"Keeplinks API Response Text: {response_text}")

                    # Parse the XML response
                    root = ET.fromstring(response_text)
                    error_elem = root.find('api_error')

                    if error_elem is not None:
                        error_message = error_elem.text
                        logging.error(f"Keeplinks API Error: {error_message}")

                        # Check if it's a temporary error that warrants a retry
                        if any(err in error_message.lower() for err in ['timeout', 'temporary', 'try again']):
                            if attempt < max_retries - 1:
                                logging.info(
                                    f"Retrying Keeplinks request in {retry_delay} seconds... "
                                    f"(Attempt {attempt + 1}/{max_retries})"
                                )
                                time.sleep(retry_delay)
                                continue
                        return ''

                    p_links_elem = root.find('p_links')
                    keeplinks_url = p_links_elem.text.strip() if p_links_elem is not None else ''
                    if keeplinks_url:
                        logging.info(f"Keeplinks URL generated: {keeplinks_url}")
                        return keeplinks_url
                    else:
                        logging.error("No valid Keeplinks URL found in response")
                        return ''

                except ET.ParseError as e:
                    logging.error(f"Failed to parse Keeplinks API response XML: {e}")
                    if attempt < max_retries - 1:
                        logging.info(
                            f"Retrying due to XML parse error... "
                            f"(Attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(retry_delay)
                        continue
                    return ''

                except requests.Timeout:
                    logging.error(f"Keeplinks API request timed out (Attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        logging.info(f"Retrying after timeout in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
                    return ''

                except requests.RequestException as e:
                    logging.error(f"Keeplinks API request failed: {e}")
                    if attempt < max_retries - 1:
                        logging.info(
                            f"Retrying after error in {retry_delay} seconds... "
                            f"(Attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(retry_delay)
                        continue
                    return ''

            logging.error(f"Failed to get Keeplinks URL after {max_retries} attempts")
            return ''

        except Exception as e:
            logging.error(f"Error sending URLs to Keeplinks: {e}", exc_info=True)
            return ''

    def check_rapidgator_link_status(self, link):
        """Check a Rapidgator link using the /file/check_link endpoint."""
        # Prefer main token but fall back to backup
        account_type = None
        if self.upload_rapidgator_token:
            account_type = 'main'
        elif self.rapidgator_token:
            account_type = 'backup'

        if not account_type:
            if self.load_token('main'):
                account_type = 'main'
            elif self.load_token('backup'):
                account_type = 'backup'

        if not account_type or not self.ensure_valid_token(account_type):
            logging.error("Rapidgator token is not available.")
            return {'status': 'DEAD'}

        token = self.upload_rapidgator_token if account_type == 'main' else self.rapidgator_token

        # Extract file_id from URL
        api_url = "https://rapidgator.net/api/v2/file/check_link"
        params = {
            'token': token,
            'url': link,
        }

        try:
            response = requests.get(api_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200:
                    info_list = data.get('response', [])
                    if info_list:
                        return info_list[0]
                    return {'status': 'DEAD'}
                else:
                    logging.warning("Link appears dead: %s", data.get('details'))
                    return {'status': 'DEAD'}

                return file_data
            else:
                logging.error("Failed to check link status. HTTP %s", response.status_code)
                return {'status': 'DEAD'}

        except Exception as e:
            logging.error(f"Exception occurred while checking Rapidgator link status: {e}")

            return {'status': 'DEAD'}

    def parse_content_disposition(self, content_disp):
            """
            Parses the Content-Disposition header to extract parameters like filename.

            Parameters:
            - content_disp (str): The Content-Disposition header string.

            Returns:
            - dict: A dictionary of parameters extracted from the header.
            """
            parser = HeaderParser()
            headers = parser.parsestr(f'Content-Disposition: {content_disp}')
            params = headers.get_params(header='content-disposition', failobj=[])
            return {param[0]: param[1] for param in params}

    def handle_exception(self, operation_name, exception):
            """
            Handles exceptions by logging them with a specific operation name.

            Parameters:
            - operation_name (str): The name of the operation where the exception occurred.
            - exception (Exception): The exception to handle.
            """
            logging.error(f"Exception during {operation_name}: {exception}", exc_info=True)

    # -----------------------------------
    # 6. Enhanced Exception Handling # NEW
    # -----------------------------------
    def safe_execute(self, func, *args, **kwargs):
        """
        Executes a function with enhanced exception handling.
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.handle_exception(f"executing {func.__name__}", e)
            return None

    # -----------------------------------
    # 7. Improved Auto-Login Mechanism # NEW
    # -----------------------------------
    def ensure_logged_in(self, category_url=None):
        """
        Ensures that the bot is logged in. If not, performs login and navigates back to the category URL if provided.
        """
        if not self.is_logged_in:
            logging.info("Bot is not logged in. Initiating login process.")
            self.login(current_url=category_url)
            if not self.is_logged_in:
                logging.error("Auto-login failed.")
                return False
        else:
            logging.debug("Bot is already logged in.")
        return True

    # -----------------------------------
    # 8. Retry Mechanism for Network Operations # NEW
    # -----------------------------------
    def retry_operation(self, func, retries=3, delay=5, *args, **kwargs):
        """
        Retries a network operation with specified retries and delay.
        """
        for attempt in range(1, retries + 1):
            result = self.safe_execute(func, *args, **kwargs)
            if result:
                return result
            else:
                logging.warning(f"Attempt {attempt} failed for {func.__name__}. Retrying in {delay} seconds...")
                time.sleep(delay)
        logging.error(f"All {retries} attempts failed for {func.__name__}.")
        return None

    # -----------------------------------
    # 9. Enhanced Captcha Handling # NEW
    # -----------------------------------
    def solve_and_apply_captcha(self, captcha):
        """
        Solves the captcha and applies the solution to the webpage.
        """
        solution = self.solve_captcha(captcha)
        if not solution:
            logging.error("Failed to solve captcha.")
            return False

        try:
            # Apply the solution to the captcha response field
            self.driver.execute_script(
                "document.getElementById('g-recaptcha-response').innerHTML = arguments[0];", solution
            )
            logging.debug("Applied captcha solution to the page.")
            return True
        except Exception as e:
            self.handle_exception("applying captcha solution", e)
            return False

    # -----------------------------------
    # 10. Robust WebDriver Handling # NEW
    # -----------------------------------
    def initialize_driver_with_retries(self, retries=3, delay=5):
        """
        Initializes the WebDriver with retries in case of failures.
        Enhanced with comprehensive timeout configurations to prevent hanging.
        """
        for attempt in range(1, retries + 1):
            try:
                service = Service(ChromeDriverManager().install())
                chrome_options = Options()
                chrome_options.add_argument("--window-size=1920,1080")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--ignore-certificate-errors")
                chrome_options.add_argument("--disable-extensions")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")  # Prevents crashes in headless mode
                chrome_options.add_argument("--disable-background-timer-throttling")  # Better performance
                chrome_options.add_argument("--disable-renderer-backgrounding")  # Better performance
                chrome_options.add_argument("--disable-backgrounding-occluded-windows")  # Better performance
                if self.headless:
                    chrome_options.add_argument("--headless")
                
                # Initialize WebDriver
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                
                # Configure comprehensive timeouts to prevent hanging
                # Page load timeout: Maximum time to wait for a page to fully load
                self.driver.set_page_load_timeout(30)  # 30 seconds timeout for page loads
                
                # Script timeout: Maximum time to wait for asynchronous scripts
                self.driver.set_script_timeout(20)  # 20 seconds timeout for JavaScript
                
                # Implicit wait: Default wait time for element searches  
                self.driver.implicitly_wait(10)  # 10 seconds implicit wait for elements
                
                logging.info("🚀 WebDriver initialized successfully with timeout configurations:")
                logging.info("   ⏱️ Page load timeout: 30 seconds")
                logging.info("   ⏱️ Script timeout: 20 seconds")
                logging.info("   ⏱️ Implicit wait: 10 seconds")
                return True
            except WebDriverException as e:
                self.handle_exception(f"initializing WebDriver on attempt {attempt}", e)
                time.sleep(delay)
        self.handle_exception("initializing WebDriver after multiple attempts",
                              WebDriverException("Failed to initialize WebDriver"))
        return False
    
    def safe_navigate(self, url, timeout=30):
        """
        🔒 Timeout-aware navigation wrapper that can be interrupted during thread stopping.
        Provides additional safety layer for WebDriver navigation operations.
        
        Args:
            url (str): URL to navigate to
            timeout (int): Custom timeout in seconds (default: 30)
            
        Returns:
            bool: True if navigation successful, False if failed or timed out
        """
        try:
            logging.debug(f"🧭 Safe navigation to: {url}")
            
            # Set custom timeout if different from default
            if timeout != 30:
                original_timeout = self.driver.timeouts.page_load
                self.driver.set_page_load_timeout(timeout)
            
            # Perform navigation with timeout protection
            self.driver.get(url)
            
            # Restore original timeout if changed
            if timeout != 30:
                self.driver.set_page_load_timeout(original_timeout)
            
            logging.debug(f"✅ Safe navigation completed: {url}")
            return True
            
        except Exception as e:
            # Restore timeout even if exception occurred
            if timeout != 30:
                try:
                    self.driver.set_page_load_timeout(30)
                except:
                    pass  # Ignore timeout restore errors
            
            logging.warning(f"⚠️ Safe navigation failed for {url}: {e}")
            return False

    # -----------------------------------
    # 1. Loading Host Configurations # NEW
    # -----------------------------------
    def load_hosts(self, host_type):
        """
        Load download or upload hosts from environment variables.

        Parameters:
        - host_type (str): 'DOWNLOAD_HOSTS' or 'UPLOAD_HOSTS'

        Returns:
        - List of host names
        """
        hosts_str = os.getenv(host_type, '')
        hosts = [host.strip().lower() for host in hosts_str.split(',') if host.strip()]
        logging.debug(f"Loaded {host_type}: {hosts}")
        return hosts

    def load_backup_host(self):
        """Load backup host configuration from environment variables."""
        backup_host = 'rapidgator'
        backup_username = (
            os.getenv('UPLOAD_RAPIDGATOR_USERNAME')
            or os.getenv('UPLOAD_RAPIDGATOR_LOGIN', '')
        )
        backup_password = os.getenv('UPLOAD_RAPIDGATOR_PASSWORD', '')
        logging.debug(f"Loaded backup host: {backup_host}")
        return {
            'host': backup_host,
            'username': backup_username,
            'password': backup_password
        }

    def load_keep_links_credentials(self):
        """Load Keeplinks.org account credentials from environment variables."""
        username = os.getenv('KEEP_LINKS_USERNAME', '')
        password = os.getenv('KEEP_LINKS_PASSWORD', '')
        logging.debug(f"Loaded Keeplinks.org credentials: Username={username}")
        return {
            'username': username,
            'password': password
        }

    def load_image_host_config(self):
        """Load Image Host configurations from environment variables."""
        image_host = os.getenv('IMAGE_HOST', '').lower()
        config = {
            'host': image_host,
            'client_id': os.getenv('imgur_client_id', ''),
            'client_secret': os.getenv('imgur_client_secret', '')
            # Add more configurations if using a different image host
        }
        logging.debug(f"Loaded Image Host config: {config}")
        return config

    # -----------------------------------
    # 2. API Login and Token Management
    # -----------------------------------
    # ---------------------------------------------------------------------------
    # 1)  API LOGIN – returns True on success, False on failure
    # ---------------------------------------------------------------------------
    def api_login(self, account_type: str = "backup") -> bool:
        """
        Authenticate to Rapidgator for either the MAIN (upload) or BACKUP (premium) account
        and store the token + expiry on the instance.

        account_type: "main" | "backup"
        """
        if account_type not in {"main", "backup"}:
            logging.error("api_login: invalid account_type '%s'", account_type)
            return False

        login_url = "https://rapidgator.net/api/v2/user/login"

        # Pick credentials from environment
        if account_type == "main":
            username = (
                os.getenv("UPLOAD_RAPIDGATOR_USERNAME")
                or os.getenv("UPLOAD_RAPIDGATOR_LOGIN", "")
            )
            password = os.getenv("UPLOAD_RAPIDGATOR_PASSWORD", "")
        else:  # backup
            username = os.getenv("RAPIDGATOR_LOGIN", "")
            password = os.getenv("RAPIDGATOR_PASSWORD", "")

        payload = {"login": username, "password": password}
        headers = {"Content-Type": "application/json"}

        try:
            logging.info("🔐 RG login (%s account)…", account_type)
            resp = requests.post(login_url, json=payload, headers=headers, timeout=20)

            if resp.status_code != 200:
                logging.error("RG login HTTP %s – %s", resp.status_code, resp.text)
                return False

            data = resp.json()
            token = data.get("response", {}).get("token")
            if not token:
                logging.error("RG login failed – token missing (%s)", data.get("details"))
                return False

            expires_in = int(data.get("response", {}).get("expire_in", 900))  # seconds
            expiry_time = time.time() + expires_in

            if account_type == "main":
                self.rg_main_token = token
                self.rg_main_token_expiry = expiry_time
                # legacy / compatibility aliases
                self.upload_rapidgator_token = token
                self.upload_rapidgator_token_expiry = expiry_time
            else:  # backup
                self.rg_backup_token = token
                self.rg_backup_token_expiry = expiry_time
                # legacy / compatibility aliases
                self.rapidgator_token = token
                self.rapidgator_token_expiry = expiry_time

            self.save_token(account_type)  # persist
            logging.info("✅ RG %s login OK – token saved.", account_type)
            return True

        except Exception as exc:
            logging.exception("RG %s login exception: %s", account_type, exc)
            return False

    # ---------------------------------------------------------------------------
    # 2)  SAVE TOKEN
    # ---------------------------------------------------------------------------
    def save_token(self, account_type: str = "backup") -> None:
        """Persist the token/expiry for the given account_type to JSON."""
        if account_type == "main":
            token = getattr(self, "rg_main_token", None)
            expiry = getattr(self, "rg_main_token_expiry", 0)
        else:  # backup
            token = getattr(self, "rg_backup_token", None)
            expiry = getattr(self, "rg_backup_token_expiry", 0)

        if not token:
            logging.warning("save_token: no token to save for '%s' account.", account_type)
            return

        # build path
        if self.user_manager and self.user_manager.get_current_user():
            folder = self.user_manager.get_user_folder()
        else:
            folder = DATA_DIR
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, f"rapidgator_{account_type}_token.json")

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"token": token, "expiry": expiry}, fh, ensure_ascii=False, indent=2)
            logging.info("💾 Token (%s) saved to %s", account_type, path)
        except Exception as exc:
            self.handle_exception(f"saving {account_type} token", exc)

    # ---------------------------------------------------------------------------
    # 3)  LOAD TOKEN
    # ---------------------------------------------------------------------------
    def load_token(self, account_type: str = "backup") -> bool:
        """Load token/expiry for MAIN or BACKUP account from disk; return True if found."""
        if self.user_manager and self.user_manager.get_current_user():
            folder = self.user_manager.get_user_folder()
        else:
            folder = DATA_DIR

        path = os.path.join(folder, f"rapidgator_{account_type}_token.json")
        if not os.path.isfile(path):
            logging.info("No stored %s token at %s", account_type, path)
            return False

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                token = data.get("token")
                expiry = data.get("expiry", 0)

            if account_type == "main":
                self.rg_main_token = token
                self.rg_main_token_expiry = expiry
                self.upload_rapidgator_token = token
                self.upload_rapidgator_token_expiry = expiry
            else:  # backup
                self.rg_backup_token = token
                self.rg_backup_token_expiry = expiry
                self.rapidgator_token = token
                self.rapidgator_token_expiry = expiry

            logging.info("🔑 Loaded %s token from %s", account_type, path)
            return True

        except Exception as exc:
            self.handle_exception(f"loading {account_type} token", exc)
            return False

    def ensure_valid_token(self, account_type='backup'):
        """
        Ensures that the specified token (download or upload) is valid and not expired.
        If expired or close to expiry, it refreshes the token.
        """
        if account_type == 'main':
            token_expiry = self.rg_main_token_expiry
            token = self.rg_main_token
        else:
            token_expiry = self.rg_backup_token_expiry
            token = self.rg_backup_token

        # If no token or token is near expiry (e.g., within 60 seconds), re-login
        if not token or time.time() > token_expiry - 60:
            logging.info(f"{account_type.capitalize()} token expired or near expiry, re-authenticating...")
            if not self.api_login(account_type):
                logging.error(f"Failed to re-authenticate {account_type} token.")
                return False
        return True

    def api_get_user_info(self):
        """
        Retrieves user information using the Rapidgator API.
        """
        # Ensure the download token is valid before making the call
        if not self.ensure_valid_token('backup'):
            logging.error("Cannot get user info because download token could not be refreshed.")
            return None

        info_url = "https://rapidgator.net/api/v2/user/info"
        params = {
            'token': self.rapidgator_token
        }

        try:
            logging.info("Fetching Rapidgator user info via API.")
            response = requests.get(info_url, params=params)

            # If we got a session doesn't exist error, try refreshing and retrying once
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200:
                    user_info = data.get('response', {}).get('user')
                    logging.info("Rapidgator user info retrieved successfully.")
                    return user_info
                else:
                    details = data.get('details', '')
                    if "Session doesn't exist" in details:
                        # Attempt to refresh token and retry
                        if self.api_login('backup'):
                            response = requests.get(info_url, params={'token': self.rg_backup_token})
                            if response.status_code == 200:
                                data = response.json()
                                if data.get('status') == 200:
                                    user_info = data.get('response', {}).get('user')
                                    logging.info("Rapidgator user info retrieved successfully after re-login.")
                                    return user_info
                    logging.error(f"Failed to retrieve user info: {details}")
                    return None
            else:
                details = ""
                try:
                    details = response.json().get('details', '')
                except:
                    pass
                logging.error(f"Failed to retrieve Rapidgator user info: {details} (Status {response.status_code})")
                return None
        except Exception as e:
            self.handle_exception("Rapidgator API user info retrieval", e)
            return None

    def is_token_valid(self):
        """
        Checks if the current Rapidgator token is valid by checking the expiry time.

        Returns:
        - bool: True if token is valid, False otherwise.
        """
        return self.rg_backup_token and time.time() < self.rg_backup_token_expiry

    # -----------------------------------
    # 2. Upload Rapidgator API Login and Token Management
    # -----------------------------------
    def api_upload_get_user_info(self):
        """
        Retrieves user information using the Rapidgator API for the upload account.
        """
        # Ensure the upload token is valid before making the call
        if not self.ensure_valid_token('main'):
            logging.error("Cannot get upload user info because upload token could not be refreshed.")
            return None

        info_url = "https://rapidgator.net/api/v2/user/info"
        params = {
            'token': self.upload_rapidgator_token
        }

        try:
            logging.info("Fetching Rapidgator upload user info via API.")
            response = requests.get(info_url, params=params)

            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200:
                    user_info = data.get('response', {}).get('user')
                    logging.info("Rapidgator upload user info retrieved successfully.")
                    return user_info
                else:
                    details = data.get('details', '')
                    if "Session doesn't exist" in details:
                        # Attempt to refresh token and retry
                        if self.api_login('main'):
                            response = requests.get(info_url, params={'token': self.rg_main_token})
                            if response.status_code == 200:
                                data = response.json()
                                if data.get('status') == 200:
                                    user_info = data.get('response', {}).get('user')
                                    logging.info("Rapidgator upload user info retrieved successfully after re-login.")
                                    return user_info
                    logging.error(f"Failed to retrieve Rapidgator upload user info: {details}")
                    return None
            else:
                details = ""
                try:
                    details = response.json().get('details', '')
                except:
                    pass
                logging.error(
                    f"Failed to retrieve Rapidgator upload user info: {details} (Status {response.status_code})")
                return None
        except Exception as e:
            self.handle_exception("Rapidgator upload API user info retrieval", e)
            return None

    def is_upload_token_valid(self):
        """
        Checks if the current Rapidgator upload token is valid by checking the expiry time.

        Returns:
        - bool: True if token is valid, False otherwise.
        """
        return self.rg_main_token and time.time() < self.rg_main_token_expiry

    # ----------------------------------
    # 3. Download Methods # NEW
    # -----------------------------------
    def download_links(self, host, links, category_name, thread_id, thread_title):
        """
        Download links using the specified download host.

        Parameters:
        - host (str): The download host to use.
        - links (list): List of URLs to download.
        - category_name (str): Name of the category.
        - thread_id (str): ID of the thread.
        - thread_title (str): Title of the thread.
        """
        with self.lock:  # Ensure thread-safe access
            method_name = f"download_{host.replace('.', '_')}"
            method = getattr(self, method_name, None)
            if method:
                logging.info(f"Starting download using host '{host}'.")
                for link in links:
                    method(link, category_name, thread_id, thread_title)
            else:
                logging.error(f"No download method implemented for host '{host}'.")

    def extract_file_id(self, url):
        """
        Extracts the file_id from a Rapidgator download URL.

        Parameters:
        - url (str): The Rapidgator download URL.

        Returns:
        - str or None: The extracted file_id or None if not found.
        """
        # Updated regex: Trailing slash is optional
        match = re.search(r'/file/([a-fA-F0-9]+)(?:/|$)', url)
        if match:
            return match.group(1)
        else:
            logging.error(f"Failed to extract file_id from URL: {url}")
            return None

    def sanitize_filename(self, filename):
        """
        Sanitizes a filename by removing/replacing invalid characters.

        Args:
            filename (str): The filename to sanitize

        Returns:
            str: The sanitized filename
        """
        # Remove or replace illegal characters
        filename = re.sub(r'[<>:"/\\|?*]', '', str(filename))

        # Replace spaces with underscores
        filename = filename.replace(' ', '_')

        # Replace other potentially problematic characters
        filename = filename.replace('&', 'and')

        # Remove non-ASCII characters
        filename = ''.join(char for char in filename if ord(char) < 128)

        # Remove any leading/trailing spaces or dots
        filename = filename.strip('. ')

        # Limit length
        max_length = 255  # Maximum filename length for most filesystems
        if len(filename) > max_length:
            base, ext = os.path.splitext(filename)
            filename = base[:max_length - len(ext)] + ext

        return filename

    def download_rapidgator_net(self, link, category_name, thread_id, thread_title, progress_callback=None, download_dir=None):
        """Enhanced Rapidgator download with progress tracking"""
        try:
            # Validate and refresh token if needed
            if not self.is_token_valid():
                logging.info("Rapidgator token expired or invalid. Re-authenticating.")
                if not self.api_login('backup'):
                    logging.error("Failed to re-authenticate Rapidgator download account.")
                    return False

            # Extract file_id from URL
            file_id = self.extract_file_id(link)
            if not file_id:
                logging.error(f"Could not extract file ID from URL: {link}")
                return False

            # Get download URL from API
            download_api_url = "https://rapidgator.net/api/v2/file/download"
            headers = {
                'Authorization': f'Bearer {self.rapidgator_token}',
                'Content-Type': 'application/json'
            }
            payload = {
                'token': self.rapidgator_token,
                'file_id': file_id
            }

            # Use provided download_dir or construct it
            if download_dir:
                download_path = download_dir
            else:
                sanitized_category = self.sanitize_filename(category_name)
                sanitized_thread_id = self.sanitize_filename(str(thread_id))
                download_path = os.path.join(self.download_dir, sanitized_category, sanitized_thread_id)
            os.makedirs(download_path, exist_ok=True)

            logging.info(f"Getting download URL for file {file_id}")
            response = requests.post(download_api_url, headers=headers, json=payload)

            logging.debug(f"API Response Status: {response.status_code}")
            logging.debug(f"API Response Content: {response.text}")

            if response.status_code != 200:
                logging.error(f"API request failed with status code: {response.status_code}")
                return False

            data = response.json()
            if not data or data.get('status') != 200:
                logging.error(f"API error: {data.get('details', 'Unknown error')}")
                return False

            download_url = data['response'].get('download_url')
            if not download_url:
                logging.error("No download URL in API response")
                return False

            # Start the actual download with progress tracking
            logging.info(f"Starting download from URL: {download_url}")
            file_response = requests.get(download_url, stream=True)
            total_size = int(file_response.headers.get('content-length', 0))

            if total_size == 0:
                logging.error("Could not determine file size")
                return False

            # Get filename from response headers or URL
            filename = None
            content_disp = file_response.headers.get('Content-Disposition')
            if content_disp:
                try:
                    params = self.parse_content_disposition(content_disp)
                    filename = params.get('filename')
                except Exception as e:
                    logging.warning(f"Error parsing Content-Disposition: {e}")

            if not filename:
                filename = os.path.basename(download_url)

            filename = self.sanitize_filename(filename)
            file_path = os.path.join(download_path, filename)

            logging.info(f"Downloading to: {file_path}")

            # Download with progress tracking
            downloaded_size = 0
            start_time = time.time()
            block_size = 8192

            with open(file_path, 'wb') as f:
                for chunk in file_response.iter_content(chunk_size=block_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)

                        if progress_callback:
                            elapsed_time = time.time() - start_time
                            speed = downloaded_size / elapsed_time if elapsed_time > 0 else 0
                            progress_callback(downloaded_size, total_size, os.path.basename(file_path))

                            if downloaded_size % (1024 * 1024) == 0:  # Log every MB
                                logging.debug(f"Downloaded: {downloaded_size}/{total_size} bytes")

            # Verify download
            if os.path.exists(file_path):
                actual_size = os.path.getsize(file_path)
                if total_size > 0 and actual_size != total_size:
                    logging.error(f"File size mismatch. Expected: {total_size}, Got: {actual_size}")
                    os.remove(file_path)
                    return False

                logging.info(f"Successfully downloaded {filename}")
                return file_path
            else:
                logging.error(f"File not found after download: {file_path}")
                return None

        except Exception as e:
            logging.error(f"Error downloading from Rapidgator: {str(e)}", exc_info=True)
            return None

    def download_katfile_net(self, url, category_name, thread_id, thread_title,
                             progress_callback=None, download_dir=None):
        """
        تحميل مباشر من Katfile (Premium أو Free) بدون API Key:
        1) يعمل login لمرة واحدة (Premium)
        2) يحاول direct-stream عبر header
        3) يحاول استخراج <a id="downloadbtn"> من HTML
        4) fallback إلى free-mode form
        """
        # 1) تحضير مجلد التنزيل
        dest_dir = download_dir or os.path.join(
            self.bot.download_dir,
            self.sanitize_filename(category_name),
            str(thread_id)
        )
        os.makedirs(dest_dir, exist_ok=True)

        # 2) login لمرة واحدة لو عندك credentials بريميوم
        if getattr(self, "_logged_in", False) is False and self.username and self.password:
            self._login()              # دالة login اللي عندك
            self._logged_in = True

        # 3) direct-stream عبر header
        try:
            r = self.session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True,
                stream=True,
                timeout=20
            )
            r.raise_for_status()
            cd = r.headers.get("content-disposition", "")
            if "filename" in cd.lower():
                m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^"\n]+)"?', cd)
                fname = m.group(1) if m else os.path.basename(url)
                return self._download_stream(r, fname, dest_dir, progress_callback)
        except Exception:
            logging.debug("Direct header download failed", exc_info=True)

        # 4) استخراج رابط من زر التحميل في HTML
        try:
            r2 = self.session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20
            )
            r2.raise_for_status()
            soup = BeautifulSoup(r2.text, "html.parser")
            btn = soup.find("a", id="downloadbtn") or soup.find("a", class_=re.compile(r"btn-download"))
            if btn and btn.get("href"):
                dl_url = urljoin(url, btn["href"])
                fname  = os.path.basename(dl_url.split("?",1)[0])
                return self._download_stream(dl_url, fname, dest_dir, progress_callback)
        except Exception:
            logging.debug("HTML button download failed", exc_info=True)

        # 5) fallback free-mode form
        return self._download_via_html_fallback(url, dest_dir, progress_callback)


    def download_katfile_com(self, link, category_name, thread_id, thread_title,
                             progress_callback=None, download_dir=None):
        """
        Alias متوافق مع download_links
        """
        return self.download_katfile_net(
            link,
            category_name,
            thread_id,
            thread_title,
            progress_callback,
            download_dir
        )


    def _download_stream(self, resp_or_url, filename, dest_dir, progress_callback):
        """
        يحمّل chunk-wise. يقبل requests.Response أو URL نصي.
        """
        # إذا جرى تمرير URL بدل response:
        if isinstance(resp_or_url, str):
            r = self.session.get(resp_or_url, headers={"User-Agent":"Mozilla/5.0"},
                                 stream=True, timeout=60)
            r.raise_for_status()
        else:
            r = resp_or_url

        outpath = os.path.join(dest_dir, filename)
        total   = int(r.headers.get("content-length", 0)) or None
        dl      = 0

        try:
            with open(outpath, "wb") as f:
                for chunk in r.iter_content(8192):
                    if not chunk: continue
                    f.write(chunk)
                    dl += len(chunk)
                    if progress_callback and total:
                        progress_callback(dl, total, filename)
        except Exception as e:
            logging.error("Download error %s: %s", outpath, e, exc_info=True)
            if os.path.exists(outpath):
                os.remove(outpath)
            return False

        logging.info("Downloaded Katfile file: %s", outpath)
        return True


    def sanitize_filename(self, filename):
        """Sanitize filename to remove or replace invalid characters"""
        # Normalize Unicode characters
        normalized = unicodedata.normalize('NFKD', filename)
        # Encode to ASCII bytes, ignore errors (this removes non-ASCII chars)
        ascii_bytes = normalized.encode('ASCII', 'ignore')
        # Decode back to string
        sanitized = ascii_bytes.decode('ASCII')
        # Remove invalid characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '', sanitized)
        sanitized = sanitized.replace(' ', '_')
        # Remove any remaining non-printable characters
        sanitized = ''.join(c for c in sanitized if c.isprintable())
        return sanitized.strip()

    def parse_content_disposition(self, content_disp: str) -> dict:
        """
        Parse Content-Disposition header.

        Args:
            content_disp (str): Content-Disposition header value

        Returns:
            dict: Dictionary of parsed parameters
        """
        try:
            import email.parser
            import email.policy

            parser = email.parser.HeaderParser()
            header = parser.parsestr(f'Content-Disposition: {content_disp}')
            params = dict(header.get_params(header='content-disposition'))

            # Clean up parameters
            if 'Content-Disposition' in params:
                del params['Content-Disposition']

            return params
        except Exception as e:
            logging.warning(f"Error parsing Content-Disposition: {str(e)}")
            return {}

    def extract_file_id(self, url: str) -> Optional[str]:
        """
        Enhanced file ID extraction with better error handling.

        Args:
            url (str): Rapidgator URL

        Returns:
            Optional[str]: File ID if found, None otherwise
        """
        try:
            # Handle both short and long URL formats
            if 'rg.to' in url:
                match = re.search(r'/([a-fA-F0-9]+)(?:/|$)', url)
            else:
                match = re.search(r'/file/([a-fA-F0-9]+)(?:/|$)', url)

            if match:
                file_id = match.group(1)
                logging.debug(f"Extracted file ID: {file_id} from URL: {url}")
                return file_id
            else:
                logging.error(f"Failed to extract file ID from URL: {url}")
                return None
        except Exception as e:
            logging.error(f"Error extracting file ID: {str(e)}")
            return None

    # -----------------------------------
    # 3.2 Upload Links Using Configured Upload Hosts # NEW
    # -----------------------------------
    def get_upload_rapidgator_token(self, upload_username: str, upload_password: str) -> str:
        """
        Authenticate with Rapidgator and retrieve an upload access token,
        ثمّ تحفظه في DATA_DIR.

        Parameters:
        - upload_username (str): Rapidgator upload account username.
        - upload_password (str): Rapidgator upload account password.

        Returns:
        - str: Access token if successful, None otherwise.
        """
        try:
            auth_url = "https://rapidgator.net/api/v2/user/login"
            payload = {"username": upload_username, "password": upload_password}
            headers = {"Content-Type": "application/json"}

            response = requests.post(auth_url, data=json.dumps(payload), headers=headers)
            if response.status_code == 200:
                data = response.json()
                # الحالة الناجحة في API ترجع status == 200 و response موجود
                if data.get('status') == 200 and data.get('response'):
                    token = data['response']['token']
                    # خزّن التوكن في الخاصية المخصّصة للرفع
                    self.upload_rapidgator_token = token
                    logging.info("Rapidgator upload token retrieved successfully.")
                    # احفظ التوكن في الملف
                    try:
                        self.save_token('upload')
                    except Exception as e:
                        logging.warning(f"Failed to auto-save upload token: {e}")
                    return token
                else:
                    logging.error(f"Rapidgator authentication failed: {data.get('details')}")
                    return None
            else:
                logging.error(f"Rapidgator authentication HTTP error: {response.status_code}")
                return None
        except Exception as e:
            # استخدم handle_exception للمعالجة الموّحدة
            self.handle_exception("Rapidgator authentication", e)
            return None

    def calculate_md5(self, file_path, chunk_size=8192):
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                md5.update(chunk)
        return md5.hexdigest()

    def initiate_upload_session(self, file_path, folder_id=None, multipart=True, max_retries=3, delay=5):
        """
        Initiates an upload session with multiple hosts.
        """
        try:
            uploaded_urls = []  # Store URLs from all file hosts
            backup_rg_url = ''  # Store Rapidgator backup URL

            # Step 1: Rapidgator Upload
            logging.info(f"Initiating Rapidgator upload for {os.path.basename(file_path)}...")
            rapidgator_url = None

            # Validate upload token
            if not self.validate_and_refresh_upload_token():
                logging.error("Failed to obtain valid upload token. Skipping Rapidgator upload.")
            else:
                upload_url = "https://rapidgator.net/api/v2/file/upload"
                file_name = os.path.basename(file_path)
                file_size = os.path.getsize(file_path)
                md5_hash = self.calculate_md5(file_path)

                payload = {
                    "token": self.upload_rapidgator_token,
                    "name": file_name,
                    "hash": md5_hash,
                    "size": file_size,
                    "multipart": multipart
                }

                if folder_id:
                    payload["folder_id"] = folder_id

                # Initialize upload
                response = requests.post(upload_url, json=payload, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 200 and data.get('response'):
                        upload_info = data['response']['upload']
                        if upload_info['state'] == 0:
                            upload_id = upload_info['upload_id']
                            upload_process_url = upload_info['url']

                            # Perform actual file upload
                            if self.upload_file(upload_process_url, file_path):
                                # Check upload status and get URL
                                for _ in range(10):  # Check status up to 10 times
                                    status_response = requests.get(
                                        "https://rapidgator.net/api/v2/file/upload_info",
                                        params={
                                            'token': self.upload_rapidgator_token,
                                            'upload_id': upload_id
                                        }
                                    )
                                    if status_response.status_code == 200:
                                        status_data = status_response.json()
                                        if status_data.get('status') == 200:
                                            upload_info = status_data['response']['upload']
                                            if upload_info['state'] == 2:  # Upload complete
                                                rapidgator_url = upload_info['file']['url']
                                                if rapidgator_url:
                                                    logging.info(
                                                        f"Rapidgator upload completed successfully: {rapidgator_url}")
                                                    uploaded_urls.append(rapidgator_url)
                                                    break
                                    time.sleep(2)

            # Continue with other hosts even if Rapidgator fails
            # Step 2: Nitroflare Upload
            logging.info("Uploading to Nitroflare...")
            try:
                nitroflare_url = self.upload_to_nitroflare(file_path)
                if nitroflare_url:
                    logging.info(f"Nitroflare upload successful: {nitroflare_url}")
                    uploaded_urls.append(nitroflare_url)
            except Exception as e:
                logging.error(f"Nitroflare upload error: {str(e)}")

            # Step 3: DDownload Upload
            logging.info("Uploading to DDownload...")
            try:
                ddownload_url = self.upload_to_ddownload(file_path)
                if ddownload_url:
                    logging.info(f"DDownload upload successful: {ddownload_url}")
                    uploaded_urls.append(ddownload_url)
            except Exception as e:
                logging.error(f"DDownload upload error: {str(e)}")

            # Step 4: KatFile Upload
            logging.info("Uploading to KatFile...")
            try:
                katfile_url = self.upload_to_katfile(file_path)
                if katfile_url:
                    logging.info(f"KatFile upload successful: {katfile_url}")
                    uploaded_urls.append(katfile_url)
            except Exception as e:
                logging.error(f"KatFile upload error: {str(e)}")

            # Step 5: Rapidgator Backup Upload (optional)
            backup_rg_url = ''
            if self.use_backup_rg:
                try:
                    backup_rg_url = self.upload_to_rapidgator_backup(file_path)
                    if backup_rg_url:
                        logging.info(
                            f"Rapidgator backup successful: {backup_rg_url}"
                        )
                except Exception as e:
                    logging.error(f"Rapidgator backup upload error: {str(e)}")
                    backup_rg_url = ''
            else:
                logging.debug("Rapidgator backup disabled; skipping upload")

            # Return results if any uploads were successful
            if uploaded_urls:
                return {
                    'uploaded_urls': uploaded_urls,
                    'backup_rg_url': backup_rg_url
                }

            return None

        except Exception as e:
            logging.error(f"Exception during upload session: {str(e)}", exc_info=True)
            return None

    def handle_rapidgator_upload(self, file_path, row, host_progress_bars):
        """
        Handler for Rapidgator uploads with proper progress tracking.
        """
        try:
            filename = os.path.basename(file_path)
            self.update_host_progress(host_progress_bars['rapidgator'], 0, "Initializing...")

            # Initialize upload session
            upload_result = self.initiate_upload_session(file_path)

            if upload_result and isinstance(upload_result, dict):
                # Check for Rapidgator URL in uploaded_urls
                rapidgator_urls = [url for url in upload_result.get('uploaded_urls', [])
                                   if 'rapidgator.net' in url]

                if rapidgator_urls:
                    self.update_host_progress(
                        host_progress_bars['rapidgator'],
                        100,
                        "Complete",
                        success=True
                    )
                    return rapidgator_urls[0]

            self.update_host_progress(
                host_progress_bars['rapidgator'],
                0,
                "Failed",
                error=True
            )
            return None

        except Exception as e:
            logging.error(f"Error in Rapidgator upload: {str(e)}")
            self.update_host_progress(
                host_progress_bars['rapidgator'],
                0,
                f"Error: {str(e)}",
                error=True
            )
            return None

    def check_rapidgator_upload_status(self, upload_id):
        """Enhanced status checker for Rapidgator uploads."""
        try:
            if not self.upload_rapidgator_token:
                logging.error("Rapidgator upload token is not set. Cannot check upload status.")
                return None

            upload_info_url = "https://rapidgator.net/api/v2/file/upload_info"
            params = {
                'token': self.upload_rapidgator_token,
                'upload_id': upload_id
            }

            response = requests.get(upload_info_url, params=params)
            if response.status_code != 200:
                return 'error'

            data = response.json()
            if data.get('status') != 200:
                return 'error'

            upload_info = data.get('response', {}).get('upload', {})
            state = upload_info.get('state')

            if state == 2:  # Completed
                return 'completed'
            elif state == 1:  # Processing
                return 'processing'
            else:
                return 'error'

        except Exception as e:
            logging.error(f"Error checking Rapidgator upload status: {str(e)}")
            return 'error'

    def get_rapidgator_file_url(self, upload_id):
        """Enhanced URL retriever for Rapidgator uploads."""
        try:
            info_url = "https://rapidgator.net/api/v2/file/upload_info"
            params = {
                'token': self.upload_rapidgator_token,
                'upload_id': upload_id
            }

            response = requests.get(info_url, params=params)
            if response.status_code != 200:
                return None

            data = response.json()
            if data.get('status') != 200:
                return None

            file_info = data.get('response', {}).get('upload', {}).get('file', {})
            return file_info.get('url')

        except Exception as e:
            logging.error(f"Error retrieving Rapidgator file URL: {str(e)}")
            return None

    def validate_and_refresh_upload_token(self):
        """
        Validates the current upload token and refreshes if needed.
        Returns True if a valid token is available after validation/refresh.
        """
        try:
            # First try to validate existing token
            if self.is_upload_token_valid():
                if self.check_upload_permissions():  # Additional validation
                    return True

            # Token invalid or expired, attempt to refresh
            logging.info("Upload token invalid or expired. Attempting refresh...")
            if self.api_login('main'):
                # Verify the new token works
                if self.check_upload_permissions():
                    return True
                else:
                    logging.error("New token obtained but permissions check failed")
                    return False
            else:
                logging.error("Failed to refresh upload token")
                return False
        except Exception as e:
            logging.error(f"Error validating/refreshing upload token: {e}")
            return False

    def update_keeplinks_links(self, keeplinks_url, new_links):
        """Update a Keeplinks URL with new links and return the updated URL."""
        try:
            # Extract the URL ID from the keeplinks_url
            url_id = self.extract_keeplinks_url_id(keeplinks_url)
            if not url_id:
                logging.error("Failed to extract URL ID from Keeplinks URL.")
                return None

            # Prepare the API parameters
            api_url = "https://www.keeplinks.org/api.php"
            api_hash = (
                self.config.get('keeplinks_api_hash', '').strip()
                or os.getenv("KEEP_LINKS_API_HASH", "").strip()
            )
            if not api_hash:
                logging.error("Keeplinks API hash is missing")
                return None
            # Flatten potential nested lists and sanitize URLs
            flat_links = []
            for link in new_links:
                if isinstance(link, (list, tuple)):
                    flat_links.extend(link)
                else:
                    flat_links.append(link)

            from urllib.parse import urlparse, quote

            def extract_base_rg(url):
                parsed = urlparse(url)
                if parsed.netloc.lower() == 'rapidgator.net' and parsed.path.startswith('/file/'):
                    parts = parsed.path.split('/')
                    if len(parts) >= 3:
                        base = '/'.join(parts[:3]) + '/'
                        return f"{parsed.scheme}://{parsed.netloc}{base}"
                return url

            processed = [extract_base_rg(u) for u in flat_links]
            sanitized = [self.sanitize_url(u) for u in processed]
            encoded = [quote(u, safe=':/?=&,') for u in sanitized]
            grouped = self.group_links_by_host(encoded)
            formatted = self.format_links_for_keeplinks(grouped)
            all_urls_string = ','.join(formatted)
            api_params = {
                'apihash': api_hash,
                'url-id': url_id,
                'link-to-protect': all_urls_string,
                'output': 'xml'
            }
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/xml'
            }

            # Send the request
            response = requests.post(api_url, data=api_params, headers=headers)
            response.raise_for_status()
            response_text = response.text.strip()
            logging.debug(f"Keeplinks API Response Text: {response_text}")

            # Parse the response to confirm the update
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response_text)
            error_elem = root.find('api_error')
            if error_elem is not None:
                logging.error(f"Keeplinks API Error: {error_elem.text}")
                return None
            else:
                p_links_elem = root.find('p_links')
                if p_links_elem is not None:
                    updated_keeplinks_url = p_links_elem.text.strip()
                    return updated_keeplinks_url
                else:
                    logging.error("Failed to get updated Keeplinks URL from response.")
                    return None
        except Exception as e:
            logging.error(f"Error updating Keeplinks links: {e}", exc_info=True)
            return None

    def extract_keeplinks_url_id(self, keeplinks_url):
        # Assuming the URL ID is the last part of the URL
        # e.g., https://www.keeplinks.org/p42/6713cf408f886
        try:
            url_parts = keeplinks_url.rstrip('/').split('/')
            url_id = url_parts[-1]
            return url_id
        except Exception as e:
            logging.error(f"Error extracting URL ID from Keeplinks URL: {e}")
            return None

    def check_rapidgator_link_alive(self, link):
        try:
            response = requests.head(link, allow_redirects=True)
            if response.status_code == 200:
                return True
            elif response.status_code == 404:
                return False
            else:
                # Handle other status codes if necessary
                return False
        except Exception as e:
            logging.error(f"Error checking Rapidgator link '{link}': {e}")
            return False

    def init_timers(self):
        """Initialize timers for periodic tasks."""
        self.link_check_timer = QTimer()
        self.link_check_timer.timeout.connect(self.check_rapidgator_links)
        self.link_check_timer.start(3600000)  # Check every hour (3600000 ms)

    def upload_file(self, upload_process_url, file_path):
        """
        Upload a file to Rapidgator with improved success detection.
        """
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            md5_hash = self.calculate_md5(file_path)

            with open(file_path, 'rb') as f:
                files = {'file': (file_name, f)}
                data = {
                    'token': self.upload_rapidgator_token,
                    'name': file_name,
                    'hash': md5_hash,
                    'size': str(file_size)
                }

                response = requests.post(upload_process_url, files=files, data=data)
                if response.status_code == 200:
                    return True  # Just return True here, actual URL will be retrieved later
                return False

        except Exception as e:
            logging.error(f"Error uploading file to Rapidgator: {str(e)}")
            return False

    def upload_to_nitroflare(self, file_path, progress_callback=None):
        """
        Uploads a file to Nitroflare and returns the download URL.
        Modified to return the URL in the format:
        https://nitroflare.com/view/<FILE_ID>/
        """
        try:
            # Step 1: Get Nitroflare server URL
            server_url = requests.get("http://nitroflare.com/plugins/fileupload/getServer").text.strip()
            logging.info(f"Received Nitroflare server URL: {server_url}")

            nitroflare_user_hash = os.getenv('NITROFLARE_USER_HASH')  # User hash from .env
            if not nitroflare_user_hash:
                logging.error("Nitroflare user hash is not configured in environment variables.")
                return None

            # Step 2: Create MultipartEncoder for upload with progress tracking
            encoder = MultipartEncoder(
                fields={
                    'files': (os.path.basename(file_path), open(file_path, 'rb')),
                    'user': nitroflare_user_hash
                }
            )

            total_size = os.path.getsize(file_path)

            def upload_callback(monitor):
                if progress_callback:
                    progress_callback(monitor.bytes_read, total_size)

            monitor = MultipartEncoderMonitor(encoder, upload_callback)

            # Step 3: Upload the file with progress tracking
            headers = {'Content-Type': monitor.content_type}
            response = requests.post(server_url, data=monitor, headers=headers)
            logging.debug(f"Nitroflare Response: {response.text}")

            if response.status_code == 200:
                data = response.json()

                # The response should have a 'files' key with the upload info
                if 'files' in data and len(data['files']) > 0:
                    nitroflare_url = data['files'][0].get('url')
                    if nitroflare_url:
                        logging.info(f"File uploaded successfully to Nitroflare: {nitroflare_url}")

                        # Original URL format (example):
                        # https://nitroflare.com/view/<FILE_ID>/<FILENAME>
                        #
                        # Desired format:
                        # https://nitroflare.com/view/<FILE_ID>/

                        from urllib.parse import urlparse
                        parsed = urlparse(nitroflare_url)
                        path_parts = parsed.path.strip('/').split('/')
                        # Expecting path_parts[0] = 'view', path_parts[1] = <FILE_ID>
                        if len(path_parts) >= 2 and path_parts[0].lower() == 'view':
                            file_id = path_parts[1]
                            # Construct the simplified URL with view and trailing slash
                            simplified_url = f"https://nitroflare.com/view/{file_id}/"
                            logging.info(f"Simplified Nitroflare URL: {simplified_url}")
                            return simplified_url
                        else:
                            # If the format is unexpected, return the original URL or None
                            logging.warning("Unexpected Nitroflare URL format. Returning original URL.")
                            return nitroflare_url
                    else:
                        logging.error("Failed to extract Nitroflare URL from response.")
                        return None
                else:
                    logging.error(f"Unexpected response format from Nitroflare: {data}")
                    return None
            else:
                logging.error(f"Nitroflare upload failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logging.error(f"Exception during Nitroflare upload: {e}", exc_info=True)
            return None

    def upload_to_ddownload(self, file_path, progress_callback=None):
        """
        Uploads a file to DDownload and returns the download URL.
        """
        try:
            # Step 1: Get the upload server URL
            api_key = os.getenv('DDOWNLOAD_API_KEY')  # Ensure API key is in .env
            server_response = requests.get(f"https://api-v2.ddownload.com/api/upload/server?key={api_key}")
            logging.debug(f"DDownload Server Response: {server_response.text}")

            if server_response.status_code == 200:
                server_data = server_response.json()
                upload_url = server_data.get('result')
                sess_id = server_data.get('sess_id')

                if upload_url and sess_id:
                    # Step 2: Create MultipartEncoder for upload with progress tracking
                    encoder = MultipartEncoder(
                        fields={
                            'file': (os.path.basename(file_path), open(file_path, 'rb')),
                            'sess_id': sess_id,
                            'utype': 'prem'
                        }
                    )

                    # Create a monitor for progress tracking
                    total_size = os.path.getsize(file_path)
                    last_bytes_read = 0

                    def upload_callback(monitor):
                        nonlocal last_bytes_read
                        if progress_callback:
                            bytes_read = monitor.bytes_read
                            # Only update if there's actual progress
                            if bytes_read > last_bytes_read:
                                progress_callback(bytes_read, total_size)
                                last_bytes_read = bytes_read

                    monitor = MultipartEncoderMonitor(encoder, upload_callback)

                    # Step 3: Upload the file with progress tracking
                    headers = {'Content-Type': monitor.content_type}
                    response = requests.post(upload_url, data=monitor, headers=headers, verify=False)
                    logging.debug(f"DDownload Upload Response: {response.text}")

                    if response.status_code == 200:
                        data = response.json()[0]  # Extract first file info
                        file_code = data.get('file_code')

                        if file_code:
                            download_url = f"https://ddownload.com/{file_code}"
                            logging.info(f"File uploaded successfully to DDownload: {download_url}")
                            # Final progress update
                            if progress_callback:
                                progress_callback(total_size, total_size)
                            return download_url
                        else:
                            logging.error(f"Failed to retrieve file code from DDownload: {data}")
                            return None
                    else:
                        logging.error(f"DDownload upload failed: {response.status_code} - {response.text}")
                        return None
                else:
                    logging.error("Failed to get DDownload upload server URL or session ID.")
                    return None
            else:
                logging.error(f"DDownload server request failed: {server_response.status_code}")
                return None

        except Exception as e:
            logging.error(f"Exception during DDownload upload: {e}", exc_info=True)
            return None

    def upload_to_katfile(self, file_path, progress_callback=None):
        """
        Uploads a file to KatFile and returns the download URL.
        """
        try:
            # Step 1: Get the upload server URL
            api_key = os.getenv('KATFILE_API_KEY')  # Ensure the API key is in .env
            server_response = requests.get(f"https://katfile.com/api/upload/server?key={api_key}")
            logging.debug(f"KatFile Server Response: {server_response.text}")

            if server_response.status_code == 200:
                server_data = server_response.json()
                upload_url = server_data.get('result')
                sess_id = server_data.get('sess_id')

                if upload_url and sess_id:
                    # Step 2: Create MultipartEncoder for upload with progress tracking
                    encoder = MultipartEncoder(
                        fields={
                            'file': (os.path.basename(file_path), open(file_path, 'rb')),
                            'sess_id': sess_id,
                            'utype': 'prem'  # Premium user type
                        }
                    )

                    # Create a monitor for progress tracking
                    total_size = os.path.getsize(file_path)
                    last_bytes_read = 0

                    def upload_callback(monitor):
                        nonlocal last_bytes_read
                        if progress_callback:
                            bytes_read = monitor.bytes_read
                            # Only update if there's actual progress
                            if bytes_read > last_bytes_read:
                                progress_callback(bytes_read, total_size)
                                last_bytes_read = bytes_read

                    monitor = MultipartEncoderMonitor(encoder, upload_callback)

                    # Step 3: Upload the file with progress tracking
                    headers = {'Content-Type': monitor.content_type}
                    response = requests.post(upload_url, data=monitor, headers=headers, verify=False)
                    logging.debug(f"KatFile Upload Response: {response.text}")

                    if response.status_code == 200:
                        data = response.json()[0]  # Extract first file info
                        file_code = data.get('file_code')

                        if file_code:
                            download_url = f"https://katfile.com/{file_code}"
                            logging.info(f"File uploaded successfully to KatFile: {download_url}")
                            # Final progress update
                            if progress_callback:
                                progress_callback(total_size, total_size)
                            return download_url
                        else:
                            logging.error(f"Failed to retrieve file code from KatFile: {data}")
                            return None
                    else:
                        logging.error(f"KatFile upload failed: {response.status_code} - {response.text}")
                        return None
                else:
                    logging.error("Failed to get KatFile upload server URL or session ID.")
                    return None
            else:
                logging.error(f"KatFile server request failed: {server_response.status_code}")
                return None

        except Exception as e:
            logging.error(f"Exception during KatFile upload: {e}", exc_info=True)
            return None

    def upload_to_rapidgator_backup(self, file_path: str, progress_callback=None) -> str | None:
        """
        Upload a file to the *backup* Rapidgator account and return its public URL.

        Args:
            file_path (str): Local path to the file.
            progress_callback (callable, optional): Called as progress_callback(bytes_sent, total_bytes).

        Returns:
            str | None: Rapidgator download URL, or None on failure.
        """
        try:
            # ------------------------------------------------------------------
            # 0) Ensure we have a valid token for the backup account
            # ------------------------------------------------------------------
            if not self.ensure_valid_token("backup"):
                logging.error("Backup token invalid and refresh failed.")
                return None

            # ------------------------------------------------------------------
            # 1) Initialise the upload session
            # ------------------------------------------------------------------
            init_url = "https://rapidgator.net/api/v2/file/upload"
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            md5_hash = self.calculate_md5(file_path)

            payload = {
                "token": self.rg_backup_token,
                "name": file_name,
                "hash": md5_hash,
                "size": file_size,
                "multipart": True,
            }

            resp = requests.post(init_url, json=payload,
                                 headers={"Content-Type": "application/json"},
                                 timeout=30)
            if resp.status_code != 200:
                logging.error("Init failed (%s): %s", resp.status_code, resp.text)
                return None

            data = resp.json()
            if data.get("status") != 200 or not data.get("response"):
                logging.error("Init error: %s", data.get("details"))
                return None

            upload = data["response"]["upload"]
            upload_id = upload.get("upload_id")
            upload_url = upload.get("url")
            if not upload_url:
                logging.error("No upload URL returned by Rapidgator.")
                return None

            # ------------------------------------------------------------------
            # 2) Perform the actual file upload (streamed multipart)
            #     self.upload_file() should return True on success.
            # ------------------------------------------------------------------
            if not self.upload_file(upload_url, file_path, progress_callback=progress_callback):
                logging.error("File transfer step failed.")
                return None

            # ------------------------------------------------------------------
            # 3) Poll the API until RG finishes processing the upload
            # ------------------------------------------------------------------
            info_url = "https://rapidgator.net/api/v2/file/upload_info"
            for _ in range(10):  # ~20 s total (10 × 2 s)
                info_resp = requests.get(
                    info_url,
                    params={"token": self.rg_backup_token, "upload_id": upload_id},
                    timeout=15,
                )
                if info_resp.status_code == 200:
                    info = info_resp.json()
                    if info.get("status") == 200:
                        up = info["response"]["upload"]
                        state = up.get("state", 0)  # 0=uploading,1=processing,2=done,3=fail
                        if state == 2:
                            return up["file"]["url"]
                        if state == 3:
                            logging.error("Rapidgator marked upload as failed.")
                            return None
                time.sleep(2)

            logging.error("Upload did not reach 'done' state within timeout.")
            return None

        except Exception as exc:
            logging.exception("Rapidgator backup upload failed: %s", exc)
            return None

    def save_backup_links(self, file_path: str, backup_urls: list, keeplinks_url: str):
        """
        Save the backup links along with the Keeplinks URL into the data directory.

        Parameters:
        - self: يجب أن تكون هذه الدالة جزءًا من كلاس يحتوي على self.config
        - file_path: المسار إلى مجلّد الـ thread (أو أى مُعرف آخر)
        - backup_urls: قائمة روابط Mega.nz
        - keeplinks_url: رابط Keeplinks الناتج
        """
        # 1) احصل على مسار مجلّد البيانات من الإعدادات (أو استخدم cwd كافتراضي)
        data_dir = self.config.get('data_dir', os.getcwd())
        # تأكد من وجود المجلّد
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # 2) جهّز هيكل البيانات للحفظ
        backup_data = {
            'file_path': file_path,
            'backup_urls': backup_urls,  # قائمة روابط Mega.nz
            'keeplinks_url': keeplinks_url,
            'timestamp': datetime.now().isoformat()
        }

        # 3) حدّد اسم الملف بناءً على thread_id أو اسم المجلّد
        thread_id = Path(file_path).name
        filename = f'backup_{thread_id}.json'
        full_path = os.path.join(data_dir, filename)

        # 4) اكتب الملف بترميز UTF-8 وتنسيق جميل
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=4, ensure_ascii=False)
            logging.info(f"Backup data saved for '{thread_id}' at '{full_path}'.")
        except Exception as e:
            logging.error(f"Failed to save backup data for '{thread_id}': {e}", exc_info=True)

    def calculate_md5(self, file_path):
        """Calculate MD5 hash of the given file."""
        import hashlib
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def retrieve_rapidgator_file_url(self, upload_id, max_retries=20, retry_delay=3):
        """
        Retrieves the file URL for a successfully uploaded file on Rapidgator.
        Polls the upload status until it is complete.

        Parameters:
        - upload_id (str): The upload ID received after successful file upload
        - max_retries (int): Maximum number of retry attempts
        - retry_delay (int): Delay in seconds between retries

        Returns:
        - str: The URL of the uploaded file, or None if retrieval fails
        """
        try:
            logging.info(f"Starting file URL retrieval process for upload ID: {upload_id}")

            # Step 1: Check upload permissions
            if not self.check_upload_permissions():
                logging.error("Insufficient permissions for file URL retrieval. Aborting process.")
                return None

            # Step 2: Load the upload token
            if not self.load_token('main'):
                logging.error("Failed to load upload token. Aborting file URL retrieval.")
                return None

            # Step 3: Retrieve file URL
            info_url = "https://rapidgator.net/api/v2/file/upload_info"

            for attempt in range(1, max_retries + 1):
                params = {
                    'token': self.upload_rapidgator_token,
                    'upload_id': upload_id
                }

                logging.debug(f"Attempt {attempt}: Sending file info request to {info_url}")
                logging.debug(f"Attempt {attempt}: Request params: {params}")

                try:
                    response = requests.get(info_url, params=params, timeout=10)
                    logging.debug(
                        f"Attempt {attempt}: File info response - Status: {response.status_code}, Content: {response.text}")
                except requests.Timeout:
                    logging.error(f"Attempt {attempt}: Request timed out. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                except Exception as e:
                    logging.error(f"Attempt {attempt}: Exception during file info request: {e}", exc_info=True)
                    time.sleep(retry_delay)
                    continue

                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 200:
                        upload_info = data.get('response', {}).get('upload', {})
                        if upload_info:
                            state = upload_info.get('state')
                            state_label = upload_info.get('state_label')

                            if state == 2:  # Upload is complete
                                file_info = upload_info.get('file', {})
                                if 'url' in file_info:
                                    file_url = file_info['url']
                                    logging.info(f"File URL retrieved successfully: {file_url}")
                                    return file_url
                                else:
                                    logging.warning("File URL missing from upload info.")
                                    return None
                            elif state == 1:  # Processing
                                logging.info(
                                    f"Attempt {attempt}: File still processing. Current state: {state_label}. Retrying in {retry_delay} seconds...")
                            else:
                                logging.warning(
                                    f"Attempt {attempt}: Unexpected state: {state_label}. Retrying in {retry_delay} seconds...")
                        else:
                            logging.warning("No 'upload' info found in response.")
                    else:
                        logging.error(f"Attempt {attempt}: Error in file info response: {data.get('details')}")
                        return None
                else:
                    logging.error(
                        f"Attempt {attempt}: Failed to retrieve file info. Status code: {response.status_code}")
                    return None

                if attempt < max_retries:
                    time.sleep(retry_delay)

            logging.error(f"Max retries ({max_retries}) reached. Failed to retrieve file URL.")
            return None

        except Exception as e:

            self.handle_exception("retrieving file URL", e)

            return None

    def check_upload_permissions(self):
        """
        Check if the current account has permission to upload files.

        Returns:
        - bool: True if upload permissions are confirmed, False otherwise.
        """
        try:
            info_url = "https://rapidgator.net/api/v2/user/info"
            params = {'token': self.upload_rapidgator_token}
            response = requests.get(info_url, params=params)
            logging.debug(f"Permission check response - Status: {response.status_code}, Content: {response.text}")

            if response.status_code != 200:
                logging.error(f"Failed to check permissions. Status code: {response.status_code}")
                return False

            data = response.json()
            if data.get('status') != 200:
                logging.error(f"Failed to check permissions: {data.get('details')}")
                return False

            user_info = data.get('response', {}).get('user', {})

            # Check if the account is premium and activated
            is_premium = user_info.get('is_premium', False)
            is_activated = user_info.get('state', 0) == 1  # Assuming 1 means activated

            # Check if there's upload information
            upload_info = user_info.get('upload', {})
            max_file_size = upload_info.get('max_file_size', 0)

            can_upload = is_premium and is_activated and max_file_size > 0

            logging.info(f"Upload permission check result: {can_upload}")
            logging.debug(f"Is Premium: {is_premium}, Is Activated: {is_activated}, Max File Size: {max_file_size}")

            return can_upload

        except Exception as e:

            self.handle_exception("checking upload permissions", e)

            return False

    def upload_file_and_update_thread(self, file_path, category_name, thread_id):
        """
        Uploads a file to Rapidgator and updates the corresponding thread with the file URL.

        Parameters:
        - file_path (str): Path to the file to upload.
        - category_name (str): Name of the category.
        - thread_id (str): ID of the thread.

        Returns:
        - bool: True if upload and update are successful, False otherwise.
        """
        try:
            logging.info(
                f"Starting upload process for file: {file_path}, Category: {category_name}, Thread ID: {thread_id}")

            # Initiate upload session and upload the file
            file_url = self.initiate_upload_session(file_path)
            if not file_url:
                logging.error(f"Failed to upload file: {file_path}")
                return False

            logging.info(f"File uploaded successfully. URL: {file_url}")

            # Update the process threads with the new link
            if thread_id in self.process_threads:
                self.process_threads[thread_id]['new_link'] = file_url
                logging.info(f"Updated thread {thread_id} with new link {file_url}")
                # Emit signal or handle accordingly in the GUI
                # self.update_threads.emit(category_name, self.process_threads)
                return True
            else:
                logging.error(f"Thread ID {thread_id} not found in process_threads.")
                return False

        except Exception as e:

                self.handle_exception(f"upload for thread {thread_id}", e)

                return False

    def check_upload_upload_status(self, upload_id):
        """
        Check the status of an ongoing upload session for the upload account.

        Parameters:
        - upload_id (str): The upload session ID.

        Returns:
        - dict: Contains 'state' and 'state_label' if successful, None otherwise.
        """
        try:
            if not self.upload_rapidgator_token:
                logging.error("Rapidgator upload token is not set. Cannot check upload status.")
                return None

            upload_info_url = "https://rapidgator.net/api/v2/file/upload_info"
            payload = {
                "token": self.upload_rapidgator_token,
                "upload_id": upload_id
            }

            headers = {
                "Content-Type": "application/json"
            }

            response = requests.post(upload_info_url, data=json.dumps(payload), headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200 and data.get('response'):
                    upload_info = data['response']['upload']
                    logging.info(f"Upload status checked. State: {upload_info['state_label']}")
                    return {
                        "state": upload_info['state'],
                        "state_label": upload_info['state_label']
                    }
                else:
                    logging.error(f"Failed to check upload status: {data.get('details')}")
                    return None
            else:
                logging.error(f"HTTP error during upload status check: {response.status_code}")
                return None
        except Exception as e:
                self.handle_exception("upload status check", e)
                return None

    # -----------------------------------
    # 3.3 Backup Links Using Configured Backup Host # NEW
    # -----------------------------------
    def backup_links(self, links):
        """
        Backup links using the configured backup host.

        Parameters:
        - links (list): List of URLs to backup.
        """
        backup_host = self.backup_host.get('host', '')
        if not backup_host:
            logging.warning("No backup host configured.")
            return

        method_name = f"backup_{backup_host.replace('.', '_')}"
        method = getattr(self, method_name, None)
        if method:
            logging.info(f"Starting backup using host '{backup_host}'.")
            method(links)
        else:
            logging.error(f"No backup method implemented for host '{backup_host}'.")

    def extract_url_id(self, keeplinks_url: str) -> str:
        """
        Extracts the url-id from a given Keeplinks URL.
        Keeplinks URLs look like: https://www.keeplinks.org/p42/<url-id> or
        https://www.keeplinks.org/r42/<url-id>

        We'll split by '/' and take the last part as url-id.
        """
        if not keeplinks_url:
            return ""
        parts = keeplinks_url.strip().split('/')
        if parts:
            return parts[-1]  # The last segment should be the url-id
        return ""

    def insert_into_keeplinks(self, urls):
        """
        Inserts uploaded file URLs into keeplinks.org and returns the public Keeplinks URL.
        This creates a new Keeplinks link with only recaptcha enabled.
        """
        keeplinks_api_url = "https://www.keeplinks.org/api.php"
        api_hash = (
            os.getenv("KEEP_LINKS_API_HASH", "").strip()
            or self.config.get('keeplinks_api_hash', '').strip()
        )
        if not api_hash:
            logging.error("Keeplinks API hash is missing")
            return False

        # Join URLs into a comma-separated string
        links_to_protect = ",".join(urls)

        payload = {
            "apihash": api_hash,
            "link-to-protect": links_to_protect,
            "output": "json",
            "captcha": "on",
            "captchatype": "Re"
        }

        try:
            response = requests.post(keeplinks_api_url, data=payload, timeout=30)

            logging.debug(f"Keeplinks (insert) API Response: {response.text}")

            if response.status_code == 200:
                data = response.json()
                # Extract either the public or restricted link
                keeplinks_url = data.get("p_links") or data.get("r_links")

                if keeplinks_url:
                    logging.info(f"Keeplinks URL generated: {keeplinks_url}")
                    return keeplinks_url
                else:
                    logging.error(f"Failed to extract Keeplinks URL from response: {data}")
                    return None
            else:
                logging.error(f"Keeplinks API error on insert: {response.status_code}. Response: {response.text}")
                return None

        except Exception as e:
            self.handle_exception("insert_into_keeplinks", e)
            return None

    def update_keeplinks(self, keeplinks_url: str, urls):
        """
        Updates an existing Keeplinks link by overwriting its links with the new provided ones.
        Keeps the same Keeplinks URL (no new URL is created), just updates the protected links.
        Recaptcha only, no password or other parameters.

        Parameters:
        - keeplinks_url: The existing Keeplinks URL (e.g., https://www.keeplinks.org/p42/xxxxxx)
        - urls: A list of new links to set in the Keeplinks link.
        """
        keeplinks_api_url = "https://www.keeplinks.org/api.php"
        api_hash = (
            os.getenv("KEEP_LINKS_API_HASH", "").strip()
            or self.config.get('keeplinks_api_hash', '').strip()
        )
        if not api_hash:
            logging.error("Keeplinks API hash is missing")
            return False

        url_id = self.extract_url_id(keeplinks_url)
        if not url_id:
            logging.error("Could not extract url-id from Keeplinks URL during update.")
            return False

        links_to_protect = ",".join(urls)

        payload = {
            "apihash": api_hash,
            "url-id": url_id,
            "link-to-protect": links_to_protect,
            "output": "json",
            "captcha": "on",
            "captchatype": "Re"
        }

        try:
            response = requests.post(keeplinks_api_url, data=payload, timeout=30)

            logging.debug(f"Keeplinks (update) API Response: {response.text}")

            if response.status_code == 200:
                data = response.json()
                # On success, it should return p_links or r_links again.
                new_p_link = data.get("p_links")
                if new_p_link:
                    # The URL should remain the same as the original because we used url-id.
                    logging.info("Keeplinks link updated successfully with new links.")
                    return True
                else:
                    logging.error(f"Failed to confirm Keeplinks update from response: {data}")
                    return False
            else:
                logging.error(f"Keeplinks API error on update: {response.status_code}. Response: {response.text}")
                return False

        except Exception as e:
            logging.error(f"Error updating Keeplinks link: {e}", exc_info=True)
            return False

    # -----------------------------------
    # 3.5 Upload Images to Image Host # NEW
    # -----------------------------------
    def upload_images(self, image_paths):
        """
        Upload images to the configured image host.

        Parameters:
        - image_paths (list): List of file paths to images.
        """
        image_host = self.image_host_config.get('host', '')
        if not image_host:
            logging.warning("No image host configured.")
            return

        method_name = f"upload_{image_host.replace('.', '_')}"
        method = getattr(self, method_name, None)
        if method:
            logging.info(f"Starting image upload to '{image_host}'.")
            method(image_paths)
        else:
            logging.error(f"No upload method implemented for image host '{image_host}'.")

    def upload_imgur(self, image_paths):
        """Implement image upload logic for Imgur."""
        client_id = self.image_host_config.get('client_id', '')
        client_secret = self.image_host_config.get('client_secret', '')
        if not client_id:
            logging.error("Imgur Client ID is not set.")
            return

        headers = {'Authorization': f'Client-ID {client_id}'}
        logging.info(f"Uploading {len(image_paths)} images to Imgur.")

        for image_path in image_paths:
            try:
                with open(image_path, 'rb') as img_file:
                    # Imgur API expects the image in the 'image' field
                    response = requests.post(
                        'https://api.imgur.com/3/image',
                        headers=headers,
                        files={'image': img_file}
                    )
                    if response.status_code == 200:
                        link = response.json()['data']['link']
                        logging.info(f"Uploaded image '{image_path}' to Imgur: {link}")
                        # Optionally, store or return the link
                    else:
                        logging.error(
                            f"Failed to upload image '{image_path}' to Imgur. Status Code: {response.status_code}")
            except Exception as e:
                logging.error(f"Error uploading image '{image_path}' to Imgur: {e}", exc_info=True)

    # Add more image upload methods as needed for other image hosts # NEW
    # def upload_another_image_host(self, image_paths):
    #     """Implement image upload logic for AnotherImageHost.com."""
    #     pass

    # -----------------------------------
    # 3.6 Download and Upload Thread Methods # NEW
    # -----------------------------------
    def download_thread_links(self, thread_title, thread_url):
        """
        Download all links associated with a specific thread.

        Parameters:
        - thread_title (str): Title of the thread.
        - thread_url (str): URL of the thread.
        """
        links_dict = self.thread_links.get(thread_title, {})
        thread_info = self.extracted_threads.get(thread_title)
        if not thread_info:
            logging.error(f"No thread information found for '{thread_title}'.")
            return
        _, _, thread_id, _ = thread_info  # Extract thread_id

        for host, links in links_dict.items():
            self.download_links(host, links, self.protected_category, thread_id, thread_title)

    def upload_thread_links(self, thread_title, thread_url):
        """
        Upload all links associated with a specific thread.

        Parameters:
        - thread_title (str): Title of the thread.
        - thread_url (str): URL of the thread.
        """
        links_dict = self.thread_links.get(thread_title, {})
        if not links_dict:
            logging.warning(f"No links found for thread '{thread_title}'.")
            return

        # Retrieve thread_id from extracted_threads
        thread_info = self.extracted_threads.get(thread_title)
        if not thread_info:
            logging.error(f"No thread information found for '{thread_title}'. Cannot retrieve thread_id.")
            return

        thread_id = thread_info[2]  # Assuming thread_info is a tuple (thread_url, date_text, thread_id, file_hosts)

        for host, links in links_dict.items():
            if host == 'rapidgator.net':
                for link in links:
                    logging.debug(f"Processing link: {link}")
                    file_path = self.get_local_file_path_from_link(link)
                    if file_path and file_path.exists():
                        logging.debug(f"Found local file path: {file_path}")
                        file_url = self.initiate_upload_session(str(file_path))
                        if file_url:
                            logging.info(f"Uploaded '{file_path}' successfully. URL: {file_url}")
                            # Optionally, update the thread with 'file_url'
                    else:
                        logging.warning(f"No local file found for link: {link} at expected path.")
            else:
                self.upload_links(host, links)

    def backup_thread_links(self, thread_title, thread_url):
        """
        Backup all links associated with a specific thread.

        Parameters:
        - thread_title (str): Title of the thread.
        - thread_url (str): URL of the thread.
        """
        links_dict = self.thread_links.get(thread_title, {})
        all_links = []
        for host, links in links_dict.items():
            all_links.extend(links)
        self.backup_links(all_links)

    def upload_images_from_thread(self, thread_title, thread_url, image_paths):
        """
        Upload images associated with a specific thread.

        Parameters:
        - thread_title (str): Title of the thread.
        - thread_url (str): URL of the thread.
        - image_paths (list): List of image file paths to upload.
        """
        self.upload_images(image_paths)

    def insert_links_for_thread_keep_links(self, thread_title, thread_url):
        """
        Insert all links of a thread into Keeplinks.org.

        Parameters:
        - thread_title (str): Title of the thread.
        - thread_url (str): URL of the thread.
        """
        links_dict = self.thread_links.get(thread_title, {})
        all_links = []
        for host, links in links_dict.items():
            all_links.extend(links)
        self.insert_links_into_keep_links(all_links)

    def download_thread(self, thread_title, thread_url):
        """
        Example method to handle downloading of a specific thread's links.
        This should be called from a worker thread in the GUI.
        """
        logging.info(f"Initiating download for thread '{thread_title}' from URL: {thread_url}")
        self.download_thread_links(thread_title, thread_url)

    def upload_thread(self, thread_title, thread_url):
        """
        Example method to handle uploading of a specific thread's links.
        This should be called from a worker thread in the GUI.
        """
        logging.info(f"Initiating upload for thread '{thread_title}' from URL: {thread_url}")
        self.upload_thread_links(thread_title, thread_url)

    def backup_thread(self, thread_title, thread_url):
        """
        Example method to handle backing up of a specific thread's links.
        This should be called from a worker thread in the GUI.
        """
        logging.info(f"Initiating backup for thread '{thread_title}' from URL: {thread_url}")
        self.backup_thread_links(thread_title, thread_url)

    def upload_images_thread(self, thread_title, thread_url, image_paths):
        """
        Example method to handle uploading images for a specific thread.
        This should be called from a worker thread in the GUI.
        """
        logging.info(f"Initiating image upload for thread '{thread_title}' from URL: {thread_url}")
        self.upload_images_from_thread(thread_title, thread_url, image_paths)

    def insert_links_keep_links_thread(self, thread_title, thread_url):
        """
        Example method to handle inserting links into Keeplinks.org for a specific thread.
        This should be called from a worker thread in the GUI.
        """
        logging.info(f"Initiating Keeplinks.org insertion for thread '{thread_title}' from URL: {thread_url}")
        self.insert_links_for_thread_keep_links(thread_title, thread_url)

    def get_local_file_path_from_link(self, link):
        """
        Maps a Rapidgator link to the corresponding local file path.

        Parameters:
        - link (str): Rapidgator download URL.

        Returns:
        - Path or None: Local file path if found, None otherwise.
        """
        file_id = self.extract_file_id(link)
        if not file_id:
            logging.error(f"Invalid link format: {link}")
            return None

        sanitized_category = sanitize_filename(self.protected_category)
        download_path = Path(self.download_dir) / sanitized_category

        # Ensure the download path exists
        if not download_path.exists():
            logging.error(f"Download path does not exist: {download_path}")
            return None

        # Use rglob to search recursively for any file starting with the file_id
        pattern = f"{file_id}.*"
        matched_files = list(download_path.rglob(pattern))

        if matched_files:
            # If multiple matches, choose the first one (assuming unique file_ids)
            logging.debug(f"Matched files for file_id '{file_id}': {[str(f) for f in matched_files]}")
            return matched_files[0]
        else:
            logging.error(f"No files found for file_id '{file_id}' in '{download_path}'.")
            return None

    # -----------------------------------
    # 4. Process Thread ID Management
    # -----------------------------------
    def load_processed_thread_ids(self):
        """
        Loads processed thread IDs from a file if it exists.
        """
        try:
            # Use user-specific folder if user is logged in, otherwise fallback to global
            if self.user_manager and self.user_manager.get_current_user():
                try:
                    user_folder = self.user_manager.get_user_folder()
                    os.makedirs(user_folder, exist_ok=True)
                    filename = os.path.join(user_folder, 'processed_threads.pkl')
                    logging.debug(f"📁 Using user-specific processed threads file: {filename}")
                except Exception as e:
                    logging.warning(f"⚠️ Could not get user folder, using global: {e}")
                    filename = os.path.join(DATA_DIR, 'processed_threads.pkl')
            else:
                filename = os.path.join(DATA_DIR, 'processed_threads.pkl')
                logging.debug(f"📁 Using global processed threads file: {filename}")
            
            if os.path.exists(filename):
                with open(filename, 'rb') as f:
                    self.processed_thread_ids = pickle.load(f)
                logging.info(f"✅ Processed thread IDs loaded successfully from {filename}")
            else:
                logging.info(f"📄 No existing processed thread IDs file found at {filename}")
                self.processed_thread_ids = set()
        except Exception as e:
            self.handle_exception("loading processed thread IDs", e)
            self.processed_thread_ids = set()

    def save_processed_thread_ids(self):
        """
        Saves processed thread IDs to a file for persistence across sessions.
        """
        try:
            # Use user-specific folder if user is logged in, otherwise fallback to global
            if self.user_manager and self.user_manager.get_current_user():
                try:
                    user_folder = self.user_manager.get_user_folder()
                    # Ensure user folder exists
                    os.makedirs(user_folder, exist_ok=True)
                    filename = os.path.join(user_folder, 'processed_threads.pkl')
                    logging.debug(f"📁 Saving to user-specific processed threads file: {filename}")
                except Exception as e:
                    logging.warning(f"⚠️ Could not get user folder, using global: {e}")
                    filename = os.path.join(DATA_DIR, 'processed_threads.pkl')
            else:
                filename = os.path.join(DATA_DIR, 'processed_threads.pkl')
                logging.debug(f"📁 Saving to global processed threads file: {filename}")
            
            with open(filename, 'wb') as f:
                pickle.dump(self.processed_thread_ids, f)
            logging.info(f"✅ Processed thread IDs saved successfully to {filename}")
        except Exception as e:
            self.handle_exception("saving processed thread IDs", e)

    def reset_processed_thread_ids(self):
        """
        Resets the processed thread IDs by clearing the set and deleting the pickle file.
        """
        try:
            self.processed_thread_ids.clear()
            
            # Use user-specific folder if user is logged in, otherwise fallback to global
            if self.user_manager and self.user_manager.get_current_user():
                try:
                    user_folder = self.user_manager.get_user_folder()
                    filename = os.path.join(user_folder, 'processed_threads.pkl')
                    logging.debug(f"📁 Resetting user-specific processed threads file: {filename}")
                except Exception as e:
                    logging.warning(f"⚠️ Could not get user folder, using global: {e}")
                    filename = os.path.join(DATA_DIR, 'processed_threads.pkl')
            else:
                filename = os.path.join(DATA_DIR, 'processed_threads.pkl')
                logging.debug(f"📁 Resetting global processed threads file: {filename}")
            
            if os.path.exists(filename):
                os.remove(filename)
                logging.info(f"🗑️ Deleted processed thread IDs file: {filename}")
            logging.info("✅ Processed thread IDs have been reset.")
        except Exception as e:
            self.handle_exception("resetting processed thread IDs", e)

    def login(self, current_url=None):
        """
        Handles the login process using Selenium by accessing the login page directly.
        Sets self.is_logged_in to True upon successful login and returns True.
        Returns False if login fails.
        """
        if self.is_logged_in:
            logging.info("Already logged in.")
            return True

        try:
            # Navigate to the login page
            login_url = f"{self.forum_url}/login.php"  # Adjust based on the actual login URL
            logging.debug(f"Accessing login page: {login_url}")
            print(f"Accessing URL for login: {login_url}")
            self.driver.get(login_url)
            time.sleep(3)  # Wait for the page to load

            # Wait until the username field is present
            try:
                username_field = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "vb_login_username"))  # Update with actual field name
                )
            except TimeoutException as e:
                self.handle_exception("finding username field on login page", e)
                print("Username field not found on login page.")
                self.is_logged_in = False
                return False

            try:
                password_field = self.driver.find_element(By.NAME, "vb_login_password")  # Update with actual field name
            except NoSuchElementException as e:
                self.handle_exception("finding password field on login page", e)
                print("Password field not found on login page.")
                self.is_logged_in = False
                return False

            # Enter credentials
            username_field.clear()
            username_field.send_keys(self.username)
            password_field.clear()
            password_field.send_keys(self.password)

            # Check the "Remember Me" checkbox (cookieuser)
            try:
                cookieuser_checkbox = self.driver.find_element(By.ID, "cb_cookieuser_navbar")
                if not cookieuser_checkbox.is_selected():
                    cookieuser_checkbox.click()
                    logging.info("✅ Remember Me checkbox selected.")
                    print("✅ Remember Me checkbox selected.")
                else:
                    logging.info("✅ Remember Me checkbox already selected.")
            except NoSuchElementException:
                logging.warning("⚠️ Remember Me checkbox not found - trying alternative selector")
                try:
                    # Try alternative selector by name
                    cookieuser_checkbox = self.driver.find_element(By.NAME, "cookieuser")
                    if not cookieuser_checkbox.is_selected():
                        cookieuser_checkbox.click()
                        logging.info("✅ Remember Me checkbox selected (alternative selector).")
                        print("✅ Remember Me checkbox selected (alternative selector).")
                except NoSuchElementException:
                    logging.warning("⚠️ Remember Me checkbox not found with any selector - continuing without it")

            # Submit the form
            password_field.send_keys(Keys.RETURN)
            time.sleep(5)  # Wait for login to process

            # Verify login by checking for 'Logout' or 'Abmelden' link
            if self.check_login_status():
                logging.info("Logged in successfully via Selenium.")
                print("Logged in successfully via Selenium.")
                self.is_logged_in = True
                # Save cookies
                self.save_cookies()

                # Redirect back to the original category if provided
                if current_url:
                    logging.info(f"Redirecting back to {current_url}")
                    self.driver.get(current_url)
                    time.sleep(3)
                return True
            else:
                # Capture potential error messages from the page
                error_message_elements = self.driver.find_elements(By.CLASS_NAME, 'error')  # Update with actual class
                if error_message_elements:
                    error_message = error_message_elements[0].text
                    logging.error(f"Login failed: {error_message}")
                    print(f"Login failed: {error_message}")
                else:
                    logging.error("Login failed via Selenium: 'Logout' link not found.")
                    print("Login failed via Selenium: 'Logout' link not found.")
                self.is_logged_in = False
                return False

        except Exception as e:
            self.handle_exception("Selenium login", e)
            print(f"An error occurred during Selenium login: {e}")
            self.is_logged_in = False
            return False

    def check_login_status(self):
        """
        Checks if the user is logged in by looking for 'Logout' or 'Abmelden' link in the page source.
        Does NOT navigate away from current page.
        """
        try:
            # Check current page source without navigating away
            page_source = self.driver.page_source.lower()
            if "logout" in page_source or "abmelden" in page_source or "log out" in page_source:
                logging.info("User is logged in.")
                return True
            else:
                logging.info("User is not logged in.")
                return False
        except Exception as e:
            self.handle_exception("checking login status", e)
            return False

    def save_cookies(self):
        """
        Saves cookies to a file for later use, under DATA_DIR.
        """
        try:
            # إنشاء مجلد المستخدم إذا لم يكن موجودًا
            cookies_dir = os.path.dirname(self.cookies_file)
            os.makedirs(cookies_dir, exist_ok=True)

            cookies = self.driver.get_cookies()
            
            # Use the cookies_file path set in constructor (user-specific or global)
            with open(self.cookies_file, 'wb') as f:
                pickle.dump(cookies, f)

            logging.info(f"🍪 Cookies saved to {self.cookies_file}")
        except Exception as e:
            self.handle_exception("saving cookies", e)

    def update_user_file_paths(self):
        """
        Update file paths after user login to use user-specific folders
        """
        if self.user_manager and self.user_manager.get_current_user():
            try:
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                
                # Update cookies file path
                old_cookies_file = self.cookies_file
                self.cookies_file = os.path.join(user_folder, "cookies.pkl")
                logging.info(f"🔄 Updated cookies path from {old_cookies_file} to {self.cookies_file}")
                
            except Exception as e:
                logging.error(f"❌ Error updating user file paths: {e}")
                # Keep fallback paths
                self.cookies_file = os.path.join(DATA_DIR, "cookies.pkl")
        else:
            # Use global paths when no user logged in
            self.cookies_file = os.path.join(DATA_DIR, "cookies.pkl")
            logging.info(f"🔄 Using global cookies path: {self.cookies_file}")

    def load_cookies(self):
        """
        Loads cookies from DATA_DIR if the file exists.
        """
        # Use the cookies_file path set in constructor (user-specific or global)
        if os.path.exists(self.cookies_file):
            try:
                with open(self.cookies_file, 'rb') as f:
                    cookies = pickle.load(f)

                # للتأكد من أننا على الصفحة الصحيحة قبل إضافة الكوكيز
                self.driver.get(self.forum_url)

                for cookie in cookies:
                    # اضبط الدومين لو لزم الأمر
                    if 'domain' in cookie:
                        cookie['domain'] = self.forum_url.replace('https://', '').replace('http://', '')
                    # اضبط تاريخ الانتهاء ليكون عدد صحيح
                    if 'expiry' in cookie and isinstance(cookie['expiry'], float):
                        cookie['expiry'] = int(cookie['expiry'])

                    self.driver.add_cookie(cookie)

                logging.info(f"Cookies loaded from {self.cookies_file}")
                return True
            except Exception as e:
                self.handle_exception("loading cookies", e)
                return False
        else:
            logging.info(f"No cookies file found for user {self.username} at {self.cookies_file}")
            return False

    def logout(self):
        """
        Logs out the user by deleting cookies and clicking the logout link if necessary.
        """
        try:
            # Delete cookies using the same path logic as initialization
            if os.path.exists(self.cookies_file):
                os.remove(self.cookies_file)
                logging.info(f"Deleted cookies file: {self.cookies_file}")

            self.driver.delete_all_cookies()
            self.is_logged_in = False
            logging.info("Logged out successfully.")

        except Exception as e:
            self.handle_exception("logging out", e)

    def navigate_to_url(self, category_url, date_filters, page_from, page_to):
        """
        Navigates to a specified category URL and checks whether the bot is still logged in.
        If logged out, it re-logs in at the current category page.
        Additionally, it extracts file hosts and links within each thread.
        """
        try:
            print(f"navigate_to_url called with category_url: {category_url}")

            # Ensure the category URL is in the correct format
            category_url = self.normalize_category_url(category_url)
            print(f"Normalized category URL: {category_url}")

            # Ensure we are logged in
            if not self.is_logged_in:
                self.login()
                if not self.is_logged_in:
                    logging.error("Cannot proceed without login.")
                    return False

            # Parse the date filters
            date_ranges = self.parse_date_filter(date_filters)

            # Do NOT clear self.thread_links here to preserve existing links
            self.extracted_threads = {}  # Clear previous threads

            for page_number in range(page_from, page_to + 1):
                if page_number > 1:
                    # MyGully forum uses format: /377-ebooks/ -> /377-ebooks-2/ -> /377-ebooks-3/
                    # Remove trailing slash, add page number, then add slash back
                    base_url = category_url.rstrip('/')
                    page_url = f"{base_url}-{page_number}/"
                else:
                    # Use the original category URL for the first page
                    page_url = category_url

                logging.info(f"📄 Navigating to page {page_number}/{page_to}: {page_url}")
                print(f"📄 Navigating to page {page_number}/{page_to}: {page_url}")

                self.driver.get(page_url)
                time.sleep(3)  # Wait for page to load

                logging.info(f"✅ Successfully loaded page {page_number}: {self.driver.current_url}")
                print(f"✅ Successfully loaded page {page_number}: {self.driver.current_url}")

                # Check if we've been redirected to the login page
                if "/login" in self.driver.current_url:
                    logging.warning(f"Redirected to login page from {page_url}. Re-logging in.")
                    self.is_logged_in = False
                    self.login(current_url=page_url)
                    if not self.is_logged_in:
                        logging.error("Re-login failed. Stopping navigation.")
                        return False
                    else:
                        # After re-login, try navigating again
                        self.driver.get(page_url)
                        time.sleep(3)

                # Extract and filter threads by the provided date ranges
                page_threads_before = len(self.extracted_threads)
                self.extract_threads(date_ranges)
                page_threads_after = len(self.extracted_threads)
                new_threads_found = page_threads_after - page_threads_before
                logging.info(f"📊 Page {page_number} processed: {new_threads_found} new threads found (Total: {page_threads_after})")
                print(f"📊 Page {page_number} processed: {new_threads_found} new threads found (Total: {page_threads_after})")

            # Final summary
            total_threads = len(self.extracted_threads)
            total_pages = page_to - page_from + 1
            logging.info(f"✅ Navigation completed! Processed {total_pages} pages and found {total_threads} total threads")
            print(f"✅ Navigation completed! Processed {total_pages} pages and found {total_threads} total threads")
            return True
        except Exception as e:
            self.handle_exception("navigating to URL", e)
            print(f"Error navigating to URL: {e}")
            return False

    def get_megathread_last_page(self, thread_url):
        """
        Determine if the megathread has multiple pages, and return the last page URL if so.
        This method:
        - Checks for a 'Last »' link first.
        - If not found, checks numeric pagination links and chooses the highest page.
        - If no pagination is found, returns None.
        The calling code should fallback to thread_url if None is returned.
        """

        # Ensure the thread_url is a fully qualified URL
        if thread_url.startswith('/'):
            thread_url = self.forum_url.rstrip('/') + thread_url
        elif not thread_url.startswith('http'):
            thread_url = self.forum_url.rstrip('/') + '/' + thread_url.lstrip('/')

        self.driver.get(thread_url)
        time.sleep(3)
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')

        # Check for 'Last »' link first
        last_page_link = soup.select_one('a.smallfont[title*="Letzte Seite"]')
        if last_page_link:
            href = last_page_link.get('href', '')
            if href.startswith('/'):
                href = self.forum_url.rstrip('/') + href
            elif not href.startswith('http'):
                href = self.forum_url.rstrip('/') + '/' + href.lstrip('/')
            return href

        # If no 'Last »' link, check numeric pagination
        page_links = soup.select('a.smallfont[title^="Zeige Ergebnis"]')
        if page_links:
            max_page = 1
            max_page_url = None
            for plink in page_links:
                href = plink.get('href', '')
                match = re.search(r'page=(\d+)', href)
                if match:
                    pnum = int(match.group(1))
                    if pnum > max_page:
                        max_page = pnum
                        if href.startswith('/'):
                            href = self.forum_url.rstrip('/') + href
                        elif not href.startswith('http'):
                            href = self.forum_url.rstrip('/') + '/' + href.lstrip('/')
                        max_page_url = href
            if max_page_url:
                return max_page_url

        # If no extra pages found
        return None

    def get_main_thread_version_title(self, last_page_url):
        """
        Extracts the main version title from the first post of the thread.
        If a <b> tag is found in the first post, use that.
        If not, fallback to the main thread title (from <h1><strong>).
        """
        if last_page_url.startswith('/'):
            last_page_url = self.forum_url.rstrip('/') + last_page_url
        elif not last_page_url.startswith('http'):
            last_page_url = self.forum_url.rstrip('/') + '/' + last_page_url.lstrip('/')

        self.driver.get(last_page_url)
        time.sleep(3)
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')

        main_thread_title_el = soup.select_one('h1 > strong')
        main_thread_title = main_thread_title_el.get_text(strip=True) if main_thread_title_el else "No Title"

        # The first post is usually the first 'div' with id starting with post_message_
        first_post = soup.find('div', id=re.compile(r'post_message_\d+'))
        if not first_post:
            return main_thread_title

        # Try to get a <b> tag inside the first post
        version_b = first_post.select_one('b')
        if version_b:
            ver_name = version_b.get_text(strip=True)
            if ver_name:
                return ver_name

        return main_thread_title

    def navigate_to_actual_last_page(self, thread_url):
        """
        Navigate to the actual last page of a megathread.
        Some threads have multiple pages, we need to find the real last page.
        """
        try:
            # First, navigate to the thread (might be first page)
            if thread_url.startswith('/'):
                thread_url = self.forum_url.rstrip('/') + thread_url
            elif not thread_url.startswith('http'):
                thread_url = self.forum_url.rstrip('/') + '/' + thread_url.lstrip('/')
            
            self.driver.get(thread_url)
            time.sleep(2)
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Look for pagination - find the last page number
            pagination_links = soup.find_all('a', href=True)
            last_page_num = 1
            
            for link in pagination_links:
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                # Look for page numbers in pagination
                if 'page=' in href and text.isdigit():
                    page_num = int(text)
                    if page_num > last_page_num:
                        last_page_num = page_num
                        
                # Also check for "Last Page" or similar links
                elif ('last' in text.lower() or 'letzte' in text.lower()) and 'page=' in href:
                    # Extract page number from the href
                    import re
                    page_match = re.search(r'page=([0-9]+)', href)
                    if page_match:
                        page_num = int(page_match.group(1))
                        if page_num > last_page_num:
                            last_page_num = page_num
            
            # If we found a higher page number, construct the last page URL
            if last_page_num > 1:
                if '?' in thread_url:
                    last_page_url = f"{thread_url}&page={last_page_num}"
                else:
                    last_page_url = f"{thread_url}?page={last_page_num}"
                logging.info(f"📚 Found multi-page thread, navigating to page {last_page_num}: {last_page_url}")
                return last_page_url
            else:
                logging.info(f"📚 Single page thread, using original URL: {thread_url}")
                return thread_url
                
        except Exception as e:
            logging.error(f"⚠️ Error finding last page, using original URL: {e}")
            return thread_url

    def extract_improved_version_title(self, post_element, main_thread_title):
        """
        Enhanced version title extraction specifically for magazines and complex posts.
        Handles magazine dates like "August/September 2024" properly.
        """
        try:
            # First, try to find magazine-style dates (Month/Month Year, Month Year, etc.)
            text_content = post_element.get_text()
            
            # Look for magazine date patterns
            import re
            
            # Pattern 1: "August/September 2024", "July/August 2024"
            month_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)(?:/| |\s+)(January|February|March|April|May|June|July|August|September|October|November|December)?\s*(20[0-9]{2})'
            
            # Pattern 2: German months "August/September", "Juli/August"
            german_month_pattern = r'(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)(?:/| |\s+)(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)?\s*(20[0-9]{2})'
            
            # Look in bold tags first (most likely to contain the title)
            bold_tags = post_element.find_all('b')
            for bold_tag in bold_tags:
                bold_text = bold_tag.get_text(strip=True)
                
                # Skip if it's clearly a download link or host name
                if any(skip_word in bold_text.lower() for skip_word in ['download', 'rapidgator', 'katfile', 'nitroflare', 'mega.nz', 'http', 'www.']):
                    continue
                
                # Check for magazine date patterns
                if re.search(month_pattern, bold_text, re.IGNORECASE) or re.search(german_month_pattern, bold_text, re.IGNORECASE):
                    logging.info(f"📅 Found magazine date in bold: {bold_text}")
                    return bold_text
                
                # Check for version numbers
                if re.search(r'(?:v|version\s*|ver\s*)?[0-9]+(?:\.[0-9]+)+(?![0-9])', bold_text, re.IGNORECASE):
                    logging.info(f"🔢 Found version number in bold: {bold_text}")
                    return bold_text
                
                # If it's a substantial title (not just a word or two)
                if len(bold_text) > 10 and not bold_text.startswith('http'):
                    logging.info(f"📝 Found substantial title in bold: {bold_text}")
                    return bold_text
            
            # If no good bold tags, look in the entire post text
            lines = text_content.split('\n')
            for line in lines:
                line = line.strip()
                if not line or len(line) < 5:
                    continue
                
                # Skip download links and host names
                if any(skip_word in line.lower() for skip_word in ['download', 'rapidgator', 'katfile', 'nitroflare', 'mega.nz', 'http', 'www.']):
                    continue
                
                # Check for magazine date patterns
                if re.search(month_pattern, line, re.IGNORECASE) or re.search(german_month_pattern, line, re.IGNORECASE):
                    logging.info(f"📅 Found magazine date in text: {line}")
                    return line
                
                # Check for version numbers
                if re.search(r'(?:v|version\s*|ver\s*)?[0-9]+(?:\.[0-9]+)+(?![0-9])', line, re.IGNORECASE):
                    logging.info(f"🔢 Found version number in text: {line}")
                    return line
            
            # Fallback to the original extract_version_title function
            fallback_title = extract_version_title(post_element, main_thread_title)
            logging.info(f"🔄 Using fallback title extraction: {fallback_title}")
            return fallback_title
            
        except Exception as e:
            logging.error(f"⚠️ Error in improved title extraction: {e}")
            return extract_version_title(post_element, main_thread_title)

    def compare_magazine_dates(self, title1, title2):
        """
        Compare magazine dates properly. Returns True if title1 is newer than title2.
        Handles formats like "August/September 2024" vs "April/Mai 2024".
        """
        try:
            import re
            from datetime import datetime
            
            # Month name mappings (English and German)
            month_map = {
                'january': 1, 'januar': 1,
                'february': 2, 'februar': 2,
                'march': 3, 'märz': 3,
                'april': 4,
                'may': 5, 'mai': 5,
                'june': 6, 'juni': 6,
                'july': 7, 'juli': 7,
                'august': 8,
                'september': 9,
                'october': 10, 'oktober': 10,
                'november': 11,
                'december': 12, 'dezember': 12
            }
            
            def extract_date_info(title):
                # Pattern for "Month/Month Year" or "Month Year"
                pattern = r'(january|february|march|april|may|june|july|august|september|october|november|december|januar|februar|märz|mai|juni|juli|oktober|dezember)(?:/|\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|januar|februar|märz|mai|juni|juli|oktober|dezember)?\s*(20[0-9]{2})'
                
                match = re.search(pattern, title.lower())
                if match:
                    month1 = match.group(1)
                    month2 = match.group(2) if match.group(2) else month1
                    year = int(match.group(3))
                    
                    # Get the later month (for ranges like August/September)
                    month1_num = month_map.get(month1, 1)
                    month2_num = month_map.get(month2, month1_num)
                    later_month = max(month1_num, month2_num)
                    
                    return year, later_month
                return None, None
            
            year1, month1 = extract_date_info(title1)
            year2, month2 = extract_date_info(title2)
            
            if year1 and year2 and month1 and month2:
                # Compare year first, then month
                if year1 != year2:
                    result = year1 > year2
                    logging.debug(f"📅 Date comparison: '{title1}' ({year1}) vs '{title2}' ({year2}) = {result}")
                    return result
                else:
                    result = month1 > month2
                    logging.debug(f"📅 Month comparison: '{title1}' (month {month1}) vs '{title2}' (month {month2}) = {result}")
                    return result
            
            # Fallback to string comparison
            return title1 > title2
            
        except Exception as e:
            logging.error(f"⚠️ Error comparing magazine dates: {e}")
            return title1 > title2

    def extract_megathread_latest_version(self, last_page_url, last_check_timestamp=None):
        """
        Extracts the LAST POST from the megathread's last page, regardless of known hosts.
        Uses the same HTML parsing and BBCode conversion as normal thread tracking.
        Always selects the latest reply containing download links.
        
        Args:
            last_page_url (str): URL of the last page of the megathread
            last_check_timestamp (datetime): Optional timestamp to filter posts newer than this time
            
        Returns:
            dict: {
                'version_title': str,
                'links': dict,
                'bbcode_content': str,
                'thread_id': str,
                'thread_url': str,
                'has_rapidgator': bool,
                'has_katfile': bool,
                'has_other_known_hosts': bool,
                'has_any_links': bool,
                'priority_score': int,
                'post_date': datetime
            }
        or None if no suitable post is found.
        """
        # Navigate to the ACTUAL last page first
        actual_last_page_url = self.navigate_to_actual_last_page(last_page_url)
        
        if actual_last_page_url.startswith('/'):
            actual_last_page_url = self.forum_url.rstrip('/') + actual_last_page_url
        elif not actual_last_page_url.startswith('http'):
            actual_last_page_url = self.forum_url.rstrip('/') + '/' + actual_last_page_url.lstrip('/')

        logging.info(f"🔍 Extracting LAST POST from megathread's actual last page: {actual_last_page_url}")
        self.driver.get(actual_last_page_url)
        time.sleep(3)
        
        # Store HTML content to avoid double visits (same as normal thread tracking)
        html_content = self.driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')

        main_thread_title_el = soup.select_one('h1 > strong')
        main_thread_title = main_thread_title_el.get_text(strip=True) if main_thread_title_el else "No Title"

        # Find all posts using the same method as normal thread tracking
        all_posts = soup.find_all('div', id=re.compile(r'post_message_\d+'))
        if not all_posts:
            logging.warning("No posts found in megathread")
            return None

        logging.info(f"📝 Found {len(all_posts)} posts in megathread, selecting LAST POST")
        
        # Always select the LAST POST (latest reply)
        last_post = all_posts[-1]
        
        # Get post date for continuous monitoring
        post_date = self.get_megathread_post_date(last_post)
        
        # Skip if post is older than last check (for continuous monitoring)
        if last_check_timestamp and post_date:
            if post_date <= last_check_timestamp:
                logging.info(f"⏭️ Last post is older than last check ({post_date} <= {last_check_timestamp}), skipping")
                return None
        
        # Extract links using the same method as normal thread tracking
        file_hosts_found = set()
        links_dict = {}
        keeplinks_urls = set()

        # Use the same link extraction method as normal thread tracking
        logging.info(f"🔗 Extracting links from the LAST POST (post HTML length: {len(str(last_post))} chars)")
        self.extract_links_from_post(last_post, file_hosts_found, links_dict, keeplinks_urls)

        # Add keeplinks as a normal host if no other hosts found
        if not file_hosts_found and keeplinks_urls:
            logging.info("No known hosts found, adding keeplinks.org as normal host")
            links_dict['keeplinks'] = list(keeplinks_urls)

        # Remove duplicates (same as normal tracking)
        for host in links_dict:
            links_dict[host] = list(set(links_dict[host]))

        # Convert to BBCode using the same method as normal thread tracking
        # Use ONLY the last post HTML (same post we extracted links from)
        last_post_html = str(last_post)  # Get HTML of the specific last post
        logging.info(f"🔄 Converting BBCode from the SAME last post that links were extracted from (HTML length: {len(last_post_html)} chars)")
        bbcode_content = self.convert_megathread_post_to_bbcode(last_post_html, last_post)
        
        thread_id = self.get_megathread_post_id(last_post)
        version_title = self.extract_improved_version_title(last_post, main_thread_title)

        if not bbcode_content.strip():
            bbcode_content = "[CENTER]No BBCode content extracted.[/CENTER]"

        # Calculate host flags (same as normal tracking)
        known_hosts_priority = ['rapidgator.net', 'katfile.com', 'nitroflare.com', 'ddownload.com', 'mega.nz', 'xup.in', 'f2h.io', 'filepv.com', 'filespayouts.com', 'uploady.io']
        has_rapidgator = any('rapidgator.net' in h for h in links_dict.keys())
        has_katfile = any('katfile.com' in h for h in links_dict.keys())
        other_known_hosts = [h for h in links_dict if any(kh in h for kh in known_hosts_priority[2:])]
        has_other_known_hosts = bool(other_known_hosts)
        has_any_links = any(links_dict.values())
        
        # Calculate priority score (lower = better)
        priority_score = self.calculate_version_priority_score(
                has_rapidgator, has_katfile, has_other_known_hosts, has_any_links, post_date
            )

        return {
            'version_title': version_title,
            'links': links_dict,
            'bbcode_content': bbcode_content,
            'thread_id': thread_id,
            'thread_url': actual_last_page_url,
            'post_date': post_date,
            'has_rapidgator': has_rapidgator,
            'has_katfile': has_katfile,
            'has_other_known_hosts': has_other_known_hosts,
            'has_any_links': has_any_links,
            'priority_score': priority_score,
            'html_content': str(last_post)  # Store HTML for BBCode conversion
        }

        # Log the selection decision for the last post
        logging.info(f"📌 SELECTED LAST POST: '{version_title}' from {post_date}")
        if has_rapidgator:
            logging.info(f"🥇 Last post has Rapidgator links!")
        elif has_katfile:
            logging.info(f"🥈 Last post has Katfile links")
        elif has_other_known_hosts:
            logging.info(f"🥉 Last post has other known hosts")
        elif has_any_links:
            logging.info(f"📝 Last post has some links (manual review needed)")
        else:
            logging.info(f"⚠️ Last post has no download links found")

        return {
            'version_title': version_title,
            'links': links_dict,
            'bbcode_content': bbcode_content,
            'thread_id': thread_id,
            'thread_url': actual_last_page_url,
            'post_date': post_date,
            'has_rapidgator': has_rapidgator,
            'has_katfile': has_katfile,
            'has_other_known_hosts': has_other_known_hosts,
            'has_any_links': has_any_links,
            'priority_score': priority_score,
            'html_content': str(last_post)  # Store HTML for BBCode conversion
        }

    def calculate_version_priority_score(self, has_rapidgator, has_katfile, has_other_known_hosts, has_any_links, post_date):
        """
        Calculate priority score for megathread versions.
        Lower score = higher priority.
        
        Priority order:
        1. Rapidgator (score: 1-10)
        2. Katfile (score: 11-20) 
        3. Other known hosts (score: 21-30)
        4. Any links (score: 31-40)
        5. No links (score: 41-50)
        
        Within each category, newer posts get slightly better scores.
        """
        from datetime import datetime, timedelta
        
        base_score = 0
        
        # Primary priority based on host quality
        if has_rapidgator:
            base_score = 1  # Highest priority
        elif has_katfile:
            base_score = 11  # Second priority
        elif has_other_known_hosts:
            base_score = 21  # Third priority
        elif has_any_links:
            base_score = 31  # Fourth priority - has links but unknown hosts
        else:
            base_score = 41  # Lowest priority - no links
        
        # Add date-based modifier (newer posts get slightly better scores)
        try:
            if post_date and isinstance(post_date, datetime):
                # Posts from last 24 hours get -2 bonus
                if post_date > datetime.now() - timedelta(days=1):
                    base_score -= 2
                # Posts from last week get -1 bonus
                elif post_date > datetime.now() - timedelta(days=7):
                    base_score -= 1
                # Very old posts (>30 days) get +1 penalty
                elif post_date < datetime.now() - timedelta(days=30):
                    base_score += 1
        except Exception as e:
            logging.debug(f"Date processing error in priority calculation: {e}")
        
        return max(1, base_score)  # Ensure minimum score of 1

    def convert_megathread_post_to_bbcode(self, post_html, post_element):
        """
        Convert megathread post HTML to BBCode using the same sophisticated logic as normal thread tracking.
        This ensures consistency between megathread and normal thread content extraction.
        
        Args:
            post_html: HTML content of the specific post (not full page)
            post_element: BeautifulSoup element of the post
        """
        from bs4 import BeautifulSoup, NavigableString
        import re
        
        try:
            # Parse the specific post HTML content
            soup = BeautifulSoup(post_html, 'html.parser')
            
            # Find the main post content - try different selectors within this specific post
            main_content = None
            
            # Try to find the post message div within this specific post
            post_message = soup.find('div', id=re.compile(r'^post_message_'))
            if post_message:
                main_content = post_message
                logging.debug("Found post_message div in last post")
            else:
                # Try to find other content containers within the post
                content_divs = soup.find_all('div', class_=re.compile(r'post.*content|message.*content|content'))
                if content_divs:
                    main_content = content_divs[0]
                    logging.debug("Found content div in last post")
                else:
                    # Use the entire post element as main content
                    main_content = soup
                    logging.debug("Using entire last post as main content")
            
            if not main_content:
                logging.debug("Could not find main content in megathread post, using post element")
                main_content = soup
            
            def traverse(node):
                """Recursively traverse HTML nodes and convert to BBCode"""
                bbcode = ""
                
                if isinstance(node, NavigableString):
                    # Clean up whitespace but preserve line breaks
                    text = str(node)
                    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
                    bbcode += text
                elif hasattr(node, 'name'):
                    tag_name = node.name.lower()
                    
                    # Handle different HTML tags
                    if tag_name == 'b' or tag_name == 'strong':
                        bbcode += '[B]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/B]'
                    elif tag_name == 'i' or tag_name == 'em':
                        bbcode += '[I]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/I]'
                    elif tag_name == 'u':
                        bbcode += '[U]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/U]'
                    elif tag_name == 'a':
                        href = node.get('href', '')
                        if href:
                            # Normalize the link
                            if href.startswith('//'):
                                href = 'https:' + href
                            elif href.startswith('/'):
                                href = 'https://example.com' + href  # Fallback base URL
                            
                            link_text = ''.join(traverse(child) for child in node.children)
                            if link_text.strip():
                                bbcode += f'[URL={href}]{link_text}[/URL]'
                            else:
                                bbcode += f'[URL]{href}[/URL]'
                        else:
                            for child in node.children:
                                bbcode += traverse(child)
                    elif tag_name == 'img':
                        src = node.get('src', '')
                        if src:
                            if src.startswith('//'):
                                src = 'https:' + src
                            bbcode += f'[IMG]{src}[/IMG]'
                    elif tag_name == 'center':
                        bbcode += '[CENTER]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/CENTER]'
                    elif tag_name == 'blockquote':
                        bbcode += '[QUOTE]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/QUOTE]'
                    elif tag_name == 'code':
                        bbcode += '[CODE]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/CODE]'
                    elif tag_name == 'br':
                        bbcode += '\n'
                    elif tag_name == 'p':
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '\n\n'
                    elif tag_name in ['div', 'span']:
                        # Handle divs and spans by processing their children
                        for child in node.children:
                            bbcode += traverse(child)
                    elif tag_name == 'table':
                        bbcode += '[TABLE]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/TABLE]'
                    elif tag_name == 'tr':
                        bbcode += '[TR]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/TR]'
                    elif tag_name == 'td' or tag_name == 'th':
                        bbcode += '[TD]'
                        for child in node.children:
                            bbcode += traverse(child)
                        bbcode += '[/TD]'
                    else:
                        # For unknown tags, just process children
                        for child in node.children:
                            bbcode += traverse(child)
                
                return bbcode
            
            # Convert the main content
            bbcode_result = traverse(main_content)
            
            # Clean up the result
            bbcode_result = re.sub(r'\n\s*\n\s*\n+', '\n\n', bbcode_result)  # Remove excessive line breaks
            bbcode_result = bbcode_result.strip()
            
            # Apply text replacements similar to normal thread tracking
            replacements = {
                'Rapidgator.net': '[URL=https://rapidgator.net]Rapidgator.net[/URL]',
                'Katfile.com': '[URL=https://katfile.com]Katfile.com[/URL]',
                'Nitroflare.com': '[URL=https://nitroflare.com]Nitroflare.com[/URL]',
                'DDownload.com': '[URL=https://ddownload.com]DDownload.com[/URL]',
                'Mega.nz': '[URL=https://mega.nz]Mega.nz[/URL]'
            }
            
            for text, replacement in replacements.items():
                bbcode_result = bbcode_result.replace(text, replacement)
            
            logging.debug(f"Converted megathread post HTML to BBCode ({len(bbcode_result)} chars)")
            return bbcode_result
            
        except Exception as e:
            logging.error(f"Error converting megathread post to BBCode: {e}")
            # Fallback to simple conversion
            return self.convert_post_html_to_bbcode(post_element)

    def get_megathread_post_date(self, post):
        """
        Extract post date from megathread post for continuous monitoring.
        Returns datetime object or None if date cannot be parsed.
        """
        try:
            # Look for date in various possible locations
            date_elements = [
                post.find('span', class_='date'),
                post.find('div', class_='postdate'),
                post.find('td', class_='thead'),
                post.find_parent('tr').find('td', class_='thead') if post.find_parent('tr') else None
            ]
            
            for date_elem in date_elements:
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                    # Try to parse German date format
                    parsed_date = self.parse_german_date(date_text)
                    if parsed_date:
                        return parsed_date
            
            return None
        except Exception as e:
            logging.debug(f"Could not extract post date: {e}")
            return None
    
    def calculate_version_priority_score(self, has_rapidgator, has_katfile, has_other_known_hosts, has_any_links, post_date):
        """
        Calculate priority score for megathread version selection.
        Lower score = higher priority.
        
        Priority logic:
        1. Rapidgator links (score: 1-10)
        2. Katfile links (score: 11-20) 
        3. Other known hosts (score: 21-30)
        4. Any links (score: 31-40)
        5. No links (score: 41-50)
        
        Within each category, newer posts get lower scores.
        """
        import time
        from datetime import datetime
        
        # Base score by link type
        if has_rapidgator:
            base_score = 1
        elif has_katfile:
            base_score = 11
        elif has_other_known_hosts:
            base_score = 21
        elif has_any_links:
            base_score = 31
        else:
            base_score = 41
        
        # Add date factor (newer posts get lower scores)
        date_factor = 0
        if post_date:
            try:
                # Calculate days ago (newer = lower score)
                now = datetime.now()
                days_ago = (now - post_date).days
                date_factor = min(days_ago * 0.1, 9)  # Max 9 points for date
            except:
                date_factor = 5  # Default middle value
        else:
            date_factor = 5  # Default for posts without date
        
        return base_score + date_factor

    def unify_and_select_best_post(self, candidate_posts):
        """
        Given candidate_posts, unify their version titles and pick the best post.

        Steps:
        1. Check if all version titles are essentially referring to the same magazine/issue.
           We'll do a simple heuristic: If the similarity between each version title and
           the first version title is high, consider them the same.
        2. Unify all version titles to the first post's version title (or the most standard looking one).
        3. Filter posts by those that have Rapidgator links, pick the latest by date/time.
        4. If no Rapidgator post is found, pick the latest post anyway.

        candidate_posts structure:
        {
            'version_title': ...,
            'links': {host: [urls], ...},
            'bbcode_content': ...,
            'thread_id': ...,
            'thread_url': ...,
            'has_rapidgator': bool,
            'has_known_hosts': bool,
            'has_any_links': bool,
            'post_datetime': datetime object
        }
        """
        if not candidate_posts:
            return None

        # Step 1: Check similarity among version titles
        base_title = candidate_posts[0]['version_title']
        def title_similarity(t1, t2):
            return difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio()

        # If all similar to base_title > 0.3, unify
        all_same = all(title_similarity(base_title, p['version_title']) > 0.3 for p in candidate_posts)

        unified_title = base_title if all_same else base_title

        for p in candidate_posts:
            p['version_title'] = unified_title

        # Step 3: Pick best post
        # Prefer posts with Rapidgator and latest by date/time
        rapidgator_posts = [p for p in candidate_posts if p['has_rapidgator']]
        if rapidgator_posts:
            # sort by datetime descending, pick latest
            rapidgator_posts.sort(key=lambda x: x['post_datetime'], reverse=True)
            best_post = rapidgator_posts[0]
            return best_post

        # If no rapidgator, pick latest post anyway
        candidate_posts.sort(key=lambda x: x['post_datetime'], reverse=True)
        return candidate_posts[0]

    def get_post_date_time(self, post_element):
        """
        Extracts the post date/time from a post element.
        We look for a smallfont div that is not styled, similar to how we got the thread date.
        Example formats: "Heute, 07:36"
        We'll convert 'Heute' to today's date and parse the time.
        """
        parent_td = post_element.find_parent('td')
        if not parent_td:
            return None
        date_div = parent_td.find_next('div', class_='smallfont')
        if not date_div or date_div.has_attr('style'):
            return None

        date_text = date_div.get_text(separator=",").split(",")[-1].strip()
        # date_text might look like "Heute, 07:36"
        # Let's parse it:
        # If "Heute", use today's date:
        # If "Gestern", use yesterday's date:
        # If a normal date, parse it.
        # We'll handle Heute/Gestern only for this scenario.

        today = datetime.now()
        if 'heute' in date_text.lower():
            # Extract time after "Heute,"
            time_part = date_text.lower().replace('heute', '').strip(', ').strip()
            # parse HH:MM
            try:
                post_time = datetime.strptime(time_part, "%H:%M").time()
                post_datetime = datetime.combine(today.date(), post_time)
                return post_datetime
            except:
                return today  # fallback

        elif 'gestern' in date_text.lower():
            time_part = date_text.lower().replace('gestern', '').strip(', ').strip()
            try:
                post_time = datetime.strptime(time_part, "%H:%M").time()
                post_datetime = datetime.combine((today - timedelta(days=1)).date(), post_time)
                return post_datetime
            except:
                return today - timedelta(days=1)

        else:
            # Try parsing a known date format like %d.%m.%Y etc. If fails, just return today.
            # Since original scenario uses "Heute", this is a fallback.
            return today

    def preprocess_post_html(self, post_element):
        """
        Clean HTML before converting to BBCode:
        - Replace <a><img></a> with <img src="real_link">
        """
        soup = BeautifulSoup(str(post_element), "html.parser")

        # Loop over all <a> tags that contain <img>
        for a_tag in soup.find_all("a"):
            img_tag = a_tag.find("img")
            if img_tag:
                # Keep only the <img> and remove the <a>
                a_tag.replace_with(img_tag)

        return str(soup)

    def convert_post_html_to_bbcode(self, post_element):
        """
        Converts HTML content to BBCode.
        Ensures that image src links are preserved even if inside <a>.
        """
        import html
        import re
        from bs4 import BeautifulSoup

        if not post_element:
            return "[CENTER]No content available.[/CENTER]"

        soup = BeautifulSoup(str(post_element), "html.parser")

        # 1️⃣ أي <img> جوه <a> → استبدلها بـ BBCode صورة
        for a_tag in soup.find_all("a"):
            img_tag = a_tag.find("img")
            if img_tag and img_tag.get("src"):
                src = img_tag["src"]
                if src.startswith("//"):
                    src = "https:" + src
                a_tag.replace_with(f"[img]{src}[/img]")

        # 2️⃣ أي <img> مش جوه <a> → استبدلها بـ BBCode صورة
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src", "")
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                img_tag.replace_with(f"[img]{src}[/img]")

        bbcode = str(soup)

        # 3️⃣ الروابط العادية (بعد الصور)
        bbcode = re.sub(
            r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            lambda m: f"[url={m.group(1)}]{m.group(2)}[/url]",
            bbcode,
            flags=re.IGNORECASE
        )

        # 4️⃣ التنسيقات
        bbcode = re.sub(r'<br\s*/?>', '\n', bbcode, flags=re.IGNORECASE)
        bbcode = re.sub(r'<b>(.*?)</b>', r'[b]\1[/b]', bbcode, flags=re.IGNORECASE)
        bbcode = re.sub(r'<strong>(.*?)</strong>', r'[b]\1[/b]', bbcode, flags=re.IGNORECASE)
        bbcode = re.sub(r'<i>(.*?)</i>', r'[i]\1[/i]', bbcode, flags=re.IGNORECASE)
        bbcode = re.sub(r'<em>(.*?)</em>', r'[i]\1[/i]', bbcode, flags=re.IGNORECASE)
        bbcode = re.sub(r'<u>(.*?)</u>', r'[u]\1[/u]', bbcode, flags=re.IGNORECASE)

        # 5️⃣ مسح أي وسوم HTML متبقية
        bbcode = re.sub(r'<[^>]+>', '', bbcode)

        # 6️⃣ فك ترميزات HTML
        bbcode = html.unescape(bbcode)

        # 7️⃣ إزالة الفراغات الزايدة
        bbcode = re.sub(r'\n\s*\n\s*\n+', '\n\n', bbcode).strip()

        return bbcode

    def get_megathread_post_id(self, post_element):
        """
        Extract thread/post ID from the post_element, similar to normal posts.
        If in normal posts we got it from something like post_message_123456, we do the same here.
        """
        post_id_match = re.search(r'post_message_(\d+)', post_element.get('id', ''))
        if post_id_match:
            return post_id_match.group(1)
        return None

        # ملف: selenfdt.py

    def navigate_to_megathread_category(self, category_url, date_filter, page_from=1, page_to=1):
        """
        بعد إيجاد MegaThreads، نختار أفضل نسخة من كل موضوع فرعي
        وترجع dict بالشكل {main_thread_title: best_version_data}.
        """

        # 1) تأكد من تسجيل الدخول
        if not self.is_logged_in:
            if not self.login(current_url=category_url):
                logging.error("Cannot proceed without login.")
                return {}

        # 2) طبع رابط الكاتيجوري
        category_url = self.normalize_category_url(category_url)

        # 3) لو الفلتر List، حوّله لنص
        if isinstance(date_filter, list):
            date_filter = ",".join(date_filter)

        # 4) parse_date_filter ينتظر String
        date_ranges = self.parse_date_filter(date_filter)

        # DEBUG: تأكد إن اللوب بياخد صفحة من وإلى
        logging.info(f"[Megathreads] Pages {page_from}→{page_to}")

        # 5) اجمع كل الميجاثريدز عبر الصفحات
        megathreads_data = {}
        for page_number in range(page_from, page_to + 1):
            # نفس Pagination بتاع الـ Posts: -<n>/ للصفحات التانية
            if page_number > 1:
                page_url = f"{category_url.rstrip('/')}-{page_number}/"
            else:
                page_url = category_url

            logging.info(f"[Megathreads] Visiting: {page_url}")
            self.driver.get(page_url)
            time.sleep(3)

            # لو رُدّ لصفحة لوجين
            if "/login" in self.driver.current_url:
                logging.warning(f"[Megathreads] Redirected to login from {page_url}. Re-login.")
                self.is_logged_in = False
                if not self.login(current_url=page_url):
                    logging.error("[Megathreads] Re-login failed.")
                    return {}
                self.driver.get(page_url)
                time.sleep(3)

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            elems = soup.select('a[id^="thread_title_"]')
            logging.debug(f"[Megathreads] Page {page_number}: {len(elems)} threads")

            for el in elems:
                title = el.get_text(strip=True)
                href  = el['href']
                # أطوّل اللينك لو نسبي
                if href.startswith('/'):
                    href = self.forum_url.rstrip('/') + href
                elif not href.startswith('http'):
                    href = self.forum_url.rstrip('/') + '/' + href.lstrip('/')

                parent_td = el.find_parent('td')
                if not parent_td:
                    continue
                date_div = parent_td.find_next('div', class_='smallfont')
                if not date_div or date_div.has_attr('style'):
                    continue
                date_text = date_div.get_text(separator=",").split(",")[-1].strip()

                if self.match_date(date_ranges, date_text):
                    if title not in megathreads_data:
                        megathreads_data[title] = {'url': href, 'date': date_text}

        # 6) استخرج أحدث نسخة لكل ميجاتريد مع المراقبة المستمرة
        new_versions = {}
        for title, info in megathreads_data.items():
            last = self.get_megathread_last_page(info['url']) or info['url']
            
            # Get last check timestamp for continuous monitoring
            last_check_timestamp = getattr(self, 'megathread_last_check', {}).get(title, None)
            
            # Extract latest version with continuous monitoring
            ver = self.extract_megathread_latest_version(last, last_check_timestamp)
            if ver:
                new_versions[title] = ver
                
                # Update last check timestamp
                if not hasattr(self, 'megathread_last_check'):
                    self.megathread_last_check = {}
                self.megathread_last_check[title] = datetime.now()
                
                logging.info(f"🔄 Updated last check timestamp for '{title}'")

        return new_versions

    def extract_megathread_posts_on_page(self, page_url):
        """
        Extract all megathread posts from the given page URL, using same logic as normal posts.
        We already have a pattern: posts are divs with id^='post_message_'.
        """
        self.driver.get(page_url)
        time.sleep(3)  # Wait for the page to load
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')

        posts = soup.find_all('div', id=re.compile(r'post_message_\d+'))
        return posts

    def get_megathread_post_date(self, post_element):
        """
        Extracts the post date from a megathread post element using the same logic as normal posts.
        We will:
        - Find a parent <td>, then find the next <div class='smallfont'> without style.
        - Extract the date text and parse it using the same formats and logic as normal posts.
        """
        parent_td = post_element.find_parent('td')
        if not parent_td:
            return None
        date_div = parent_td.find_next('div', class_='smallfont')
        if not date_div or date_div.has_attr('style'):
            return None

        date_text = date_div.get_text(separator=",").split(",")[-1].strip()

        date_formats = ["%d.%m.%Y", "%d.%m.%y", "%d.%m.", "%d.%m"]
        thread_date = None
        for fmt in date_formats:
            try:
                if fmt in ["%d.%m.", "%d.%m"]:
                    # Assume current year if year is missing
                    thread_date = datetime.strptime(date_text, fmt).date().replace(year=datetime.now().year)
                else:
                    thread_date = datetime.strptime(date_text, fmt).date()
                break  # Successfully parsed
            except ValueError:
                continue

        if not thread_date:
            date_text_lower = date_text.lower()
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            if 'heute' in date_text_lower:
                thread_date = today
            elif 'gestern' in date_text_lower:
                thread_date = yesterday
            else:
                # Unrecognized date format
                return None

        return thread_date

    def check_megathreads_for_updates(self, existing_threads):
        """
        Checks previously tracked megathreads for any newer versions since the last check.

        Parameters:
        - existing_threads (dict): The data structure holding previously known versions of megathreads.

        Structure of existing_threads expected:
        {
          "MainThreadTitle": {
             "versions": [
                 { "thread_url": ..., "thread_id": ..., "links": {...}, "bbcode_content": ..., "version_title": ... },
                 ...
             ]
          },
          ...
        }

        Returns:
        A dictionary of new versions found:
        {
          "MainThreadTitle": {
            "links": {...},
            "bbcode_content": "...",
            "thread_id": "...",
            "version_title": "...",
            "thread_url": "..."
          },
          ...
        }
        """
        updated_versions = {}

        for main_thread_title, data in existing_threads.items():
            versions = data.get('versions', [])
            if not versions:
                # No previously known versions, skip
                continue

            # Last known version
            last_known_version = versions[-1]
            last_page_url = last_known_version.get('thread_url', '')
            if not last_page_url:
                # Can't re-check if we don't have a last_page_url
                continue

            # Re-check the last page of the thread to find if there is a newer version
            new_last_page_url = self.get_megathread_last_page(last_page_url)
            if not new_last_page_url:
                new_last_page_url = last_page_url

            current_version = self.extract_megathread_latest_version(new_last_page_url)
            if not current_version:
                # No version currently found
                continue

            # Check if current_version is newer
            if self.is_new_megathread_version(last_known_version, current_version):
                # Update versions list
                current_version['thread_url'] = new_last_page_url
                data['versions'].append(current_version)

                # Keep only the last two versions to avoid clutter
                if len(data['versions']) > 2:
                    data['versions'] = data['versions'][-2:]

                updated_versions[main_thread_title] = {
                    "links": current_version.get('links', {}),
                    "bbcode_content": current_version.get('bbcode_content', ''),
                    "thread_id": current_version.get('thread_id', ''),
                    "version_title": current_version.get('version_title', 'New Version'),
                    "thread_url": current_version.get('thread_url', '')
                }

        return updated_versions

    def is_new_megathread_version(self, last_version, current_version):
        """
        Determine if current_version is newer than last_version.

        Criteria:
        - If thread_id changed, it's definitely a new version.
        - If bbcode_content changed, consider it a new version.
        - If links differ, consider it a new version.
        - If previously we had no known hosts and now we do, it's a new version.
        - If previously had known hosts and now also have known hosts, but the sets of links differ, it's a new version.

        Returns True if a new version is detected, False otherwise.
        """
        # Check thread_id
        if current_version.get('thread_id') != last_version.get('thread_id'):
            return True

        # Check bbcode content
        prev_bbcode = last_version.get('bbcode_content', '').strip()
        curr_bbcode = current_version.get('bbcode_content', '').strip()
        if curr_bbcode != prev_bbcode:
            return True

        # Compare links
        prev_links = last_version.get('links', {})
        curr_links = current_version.get('links', {})

        if not self.compare_links(prev_links, curr_links):
            return True

        # Check known hosts scenario
        prev_known_hosts = self.extract_known_hosts(prev_links)
        curr_known_hosts = self.extract_known_hosts(curr_links)

        # If previously no known hosts and now we have some
        if not prev_known_hosts and curr_known_hosts:
            return True

        # If we reach here, no significant difference
        return False

    def compare_links(self, old_links, new_links):
        """
        Compare two link dictionaries to see if they are identical.

        Parameters:
            old_links (dict): {host: [list_of_links]}
            new_links (dict): {host: [list_of_links]}

        Returns:
            bool: True if both old and new links are identical, False otherwise.
        """
        if set(old_links.keys()) != set(new_links.keys()):
            return False

        for host in old_links:
            old_list = sorted(set(old_links[host]))
            new_list = sorted(set(new_links[host]))
            if old_list != new_list:
                return False

        return True

    def normalize_category_url(self, url):
        """
        Ensures the category URL is in the correct format and properly encoded.
        """
        # Remove any duplicate '/forum/' segments
        url = re.sub(r'(/forum/)+', '/forum/', url)

        # Split the URL into parts
        parts = url.split('/')

        # Sanitize the last part (category name) if it contains special characters
        if len(parts) > 3:
            parts[-1] = sanitize_filename(parts[-1])

        # Rejoin the URL parts
        url = '/'.join(parts)

        # Ensure the URL ends with a trailing slash
        if not url.endswith('/'):
            url += '/'

        return url

    def encode_url_component(self, component):
        """
        Encodes URL component using the forum's specific encoding for special characters.
        """
        # Custom encoding for special characters
        char_map = {
            'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
            'é': 'e', 'è': 'e', 'ê': 'e',
            'á': 'a', 'à': 'a', 'â': 'a',
            'ó': 'o', 'ò': 'o', 'ô': 'o',
            'ú': 'u', 'ù': 'u', 'û': 'u',
            ' ': '-'
        }

        for char, replacement in char_map.items():
            component = component.replace(char, replacement)

        # Remove any characters that are not alphanumeric, hyphen, or underscore
        encoded = re.sub(r'[^a-zA-Z0-9-_]', '', component)
        return encoded

    def is_new_megathread_version(self, current_version, last_version):
        """
        Determines if current_version represents a new version of the megathread
        compared to last_version.
        
        Criteria:
        - If thread_id changed, it's definitely a new version.
        - If bbcode_content changed, consider it a new version.
        - If links differ, consider it a new version.
        - If previously we had no known hosts and now we do, it's a new version.
        - If previously had known hosts and now also have known hosts, but the sets of links differ, it's a new version.
        
        Returns True if a new version is detected, False otherwise.
        """
        # Check thread_id
        if current_version.get('thread_id') != last_version.get('thread_id'):
            return True
        
        # Check bbcode content
        prev_bbcode = last_version.get('bbcode_content', '').strip()
        curr_bbcode = current_version.get('bbcode_content', '').strip()
        if curr_bbcode != prev_bbcode:
            return True
        
        # Compare links
        prev_links = last_version.get('links', {})
        curr_links = current_version.get('links', {})
        
        if not self.compare_links(prev_links, curr_links):
            return True
        
        # Check known hosts scenario
        prev_known_hosts = self.extract_known_hosts(prev_links)
        curr_known_hosts = self.extract_known_hosts(curr_links)
        
        # If previously no known hosts and now we have some
        if not prev_known_hosts and curr_known_hosts:
            return True
        
        # If we reach here, no significant difference
        return False
        
    def compare_links(self, old_links, new_links):
        """
        Compare two link dictionaries to see if they are identical.
        
        Parameters:
            old_links (dict): {host: [list_of_links]}
            new_links (dict): {host: [list_of_links]}
        
        Returns:
            bool: True if both old and new links are identical, False otherwise.
        """
        if set(old_links.keys()) != set(new_links.keys()):
            return False
        
        for host in old_links:
            old_list = sorted(set(old_links[host]))
            new_list = sorted(set(new_links[host]))
            if old_list != new_list:
                return False
        
        return True

    def normalize_category_url(self, url):
        """
        Ensures the category URL is in the correct format and properly encoded.
        """
        # Remove any duplicate '/forum/' segments
        url = re.sub(r'(/forum/)+', '/forum/', url)
        
        # Split the URL into parts
        parts = url.split('/')
        
        # Sanitize the last part (category name) if it contains special characters
        if len(parts) > 3:
            parts[-1] = sanitize_filename(parts[-1])
        
        # Rejoin the URL parts
        url = '/'.join(parts)
        
        # Ensure the URL ends with a trailing slash
        if not url.endswith('/'):
            url += '/'
        
        return url
        
    def encode_url_component(self, component):
        """
        Encodes URL component using the forum's specific encoding for special characters.
        """
        # Custom encoding for special characters
        char_map = {
            'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
            'é': 'e', 'è': 'e', 'ê': 'e',
            'á': 'a', 'à': 'a', 'â': 'a',
            'ó': 'o', 'ò': 'o', 'ô': 'o',
            'ú': 'u', 'ù': 'u', 'û': 'u',
            ' ': '-'
        }
        
        for char, replacement in char_map.items():
            component = component.replace(char, replacement)
        
        # Remove any characters that are not alphanumeric, hyphen, or underscore
        encoded = re.sub(r'[^a-zA-Z0-9-_]', '', component)
        
        return encoded

    def extract_threads(self, date_ranges):
        """
        Extracts threads from the current page and filters them based on the date ranges.
        TRUE SINGLE-VISIT: Process each matching thread immediately without collecting first.
        """
        try:
            logging.info("🧵 TRUE Single-Visit: Processing threads immediately when found...")
            

            # Store the original forum page URL and base URL before any processing
            original_forum_url = self.driver.current_url
            base_url = original_forum_url.split('/forum/')[0]  # Get base domain once
            logging.debug(f"🏠 Using base URL: {base_url}")
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            thread_elements = soup.select('a[id^="thread_title_"]')
            
            logging.info(f"📊 Found {len(thread_elements)} threads to analyze...")
            
            threads_processed = 0
            threads_with_hosts = 0
            threads_for_review = 0
            
            # SINGLE PASS: Check date filter and process immediately if matches
            # Use index to avoid re-parsing page after each thread
            thread_index = 0
            while thread_index < len(thread_elements):
                thread = thread_elements[thread_index]
                thread_title = thread.text.strip()
                thread_url = thread['href']
                
                # CRITICAL: Increment thread_index IMMEDIATELY to prevent infinite loop
                thread_index += 1
                
                # Convert relative URL to absolute URL using stored base_url
                original_url = thread_url
                if thread_url.startswith('/') or thread_url.startswith('showthread.php'):
                    if thread_url.startswith('/'):
                        thread_url = base_url + thread_url
                    else:
                        thread_url = base_url + '/' + thread_url
                    logging.debug(f"🔗 Converted relative URL '{original_url}' to absolute URL '{thread_url}'")
                
                thread_id = thread_url.split('=')[-1]  # Extract thread ID
            
                # Find the correct div.smallfont next to the thread title without style attribute
                try:
                    parent_td = thread.find_parent('td')
                    if parent_td:
                        date_div = parent_td.find_next('div', class_='smallfont')
                        if date_div and not date_div.has_attr('style'):
                            date_text = date_div.get_text(separator=",").split(",")[
                                -1].strip()  # Extract the date portion
                        else:
                            logging.warning(f"⚠️ Could not find date for thread '{thread_title}'. Skipping.")
                            continue
                    else:
                        logging.warning(f"⚠️ Could not find parent td for thread '{thread_title}'. Skipping.")
                        continue
                except Exception as e:
                    logging.warning(f"⚠️ Error processing date for thread '{thread_title}': {e}")
                    continue
            
                # Check if the thread date matches any of the date ranges FIRST
                if self.match_date(date_ranges, date_text):
                    # Only AFTER date match, check if thread was already processed for THIS session
                    if thread_id in self.processed_thread_ids:
                        logging.debug(f"⏭️ Thread '{thread_title}' with ID '{thread_id}' already processed in this session. Skipping.")
                        continue
                    logging.info(f"✅ Thread '{thread_title}' matches date filter. Processing IMMEDIATELY...")
                    
                    # IMMEDIATE PROCESSING - Extract file hosts and links RIGHT NOW
                    try:
                        logging.debug(f"🔍 Processing thread URL: {thread_url}")
                        file_hosts, links_dict, html_content, author = self.extract_file_hosts(thread_url)
                        
                        # Create thread data structure with HTML content to avoid double visits
                        thread_data = {
                            'thread_id': thread_id,
                            'thread_title': thread_title,
                            'thread_url': thread_url,
                            'file_hosts': file_hosts,
                            'links': links_dict,
                            'has_known_hosts': bool(file_hosts),
                            'html_content': html_content,  # Include HTML to avoid double visit
                            'author': author
                        }
                        
                        # Store in extracted_threads
                        self.extracted_threads[thread_id] = thread_data
                        threads_processed += 1
                        
                        if file_hosts or links_dict:
                            threads_with_hosts += 1
                            logging.info(f"✅ Successfully processed thread '{thread_title}' with {len(file_hosts)} known hosts and {sum(len(v) for v in links_dict.values())} total links")
                        else:
                            threads_for_review += 1
                            logging.info(f"📝 Added thread '{thread_title}' for manual review (no known hosts detected)")
                        
                        # Mark as processed
                        self.processed_thread_ids.add(thread_id)
                        # Save immediately to prevent data loss
                        self.save_processed_thread_ids()
                        
                        # Return to forum page immediately after processing this thread
                        logging.debug(f"🔙 Returning to forum page after processing '{thread_title}'")
                        self.driver.get(original_forum_url)
                        time.sleep(1)  # Brief pause
                        
                    except Exception as e:
                        logging.error(f"❌ Error processing thread '{thread_title}': {e}", exc_info=True)
                        # Mark as processed even if there was an error to avoid reprocessing
                        self.processed_thread_ids.add(thread_id)
                        # Save immediately to prevent data loss
                        self.save_processed_thread_ids()
                        # Return to forum page even on error
                        try:
                            self.driver.get(original_forum_url)
                            time.sleep(1)
                        except:
                            pass
                        
                else:
                    logging.debug(f"❌ Thread '{thread_title}' does not match date filter. Skipping.")
            
            # Log processing summary
            logging.info(f"📊 TRUE Single-Visit complete: {threads_processed} total threads ({threads_with_hosts} with known hosts, {threads_for_review} for manual review)")
            
            if threads_processed == 0:
                logging.info("📭 No matching threads found on this page.")
                
        except Exception as e:
            self.handle_exception("extracting threads from current page", e)
    
    def _process_threads_batch(self, threads_list):
        """
        DEPRECATED: This method is no longer used with single-visit optimization.
        Process a batch of threads to extract file hosts and links efficiently.
        Now includes ALL threads that match date filter, regardless of known hosts.
        """
        # Clear extracted_threads for this batch to ensure clean state
        self.extracted_threads.clear()
        logging.debug(f"🧹 Cleared extracted_threads for new batch of {len(threads_list)} threads")
        
        for thread_info in threads_list:
            try:
                thread_id = thread_info['id']
                thread_title = thread_info['title']
                thread_url = thread_info['url']
                
                # Skip if already processed
                if thread_id in self.processed_thread_ids:
                    logging.debug(f"⏭️ Thread '{thread_title}' already processed. Skipping.")
                    continue
                    
                logging.info(f"🔍 Processing thread: '{thread_title}'...")
                
                # Extract file hosts and links from this thread
                file_hosts, links_dict, _, author = self.extract_file_hosts(thread_url)
                
                # Create thread data structure - include ALL threads that matched date filter
                thread_data = {
                    'thread_id': thread_id,
                    'thread_title': thread_title,
                    'thread_url': thread_url,
                    'file_hosts': file_hosts,
                    'links': links_dict,
                    'has_known_hosts': bool(file_hosts),  # Flag to indicate if known hosts were found
                    'author': author
                }
                # Store in dictionary with thread_id as key (original structure)
                self.extracted_threads[thread_id] = thread_data
                
                if file_hosts or links_dict:
                    logging.info(f"✅ Successfully processed thread '{thread_title}' with {len(file_hosts)} known hosts and {sum(len(v) for v in links_dict.values())} total links")
                else:
                    logging.info(f"📝 Added thread '{thread_title}' for manual review (no known hosts detected)")
                
                # Mark as processed regardless of whether we found hosts
                self.processed_thread_ids.add(thread_id)
                # Save immediately to prevent data loss
                self.save_processed_thread_ids()
                
            except Exception as e:
                logging.error(f"❌ Error processing thread '{thread_info.get('title', 'Unknown')}': {e}", exc_info=True)
                # Mark as processed even if there was an error to avoid reprocessing
                if 'thread_id' in locals():
                    self.processed_thread_ids.add(thread_id)
                continue
        
        # Log batch processing summary
        total_threads = len(self.extracted_threads)
        threads_with_hosts = sum(1 for thread in self.extracted_threads.values() if thread.get('has_known_hosts', False))
        threads_for_review = total_threads - threads_with_hosts
        logging.info(f"📊 Batch processing complete: {total_threads} total threads ({threads_with_hosts} with known hosts, {threads_for_review} for manual review)")
    
    def parse_date_filter(self, date_filter):
        """
        Enhanced date filter parsing that supports German keywords (heute, gestern),
        full years, ISO and German-style ranges, and single dates.
        """
        date_ranges = []
        filters = date_filter.split(',')
        today = datetime.now().date()
        
        logging.debug(f"📅 Parsing date filters: {filters}")
        
        for f in filters:
            f = f.strip().lower()
            logging.debug(f"🔍 Processing filter: {f}")
            
            # Handle German keywords
            if f == 'heute':
                date_ranges.append((today, today))
                continue
            if f == 'gestern':
                yesterday = today - timedelta(days=1)
                date_ranges.append((yesterday, yesterday))
                continue
                
            # Handle full year (e.g., "2024")
            if re.match(r'^\d{4}$', f):
                year = int(f)
                start = date(year, 1, 1)
                end = date(year, 12, 31)
                date_ranges.append((start, end))
                continue
                
            # Handle dd.mm.yyyy or d.m.yyyy - support flexible formats
            m = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', f)
            if m:
                d, mo, y = map(int, m.groups())
                try:
                    obj = date(year=y, month=mo, day=d)
                    date_ranges.append((obj, obj))
                    logging.debug(f"✅ Parsed German date '{f}' -> {obj}")
                except ValueError as e:
                    logging.error(f"❌ Invalid German date in filter '{f}': {e}")
                continue
                
            # Handle date ranges with various separators
            if '→' in f or '->' in f or ':' in f:
                sep = '→' if '→' in f else ('->' if '->' in f else ':')
                parts = [p.strip() for p in f.split(sep)]
                if len(parts) == 2:
                    try:
                        def to_date(s):
                            if '-' in s:
                                return datetime.strptime(s, "%Y-%m-%d").date()
                            else:
                                d1, m1, y1 = map(int, s.split('.'))
                                return date(y1, m1, d1)
                                
                        start = to_date(parts[0])
                        end = to_date(parts[1])
                        date_ranges.append((start, end))
                    except Exception as e:
                        logging.error(f"❌ Invalid range filter '{f}': {e}", exc_info=True)
                continue
                
            # Handle dd.mm format (using current year)
            m2 = re.match(r'^(\d{1,2})\.(\d{1,2})$', f)
            if m2:
                d, mo = map(int, m2.groups())
                try:
                    obj = date(year=today.year, month=mo, day=d)
                    date_ranges.append((obj, obj))
                except ValueError:
                    logging.error(f"❌ Invalid date in filter '{f}'", exc_info=True)
                continue
                
            logging.warning(f"⚠️ Unrecognized date filter '{f}' - will be ignored.")
            
        return date_ranges

    def match_date(self, date_ranges, date_text):
        """
        Checks if the date matches any of the given date ranges.
        """
        logging.debug(f"Matching date for thread. date_text: '{date_text}', date_ranges: {date_ranges}")

        if not date_ranges:
            logging.debug("No date ranges provided. Skipping thread.")
            return False

        thread_date_str = date_text.strip()
        logging.debug(f"Extracted thread_date_str: '{thread_date_str}'")

        # Try known formats
        date_formats = ["%d.%m.%Y", "%d.%m.%y", "%d.%m.", "%d.%m"]

        thread_date = None
        for fmt in date_formats:
            try:
                if fmt in ["%d.%m.", "%d.%m"]:
                    # Assume current year if year is missing
                    thread_date = datetime.strptime(thread_date_str, fmt).date().replace(year=datetime.now().year)
                else:
                    thread_date = datetime.strptime(thread_date_str, fmt).date()
                logging.debug(f"Parsed thread date with format '{fmt}': {thread_date}")
                break  # Successfully parsed
            except ValueError:
                continue

        # If parsing didn't work, check for 'heute' or 'gestern'
        if not thread_date:
            date_text_lower = date_text.lower()
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            if 'heute' in date_text_lower:
                thread_date = today
            elif 'gestern' in date_text_lower:
                thread_date = yesterday
            else:
                # Unrecognized date format
                logging.warning(f"Unrecognized date format: '{date_text}'. Skipping thread.")
                return False

        # Now compare thread_date with date_ranges
        for date_range in date_ranges:
            if isinstance(date_range, tuple):
                # This handles both monthly and yearly ranges
                if date_range[0] <= thread_date <= date_range[1]:
                    logging.debug(f"Thread date {thread_date} is within range {date_range}")
                    return True
            elif isinstance(date_range, date):
                if thread_date == date_range:
                    logging.debug(f"Thread date {thread_date} matches {date_range}")
                    return True
            elif date_range == 'heute':
                if thread_date == datetime.now().date():
                    logging.debug("Thread date matches 'heute'")
                    return True
            elif date_range == 'gestern':
                if thread_date == (datetime.now().date() - timedelta(days=1)):
                    logging.debug("Thread date matches 'gestern'")
                    return True

        logging.debug(f"Thread date {thread_date} does not match any date ranges.")
        return False

    def extract_file_hosts(self, thread_url):
        """
        Navigate to the given thread URL and extract file hosts and links.
        The method also grabs the raw HTML content and the author's name so
        that callers can store them without re-visiting the page.

        Returns:
            tuple[list[str], dict, str, str]:
                A tuple containing the list of file hosts found, a dictionary of
                links grouped by host, the raw HTML content of the page, and the
                thread author's name.
        """
        try:
            logging.info(f"Navigating to thread URL: {thread_url}")
            self.driver.get(thread_url)
            time.sleep(3)  # Wait for thread page to load

            # Store HTML content to avoid double visits
            html_content = self.driver.page_source
            soup = BeautifulSoup(html_content, 'html.parser')

            # Extract thread author from the first post
            author_elem = soup.select_one('td.alt2 a.bigusername span')
            author = author_elem.get_text(strip=True) if author_elem else ''

            # Initialize containers
            file_hosts_found = set()
            links_dict = {}  # Dictionary to store links grouped by file host
            keeplinks_urls = set()  # Set to store unique keeplinks.org URLs

            # Find all post containers separated by <td class="thead">
            all_posts = soup.find_all(lambda tag: tag.name == 'td' and 'thead' in tag.get('class', []))

            # Extract from the main post (first post)
            if all_posts:
                main_post = all_posts[0].find_previous('div', {'id': re.compile(r'post_message_\d+')})
                if main_post:
                    logging.info("Extracting links from main post.")
                    self.extract_links_from_post(main_post, file_hosts_found, links_dict, keeplinks_urls)

            # If known links are found in the main post, stop further processing
            if file_hosts_found:
                logging.info(f"Known links found in main post. Skipping reply and keeplinks.org processing.")
                return list(file_hosts_found), links_dict, html_content, author

            # If no known links found in main post, proceed to process replies
            for i in range(1, len(all_posts)):
                reply = all_posts[i].find_previous('div', {'id': re.compile(r'post_message_\d+')})
                if reply:
                    logging.info(f"Extracting links from reply {i}")
                    self.extract_links_from_post(reply, file_hosts_found, links_dict, keeplinks_urls)

                    # If known links are found, stop further processing
                    if file_hosts_found:
                        logging.info(
                            f"Known links found in replies. Skipping remaining replies and keeplinks.org processing.")
                        return list(file_hosts_found), links_dict, html_content, author

            # Add keeplinks as a normal host if no other hosts found
            if not file_hosts_found and keeplinks_urls:
                logging.info("No known links found, adding keeplinks.org as normal host.")
                links_dict['keeplinks'] = list(keeplinks_urls)

            # Remove duplicate links per host
            for host in links_dict:
                links_dict[host] = list(set(links_dict[host]))

            return list(file_hosts_found), links_dict, html_content, author

        except Exception as e:
            self.handle_exception(f"extracting file hosts and links from thread '{thread_url}'", e)
            return [], {}, "", ""

    def extract_links_from_post(self, post, file_hosts_found, links_dict, keeplinks_urls):
        """
        Helper function to extract links from a given post (either main or reply).
        Updates the file_hosts_found, links_dict, and keeplinks_urls sets as needed.
        """
        # Extract links from <a> tags
        a_tags = post.find_all('a', href=True)
        logging.debug(f"Found {len(a_tags)} <a> tags with href.")
        for link in a_tags:
            href = link['href']
            self.process_link(href, file_hosts_found, links_dict)
            # Also collect keeplinks URLs for potential fallback
            if 'keeplinks.org' in href:
                keeplinks_urls.add(href)

        # Extract links from <pre class="alt2"> blocks
        pre_tags = post.find_all('pre', class_='alt2')
        logging.debug(f"Found {len(pre_tags)} <pre class='alt2'> blocks.")
        for pre in pre_tags:
            pre_text = pre.get_text(separator="\n")
            urls_in_pre = re.findall(r'(https?://[^\s<>]+)', pre_text)
            logging.debug(f"Extracted {len(urls_in_pre)} URLs from <pre class='alt2'>.")
            for url in urls_in_pre:
                self.process_link(url, file_hosts_found, links_dict)
                # Also collect keeplinks URLs for potential fallback
                if 'keeplinks.org' in url:
                    keeplinks_urls.add(url)

        # Extract links from <quote> elements (optional, if applicable)
        quote_tags = post.find_all('quote')
        logging.debug(f"Found {len(quote_tags)} <quote> elements.")
        for quote in quote_tags:
            quote_text = quote.get_text(separator="\n")
            urls_in_quote = re.findall(r'(https?://[^\s<>]+)', quote_text)
            logging.debug(f"Extracted {len(urls_in_quote)} URLs from <quote>.")
            for url in urls_in_quote:
                if 'keeplinks.org' in url:
                    keeplinks_urls.add(url)
                    logging.debug(f"Added Keeplinks URL: {url}")
                else:
                    self.process_link(url, file_hosts_found, links_dict)

        # **New Addition:** Extract links from nested 'div.alt2 code code' elements
        nested_code_elements = post.select('div.alt2 code code')
        logging.debug(f"Found {len(nested_code_elements)} nested <code> elements within <div class='alt2'>.")
        for code_element in nested_code_elements:
            # Change separator from ' ' to ''
            inner_text = code_element.get_text(separator='')
            # Use regex to extract URLs from the inner text
            urls_in_code = re.findall(r'(https?://[^\s<>]+)', inner_text)
            logging.debug(f"Extracted {len(urls_in_code)} URLs from nested <code> element.")
            for url in urls_in_code:
                # Clean the URL by removing any trailing non-URL characters
                cleaned_url = url.strip().strip('&nbsp;').strip('<br>').strip()
                if 'keeplinks.org' in cleaned_url:
                    keeplinks_urls.add(cleaned_url)
                    logging.debug(f"Added Keeplinks URL: {cleaned_url}")
                else:
                    # Identify the host and categorize accordingly
                    parsed_url = re.findall(r'https?://([^/]+)/', cleaned_url)
                    if parsed_url:
                        host = parsed_url[0].lower()
                        for known_host in self.known_file_hosts:
                            if known_host in host:
                                file_hosts_found.add(known_host)
                                if known_host not in links_dict:
                                    links_dict[known_host] = []
                                links_dict[known_host].append(cleaned_url)
                                logging.debug(f"Added URL '{cleaned_url}' under host '{known_host}'.")
                                break  # Stop checking other known hosts if matched

    def process_link(self, url, file_hosts_found, links_dict):
        """
        Process a single link, updating file_hosts_found and links_dict.
        Handles rg.to URLs by normalizing them to rapidgator.net.
        Handles keeplinks.org URLs by adding them under the 'rapidgator' key.
        """
        parsed_url = re.findall(r'https?://([^/]+)/', url)
        if not parsed_url:
            return
            
        host = parsed_url[0].lower()
        
        # Special handling for keeplinks.org URLs - add under rapidgator key
        if 'keeplinks.org' in host:
            target_host = 'rapidgator.net'
            file_hosts_found.add(target_host)
            if target_host not in links_dict:
                links_dict[target_host] = []
            links_dict[target_host].append(url)
            logging.info(f"🔗 Added Keeplinks URL under rapidgator: {url}")
            return
            
        # Process other known hosts
        for known_host in self.known_file_hosts:
            if known_host in host:
                # Special handling for rg.to URLs - normalize to rapidgator.net
                if known_host == 'rg.to' or host == 'rg.to':
                    # Convert rg.to URL to rapidgator.net
                    normalized_url = url.replace('rg.to', 'rapidgator.net')
                    target_host = 'rapidgator.net'
                    
                    file_hosts_found.add(target_host)
                    if target_host not in links_dict:
                        links_dict[target_host] = []
                    links_dict[target_host].append(normalized_url)
                    
                    logging.info(f"🔄 Normalized rg.to URL: {url} -> {normalized_url}")
                else:
                    # Regular host processing
                    file_hosts_found.add(known_host)
                    if known_host not in links_dict:
                        links_dict[known_host] = []
                    links_dict[known_host].append(url)
                
                break  # Stop checking other known hosts if matched

    def solve_captcha(self, captcha: dict):
        """
        Solves reCAPTCHA using DeathByCaptcha service.
        """
        json_captcha = json.dumps(captcha)
        try:
            balance = self.dbc_client.get_balance()
            print(f'DeathByCaptcha Balance: {balance}')
            logging.info(f'DeathByCaptcha Balance: {balance}')
            if balance <= 0:
                logging.error("Insufficient balance on DeathByCaptcha account.")
                return None

            print('Solving captcha...')
            logging.info('Solving captcha...')
            self.dbc_client.is_verbose = True
            result = self.dbc_client.decode(type=4, token_params=json_captcha)
            if result:
                logging.info("Captcha solved successfully.")
                return result.get('text')
            else:
                logging.error("Failed to solve captcha.")
                return None
        except Exception as e:
            print(e)
            self.handle_exception("solving captcha", e)
            return None



    def get_page_source(self, url):
        """
        Navigates to the given URL and returns the page source.
        """
        try:
            self.driver.get(url)
            time.sleep(3)  # Wait for page to load
            return self.driver.page_source
        except Exception as e:
            self.handle_exception(f"fetching page source for URL {url}", e)
            return "Error fetching page content"

    def get_post_date_time(self, post):
        """
        Extract post date and time from megathread post.
        Returns datetime object or None if cannot be parsed.
        """
        try:
            # Look for date/time in post header or metadata
            date_elements = [
                post.find('span', class_='date'),
                post.find('div', class_='postdate'),
                post.find('td', class_='thead'),
                post.find_parent('tr').find('td', class_='thead') if post.find_parent('tr') else None,
                post.find('div', class_='smallfont')
            ]
            
            for date_elem in date_elements:
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                    # Try to parse German date/time format
                    parsed_datetime = self.parse_german_datetime(date_text)
                    if parsed_datetime:
                        return parsed_datetime
            
            return None
        except Exception as e:
            logging.debug(f"Could not extract post date/time: {e}")
            return None
    
    def parse_german_datetime(self, date_text):
        """
        Parse German date/time formats including relative terms.
        Returns datetime object or None.
        """
        from datetime import datetime, timedelta
        import re
        
        try:
            # Handle relative dates first
            date_text_lower = date_text.lower()
            now = datetime.now()
            
            if 'heute' in date_text_lower:
                # Extract time if present
                time_match = re.search(r'(\d{1,2}):(\d{2})', date_text)
                if time_match:
                    hour, minute = int(time_match.group(1)), int(time_match.group(2))
                    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return now.replace(hour=12, minute=0, second=0, microsecond=0)  # Default to noon
                
            elif 'gestern' in date_text_lower:
                yesterday = now - timedelta(days=1)
                time_match = re.search(r'(\d{1,2}):(\d{2})', date_text)
                if time_match:
                    hour, minute = int(time_match.group(1)), int(time_match.group(2))
                    return yesterday.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return yesterday.replace(hour=12, minute=0, second=0, microsecond=0)
            
            # Try various German date/time formats
            formats = [
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y, %H:%M",
                "%d.%m.%y %H:%M",
                "%d.%m.%y, %H:%M",
                "%d.%m.%Y",
                "%d.%m.%y",
                "%d.%m.",
                "%d.%m"
            ]
            
            for fmt in formats:
                try:
                    if fmt in ["%d.%m.", "%d.%m"]:
                        # Assume current year if year is missing
                        parsed = datetime.strptime(date_text, fmt).replace(year=now.year)
                        return parsed
                    else:
                        return datetime.strptime(date_text, fmt)
                except ValueError:
                    continue
            
            return None
        except Exception as e:
            logging.debug(f"Could not parse German datetime '{date_text}': {e}")
            return None

    def get_megathread_post_id(self, post):
        """
        Extract post ID from megathread post element.
        Returns post ID string or None.
        """
        try:
            # Look for post ID in various attributes
            if post.get('id'):
                post_id = post.get('id')
                if 'post_message_' in post_id:
                    return post_id.replace('post_message_', '')
                return post_id
            
            # Look for post ID in parent elements
            parent = post.find_parent('div', id=re.compile(r'post_\d+'))
            if parent and parent.get('id'):
                return parent.get('id').replace('post_', '')
            
            # Look for post ID in links or anchors
            post_link = post.find('a', href=re.compile(r'showpost.*p=(\d+)'))
            if post_link:
                match = re.search(r'p=(\d+)', post_link.get('href', ''))
                if match:
                    return match.group(1)
            
            return None
        except Exception as e:
            logging.debug(f"Could not extract post ID: {e}")
            return None

    def close(self):
        """
        Closes the WebDriver session.
        """
        try:
            self.driver.quit()
            logging.info("WebDriver session closed.")
        except Exception as e:
            self.handle_exception("closing the WebDriver", e)

    def update_download_directory(self, new_download_dir):
        """
        Updates the download directory for the bot.
        
        Args:
            new_download_dir (str): The new download directory path
        """
        if new_download_dir and new_download_dir.strip():
            self.download_dir = new_download_dir.strip()
            logging.info(f"Bot download directory updated to: {self.download_dir}")
            print(f"Bot download directory updated to: {self.download_dir}")
        else:
            logging.warning("Invalid download directory provided for bot update")

    def check_login_status(self):
        """
        Checks if the user is logged in by looking for 'Logout' or 'Abmelden' link in the page source.
        Does NOT navigate away from current page.
        """
        try:
            # Check current page source without navigating away
            page_source = self.driver.page_source.lower()
            if "logout" in page_source or "abmelden" in page_source or "log out" in page_source:
                logging.info("User is logged in.")
                return True
            else:
                logging.info("User is not logged in.")
                return False
        except Exception as e:
            self.handle_exception("checking login status", e)
            return False
    
    def upload_image_to_fastpic(self, image_url):
        """
        Uploads an image from URL to fastpic.org and returns the new image URL.
        
        Args:
            image_url (str): The original image URL to upload
            
        Returns:
            str: The new fastpic.org image URL, or original URL if upload fails
        """
        try:
            logging.info(f"🖼️ Starting fastpic.org upload for: {image_url}")
            
            # Store current page URL to return later
            original_url = self.driver.current_url
            
            # Navigate to fastpic.org
            self.driver.get("https://fastpic.org/")
            time.sleep(3)
            
            # Click "at the link" option
            try:
                switch_link = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "switch_to_copy"))
                )
                switch_link.click()
                logging.info("✅ Clicked 'at the link' option")
                time.sleep(2)
            except Exception as e:
                logging.error(f"❌ Failed to click 'at the link' option: {e}")
                return image_url
            
            # Paste the image URL in the textarea
            try:
                textarea = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "files"))
                )
                textarea.clear()
                textarea.send_keys(image_url)
                logging.info(f"✅ Pasted image URL: {image_url}")
                time.sleep(1)
            except Exception as e:
                logging.error(f"❌ Failed to paste image URL: {e}")
                return image_url
            
            # Click upload button
            try:
                upload_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "uploadButton"))
                )
                upload_button.click()
                logging.info("✅ Clicked upload button")
            except Exception as e:
                logging.error(f"❌ Failed to click upload button: {e}")
                return image_url
            
            # Wait for upload to complete and get new URL
            try:
                # Wait for the result input field to appear with the new URL
                new_url_input = WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'][style*='width: 87%']"))
                )
                
                # Get the new image URL
                new_image_url = new_url_input.get_attribute("value")
                
                if new_image_url and "fastpic.org" in new_image_url:
                    logging.info(f"🎉 Successfully uploaded to fastpic.org: {new_image_url}")
                    
                    # Return to original page
                    self.driver.get(original_url)
                    time.sleep(2)
                    
                    return new_image_url
                else:
                    logging.error("❌ No valid fastpic URL found in result")
                    return image_url
                    
            except Exception as e:
                logging.error(f"❌ Failed to get upload result: {e}")
                return image_url
                
        except Exception as e:
            logging.error(f"❌ Error uploading image to fastpic.org: {e}")
            return image_url
    
    def process_images_in_content(self, content):
        """
        Processes BBCode content to upload the first image to fastpic.org and replace it.
        
        Args:
            content (str): BBCode content containing images
            
        Returns:
            str: Updated content with first image replaced by fastpic.org URL
        """
        try:
            logging.info("🖼️ Processing images in content for fastpic.org upload")
            logging.info(f"📝 Content length: {len(content)}")
            logging.info(f"📝 Content preview: {content[:300]}...")  # Show first 300 chars
            
            # Find all IMG tags in BBCode format
            img_pattern = r'\[IMG\](https?://[^\]]+)\[/IMG\]'
            logging.info(f"🔍 Using regex pattern: {img_pattern}")
            matches = re.findall(img_pattern, content, re.IGNORECASE)
            logging.info(f"🔍 Found {len(matches)} image matches")
            
            if not matches:
                logging.info("📋 No images found in content")
                return content
            
            # Get the first image URL
            first_image_url = matches[0]
            logging.info(f"🎯 Found first image: {first_image_url}")
            
            # Upload to fastpic.org
            new_image_url = self.upload_image_to_fastpic(first_image_url)
            
            # Replace the first image URL with the new one
            if new_image_url != first_image_url:
                old_img_tag = f"[IMG]{first_image_url}[/IMG]"
                new_img_tag = f"[IMG]{new_image_url}[/IMG]"
                updated_content = content.replace(old_img_tag, new_img_tag, 1)  # Replace only first occurrence
                
                logging.info(f"✅ Replaced first image with fastpic.org URL")
                logging.info(f"📝 Old: {first_image_url}")
                logging.info(f"📝 New: {new_image_url}")
                
                return updated_content
            else:
                logging.warning("⚠️ Image upload failed, keeping original content")
                return content
                
        except Exception as e:
            logging.error(f"❌ Error processing images in content: {e}")
            return content

    def post_reply(self, thread_url, bbcode_content):
        """
        Posts a BBCode reply to a forum thread.
        
        Args:
            thread_url (str): The URL of the thread to reply to
            bbcode_content (str): The BBCode content to post
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logging.info(f"🔄 Posting BBCode reply to thread: {thread_url}")
            logging.info(f"📝 Content length: {len(bbcode_content)} characters")
            
            # Navigate to the thread
            self.driver.get(thread_url)
            time.sleep(5)  # Increased wait time
            
            # Check if user is logged in
            if not self.check_login_status():
                logging.error("❌ Not logged in. Cannot post reply.")
                return False
            
            # Remove any overlays or intercepting elements
            self._remove_overlays()
            
            # Look for the reply button or quick reply form
            try:
                # Try to find quick reply textarea first
                reply_textarea = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.NAME, "message"))
                )
                logging.info("✅ Found quick reply textarea")
                
                # Scroll to textarea and clear
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", reply_textarea)
                time.sleep(2)
                reply_textarea.clear()
                reply_textarea.send_keys(bbcode_content)
                logging.info("✅ BBCode content entered")
                
                # Look for submit button with better error handling
                submit_button = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "sbutton"))
                )
                
                if submit_button:
                    # Remove overlays again before clicking
                    self._remove_overlays()
                    
                    # Try multiple click methods
                    success = self._safe_click(submit_button, "quick reply submit")
                    if success:
                        time.sleep(8)  # Wait longer for post to process
                        
                        # Check if reply was successful
                        page_source = self.driver.page_source.lower()
                        if any(indicator in page_source for indicator in [
                            "your reply has been added", "thank", "post added", "antwort", "erfolgreich"
                        ]):
                            logging.info("✅ Reply posted successfully!")
                            return True
                        else:
                            logging.warning("⚠️ Reply may not have been posted successfully")
                            # Try to check for new post by looking at page structure
                            return self._verify_post_success()
                    else:
                        logging.error("❌ Failed to click quick reply submit button")
                        raise Exception("Quick reply click failed")
                else:
                    logging.error("❌ Submit button not found")
                    raise Exception("Submit button not found")
                    
            except Exception as e:
                logging.error(f"❌ Error in quick reply: {e}")
                
                # Try alternative method - look for "Reply" or "Post Reply" button
                try:
                    logging.info("🔄 Trying full reply form...")
                    
                    # Look for various reply button texts
                    reply_selectors = [
                        (By.PARTIAL_LINK_TEXT, "Reply"),
                        (By.PARTIAL_LINK_TEXT, "Antworten"),
                        (By.PARTIAL_LINK_TEXT, "Post Reply"),
                        (By.XPATH, "//a[contains(@href, 'newreply')]"),
                        (By.XPATH, "//input[@value='Reply' or @value='Antworten']")
                    ]
                    
                    reply_button = None
                    for selector in reply_selectors:
                        try:
                            reply_button = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable(selector)
                            )
                            logging.info(f"✅ Found reply button with selector: {selector}")
                            break
                        except:
                            continue
                    
                    if not reply_button:
                        logging.error("❌ No reply button found")
                        return False
                    
                    # Click reply button safely
                    self._safe_click(reply_button, "reply button")
                    time.sleep(5)
                    
                    # Find the message textarea in the full reply form
                    message_textarea = WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.NAME, "message"))
                    )
                    
                    # Scroll to textarea and enter content
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", message_textarea)
                    time.sleep(2)
                    message_textarea.clear()
                    message_textarea.send_keys(bbcode_content)
                    logging.info("✅ BBCode content entered in full reply form")
                    
                    # Find and click submit button
                    submit_button = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.NAME, "sbutton"))
                    )
                    
                    # Remove overlays and click safely
                    self._remove_overlays()
                    success = self._safe_click(submit_button, "full reply submit")
                    
                    if success:
                        time.sleep(8)
                        
                        # Check for success
                        page_source = self.driver.page_source.lower()
                        if any(indicator in page_source for indicator in [
                            "your reply has been added", "post", "antwort", "erfolgreich", "thank"
                        ]):
                            logging.info("✅ Full reply posted successfully!")
                            return True
                        else:
                            logging.warning("⚠️ Full reply may not have been posted successfully")
                            return self._verify_post_success()
                    else:
                        logging.error("❌ Failed to click full reply submit button")
                        return False
                        
                except Exception as e2:
                    logging.error(f"❌ Error in full reply form: {e2}")
                    return False
            
        except Exception as e:
            logging.error(f"❌ Error posting reply to {thread_url}: {e}")
            return False
    
    def _remove_overlays(self):
        """Remove overlay elements that might intercept clicks."""
        try:
            # Remove common overlay elements
            overlay_selectors = [
                "#dontfoid",
                ".overlay",
                ".modal-backdrop",
                "[style*='position: fixed'][style*='z-index']",
                "div[id*='overlay']",
                "div[class*='overlay']"
            ]
            
            for selector in overlay_selectors:
                try:
                    self.driver.execute_script(f"""
                        var elements = document.querySelectorAll('{selector}');
                        for (var i = 0; i < elements.length; i++) {{
                            elements[i].style.display = 'none';
                            elements[i].remove();
                        }}
                    """)
                except:
                    pass
                    
            logging.info("🧹 Attempted to remove overlay elements")
            
        except Exception as e:
            logging.debug(f"Error removing overlays: {e}")
    
    def _safe_click(self, element, element_name):
        """Safely click an element using multiple methods."""
        try:
            # Method 1: Regular click
            try:
                element.click()
                logging.info(f"✅ Successfully clicked {element_name} (regular click)")
                return True
            except Exception as e1:
                logging.warning(f"⚠️ Regular click failed for {element_name}: {e1}")
            
            # Method 2: JavaScript click
            try:
                self.driver.execute_script("arguments[0].click();", element)
                logging.info(f"✅ Successfully clicked {element_name} (JavaScript click)")
                return True
            except Exception as e2:
                logging.warning(f"⚠️ JavaScript click failed for {element_name}: {e2}")
            
            # Method 3: Action chains
            try:
                from selenium.webdriver.common.action_chains import ActionChains
                ActionChains(self.driver).move_to_element(element).click().perform()
                logging.info(f"✅ Successfully clicked {element_name} (ActionChains)")
                return True
            except Exception as e3:
                logging.warning(f"⚠️ ActionChains click failed for {element_name}: {e3}")
            
            # Method 4: Submit if it's a form element
            try:
                if element.tag_name.lower() in ['input', 'button'] and element.get_attribute('type') == 'submit':
                    element.submit()
                    logging.info(f"✅ Successfully submitted {element_name}")
                    return True
            except Exception as e4:
                logging.warning(f"⚠️ Submit failed for {element_name}: {e4}")
            
            logging.error(f"❌ All click methods failed for {element_name}")
            return False
            
        except Exception as e:
            logging.error(f"❌ Error in safe_click for {element_name}: {e}")
            return False
    
    def _verify_post_success(self):
        """Verify if the post was successful by checking page structure."""
        try:
            # Look for indicators that a new post was added
            time.sleep(3)
            
            # Check for common success indicators
            success_indicators = [
                "// You have posted successfully",
                "// Your post has been added",
                "// Thank you for posting",
                "postbit",  # Common class for post containers
                "post_",    # Common ID prefix for posts
            ]
            
            page_source = self.driver.page_source.lower()
            for indicator in success_indicators:
                if indicator.lower() in page_source:
                    logging.info(f"✅ Found success indicator: {indicator}")
                    return True
            
            logging.warning("⚠️ No clear success indicators found")
            return False
            
        except Exception as e:
            logging.error(f"❌ Error verifying post success: {e}")
            return False
    def auto_process_job(self, job):
        """Execute one step of Auto‑Process for the given job.
        Returns True on success, False on failure."""
        step = job.step
        try:
            if step == "download":
                download_path = Path(self.download_dir) / sanitize_filename(job.category) / str(job.thread_id)
                download_path.mkdir(parents=True, exist_ok=True)
                self.protected_category = job.category
                self.download_thread(job.title, job.url)
                job.download_folder = str(download_path)
                return True
            elif step == "modify":
                if job.download_folder:
                    from core.file_processor import FileProcessor
                    fp = FileProcessor(job.download_folder, self.config.get("winrar_exe_path", "winrar"))
                    fp._modify_files_for_hash_safely(Path(job.download_folder))
                return True
            elif step == "upload":
                from urllib.parse import urlparse
                uploaded = {}
                folder = Path(job.download_folder)
                for f in folder.glob("*"):
                    if not f.is_file():
                        continue
                    result = self.initiate_upload_session(str(f))
                    if not result:
                        continue
                    for url in result.get('uploaded_urls', []):
                        host = urlparse(url).netloc
                        uploaded.setdefault(host, []).append(url)
                    if result.get('backup_rg_url'):
                        uploaded.setdefault('rapidgator-backup', []).append(result['backup_rg_url'])
                if uploaded:
                    job.uploaded_links = uploaded
                    return True
                return False
            elif step == "keeplinks":
                urls = []
                for host, links in job.uploaded_links.items():
                    if host != 'rapidgator-backup':
                        urls.extend(links)
                if not urls:
                    return False
                kl = self.send_to_keeplinks(urls)
                if kl:
                    job.keeplinks_url = kl
                    return True
                return False
            elif step == "template":
                return True
        except Exception as e:
            logging.error("auto_process_job step %s failed: %s", step, e)
            return False
        return False
