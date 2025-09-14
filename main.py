# main.py
# =========
# Central entry‑point for ForumBot

import os
import sys
import logging
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication
from common.logging_setup import setup_logging
from diagnostics import run_diagnostics
from downloaders.base_downloader import BaseDownloader  # noqa: E402

# 🎯 DISABLED STATUS SYSTEM - CAUSING ERRORS
# import gui.magical_status_integration  # DISABLED until fixed

from gui.main_window import ForumBotGUI  # noqa: E402
from config.loader import load_config_with_prompts

setup_logging()
log = logging.getLogger(__name__)
log.info("Logger initialised.")

load_dotenv()
log.info(".env loaded.")

print("KEEPLINKS_API_HASH =", os.getenv('KEEPLINKS_API_HASH'))

print("SUCCESS: downloaders package loaded, BaseDownloader =", BaseDownloader)


def global_exception_handler(exctype, value, traceback):
    log.critical("Unhandled exception:", exc_info=(exctype, value, traceback))
    sys.__excepthook__(exctype, value, traceback)

sys.excepthook = global_exception_handler

def main():
    """Manual Test Plan
    1. direct-only with multiple hosts → only chosen host checked
    2. container with captcha → wait, extract, filter to chosen host, check, replace, persist, restart shows direct link
    3. cancel mid-solve
    4. JD errors handled
    """
    log.info("Application starting…")

    run_diagnostics()
    app = QApplication(sys.argv)

    try:
        config = load_config_with_prompts()
        log.info("Configuration loaded successfully.")
    except Exception as e:
        log.critical("Configuration Error: %s", e, exc_info=True)
        print(f"Configuration Error: {e}")
        sys.exit(1)

    try:
        gui = ForumBotGUI(config)
        gui.run()
    except Exception as e:
        log.critical("Failed to initialise ForumBotGUI: %s", e, exc_info=True)
        print(f"Failed to initialise ForumBotGUI: {e}")
        sys.exit(1)

    log.info("Application exited gracefully.")
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
