"""Utility helpers to provide lightweight Qt stubs for unit tests.

The production code relies on PyQt5 for its threading primitives.  The test
environment used for automated evaluation does not ship with Qt, so we provide
simple stand-ins that mimic the behaviour required by the upload worker tests.

These stubs intentionally execute work synchronously.  This keeps the tests
deterministic while still exercising the threading coordination code paths in
``workers.upload_worker``.
"""

from __future__ import annotations

from types import ModuleType
from typing import Callable, List


class DummySignal:
    """Minimal signal object supporting ``connect`` and ``emit``."""

    def __init__(self) -> None:
        self._slots: List[Callable] = []

    def connect(self, slot: Callable, *_args, **_kwargs) -> None:
        self._slots.append(slot)

    def emit(self, *args, **kwargs) -> None:
        for slot in list(self._slots):
            slot(*args, **kwargs)


def dummy_pyqt_signal(*_args, **_kwargs) -> DummySignal:
    return DummySignal()


class ImmediateQRunnable:
    """Synchronous QRunnable stand-in."""

    def __init__(self) -> None:
        pass

    def run(self) -> None:  # pragma: no cover - subclasses override
        raise NotImplementedError


class ImmediateQThreadPool:
    """QThreadPool stub that executes runnables immediately."""

    def __init__(self) -> None:
        self._max = 1

    def setMaxThreadCount(self, count: int) -> None:
        self._max = max(1, int(count))

    def start(self, runnable: ImmediateQRunnable) -> None:
        runnable.run()

    def waitForDone(self) -> None:
        return None


class DummyQtCore(ModuleType):
    """Module object exposing the QtCore attributes used in tests."""

    def __init__(self) -> None:
        super().__init__("PyQt5.QtCore")
        self.QThread = object
        self.pyqtSignal = dummy_pyqt_signal
        self.pyqtSlot = lambda *a, **k: (lambda f: f)
        self.QThreadPool = ImmediateQThreadPool
        self.QRunnable = ImmediateQRunnable


def install_qt_stubs(modules=None) -> DummyQtCore:
    """Install the Qt stubs into ``sys.modules``.

    Returns the created ``PyQt5.QtCore`` module so tests can customise it if
    needed.
    """

    import sys

    if modules is None:
        modules = sys.modules

    qtcore = DummyQtCore()
    pyqt_pkg = ModuleType("PyQt5")
    setattr(pyqt_pkg, "QtCore", qtcore)

    modules["PyQt5"] = pyqt_pkg
    modules["PyQt5.QtCore"] = qtcore
    return qtcore


__all__ = [
    "DummyQtCore",
    "DummySignal",
    "ImmediateQThreadPool",
    "ImmediateQRunnable",
    "dummy_pyqt_signal",
    "install_qt_stubs",
]
