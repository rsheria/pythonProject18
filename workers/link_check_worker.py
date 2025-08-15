import uuid
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

from PyQt5 import QtCore
import logging
import time
import re

# ================================
# Constants & helpers
# ================================
# Known hosts that act purely as container/redirect services. Any URL whose
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

# Number of consecutive polls with an unchanged result set before we give up
# waiting for JDownloader to resolve links when no containers are involved.
MAX_STABLE_POLLS = 5

# Direct hosts canonicalization regexes
RG_RE = re.compile(r"^/file/([A-Za-z0-9]+)")
NF_RE = re.compile(r"^/view/([A-Za-z0-9]+)")
DD_RE = re.compile(r"^/(?:f|file)/([A-Za-z0-9]+)")
TB_RE = re.compile(r"^/([A-Za-z0-9]+)")

# Container path variants (e.g., keeplinks uses /p16/<id> or /p/<id>)
KLP_RE = re.compile(r"^/p\d*/([A-Za-z0-9]+)")

# Host aliases (user might set "rapidgator" or JD may report aliased forms)
_HOST_ALIASES = {
    "rapidgator": "rapidgator.net",
    "rg.to": "rapidgator.net",  # short domain alias seen in JD
    "nitroflare": "nitroflare.com",
    "ddownload": "ddownload.com",
    "turbobit": "turbobit.net",
}

def is_container_host(host: str) -> bool:
    """Return True if *host* is considered a container/redirect service."""
    return (host or "").lower() in CONTAINER_HOSTS


def _clean_host(h: str) -> str:
    h = (h or "").lower().strip()
    if h.startswith("www."):
        h = h[4:]
    return _HOST_ALIASES.get(h, h)


