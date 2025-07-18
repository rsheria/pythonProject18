from abc import ABC, abstractmethod

class BaseUploader(ABC):
    """
    واجهة لكل Uploader: يرفع ملف ويرجع dict بنتيجة الرفع.
    """

    @abstractmethod
    def upload(self, file_path: str, **kwargs) -> dict:
        """
        يرفع الملف الموجود في file_path
        ويرجع dict فيه keys: 'status', 'url' أو 'error'
        """
        pass
