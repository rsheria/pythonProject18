import sys
import types

# Stub minimal PyQt5 modules so workers can import
qtcore = types.SimpleNamespace(
    QThread=object, pyqtSignal=lambda *a, **k: None, pyqtSlot=lambda *a, **k: (lambda f: f)
)
sys.modules.setdefault("PyQt5", types.ModuleType("PyQt5"))
sys.modules["PyQt5.QtCore"] = qtcore
sys.modules.setdefault("requests", types.ModuleType("requests"))
# Stub out heavy dependencies referenced by download_worker
sys.modules.setdefault("downloaders", types.ModuleType("downloaders"))
dj = types.ModuleType("downloaders.jdownloader")
dj.JDownloaderDownloader = object
sys.modules.setdefault("downloaders.jdownloader", dj)
kat_mod = types.ModuleType("downloaders.katfile")
kat_mod.KatfileDownloader = object
sys.modules.setdefault("downloaders.katfile", kat_mod)
rg_mod = types.ModuleType("downloaders.rapidgator")
rg_mod.RapidgatorDownloader = object
sys.modules.setdefault("downloaders.rapidgator", rg_mod)
sys.modules.setdefault("integrations", types.ModuleType("integrations"))
jd_mod = types.ModuleType("integrations.jd_client")
jd_mod.hard_cancel = lambda *a, **k: None
sys.modules.setdefault("integrations.jd_client", jd_mod)
sys.modules.setdefault("jd_client", types.ModuleType("jd_client"))
sys.modules.setdefault("core", types.ModuleType("core"))
core_user_manager = types.ModuleType("core.user_manager")
core_user_manager.get_user_manager = lambda: None
sys.modules.setdefault("core.user_manager", core_user_manager)
sys.modules.setdefault("models", types.ModuleType("models"))
op_mod = types.ModuleType("models.operation_status")
op_mod.OperationStatus = object
op_mod.OpStage = object
op_mod.OpType = object
sys.modules.setdefault("models.operation_status", op_mod)
wu_mod = types.ModuleType("workers.upload_worker")
wu_mod.UploadWorker = object
sys.modules.setdefault("workers.upload_worker", wu_mod)
wt_mod = types.ModuleType("workers.worker_thread")
wt_mod.WorkerThread = object
sys.modules.setdefault("workers.worker_thread", wt_mod)
sys.modules.setdefault("utils", types.ModuleType("utils"))
san_mod = types.ModuleType("utils.sanitize")
san_mod.sanitize_filename = lambda x: x
sys.modules.setdefault("utils.sanitize", san_mod)
fs_mod = types.ModuleType("utils.file_scanner")
fs_mod.scan_thread_dir = lambda *a, **k: []
sys.modules.setdefault("utils.file_scanner", fs_mod)

import importlib.util
from pathlib import Path

workers_pkg = types.ModuleType("workers")
workers_pkg.__path__ = []
sys.modules.setdefault("workers", workers_pkg)
spec = importlib.util.spec_from_file_location(
    "workers.download_worker",
    Path(__file__).resolve().parents[1] / "workers" / "download_worker.py",
)
download_worker = importlib.util.module_from_spec(spec)
sys.modules["workers.download_worker"] = download_worker
spec.loader.exec_module(download_worker)
DownloadWorker = download_worker.DownloadWorker


def test_are_all_book_files_true():
    files = ["a.pdf", "b.epub", "c.cbz"]
    assert DownloadWorker._are_all_book_files(files)


def test_are_all_book_files_false():
    files = ["a.pdf", "b.mp3"]
    assert not DownloadWorker._are_all_book_files(files)
