from PyQt5.QtWidgets import QMessageBox


class UINotifier:
    def __init__(self):
        self._suppress_status_popups = False  # mute only during Status Panel pipeline

    def set_suppress_status_popups(self, val: bool):
        self._suppress_status_popups = bool(val)

    def info(self, parent, title, text):
        if self._suppress_status_popups:
            return  # swallow
        QMessageBox.information(parent, title, text)

    def warn(self, parent, title, text):
        if self._suppress_status_popups:
            return
        QMessageBox.warning(parent, title, text)

    def error(self, parent, title, text):
        if self._suppress_status_popups:
            return
        QMessageBox.critical(parent, title, text)


ui_notifier = UINotifier()