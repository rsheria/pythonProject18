# workers/__init__.py

from .worker_thread           import WorkerThread
from .download_worker        import DownloadWorker
from .upload_worker          import UploadWorker
from .megathreads_worker     import MegaThreadsWorkerThread
from .mega_download_worker   import MegaDownloadWorker   # ← أضف هذا السطر
from .auto_process_worker import AutoProcessWorker