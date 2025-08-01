import logging
from PyQt5.QtCore import QThread, pyqtSignal

class LoginThread(QThread):
    login_success = pyqtSignal()
    login_failed = pyqtSignal(str)
    login_status = pyqtSignal(str)

    def __init__(self, bot, username, password):
        super().__init__()
        self.bot = bot
        self.username = username
        self.password = password
        self._running = True

    def run(self):
        try:
            self.login_status.emit("Attempting login...")
            self.bot.username = self.username
            self.bot.password = self.password
            success = self.bot.login()
            if success:
                self.login_status.emit("Login successful")
                self.login_success.emit()
            else:
                self.login_status.emit("Login failed")
                self.login_failed.emit("Invalid username or password.")
        except Exception as e:
            logging.error(f"Exception in LoginThread: {e}", exc_info=True)
            self.login_failed.emit(str(e))
        finally:
            self._running = False

    def stop(self):
        self._running = False
