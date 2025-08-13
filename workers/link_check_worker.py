import uuid
from collections import defaultdict
from PyQt5 import QtCore
import time
import logging

class LinkCheckWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(dict)  # لكل عنصر
    finished = QtCore.pyqtSignal(dict)  # session info
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
        self._pending = set()
        self._group_uuids = defaultdict(list)
        self._ackd = set()
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
        if container_key not in self._pending:
            return
        self._pending.remove(container_key)
        self._ackd.add(container_key)
        uuids = self._group_uuids.get(container_key, [])
        if uuids:
            try:
                self.jd.remove_links(uuids)
            except Exception as e:
                logging.getLogger(__name__).warning("remove_links failed for %s: %s", container_key, e)
    def run(self):
        log = logging.getLogger(__name__)
        self.session_id = uuid.uuid4().hex
        self._pending.clear()
        self._ackd.clear()
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

            all_resolved = curr_count > 0 and all((it.get("availability") or "").upper() in ("ONLINE", "OFFLINE") for it in items)

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
            return a if a in ("ONLINE", "OFFLINE") else "OFFLINE"

        def _host_of(it):
            return _clean_host(it.get("host"))

        def pick_host(items, priority):
            hosts = {}
            for it in items:
                hosts.setdefault(_host_of(it), []).append(it)
            for p in priority:
                if p in hosts:
                    return p
            return next(iter(hosts.keys()), "")

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

        priority = self.host_priority or []

        for container_key, gitems in groups.items():
            chosen_host = pick_host(gitems, priority)
            selected = [it for it in gitems if _host_of(it) == chosen_host]
            selected.sort(key=lambda it: 0 if _availability(it) == "ONLINE" else 1)

            self._group_uuids[container_key] = [it.get("uuid") for it in selected if it.get("uuid")]
            self._pending.add(container_key)

            total = len(selected)
            if total == 0:
                total = 1
                selected = [{"url": None, "availability": "OFFLINE", "name": "", "host": ""}]

            for idx, it in enumerate(selected, start=1):
                final_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                availability = _availability(it)
                payload = {
                    "type": "progress",
                    "session": self.session_id,
                    "gui_url": container_key,
                    "final_url": final_url,
                    "status": availability,
                    "host": it.get("host") or "",
                    "alias": it.get("name") or "",
                    "name": it.get("name") or "",
                    "replace": True,
                    "idx": idx,
                    "total": total,
                    "is_last": (idx == total),
                }
                log.debug(
                    "EMIT replace gui=%s final=%s status=%s idx=%s/%s",
                    container_key,
                    final_url,
                    availability,
                    idx,
                    total,
                )
                self.progress.emit(payload)

        self.finished.emit({"session": self.session_id})
