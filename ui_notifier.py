from typing import Optional, Callable
import logging

class UINotifier:
    def __init__(self):
        self._suppressed = False
        self._sink: Optional[Callable[[str, str, str], None]] = None  # (level, title, text)

    def set_sink(self, sink: Optional[Callable[[str, str, str], None]]):
        """Optional custom sink for routed messages (e.g., log or status panel message area)."""
        self._sink = sink

    def suppress(self, flag: bool):
        self._suppressed = bool(flag)

    def _emit(self, level: str, title: str, text: str):
        if self._suppressed:
            # No modal UI; just log and optionally push to sink
            logging.info("Suppressed %s: %s - %s", level.upper(), title, text)
            if self._sink:
                try:
                    self._sink(level, title, text)
                except Exception:
                    logging.exception("ui_notifier sink failed")
            return
        # If not suppressed, you MAY still show a non-blocking toast if the app has one,
        # but do NOT introduce modal QMessageBox here.
        logging.info("%s: %s - %s", level.upper(), title, text)

    def info(self, title: str, text: str):
        self._emit("info", title, text)

    def warn(self, title: str, text: str):
        self._emit("warning", title, text)

    def error(self, title: str, text: str):
        self._emit("error", title, text)

# singleton
ui_notifier = UINotifier()

class suppress_popups:
    """Context manager to suppress popups within a scope."""
    def __enter__(self):
        ui_notifier.suppress(True)
        return self
    def __exit__(self, exc_type, exc, tb):
        ui_notifier.suppress(False)
        # No swallow of exceptions; normal propagation
        return False