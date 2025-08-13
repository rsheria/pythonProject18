import uuid
from collections import defaultdict
from urllib.parse import urlsplit

from PyQt5 import QtCore
import logging
import time


CONTAINER_HOSTS = {
    "keeplinks.org",
    "kprotector.com",
    "linkvertise",
    "ouo.io",
    "shorte.st",
    "shorteners",
}


class LinkCheckWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(dict)
    finished = QtCore.pyqtSignal(dict)
    error = QtCore.pyqtSignal(str)
    gui_ack = QtCore.pyqtSignal(str, str)  # (session_id, container_key)

    def __init__(self, jd_client, urls, cancel_event, poll_timeout_sec=120, poll_interval=1.0):
        super().__init__()
        self.jd = jd_client
        self.urls = urls or []
        self.cancel_event = cancel_event
        self.poll_timeout = poll_timeout_sec
        self.poll_interval = poll_interval
        self.host_priority = []
        self.session_id = None
        self.pending_containers: dict[str, dict] = {}
        self._group_uuids = defaultdict(list)
        self.gui_ack.connect(self.on_gui_ack, QtCore.Qt.QueuedConnection)

    def set_host_priority(self, priority_list: list):
        self.host_priority = []
        for h in (priority_list or []):
            if isinstance(h, str):
                h = h.strip().lower()
                if h.startswith("www."):
                    h = h[4:]
                self.host_priority.append(h)

    @QtCore.pyqtSlot(str, str)
    def on_gui_ack(self, session_id: str, container_key: str):
        if session_id != self.session_id:
            return
        info = self.pending_containers.get(container_key)
        if not info:
            return
        info["acked"] = True
        uuids = self._group_uuids.get(container_key, [])
        if uuids:
            try:
                self.jd.remove_links(uuids)
                logging.getLogger(__name__).debug(
                    "JD.removeLinks container=%s done", container_key
                )
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "remove_links failed for %s: %s", container_key, e
                )
        self.pending_containers.pop(container_key, None)

    def run(self):
        log = logging.getLogger(__name__)
        self.session_id = uuid.uuid4().hex
        self.pending_containers.clear()
        self._group_uuids.clear()

        if not self.urls:
            msg = "No URLs to check."
            log.error("LinkCheckWorker: %s", msg)
            self.error.emit(msg)
            self.finished.emit({"session": self.session_id})
            return

        if self.cancel_event.is_set():
            self.finished.emit({"session": self.session_id})
            return

        if not self.jd.connect():
            self.error.emit("JDownloader connection failed.")
            self.finished.emit({"session": self.session_id})
            return



        if not self.jd.add_links_to_linkgrabber(self.urls):
            self.error.emit("Failed to add links to LinkGrabber.")
            self.finished.emit({"session": self.session_id})
            return

        time.sleep(2)

        t0 = time.time()
        last_count = -1
        stable_hits = 0

        while time.time() - t0 < self.poll_timeout:
            if self.cancel_event.is_set():
                self.finished.emit({"session": self.session_id})
                return

            items = self.jd.query_links()
            curr_count = len(items)

            all_resolved = curr_count > 0 and all(
                (it.get("availability") or "").upper() in ("ONLINE", "OFFLINE")
                for it in items
            )

            if curr_count > 0 and curr_count == last_count:
                stable_hits += 1
            else:
                stable_hits = 0

            log.debug("LinkCheckWorker: poll count=%d (stable=%d)", curr_count, stable_hits)

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
            return a if a in ("ONLINE", "OFFLINE") else "UNKNOWN"

        def _host_of(it):
            return _clean_host(it.get("host"))

        def pick_host(items, priority):
            hosts = {}
            for it in items:
                hosts.setdefault(_host_of(it), []).append(it)
            for p in priority:
                if p in hosts:
                    return p
            for h, lst in hosts.items():
                if any(_availability(x) == "ONLINE" for x in lst):
                    return h
            return next(iter(hosts.keys()), "")

        def canonical_url(s: str) -> str:
            if not s:
                return ""
            try:
                sp = urlsplit(s.strip())
                host = _clean_host(sp.hostname or "")
                path = sp.path or ""
                if path.endswith("/"):
                    path = path[:-1]
                if path.endswith(".html"):
                    path = path[:-5]
                if host.endswith("rapidgator.net") and path.startswith("/file/"):
                    path = "/file/" + path.split("/")[2]
                elif host.endswith("nitroflare.com") and path.startswith("/view/"):
                    path = "/view/" + path.split("/")[2]
                elif host.endswith("ddownload.com") and (
                    path.startswith("/f/") or path.startswith("/file/")
                ):
                    parts = path.split("/")
                    if len(parts) > 2:
                        path = f"/f/{parts[2]}"
                return urlsplit(
                    f"{sp.scheme.lower()}://{host}{path}"
                ).geturl()
            except Exception:
                return (s or "").strip().lower().rstrip("/").removesuffix(".html")

        groups = {}
        priority = self.host_priority or []

        for it in items:
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            container_url = it.get("containerURL") or ""
            chost = _clean_host(urlsplit(container_url).hostname or "")
            is_container = chost in CONTAINER_HOSTS
            if is_container:
                groups.setdefault(container_url, []).append(it)
            else:
                availability = _availability(it)
                payload = {
                    "type": "progress",
                    "session": self.session_id,
                    "gui_url": item_url,
                    "status": availability,
                    "replace": False,
                }
                log.debug(
                    "EMIT status-only url=%s status=%s", item_url, availability
                )
                self.progress.emit(payload)

        for container_key, gitems in groups.items():
            log.debug(
                "Group for container=%s candidates=%d", container_key, len(gitems)
            )
            chosen_host = pick_host(gitems, priority)
            selected = [it for it in gitems if _host_of(it) == chosen_host]
            if not selected:
                selected = gitems[:]
            selected.sort(
                key=lambda it: {"ONLINE": 0, "OFFLINE": 1, "UNKNOWN": 2}[_availability(it)]
            )

            self._group_uuids[container_key] = [
                it.get("uuid") for it in gitems if it.get("uuid")
            ]
            best_final = (
                selected[0].get("url")
                or selected[0].get("contentURL")
                or selected[0].get("pluginURL")
                or ""
            ) if selected else ""
            self.pending_containers[container_key] = {
                "session": self.session_id,
                "chosen_final": best_final,
                "acked": False,
            }

            total = len(selected) or 1
            if not selected:
                selected = [
                    {"url": None, "availability": "OFFLINE", "name": "", "host": ""}
                ]

            log.debug(
                "Best host=%s availability=%s",
                chosen_host,
                _availability(selected[0]) if selected else "UNKNOWN",
            )

            for idx, it in enumerate(selected, start=1):
                final_url = (
                    it.get("url")
                    or it.get("contentURL")
                    or it.get("pluginURL")
                    or ""
                )
                availability = _availability(it)
                replace = bool(
                    final_url and canonical_url(final_url) != canonical_url(container_key)
                )
                payload = {
                    "type": "progress",
                    "session": self.session_id,
                    "gui_url": container_key,
                    "final_url": final_url,
                    "status": availability,
                    "host": it.get("host") or "",
                    "alias": it.get("name") or "",
                    "name": it.get("name") or "",
                    "replace": replace,
                    "idx": idx,
                    "total": total,
                    "is_last": (idx == total),
                }
                if replace:
                    log.debug(
                        "EMIT replace gui=%s final=%s status=%s idx=%s/%s",
                        container_key,
                        final_url,
                        availability,
                        idx,
                        total,
                    )
                else:
                    log.debug(
                        "EMIT status-only url=%s status=%s",
                        container_key,
                        availability,
                    )
                self.progress.emit(payload)

        self.finished.emit({"session": self.session_id})