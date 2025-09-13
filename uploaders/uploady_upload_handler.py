import logging
import os
from typing import Optional

from dotenv import load_dotenv

try:
    from .uploady_client import UploadyClient
except Exception:  # pragma: no cover - dependency missing
    UploadyClient = None

load_dotenv()


class UploadyUploadHandler:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or os.getenv("UPLOADY_API_KEY", "")).strip()
        self.client = UploadyClient() if UploadyClient else None
        if not self.api_key:
            logging.warning("Uploady API key is missing")

    def upload_file(self, file_path: str, progress_callback=None) -> Optional[str]:
        if not self.api_key or not self.client:
            logging.error("UploadyUploadHandler: API key or client missing")
            return None
        try:
            upload_url = self.client.get_upload_server(self.api_key)
            if not upload_url:
                logging.error("UploadyUploadHandler: could not fetch upload server")
                return None
            sess_id = self.client.get_sess_id(self.client.session)
            resp = self.client.upload_file(
                upload_url, sess_id, file_path, progress_callback
            )
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            if not isinstance(resp, dict):
                resp = {"result": resp}

            file_code = (
                resp.get("file_code")
                or resp.get("filecode")
                or resp.get("code")
            )
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
            if isinstance(file_code, list):
                file_code = file_code[0] if file_code else None
            if not file_code:
                logging.error(f"Uploady upload failed: {resp}")
                return None
            return f"https://uploady.io/{file_code}"
        except Exception as e:
            logging.error(f"Uploady upload error: {e}", exc_info=True)
            return None
