from .base_uploader import BaseUploader
from katfile_upload_handler import KatfileUploadHandler

class KatfileUploader(BaseUploader):
    def __init__(self, api_key: str):
        self.handler = KatfileUploadHandler(api_key)

    def upload(self, file_path: str, **kwargs) -> dict:
        return self.handler.upload_file(file_path, **kwargs)
