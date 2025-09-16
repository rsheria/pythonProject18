import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

if "psutil" not in sys.modules:
    class _FakeProcess:
        def memory_info(self):
            return SimpleNamespace(rss=0)

    sys.modules["psutil"] = SimpleNamespace(Process=_FakeProcess)

_original_atexit = sys.modules.get("atexit")
sys.modules["atexit"] = SimpleNamespace(register=lambda func, *_, **__: func)

from core import file_processor

if _original_atexit is not None:
    sys.modules["atexit"] = _original_atexit
else:
    del sys.modules["atexit"]


@pytest.fixture
def processor(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    winrar_path = tmp_path / "winrar.exe"

    monkeypatch.setattr(file_processor, "DATA_DIR", str(data_dir))
    winrar_path.write_text("stub")

    return file_processor.FileProcessor(str(download_dir), str(winrar_path))


def test_win_move_file_ex_logs_on_failure(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(file_processor, "WINDOWS", True)

    calls = []

    def fake_move(src, dst, flags):
        calls.append((src, dst, flags))
        return 0

    monkeypatch.setattr(file_processor, "_MoveFileExW", fake_move)
    monkeypatch.setattr(file_processor, "_GET_LAST_ERROR", lambda: 123)
    monkeypatch.setattr(file_processor, "_FORMAT_ERROR", lambda err: "Simulated failure")

    result = file_processor._win_move_file_ex("C:\\very\\long\\path", "C:\\new\\path", 3)

    assert not result
    assert calls
    assert any(
        "MoveFileExW failed (C:\\very\\long\\path -> C:\\new\\path)" in record.message
        and "[WinError 123] Simulated failure" in record.message
        for record in caplog.records
    )


def test_safely_remove_file_permission_logs(monkeypatch, caplog, processor):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(file_processor, "WINDOWS", True)
    monkeypatch.setattr(file_processor, "_DeleteFileW", lambda path: 0)
    monkeypatch.setattr(file_processor, "_GET_LAST_ERROR", lambda: 5)
    monkeypatch.setattr(file_processor, "_FORMAT_ERROR", lambda err: "Access denied")

    target = processor.download_dir / "blocked.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("payload")

    original_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self == target:
            raise PermissionError("Denied")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    result = processor._safely_remove_file(target)

    assert result
    assert any(
        "DeleteFileW failed" in record.message
        and str(target) in record.message
        and "[WinError 5] Access denied" in record.message
        for record in caplog.records
    )

    original_unlink(target)
