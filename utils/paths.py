# paths.py
import os
from pathlib import Path
import sys
def get_data_folder() -> str:
    """Return the directory used to store persistent application data."""

    # Environment variable override takes highest priority
    override = os.getenv("FORUMBOT_DATA_DIR")
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent

    data_dir = base / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)
