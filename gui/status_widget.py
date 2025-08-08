from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QTableView, QVBoxLayout, QWidget

from .status_model import StatusTableModel


class StatusWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = StatusTableModel()
        layout = QVBoxLayout(self)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def connect_worker(self, worker: QObject) -> None:
        if hasattr(worker, "progress_update"):
            worker.progress_update.connect(self.model.upsert)