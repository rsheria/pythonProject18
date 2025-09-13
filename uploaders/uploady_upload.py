from .base_uploader import BaseUploader
from .uploady_upload_handler import UploadyUploadHandler

class UploadyUploader(BaseUploader):
    def __init__(self, api_key: str | None = None):
        self.handler = UploadyUploadHandler(api_key)

    def upload(self, file_path: str, **kwargs) -> dict:
        url = self.handler.upload_file(file_path, **kwargs)
        if url:
            return {"status": "success", "url": url}
        return {"status": "error", "error": "Upload failed"}
