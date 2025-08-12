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
        self.host_priority = []

    def set_host_priority(self, priority_list: list):
        self.host_priority = []
        for h in (priority_list or []):
            if isinstance(h, str):
                h = h.strip().lower()
                if h.startswith("www."):
                    h = h[4:]
                self.host_priority.append(h)
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

        items = self.jd.query_links() or []

        def host_rank(h: str) -> int:
            if not self.host_priority:
                return 10**6
            h = (h or "").lower()
            if h.startswith("www."):
                h = h[4:]
            for idx, pref in enumerate(self.host_priority):
                if pref in h:
                    return idx
            return 10**6

        def availability_rank(a):
            a = (a or "").upper()
            return 0 if a == "ONLINE" else (1 if a == "OFFLINE" else 2)

        # Group by packageUUID so keeplinks expansions are evaluated together
        groups = {}

        for it in items:
            key = it.get("packageUUID") or "all"
            groups.setdefault(key, []).append(it)

        results = []
        for key, group in groups.items():
            best = sorted(
                group,
                key=lambda it: (host_rank(it.get("host")), availability_rank(it.get("availability")))
            )[0]
            best_direct_url = best.get("url") or best.get("contentURL") or best.get("pluginURL") or ""
            container_url = best.get("containerURL") or ""
            availability = (best.get("availability") or "").upper()
            if availability not in ("ONLINE", "OFFLINE"):
                availability = "UNKNOWN"
            d = {
                # direct link the user would actually download
                "url": best_direct_url,
                # keeplinks/container url (if any). empty for plain direct links
                "container_url": container_url,
                # convenience: what to use for row matching/display first
                "display_url": container_url or best_direct_url,
                "status": availability,
                "name": best.get("name") or "",
                "host": best.get("host") or "",
                "size": best.get("size") or -1,
                "package": best.get("packageName") or "",
            }
            self.progress.emit(d)
            results.append(d)

        self.jd.remove_all_from_linkgrabber()
        self.finished.emit(results)
