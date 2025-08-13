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

        default_priority = [
            "rapidgator",
            "ddownload",
            "nitroflare",
            "mega",
            "1fichier",
            "gofile",
            "uploaded",
            "mediafire",
        ]

        def availability_rank(a):
            a = (a or "").upper()
            return 0 if a == "ONLINE" else (1 if a == "OFFLINE" else 2)

        # Group items by container key: prefer containerURL > contentURL > origin/pluginURL > url
        groups = {}

        for it in items:
            key = (
                it.get("containerURL")
                or it.get("contentURL")
                or it.get("origin")
                or it.get("pluginURL")
                or it.get("url")
                or ""
            )
            groups.setdefault(key, []).append(it)
        log = logging.getLogger(__name__)
        results = []
        for key, group in groups.items():
            priority_list = self.host_priority or default_priority
            best = None
            for pref in priority_list:
                matches = [it for it in group if pref in (it.get("host") or "").lower()]
                if matches:
                    best = sorted(matches, key=lambda it: availability_rank(it.get("availability")))[0]
                    break
            if best is None:
                best = group[0]
            gui_url = key
            final_url = (
                best.get("url")
                or best.get("contentURL")
                or best.get("pluginURL")
                or None
            )
            availability = (best.get("availability") or "").upper()
            if availability not in ("ONLINE", "OFFLINE"):
                availability = "UNKNOWN"
                replace = bool(final_url and final_url != gui_url)

                payload = {
                "type": "progress",
                "gui_url": gui_url,
                "url": gui_url,
                "final_url": final_url,
                "status": availability if availability in ("ONLINE", "OFFLINE") else "OFFLINE",
                "replace": replace,
            }
            alias = best.get("name") or best.get("host")
            if alias:
                payload["alias"] = alias

            if replace:
                log.debug(
                    "EMIT replace: gui_url=%s -> final_url=%s status=%s",
                    gui_url,
                    final_url,
                    payload["status"],
                )

            self.progress.emit(payload)
            results.append(payload)

        self.jd.remove_all_from_linkgrabber()
        self.finished.emit(results)
