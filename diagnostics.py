import logging
import platform
import shutil
from pathlib import Path
from typing import Optional

try:
    from appdirs import user_data_dir
except Exception:  # pragma: no cover
    from platformdirs import user_data_dir

APP_NAME = "ForumBot"


def run_diagnostics() -> Path:
    """Run startup environment checks and log the results.

    Returns the path to the diagnostics log file.
    """
    base_dir = Path(user_data_dir(APP_NAME, appauthor=False))
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    logger = logging.getLogger("diagnostics")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file)
               for h in logger.handlers):
        logger.addHandler(handler)

    logger.info("=== Diagnostics Start ===")
    logger.info("Python: %s", platform.python_version())
    logger.info("Platform: %s", platform.platform())
    logger.info("Data dir: %s", base_dir)

    try:
        from config.config import load_configuration
        cfg = load_configuration()
        missing = [k for k in ("jd_email", "jd_password") if not cfg.get(k)]
        if missing:
            logger.warning("Missing credentials: %s", ", ".join(missing))
        else:
            logger.info("JDownloader credentials present")
    except Exception as e:
        logger.exception("Failed loading configuration: %s", e)

    chromedriver = shutil.which("chromedriver")
    logger.info("ChromeDriver: %s", chromedriver or "not found")

    java = shutil.which("java")
    logger.info("Java runtime: %s", java or "not found")

    try:
        import selenium  # type: ignore
        logger.info("Selenium: %s", getattr(selenium, '__version__', 'unknown'))
    except Exception:
        logger.warning("Selenium not installed")

    logger.info("=== Diagnostics End ===")
    return log_file


__all__ = ["run_diagnostics"]