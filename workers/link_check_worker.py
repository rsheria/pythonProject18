# -*- coding: utf-8 -*-
import logging
import re
import time
import uuid
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from PyQt5 import QtCore

from integrations.jd_client import JDClient


log = logging.getLogger(__name__)

# ======= ثوابت وأدوات =======
CONTAINER_HOSTS = {
    "keeplinks.org",
    "filecrypt.cc",
    "linksafe.me",
    "pastehere.xyz",
}

_HOST_ALIASES = {
    "rg.to": "rapidgator.net",
    "rapidgator": "rapidgator.net",
    "nitroflare": "nitroflare.com",
    "ddownload": "ddownload.com",
    "turbobit": "turbobit.net",
}

RG_RE = re.compile(r"^/file/([A-Za-z0-9]+)")
NF_RE = re.compile(r"^/view/([A-Za-z0-9]+)")
DD_RE = re.compile(r"^/(?:f|file)/([A-Za-z0-9]+)")
TB_RE = re.compile(r"^/([A-Za-z0-9]+)")
KLP_RE = re.compile(r"/p(?:10)?/([a-fA-F0-9]+)")
ROW_KEY_RE = re.compile(r"^row:(\d+)$", re.I)

def _clean_host(host: Optional[str]) -> str:
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return _HOST_ALIASES.get(h, h)

def is_container_host(host: str) -> bool:
    return _clean_host(host) in CONTAINER_HOSTS

def canonical_url(s: str) -> str:
    if not s:
        return ""
    try:
        sp = urlsplit(s.strip())
        host = _clean_host(sp.hostname or "")
        path = sp.path or "/"
        if host == "keeplinks.org":
            m = KLP_RE.search(path)
            if m:
                return f"https://keeplinks.org/p/{m.group(1).lower()}"
        # normalize some file hosts ID in path
        if host == "rapidgator.net":
            m = RG_RE.match(path)
            if m:
                path = f"/file/{m.group(1)}"
        elif host == "nitroflare.com":
            m = NF_RE.match(path)
            if m:
                path = f"/view/{m.group(1)}"
        elif host == "ddownload.com":
            m = DD_RE.match(path)
            if m:
                path = f"/{m.group(1)}"
        elif host == "turbobit.net":
            m = TB_RE.match(path)
            if m:
                path = f"/{m.group(1)}"
        return urlunsplit(("https", host, path.rstrip("/"), "", ""))
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

