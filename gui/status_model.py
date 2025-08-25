from typing import List

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt5.QtGui import QColor

from .themes import theme_manager

from models.operation_status import OperationStatus, OpStage


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
        if role == Qt.BackgroundRole:
            t = theme_manager.get_current_theme()
            if theme_manager.theme_mode == "dark":
                colors = {
                    OpStage.QUEUED: t.SURFACE_VARIANT,
                    OpStage.RUNNING: getattr(t, "INFO_LIGHT", t.INFO),
                    OpStage.FINISHED: getattr(t, "SUCCESS_LIGHT", t.SUCCESS),
                    OpStage.ERROR: getattr(t, "ERROR_LIGHT", t.ERROR),

                }
            else:
                colors = {
                    OpStage.QUEUED: t.SURFACE_VARIANT,
                    OpStage.RUNNING: t.INFO,
                    OpStage.FINISHED: t.SUCCESS,
                    OpStage.ERROR: t.ERROR,

                }
            color = colors.get(op.stage)
            if color:
                return QColor(color)
        if role == Qt.ForegroundRole:
            t = theme_manager.get_current_theme()
            if op.stage == OpStage.QUEUED:
                return QColor(t.TEXT_PRIMARY)
            if theme_manager.theme_mode == "dark":
                return QColor(t.BACKGROUND)
            return QColor(t.TEXT_ON_PRIMARY)
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
        for row, existing in enumerate(self._rows):
            if (existing.section, existing.item, existing.op_type, existing.host) == key:
                # Determine which columns have changed compared to the existing
                # OperationStatus.  We update only those indices to minimise
                # view refresh work.
                changed: list[int] = []
                if existing.section != op.section:
                    changed.append(0)
                if existing.item != op.item:
                    changed.append(1)
                if existing.op_type != op.op_type:
                    changed.append(2)
                if existing.added != op.added:
                    changed.append(3)
                if existing.stage != op.stage:
                    changed.append(4)
                if existing.message != op.message:
                    changed.append(5)
                if existing.errors != op.errors:
                    changed.append(6)
                if existing.host != op.host:
                    changed.append(7)
                if existing.speed != op.speed:
                    changed.append(8)
                if existing.eta != op.eta:
                    changed.append(9)
                if existing.progress != op.progress:
                    changed.append(10)
                self._rows[row] = op
                for col in changed:
                    idx = self.index(row, col)
                    self.dataChanged.emit(
                        idx, idx, [Qt.DisplayRole, Qt.BackgroundRole]
                    )
                return
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append(op)
        self.endInsertRows()