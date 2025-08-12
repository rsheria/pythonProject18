from PyQt5.QtCore import QThread, pyqtSignal
import time
import logging

class LinkCheckWorker(QThread):
    progress = pyqtSignal(dict)  # لكل عنصر
    finished = pyqtSignal(list)  # كل النتائج
    error = pyqtSignal(str)

    def __init__(self, jd_client, urls, cancel_event, poll_timeout_sec=60, poll_interval=1.0):
        super().__init__()
        self.jd = jd_client
        self.urls = urls or []
        self.cancel_event = cancel_event
        self.poll_timeout = poll_timeout_sec
        self.poll_interval = poll_interval

    def run(self):
        results = []

        if not self.urls:
            msg = "No URLs to check."
            logging.error("LinkCheckWorker: %s", msg)
            self.error.emit(msg)
            self.finished.emit(results)
            return

        if self.cancel_event.is_set():
            self.finished.emit(results)
            return

        if not self.jd.connect():
            self.error.emit("JDownloader connection failed.")
            self.finished.emit(results)
            return

        # نظف القديم
        self.jd.remove_all_from_linkgrabber()

        if not self.jd.add_links_to_linkgrabber(self.urls):
            self.error.emit("Failed to add links to LinkGrabber.")
            self.finished.emit(results)
            return

        # مهلة صغيرة يبدأ فيها التحليل
        time.sleep(2)

        t0 = time.time()
        last_count = -1
        stable_hits = 0

        while time.time() - t0 < self.poll_timeout:
            if self.cancel_event.is_set():
                self.jd.remove_all_from_linkgrabber()
                self.finished.emit(results)
                return

            items = self.jd.query_links()
            curr_count = len(items)

            if curr_count > 0 and curr_count == last_count:
                stable_hits += 1
            else:
                stable_hits = 0

            logging.debug("LinkCheckWorker: poll count=%d (stable=%d)", curr_count, stable_hits)

            # اعتبرها استقرت لما تثبت مرتين
            if curr_count > 0 and stable_hits >= 2:
                break

            last_count = curr_count
            time.sleep(self.poll_interval)

        items = self.jd.query_links()
        for it in items:
            availability = (it.get("availability") or "").upper()
            if availability not in ("ONLINE", "OFFLINE"):
                availability = "UNKNOWN"
            name = it.get("name") or ""
            host = it.get("host") or ""
            size = it.get("size") or -1
            link_url = it.get("url") or ""
            row = {"url": link_url, "status": availability, "name": name, "host": host, "size": size}
            self.progress.emit(row)
            results.append(row)

        self.jd.remove_all_from_linkgrabber()
        self.finished.emit(results)
