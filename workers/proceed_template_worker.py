import logging
from PyQt5.QtCore import QThread, pyqtSignal, QMutexLocker

from models.operation_status import OperationStatus, OpStage, OpType
import templab_manager


class ProceedTemplateWorker(QThread):
    """Worker to apply templates and upload images without blocking the UI."""

    progress_update = pyqtSignal(OperationStatus)
    finished = pyqtSignal(str, str, str)  # category, title, processed bbcode

    def __init__(self, bot, bot_lock, category, title, raw_bbcode, author, links_block):
        super().__init__()
        self.bot = bot
        self.bot_lock = bot_lock
        self.category = category
        self.title = title
        self.raw_bbcode = raw_bbcode
        self.author = author
        self.links_block = links_block

    def run(self):
        status = OperationStatus(
            section="Template",
            item=self.title,
            op_type=OpType.POST,
            host="fastpic.org",
            stage=OpStage.RUNNING,
            message="Applying template",
            progress=0,
        )
        try:
            # Apply template
            bbcode_filled = templab_manager.apply_template(
                self.raw_bbcode,
                self.category,
                self.author,
                thread_title=self.title,
            )
            if "{LINKS}" in bbcode_filled:
                bbcode_filled = bbcode_filled.replace("{LINKS}", self.links_block)
            self.progress_update.emit(status)

            # Upload image via bot
            status.message = "Uploading image"
            status.progress = 50
            self.progress_update.emit(status)
            if self.bot:
                with QMutexLocker(self.bot_lock):
                    processed = self.bot.process_images_in_content(bbcode_filled)
                bbcode_filled = processed
            else:
                logging.warning("⚠️ bot is not available.")

            status.stage = OpStage.FINISHED
            status.message = "Template complete"
            status.progress = 100
            self.progress_update.emit(status)
            self.finished.emit(self.category, self.title, bbcode_filled)
        except Exception as e:
            logging.exception("Proceed template failed")
            status.stage = OpStage.ERROR
            status.message = str(e)
            self.progress_update.emit(status)
            self.finished.emit(self.category, self.title, "")