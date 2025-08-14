import logging
import sys
from pathlib import Path
from typing import List, Tuple
from config.config import DATA_DIR


def setup_logging() -> logging.Logger:
    """Configure application wide logging.

    The configuration is applied only once. Subsequent calls return immediately
    leaving the existing configuration untouched. Handlers are cleared before
    being attached to avoid duplication during hot reloads or re‑runs.
    """
    if getattr(setup_logging, "_configured", False):
        return logging.getLogger()

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")

    try:
        stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, errors="replace")
    except Exception:
        stream = sys.stdout
    console = logging.StreamHandler(stream)
    console.setFormatter(fmt)
    console.name = "console"

    log_file = Path(DATA_DIR) / "forum_bot.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.name = "file"

    logger.addHandler(console)
    logger.addHandler(file_handler)

    setup_logging._configured = True
    handler_info: List[Tuple[str, str]] = [
        (h.name or "<unnamed>", h.__class__.__name__) for h in logger.handlers
    ]
    logger.debug("Logging handlers: %s", handler_info)
    return logger