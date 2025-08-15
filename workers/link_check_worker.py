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

    # ------------------------------- direct processor -------------------------------
    def _process_direct_batch(self, items: list[dict], allowed_direct: set[str], scope_rows: dict[str, int]) -> None:
        """Process direct-only logic (also used as a safety fallback if containers exist but don't group)."""
        log = logging.getLogger(__name__)

        # Build host map from JD items that correspond to our provided direct URLs.
        matched: list[dict] = []
        for it in items:
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            if canonical_url(item_url) in allowed_direct:
                matched.append(it)

        # If no strict match but we *do* have items (and LinkGrabber is clean per session),
        # assume these items belong to this direct run.
        if not matched and items:
            matched = items[:]
            log.debug(
                "DIRECT FALLBACK | session=%s | using_all_items=%d | allowed=%d",
                self.session_id,
                len(items),
                len(allowed_direct),
            )

        if not matched:
            log.debug(
                "DIRECT FLOW | session=%s | matched=0 | allowed=%d",
                self.session_id,
                len(allowed_direct),
            )
            return

        host_map: dict[str, list] = defaultdict(list)
        for it in matched:
            host_map[self._host_of(it)].append(it)

        available_hosts = sorted(host_map.keys())
        picked_host = None
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

        direct_ids: list[str] = [it.get("uuid") for it in selected_items if it.get("uuid")]

        log.debug(
            "DIRECT SUMMARY | session=%s | available_hosts=%s | chosen=%s | kept=%d | total=%d",
            self.session_id,
            available_hosts,
            picked_host,
            len(direct_ids),
            len(matched),
        )

        # Optional JD-side online check (guarded to avoid 404s)
        self._safe_start_online_check(direct_ids)

        # Re-query to fetch availability and emit status with row mapping (if present)
        items_now = self.jd.query_links(
            package_uuid=self.package_uuid, package_name=self.package_name
        ) or []
        item_map = {it.get("uuid"): it for it in items_now}
        for uid in direct_ids:
            it = item_map.get(uid) or next((x for x in selected_items if x.get("uuid") == uid), None)
            if not it:
                continue
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            status = self._availability(it)
            row_idx = scope_rows.get(canonical_url(item_url))
            self.progress.emit({
                "type": "status",
                "session_id": self.session_id,
                "row": row_idx,
                "url": item_url,
                "status": status,
                "scope_hosts": [self._host_of(it)],
            })
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
        if not self.jd.add_links_to_linkgrabber(
            self.urls, start_check=start_check, package_name=self.package_name
        ):
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

            items = self.jd.query_links(
                package_uuid=self.package_uuid, package_name=self.package_name
            ) or []
            if self.package_uuid is None and items:
                self.package_uuid = items[0].get("packageUUID")
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

        items = self.jd.query_links(
            package_uuid=self.package_uuid, package_name=self.package_name
        ) or []

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

        # -------------------------- container flow --------------------------
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
            is_c = is_container_host(chost) or bool(it.get("containerURL"))
            if is_c:
                ccanon = canonical_url(container_url)
                if ccanon in allowed_containers:
                    orig = allowed_containers[ccanon]
                    groups[orig].append(it)

        # Fallback grouping: if JD returned items but none matched our container keys,
        # attribute all decrypted items to the first requested container. This ensures
        # we still proceed to filter→check→replace.
        if not groups and items and allowed_containers:
            first_container = next(iter(allowed_containers.values()))
            for it in items:
                groups[first_container].append(it)
            log.debug(
                "GROUP FALLBACK | session=%s | container=%s | assigned=%d",
                self.session_id,
                canonical_url(first_container),
                len(items),
            )

        # Safety: If still no groups AND we have direct URLs, process as direct batch
        if not groups and allowed_direct:
            log.debug(
                "GROUP→DIRECT SAFETY | session=%s | containers_present=%d | groups=0 | direct_allowed=%d",
                self.session_id,
                len(self.container_urls),
                len(allowed_direct),
            )
            self._process_direct_batch(items, allowed_direct, scope_rows)
            # fall through to finalize/cleanup below
        else:
            selected: list[dict] = []
            check_ids: list[str] = []
            total_groups = len(groups)
            for idx, (container_key, gitems) in enumerate(groups.items(), start=1):
                ccanon = canonical_url(container_key)
                allowed = scope_hosts.get(ccanon, set())
                row_idx = scope_rows.get(ccanon)
                all_hosts = sorted({self._host_of(it) for it in gitems})

                if self.single_host_mode:
                    filtered = [it for it in gitems if not allowed or self._host_of(it) in allowed]
                    dropped = len(gitems) - len(filtered)
                else:
                    filtered = gitems
                    dropped = 0
                    if not allowed:
                        allowed = {self._host_of(it) for it in gitems}

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
                    log.debug(
                        "REPLACE SKIP | session=%s | row=%s | reason=kept_count=0 | dur=%.3f",
                        self.session_id,
                        row_idx,
                        time.monotonic() - self._start_time,
                    )
                    continue

                host_map: dict[str, list] = defaultdict(list)
                for it in filtered:
                    host_map[self._host_of(it)].append(it)
                if not host_map:
                    continue

                chosen_count = len(host_map.get(_clean_host(self.chosen_host), [])) if self.chosen_host else 0
                log.debug(
                    "DECRYPT CHOSEN | session=%s | row=%s | chosen=%s | hosts=%s | kept=%d",
                    self.session_id,
                    row_idx,
                    self.chosen_host,
                    all_hosts,
                    chosen_count,
                )

                host = None
                if self.single_host_mode:
                    if self.chosen_host and _clean_host(self.chosen_host) in host_map:
                        host = _clean_host(self.chosen_host)
                    else:
                        for h in self.host_priority:
                            if h in host_map:
                                host = h
                                break
                        if host is None:
                            host = next(iter(host_map))
                        if self.chosen_host and host != _clean_host(self.chosen_host):
                            log.debug(
                                "HOST FALLBACK | session=%s | preferred=%s | fallback=%s | dur=%.3f",
                                self.session_id,
                                self.chosen_host,
                                host,
                                time.monotonic() - self._start_time,
                            )
                else:
                    # Not single-host mode → take all but still prefer the first priority for chosen summary
                    host, _ = self._pick_best(filtered, self.host_priority)

                ordered = host_map.get(host, []) if self.single_host_mode else [it for lst in host_map.values() for it in lst]
                ordered_ids = [it.get("uuid") for it in ordered if it.get("uuid")]
                all_ids = [it.get("uuid") for it in filtered if it.get("uuid")]

                replace = self.auto_replace and self.single_host_mode and bool(self.host_priority)
                kept_count = len(ordered_ids)
                log.debug(
                    "DECRYPT SUMMARY | session=%s | row=%s | chosen=%s | decrypted=%d | hosts=%s | kept=%d | auto_replace=%s | single_host=%s",
                    self.session_id,
                    row_idx,
                    host if host else "",
                    len(gitems),
                    all_hosts,
                    kept_count,
                    "ON" if self.auto_replace else "OFF",
                    "ON" if self.single_host_mode else "OFF",
                )

                reason = None
                if kept_count == 0:
                    replace = False
                    reason = "kept_count=0"
                elif not replace:
                    parts = []
                    if not self.auto_replace:
                        parts.append("auto-replace-container=OFF")
                    if not self.single_host_mode:
                        parts.append("single-host-check=OFF")
                    if not self.host_priority:
                        parts.append("host-priority=EMPTY")
                    if parts:
                        reason = ",".join(parts)
                if reason:
                    log.debug(
                        "REPLACE SKIP | session=%s | row=%s | reason=%s | dur=%.3f",
                        self.session_id,
                        row_idx,
                        reason,
                        time.monotonic() - self._start_time,
                    )

                group_id = uuid.uuid4().hex if replace else ""
                if replace:
                    self.awaiting_ack[(self.session_id, group_id)] = {
                        "container_url": container_key,
                        "remove_ids": all_ids,
                        "row": row_idx,
                    }

                ordered_ids = [it.get("uuid") for it in ordered if it.get("uuid")]
                # Trigger JD availability check for selected items (synchronous in tests)
                self._safe_start_online_check(ordered_ids)
                siblings = []
                chosen_status = "UNKNOWN"
                chosen_url = ""
                first_host = None
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

                # Emit status for the container URL before replacement
                self.progress.emit({
                    "type": "status",
                    "session_id": self.session_id,
                    "row": row_idx,
                    "url": container_key,
                    "status": chosen_status,
                    "scope_hosts": [first_host] if first_host else [],
                })

                # Emit container replacement instruction (row included)
                payload = {
                    "type": "container",
                    "container_url": container_key,
                    "final_url": chosen_url,
                    "chosen": {
                        "url": chosen_url,
                        "status": chosen_status,
                        "host": host or "",
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
                self.progress.emit(payload)
                log.debug(
                    "EMIT container (scoped) | row=%s | container_url=%s chosen=%s/%s idx=%d/%d scope_hosts=%s",
                    row_idx,
                    canonical_url(container_key),
                    host or "",
                    chosen_status,
                    idx,
                    total_groups,
                    sorted(allowed),
                )

                if replace:
                    self._rows += 1
                    self._replaced += 1

                check_ids.extend(ordered_ids)

            # Final JD-side check for all selected ids (guarded)
            self._safe_start_online_check(check_ids)

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
                log.warning("AUTO CLEANUP failed for container=%s: %s", info.get("container_url"), e)
        self.awaiting_ack.clear()

        # Final safety cleanup: remove any leftover links from this session's package
        try:
            remaining = self.jd.query_links(
                package_uuid=self.package_uuid, package_name=self.package_name
            ) or []
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
