"""Stress tests for the threading architecture of ``UploadWorker``."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tests.qt_stubs import install_qt_stubs


def _ensure_module(mod_name: str, attrs: dict, monkeypatch) -> None:
    module = ModuleType(mod_name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, mod_name, module)


@pytest.fixture
def upload_worker_module(monkeypatch):
    """Import ``workers.upload_worker`` with lightweight stubs."""

    install_qt_stubs()

    # Stub heavy dependencies the worker pulls in on import.
    _ensure_module(
        "integrations.jd_client",
        {"hard_cancel": lambda *a, **k: None},
        monkeypatch,
    )

    uploader_classes = {
        "uploaders.ddownload_upload_handler": "DDownloadUploadHandler",
        "uploaders.katfile_upload_handler": "KatfileUploadHandler",
        "uploaders.nitroflare_upload_handler": "NitroflareUploadHandler",
        "uploaders.rapidgator_upload_handler": "RapidgatorUploadHandler",
        "uploaders.uploady_upload_handler": "UploadyUploadHandler",
    }
    for mod_name, cls_name in uploader_classes.items():
        _ensure_module(mod_name, {cls_name: object}, monkeypatch)

    op_mod = ModuleType("models.operation_status")

    class DummyOperationStatus:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    op_mod.OperationStatus = DummyOperationStatus
    op_mod.OpStage = SimpleNamespace(RUNNING="running", ERROR="error", FINISHED="finished")
    op_mod.OpType = SimpleNamespace(UPLOAD="upload")
    monkeypatch.setitem(sys.modules, "models.operation_status", op_mod)

    module_path = Path(__file__).resolve().parents[1] / "workers" / "upload_worker.py"
    spec = importlib.util.spec_from_file_location("workers.upload_worker", module_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "workers.upload_worker", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _dummy_bot():
    return SimpleNamespace(config={}, send_to_keeplinks=lambda urls: "keeplink" if urls else None)


def _create_files(tmp_path, count=2):
    files = []
    for idx in range(count):
        path = tmp_path / f"file_{idx}.bin"
        path.write_bytes(b"data")
        files.append(str(path))
    return files


def test_upload_worker_cancellation(tmp_path, monkeypatch, upload_worker_module):
    UploadWorker = upload_worker_module.UploadWorker

    worker = UploadWorker(
        _dummy_bot(),
        row=0,
        folder_path=str(tmp_path),
        thread_id="tid",
        upload_hosts=["h1", "h2"],
        files=_create_files(tmp_path, 1),
    )

    events = []
    worker.upload_error = SimpleNamespace(emit=lambda *args: events.append(("error", args)))
    worker.upload_complete = SimpleNamespace(emit=lambda *args: events.append(("complete", args)))
    worker.upload_success = SimpleNamespace(emit=lambda *args: events.append(("success", args)))
    worker.progress_update = SimpleNamespace(emit=lambda *_: None)
    worker.host_progress = SimpleNamespace(emit=lambda *_: None)

    def fail_first_host(self, host_idx):
        if host_idx == 0:
            self.cancel_uploads()
            raise Exception("Upload cancelled by user")
        return "success"

    monkeypatch.setattr(UploadWorker, "_upload_host_all", fail_first_host)

    worker.run()

    assert any("أُلغي" in evt[1][1] for evt in events if evt[0] == "error")
    assert any(evt[0] == "complete" for evt in events)


def test_upload_worker_retry_recovers(tmp_path, monkeypatch, upload_worker_module):
    UploadWorker = upload_worker_module.UploadWorker

    worker = UploadWorker(
        _dummy_bot(),
        row=1,
        folder_path=str(tmp_path),
        thread_id="tid",
        upload_hosts=["h1", "h2"],
        files=_create_files(tmp_path, 1),
    )

    worker.upload_results[0] = {"status": "failed", "urls": []}
    worker.upload_results[1] = {"status": "success", "urls": ["ok"]}

    completions = []
    worker.upload_complete = SimpleNamespace(emit=lambda row, payload: completions.append(payload))
    worker.progress_update = SimpleNamespace(emit=lambda *_: None)
    worker.host_progress = SimpleNamespace(emit=lambda *_: None)

    def succeed_on_retry(self, host_idx):
        self.upload_results[host_idx]["urls"] = [f"https://retry/{host_idx}"]
        return "success"

    monkeypatch.setattr(UploadWorker, "_upload_host_all", succeed_on_retry)

    worker._retry_in_background()

    assert worker.upload_results[0]["status"] == "success"
    assert worker.upload_results[0]["urls"] == ["https://retry/0"]
    assert completions and "error" not in completions[-1]


def test_upload_worker_handles_rapid_restarts(tmp_path, monkeypatch, upload_worker_module):
    UploadWorker = upload_worker_module.UploadWorker

    worker = UploadWorker(
        _dummy_bot(),
        row=2,
        folder_path=str(tmp_path),
        thread_id="tid",
        upload_hosts=["h1", "h2"],
        files=_create_files(tmp_path, 1),
    )

    call_sequence = []

    def controlled_upload(self, host_idx):
        step = getattr(self, "_restart_step", 0)
        call_sequence.append((step, host_idx))
        if step == 0 and host_idx == 0:
            self.cancel_uploads()
            raise Exception("Upload cancelled by user")
        self.upload_results[host_idx]["urls"] = [f"https://ok/{step}/{host_idx}"]
        return "success"

    monkeypatch.setattr(UploadWorker, "_upload_host_all", controlled_upload)

    cancelled, errors = worker._run_host_batch([0, 1])
    with pytest.raises(Exception):
        worker._raise_if_batch_failed(cancelled, errors)

    worker._reset_control_for_retry()
    for idx in worker.upload_results:
        worker.upload_results[idx] = {"status": "not_attempted", "urls": []}
    worker._restart_step = 1

    cancelled, errors = worker._run_host_batch([0, 1])
    worker._raise_if_batch_failed(cancelled, errors)

    assert all(res["status"] == "success" for res in worker.upload_results.values())
    assert any(step == 0 for step, _ in call_sequence)
    assert any(step == 1 for step, _ in call_sequence)
