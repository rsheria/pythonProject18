import json
import logging
from pathlib import Path
from typing import Dict

from config.config import DATA_DIR
from models.job_model import AutoProcessJob


class JobManager:
    """Load/save Auto‑Process jobs from DATA_DIR/jobs.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else Path(DATA_DIR) / "jobs.json"
        self.jobs: Dict[str, AutoProcessJob] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                data = json.load(open(self.path, "r", encoding="utf-8"))
                self.jobs = {jid: AutoProcessJob.from_dict(j) for jid, j in data.items()}
            except Exception as e:
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