"""Job and queue orchestration utilities.

This module keeps the original :class:`JobManager` used for persisting
``AutoProcessJob`` instances and adds a new :class:`QueueOrchestrator`
responsible for coordinating the Auto‑Proceed pipeline.  The orchestrator
throttles the different pipeline stages using semaphores so that downloads
run strictly one at a time, uploads may run concurrently (up to three) and
template generation is limited to a single worker.

The orchestrator is intentionally lightweight – it does not modify the
business logic inside the individual worker classes; it only schedules and
emits :class:`OperationStatus` updates so that the UI can remain responsive.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:  # pragma: no cover - provide fallbacks when PyQt5 is missing
    from PyQt5.QtCore import QObject, pyqtSignal
except Exception:  # pragma: no cover
    class QObject:  # type: ignore
        """Minimal QObject fallback used in headless test environments."""

        def __init__(self, *a, **kw):
            super().__init__()

    class _Signal:  # pragma: no cover - simple python signal
        def __init__(self):
            self._slots: List[Callable[..., Any]] = []

        def connect(self, func: Callable[..., Any], *_args, **_kw) -> None:
            self._slots.append(func)

        def emit(self, *args, **kwargs) -> None:
            for cb in list(self._slots):
                cb(*args, **kwargs)

    def pyqtSignal(*_args, **_kwargs):  # type: ignore
        return _Signal()

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Semaphore

from config.config import DATA_DIR
from models.job_model import AutoProcessJob
from models.operation_status import OpStage, OpType, OperationStatus

try:  # pragma: no cover - user manager is optional in tests
    from core.user_manager import get_user_manager
except Exception:  # pragma: no cover
    get_user_manager = lambda: None


# ---------------------------------------------------------------------------
# Existing JobManager
# ---------------------

class JobManager:
    """Load/save Auto‑Process jobs from ``DATA_DIR/jobs.json``."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else Path(DATA_DIR) / "jobs.json"
        self.jobs: Dict[str, AutoProcessJob] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                data = json.load(open(self.path, "r", encoding="utf-8"))
                self.jobs = {
                    jid: AutoProcessJob.from_dict(j) for jid, j in data.items()
                }
            except Exception as e:  # pragma: no cover - log but ignore
                logging.error("Failed to load jobs: %s", e)
                self.jobs = {}
        else:
            self.jobs = {}

    def save(self) -> None:
        tmp = {jid: job.to_dict() for jid, job in self.jobs.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(tmp, f, indent=2)

    def add_job(self, job: AutoProcessJob) -> None:
        self.jobs[job.job_id] = job
        self.save()

    def update_job(self, job: AutoProcessJob) -> None:
        self.jobs[job.job_id] = job
        self.save()

    def remove_job(self, job_id: str) -> None:
        if job_id in self.jobs:
            self.jobs.pop(job_id)
            self.save()

# ---------------------------------------------------------------------------
# QueueOrchestrator
# ---------------------------------------------------------------------------


@dataclass
class TopicPipeline:
    """Runtime state for a topic's pipeline."""

    topic_id: str
    download_fn: Callable[[], bool]
    process_fn: Callable[[], bool]
    upload_fn: Callable[[], bool]
    template_fn: Callable[[], bool]
    working_dir: str = ""
    ops: Dict[str, OpStage] = field(
        default_factory=lambda: {
            "download": OpStage.QUEUED,
            "process": OpStage.QUEUED,
            "upload": OpStage.QUEUED,
            "template": OpStage.QUEUED,
        }
    )
    failed_op: Optional[str] = None
    host_results: Dict[str, Any] = field(default_factory=dict)


class QueueOrchestrator(QObject):
    """Coordinate Auto‑Proceed operations with throttling and persistence."""

    progress_update = pyqtSignal(OperationStatus)

    def __init__(self, snapshot_file: str = "queue_snapshot.json", parent=None):
        super().__init__(parent)
        self.dl_sem = Semaphore(1)
        self.up_sem = Semaphore(3)
        self.tpl_sem = Semaphore(1)
        self.executor = ThreadPoolExecutor(max_workers=5)
        self._futures: List[Future] = []
        self.topics: Dict[str, TopicPipeline] = {}

        self.user_manager = get_user_manager()
        self.snapshot_file = snapshot_file
        self._load_snapshot()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _save_snapshot(self) -> None:
        """Persist queue state for the current user."""
        if not self.user_manager or not getattr(self.user_manager, "save_user_data", None):
            return
        data = {}
        for tid, state in self.topics.items():
            data[tid] = {
                "ops": {k: v.name for k, v in state.ops.items()},
                "failed_op": state.failed_op,
                "host_results": state.host_results,
                "working_dir": state.working_dir,
            }
        try:  # pragma: no cover - persistence best effort
            self.user_manager.save_user_data(self.snapshot_file, data)
        except Exception:  # pragma: no cover
            logging.debug("Queue snapshot save failed", exc_info=True)

    def _load_snapshot(self) -> None:
        if not self.user_manager or not getattr(self.user_manager, "load_user_data", None):
            return
        try:  # pragma: no cover - IO not under test
            data = self.user_manager.load_user_data(self.snapshot_file, default={})
        except Exception:
            data = {}
        for tid, info in data.items():
            ops = {
                k: OpStage[v]
                for k, v in info.get("ops", {}).items()
                if v in OpStage.__members__
            }
            state = TopicPipeline(
                topic_id=tid,
                download_fn=lambda: True,
                process_fn=lambda: True,
                upload_fn=lambda: True,
                template_fn=lambda: True,
                working_dir=info.get("working_dir", ""),
            )
            state.ops.update(ops)
            state.failed_op = info.get("failed_op")
            state.host_results = info.get("host_results", {})
            self.topics[tid] = state
            for name, st in state.ops.items():
                self._emit_status(tid, name, st)

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------
    def enqueue(
        self,
        topic_id: str,
        download_fn: Callable[[], bool],
        process_fn: Callable[[], bool],
        upload_fn: Callable[[], bool],
        template_fn: Callable[[], bool],
        working_dir: str = "",
    ) -> None:
        """Add a new topic to the queue and start its pipeline."""

        state = TopicPipeline(
            topic_id=topic_id,
            download_fn=download_fn,
            process_fn=process_fn,
            upload_fn=upload_fn,
            template_fn=template_fn,
            working_dir=working_dir,
        )
        self.topics[topic_id] = state

        # Emit queued status for all operations
        for name in ["download", "process", "upload", "template"]:
            self._emit_status(topic_id, name, OpStage.QUEUED)

        fut = self.executor.submit(self._run_topic, state)
        self._futures.append(fut)
        self._save_snapshot()

    # ------------------------------------------------------------------
    def _run_topic(self, state: TopicPipeline) -> None:
        """Execute the pipeline for a single topic."""

        # Download + Process (single worker)
        with self.dl_sem:
            if not self._run_stage(state, "download", state.download_fn):
                return
            if not self._run_stage(state, "process", state.process_fn):
                return

        # Upload (up to 3 concurrent)
        with self.up_sem:
            if not self._run_stage(state, "upload", state.upload_fn):
                return

        # Template generation (single worker)
        with self.tpl_sem:
            if not self._run_stage(state, "template", state.template_fn):
                return

        self._save_snapshot()

    # ------------------------------------------------------------------
    def _run_stage(self, state: TopicPipeline, name: str, fn: Callable[[], bool]) -> bool:
        self._emit_status(state.topic_id, name, OpStage.RUNNING)
        try:
            ok = fn()
        except Exception as e:  # pragma: no cover - worker errors
            ok = False
            err = str(e)
        else:
            err = ""
        if not ok:
            state.ops[name] = OpStage.ERROR
            state.failed_op = name
            self._emit_status(state.topic_id, name, OpStage.ERROR, err)
            self._save_snapshot()
            return False
        state.ops[name] = OpStage.FINISHED
        self._emit_status(state.topic_id, name, OpStage.FINISHED)
        self._save_snapshot()
        return True

    # ------------------------------------------------------------------
    def _emit_status(
        self, topic_id: str, name: str, stage: OpStage, message: str = ""
    ) -> None:
        op_map = {
            "download": OpType.DOWNLOAD,
            "process": OpType.COMPRESS,
            "upload": OpType.UPLOAD,
            "template": OpType.POST,
        }
        status = OperationStatus(
            section=topic_id,
            item=topic_id,
            op_type=op_map[name],
            stage=stage,
            message=message or ("Waiting…" if stage is OpStage.QUEUED else ""),
        )
        self.progress_update.emit(status)

    # ------------------------------------------------------------------
    def retry_topic(self, topic_id: str) -> None:
        state = self.topics.get(topic_id)
        if not state or not state.failed_op:
            return

        failed = state.failed_op
        if failed in {"download", "process"}:
            if state.working_dir:
                shutil.rmtree(state.working_dir, ignore_errors=True)
            for key in ["download", "process", "upload", "template"]:
                state.ops[key] = OpStage.QUEUED
        elif failed == "upload":
            state.host_results.clear()
            state.ops["upload"] = OpStage.QUEUED
            state.ops["template"] = OpStage.QUEUED
        else:  # template failure → restart template only
            state.ops["template"] = OpStage.QUEUED

        state.failed_op = None
        for name, st in state.ops.items():
            if st == OpStage.QUEUED:
                self._emit_status(topic_id, name, OpStage.QUEUED)

        fut = self.executor.submit(self._run_topic, state)
        self._futures.append(fut)
        self._save_snapshot()

    # ------------------------------------------------------------------
    def wait_for_all(self) -> None:
        """Utility used mainly in tests to wait for all queued tasks."""
        for fut in list(self._futures):
            fut.result()