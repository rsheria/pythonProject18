from dataclasses import dataclass, asdict, field
from typing import Dict, Any


@dataclass
class AutoProcessJob:
    """Persistent job state for Auto‑Process pipeline."""
    job_id: str
    thread_id: str
    title: str
    url: str
    category: str = ""
    step: str = "download"
    status: str = "pending"
    retries_left: int = 5
    download_folder: str = ""
    keeplinks_url: str = ""
    uploaded_links: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["uploaded_links"] = dict(self.uploaded_links)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutoProcessJob":
        return cls(**data)