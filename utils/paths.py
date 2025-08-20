# paths.py
import os
from pathlib import Path
try:  # Prefer appdirs but fall back to platformdirs if unavailable
    from appdirs import user_data_dir
except Exception:  # pragma: no cover - fallback path
    from platformdirs import user_data_dir


APP_NAME = "ForumBot"
def get_data_folder() -> str:
    """Return the directory used to store persistent application data.

    The location defaults to the per-user app data directory provided by
    ``appdirs`` (e.g. ``%LOCALAPPDATA%/ForumBot`` on Windows).  An optional
    environment variable ``FORUMBOT_DATA_DIR`` can override this location.
    """

    override = os.getenv("FORUMBOT_DATA_DIR")
    if override:
        path = Path(override).expanduser()

    else:
        path = Path(user_data_dir(APP_NAME, appauthor=False))

    path.mkdir(parents=True, exist_ok=True)
    return str(path)
