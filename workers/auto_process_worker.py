import logging
import time
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

            # Upload stage ---------------------------------------------------
            logging.info(
                "AutoProcessWorker uploading from %s with %d files",
                self.snapshot.working_dir,
                len(self.files_to_upload),
            )
            hosts = ["RG", "DDL", "KF", "NF", "RG_BAK"]
            for host in hosts:
                self._emit(OpType.UPLOAD, OpStage.RUNNING, f"Uploading to {host}", host=host)
                time.sleep(0.05)

            # Post stage -----------------------------------------------------
            self._emit(OpType.POST, OpStage.RUNNING, "Posting")
            # Build a canonical mapping for uploaded links similar to UploadWorker
            canonical: dict[str, dict] = {}
            # Generate dummy URLs per host for simulation
            # Note: hosts = ["RG", "DDL", "KF", "NF", "RG_BAK"]
            try:
                tid = self.snapshot.thread_id
            except Exception:
                tid = ""
            # Rapidgator main
            rg_url = f"https://rg.example/{tid}"
            canonical['rapidgator.net'] = {
                'urls': [rg_url],
                'is_backup': False,
            }
            # DDownload
            ddl_url = f"https://ddl.example/{tid}"
            canonical['ddownload.com'] = {'urls': [ddl_url]}
            # Katfile
            kf_url = f"https://kf.example/{tid}"
            canonical['katfile.com'] = {'urls': [kf_url]}
            # Nitroflare
            nf_url = f"https://nf.example/{tid}"
            canonical['nitroflare.com'] = {'urls': [nf_url]}
            # Rapidgator backup
            rg_bak_url = f"https://rgbak.example/{tid}"
            canonical['rapidgator-backup'] = {
                'urls': [rg_bak_url],
                'is_backup': True,
            }
            # Keeplinks
            keeplinks_url = f"https://keeplinks.example/{tid}"
            canonical['keeplinks'] = keeplinks_url
            payload = {
                'thread_id': tid,
                'uploaded_links': canonical,
                'keeplinks': keeplinks_url,
            }
            self.signals.result_ready.emit(self.job.job_id, payload)
            self._emit(OpType.POST, OpStage.FINISHED, "Finished")
            self.signals.finished.emit(self.job.job_id)
            logging.info(
                "AutoProcessWorker finished job %s", self.job.job_id
            )
        except Exception as e:  # pragma: no cover - best effort
            logging.error("AutoProcessWorker error: %s", e)
            self._emit(OpType.POST, OpStage.ERROR, str(e))
            self.signals.error.emit(self.job.job_id, str(e))

