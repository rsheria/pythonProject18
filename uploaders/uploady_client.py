import logging
import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor

load_dotenv()

API_SERVER = "https://uploady.io/api/upload/server"
VERIFY_URL = "https://uploady.io/api/file/info"
LOGIN_URL = "https://uploady.io/login"

class UploadyClient:
    def __init__(self, session: Optional[requests.Session] = None, cookies: Optional[dict] = None):
        self.session = session or requests.Session()
        if cookies:
            self.session.cookies.update(cookies)
        self._sess_id: Optional[str] = None

    def get_upload_server(self, api_key: str) -> Optional[str]:
        try:
            r = self.session.get(API_SERVER, params={"key": api_key}, timeout=30)
            data = r.json()
            result = data.get("result")
            self._sess_id = data.get("sess_id")
            if isinstance(result, dict):
                self._sess_id = self._sess_id or result.get("sess_id")
                return result.get("url") or result.get("upload_url")
            return result
        except Exception as e:
            logging.error(f"UploadyClient.get_upload_server: {e}", exc_info=True)
            return None

    def get_sess_id(self, session: Optional[requests.Session] = None) -> str:
        if self._sess_id:
            return self._sess_id
        sess = session or self.session
        xfss = sess.cookies.get("xfss")
        if xfss:
            self._sess_id = xfss
            return xfss
        username = os.getenv("UPLOADY_USERNAME", "")
        password = os.getenv("UPLOADY_PASSWORD", "")
        if username and password:
            try:
                sess.post(LOGIN_URL, data={"op": "login", "login": username, "password": password}, timeout=30)
                xfss = sess.cookies.get("xfss", "")
                self._sess_id = xfss
                return xfss
            except Exception as e:
                logging.error(f"UploadyClient.get_sess_id login error: {e}", exc_info=True)
        return ""

    def upload_file(self, upload_url: str, sess_id: str, file_path: str, progress_callback=None) -> dict:
        fields = ["file", "file_0"]
        cookies = {"xfss": sess_id} if sess_id else None
        for field in fields:
            try:
                with Path(file_path).open("rb") as f:
                    data = {field: (Path(file_path).name, f)}
                    if sess_id:
                        data["sess_id"] = sess_id
                    enc = MultipartEncoder(data)
                    monitor = (
                        MultipartEncoderMonitor(
                            enc, lambda m: progress_callback(m.bytes_read, m.len)
                        )
                        if progress_callback
                        else enc
                    )
                    headers = {"Content-Type": monitor.content_type}
                    r = self.session.post(
                        upload_url,
                        data=monitor,
                        headers=headers,
                        cookies=cookies,
                        timeout=3600,
                    )
                try:
                    return r.json()
                except Exception:
                    return {"result": r.text}
            except Exception as e:
                logging.error(
                    f"UploadyClient.upload_file {field} error: {e}", exc_info=True
                )
        return {}

    def verify(self, api_key: str, file_code: str) -> dict:
        try:
            r = self.session.get(VERIFY_URL, params={"key": api_key, "file_code": file_code}, timeout=30)
            return r.json()
        except Exception as e:
            logging.error(f"UploadyClient.verify: {e}", exc_info=True)
            return {}
