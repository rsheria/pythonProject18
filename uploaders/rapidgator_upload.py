from .base_uploader import BaseUploader
from rapidgator_upload_handler import RapidgatorUploadHandler

class RapidgatorUploader(BaseUploader):
    def __init__(self, api_key: str):
        self.handler = RapidgatorUploadHandler(api_key)

    def upload(self, file_path: str, **kwargs) -> dict:
        return self.handler.upload_file(file_path, **kwargs)
