import pytest

try:
    from PyQt5.QtCore import QObject, pyqtSignal
    from PyQt5.QtWidgets import QApplication
except Exception:  # pragma: no cover - optional dependency
    pytest.skip("PyQt5 not available", allow_module_level=True)

from gui.status_model import StatusTableModel
from models.operation_status import OperationStatus, OpType


class DummyWorker(QObject):
    progress_update = pyqtSignal(OperationStatus)


def test_status_model_upsert():
    app = QApplication.instance() or QApplication([])
    worker = DummyWorker()
    model = StatusTableModel()
    worker.progress_update.connect(model.upsert)

    worker.progress_update.emit(OperationStatus("Sec", "Item", OpType.DOWNLOAD))
    worker.progress_update.emit(
        OperationStatus("Sec", "Item", OpType.DOWNLOAD, progress=50)
    )
    worker.progress_update.emit(
        OperationStatus("Sec", "Item", OpType.DOWNLOAD, progress=100)
    )

    assert model.rowCount() == 1
    assert model.data(model.index(0, 10)) == 100