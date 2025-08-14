# main.py
# =========
# ‑ Central entry‑point for ForumBot
# ‑ Adds dual‑logging: *console*  +  *main.log* (DATA_DIR)
# ‑ Keeps all existing behaviour (dotenv, config‑load, GUI, …)

from config.config import DATA_DIR     # ← DATA_DIR path from your config

# ------------------------------------------------------------------

# ------------------------------------------------------------------
import os, sys, logging
from pathlib import Path
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication


def _configure_logging() -> None:
    log_fmt = '%(asctime)s %(levelname)s %(message)s'
    formatter = logging.Formatter(log_fmt, datefmt='%H:%M:%S')

    # console (PyCharm Run)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG)

    # file  (…/data/main.log)
    logfile = Path(DATA_DIR) / 'main.log'
    logfile.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(logfile, encoding='utf‑8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[console, file_handler],
        force=True               # overrides any previous config
    )

_configure_logging()
logging.info("Logger initialised.")

# ------------------------------------------------------------------
# 2) Load .env before anything reads os.environ
# ------------------------------------------------------------------
load_dotenv()        # reads .env in current working dir
logging.info(".env loaded.")

# ------------------------------------------------------------------
# 3) Quick check (optional prints stay as before)
# ------------------------------------------------------------------
print("KEEPLINKS_API_HASH =", os.getenv('KEEPLINKS_API_HASH'))

# ------------------------------------------------------------------
# 4) Rest of imports that rely on environment variables
# ------------------------------------------------------------------
from downloaders.base_downloader import BaseDownloader       # noqa: E402
from config.config import load_configuration                 # noqa: E402
from gui.main_window import ForumBotGUI                      # noqa: E402

print("✅ downloaders package loaded, BaseDownloader =", BaseDownloader)

# ------------------------------------------------------------------
# 5) Global exception hook → logs critical tracebacks
# ------------------------------------------------------------------
def global_exception_handler(exctype, value, traceback):
    logging.critical("Unhandled exception:", exc_info=(exctype, value, traceback))
    sys.__excepthook__(exctype, value, traceback)

sys.excepthook = global_exception_handler

# ------------------------------------------------------------------
# 6) Main routine
# ------------------------------------------------------------------
def main():
    """Manual Test Plan
    1. direct-only with multiple hosts → only chosen host checked
    2. container with captcha → wait, extract, filter to chosen host, check, replace, persist, restart shows direct link
    3. cancel mid-solve
    4. JD errors handled
    """
    logging.info("Application starting…")

    # Qt application
    app = QApplication(sys.argv)

    # Load configuration
    try:
        config = load_configuration()
        logging.info("Configuration loaded successfully.")
    except Exception as e:
        logging.critical("Configuration Error: %s", e, exc_info=True)
        print(f"Configuration Error: {e}")
        sys.exit(1)

    # Launch GUI
    try:
        gui = ForumBotGUI(config)
        gui.run()
    except Exception as e:
        logging.critical("Failed to initialise ForumBotGUI: %s", e, exc_info=True)
        print(f"Failed to initialise ForumBotGUI: {e}")
        sys.exit(1)

    logging.info("Application exited gracefully.")
    sys.exit(app.exec_())


# ------------------------------------------------------------------
if __name__ == '__main__':
    main()
