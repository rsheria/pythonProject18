from PyQt5.QtCore import QThread, pyqtSignal
import time

class LinkCheckWorker(QThread):
    progress = pyqtSignal(dict)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jd_client, urls, cancel_event, poll_timeout_sec=20, poll_interval=1.0):
        super().__init__()
        self.jd = jd_client
        self.urls = urls or []
        self.cancel_event = cancel_event
        self.poll_timeout = poll_timeout_sec
        self.poll_interval = poll_interval

    def run(self):
        results = []
        if not self.urls:
            self.finished.emit(results)
            return

        if self.cancel_event.is_set():
            self.finished.emit(results)
            return

        if not self.jd.connect():
            self.error.emit("JDownloader is not connected.")
            self.finished.emit(results)
            return

        self.jd.remove_all_from_linkgrabber()


        if not self.jd.add_links_to_linkgrabber(self.urls):
            self.error.emit("Failed to add links to LinkGrabber.")
            self.finished.emit(results)
            return

        t0 = time.time()
        last_count = -1
        while time.time() - t0 < self.poll_timeout:
            if self.cancel_event.is_set():
                self.jd.remove_all_from_linkgrabber()
                self.finished.emit(results)
                return
            items = self.jd.query_links()
            if items and len(items) == last_count:
                break
            last_count = len(items)
            time.sleep(self.poll_interval)

        items = self.jd.query_links()
        for it in items:
            availability = (it.get("availability") or "").upper()
            if availability not in ("ONLINE", "OFFLINE"):
                availability = "UNKNOWN"
            name = it.get("name") or ""
            host = it.get("host") or ""
            size = it.get("size") or -1
            link_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            d = {"url": link_url, "status": availability, "name": name, "host": host, "size": size}
            self.progress.emit(d)
            results.append(d)

        self.jd.remove_all_from_linkgrabber()
        self.finished.emit(results)