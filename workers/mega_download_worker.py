# workers/mega_download_worker.py

from .download_worker import DownloadWorker

class MegaDownloadWorker(DownloadWorker):
    """
    Worker مخصّص لتحميل محتوى الميجاثريدز (إذا كنت تريد منطقًا مختلفًا،
    افرِضه هنا ورثًا عن DownloadWorker).
    حالياً يرث من DownloadWorker بدون تغيير.
    """
    pass
