import threading

from PyQt5.QtCore import QObject, Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractScrollArea,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionProgressBar,
    QPushButton,
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
        # adapt progress bar colour to theme
        palette = QApplication.palette()
        opt.palette = palette
        base = palette.color(QPalette.Base)
        is_dark = base.lightness() < 128
        bar_color = QColor("#66bb6a") if is_dark else QColor("#2e7d32")
        opt.palette.setColor(QPalette.Highlight, bar_color)
        opt.palette.setColor(QPalette.HighlightedText, QColor("white"))
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
        # Improve responsiveness and readability
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        # allow the message column to take remaining space
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.table.setSortingEnabled(True)
        # Use a progress bar delegate for the Progress column
        self.table.setItemDelegateForColumn(10, ProgressBarDelegate(self.table))
        layout.addWidget(self.table)
        self.cancel_event = threading.Event()
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        layout.addWidget(self.btn_cancel)
    def connect_worker(self, worker: QObject) -> None:
        if hasattr(worker, "progress_update"):
            worker.progress_update.connect(self.model.upsert)

    def on_cancel_clicked(self) -> None:
            """Signal the running worker to cancel."""
            self.cancel_event.set()