# ======= الوركر (QThread) =======
class LinkCheckWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(dict)
    finished = QtCore.pyqtSignal(dict)
    error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        jd_client: JDClient,
        direct_urls: Optional[List[str]],
        container_urls: Optional[List[str]],
        cancel_event,
        visible_scope: Optional[Dict] = None,
        poll_timeout_sec: float = 120.0,
        poll_interval: float = 1.0,
        *,
        single_host_mode: bool = True,
        auto_replace: bool = True,
        enable_jd_online_check: bool = False,
    ):
        super().__init__()
        self.jd = jd_client
        self.direct_urls = list(direct_urls or [])
        self.container_urls = list(container_urls or [])
        self.urls = self.direct_urls + self.container_urls
        self.visible_scope = visible_scope or {}
        self.cancel_event = cancel_event

        self.poll_timeout = float(poll_timeout_sec)
        self.poll_interval = float(poll_interval)

        self.single_host_mode = bool(single_host_mode)
        self.auto_replace = bool(auto_replace)
        self.enable_jd_online_check = bool(enable_jd_online_check)

        self.host_priority: List[str] = []
        self.chosen_host: Optional[str] = None

        # runtime state
        self.session_id: Optional[str] = None
        self.awaiting_ack: Dict[Tuple[str, str], dict] = {}
        self._rows = 0
        self._replaced = 0
        self._c_online = 0
        self._c_offline = 0
        self._c_unknown = 0
        self._start_time = 0.0

        # per-row prefs/map
        self._row_prefs: Dict[int, dict] = {}   # row -> {"priority":[...], "chosen_host":str|None, "allowed_hosts":set[str]}
        self._url_to_row: Dict[str, int] = {}   # canonical(url) -> row

    # ======= إعدادات الأولويات =======
    def set_host_priority(self, priority_list: List[str]):
        self.host_priority = []
        for h in (priority_list or []):
            if isinstance(h, str):
                self.host_priority.append(_clean_host(h))

    def set_chosen_host(self, host: Optional[str]):
        self.chosen_host = _clean_host(host or "")

    # ======= ACK من الـGUI لما يتم الاستبدال =======
    @QtCore.pyqtSlot(str, str, str)
    def ack_replaced(self, container_url: str, session_id: str, group_id: str):
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
                log.debug("JD CLEANUP | session=%s | group=%s | rc=%s | removed=%d",
                          session_id, group_id, rc if rc is not None else 200, len(ids))
            except Exception as e:
                log.warning("JD remove failed for container=%s: %s", container_url, e)

    # ======= Helpers =======
    def _availability(self, it: dict) -> str:
        a = (it.get("availability") or "").upper()
        s = (it.get("status") or "").upper()
        if a == "ONLINE" or s in {"ONLINE", "CHECKED"}:
            return "ONLINE"
        if a == "OFFLINE" or s in {"OFFLINE", "FILE_UNAVAILABLE"}:
            return "OFFLINE"
        return "UNKNOWN"

    def _host_of(self, it: dict) -> str:
        url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
        return _clean_host(urlsplit(url).hostname or "")

    def _pick_best_host(self, host_map: Dict[str, List[dict]], *, row_prio: List[str], row_chosen: Optional[str]) -> str:
        # حماية من الفراغ لتجنب StopIteration وقت الكانسل/العدم
        if not host_map:
            return ""
        # 1) chosen_host (row override > global)
        prefer = _clean_host(row_chosen or "") or _clean_host(self.chosen_host or "")
        if prefer and prefer in host_map:
            return prefer
        # 2) row priority then global priority
        prio = [*row_prio] if row_prio else []
        for h in self.host_priority:
            if h not in prio:
                prio.append(h)
        for h in prio:
            if h in host_map:
                return h
        # 3) fallback: أي هوست موجود
        return next(iter(host_map.keys()))

    def _safe_start_online_check(self, ids: List[str]):
        if not (self.enable_jd_online_check and ids):
            return
        try:
            self.jd.start_online_check(ids)
        except Exception:
            log.debug("JD startOnlineStatusCheck not available; skipping")

    # ======= بناء فهرس نطاق الرؤية (اختياري) =======
    def _build_scope_index(self):
        """
        يدعم:
        - visible_scope مفاتيحه URLs أو 'row:<N>'
        بنستخرج:
          self._url_to_row[canon_url] = row
          self._row_prefs[row] = {priority, chosen_host, allowed_hosts}
        """
        url_to_row: Dict[str, int] = {}
        row_prefs: Dict[int, dict] = {}

        for k, v in (self.visible_scope or {}).items():
            if not isinstance(v, dict):
                continue

            m = ROW_KEY_RE.match(str(k))
            if m:
                row = int(m.group(1))
                pref = row_prefs.setdefault(row, {"priority": None, "chosen_host": None, "allowed_hosts": set()})
                # hosts/priority/chosen_host
                for h in (v.get("hosts") or []):
                    hh = _clean_host(h)
                    if hh:
                        pref["allowed_hosts"].add(hh)
                pr = v.get("priority") or None
                if pr:
                    pref["priority"] = [_clean_host(x) for x in pr if isinstance(x, str)]
                ch = v.get("chosen_host")
                if isinstance(ch, str):
                    pref["chosen_host"] = _clean_host(ch)
                for u in (v.get("urls") or v.get("links") or []):
                    cu = canonical_url(u)
                    if cu:
                        url_to_row[cu] = row
                continue

            cu = canonical_url(k)
            row = v.get("row")
            if cu and row is not None:
                url_to_row[cu] = row
                pref = row_prefs.setdefault(row, {"priority": None, "chosen_host": None, "allowed_hosts": set()})
                for h in (v.get("hosts") or []):
                    hh = _clean_host(h)
                    if hh:
                        pref["allowed_hosts"].add(hh)
                pr = v.get("priority") or None
                if pr and pref.get("priority") is None:
                    pref["priority"] = [_clean_host(x) for x in pr if isinstance(x, str)]
                ch = v.get("chosen_host")
                if isinstance(ch, str) and pref.get("chosen_host") is None:
                    pref["chosen_host"] = _clean_host(ch)

        self._url_to_row = url_to_row
        self._row_prefs = row_prefs

    def _get_row_pref(self, row: int) -> Tuple[List[str], Optional[str], List[str]]:
        p = self._row_prefs.get(row) or {}
        prio = p.get("priority") or []
        chosen = p.get("chosen_host")
        allowed = list(p.get("allowed_hosts") or [])
        return prio, chosen, allowed

    # ======= DIRECT: معالجة لكل صف بدون إسقاط هوست غير مُعرّف =======
    def _process_direct_batch(self, items: List[dict], allowed_direct: set) -> None:
        # طابق الـitems مع direct_urls (لو محددة)، لكن لو فاضية هنفحص أي لينك
        matched: List[dict] = []
        for it in items:
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            cu = canonical_url(item_url)
            if not allowed_direct or cu in allowed_direct:
                matched.append(it)
        if not matched:
            log.debug("DIRECT FLOW | session=%s | matched=0 | allowed=%d", self.session_id, len(allowed_direct))
            return

        # جروّب حسب الصف
        row_map: Dict[int, List[dict]] = defaultdict(list)
        for it in matched:
            item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            row = self._url_to_row.get(canonical_url(item_url), -1)
            row_map[row].append(it)

        for row, row_items in row_map.items():
            host_map: Dict[str, List[dict]] = defaultdict(list)
            for it in row_items:
                host_map[self._host_of(it)].append(it)

            if not host_map:
                log.debug("DIRECT SUMMARY (per-row) | session=%s | row=%s | host_map=EMPTY", self.session_id, row)
                continue

            row_prio, row_chosen, allowed_hosts = self._get_row_pref(row)

            # لا نُسقِط أي هوست لو allowed_hosts مش متضمنه — نستعملها كتفضيل فقط
            picked = self._pick_best_host(host_map, row_prio=row_prio, row_chosen=row_chosen)
            if allowed_hosts and picked not in allowed_hosts:
                # لو فيه قائمة مُفضّلة، جرّب أول مُفضّل موجود
                for h in allowed_hosts:
                    if h in host_map:
                        picked = h
                        break

            selected = host_map.get(picked, [])
            ids = [it.get("uuid") for it in selected if it.get("uuid")]

            log.debug(
                "DIRECT SUMMARY (per-row) | session=%s | row=%s | available_hosts=%s | chosen=%s | kept=%d | total=%d",
                self.session_id, row, sorted(host_map.keys()), picked, len(ids), len(row_items)
            )

            self._safe_start_online_check(ids)

            # أبلغ الـGUI بالحالة (لأول عنصر مختار على الأقل)
            now = self.jd.query_links() or []
            imap = {it.get("uuid"): it for it in now}
            for uid in ids:
                it = imap.get(uid) or next((x for x in selected if x.get("uuid") == uid), None)
                if not it:
                    continue
                item_url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                status = self._availability(it)
                self.progress.emit({
                    "type": "status",
                    "session_id": self.session_id,
                    "row": row,
                    "url": item_url,
                    "status": status,
                    "dur": time.monotonic() - self._start_time,
                })
                log.debug("AVAIL RESULT | session=%s | row=%s | url=%s | status=%s | dur=%.3f",
                          self.session_id, row, canonical_url(item_url), status, time.monotonic() - self._start_time)

            # نظّف المختارين
            if ids:
                try:
                    self.jd.remove_links(ids)
                except Exception as e:
                    log.warning("remove direct links failed: %s", e)

    # ======= RUN =======
    def run(self):
        self.session_id = uuid.uuid4().hex
        self.awaiting_ack.clear()
        self._rows = self._replaced = self._c_online = self._c_offline = self._c_unknown = 0
        self._start_time = time.monotonic()

        # لوج نطاق الرؤية
        log.debug("SCOPE START | rows=%d", len(self.visible_scope or {}))
        for k, v in (self.visible_scope or {}).items():
            key = k
            urls = len(v.get("urls") or [])
            hosts = v.get("hosts") or []
            log.debug("SCOPE ROW | key=%s | hosts=%s | urls=%d", key, hosts, urls)

        # اكتشف النوع
        direct_ct = len(self.direct_urls)
        cont_ct = len(self.container_urls)
        self._build_scope_index()

        # DETECT
        log.debug(
            "DETECT | session=%s | direct=%d | containers=%d | chosen_host=%s",
            self.session_id, direct_ct, cont_ct, (self.chosen_host or "")
        )

        # اتصل بـ JD
        if not self.jd.connect():
            self.error.emit("JDownloader connection failed.")
            self.finished.emit({"session_id": self.session_id})
            return

        # نظّف LinkGrabber في بداية الجلسة
        try:
            cleared = self.jd.remove_all_from_linkgrabber()
            log.debug("SESSION RESET | session=%s | linkgrabber_cleared=%s", self.session_id, bool(cleared))
        except Exception as e:
            log.warning("SESSION RESET failed: %s", e)

        # لو اتعمل Cancel بدري
        if self.cancel_event.is_set():
            log.debug("CANCEL REQUEST | session=%s", self.session_id)
            try:
                self.jd.stop_and_clear()
            except Exception:
                pass
            self.finished.emit({"session_id": self.session_id})
            return

        log.debug(
            "FLAGS | session=%s | auto_replace=%s | single_host=%s | chosen_host=%s | host_priority=%s | online_check=%s",
            self.session_id,
            "ON" if self.auto_replace else "OFF",
            "ON" if self.single_host_mode else "OFF",
            (self.chosen_host or ""),
            ",".join(self.host_priority or []),
            "ON" if self.enable_jd_online_check else "OFF",
        )

        # polling helper
        def poll_until_ready(expected_min_items: int = 1) -> List[dict]:
            time.sleep(1.5)
            t0 = time.time()
            stable_hits = 0
            last_count = None
            items: List[dict] = []
            while time.time() - t0 < self.poll_timeout:
                if self.cancel_event.is_set():
                    # إيقاف فوري لـ JD
                    try:
                        self.jd.stop_and_clear()
                    except Exception:
                        pass
                    return []
                cur = self.jd.query_links() or []
                c = len(cur)
                if last_count is None or c != last_count:
                    stable_hits = 0
                else:
                    stable_hits += 1
                last_count = c
                items = cur
                # اكتفى عند ثبات بسيط وعدد كفاية
                if stable_hits >= 2 and c >= expected_min_items:
                    break
                time.sleep(self.poll_interval)
            log.debug("LinkCheckWorker: poll count=%d%s", len(items), f" (stable={stable_hits})")
            return items

        # ======= (1) DIRECT (لو فيه) =======
        allowed_direct = {canonical_url(u) for u in self.direct_urls}
        if self.direct_urls:
            if self.cancel_event.is_set():
                log.debug("CANCEL REQUEST | session=%s", self.session_id)
                try:
                    self.jd.stop_and_clear()
                except Exception:
                    pass
                self.finished.emit({"session_id": self.session_id})
                return

            if not self.jd.add_links_to_linkgrabber(self.direct_urls):
                self.error.emit("Failed to add direct links to LinkGrabber.")
                self.finished.emit({"session_id": self.session_id})
                return
            log.debug("JD.ADD | direct=%d | containers=%d", len(self.direct_urls), 0)

            if self.cancel_event.is_set():
                log.debug("CANCEL REQUEST | session=%s", self.session_id)
                try:
                    self.jd.stop_and_clear()
                except Exception:
                    pass
                self.finished.emit({"session_id": self.session_id})
                return

            items = poll_until_ready(expected_min_items=min(1, len(self.direct_urls)))
            if items:
                self._process_direct_batch(items, allowed_direct)

            try:
                self.jd.remove_all_from_linkgrabber()
            except Exception:
                pass

        # ======= (2) CONTAINERS — بالتتابع بدون تضارب =======
        for idx, container_url in enumerate(self.container_urls, start=1):
            if self.cancel_event.is_set():
                log.debug("CANCEL REQUEST | session=%s", self.session_id)
                try:
                    self.jd.stop_and_clear()
                except Exception:
                    pass
                self.finished.emit({"session_id": self.session_id})
                return

            if not self.jd.add_links_to_linkgrabber([container_url]):
                self.error.emit(f"Failed to add container to LinkGrabber: {container_url}")
                break
            log.debug("JD.ADD | direct=%d | containers=%d", 0, 1)

            if self.cancel_event.is_set():
                log.debug("CANCEL REQUEST | session=%s", self.session_id)
                try:
                    self.jd.stop_and_clear()
                except Exception:
                    pass
                self.finished.emit({"session_id": self.session_id})
                return

            items = poll_until_ready(expected_min_items=1)

            # في التتابع، كل العناصر اللي رجعت دلوقتي تخص الكونتينر ده
            row_idx = self._url_to_row.get(canonical_url(container_url), -1)
            row_prio, row_chosen, allowed_hosts = self._get_row_pref(row_idx)

            # بِنَى خريطة هوست -> عناصر
            host_map: Dict[str, List[dict]] = defaultdict(list)
            for it in (items or []):
                host_map[self._host_of(it)].append(it)

            if not host_map:
                log.debug(
                    "DECRYPT SUMMARY | session=%s | row=%s | host_map=EMPTY (likely cancel/empty container)",
                    self.session_id, row_idx
                )
                try:
                    self.jd.remove_all_from_linkgrabber()
                except Exception:
                    pass
                continue

            # اختَر هوست — نستخدم allowed_hosts كتفضيل فقط
            picked = self._pick_best_host(host_map, row_prio=row_prio, row_chosen=row_chosen)
            if allowed_hosts and picked not in allowed_hosts:
                for h in allowed_hosts:
                    if h in host_map:
                        picked = h
                        break

            selected = host_map.get(picked, []) or []
            selected_ids = [it.get("uuid") for it in selected if it.get("uuid")]
            all_ids = [it.get("uuid") for its in host_map.values() for it in its if it.get("uuid")]

            log.debug(
                "DECRYPT SUMMARY | session=%s | row=%s | chosen=%s | hosts=%s | kept=%d",
                self.session_id, row_idx, picked, sorted(host_map.keys()), len(selected_ids),
            )

            # أرسل حالة أول اختيار + الأشقاء
            chosen_url = ""
            chosen_status = "UNKNOWN"
            # أرسل حالة أول اختيار + الأشقاء
            chosen_url = ""
            chosen_status = "UNKNOWN"
            siblings: List[dict] = []
            if selected:
                first = selected[0]
                chosen_url = first.get("url") or first.get("contentURL") or first.get("pluginURL") or ""
                chosen_status = self._availability(first)
                for it in selected[1:]:
                    siblings.append({
                        "url": it.get("url") or it.get("contentURL") or it.get("pluginURL") or "",
                        "status": self._availability(it),
                    })

                # ابعت ستاتس لأول اختيار
                self.progress.emit({
                    "type": "status",
                    "session_id": self.session_id,
                    "row": row_idx,
                    "url": chosen_url,
                    "status": chosen_status,
                    "dur": time.monotonic() - self._start_time,
                })
                log.debug("AVAIL RESULT | session=%s | row=%s | url=%s | status=%s | dur=%.3f",
                          self.session_id, row_idx, canonical_url(chosen_url), chosen_status,
                          time.monotonic() - self._start_time)

                # (الجديد) ابعت ستاتس برضه لكل الأشقاء، عشان يبان في اللوج ويتحفظوا في الكاش
                for s in siblings:
                    su = (s.get("url") or "").strip()
                    ss = (s.get("status") or "UNKNOWN").upper()
                    if su:
                        self.progress.emit({
                            "type": "status",
                            "session_id": self.session_id,
                            "row": row_idx,
                            "url": su,
                            "status": ss,
                            "dur": time.monotonic() - self._start_time,
                        })

            # تحضير الاستبدال التلقائي (يحترم الـACK)
            group_id = ""
            do_replace = self.auto_replace and bool(selected_ids)
            if do_replace:
                group_id = uuid.uuid4().hex
                self.awaiting_ack[(self.session_id, group_id)] = {
                    "container_url": container_url,
                    "remove_ids": all_ids,  # هنمسح الكل بعد ما الـGUI تأكد
                    "row": row_idx,
                }

            # باكدج للـGUI (نوع=container)
            self.progress.emit({
                "type": "container",
                "container_url": container_url,
                "final_url": chosen_url,
                "chosen": {"url": chosen_url, "status": chosen_status, "host": picked or ""},
                "siblings": siblings,  # ← فيه كل الأجزاء
                "replace": do_replace,  # ← لازم تبقى True علشان يحصل الاستبدال
                "session_id": self.session_id,
                "group_id": group_id,
                "idx": idx,
                "total_groups": len(self.container_urls),
                "row": row_idx,
            })

            # Optional: شغل فحص للأUNKNOWN
            unknown_ids = [it.get("uuid") for it in selected if self._availability(it) == "UNKNOWN" and it.get("uuid")]
            self._safe_start_online_check(unknown_ids)

            # في نهاية الكونتينر ده: نظّف كل حاجة قبل ما تنتقل للي بعده
            try:
                self.jd.remove_all_from_linkgrabber()
                log.debug("SESSION STEP CLEAR | session=%s | idx=%d", self.session_id, idx)
            except Exception:
                pass

        # Auto cleanup لأي pending ACKs (لو الـGUI ما بعتتش ACK لأي سبب)
        for key, info in list(self.awaiting_ack.items()):
            ids = info.get("remove_ids") or []
            if not ids:
                continue
            try:
                rc = self.jd.remove_links(ids)
                log.debug("AUTO CLEANUP | session=%s | row=%s | removed=%d | rc=%s",
                          self.session_id, info.get("row"), len(ids), rc if rc is not None else 200)
            except Exception as e:
                log.warning("AUTO CLEANUP failed for container=%s: %s", info.get("container_url"), e)
        self.awaiting_ack.clear()

        # Final clear
        try:
            self.jd.remove_all_from_linkgrabber()
            log.debug("SESSION FINALIZE | session=%s | linkgrabber_cleared=1", self.session_id)
        except Exception:
            pass

        log.info(
            "SUMMARY | session=%s | rows=%d | replaced=%d | online=%d | offline=%d | unknown=%d | cancelled=%s | dur=%.3f",
            self.session_id, self._rows, self._replaced, self._c_online, self._c_offline, self._c_unknown,
            False, time.monotonic() - self._start_time,
        )
        self.finished.emit({"session_id": self.session_id})
