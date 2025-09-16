from types import ModuleType, SimpleNamespace
import importlib.util
import pathlib
import sys

from tests.qt_stubs import install_qt_stubs

# Install Qt stubs required by the upload worker
install_qt_stubs()

# Stub external dependencies used by UploadWorker
stubs = {
    "uploaders.ddownload_upload_handler": "DDownloadUploadHandler",
    "uploaders.katfile_upload_handler": "KatfileUploadHandler",
    "uploaders.nitroflare_upload_handler": "NitroflareUploadHandler",
    "uploaders.rapidgator_upload_handler": "RapidgatorUploadHandler",
    "uploaders.uploady_upload_handler": "UploadyUploadHandler",
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
    bot = SimpleNamespace(config={}, send_to_keeplinks=lambda urls: "keeplink")
    worker = UploadWorker(bot, row=0, folder_path=str(tmp_path), thread_id="t1", upload_hosts=["rapidgator", "rapidgator-backup"], files=[str(dummy)])

    def fake_upload_single(self, host_idx, file_path):
        return "https://rapidgator.net/main.rar" if host_idx == 0 else "https://rapidgator.net/backup.rar"

    monkeypatch.setattr(UploadWorker, "_upload_single", fake_upload_single)

    worker._upload_host_all(0)
    worker._upload_host_all(1)

    assert worker.upload_results[0]["urls"] == ["https://rapidgator.net/main.rar"]
    assert worker.upload_results[1]["urls"] == ["https://rapidgator.net/backup.rar"]

    final = worker._prepare_final_urls()
    assert final["rapidgator"] == ["https://rapidgator.net/main.rar"]
    assert final["rapidgator-backup"] == ["https://rapidgator.net/backup.rar"]