def canonical_url(s: str) -> str:
    """Normalize URL so that semantically identical URLs map to the same key.

    - Lowercase host, strip www.
    - Drop trailing slash / .html
    - Normalize known direct-host paths to stable forms (id extracted).
    - Force https scheme so http/https variants collide.
    - For known container hosts (keeplinks), normalize /pXX/<id> => /p/<id>.
    """
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

        # Containers (keeplinks variants)
        if host.endswith("keeplinks.org"):
            m = KLP_RE.match(path)
            if m:
                path = f"/p/{m.group(1)}"

        # Direct hosts
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
    """Return a stable key host|id for known direct hosts if possible."""
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
        *,
        single_host_mode: bool = True,
        auto_replace: bool = True,
        enable_jd_online_check: bool = True,
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
        self.chosen_host: str | None = None
        self.single_host_mode = bool(single_host_mode)
        self.auto_replace = bool(auto_replace)
        # Allow JD startOnlineCheck by default; failures are handled gracefully
        self.enable_jd_online_check = bool(enable_jd_online_check)

        self.session_id: str | None = None
        # {(session_id, group_id): {"container_url": str, "remove_ids": [jd_ids], "row": int}}
        self.awaiting_ack: dict[tuple[str, str], dict] = {}
        self._direct_ids: list[str] = []

        # session package isolation
        self.package_name: str | None = None
        self.package_uuid: str | None = None

        # summary counters
        self._rows = 0
        self._replaced = 0
        self._c_online = 0
        self._c_offline = 0
        self._c_unknown = 0

    def set_host_priority(self, priority_list: list):
        self.host_priority = []
        for h in (priority_list or []):
            if isinstance(h, str):
                h = h.strip().lower()
                if h.startswith("www."):
                    h = h[4:]
                self.host_priority.append(_HOST_ALIASES.get(h, h))

    @QtCore.pyqtSlot(str, str, str)
    def ack_replaced(self, container_url: str, session_id: str, group_id: str):
        """Ack from GUI that container_url has been replaced in the table."""
        if session_id != self.session_id:
            return
        key = (session_id, group_id)
        info = self.awaiting_ack.pop(key, None)
        if not info:
            return
        ids = info.get("remove_ids", []) or info.get("ids", [])
        if ids:
            try:
                rc = self.jd.remove_links(ids)
                logging.getLogger(__name__).debug(
                    "JD CLEANUP | session=%s | group=%s | rc=%s | removed=%d",
                    session_id,
                    group_id,
                    rc if rc is not None else 200,
                    len(ids),
                )
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "JD remove failed for container=%s: %s", container_url, e
                )

    # ------------------------ internal helpers ------------------------
    def _availability(self, it: dict) -> str:
        a = (it.get("availability") or "").upper()
        if a in ("ONLINE", "OFFLINE"):
            return a
        return "UNKNOWN"

    def _host_of(self, it: dict) -> str:
        return _clean_host(it.get("host"))

    def _pick_best(self, items: list[dict], priority: list[str]) -> tuple[str, list[dict]]:
        hosts: dict[str, list[dict]] = defaultdict(list)
        for it in items:
            hosts[self._host_of(it)].append(it)
        priority_map = {h: i for i, h in enumerate(priority or [])}
        online_hosts: list[tuple[int, str, list[dict]]] = []
        offline_hosts: list[tuple[int, str, list[dict]]] = []
        for h, lst in hosts.items():
            idx = priority_map.get(h, len(priority_map))
            if any(self._availability(x) == "ONLINE" for x in lst):
                online_hosts.append((idx, h, lst))
            else:
                offline_hosts.append((idx, h, lst))
        if online_hosts:
            _idx, host, lst = sorted(online_hosts, key=lambda x: x[0])[0]
        else:
            _idx, host, lst = sorted(offline_hosts, key=lambda x: x[0])[0]
        lst.sort(key=lambda it: {"ONLINE": 0, "OFFLINE": 1, "UNKNOWN": 2}[self._availability(it)])
        return host, lst

    def _safe_start_online_check(self, ids: list[str]):
        """Start online check if enabled and supported; swallow unsupported errors."""
        if not (self.enable_jd_online_check and ids):
            return
        try:
            self.jd.start_online_check(ids)
        except Exception:
            # Silent: device may not expose this endpoint; availability still
            # arrives through queryLinks.
            logging.getLogger(__name__).debug("JD startOnlineCheck not available; skipping")

    def _query_links_scoped(self) -> list[dict]:
        """Query JD for links in this session's package.

        Falls back to an unscoped query if the scoped query either fails due to
        signature mismatch or returns no items.  This guards against JD
        filtering issues where querying by package yields zero results even
        though links exist."""
        try:
            items = self.jd.query_links(package_uuid=self.package_uuid) or []
        except TypeError:
            items = self.jd.query_links() or []
        if not items:
            try:
                items = self.jd.query_links() or []
            except TypeError:
                items = []
        if self.package_uuid is None and items:
            self.package_uuid = items[0].get("packageUUID")
        return items



    # ------------------------------- direct processor -------------------------------
    def _process_direct_batch(self, items: list[dict], allowed_direct: set[str], scope_rows: dict[str, int]) -> None:
        """Process direct-only logic (also used as a safety fallback if containers exist but don't group)."""
        log = logging.getLogger(__name__)

        # Group matched items by their row (canonical direct URL)
        groups: dict[str, list] = defaultdict(list)
        for it in items:
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            key = canonical_url(item_url)
            if key in allowed_direct:
                groups[key].append(it)

        # Fallback: if nothing matched but items exist, attribute all items to
        # the first provided direct URL so we still emit a status.
        if not groups and items and allowed_direct:
            first = next(iter(allowed_direct))
            groups[first] = items[:]
            log.debug(
                "DIRECT FALLBACK | session=%s | using_all_items=%d | allowed=%d",
                self.session_id,
                len(items),
                len(allowed_direct),
            )

        if not groups:
            log.debug(
                "DIRECT FLOW | session=%s | matched=0 | allowed=%d",
                self.session_id,
                len(allowed_direct),
            )
            return

        chosen_by_row: dict[str, dict] = {}
        direct_ids: list[str] = []

        for key, gitems in groups.items():
            host_map: dict[str, list] = defaultdict(list)
            for it in gitems:
                host_map[self._host_of(it)].append(it)

            available_hosts = sorted(host_map.keys())
            picked_host = None
            selected_items: list[dict]
            if self.single_host_mode:
                if self.chosen_host and _clean_host(self.chosen_host) in host_map:
                    picked_host = _clean_host(self.chosen_host)
                else:
                    for h in self.host_priority:
                        if h in host_map:
                            picked_host = h
                            break
                    if picked_host is None and host_map:
                        picked_host = next(iter(host_map))
                if self.chosen_host and picked_host != _clean_host(self.chosen_host):
                    log.debug(
                        "DIRECT HOST FALLBACK | session=%s | preferred=%s | picked=%s",
                        self.session_id,
                        self.chosen_host,
                        picked_host,
                    )
                selected_items = host_map.get(picked_host, [])
            else:
                selected_items = [it for lst in host_map.values() for it in lst]
                picked_host, _ = self._pick_best(selected_items, self.host_priority)

            if not selected_items:
                continue

            first = selected_items[0]
            cid = first.get("uuid")
            if cid:
                direct_ids.append(cid)
            chosen_by_row[key] = {
                "item": first,
                "host": self._host_of(first),
                "available": available_hosts,
                "picked": picked_host,
                "total": len(gitems),
            }

            log.debug(
                "DIRECT SUMMARY | session=%s | row=%s | available_hosts=%s | chosen=%s | kept=1 | total=%d",
                self.session_id,
                scope_rows.get(key),
                available_hosts,
                picked_host,
                len(gitems),
            )

        # Optional JD-side online check (guarded to avoid 404s)
        self._safe_start_online_check(direct_ids)

        # Re-query to fetch availability and emit status with row mapping (if present)
        items_now = self._query_links_scoped()
        item_map = {it.get("uuid"): it for it in items_now}

        for key, info in chosen_by_row.items():
            it = info["item"]
            uid = it.get("uuid")
            it = item_map.get(uid) or it
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            status = self._availability(it)
            row_idx = scope_rows.get(key)
            self.progress.emit(
                {
                    "type": "status",
                    "session_id": self.session_id,
                    "row": row_idx,
                    "url": item_url,
                    "status": status,
                    "scope_hosts": [info["host"]],
                }
            )
            if status == "ONLINE":
                self._c_online += 1
            elif status == "OFFLINE":
                self._c_offline += 1
            else:
                self._c_unknown += 1
            log.debug(
                "AVAIL RESULT | session=%s | row=%s | url=%s | status=%s | dur=%.3f",
                self.session_id,
                row_idx,
                canonical_url(item_url),
                status,
                time.monotonic() - self._start_time,
            )

        if direct_ids:
            try:
                self.jd.remove_links(direct_ids)
            except Exception as e:
                log.warning("remove direct links failed: %s", e)

    # ------------------------------- run -------------------------------
    def run(self):
        log = logging.getLogger(__name__)
        self.session_id = uuid.uuid4().hex
        self.awaiting_ack.clear()
        self._direct_ids.clear()
        self._rows = self._replaced = self._c_online = self._c_offline = self._c_unknown = 0
        self._start_time = time.monotonic()

        # isolate this session in its own package inside JD
        self.package_name = f"lcw_{self.session_id}"
        self.package_uuid = None

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

        # Log flags effective at the start of the run
        log.debug(
            "FLAGS | session=%s | auto_replace=%s | single_host=%s | chosen_host=%s | host_priority=%s | online_check=%s",
            self.session_id,
            "ON" if self.auto_replace else "OFF",
            "ON" if self.single_host_mode else "OFF",
            (self.chosen_host or ""),
            ",".join(self.host_priority),
            "ON" if self.enable_jd_online_check else "OFF",
        )

        start_check = not self.container_urls
        urls_to_add = self.container_urls if self.container_urls else self.direct_urls
        try:
            ok = self.jd.add_links_to_linkgrabber(
                urls_to_add, start_check=start_check, package_name=self.package_name
            )
        except TypeError:
            ok = self.jd.add_links_to_linkgrabber(urls_to_add, start_check=start_check)
        if not ok:
            self.error.emit("Failed to add links to LinkGrabber.")
            self.finished.emit({"session_id": self.session_id})
            return

        log.debug(
            "JD.ADD | direct=%d | containers=%d | package=%s",
            len(self.direct_urls),
            len(self.container_urls),
            self.package_name,
        )

        time.sleep(2)

        # Poll LinkGrabber until items appear / resolve or timeout
        t0 = time.time()
        stable_hits = 0
        last_count: int | None = None
        while time.time() - t0 < self.poll_timeout:
            if self.cancel_event.is_set():
                self.finished.emit({"session_id": self.session_id})
                return

            items = self._query_links_scoped()
            curr_count = len(items)
            all_resolved = curr_count > 0 and all(
                (it.get("availability") or "").upper() in ("ONLINE", "OFFLINE") for it in items
            )

            if not self.container_urls:
                if curr_count == last_count:
                    stable_hits += 1
                else:
                    stable_hits = 0
                last_count = curr_count
                if stable_hits >= MAX_STABLE_POLLS:
                    log.debug("LinkCheckWorker: poll count=%d (stable=%d)", curr_count, stable_hits)
                    break
            log.debug(
                "LinkCheckWorker: poll count=%d%s",
                curr_count,
                f" (stable={stable_hits})" if not self.container_urls else "",
            )
            if all_resolved:
                break
            time.sleep(self.poll_interval)

        items = self._query_links_scoped()

        # Precompute scopes & allowed keys
        allowed_direct = {canonical_url(u) for u in self.direct_urls}
        allowed_containers = {canonical_url(u): u for u in self.container_urls}
        scope_hosts = {canonical_url(k): set(v.get("hosts", [])) for k, v in (self.visible_scope or {}).items()}
        scope_rows = {canonical_url(k): v.get("row") for k, v in (self.visible_scope or {}).items()}

        # -------------------------- direct-only OR safety-fallback --------------------------
        if not self.container_urls:
            self._process_direct_batch(items, allowed_direct, scope_rows)
            log.info(
                "SUMMARY | session=%s | rows=%d | replaced=%d | online=%d | offline=%d | unknown=%d | cancelled=%s | dur=%.3f",
                self.session_id,
                self._rows,
                self._replaced,
                self._c_online,
                self._c_offline,
                self._c_unknown,
                False,
                time.monotonic() - self._start_time,
            )
            self.finished.emit({"session_id": self.session_id})
            return

        # -------------------------- container flow (multi-pass with per-container wait) --------------------------
        pending = {orig for orig in
                   allowed_containers.values()}  # keep ORIGINAL keys (not canonical) to resolve row mapping
        processed = set()
        t_loop0 = time.time()

        # Stall detection across the whole pass
        loops_no_groups = 0

        # Per-container wait limits (don’t emit UNKNOWN too early)
        container_first_seen: dict[str, float] = {}
        container_unknown_hits: dict[str, int] = {}
        UNKNOWN_MAX_POLLS = 8  # consecutive loops allowed while everything is UNKNOWN
        UNKNOWN_MAX_SECS = 30  # or max seconds per container before giving up

        while pending and (time.time() - t_loop0) < self.poll_timeout:
            if self.cancel_event.is_set():
                break

            # Query only our session/package (if jd_client supports it); otherwise returns all LinkGrabber items
            try:
                items = self._query_links_scoped()
            except AttributeError:
                items = self.jd.query_links() or []

            groups: dict[str, list] = defaultdict(list)

            # Group only items that belong to containers still pending
            for it in items:
                item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                container_url = (
                        it.get("containerURL") or it.get("origin") or it.get("pluginURL") or it.get("url") or ""
                )
                chost = _clean_host(urlsplit(container_url or item_url).hostname or "")
                if is_container_host(chost) or bool(it.get("containerURL")):
                    ccanon = canonical_url(container_url)
                    if ccanon in allowed_containers:
                        orig = allowed_containers[ccanon]
                        if orig in pending:
                            groups[orig].append(it)

            # If no groups this loop, try an orphan fallback (only when one pending remains); else count as a stall
            if not groups:
                loops_no_groups += 1

                if len(pending) == 1 and items:
                    sole = next(iter(pending))
                    orphans = []
                    for it in items:
                        c_url = it.get("containerURL") or it.get("origin") or it.get("pluginURL") or it.get("url") or ""
                        ccanon = canonical_url(c_url)
                        # take items that don’t clearly map to another pending container
                        if ccanon not in allowed_containers or allowed_containers.get(ccanon) not in pending:
                            orphans.append(it)
                    if orphans:
                        groups[sole] = orphans
                        loops_no_groups = 0  # progress happened

                # still nothing? check for stall/time budget
                if not groups:
                    if loops_no_groups >= 10 or (time.time() - t_loop0) >= self.poll_timeout:
                        # close all remaining as UNKNOWN (don’t loop forever)
                        for ck in list(pending):
                            row_idx = scope_rows.get(canonical_url(ck))
                            self.progress.emit({
                                "type": "status",
                                "session_id": self.session_id,
                                "row": row_idx,
                                "url": ck,
                                "status": "UNKNOWN",
                            })
                            pending.discard(ck)
                        break

                    time.sleep(self.poll_interval)
                    continue
            else:
                loops_no_groups = 0  # progress

            total_groups = len(groups)

            for container_key, gitems in groups.items():
                if container_key not in pending:
                    continue

                ccanon = canonical_url(container_key)
                allowed = scope_hosts.get(ccanon, set())
                row_idx = scope_rows.get(ccanon)
                all_hosts = sorted({self._host_of(it) for it in gitems})

                # Per-container wait: if everything is still UNKNOWN, give JD a bit more time
                now = time.time()
                known_items = [it for it in gitems if (it.get("availability") or "").upper() in ("ONLINE", "OFFLINE")]
                unknown_items = [it for it in gitems if
                                 (it.get("availability") or "").upper() not in ("ONLINE", "OFFLINE")]

                if container_key not in container_first_seen:
                    container_first_seen[container_key] = now

                if unknown_items and not known_items:
                    # ask JD to check unknowns (if supported)
                    self._safe_start_online_check([it.get("uuid") for it in unknown_items if it.get("uuid")])

                    container_unknown_hits[container_key] = container_unknown_hits.get(container_key, 0) + 1
                    waited_polls = container_unknown_hits[container_key]
                    waited_secs = now - container_first_seen[container_key]

                    log.debug(
                        "WAIT CONTAINER | container=%s | unknown=%d | polls=%d | secs=%.1f",
                        canonical_url(container_key), len(unknown_items), waited_polls, waited_secs
                    )

                    if waited_polls < UNKNOWN_MAX_POLLS and waited_secs < UNKNOWN_MAX_SECS:
                        # don’t process this container yet; try next loop
                        continue
                    # fell through: we’ll proceed and likely emit UNKNOWN (timeout reached)

                # Host filtering (respect single_host_mode + scope)
                if self.single_host_mode:
                    filtered = [it for it in gitems if not allowed or self._host_of(it) in allowed]
                    dropped = len(gitems) - len(filtered)
                else:
                    filtered = gitems
                    dropped = 0
                    if not allowed:
                        allowed = {self._host_of(it) for it in gitems}

                if not filtered:
                    # nothing usable → report UNKNOWN on the row and mark done
                    self.progress.emit({
                        "type": "status",
                        "session_id": self.session_id,
                        "row": row_idx,
                        "url": container_key,
                        "status": "UNKNOWN",
                    })
                    pending.discard(container_key)
                    continue

                # Choose best host
                host_map: dict[str, list] = defaultdict(list)
                for it in filtered:
                    host_map[self._host_of(it)].append(it)

                if self.single_host_mode:
                    if self.chosen_host and _clean_host(self.chosen_host) in host_map:
                        host = _clean_host(self.chosen_host)
                    else:
                        host = None
                        for h in self.host_priority:
                            if h in host_map:
                                host = h
                                break
                        if host is None:
                            host = next(iter(host_map))
                else:
                    host, _ = self._pick_best(filtered, self.host_priority)

                ordered = host_map.get(host, []) if self.single_host_mode else [it for lst in host_map.values() for it
                                                                                in lst]
                ordered_ids = [it.get("uuid") for it in ordered if it.get("uuid")]
                all_ids = [it.get("uuid") for it in filtered if it.get("uuid")]

                replace = self.auto_replace and self.single_host_mode and bool(self.host_priority)

                # Optional JD online-check for remaining UNKNOWNs (guarded)
                unknown_ids = [it.get("uuid") for it in ordered if
                               self._availability(it) == "UNKNOWN" and it.get("uuid")]
                self._safe_start_online_check(unknown_ids)

                # Emit chosen + siblings
                siblings, chosen_status, chosen_url, first_host = [], "UNKNOWN", "", None
                for j, it in enumerate(ordered):
                    url_v = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                    st = self._availability(it)
                    if j == 0:
                        chosen_status = st
                        chosen_url = url_v
                        first_host = self._host_of(it)
                        if st == "ONLINE":
                            self._c_online += 1
                        elif st == "OFFLINE":
                            self._c_offline += 1
                        else:
                            self._c_unknown += 1
                    else:
                        siblings.append({"url": url_v, "status": st})

                # Report container row status (so UI shows something while we replace)
                self.progress.emit({
                    "type": "status",
                    "session_id": self.session_id,
                    "row": row_idx,
                    "url": container_key,
                    "status": chosen_status,
                    "scope_hosts": [first_host] if first_host else [],
                })

                group_id = uuid.uuid4().hex if replace else ""
                if replace:
                    self.awaiting_ack[(self.session_id, group_id)] = {
                        "container_url": container_key,
                        "remove_ids": all_ids,
                        "row": row_idx,
                    }

                # Replace instruction
                self.progress.emit({
                    "type": "container",
                    "container_url": container_key,
                    "final_url": chosen_url,
                    "chosen": {"url": chosen_url, "status": chosen_status, "host": host or ""},
                    "siblings": siblings,
                    "replace": replace,
                    "session_id": self.session_id,
                    "group_id": group_id,
                    "total_groups": total_groups,
                    "idx": 1,  # index within current loop — cosmetic for logs/UI
                    "scope_hosts": sorted(allowed),
                    "row": row_idx,
                })

                if replace:
                    self._rows += 1
                    self._replaced += 1

                # If no replace, tidy up just this container’s items (optional)
                if not replace and all_ids:
                    try:
                        self.jd.remove_links(all_ids)
                    except Exception:
                        pass

                # Done with this container
                pending.discard(container_key)
                processed.add(container_key)

            # still pending? give JD a tick
            if pending:
                time.sleep(self.poll_interval)

        # Auto-cleanup for any pending ACKs to avoid LinkGrabber clutter
        for key, info in list(self.awaiting_ack.items()):
            ids = info.get("remove_ids") or []
            if not ids:
                continue
            try:
                rc = self.jd.remove_links(ids)
                log.debug(
                    "AUTO CLEANUP | session=%s | row=%s | removed=%d | rc=%s",
                    self.session_id,
                    info.get("row"),
                    len(ids),
                    rc if rc is not None else 200,
                )
            except Exception as e:

                log.warning("Auto cleanup failed: %s", e)
        # If both containers and directs were provided, now process the direct URLs
        if self.container_urls and self.direct_urls:
            try:
                ok = self.jd.add_links_to_linkgrabber(
                    self.direct_urls, start_check=True, package_name=self.package_name
                )
            except TypeError:
                ok = self.jd.add_links_to_linkgrabber(self.direct_urls, start_check=True)
            if ok:
                time.sleep(2)
                t0 = time.time()
                stable_hits = 0
                last_count: int | None = None
                while time.time() - t0 < self.poll_timeout:
                    if self.cancel_event.is_set():
                        self.finished.emit({"session_id": self.session_id})
                        return
                    items = self._query_links_scoped()
                    curr_count = len(items)
                    if curr_count == last_count:
                        stable_hits += 1
                    else:
                        stable_hits = 0
                    last_count = curr_count
                    all_resolved = curr_count > 0 and all(
                        (it.get("availability") or "").upper() in ("ONLINE", "OFFLINE")
                        for it in items
                    )
                    if stable_hits >= MAX_STABLE_POLLS or all_resolved:
                        log.debug(
                            "LinkCheckWorker: poll count=%d (stable=%d)",
                            curr_count,
                            stable_hits,
                        )
                        break
                    time.sleep(self.poll_interval)

                items = self._query_links_scoped()
                self._process_direct_batch(items, allowed_direct, scope_rows)
            else:
                log.warning("Failed to add direct links to LinkGrabber in mixed run")


        # Final safety cleanup: remove any leftover links from this session's package
        try:
            remaining = self.jd.query_links(package_uuid=self.package_uuid) or []
        except TypeError:
            remaining = self.jd.query_links() or []
            leftover_ids = [it.get("uuid") for it in remaining if it.get("uuid")]
            if leftover_ids:
                self.jd.remove_links(leftover_ids)
            log.debug(
                "SESSION FINALIZE | session=%s | removed=%d",
                self.session_id,
                len(leftover_ids),
            )
        except Exception as e:
            log.warning("SESSION FINALIZE clear failed: %s", e)

        log.info(
            "SUMMARY | session=%s | rows=%d | replaced=%d | online=%d | offline=%d | unknown=%d | cancelled=%s | dur=%.3f",
            self.session_id,
            self._rows,
            self._replaced,
            self._c_online,
            self._c_offline,
            self._c_unknown,
            False,
            time.monotonic() - self._start_time,
        )

        self.finished.emit({"session_id": self.session_id})
