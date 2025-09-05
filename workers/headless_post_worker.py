import logging
import time
from typing import List, Dict, Any

from PyQt5.QtCore import QThread, pyqtSignal, QMutexLocker
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from models.operation_status import OperationStatus, OpStage, OpType


class HeadlessPostWorker(QThread):
    """Post replies using Selenium in a background thread.

    The worker reuses a shared SeleniumBot instance and emits ``OperationStatus``
    updates so that the UI can reflect progress without blocking.  A hard
    minimum gap between posts is enforced to respect forum rate limits.
    """

    progress_update = pyqtSignal(object)
    post_done = pyqtSignal(str, str, bool, str)
    finished = pyqtSignal(int)

    def __init__(self, bot, bot_lock, tasks: List[Dict[str, Any]], min_gap_seconds: int = 30, parent=None):
        super().__init__(parent)
        self.bot = bot
        self.bot_lock = bot_lock
        self.tasks = list(tasks or [])
        self.min_gap = max(30, int(min_gap_seconds or 30))
        self._cancelled = False

    # ------------------------------------------------------------------
    def request_stop(self) -> None:
        self._cancelled = True

    # ------------------------------------------------------------------
    def _label_for_task(self, task: Dict[str, Any]) -> tuple[str, str]:
        tid = ""
        label = ""
        if task.get("thread_id") is not None:
            tid = str(task.get("thread_id"))
            label = task.get("title") or tid
        elif task.get("thread_url"):
            label = task.get("title") or task.get("thread_url")
        if not tid and task.get("thread_url"):
            from urllib.parse import urlparse, parse_qs
            try:
                q = parse_qs(urlparse(task.get("thread_url")).query)
                if "t" in q and q["t"]:
                    tid = str(q["t"][0])
            except Exception:
                pass
        return tid or label or "thread", label or tid or "thread"

    # ------------------------------------------------------------------
    def _perform_post(self, task: Dict[str, Any], tid: str, label: str) -> Dict[str, str]:
        """Execute a single Selenium posting attempt.

        Returns a result dict with keys: ok, final_url, error.
        Emits progress updates for START, SENDING and VERIFY stages but leaves
        the final stage emission to ``post_once`` so that retries don't cause
        duplicate end states in the UI.
        """
        result = {"ok": False, "final_url": "", "error": ""}
        thread_url = task.get("thread_url")
        message = task.get("message_html") or task.get("message") or ""
        subject = task.get("subject") or ""
        if not thread_url and tid:
            thread_url = f"{self.bot.forum_url.rstrip('/')}/showthread.php?t={tid}"
        try:
            with QMutexLocker(self.bot_lock):
                # START ---------------------------------------------------
                self.progress_update.emit(
                    OperationStatus(
                        section="Posting",
                        item=label,
                        op_type=OpType.POST,
                        stage=OpStage.RUNNING,
                        message="Open editor",
                        progress=5,
                        thread_id=tid,
                        host="forum",
                    )
                )
                if not self.bot.safe_navigate(thread_url):
                    result["error"] = "navigation failed"
                    return result
                if hasattr(self.bot, "check_login_status") and not self.bot.check_login_status():
                    result["error"] = "not logged in"
                    return result

                driver = self.bot.driver
                # Gather existing post ids for verification
                existing_ids = {
                    e.get_attribute("id").split("_")[-1]
                    for e in driver.find_elements(By.CSS_SELECTOR, "div[id^='post_message_']")
                }

                wait = WebDriverWait(driver, 15)
                textarea = wait.until(
                    EC.presence_of_element_located((By.NAME, "message"))
                )
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", textarea
                )
                textarea.clear()
                textarea.send_keys(message)

                # SENDING ------------------------------------------------
                self.progress_update.emit(
                    OperationStatus(
                        section="Posting",
                        item=label,
                        op_type=OpType.POST,
                        stage=OpStage.RUNNING,
                        message="Sending...",
                        progress=50,
                        thread_id=tid,
                        host="forum",
                    )
                )

                submit = wait.until(
                    EC.element_to_be_clickable((By.NAME, "sbutton"))
                )
                try:
                    self.bot._remove_overlays()
                except Exception:
                    pass
                submit.click()

                # VERIFY -------------------------------------------------
                self.progress_update.emit(
                    OperationStatus(
                        section="Posting",
                        item=label,
                        op_type=OpType.POST,
                        stage=OpStage.RUNNING,
                        message="Verifying...",
                        progress=90,
                        thread_id=tid,
                        host="forum",
                    )
                )

                def new_post_present(drv):
                    elems = drv.find_elements(By.CSS_SELECTOR, "div[id^='post_message_']")
                    for e in elems:
                        pid = e.get_attribute("id").split("_")[-1]
                        if pid not in existing_ids:
                            return pid
                    return False

                try:
                    post_id = WebDriverWait(driver, 20).until(new_post_present)
                    final_url = f"{self.bot.forum_url.rstrip('/')}/showthread.php?p={post_id}#post{post_id}"
                    result.update({"ok": True, "final_url": final_url})
                except TimeoutException:
                    result["error"] = "verification timeout"
        except WebDriverException as e:
            result["error"] = str(e)
        except Exception as e:  # pragma: no cover - safety net
            result["error"] = str(e)
        return result

    # ------------------------------------------------------------------
    def post_once(self, task: Dict[str, Any]) -> Dict[str, str]:
        tid, label = self._label_for_task(task)
        last = {"ok": False, "final_url": "", "error": ""}
        for attempt in range(2):
            if self._cancelled:
                break
            res = self._perform_post(task, tid, label)
            if res.get("ok"):
                last = res
                break
            last = res
        stage = OpStage.FINISHED if last.get("ok") else OpStage.ERROR
        msg = "Done" if last.get("ok") else f"Error: {last.get('error', 'failed')}"
        self.progress_update.emit(
            OperationStatus(
                section="Posting",
                item=label,
                op_type=OpType.POST,
                stage=stage,
                message=msg,
                progress=100,
                thread_id=tid,
                host="forum",
                final_url=last.get("final_url", ""),
            )
        )
        return {"ok": last.get("ok"), "final_url": last.get("final_url", ""), "error": last.get("error", ""), "thread_id": tid}

    # ------------------------------------------------------------------
    def run(self) -> None:  # pragma: no cover - thread method
        processed = 0
        for task in self.tasks:
            if self._cancelled:
                break
            start = time.monotonic()
            result = self.post_once(task)
            self.post_done.emit(
                result.get("thread_id", ""),
                result.get("final_url", ""),
                result.get("ok"),
                result.get("error", ""),
            )
            processed += 1
            if processed < len(self.tasks) and not self._cancelled:
                elapsed = time.monotonic() - start
                wait = self.min_gap - elapsed
                while wait > 0 and not self._cancelled:
                    time.sleep(min(1, wait))
                    wait -= 1
        self.finished.emit(processed)
