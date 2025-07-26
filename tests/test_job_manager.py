import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.job_manager import JobManager
from models.job_model import AutoProcessJob


def test_job_persistence(tmp_path):
    path = tmp_path / "jobs.json"
    manager = JobManager(path)
    job = AutoProcessJob(job_id="1", thread_id="10", title="t", url="u")
    manager.add_job(job)

    manager2 = JobManager(path)
    assert "1" in manager2.jobs
    assert manager2.jobs["1"].thread_id == "10"
