import sys
import types

# Stub minimal PyQt5 modules so workers can import
qtcore = types.SimpleNamespace(
    QThread=object, pyqtSignal=lambda *a, **k: None, pyqtSlot=lambda *a, **k: (lambda f: f)
)
sys.modules.setdefault("PyQt5", types.ModuleType("PyQt5"))
sys.modules["PyQt5.QtCore"] = qtcore
sys.modules.setdefault("requests", types.ModuleType("requests"))
# Stub out heavy dependencies referenced by upload_worker
sys.modules.setdefault("integrations", types.ModuleType("integrations"))
jd_mod = types.ModuleType("integrations.jd_client")
jd_mod.hard_cancel = lambda *a, **k: None
sys.modules.setdefault("integrations.jd_client", jd_mod)
sys.modules.setdefault("models", types.ModuleType("models"))
op_mod = types.ModuleType("models.operation_status")
op_mod.OperationStatus = object
op_mod.OpStage = object
op_mod.OpType = object
sys.modules.setdefault("models.operation_status", op_mod)
sys.modules.setdefault("utils", types.ModuleType("utils"))
utils_mod = types.ModuleType("utils.utils")
utils_mod._normalize_links = lambda x: x
sys.modules.setdefault("utils.utils", utils_mod)
sys.modules.setdefault("uploaders", types.ModuleType("uploaders"))
dd_mod = types.ModuleType("uploaders.ddownload_upload_handler")
dd_mod.DDownloadUploadHandler = object
sys.modules.setdefault("uploaders.ddownload_upload_handler", dd_mod)
kat_mod = types.ModuleType("uploaders.katfile_upload_handler")
kat_mod.KatfileUploadHandler = object
sys.modules.setdefault("uploaders.katfile_upload_handler", kat_mod)
nf_mod = types.ModuleType("uploaders.nitroflare_upload_handler")
nf_mod.NitroflareUploadHandler = object
sys.modules.setdefault("uploaders.nitroflare_upload_handler", nf_mod)
rg_mod = types.ModuleType("uploaders.rapidgator_upload_handler")
rg_mod.RapidgatorUploadHandler = object
sys.modules.setdefault("uploaders.rapidgator_upload_handler", rg_mod)

import importlib.util
from pathlib import Path

workers_pkg = types.ModuleType("workers")
workers_pkg.__path__ = []
sys.modules.setdefault("workers", workers_pkg)
spec = importlib.util.spec_from_file_location(
    "workers.upload_worker",
    Path(__file__).resolve().parents[1] / "workers" / "upload_worker.py",
)
upload_worker = importlib.util.module_from_spec(spec)
sys.modules["workers.upload_worker"] = upload_worker
spec.loader.exec_module(upload_worker)
UploadWorker = upload_worker.UploadWorker


class DummyBot:
    def __init__(self):
        self.config = {}

def test_kind_from_name_archive_book(tmp_path):
    dummy = DummyBot()
    (tmp_path / "a.rar").write_text("data")
    worker = UploadWorker(
        dummy,
        0,
        str(tmp_path),
        "tid",
        upload_hosts=[],
        files=[str(tmp_path / "a.rar")],
        package_label="book",
    )
    assert worker._kind_from_name("archive.rar") == "book"
    assert worker._kind_from_name("file.pdf") == "book"
core_user_manager = types.ModuleType("core.user_manager")
core_user_manager.get_user_manager = lambda: None
sys.modules.setdefault("core", types.ModuleType("core"))
sys.modules.setdefault("core.user_manager", core_user_manager)
