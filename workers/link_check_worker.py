import uuid
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit


from PyQt5 import QtCore
import logging
import time
import re
# Known hosts that act purely as container/redirect services.  Any URL whose
# hostname matches one of these entries will be sent to JDownloader so that the
# real file links can be extracted.
CONTAINER_HOSTS = {
    "keeplinks.org",
    "kprotector.com",
    "linkvertise",
    "ouo.io",
    "shorte.st",
    "shorteners",
}
def is_container_host(host: str) -> bool:
    """Return True if *host* is considered a container/redirect service."""
    return (host or "").lower() in CONTAINER_HOSTS

# Number of consecutive polls with an unchanged result set before we give up
# waiting for JDownloader to resolve links when no containers are involved.

MAX_STABLE_POLLS = 5

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
        # Normalize scheme to https so http/https variants map to the same key
        return urlunsplit(("https", host, path, "", ""))
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

    def __init__(
        self,
        jd_client,
        direct_urls,
        container_urls,
        cancel_event,
        visible_scope=None,
        poll_timeout_sec=120,
        poll_interval=1.0,
    ):
        super().__init__()
        self.jd = jd_client
        self.direct_urls = direct_urls or []
        self.container_urls = container_urls or []
        self.urls = (self.direct_urls + self.container_urls) or []
        self.visible_scope = visible_scope or {}
        self.cancel_event = cancel_event
        self.poll_timeout = poll_timeout_sec
        self.poll_interval = poll_interval
        self.host_priority: list[str] = []
        self.session_id: str | None = None
        # {(session_id, group_id): {"container_url": str, "ids": [jd_ids]}}
        self.awaiting_ack: dict[tuple[str, str], dict] = {}
        self._direct_ids: list[str] = []

    def set_host_priority(self, priority_list: list):
        self.host_priority = []
        for h in (priority_list or []):
            if isinstance(h, str):
                h = h.strip().lower()
                if h.startswith("www."):
                    h = h[4:]
                self.host_priority.append(h)

    @QtCore.pyqtSlot(str, str, str)
    def ack_replaced(self, container_url: str, session_id: str, group_id: str):
        """Ack from GUI that container_url has been replaced in the table."""
        if session_id != self.session_id:
            return

        key = (session_id, group_id)
        info = self.awaiting_ack.pop(key, None)
        if not info:
            return
        ids = info.get("ids", [])
        if ids:
            try:
                self.jd.remove_links(ids)
                logging.getLogger(__name__).debug(
                    "ACK container | container_url=%s -> remove JD",
                    canonical_url(container_url),
                )
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "JD remove failed for container=%s: %s", container_url, e
                )

    def run(self):
        log = logging.getLogger(__name__)
        self.session_id = uuid.uuid4().hex
        self.awaiting_ack.clear()
        self._direct_ids.clear()

        if not self.urls:
            msg = "No URLs to check."
            log.error("LinkCheckWorker: %s", msg)
            self.error.emit(msg)
            self.finished.emit({"session_id": self.session_id})
            return

        if self.cancel_event.is_set():
            self.finished.emit({"session_id": self.session_id})
            return

        if not self.jd.connect():
            self.error.emit("JDownloader connection failed.")
            self.finished.emit({"session_id": self.session_id})
            return



        if not self.jd.add_links_to_linkgrabber(self.urls):
            self.error.emit("Failed to add links to LinkGrabber.")
            self.finished.emit({"session_id": self.session_id})
            return

        log.debug(
            "JD.ADD | direct=%d | containers=%d",
            len(self.direct_urls),
            len(self.container_urls),
        )

        time.sleep(2)

        t0 = time.time()

        # Track stability of poll results when dealing only with direct links
        stable_hits = 0
        last_count: int | None = None
        while time.time() - t0 < self.poll_timeout:
            if self.cancel_event.is_set():
                self.finished.emit({"session_id": self.session_id})
                return

            items = self.jd.query_links()
            curr_count = len(items)

            all_resolved = curr_count > 0 and all(
                (it.get("availability") or "").upper() in ("ONLINE", "OFFLINE")
                for it in items
            )

            if not self.container_urls:
                if curr_count == last_count:
                    stable_hits += 1
                else:
                    stable_hits = 0
                last_count = curr_count
                if stable_hits >= MAX_STABLE_POLLS:
                    log.debug(
                        "LinkCheckWorker: poll count=%d (stable=%d)",
                        curr_count,
                        stable_hits,
                    )
                    break
            log.debug(
                "LinkCheckWorker: poll count=%d%s",
                curr_count,
                f" (stable={stable_hits})" if not self.container_urls else "",
            )
            if all_resolved:
                break

            time.sleep(self.poll_interval)

        items = self.jd.query_links() or []

        allowed_direct = {canonical_url(u) for u in self.direct_urls}
        # Map canonical form -> original URL so we can keep track of the exact
        # container link that was provided by the user interface.
        allowed_containers = {canonical_url(u): u for u in self.container_urls}
        scope_hosts = {
            canonical_url(k): set(v.get("hosts", []))
            for k, v in (self.visible_scope or {}).items()
        }
        # Track row index for each container so the GUI can update the proper
        # table cell without relying on string lookups.
        scope_rows = {
            canonical_url(k): v.get("row") for k, v in (self.visible_scope or {}).items()
        }
        def _availability(it):
            a = (it.get("availability") or "").upper()
            return a if a in ("ONLINE", "OFFLINE") else "UNKNOWN"

        def _host_of(it):
            return _clean_host(it.get("host"))

        def pick_best(items, priority):
            hosts = defaultdict(list)

            for it in items:
                hosts[_host_of(it)].append(it)
            priority_map = {h: i for i, h in enumerate(priority or [])}
            online_hosts = []
            offline_hosts = []
            for h, lst in hosts.items():
                idx = priority_map.get(h, len(priority_map))
                if any(_availability(x) == "ONLINE" for x in lst):
                    online_hosts.append((idx, h, lst))
                else:
                    offline_hosts.append((idx, h, lst))
                if online_hosts:
                    idx, host, lst = sorted(online_hosts, key=lambda x: x[0])[0]
                else:
                    idx, host, lst = sorted(offline_hosts, key=lambda x: x[0])[0]

                lst.sort(
                    key=lambda it: {"ONLINE": 0, "OFFLINE": 1, "UNKNOWN": 2}[_availability(it)]
                )
                return host, lst

        groups: dict[str, list] = defaultdict(list)
        for it in items:
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            container_url = (
                it.get("containerURL")
                or it.get("origin")
                or it.get("pluginURL")
                or it.get("url")
                or ""
            )
            chost = _clean_host(urlsplit(container_url or item_url).hostname or "")
            is_container = is_container_host(chost) or bool(it.get("containerURL"))
            if is_container:
                ccanon = canonical_url(container_url)
                if ccanon in allowed_containers:
                    orig = allowed_containers[ccanon]
                    groups[orig].append(it)
            else:
                canon_item = canonical_url(item_url)
                if canon_item not in allowed_direct:
                    continue
                availability = _availability(it)
                uid = it.get("uuid")
                if uid:
                    self._direct_ids.append(uid)
                payload = {
                    "type": "status",
                    "session_id": self.session_id,
                    "url": item_url,
                    "status": availability,
                    "scope_hosts": [_host_of(it)],
                }

                self.progress.emit(payload)

                log.debug(
                    "EMIT status-only | url=%s status=%s",
                    canonical_url(item_url),
                    availability,
                )

        total_groups = len(groups)
        for idx, (container_key, gitems) in enumerate(groups.items(), start=1):
            ccanon = canonical_url(container_key)
            allowed = scope_hosts.get(ccanon, set())
            row_idx = scope_rows.get(ccanon)
            filtered = [it for it in gitems if not allowed or _host_of(it) in allowed]
            dropped = len(gitems) - len(filtered)
            if allowed:
                log.debug(
                    "SCOPE FILTER | container=%s | kept=%d | dropped=%d | hosts=%s",
                    canonical_url(container_key),
                    len(filtered),
                    dropped,
                    sorted(allowed),
                )
            if not filtered:
                log.debug(
                    "CONTAINER SCOPE FILTERED OUT ALL ITEMS | container=%s | allowed_hosts=%s",
                    canonical_url(container_key),
                    sorted(allowed),
                )
                continue
            host, ordered = pick_best(filtered, self.host_priority)
            # Keep only links from the chosen host so we don't emit other hosts
            ordered = [it for it in ordered if _host_of(it) == host]
            jd_ids = [it.get("uuid") for it in filtered if it.get("uuid")]
            replace = bool(self.host_priority)
            group_id = uuid.uuid4().hex if replace else ""
            if replace:
                self.awaiting_ack[(self.session_id, group_id)] = {
                    "container_url": container_key,
                    "ids": jd_ids,
                }
            elif jd_ids:
                try:
                    self.jd.remove_links(jd_ids)
                except Exception as e:
                    log.warning("remove container links failed: %s", e)

            chosen = ordered[0]
            chosen_url = (
                chosen.get("url")
                or chosen.get("contentURL")
                or chosen.get("pluginURL")
                or ""
            )
            chosen_status = _availability(chosen)
            chosen_alias = chosen.get("name")

            siblings = []
            for alt in ordered[1:]:
                aurl = (
                    alt.get("url")
                    or alt.get("contentURL")
                    or alt.get("pluginURL")
                    or ""
                )
                siblings.append({"url": aurl, "status": _availability(alt)})

            payload = {
                "type": "container",
                "container_url": container_key,
                "final_url": chosen_url,
                "chosen": {
                    "url": chosen_url,
                    "status": chosen_status,
                    "host": host,
                },
                "siblings": siblings,
                "replace": replace,
                "session_id": self.session_id,
                "group_id": group_id,
                "total_groups": total_groups,
                "idx": idx,
                "scope_hosts": sorted(allowed),
                "row": row_idx,
            }
            if chosen_alias:
                payload["chosen"]["alias"] = chosen_alias
            self.progress.emit(payload)
            log.debug(
                "EMIT container (scoped) | container_url=%s chosen=%s/%s idx=%d/%d scope_hosts=%s",
                canonical_url(container_key),
                host,
                chosen_status,
                idx,
                total_groups,
                sorted(allowed),
            )

        if self._direct_ids:
            try:
                self.jd.remove_links(self._direct_ids)
            except Exception as e:
                log.warning("remove direct links failed: %s", e)

        for info in self.awaiting_ack.values():
            log.warning(
                "No ACK | container=%s -> keeping in JD", info.get("container_url")
            )

        self.finished.emit({"session_id": self.session_id})