import uuid
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit


from PyQt5 import QtCore
import logging
import time
import re
log = logging.getLogger(__name__)
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

_HOST_ALIASES = {
    "rapidgator": "rapidgator.net",
    "nitroflare": "nitroflare.com",
    "ddownload": "ddownload.com",
    "turbobit": "turbobit.net",
}
def _clean_host(h: str) -> str:
    h = (h or "").lower().strip()
    if h.startswith("www."):
        h = h[4:]
    return _HOST_ALIASES.get(h, h)


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
        single_host_mode: bool = True,
        auto_replace: bool = True,
    ):
        super().__init__()
        self.jd = jd_client
        self.direct_urls = list(direct_urls or [])
        self.container_urls = list(container_urls or [])
        # For container runs, only container URLs should be sent to JD.
        self.urls = self.container_urls if self.container_urls else self.direct_urls
        self.visible_scope = visible_scope or {}
        self.cancel_event = cancel_event
        self.poll_timeout = poll_timeout_sec
        self.poll_interval = poll_interval
        self.single_host_mode = single_host_mode
        self.auto_replace = auto_replace
        self.host_priority: list[str] = []
        self.chosen_host: str | None = None
        # Generate a session_id early so logs from the main thread can reference it
        self.session_id: str = uuid.uuid4().hex
        self._start_time: float | None = None
        # {(session_id, group_id): {"container_url": str, "remove_ids": [jd_ids]}}
        self.awaiting_ack: dict[tuple[str, str], dict] = {}
        self._direct_ids: list[str] = []

    def set_host_priority(self, priority_list: list):
        self.host_priority = []
        for h in (priority_list or []):
            if isinstance(h, str):
                self.host_priority.append(_clean_host(h))

        @QtCore.pyqtSlot(int, str, str)
        def ack_replaced(self, row: int, session_id: str, group_id: str):
            """Ack from GUI that the row at *row* has been replaced in the table."""
            if session_id != self.session_id:
                return

            key = (session_id, group_id)
            info = self.awaiting_ack.pop(key, None)
            if not info or info.get("row") != row:
                    return

            remove_ids = info.get("remove_ids") or []
            container_url = info.get("container_url", "")
            try:
                if remove_ids:
                    self.jd.remove_links(remove_ids)
                    log.debug(
                        "JD CLEANUP | session=%s | group=%s | row=%s | removed=%d | container=%s | dur=%.3f",
                        self.session_id,
                        group_id,
                        row,
                        len(remove_ids),
                        canonical_url(container_url),
                        time.monotonic() - self._start_time if self._start_time else 0.0,
                    )
                else:
                    log.debug(
                        "JD CLEANUP | session=%s | group=%s | row=%s | removed=0 | container=%s | dur=%.3f",
                        self.session_id,
                        group_id,
                        row,
                        canonical_url(container_url),
                        time.monotonic() - self._start_time if self._start_time else 0.0,
                    )
            except Exception as e:
                log.warning("remove container links failed: %s", e)

    def run(self):
        self._start_time = time.monotonic()
        self.awaiting_ack.clear()
        self._direct_ids.clear()
        log.debug(
            "FLAGS | session=%s | auto_replace=%s | single_host=%s",
            self.session_id,
            "ON" if self.auto_replace else "OFF",
            "ON" if self.single_host_mode else "OFF",
        )
        log.debug(
            "DETECT | session=%s | direct=%d | containers=%d | dur=%.3f",
            self.session_id,
            len(self.direct_urls),
            len(self.container_urls),
            0.0,
        )
        if self.chosen_host:
            self.chosen_host = _clean_host(self.chosen_host)
            log.debug(
                "CHOSEN HOST | session=%s | host=%s | dur=%.3f",
                self.session_id,
                self.chosen_host,
                0.0,
            )

        if not self.urls:
            msg = "No URLs to check."
            log.error("LinkCheckWorker: %s", msg)
            self.error.emit(msg)
            self.finished.emit({"session_id": self.session_id})
            return

        if self.cancel_event.is_set():
            log.debug(
                "CANCELLED | session=%s | at=start | dur=%.3f",
                self.session_id,
                time.monotonic() - self._start_time,
            )
            self.finished.emit({"session_id": self.session_id})
            return

        if not self.jd.connect():
            self.error.emit("JDownloader connection failed.")
            self.finished.emit({"session_id": self.session_id})
            return

        if not self.jd.add_links_to_linkgrabber(self.urls, start_check=not self.container_urls):
            self.error.emit("Failed to add links to LinkGrabber.")
            self.finished.emit({"session_id": self.session_id})
            return

        sent_direct = [] if self.container_urls else self.direct_urls
        log.debug(
            "JD ENQUEUE | session=%s | direct=%d | containers=%d | dur=%.3f",
            self.session_id,
            len(sent_direct),
            len(self.container_urls),
            time.monotonic() - self._start_time,
        )

        time.sleep(2)

        t0 = time.time()

        # Track stability of poll results when dealing only with direct links
        stable_hits = 0
        last_count: int | None = None
        state = "queued" if self.container_urls else ""
        if self.container_urls:
            log.debug(
                "WAIT POLL | session=%s | status=%s | dur=%.3f",
                self.session_id,
                state,
                time.monotonic() - self._start_time,
            )
        while time.time() - t0 < self.poll_timeout:
            if self.cancel_event.is_set():
                log.debug(
                    "CANCELLED | session=%s | at=poll | dur=%.3f",
                    self.session_id,
                    time.monotonic() - self._start_time,
                )
                self.finished.emit({"session_id": self.session_id})
                return

            items = self.jd.query_links()
            curr_count = len(items)

            if self.container_urls:
                if curr_count == 0 and state == "queued":
                    state = "solving"
                    log.debug(
                        "WAIT POLL | session=%s | status=%s | dur=%.3f",
                        self.session_id,
                        state,
                        time.monotonic() - self._start_time,
                    )
                elif curr_count > 0:
                    if state != "decrypted":
                        state = "decrypted"
                        log.debug(
                            "WAIT POLL | session=%s | status=%s | items=%d | dur=%.3f",
                            self.session_id,
                            state,
                            curr_count,
                            time.monotonic() - self._start_time,
                        )
                    break
            else:
                all_resolved = curr_count > 0 and all(
                    (it.get("availability") or "").upper() in ("ONLINE", "OFFLINE")
                    for it in items
                )
                if curr_count == last_count:
                    stable_hits += 1
                else:
                    stable_hits = 0
                last_count = curr_count
                if stable_hits >= MAX_STABLE_POLLS or all_resolved:
                    log.debug(
                        "WAIT POLL | session=%s | count=%d | stable=%d | dur=%.3f",
                        self.session_id,
                        curr_count,
                        stable_hits,
                        time.monotonic() - self._start_time,
                    )
                    break

                log.debug(
                    "WAIT POLL | session=%s | count=%d | stable=%d | dur=%.3f",
                    self.session_id,
                    curr_count,
                    stable_hits,
                    time.monotonic() - self._start_time,
                )
            time.sleep(self.poll_interval)

        if self.container_urls and state != "decrypted":
            log.warning(
                "WAIT POLL | session=%s | status=timeout | dur=%.3f",
                self.session_id,
                time.monotonic() - self._start_time,
            )

        items = self.jd.query_links() or []

        allowed_direct = {canonical_url(u) for u in self.direct_urls}
        allowed_containers = {canonical_url(u): u for u in self.container_urls}
        scope_hosts = {
            canonical_url(k): {_clean_host(h) for h in v.get("hosts", [])}
            for k, v in (self.visible_scope or {}).items()
        }
        scope_rows = {
            canonical_url(k): v.get("row") for k, v in (self.visible_scope or {}).items()
        }

        def _availability(it):
            a = (it.get("availability") or "").upper()
            return a if a in ("ONLINE", "OFFLINE") else "UNKNOWN"

        def _host_of(it):
            return _clean_host(it.get("host"))

        if not self.container_urls:
            direct_ids = []
            for it in items:
                item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                canon_item = canonical_url(item_url)
                if canon_item not in allowed_direct:
                    continue

                uid = it.get("uuid")
                if uid:
                    direct_ids.append(uid)
            self._direct_ids = direct_ids
            if direct_ids:
                try:
                    self.jd.start_online_check(direct_ids)
                except Exception:
                    pass
                items = self.jd.query_links() or []
            item_map = {it.get("uuid"): it for it in items}
            for uid in direct_ids:
                it = item_map.get(uid)
                if not it:
                    continue
                item_url = (
                    it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                )
                payload = {
                    "type": "status",
                    "session_id": self.session_id,
                    "url": item_url,
                    "status": _availability(it),
                    "scope_hosts": [_host_of(it)],
                }

                self.progress.emit(payload)

                log.debug(
                    "AVAIL RESULT | session=%s | url=%s | status=%s | dur=%.3f",
                    self.session_id,
                    canonical_url(item_url),
                    payload["status"],
                    time.monotonic() - self._start_time,
                )

        else:
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

            selected = []
            check_ids: list[str] = []
            total_groups = len(groups)
            for idx, (container_key, gitems) in enumerate(groups.items(), start=1):
                ccanon = canonical_url(container_key)
                allowed = scope_hosts.get(ccanon, set())
                row_idx = scope_rows.get(ccanon)
                all_hosts = sorted({_host_of(it) for it in gitems})
                if self.single_host_mode:
                    filtered = [it for it in gitems if not allowed or _host_of(it) in allowed]
                    dropped = len(gitems) - len(filtered)
                else:
                    filtered = gitems
                    dropped = 0
                    if not allowed:
                        allowed = {_host_of(it) for it in gitems}
                if allowed:
                    log.debug(
                        "POST FILTER | session=%s | container=%s | kept=%d | dropped=%d | hosts=%s | dur=%.3f",
                        self.session_id,
                        canonical_url(container_key),
                        len(filtered),
                        dropped,
                        sorted(allowed),
                        time.monotonic() - self._start_time,
                    )
                if not filtered:
                    log.debug(
                        "POST FILTER | session=%s | container=%s | dropped_all | hosts=%s | dur=%.3f",
                        self.session_id,
                        canonical_url(container_key),
                        sorted(allowed),
                        time.monotonic() - self._start_time,
                    )
                    continue

                host_map: dict[str, list] = defaultdict(list)
                for it in filtered:
                    host_map[_host_of(it)].append(it)
                if not host_map:
                    continue

                if self.single_host_mode:
                    host = None
                    if self.chosen_host and self.chosen_host in host_map:
                        host = self.chosen_host
                    else:
                        for h in self.host_priority:
                            if h in host_map:
                                host = h
                                break
                        if host is None:
                            host = next(iter(host_map))
                        if self.chosen_host and host != self.chosen_host:
                            log.debug(
                                "HOST FALLBACK | session=%s | preferred=%s | fallback=%s | dur=%.3f",
                                self.session_id,
                                self.chosen_host,
                                host,
                                time.monotonic() - self._start_time,
                            )

                    ordered = host_map.get(host, [])
                    ordered_ids = [it.get("uuid") for it in ordered if it.get("uuid")]
                    all_ids = [it.get("uuid") for it in filtered if it.get("uuid")]
                    oset = set(ordered_ids)
                    remove_ids = [uid for uid in all_ids if uid not in oset]
                    replace = (
                        self.auto_replace
                        and self.single_host_mode
                        and bool(self.host_priority)
                    )
                    kept_count = len(ordered_ids)
                    log.debug(
                        "DECRYPT SUMMARY | session=%s | row=%s | chosen=%s | decrypted=%d | hosts=%s | kept=%d | auto_replace=%s | single_host=%s",
                        self.session_id,
                        row_idx,
                        host,
                        len(gitems),
                        all_hosts,
                        kept_count,
                        "ON" if self.auto_replace else "OFF",
                        "ON" if self.single_host_mode else "OFF",
                    )
                    if not replace:
                        reason = []
                        if not self.auto_replace:
                            reason.append("auto-replace off")
                        if not self.single_host_mode:
                            reason.append("single-host-check off")
                        if reason:
                            log.debug(
                                "REPLACE SKIP | session=%s | row=%s | reason=%s | dur=%.3f",
                                self.session_id,
                                row_idx,
                                ",".join(reason),
                                time.monotonic() - self._start_time,
                            )
                    group_id = uuid.uuid4().hex if replace else ""
                    if replace:
                        self.awaiting_ack[(self.session_id, group_id)] = {
                            "container_url": container_key,
                            "remove_ids": remove_ids,
                            "row": row_idx,
                        }
                    sel = {
                        "container_url": container_key,
                        "host": host,
                        "ordered_ids": ordered_ids,
                        "idx": idx,
                        "total": total_groups,
                        "allowed": sorted(allowed),
                        "row": row_idx,
                        "replace": replace,
                        "group_id": group_id,
                    }
                    selected.append(sel)
                    check_ids.extend(ordered_ids)
                else:
                    ordered: list = []
                    for lst in host_map.values():
                        ordered.extend(lst)
                    ordered_ids = [it.get("uuid") for it in ordered if it.get("uuid")]
                    replace = self.auto_replace and self.single_host_mode
                    kept_count = len(ordered_ids)
                    chosen = _host_of(ordered[0]) if ordered else ""
                    log.debug(
                        "DECRYPT SUMMARY | session=%s | row=%s | chosen=%s | decrypted=%d | hosts=%s | kept=%d | auto_replace=%s | single_host=%s",
                        self.session_id,
                        row_idx,
                        chosen,
                        len(gitems),
                        all_hosts,
                        kept_count,
                        "ON" if self.auto_replace else "OFF",
                        "ON" if self.single_host_mode else "OFF",
                    )
                    if not replace:
                        reason = []
                        if not self.auto_replace:
                            reason.append("auto-replace off")
                        if not self.single_host_mode:
                            reason.append("single-host-check off")
                        if reason:
                            log.debug(
                                "REPLACE SKIP | session=%s | row=%s | reason=%s | dur=%.3f",
                                self.session_id,
                                row_idx,
                                ",".join(reason),
                                time.monotonic() - self._start_time,
                            )
                    group_id = uuid.uuid4().hex if replace else ""
                    if replace:
                        self.awaiting_ack[(self.session_id, group_id)] = {
                            "container_url": container_key,
                            "remove_ids": [],
                            "row": row_idx,
                        }
                    sel = {
                        "container_url": container_key,
                        "host": _host_of(ordered[0]) if ordered else "",
                        "ordered_ids": ordered_ids,
                        "idx": idx,
                        "total": total_groups,
                        "allowed": sorted(allowed or {""}),
                        "row": row_idx,
                        "replace": replace,
                        "group_id": group_id,
                    }
                    selected.append(sel)
                    check_ids.extend(ordered_ids)

            if check_ids:
                try:
                    self.jd.start_online_check(check_ids)
                except Exception:
                    pass
                items = self.jd.query_links() or []
            item_map = {it.get("uuid"): it for it in items}
            for sel in selected:
                ordered_items = [item_map.get(uid) for uid in sel["ordered_ids"] if item_map.get(uid)]
                if not ordered_items:
                    continue
                chosen = ordered_items[0]
                chosen_url = (
                    chosen.get("url")
                    or chosen.get("contentURL")
                    or chosen.get("pluginURL")
                    or ""
                )
                chosen_status = _availability(chosen)
                chosen_alias = chosen.get("name")
                # Emit a status payload so the UI records availability before any replacement
                status_payload = {
                    "type": "status",
                    "session_id": self.session_id,
                    "url": chosen_url,
                    "status": chosen_status,
                    "scope_hosts": [sel["host"]],
                    "row": sel["row"],
                }
                self.progress.emit(status_payload)
                log.debug(
                    "AVAIL RESULT | session=%s | url=%s | status=%s | dur=%.3f",
                    self.session_id,
                    canonical_url(chosen_url),
                    chosen_status,
                    time.monotonic() - self._start_time,
                )

                siblings = []
                for alt in ordered_items[1:]:
                    aurl = (
                        alt.get("url")
                        or alt.get("contentURL")
                        or alt.get("pluginURL")
                        or ""
                    )
                    siblings.append({"url": aurl, "status": _availability(alt)})
                payload = {
                    "type": "container",
                    "container_url": sel["container_url"],
                    "final_url": chosen_url,
                    "chosen": {
                        "url": chosen_url,
                        "status": chosen_status,
                        "host": sel["host"],
                    },
                    "siblings": siblings,
                    "replace": sel["replace"],
                    "session_id": self.session_id,
                    "group_id": sel["group_id"],
                    "total_groups": sel["total"],
                    "idx": sel["idx"],
                    "scope_hosts": sel["allowed"],
                    "row": sel["row"],
                }
                if chosen_alias:
                    payload["chosen"]["alias"] = chosen_alias
                self.progress.emit(payload)
                log.debug(
                    "AVAIL RESULT | session=%s | container=%s | host=%s | status=%s | idx=%d/%d | dur=%.3f",
                    self.session_id,
                    canonical_url(sel["container_url"]),
                    sel["host"],
                    chosen_status,
                    sel["idx"],
                    sel["total"],
                    time.monotonic() - self._start_time,
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