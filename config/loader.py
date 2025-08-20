from typing import Dict, List

from PyQt5.QtWidgets import QMessageBox

from .config import load_configuration

REQUIRED_KEYS: List[str] = ["jd_email", "jd_password"]


def load_config_with_prompts() -> Dict:
    """Load configuration and show user-friendly error dialogs on failure."""
    try:
        cfg = load_configuration()
    except Exception as e:
        QMessageBox.critical(None, "Configuration Error", str(e))
        raise

    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        QMessageBox.warning(
            None,
            "Missing Credentials",
            "Please set the following in your .env file: " + ", ".join(missing),
        )
    return cfg