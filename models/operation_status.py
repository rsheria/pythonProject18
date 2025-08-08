from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto


class OpType(Enum):
    DOWNLOAD = auto()
    UPLOAD = auto()
    COMPRESS = auto()
    POST = auto()


class OpStage(Enum):
    QUEUED = auto()
    RUNNING = auto()
    FINISHED = auto()
    ERROR = auto()


@dataclass
class OperationStatus:
    section: str
    item: str
    op_type: OpType
    added: datetime = field(default_factory=datetime.now)
    stage: OpStage = OpStage.QUEUED
    message: str = "Waiting…"
    progress: int = 0
    speed: float = 0.0
    eta: float = 0.0
    host: str = "-"
    errors: int = 0