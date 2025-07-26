import logging
import time
from PyQt5.QtCore import QRunnable, QObject, pyqtSignal

from models.job_model import AutoProcessJob
from core.job_manager import JobManager
from core.selenium_bot import ForumBotSelenium


class AutoProcessWorkerSignals(QObject):
    progress = pyqtSignal(str, str)  # job_id, step
    error = pyqtSignal(str, str)     # job_id, message
    finished = pyqtSignal(str)       # job_id


class AutoProcessWorker(QRunnable):
    """Background worker to run Auto‑Process pipeline for one job."""

    def __init__(self, job: AutoProcessJob, bot: ForumBotSelenium, manager: JobManager, gui=None):
        super().__init__()
        self.job = job
        self.bot = bot
        self.manager = manager
        self.gui = gui
        self.signals = AutoProcessWorkerSignals()

    def _update(self, step: str, status: str) -> None:
        self.job.step = step
        self.job.status = status
        self.manager.update_job(self.job)
        self.signals.progress.emit(self.job.job_id, step)

    def _handle_failure(self, message: str) -> bool:
        self.job.retries_left -= 1
        if self.job.retries_left <= 0:
            self.job.status = "error"
            self.manager.update_job(self.job)
            self.signals.error.emit(self.job.job_id, message)
            return False
        # calculate backoff based on retries_left
        attempt = 5 - self.job.retries_left
        delay = [30, 120, 600][min(attempt - 1, 2)]
        time.sleep(delay)
        self.manager.update_job(self.job)
        return True

    def run(self) -> None:
        logging.info("AutoProcessWorker starting job %s", self.job.job_id)
        while self.job.step != "done" and self.job.status != "error":
            step = self.job.step
            success = self.bot.auto_process_job(self.job)
            if success:
                if step == "download":
                    self._update("modify", "running")
                elif step == "modify":
                    self._update("upload", "running")
                elif step == "upload":
                    self._update("keeplinks", "running")
                elif step == "keeplinks":
                    self._update("template", "running")
                elif step == "template":
                    self._update("done", "posted")
                    if self.gui:
                        try:
                            self.gui.apply_auto_process_result(self.job)
                        except Exception as e:
                            logging.error("Failed to apply auto process result: %s", e)
            else:
                if not self._handle_failure(f"failed_{step}"):
                    return
        self.manager.update_job(self.job)
        self.signals.finished.emit(self.job.job_id)
        logging.info("AutoProcessWorker finished job %s", self.job.job_id)