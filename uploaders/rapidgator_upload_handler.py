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

# Import crash protection utilities
from utils.crash_protection import (
    safe_execute, resource_protection, SafeProcessManager, SafePathManager,
    ErrorSeverity, safe_process_manager, monitor_memory_usage, CircuitBreaker,
    crash_logger
)

# Load environment variables from .env file
load_dotenv()

API_ROOT = "https://rapidgator.net/api/v2"


# ----------------------------------------------------------------------
# Helper: جلب توكن جديد عند الحاجة
# ----------------------------------------------------------------------
@safe_execute(
    max_retries=3,
    retry_delay=2.0,
    expected_exceptions=(requests.RequestException, ValueError, KeyError, TimeoutError),
    severity=ErrorSeverity.CRITICAL,
    default_return="",
    log_success=True
)
def fetch_rg_token(username: str, password: str, code: str | None = None) -> str:
    """
    BULLETPROOF Rapidgator login with crash protection.
    Returns token or empty string on failure.
    """
    if not username or not password:
        crash_logger.logger.error("Username/password missing – cannot fetch token.")
        return ""

    with resource_protection("Rapidgator_Login", timeout_seconds=30.0):
        payload: Dict[str, Any] = {
            "login": username.strip(),
            "password": password.strip()
        }
        if code:
            payload["code"] = str(code).strip()

        # Create session with bulletproof configuration
        session = requests.Session()

        # Add retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        try:
            # Monitor memory usage
            monitor_memory_usage(threshold_mb=100.0)

            r = session.post(
                f"{API_ROOT}/user/login",
                data=payload,
                timeout=(10, 30),  # (connect_timeout, read_timeout)
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Connection": "close"  # Prevent connection pooling issues
                }
            )

            # Safe response validation
            if r.status_code != 200:
                crash_logger.logger.error(f"HTTP {r.status_code}: {r.text[:500]}")
                return ""

            # Safe JSON parsing
            try:
                data = r.json()
            except ValueError as json_error:
                crash_logger.logger.error(f"Invalid JSON response: {json_error}")
                return ""

            crash_logger.logger.debug(f"RG login response: {str(data)[:200]}...")

            # Safe data extraction
            if data.get("status") == 200 and isinstance(data.get("response"), dict):
                token = data["response"].get("token", "")
                if token and len(token) > 10:  # Basic token validation
                    crash_logger.logger.info("✅ New Rapidgator token obtained successfully")
                    return token
                else:
                    crash_logger.logger.error("Invalid token format received")
            else:
                error_msg = data.get('details', 'Unknown error')
                crash_logger.logger.error(f"RG Login failed: {error_msg}")

        except requests.Timeout:
            crash_logger.logger.error("Rapidgator login timeout")
        except requests.ConnectionError:
            crash_logger.logger.error("Rapidgator connection failed")
        except requests.RequestException as req_error:
            crash_logger.logger.error(f"Rapidgator request error: {req_error}")
        except Exception as unexpected_error:
            crash_logger.logger.error(f"Unexpected error in RG login: {unexpected_error}")
        finally:
            session.close()

    return ""


# ----------------------------------------------------------------------
#  الرئيسية
# ----------------------------------------------------------------------
class RapidgatorUploadHandler:
    @safe_execute(
        max_retries=2,
        retry_delay=1.0,
        expected_exceptions=(Exception,),
        severity=ErrorSeverity.CRITICAL,
        default_return=None
    )
    def __init__(
        self,
        filepath: Path | str,
        username: str = "",
        password: str = "",
        token: str = "",
        twofa_code: str | None = None,
    ):
        """
        BULLETPROOF Rapidgator upload handler initialization.
        """
        try:
            # Safe path validation
            self.filepath = SafePathManager.validate_path(filepath)

            # Safe credential handling
            self.username = (username or os.getenv("RAPIDGATOR_LOGIN", "")).strip()
            self.password = (password or os.getenv("RAPIDGATOR_PASSWORD", "")).strip()
            self.twofa_code = (str(twofa_code) if twofa_code else os.getenv("RAPIDGATOR_2FA", "")).strip() or None
            self.token = token.strip() if token else ""
            self.base_url = API_ROOT

            # Initialize safe session
            self.session = None
            self.last_init_response: Optional[dict] = None
            self._initialize_session()

            crash_logger.logger.info("✅ RapidgatorUploadHandler initialized successfully")

        except Exception as init_error:
            crash_logger.logger.error(f"💥 RapidgatorUploadHandler init failed: {init_error}")
            # Set safe defaults
            self.filepath = Path(".")
            self.username = ""
            self.password = ""
            self.token = ""
            self.session = None
            raise

    def _initialize_session(self):
        """Initialize requests session with bulletproof configuration."""
        try:
            self.session = requests.Session()

            # Configure session with retry strategy
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST"],
                raise_on_status=False  # Don't raise exceptions on HTTP errors
            )

            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=5,  # Reduced for stability
                pool_maxsize=5
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

        except Exception as e:
            crash_logger.error(f"Failed to initialize RapidgatorUploadHandler session: {e}")
            # Initialize with basic session as fallback
            self.session = requests.Session()
            self.token = None

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
