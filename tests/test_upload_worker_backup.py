from types import SimpleNamespace, ModuleType
import importlib.util
import pathlib
import sys

# Stub minimal PyQt5.QtCore
qtcore = SimpleNamespace(
    QThread=object,
    pyqtSignal=lambda *a, **kw: (lambda *a, **kw: None),
    pyqtSlot=lambda *a, **kw: (lambda f: f),
)
sys.modules.setdefault("PyQt5", ModuleType("PyQt5"))
sys.modules["PyQt5.QtCore"] = qtcore

# Stub external dependencies used by UploadWorker
stubs = {
    "uploaders.ddownload_upload_handler": "DDownloadUploadHandler",
    "uploaders.katfile_upload_handler": "KatfileUploadHandler",
    "uploaders.nitroflare_upload_handler": "NitroflareUploadHandler",
    "uploaders.rapidgator_upload_handler": "RapidgatorUploadHandler",
}
for mod_name, cls_name in stubs.items():
    mod = ModuleType(mod_name)
    setattr(mod, cls_name, type(cls_name, (), {}))
    sys.modules[mod_name] = mod

jd_mod = ModuleType("integrations.jd_client")
jd_mod.hard_cancel = lambda *a, **kw: None
sys.modules["integrations.jd_client"] = jd_mod

# Import UploadWorker from file
module_path = pathlib.Path(__file__).resolve().parent.parent / "workers" / "upload_worker.py"
spec = importlib.util.spec_from_file_location("upload_worker", module_path)
upload_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload_worker)
UploadWorker = upload_worker.UploadWorker


def test_upload_worker_separates_backup_host(tmp_path, monkeypatch):
    dummy = tmp_path / "sample.mp3"
    dummy.write_bytes(b"data")
    bot = SimpleNamespace(config={})
    worker = UploadWorker(bot, row=0, folder_path=str(tmp_path), thread_id="t1", upload_hosts=["rapidgator", "rapidgator-backup"], files=[str(dummy)])

    def fake_upload_single(self, host_idx, file_path):
        return "https://rapidgator.net/main.rar" if host_idx == 0 else "https://rapidgator.net/backup.rar"

    monkeypatch.setattr(UploadWorker, "_upload_single", fake_upload_single)

    worker._upload_host_all(0)
    worker._upload_host_all(1)

    assert "rapidgator.net" in worker._host_results
    assert "rapidgator-backup" in worker._host_results
    assert worker._host_results["rapidgator-backup"].get("is_backup") is True
