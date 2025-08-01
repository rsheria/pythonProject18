from .base_uploader import BaseUploader
from ddownload_upload_handler import DdownloadUploadHandler

class DdownloadUploader(BaseUploader):
    def __init__(self, api_key: str):
        self.handler = DdownloadUploadHandler(api_key)

    def upload(self, file_path: str, **kwargs) -> dict:
        return self.handler.upload_file(file_path, **kwargs)
