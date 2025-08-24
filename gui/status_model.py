from typing import List

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt
from models.operation_status import OperationStatus


class StatusTableModel(QAbstractTableModel):
    columns = [
        "Section",
        "File / Thread",
        "Type",
        "Added date",
        "Stage",
        "Message",
        "Errors",
        "Host",
        "Speed",
        "ETA",
        "Progress",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: List[OperationStatus] = []

    # Qt model interface -------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        op = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return op.section
            if col == 1:
                return op.item
            if col == 2:
                return op.op_type.name.title()
            if col == 3:
                return op.added.strftime("%Y-%m-%d %H:%M:%S")
            if col == 4:
                return op.stage.name.title()
            if col == 5:
                return op.message
            if col == 6:
                return op.errors
            if col == 7:
                return op.host
            if col == 8:
                return self._human_speed(op.speed)
            if col == 9:
                return self._human_time(op.eta)
            if col == 10:
                return op.progress
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _human_speed(speed: float) -> str:
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        idx = 0
        while speed >= 1024 and idx < len(units) - 1:
            speed /= 1024.0
            idx += 1
        return f"{speed:.1f} {units[idx]}"
    @staticmethod
    def _human_time(seconds: float) -> str:
        if seconds <= 0:
            return "-"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:d}:{s:02d}"
    def upsert(self, op: OperationStatus) -> None:
        key = (op.section, op.item, op.op_type, op.host)
        for r, existing in enumerate(self._rows):
            if (existing.section, existing.item, existing.op_type, existing.host) == key:
                self._rows[r] = op
                break
            else:
                r = len(self._rows)
                self.beginInsertRows(QModelIndex(), r, r)
                self._rows.append(op)
                self.endInsertRows()
        self.dataChanged.emit(
            self.index(r, 0),
            self.index(r, self.columnCount() - 1),
            [],
        )