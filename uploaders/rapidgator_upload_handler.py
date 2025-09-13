"""
Rapidgator Upload Handler
• Automatically generates token (via /user/login) if missing or expired
• Validates token (/user/info)
• Handles file uploads following Rapidgator API flow (/file/upload → POST → /file/upload_info)
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any

from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor

# Load environment variables from .env file
load_dotenv()

API_ROOT = "https://rapidgator.net/api/v2"


# ----------------------------------------------------------------------
# Helper: جلب توكن جديد عند الحاجة
# ----------------------------------------------------------------------
def fetch_rg_token(username: str, password: str, code: str | None = None) -> str:
    """
    Logs-in via POST and returns a new Access-Token.
    Returns "" if login fails.
    """
    if not username or not password:
        logging.error("Username/password missing – cannot fetch token.")
        return ""

    payload: Dict[str, Any] = {
        "login":    username.strip(),
        "password": password.strip()
    }
    if code:
        payload["code"] = str(code).strip()

    try:
        r = requests.post(
            f"{API_ROOT}/user/login",
            data=payload,                       # ← POST not GET
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        data = r.json()
        logging.debug(f"RG login resp: {data}")

        if r.status_code == 200 and data.get("status") == 200:
            token = data["response"]["token"]
            logging.info("✅ New Rapidgator token obtained.")
            return token

        logging.error(f"RG Login error: {data.get('details')}")
    except Exception as exc:
        logging.error(f"RG login request failed: {exc}", exc_info=True)
    return ""


# ----------------------------------------------------------------------
#  الرئيسية
# ----------------------------------------------------------------------
class RapidgatorUploadHandler:
    def __init__(
        self,
        filepath: Path | str,
        username: str = "",
        password: str = "",
        token: str = "",
        twofa_code: str | None = None,
    ):
        """
        Initialize the Rapidgator upload handler.
        
        Args:
            filepath: Path to the file to upload
            username: Rapidgator username/email
            password: Rapidgator password
            token: Existing token (if available)
            twofa_code: 2FA code if enabled
            
        Raises:
            Exception: If unable to obtain a valid token
        """
        self.filepath = Path(filepath)
        # Get credentials from parameters or environment variables
        self.username = (username or os.getenv("RAPIDGATOR_LOGIN", "")).strip()
        self.password = (password or os.getenv("RAPIDGATOR_PASSWORD", "")).strip()
        self.twofa_code = (str(twofa_code) if twofa_code else os.getenv("RAPIDGATOR_2FA", "")).strip() or None
        self.token = token.strip() if token else ""
        self.base_url = API_ROOT
        self.session = requests.Session()
        self.last_init_response: Optional[dict] = None

        # Configure session with retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10
        )
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set default headers
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json"
        })

        # Log initialization
        logging.info("Initializing RapidgatorUploadHandler")
        logging.debug(f"Username: {self.username}")
        logging.debug(f"Using token: {'Yes' if self.token else 'No'}")
        logging.debug(f"2FA enabled: {'Yes' if self.twofa_code else 'No'}")

        # Validate or obtain token
        if self.token:
            logging.info("Validating existing token...")
            if not self.is_token_valid():
                logging.warning("Existing token is invalid, attempting to get a new one...")
                self.token = fetch_rg_token(self.username, self.password, self.twofa_code)
        else:
            logging.info("No token provided, attempting to get a new one...")
            self.token = fetch_rg_token(self.username, self.password, self.twofa_code)

        # Final validation
        if not self.token or not self.is_token_valid():
            error_msg = "❌ Unable to obtain a valid Rapidgator token. "
            error_msg += "Please check your username, password, and 2FA code (if enabled)."
            logging.error(error_msg)
            raise Exception(error_msg)
            
        logging.info("✅ Successfully initialized RapidgatorUploadHandler with valid token")

    # ------------------------------------------------------------------
    # صلاحية التوكن
    # ------------------------------------------------------------------
    def is_token_valid(self) -> bool:
        """
        Check if the current token is valid by calling the /user/info endpoint.
        
        Returns:
            bool: True if the token is valid, False otherwise
        """
        if not self.token:
            logging.debug("No token available for validation")
            return False
            
        try:
            # Log the validation attempt
            logging.debug(f"Validating token: {self.token[:8]}...")
            
            # Make the API request
            response = self.session.get(
                f"{self.base_url}/user/info",
                params={"token": self.token},
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            
            # Log response details for debugging
            logging.debug(f"Token validation response status: {response.status_code}")
            
            try:
                data = response.json()
                logging.debug(f"Token validation response: {data}")
            except ValueError as e:
                logging.error(f"Failed to parse token validation response: {e}")
                logging.error(f"Raw response: {response.text}")
                return False
            
            # Check if token is valid
            if response.status_code == 200 and data.get("status") == 200:
                user_info = data.get("response", {})
                if user_info:
                    logging.info(f"✅ Valid token for user: {user_info.get('email', 'Unknown')}")
                    logging.debug(f"Account status: {user_info.get('status')}")
                    logging.debug(f"Premium until: {user_info.get('premium_until')}")
                    return True
                
            # Token is invalid or expired
            error_msg = data.get("details", data.get("error", "Unknown error"))
            logging.warning(f"❌ Token validation failed: {error_msg}")
            
            # If we have credentials, try to get a new token
            if self.username and self.password:
                logging.info("Attempting to refresh token with credentials...")
                new_token = fetch_rg_token(self.username, self.password, self.twofa_code)
                if new_token:
                    self.token = new_token
                    return True
                
            return False
            
        except requests.exceptions.RequestException as e:
            logging.error(f"⚠️ Network error during token validation: {str(e)}")
            # Don't invalidate token on network errors - it might be a temporary issue
            return True
            
        except Exception as e:
            logging.error(f"❌ Unexpected error during token validation: {str(e)}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # رفع الملف الرئيسى
    # ------------------------------------------------------------------
    def upload(self, folder_id: str | None = None, progress_cb=None) -> Optional[str]:
        """
        يرفع الملف ويُعيد رابط التنزيل النهائى أو None عند الفشل.

        Args:
            folder_id   : رقم المجلد على Rapidgator (اختياري).
            progress_cb : دالة رد نداء لتحديث شريط التقدم (bytes_uploaded, total_size).

        Returns:
            str | None
        """
        max_retries = 3
        retry_delay = 5  # ثوانى

        for attempt in range(1, max_retries + 1):
            try:
                if not self.filepath.exists():
                    raise FileNotFoundError(self.filepath)

                # 1) تأكّد من صلاحية التوكن
                if not self.is_token_valid():
                    raise Exception("Failed to obtain valid Rapidgator token")

                # 2) احسب الـ hash والحجم
                file_hash = self._hash_md5(self.filepath)
                file_size = self.filepath.stat().st_size

                # 3) تهيئة الرفع
                init_info = self._initialize(file_hash, file_size, folder_id)
                if not init_info:
                    raise Exception("Upload initialization failed")

                upload_url = init_info.get("url")
                upload_id = init_info.get("upload_id")
                state = init_info.get("state", 0)

                # ─── حالة الملف على الخادم ──────────────────────────────
                # 0 = Uploading (نحتاج رفع)
                # 1 = Processing (مرفوع ويُعالج)
                # 2 = Done       (لدينا الرابط فورًا)
                # 3 = Fail
                if state == 2:
                    existing = init_info.get("file", {})
                    return existing.get("url")

                if state == 3:
                    raise Exception(f"Server returned FAIL state: "
                                    f"{init_info.get('state_label', 'Fail')}")

                if state == 1:
                    logging.info("File already uploaded, waiting for processing …")
                    final_url = self._poll_for_url(upload_id)
                    if final_url:
                        logging.info(f"Upload completed successfully: {final_url}")
                        return final_url
                    raise Exception("Processing timed‑out")

                # state == 0 → نرفع المحتوى ثم ننتظر الرابط
                if not upload_url or not upload_id:
                    raise Exception("Invalid upload URL or ID from server")

                if not self._upload_content(upload_url, progress_cb):
                    raise Exception("File upload failed")

                final_url = self._poll_for_url(upload_id)
                if final_url:
                    logging.info(f"Upload completed successfully: {final_url}")
                    return final_url

                raise Exception("Failed to obtain final URL after upload")

            # ── أخطاء الشبكة: أعد المحاولة ───────────────────────────
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    wait = retry_delay * attempt
                    logging.warning(f"Attempt {attempt} network error: {e}. Retrying in {wait}s …")
                    time.sleep(wait)
                    continue
                logging.error(f"Upload failed after {max_retries} attempts: {e}", exc_info=True)
                return None

            # ── أخطاء أخرى: أعد المحاولة حتى max_retries ─────────────
            except Exception as e:
                logging.error(f"Upload failed: {e}", exc_info=True)
                if attempt == max_retries:
                    return None
                time.sleep(retry_delay)

        return None

    # ------------------------------------------------------------------
    #  داخليات
    # ------------------------------------------------------------------
    def _initialize(self, file_hash: str, size: int, folder_id: str | None) -> Optional[Dict]:
        params: Dict[str, Any] = {
            "token": self.token,
            "name": self.filepath.name,
            "hash": file_hash,
            "size": size,
        }
        if folder_id:
            params["folder_id"] = folder_id

        r = self.session.get(f"{self.base_url}/file/upload", params=params, timeout=30)
        data = r.json()
        self.last_init_response = data

        if r.status_code != 200 or data.get("status") != 200:
            logging.error(f"RG init error: {data.get('details')}")
            return None
        return data["response"]["upload"]

    def _upload_content(self, url: str, progress_cb) -> bool:
        with open(self.filepath, "rb") as f:
            fields = {
                "file": (self.filepath.name, f, "application/octet-stream")
            }
            enc = MultipartEncoder(fields=fields)
            monitor = (
                MultipartEncoderMonitor(enc, lambda m: progress_cb(m.bytes_read, enc.len))
                if progress_cb
                else enc
            )
            headers = {
                "Content-Type": monitor.content_type,
                "User-Agent": "Mozilla/5.0",
            }
            r = requests.post(url, data=monitor, headers=headers, timeout=300)
            if r.status_code != 200:
                logging.error(f"RG upload HTTP error: {r.status_code}")
                return False
            try:
                data = r.json()
                return data.get("status") == 200
            except json.JSONDecodeError:
                return True  # ردّ غير JSON لكن 200 OK

    def _poll_for_url(self, upload_id: str,
                      max_secs: int = 180, interval: int = 5) -> Optional[str]:
        """
        يستعلم عن حالة الرفع حتى نحصل على الرابط أو تفشل العملية.

        Args:
            upload_id : رقم جلسة الرفع
            max_secs  : أقصى زمن انتظار بالثوانى (افتراضى 3 دقائق)
            interval  : فترة الانتظار بين الاستعلامات

        Returns:
            رابط التنزيل النهائى أو None عند الفشل.
        """
        waited = 0
        while waited < max_secs:
            try:
                r = self.session.get(
                    f"{self.base_url}/file/upload_info",
                    params={"token": self.token, "upload_id": upload_id},
                    timeout=15,
                )
                if r.status_code != 200:
                    logging.debug(f"poll http={r.status_code}; retry …")
                    time.sleep(interval)
                    waited += interval
                    continue

                data = r.json()
                if data.get("status") != 200:
                    logging.debug(f"poll status={data.get('status')}; retry …")
                    time.sleep(interval)
                    waited += interval
                    continue

                # المسار الصحيح للـ state
                upload_info = (
                        data.get("response", {}).get("upload")
                        or data.get("upload", {})
                )
                state = upload_info.get("state")
                state_lbl = upload_info.get("state_label", state)

                if state in (0, 1):  # Uploading / Processing
                    logging.debug(f"RG {state_lbl} …")
                elif state == 2:  # Done  🎉
                    return upload_info["file"]["url"]
                elif state == 3:  # Fail
                    logging.error(f"RG upload failed: {state_lbl}")
                    return None
                else:  # غير معروف – استمر
                    logging.debug(f"Unknown state={state}; retry …")

            except Exception as exc:
                logging.error(f"poll error: {exc}")

            time.sleep(interval)
            waited += interval

        logging.error("RG polling timed‑out.")
        return None

    @staticmethod
    def _hash_md5(path: Path) -> str:
        md5 = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5.update(chunk)
        return md5.hexdigest()

    # تنظيف الجلسة
    def __del__(self):
        try:
            self.session.close()
        except Exception:
            pass
