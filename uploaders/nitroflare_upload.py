from .base_uploader import BaseUploader
from nitroflare_upload_handler import NitroflareUploadHandler

class NitroflareUploader(BaseUploader):
    def __init__(self, api_key: str):
        self.handler = NitroflareUploadHandler(api_key)

    def upload(self, file_path: str, **kwargs) -> dict:
        return self.handler.upload_file(file_path, **kwargs)
