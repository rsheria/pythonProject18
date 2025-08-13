from PyQt5.QtCore import QThread, pyqtSignal
import time
import logging

class LinkCheckWorker(QThread):
    progress = pyqtSignal(dict)  # لكل عنصر
    finished = pyqtSignal(list)  # كل النتائج
    error = pyqtSignal(str)

    def __init__(self, jd_client, urls, cancel_event, poll_timeout_sec=120, poll_interval=1.0):
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

            all_resolved = curr_count > 0 and all((it.get("availability") or "").upper() in ("ONLINE", "OFFLINE") for it in items)

            if curr_count > 0 and curr_count == last_count:
                stable_hits += 1
            else:
                stable_hits = 0

            logging.debug("LinkCheckWorker: poll count=%d (stable=%d)", curr_count, stable_hits)

            # اعتبرها استقرت لما تثبت مرتين
            if all_resolved:
                break

            last_count = curr_count
            time.sleep(self.poll_interval)

        items = self.jd.query_links() or []

        def _clean_host(h):
            h = (h or "").lower().strip()
            return h[4:] if h.startswith("www.") else h

        def _availability(it):
            a = (it.get("availability") or "").upper()
            return a if a in ("ONLINE", "OFFLINE") else "OFFLINE"

        # Group items by container key: prefer containerURL > origin > pluginURL > url
        groups = {}

        for it in items:
            key = (
                    it.get("containerURL")
                    or it.get("origin")
                    or it.get("pluginURL")
                    or it.get("url")
                    or ""
            )
            groups.setdefault(key, []).append(it)

        log = logging.getLogger(__name__)
        results = []

        for key, group in groups.items():
            best = None
            if self.host_priority:
                for pref in self.host_priority:
                    matches = [
                        it for it in group
                        if pref in _clean_host(it.get("host"))
                    ]
                    if matches:
                        online = [it for it in matches if _availability(it) == "ONLINE"]
                        best = online[0] if online else matches[0]
                        break
            if best is None:
                online_all = [it for it in group if _availability(it) == "ONLINE"]
                best = online_all[0] if online_all else group[0]

            gui_url = key
            final_url = (
                    best.get("url")
                    or best.get("contentURL")
                    or best.get("pluginURL")
                    or None
            )

            availability = _availability(best)

            payload = {
                "type": "progress",
                "gui_url": gui_url,
                "url": gui_url,
                "final_url": final_url,
                "status": availability,
                "replace": True,
            }

            alias = best.get("name") or best.get("host")
            if alias:
                payload["alias"] = alias

            log.debug(
                "EMIT replace gui=%s final=%s status=%s",
                gui_url,
                final_url,
                availability,
            )

            self.progress.emit(payload)
            results.append(payload)

        self.jd.remove_all_from_linkgrabber()
        self.finished.emit(results)
