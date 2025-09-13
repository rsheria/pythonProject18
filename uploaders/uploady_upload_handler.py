import logging
import os
from pathlib import Path
from typing import Optional

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
from dotenv import load_dotenv

load_dotenv()

API_SERVER_URL = "https://uploady.io/api/upload/server"

class UploadyUploadHandler:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or os.getenv("UPLOADY_API_KEY", "")).strip()
        self.session = requests.Session()
        if not self.api_key:
            logging.warning("Uploady API key is missing")

    def upload_file(self, file_path: str, progress_callback=None) -> Optional[str]:
        if not self.api_key:
            logging.error("UploadyUploadHandler: API key required")
            return None
        try:
            # Step 1: fetch upload server
            resp = self.session.get(API_SERVER_URL, params={"key": self.api_key}, timeout=30)
            data = resp.json()
            upload_url = data.get("result")
            if resp.status_code != 200 or not upload_url:
                logging.error(f"Uploady server fetch failed: {data}")
                return None
            path = Path(file_path)
            with path.open("rb") as f:
                encoder = MultipartEncoder({"file": (path.name, f)})
                if progress_callback:
                    monitor = MultipartEncoderMonitor(encoder, lambda m: progress_callback(m.bytes_read, m.len))
                else:
                    monitor = encoder
                headers = {"Content-Type": monitor.content_type}
                upload_resp = self.session.post(upload_url, data=monitor, headers=headers, timeout=3600)
            result = {}
            try:
                result = upload_resp.json()
            except Exception:
                logging.error("Uploady upload response not JSON", exc_info=True)
            url = result.get("result") if isinstance(result, dict) else None
            if isinstance(url, dict):
                url = url.get("url") or url.get("download_url") or url.get("link")
            elif isinstance(url, list):
                url = url[0] if url else None
            if not url:
                logging.error(f"Uploady upload failed: {result}")
                return None
            return url
        except Exception as e:
            logging.error(f"Uploady upload error: {e}", exc_info=True)
            return None
