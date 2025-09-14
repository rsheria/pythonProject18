import logging
import os
from typing import Optional

from dotenv import load_dotenv

# Import crash protection utilities
from utils.crash_protection import (
    safe_execute, resource_protection, ErrorSeverity, crash_logger
)

try:
    from .uploady_client import UploadyClient
except Exception:  # pragma: no cover - dependency missing
    UploadyClient = None

load_dotenv()


class UploadyUploadHandler:
    @safe_execute(max_retries=1, default_return=None, severity=ErrorSeverity.MEDIUM)
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Uploady upload handler with bulletproof configuration."""
        try:
            self.api_key = (api_key or os.getenv("UPLOADY_API_KEY", "")).strip()
            self.client = UploadyClient() if UploadyClient else None

            if not self.api_key:
                crash_logger.warning("Uploady API key is missing")
            if not self.client:
                crash_logger.warning("UploadyClient is not available")
        except Exception as e:
            crash_logger.error(f"Failed to initialize UploadyUploadHandler: {e}")
            self.api_key = None
            self.client = None

    @safe_execute(max_retries=3, default_return=None, severity=ErrorSeverity.CRITICAL)
    def upload_file(self, file_path: str, progress_callback=None) -> Optional[str]:
        """Upload file to Uploady with bulletproof error handling."""
        with resource_protection("Uploady_Upload", timeout_seconds=300.0):
            # Step 1: Validate prerequisites
            if not self.api_key or not self.client:
                crash_logger.error("UploadyUploadHandler: API key or client missing",
                                 context={'has_api_key': bool(self.api_key), 'has_client': bool(self.client)})
                return None

            if not os.path.exists(file_path):
                crash_logger.error("File does not exist for Uploady upload",
                                 context={'file_path': file_path})
                return None

            try:
                file_size = os.path.getsize(file_path)
                if file_size == 0:
                    crash_logger.error("File is empty for Uploady upload",
                                     context={'file_path': file_path})
                    return None
            except OSError as e:
                crash_logger.error(f"Cannot access file for Uploady upload: {e}",
                                 context={'file_path': file_path})
                return None

            # Step 2: Get upload server with error protection
            try:
                upload_url = self.client.get_upload_server(self.api_key)
                if not upload_url or not isinstance(upload_url, str):
                    crash_logger.error("Invalid or missing upload server from Uploady",
                                     context={'upload_url': str(upload_url)[:100]})
                    return None

                if not upload_url.startswith('http'):
                    crash_logger.error("Invalid Uploady upload URL format",
                                     context={'upload_url': upload_url})
                    return None
            except Exception as e:
                crash_logger.error(f"Failed to get Uploady upload server: {e}",
                                 context={'file_path': file_path})
                return None

            # Step 3: Get session ID with error protection
            try:
                sess_id = self.client.get_sess_id(self.client.session)
                if not sess_id:
                    crash_logger.error("Failed to get Uploady session ID")
                    return None
            except Exception as e:
                crash_logger.error(f"Failed to get Uploady session ID: {e}")
                return None

            # Step 4: Upload file with bulletproof handling
            try:
                # Create safe progress callback wrapper
                def safe_progress_callback(current, total):
                    try:
                        if progress_callback:
                            progress_callback(current, total)
                    except Exception as e:
                        crash_logger.warning(f"Progress callback failed for Uploady: {e}")

                resp = self.client.upload_file(
                    upload_url, sess_id, file_path, safe_progress_callback
                )
            except Exception as e:
                crash_logger.error(f"Failed to upload file to Uploady: {e}",
                                 context={'file_path': file_path, 'upload_url': upload_url})
                return None
            # Step 5: Process response with comprehensive validation
            if resp is None:
                crash_logger.error("Null response from Uploady upload")
                return None

            # Normalize response to dict format
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            if not isinstance(resp, dict):
                resp = {"result": resp}

            # Step 6: Extract file code with multiple fallback attempts
            file_code = None

            # First attempt: Direct file code extraction
            file_code = (
                resp.get("file_code")
                or resp.get("filecode")
                or resp.get("code")
            )

            # Second attempt: Extract from result field
            if not file_code:
                result = resp.get("result")
                if isinstance(result, list):
                    result = result[0] if result else {}
                if isinstance(result, dict):
                    file_code = (
                        result.get("file_code")
                        or result.get("filecode")
                        or result.get("code")
                    )
                elif isinstance(result, str):
                    file_code = result

            # Handle list format file codes
            if isinstance(file_code, list):
                file_code = file_code[0] if file_code else None

            # Validate final file code
            if not file_code or not isinstance(file_code, str) or not file_code.strip():
                crash_logger.error("Missing or invalid file code from Uploady",
                                 context={'response': str(resp)[:300]})
                return None

            file_code = file_code.strip()

            # Step 7: Construct and validate final URL
            try:
                download_url = f"https://uploady.io/{file_code}"
                logging.info(f"File uploaded successfully to Uploady: {download_url}")

                # Final progress update with error protection
                try:
                    if progress_callback:
                        progress_callback(file_size, file_size)
                except Exception as e:
                    crash_logger.warning(f"Final progress callback failed for Uploady: {e}")

                return download_url
            except Exception as e:
                crash_logger.error(f"Error constructing Uploady download URL: {e}",
                                 context={'file_code': file_code})
                return None
