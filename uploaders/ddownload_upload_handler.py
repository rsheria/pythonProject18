# ddownload_upload_handler.py

class DDownloadUploadHandler:
    def __init__(self, bot):
        self.bot = bot

    def upload_file(self, file_path: str, progress_callback):
        """
        يفترض أن لديك دالة upload_to_ddownload في bot.
        """
        return self.bot.upload_to_ddownload(file_path, progress_callback)
