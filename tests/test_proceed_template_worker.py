import importlib.util
import pathlib
import sys
import types
import logging

import pytest


class DummyTM:
    def render_with_links(self, *args, **kwargs):
        raise RuntimeError("boom")


def test_merge_links_logs_exception_and_returns_original(monkeypatch, caplog):
    # Provide minimal PyQt5 stubs so proceed_template_worker can be imported without Qt.
    class _DummySignal:
        def connect(self, *args, **kwargs):
            pass

        def emit(self, *args, **kwargs):
            pass

    class _DummyQThread:
        def __init__(self, *args, **kwargs):
            pass

    def _pyqtSignal(*args, **kwargs):
        return _DummySignal()

    class _DummyMutexLocker:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

    qtcore_stub = types.SimpleNamespace(
        QThread=_DummyQThread, pyqtSignal=_pyqtSignal, QMutexLocker=_DummyMutexLocker
    )
    monkeypatch.setitem(sys.modules, "PyQt5", types.SimpleNamespace(QtCore=qtcore_stub))
    monkeypatch.setitem(sys.modules, "PyQt5.QtCore", qtcore_stub)

    spec = importlib.util.spec_from_file_location(
        "proceed_template_worker",
        pathlib.Path(__file__).resolve().parents[1] / "workers" / "proceed_template_worker.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ProceedTemplateWorker = module.ProceedTemplateWorker

    worker = ProceedTemplateWorker(
        bot=None,
        bot_lock=None,
        category="cat",
        title="title",
        raw_bbcode="raw",
        author="author",
        links_block="",
    )

    monkeypatch.setattr(
        "core.template_manager.get_template_manager", lambda: DummyTM()
    )

    filled = "[b]content[/b]"
    host_results = {"dummy": "data"}
    with caplog.at_level(logging.ERROR):
        result = worker._merge_links_into_bbcode("cat", filled, host_results)
    assert result == filled
    assert any("Failed to merge links into BBCode" in r.message for r in caplog.records)
