import os
import re
import logging
import time
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from downloaders.base_downloader import BaseDownloader

# Load environment variables
load_dotenv()


class KatfileDownloader(BaseDownloader):
    """
    Katfile downloader implementation with premium support
    """

    LOGIN_URL = "https://katfile.com/login.html"
    DIRECT_API_URL = "https://katfile.com/api/file/direct_link"

    def __init__(self, bot):
        super().__init__(bot)
        self.username = os.getenv("KATFILE_USERNAME", "").strip()
        self.password = os.getenv("KATFILE_PASSWORD", "").strip()
        self.api_key = os.getenv("KATFILE_API_KEY", "").strip()
        self.session = requests.Session()
        self.is_logged_in = False
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1'
        })

    def _login(self):
        """
        Login to Katfile account and save session cookies
        """
        try:
            logging.info("Attempting to log in to Katfile...")

            # First, get the login page to get any required tokens
            response = self.session.get(
                self.LOGIN_URL,
                timeout=15
            )
            response.raise_for_status()

            # Prepare login data
            login_data = {
                "login": self.username,
                "password": self.password,
                "op": "login",
                "redirect": ""
            }

            # Try to find and include any hidden form fields
            soup = BeautifulSoup(response.text, 'html.parser')
            form = soup.find('form', {'id': 'loginform'}) or soup.find('form')
            if form:
                for inp in form.find_all('input', {'type': 'hidden'}):
                    if inp.get('name') and inp.get('name') not in login_data:
                        login_data[inp['name']] = inp.get('value', '')

            # Submit login form
            login_url = urljoin(self.LOGIN_URL, form['action']) if form and form.get('action') else self.LOGIN_URL
            response = self.session.post(
                login_url,
                data=login_data,
                allow_redirects=True,
                timeout=15
            )
            response.raise_for_status()

            # Check if login was successful
            if any(cookie.name == 'xfss' for cookie in self.session.cookies) or \
                    "logout" in response.text.lower() or "my account" in response.text.lower():
                self.is_logged_in = True
                logging.info("Successfully logged in to Katfile")
                return True
            else:
                logging.error("Login failed - invalid credentials or login form changed")
                return False

        except Exception as e:
            logging.error(f"Error during Katfile login: {str(e)}", exc_info=True)
            return False

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
        Download a file from Katfile
        """
        logging.info(f"Starting Katfile download for URL: {url}")
        
        try:
            # 1) Prepare download directory
            dest_dir = download_dir or os.path.join(
                self.bot.download_dir,
                self.sanitize_filename(category_name),
                str(thread_id)
            )
            os.makedirs(dest_dir, exist_ok=True)
            logging.info(f"Download directory prepared: {dest_dir}")

            # 2) Login if credentials are available
            if self.username and self.password and not self.is_logged_in:
                logging.info("Attempting to login with provided credentials")
                if not self._login():
                    logging.error("Failed to login to Katfile")
                    return False
            elif not self.username or not self.password:
                logging.info("No credentials provided, proceeding without login")

            # 3) Get direct download link
            logging.info("Getting direct download link...")
            download_url, filename, response_stream = self._get_direct_download_link(url)
            if not download_url or not filename:
                logging.error("Failed to get direct download link")
                return False
            
            logging.info(f"Got download URL: {download_url}, filename: {filename}")

            # 4) Download the file
            logging.info("Starting file download...")
            result = self._download_file(
                download_url=download_url,
                filename=filename,
                response_stream=response_stream,
                dest_dir=dest_dir,
                progress_callback=progress_callback
            )
            
            if result:
                logging.info(f"Katfile download completed successfully for {filename}")
            else:
                logging.error(f"Katfile download failed for {filename}")
                
            return result
            
        except Exception as e:
            logging.error(f"Error in Katfile download: {str(e)}", exc_info=True)
            return False

    def _get_direct_download_link(self, file_url):
        """
        Get direct download link from Katfile
        """
        try:
            logging.info(f"Getting direct download link for: {file_url}")

            # First try to get the direct link from the file page
            logging.debug(f"Making request to {file_url}...")
            response = self.session.get(file_url, allow_redirects=True, stream=True, timeout=30)
            logging.debug(f"Response status: {response.status_code}")
            response.raise_for_status()

            # Check if it's a direct download
            if 'content-disposition' in response.headers:
                filename = re.findall(r'filename\*?=(?:UTF-8\'[a-zA-Z0-9\-]*\')?"?([^"\n]+)"?',
                                      response.headers['content-disposition'])
                if filename:
                    filename = filename[0]
                else:
                    filename = os.path.basename(file_url.split('?')[0])
                logging.info(f"Direct download detected. Filename: {filename}")
                return response.url, filename, response

            # If not direct download, try to find download button
            logging.debug("Parsing HTML for download buttons...")
            soup = BeautifulSoup(response.text, 'html.parser')

            # Try premium download button first, but avoid payment links
            dl_btn = soup.find('a', {'id': 'downloadbtn'})
            
            # If no direct download button, look for other download links but skip payment links
            if not dl_btn:
                download_links = soup.find_all('a', href=True)
                for link in download_links:
                    href = link.get('href', '')
                    text = link.get_text().strip().lower()
                    
                    # Skip payment and upgrade links
                    if any(x in href for x in ['payment', 'upgrade', 'premium', 'buy']):
                        continue
                    if any(x in text for x in ['payment', 'upgrade', 'premium', 'buy']):
                        continue
                        
                    # Look for actual download links
                    if ('download' in text and len(text) < 50) or 'downloadbtn' in link.get('class', []):
                        dl_btn = link
                        break

            if dl_btn and dl_btn.get('href'):
                href = dl_btn['href']
                # Skip if it's a payment link
                if any(x in href for x in ['payment', 'upgrade', 'premium', 'buy']):
                    logging.warning(f"Skipping payment link: {href}")
                    dl_btn = None
                else:
                    logging.info(f"Found download button with href: {href}")
                    dl_url = urljoin(file_url, href)
                    filename = os.path.basename(dl_url.split('?')[0]) or f"katfile_{int(time.time())}.bin"
                    logging.info(f"Premium download URL: {dl_url}, filename: {filename}")
                    return dl_url, filename, None
            
            if not dl_btn:
                logging.debug("No premium download button found")

            # If API key is available, try direct API
            if self.api_key:
                logging.debug("API key available, trying direct API...")
                file_code_match = re.search(r'katfile\.com/([^/]+)', file_url)
                if file_code_match:
                    file_code = file_code_match.group(1)
                    logging.info(f"Trying direct API with file code: {file_code}")

                    api_params = {"key": self.api_key, "file_code": file_code}
                    api_response = self.session.get(self.DIRECT_API_URL, params=api_params, timeout=30)
                    api_response.raise_for_status()
                    api_data = api_response.json()

                    if api_data.get("status") == 200 and api_data.get("msg") == "OK":
                        result = api_data.get("result", {})
                        if result and "url" in result:
                            dl_url = result['url']
                            filename = os.path.basename(dl_url.split('?')[0]) or f"katfile_{file_code}.bin"
                            logging.info(f"Got direct link from API: {dl_url}")
                            return dl_url, filename, None
                        else:
                            logging.warning("API returned success but no download URL")
                    else:
                        logging.warning(f"API returned error: {api_data}")
                else:
                    logging.debug("Could not extract file code from URL")
            else:
                logging.debug("No API key available")

            # Fallback to free download if premium fails
            logging.info("Falling back to free download flow...")
            return self._get_free_download_link(file_url, response.text)

        except Exception as e:
            logging.error(f"Error getting direct download link: {str(e)}", exc_info=True)
            return None, None, None

    def _get_free_download_link(self, page_url, page_content=None):
        """
        Handle free download flow for Katfile
        """
        logging.info(f"Starting free download flow for: {page_url}")
        try:
            if not page_content:
                logging.debug("Fetching page content for free download...")
                response = self.session.get(
                    page_url,
                    headers={"Referer": page_url},
                    timeout=30
                )
                response.raise_for_status()
                page_content = response.text
                logging.debug(f"Got page content, length: {len(page_content)}")

            soup = BeautifulSoup(page_content, 'html.parser')
            logging.debug("Parsing HTML for free download form...")

            # Find the free download form
            form = (soup.find('form', {'id': 'dl_form'}) or
                    soup.find('form', action=re.compile(r'/download/')) or
                    soup.find('form', method='post'))

            if not form:
                logging.error("Download form not found")
                # Debug: let's see what forms are available
                all_forms = soup.find_all('form')
                logging.debug(f"Found {len(all_forms)} forms on page")
                for i, f in enumerate(all_forms):
                    logging.debug(f"Form {i}: {f.get('id', 'no-id')}, action: {f.get('action', 'no-action')}, method: {f.get('method', 'get')}")
                return None, None, None

            # Prepare form data
            form_action = form.get('action', '')
            form_url = urljoin(page_url, form_action) if form_action else page_url

            form_data = {}
            for inp in form.find_all(['input', 'button']):
                if inp.get('name') and inp.get('type') != 'submit':
                    form_data[inp['name']] = inp.get('value', '')

            # Add default values if missing
            form_data.setdefault('op', 'download1')
            form_data.setdefault('method_free', 'Free Download')

            # Submit the form
            response = self.session.post(
                form_url,
                data=form_data,
                headers={
                    'Referer': page_url,
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': 'https://katfile.com',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
                },
                allow_redirects=True,
                timeout=30
            )
            response.raise_for_status()

            # Extract download link from the response
            soup = BeautifulSoup(response.text, 'html.parser')
            download_btn = (soup.find('a', {'id': 'downloadbtn'}) or
                            soup.find('a', string=re.compile(r'(Download|Download Now|Free Download)', re.I)) or
                            soup.find('a', href=re.compile(r'download/')))

            if download_btn and download_btn.get('href'):
                href = download_btn['href']
                # Skip payment links
                if any(x in href for x in ['payment', 'upgrade', 'premium', 'buy']):
                    logging.warning(f"Skipping payment link in free download: {href}")
                else:
                    dl_url = urljoin(page_url, href)
                    filename = os.path.basename(dl_url.split('?')[0]) or f"katfile_{int(time.time())}.bin"
                    logging.info(f"Found free download link: {dl_url}")
                    return dl_url, filename, None

            # If no direct download button, try to find direct links in the page
            direct_links = re.findall(r'https?://[^\s"\']+\.(?:rar|zip|7z|tar\.gz|pdf|epub|mobi|mp3|mp4|avi|mkv)',
                                      response.text)
            if direct_links:
                dl_url = direct_links[0]
                filename = os.path.basename(dl_url.split('?')[0])
                return dl_url, filename, None

            logging.error("Could not find download link in the page")
            return None, None, None

        except Exception as e:
            logging.error(f"Error in free download flow: {str(e)}", exc_info=True)
            return None, None, None

    def _download_file(self, download_url, filename, response_stream, dest_dir, progress_callback):
        """
        Download a file from the given URL or existing response stream
        """
        try:
            if response_stream:
                return self._download_from_stream(response_stream, filename, dest_dir, progress_callback)
            else:
                return self._download_from_url(download_url, filename, dest_dir, progress_callback)
        except Exception as e:
            logging.error(f"Error downloading file: {str(e)}", exc_info=True)
            return False

    def _download_from_stream(self, response_stream, filename, dest_dir, progress_callback):
        """
        Download from an existing response stream
        """
        try:
            safe_filename = self.sanitize_filename(filename)
            dest_path = os.path.join(dest_dir, safe_filename)
            temp_path = dest_path + ".downloading"
            
            total_size = int(response_stream.headers.get('content-length', 0))
            downloaded = 0
            
            logging.info(f"Downloading {filename} ({total_size} bytes) to {dest_path}")
            
            # Enhanced progress tracking
            start_time = time.time()
            last_update_time = start_time
            last_downloaded = 0
            
            display_name = self.format_progress_display_name(filename, "Katfile")
            
            with open(temp_path, 'wb') as f:
                for chunk in response_stream.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Enhanced progress callback with timing and display info
                        if progress_callback and total_size > 0:
                            current_time = time.time()
                            elapsed = current_time - start_time
                            
                            # Use adaptive reporting intervals
                            report_interval = self.calculate_adaptive_interval(elapsed, current_time - last_update_time)
                            
                            # Only report if significant progress or enough time passed
                            if (current_time - last_update_time) >= report_interval or downloaded == total_size:
                                progress_percent = (downloaded / total_size) * 100
                                # Enhanced progress callback with display name
                                progress_callback(
                                    downloaded, 
                                    total_size, 
                                    display_name,  # Enhanced display name
                                    progress_percent  # Add percentage for consistency
                                )
                                last_update_time = current_time
            
            # Rename temp file to final name
            if os.path.exists(temp_path):
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(temp_path, dest_path)
                logging.info(f"Successfully downloaded {filename}")
                return True
            else:
                logging.error(f"Temporary file not found: {temp_path}")
                return False
                
        except Exception as e:
            logging.error(f"Error downloading from stream: {str(e)}", exc_info=True)
            # Clean up temp file if it exists
            temp_path = os.path.join(dest_dir, self.sanitize_filename(filename)) + ".downloading"
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return False

    def _download_from_url(self, download_url, filename, dest_dir, progress_callback):
        """
        Download from a URL
        """
        try:
            safe_filename = self.sanitize_filename(filename)
            dest_path = os.path.join(dest_dir, safe_filename)
            temp_path = dest_path + ".downloading"
            
            logging.info(f"Starting download from URL: {download_url}")
            
            response = self.session.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            logging.info(f"Downloading {filename} ({total_size} bytes) to {dest_path}")
            
            # Enhanced progress tracking for URL downloads
            start_time = time.time()
            last_update_time = start_time
            
            display_name = self.format_progress_display_name(filename, "Katfile")
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Enhanced progress callback with timing and display info
                        if progress_callback and total_size > 0:
                            current_time = time.time()
                            elapsed = current_time - start_time
                            
                            # Use adaptive reporting intervals
                            report_interval = self.calculate_adaptive_interval(elapsed, current_time - last_update_time)
                            
                            # Only report if significant progress or enough time passed
                            if (current_time - last_update_time) >= report_interval or downloaded == total_size:
                                progress_percent = (downloaded / total_size) * 100
                                # Enhanced progress callback with display name
                                progress_callback(
                                    downloaded, 
                                    total_size, 
                                    display_name,  # Enhanced display name
                                    progress_percent  # Add percentage for consistency
                                )
                                last_update_time = current_time
            
            # Rename temp file to final name
            if os.path.exists(temp_path):
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(temp_path, dest_path)
                logging.info(f"Successfully downloaded {filename}")
                return True
            else:
                logging.error(f"Temporary file not found: {temp_path}")
                return False
                
        except Exception as e:
            logging.error(f"Error downloading from URL: {str(e)}", exc_info=True)
            # Clean up temp file if it exists
            temp_path = os.path.join(dest_dir, self.sanitize_filename(filename)) + ".downloading"
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return False
