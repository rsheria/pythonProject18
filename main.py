from config.config import DATA_DIR
# main.py

import os
from dotenv import load_dotenv

# 1) حمِّل المتغيّرات من .env قبل أي كود تاني
load_dotenv()   # بيفضّي os.environ بكل القيم من ملف .env

# 2) تأكّد إن مسار .env صحيح (لو مش في نفس المجلد ممكن تحدد مساره الكامل)
# from pathlib import Path
# dotenv_path = Path(__file__).parent / '.env'
# load_dotenv(dotenv_path=dotenv_path)

# 3) تأكيد بسيط
print("KEEPLINKS_API_HASH =", os.getenv('KEEPLINKS_API_HASH'))

# 4) بقية الاستيرادات
from downloaders.base_downloader import BaseDownloader
print("✅ downloaders package loaded, BaseDownloader =", BaseDownloader)

import sys
import logging
from PyQt5.QtWidgets import QApplication

# استيراد دوال التكوين من مجلّد config
from config.config import load_configuration
# استيراد الواجهة من مجلّد gui
from gui.main_window import ForumBotGUI

def global_exception_handler(exctype, value, traceback):
    logging.critical("Unhandled exception:", exc_info=(exctype, value, traceback))
    sys.__excepthook__(exctype, value, traceback)

# ثبتّ معالج الأخطاء العام
sys.excepthook = global_exception_handler


def main():
    # إعداد اللوجينج
    logging.basicConfig(
        filename=os.path.join(DATA_DIR, 'main.log'),
        level=logging.DEBUG,
        format='%(asctime)s:%(levelname)s:%(message)s'
    )
    logging.info("Application started.")

    # إنشاء تطبيق Qt
    app = QApplication(sys.argv)

    # 5) حمل التكوين (يقرأ من os.environ بعد load_dotenv)
    try:
        config = load_configuration()
        logging.info("Configuration loaded successfully.")
    except Exception as e:
        logging.critical(f"Configuration Error: {e}", exc_info=True)
        print(f"Configuration Error: {e}")
        sys.exit(1)

    # 6) شغّل الواجهة
    try:
        gui = ForumBotGUI(config)
        gui.run()
    except Exception as e:
        logging.critical(f"Failed to initialize ForumBotGUI: {e}", exc_info=True)
        print(f"Failed to initialize ForumBotGUI: {e}")
        sys.exit(1)

    logging.info("Application exited gracefully.")
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
