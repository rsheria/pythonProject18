# nitroflare_upload_handler.py

class NitroflareUploadHandler:
    def __init__(self, bot):
        # bot هو مثيل ForumBotSelenium أو ما يتوفّر لديك
        self.bot = bot

    def upload_file(self, file_path: str, progress_callback):
        """
        يجب أن تعيد URL (string) عند النجاح، أو None عند الفشل.
        يفترض أن لديك دالة upload_to_nitroflare في bot.
        """
        return self.bot.upload_to_nitroflare(file_path, progress_callback)
