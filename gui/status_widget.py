from PyQt5.QtCore import QObject, Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QTableView,
    QVBoxLayout,
    QWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionProgressBar,
)

from .status_model import StatusTableModel
class ProgressBarDelegate(QStyledItemDelegate):
    """Display integer progress values as a green progress bar."""

    def paint(self, painter, option, index):  # type: ignore[override]
        value = int(index.data(Qt.DisplayRole) or 0)
        opt = QStyleOptionProgressBar()
        opt.rect = option.rect
        opt.minimum = 0
        opt.maximum = 100
        opt.progress = value
        opt.text = f"{value}%"
        opt.textVisible = True
        opt.textAlignment = Qt.AlignCenter
        opt.state = option.state | QStyle.State_Enabled
        opt.palette = QApplication.palette()
        opt.palette.setColor(QPalette.Highlight, QColor("#4caf50"))
        QApplication.style().drawControl(QStyle.CE_ProgressBar, opt, painter)

class StatusWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = StatusTableModel()
        layout = QVBoxLayout(self)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setAlternatingRowColors(True)
        # Use a progress bar delegate for the Progress column
        self.table.setItemDelegateForColumn(10, ProgressBarDelegate(self.table))
        layout.addWidget(self.table)

    def connect_worker(self, worker: QObject) -> None:
        if hasattr(worker, "progress_update"):
            worker.progress_update.connect(self.model.upsert)