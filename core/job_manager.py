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
    section: str
    item: str
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

    progress_update = pyqtSignal(object)  # OperationStatus

    def __init__(
        self,
        dl_sem: int = 1,
        up_sem: int = 3,
        tpl_sem: int = 1,
        snapshot_file: str = "queue_snapshot.json",
        parent=None,
    ):
        super().__init__(parent)
        self.dl_sem = Semaphore(dl_sem)
        self.up_sem = Semaphore(up_sem)
        self.tpl_sem = Semaphore(tpl_sem)
        self.executor = ThreadPoolExecutor(max_workers=5)
        self._futures: List[Future] = []
        self.topics: Dict[str, TopicPipeline] = {}

        self.user_manager = get_user_manager()
        self.snapshot_file = snapshot_file
        self._load_snapshot()

    # ------------------------------------------------------------------
    # Persistence helpers


        def _host_from_url(self, url: str) -> str:
            """
            استخرج اسم المضيف طبيعي (بدون www)؛ أى خطأ يرجّع سلسلة فاضية.
            """
            try:
                from urllib.parse import urlparse
                host = (urlparse(url).netloc or "").lower()
                if host.startswith("www."):
                    host = host[4:]
                return host
            except Exception:
                return ""

        def _media_kind_and_ext(self, source_filename: str) -> tuple[str, str]:
            """
            حدد النوع (book|audio) والامتداد من اسم الملف الأصلي.
            لو غير معروف يرجّع ("", "") كـ fallback.
            """
            try:
                import os
                ext = os.path.splitext(source_filename)[1].lower().lstrip(".")
                if not ext:
                    return "", ""
                book_exts = {"pdf", "epub", "azw3", "mobi", "djvu"}
                audio_exts = {"mp3", "m4b", "flac", "ogg", "wav"}
                if ext in book_exts:
                    return "book", ext
                if ext in audio_exts:
                    return "audio", ext
                return "", ext  # امتداد غير معروف لكن ممكن نخزنه تحت all فقط
            except Exception:
                return "", ""

        def record_uploaded_urls(self, topic_id: str, source_filename: str, urls: list[str]) -> None:
            """
            نادِى الدالة دى بعد كل رفع ناجح لملف واحد:
            - topic_id: معرف التوبك الجاري.
            - source_filename: اسم الملف الأصلي اللى اترفع (نستخدمه لتحديد النوع والامتداد).
            - urls: قائمة الروابط الراجعة من المضيفين (Rapidgator/Nitroflare/...).
            بتحدّث state.host_results بالشكل:
            {
              "<host>": {
                "all": [..],
                "by_type": {
                  "book": { "pdf": [..], "epub": [..], ... },
                  "audio": { "m4b": [..], "mp3": [..], ... }
                }
              },
              ...
            }
            """
            try:
                state = self.topics.get(topic_id)
                if not state or not urls:
                    return

                kind, ext = self._media_kind_and_ext(source_filename)

                for u in urls:
                    h = self._host_from_url(u)
                    if not h:
                        continue

                    host_bucket = state.host_results.setdefault(h, {})
                    all_list = host_bucket.setdefault("all", [])
                    by_type = host_bucket.setdefault("by_type", {"book": {}, "audio": {}})

                    # append to 'all' (مع إزالة التكرارات مع الحفاظ على الترتيب)
                    if u not in all_list:
                        all_list.append(u)

                    # لو قدرنا نحدد النوع
                    if kind in ("book", "audio") and ext:
                        type_map = by_type.setdefault(kind, {})
                        ext_list = type_map.setdefault(ext, [])
                        if u not in ext_list:
                            ext_list.append(u)

                # حفظ سنابشوت علشان الواجهة تقدر تعرض "View Links" فورًا بنفس المنطق الحالى
                self._save_snapshot()
            except Exception:
                import logging
                logging.debug("record_uploaded_urls failed", exc_info=True)

    def _save_snapshot(self) -> None:
        """Persist queue state for the current user."""
        if not self.user_manager or not getattr(self.user_manager, "save_user_data", None):
            return
        data = {}
        for tid, state in self.topics.items():
            data[tid] = {
                "section": state.section,
                "item": state.item,
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
                section=info.get("section", tid),
                item=info.get("item", tid),
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
                if name != "process":
                    self._emit_status(state, name, st)

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------
    def enqueue(
        self,
        topic_id: str,
        section: str,
        item: str,
        download_cb: Callable[[], bool],
        process_cb: Callable[[], bool],
        upload_cb: Callable[[], bool],
        template_cb: Callable[[], bool],
        working_dir: str = "",
    ) -> None:
        """Add a new topic to the queue and start its pipeline."""

        state = TopicPipeline(
            topic_id=topic_id,
            section=section,
            item=item,
            download_fn=download_cb,
            process_fn=process_cb,
            upload_fn=upload_cb,
            template_fn=template_cb,
            working_dir=working_dir,
        )
        self.topics[topic_id] = state

        # Emit queued status for main operations only
        for name in ["download", "upload", "template"]:
            self._emit_status(state, name, OpStage.QUEUED)

        fut = self.executor.submit(self._run_topic, state)
        self._futures.append(fut)
        self._save_snapshot()

        # ------------------------------------------------------------------

    def _run_download_pipeline(self, state: TopicPipeline) -> bool:
        """Run download and process sequentially under the same status."""
        self._emit_status(state, "download", OpStage.RUNNING)
        try:
            ok = state.download_fn()
        except Exception as e:  # pragma: no cover - worker errors
            ok = False
            err = str(e)
        else:
            err = ""
        if not ok:
            state.ops["download"] = OpStage.ERROR
            state.failed_op = "download"
            self._emit_status(state, "download", OpStage.ERROR, err)
            self._save_snapshot()
            return False

        # Processing phase
        try:
            ok = state.process_fn()
        except Exception as e:  # pragma: no cover
            ok = False
            err = str(e)
        else:
            err = ""
        if not ok:
            state.ops["process"] = OpStage.ERROR
            state.ops["download"] = OpStage.ERROR
            state.failed_op = "process"
            self._emit_status(state.topic_id, "download", OpStage.ERROR, err)
            self._save_snapshot()
            return False

        state.ops["download"] = OpStage.FINISHED
        state.ops["process"] = OpStage.FINISHED
        self._emit_status(state, "download", OpStage.FINISHED)
        self._save_snapshot()
        return True

    # ------------------------------------------------------------------
    def _run_stage(self, state: TopicPipeline, name: str, fn: Callable[[], bool]) -> bool:
        self._emit_status(state, name, OpStage.RUNNING)
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
            self._emit_status(state, name, OpStage.ERROR, err)
            self._save_snapshot()
            return False
        state.ops[name] = OpStage.FINISHED
        self._emit_status(state, name, OpStage.FINISHED)
        self._save_snapshot()
        return True

    # ------------------------------------------------------------------
    def _emit_status(self, state: TopicPipeline, name: str, stage: OpStage, message: str = "") -> None:
        op_map = {
            "download": OpType.DOWNLOAD,
            "process": OpType.COMPRESS,
            "upload": OpType.UPLOAD,
            "template": OpType.POST,
        }
        status = OperationStatus(
            section=state.section,
            item=state.item,
            op_type=op_map[name],
            stage=stage,
            message=message or ("Waiting…" if stage is OpStage.QUEUED else ""),
        )
        self.progress_update.emit(status)

        # job_manager.py:

    def _host_from_url(self, url: str) -> str:
            """
            استخرج اسم المضيف طبيعي (بدون www)؛ أى خطأ يرجّع سلسلة فاضية.
            """
            try:
                from urllib.parse import urlparse
                host = (urlparse(url).netloc or "").lower()
                if host.startswith("www."):
                    host = host[4:]
                return host
            except Exception:
                return ""

    def _media_kind_and_ext(self, source_filename: str) -> tuple[str, str]:
            """
            حدد النوع (book|audio) والامتداد من اسم الملف الأصلي.
            لو غير معروف يرجّع ("", "") كـ fallback.
            """
            try:
                import os
                ext = os.path.splitext(source_filename)[1].lower().lstrip(".")
                if not ext:
                    return "", ""
                book_exts = {"pdf", "epub", "azw3", "mobi", "djvu"}
                audio_exts = {"mp3", "m4b", "flac", "ogg", "wav"}
                if ext in book_exts:
                    return "book", ext
                if ext in audio_exts:
                    return "audio", ext
                return "", ext  # امتداد غير معروف لكن ممكن نخزنه تحت all فقط
            except Exception:
                return "", ""

    def record_uploaded_urls(self, topic_id: str, source_filename: str, urls: list[str]) -> None:
            """
            نادِى الدالة دى بعد كل رفع ناجح لملف واحد:
            - topic_id: معرف التوبك الجاري.
            - source_filename: اسم الملف الأصلي اللى اترفع (نستخدمه لتحديد النوع والامتداد).
            - urls: قائمة الروابط الراجعة من المضيفين (Rapidgator/Nitroflare/...).
            بتحدّث state.host_results بالشكل:
            {
              "<host>": {
                "all": [..],
                "by_type": {
                  "book": { "pdf": [..], "epub": [..], ... },
                  "audio": { "m4b": [..], "mp3": [..], ... }
                }
              },
              ...
            }
            """
            try:
                state = self.topics.get(topic_id)
                if not state or not urls:
                    return

                kind, ext = self._media_kind_and_ext(source_filename)

                for u in urls:
                    h = self._host_from_url(u)
                    if not h:
                        continue

                    host_bucket = state.host_results.setdefault(h, {})
                    all_list = host_bucket.setdefault("all", [])
                    by_type = host_bucket.setdefault("by_type", {"book": {}, "audio": {}})

                    # append to 'all' (مع إزالة التكرارات مع الحفاظ على الترتيب)
                    if u not in all_list:
                        all_list.append(u)

                    # لو قدرنا نحدد النوع
                    if kind in ("book", "audio") and ext:
                        type_map = by_type.setdefault(kind, {})
                        ext_list = type_map.setdefault(ext, [])
                        if u not in ext_list:
                            ext_list.append(u)

                # حفظ سنابشوت علشان الواجهة تقدر تعرض "View Links" فورًا بنفس المنطق الحالى
                self._save_snapshot()
            except Exception:
                import logging
                logging.debug("record_uploaded_urls failed", exc_info=True)

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
                self._emit_status(state, name, OpStage.QUEUED)

        fut = self.executor.submit(self._run_topic, state)
        self._futures.append(fut)
        self._save_snapshot()

    # ------------------------------------------------------------------
    def wait_for_all(self) -> None:
        """Utility used mainly in tests to wait for all queued tasks."""
        for fut in list(self._futures):
            fut.result()