from .base_uploader import BaseUploader
from mega_upload_handler import MegaUploadHandler

class MegaUploader(BaseUploader):
    def __init__(self, email: str, password: str):
        self.handler = MegaUploadHandler(email, password)

    def upload(self, file_path: str, **kwargs) -> dict:
        return self.handler.upload_file(file_path, **kwargs)
