from config.config import DATA_DIR
# category_manager.py

import logging
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re
from urllib.parse import urljoin, urlparse
import json
import os

class CategoryManager:
    def __init__(self, forum_section_url, driver, username, user_manager=None):
        self.forum_section_url = forum_section_url.rstrip('/')
        self.categories        = {}
        self.driver            = driver
        self.username          = username
        self.user_manager      = user_manager
        
        # تحديد مسار ملف الفئات
        if self.user_manager and self.user_manager.get_current_user():
            # حفظ داخل مجلد المستخدم
            user_folder = self.user_manager.get_user_folder()
            os.makedirs(user_folder, exist_ok=True)
            # Use generic filename for regular categories or megathreads based on username suffix
            if self.username.endswith('_megathreads'):
                self.categories_file = os.path.join(user_folder, "categories_megathreads.json")
            else:
                self.categories_file = os.path.join(user_folder, "categories.json")
        else:
            # حفظ في المجلد العام (للتوافق مع النظام القديم)
            if self.username.endswith('_megathreads'):
                self.categories_file = os.path.join(DATA_DIR, "categories_megathreads.json")
            else:
                self.categories_file = os.path.join(DATA_DIR, "categories.json")
        
        # حمل الفئات من الملف (أو أنشئه إذا لم يكن موجودًا)
        self.load_categories()

    def update_user_file_paths(self):
        """Update file paths for current user when user switches."""
        if hasattr(self, 'user_manager') and self.user_manager:
            current_user = self.user_manager.get_current_user()
            if current_user:
                user_folder = self.user_manager.get_user_folder()
                os.makedirs(user_folder, exist_ok=True)
                
                # Update categories file path based on username suffix
                if self.username.endswith('_megathreads'):
                    self.categories_file = os.path.join(user_folder, "categories_megathreads.json")
                else:
                    self.categories_file = os.path.join(user_folder, "categories.json")
                
                logging.info(f"Updated CategoryManager file path for user: {current_user} -> {self.categories_file}")
            else:
                # No user logged in - use global data folder
                if self.username.endswith('_megathreads'):
                    self.categories_file = os.path.join(DATA_DIR, "categories_megathreads.json")
                else:
                    self.categories_file = os.path.join(DATA_DIR, "categories.json")
                
                logging.info(f"Updated CategoryManager file path for no user (global folder): {self.categories_file}")

    def extract_categories(self):
        try:
            logging.info(f"Extracting categories from {self.forum_section_url}")
            self.driver.get(self.forum_section_url)
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Find all <a> tags with href starting with "forumdisplay.php?f="
            category_elements = soup.select('a[href^="forumdisplay.php?f="]')

            # Process found category elements
            for element in category_elements:
                category_name = element.text.strip()
                relative_url = element.get('href', '')

                # Extract forum ID and name from the relative URL
                match = re.search(r'f=(\d+)(?:-([^&]+))?', relative_url)
                if match:
                    forum_id = match.group(1)
                    forum_name = match.group(2) or category_name

                    # Use the custom encode_url_component method
                    encoded_forum_name = self.encode_url_component(forum_name)

                    parsed_url = urlparse(self.forum_section_url)
                    full_url = f"{parsed_url.scheme}://{parsed_url.netloc}/forum/{forum_id}-{encoded_forum_name}/"
                else:
                    # If we can't extract the ID, use the original relative URL
                    full_url = urljoin(self.forum_section_url, relative_url)

                # Avoid duplication
                if category_name not in self.categories:
                    self.categories[category_name] = full_url
                    logging.info(f"Extracted category: {category_name} -> {full_url}")

            if not self.categories:
                logging.warning("No categories found after all methods.")

            self.save_categories()
            return True
        except Exception as e:
            logging.error(f"Error extracting categories: {e}", exc_info=True)
            return False

    def get_category_url(self, category_name):
        url = self.categories.get(category_name, '')
        return url

    def add_category(self, category_name, category_url):
        if category_name not in self.categories:
            self.categories[category_name] = category_url
            logging.info(f"Added category: {category_name} -> {category_url}")
            self.save_categories()
            return True
        logging.warning(f"Category '{category_name}' already exists.")
        return False

    def remove_category(self, category_name):
        if category_name in self.categories:
            del self.categories[category_name]
            logging.info(f"Removed category: {category_name}")
            self.save_categories()
            return True
        logging.warning(f"Category '{category_name}' does not exist.")
        return False

    def load_categories(self):
        if os.path.exists(self.categories_file):
            try:
                with open(self.categories_file, 'r', encoding='utf-8') as f:
                    self.categories = json.load(f)
                logging.info("Loaded categories from file.")
            except Exception as e:
                logging.error(f"Error loading categories from file: {e}", exc_info=True)
        else:
            current_user = self.user_manager.get_current_user() if self.user_manager else "global"
            logging.info(f"No categories file found for user {current_user} (type: {self.username}).")

    def save_categories(self):
        try:
            with open(self.categories_file, 'w', encoding='utf-8') as f:
                json.dump(self.categories, f, ensure_ascii=False, indent=4)
            logging.info("Saved categories to file.")
        except Exception as e:
            logging.error(f"Error saving categories to file: {e}", exc_info=True)

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
