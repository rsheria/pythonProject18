# katfile_upload_handler.py

class KatfileUploadHandler:
    def __init__(self, bot):
        self.bot = bot

    def upload_file(self, file_path: str, progress_callback):
        """
        يفترض أن لديك دالة upload_to_katfile في bot.
        """
        return self.bot.upload_to_katfile(file_path, progress_callback)
