import uuid
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit


from PyQt5 import QtCore
import logging
import time
import re

CONTAINER_HOSTS = {
    "keeplinks.org",
    "kprotector.com",
    "linkvertise",
    "ouo.io",
    "shorte.st",
    "shorteners",
}

RG_RE = re.compile(r"^/file/([A-Za-z0-9]+)")
NF_RE = re.compile(r"^/view/([A-Za-z0-9]+)")
DD_RE = re.compile(r"^/(?:f|file)/([A-Za-z0-9]+)")
TB_RE = re.compile(r"^/([A-Za-z0-9]+)")


def _clean_host(h: str) -> str:
    h = (h or "").lower().strip()
    return h[4:] if h.startswith("www.") else h


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
        if host.endswith("rapidgator.net"):
            m = RG_RE.match(path)
            if m:
                path = f"/file/{m.group(1)}"
        elif host.endswith("nitroflare.com"):
            m = NF_RE.match(path)
            if m:
                path = f"/view/{m.group(1)}"
        elif host.endswith("ddownload.com"):
            m = DD_RE.match(path)
            if m:
                path = f"/{m.group(1)}"
        elif host.endswith("turbobit.net"):
            m = TB_RE.match(path)
            if m:
                path = f"/{m.group(1)}"
        return urlunsplit((sp.scheme.lower(), host, path, "", ""))
    except Exception:
        return (s or "").strip().lower().rstrip("/").removesuffix(".html")


def host_id_key(s: str) -> str:
    if not s:
        return ""
    try:
        sp = urlsplit(s.strip())
        host = _clean_host(sp.hostname or "")
        path = sp.path or ""
        for regex in (RG_RE, NF_RE, DD_RE, TB_RE):
            m = regex.match(path)
            if m:
                return f"{host}|{m.group(1)}"
    except Exception:
        pass
    return ""
class LinkCheckWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(dict)
    finished = QtCore.pyqtSignal(dict)
    error = QtCore.pyqtSignal(str)


    def __init__(self, jd_client, urls, cancel_event, poll_timeout_sec=120, poll_interval=1.0):
        super().__init__()
        self.jd = jd_client
        self.urls = urls or []
        self.cancel_event = cancel_event
        self.poll_timeout = poll_timeout_sec
        self.poll_interval = poll_interval
        self.host_priority = []
        self.session_id = None
        self.awaiting_ack: dict[str, list] = {}
        self._eligible_ids: list = []
        self._direct_ids: list = []

    def set_host_priority(self, priority_list: list):
        self.host_priority = []
        for h in (priority_list or []):
            if isinstance(h, str):
                h = h.strip().lower()
                if h.startswith("www."):
                    h = h[4:]
                self.host_priority.append(h)

    @QtCore.pyqtSlot(str, str)
    def ack_container_updated(self, container_url: str, session_id: str):
        if session_id != self.session_id:
            return

        ids = self.awaiting_ack.pop(container_url, [])
        if ids:
            self._eligible_ids.extend(ids)
            logging.getLogger(__name__).debug(
                "ACK from GUI | container=%s", canonical_url(container_url)
            )

    def run(self):
        log = logging.getLogger(__name__)
        self.session_id = uuid.uuid4().hex
        self.awaiting_ack.clear()
        self._eligible_ids.clear()
        self._direct_ids.clear()

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

        groups = {}
        priority = self.host_priority or []

        for it in items:
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            container_url = it.get("containerURL") or ""
            chost = _clean_host(urlsplit(container_url or item_url).hostname or "")
            is_container = bool(container_url) or chost in CONTAINER_HOSTS
            key = container_url if container_url else item_url
            if is_container:
                groups.setdefault(key, []).append(it)
            else:
                availability = _availability(it)
                uid = it.get("uuid")
                if uid:
                    self._direct_ids.append(uid)
                payload = {
                    "type": "progress",
                    "session": self.session_id,
                    "url": item_url,
                    "status": availability,
                }

                self.progress.emit(payload)

                log.debug(
                    "EMIT status-only | url=%s status=%s",
                    canonical_url(item_url),
                    availability,
                )

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

            jd_ids = [it.get("uuid") for it in gitems if it.get("uuid")]
            self.awaiting_ack[container_key] = jd_ids

            final = selected[0]
            final_url = final.get("url") or final.get("contentURL") or final.get("pluginURL") or ""
            status_first = _availability(final)
            siblings = []
            status_map = {final_url: status_first}
            for it in selected[1:]:

                furl = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                siblings.append(furl)
                status_map[furl] = _availability(it)
            payload = {
                "type": "progress",
                "session": self.session_id,
                "container_url": container_key,
                "final_url": final_url,
                "status": status_first,
                "replace": True,
                "host": chosen_host,
                "siblings": siblings,
                "status_map": status_map,
            }
            self.progress.emit(payload)
            log.debug(
                "EMIT replace | container=%s final=%s status=%s siblings=%d session=%s",
                canonical_url(container_key),
                canonical_url(final_url),
                status_first,
                len(siblings),
                self.session_id,
            )
        # wait for ACKs
        wait_deadline = time.time() + 5.0
        while self.awaiting_ack and not self.cancel_event.is_set() and time.time() < wait_deadline:
            QtCore.QCoreApplication.processEvents()
            time.sleep(0.1)

        remove_ids = self._eligible_ids + self._direct_ids
        removed = 0
        if remove_ids:
            for attempt in range(2):
                try:
                    if self.jd.remove_links(remove_ids):
                        removed = len(remove_ids)
                        break
                except Exception as e:
                    if "400" in str(e) and attempt == 0:
                        time.sleep(0.5)
                        continue
                    log.warning("remove_links failed: %s", e)
                    break
                time.sleep(0.5)
            log.debug(
                "JD.clear: acknowledged, removed %d items for session=%s",
                removed,
                self.session_id,
            )

        for ck in self.awaiting_ack.keys():
            log.debug("No ACK | container=%s -> keeping in JD", ck)

        self.finished.emit({"session": self.session_id})