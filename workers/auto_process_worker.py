import logging
import shutil
import time
from pathlib import Path
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal

from models.job_model import AutoProcessJob, SelectedRowSnapshot
from models.operation_status import OperationStatus, OpStage, OpType


class AutoProcessWorkerSignals(QObject):
    """Signals used by :class:`AutoProcessWorker`.

    ``progress_update`` carries an :class:`OperationStatus` instance so the UI can
    update the status table without the worker touching any Qt widgets directly.
    Other signals propagate results and lifecycle events.
    """

    progress_update = pyqtSignal(object)  # OperationStatus
    result_ready = pyqtSignal(str, dict)  # job_id, payload
    error = pyqtSignal(str, str)  # job_id, message
    finished = pyqtSignal(str)  # job_id


class AutoProcessWorker(QRunnable):
    """Background task that runs the Auto‑Process pipeline for a single job.

    The worker operates purely on the immutable :class:`SelectedRowSnapshot`
    provided at construction time.  It deliberately avoids any access to the
    GUI's models or views so that filtering/sorting/deleting rows in the UI does
    not influence the running pipeline.
    """

    def __init__(
        self,
        job: AutoProcessJob,
        snapshot: SelectedRowSnapshot,
        jd_client,
        files_to_upload: list[str] | None = None,
    ):
        super().__init__()
        self.job = job
        self.snapshot = snapshot
        self.jd_client = jd_client
        self.files_to_upload = files_to_upload or []
        self.signals = AutoProcessWorkerSignals()

    # ------------------------------------------------------------------
    def _emit(
        self,
        op_type: OpType,
        stage: OpStage,
        msg: str,
        progress: int = 0,
        host: str = "-",
        speed: float = 0.0,
        eta: float = 0.0,
        errors: int = 0,
    ) -> None:
        """Helper to emit a progress update."""

        op = OperationStatus(
            section=self.snapshot.category,
            item=self.snapshot.title,
            op_type=op_type,
            stage=stage,
            message=msg,
            progress=progress,
            host=host,
            speed=speed,
            eta=eta,
            errors=errors,
        )
        self.signals.progress_update.emit(op)

    # ------------------------------------------------------------------
    def run(self) -> None:  # pragma: no cover - worker logic not unit tested
        logging.info("AutoProcessWorker starting job %s", self.job.job_id)

        try:
            # Download stage -------------------------------------------------
            self._emit(OpType.DOWNLOAD, OpStage.RUNNING, "Downloading")
            if hasattr(self.jd_client, "download"):
                self.jd_client.download(self.snapshot.url, self.snapshot.working_dir)
            else:
                time.sleep(0.1)  # simulate work

            from diagnostics import get_winrar_path
            from core.file_processor import FileProcessor

            try:
                winrar_path = str(get_winrar_path())
            except FileNotFoundError as e:
                self._emit(OpType.PROCESS, OpStage.ERROR, str(e))
                self.signals.error.emit(self.job.job_id, str(e))
                return

            fp = FileProcessor(self.snapshot.working_dir, winrar_path)

            # Extraction ---------------------------------------------------
            self._emit(OpType.PROCESS, OpStage.RUNNING, "Extracting…", progress=10)
            work_dir = Path(self.snapshot.working_dir)
            archive_files = [p for p in work_dir.glob("*") if p.is_file()]
            root_dir = work_dir
            if len(archive_files) == 1 and fp._is_archive_file(archive_files[0]):
                root_dir, _ = fp.extract_and_normalize(
                    archive_files[0], work_dir, getattr(self.snapshot, "thread_id", "")
                )

            # Detect & split -----------------------------------------------
            self._emit(OpType.PROCESS, OpStage.RUNNING, "Detecting book files…", progress=20)
            book_dir, audio_dir, assets = fp.split_embedded_assets(root_dir)
            self._emit(OpType.PROCESS, OpStage.RUNNING, "Splitting…", progress=35)

            # Package ------------------------------------------------------
            archives = fp.package_assets(
                book_dir, audio_dir, self.snapshot.title, assets
            )
            if archives.get("book"):
                self._emit(OpType.PROCESS, OpStage.RUNNING, "RAR (Book)…", progress=55)
            if archives.get("audio"):
                self._emit(OpType.PROCESS, OpStage.RUNNING, "RAR (Audio)…", progress=75)

            # Upload stage -------------------------------------------------
            self._emit(OpType.UPLOAD, OpStage.RUNNING, "Uploading…")
            try:
                tid = getattr(self.snapshot, "thread_id", "")
            except Exception:
                tid = ""
            hosts = ["rapidgator", "ddownload", "katfile", "nitroflare", "mega"]
            links_audio: dict[str, list[str]] = {}
            for host in hosts:
                links_audio[host] = [
                    f"https://{host}.example/{tid}/audio{i+1}"
                    for i, _ in enumerate(archives.get("audio", []))
                ]
            links_book: dict[str, list[str]] = {}
            for host in hosts:
                links_book[host] = [
                    f"https://{host}.example/{tid}/book{i+1}"
                    for i, _ in enumerate(archives.get("book", []))
                ]

            payload = {
                "thread_id": tid,
                "links": {"audio": links_audio, "book": links_book},
                "assets": assets,
            }
            self.signals.result_ready.emit(self.job.job_id, payload)
            self._emit(OpType.POST, OpStage.FINISHED, "Links ready")
            self.signals.finished.emit(self.job.job_id)
            logging.info(
                "AutoProcessWorker finished job %s", self.job.job_id
            )
        except Exception as e:  # pragma: no cover - best effort
            logging.error("AutoProcessWorker error: %s", e)
            self._emit(OpType.POST, OpStage.ERROR, str(e))
            self.signals.error.emit(self.job.job_id, str(e))

