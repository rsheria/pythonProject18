from __future__ import annotations

from pathlib import Path
from typing import List
import logging


def scan_thread_dir(thread_dir: Path, known_files: List[str]) -> List[str]:
    """Return ``known_files`` plus any files found under ``thread_dir``.

    The scan is recursive so that assets extracted into nested directories are
    captured as well.  Non-file entries are ignored and errors are logged at the
    debug level only.
    """
    new_files = list(known_files)
    try:
        for f in Path(thread_dir).rglob("*"):
            if f.is_file():
                fp = str(f)
                if fp not in new_files:
                    new_files.append(fp)
    except Exception as e:  # pragma: no cover - best effort
        logging.debug(f"Thread dir scan failed: {e}")
    return new_files
