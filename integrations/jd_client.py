import logging
from myjdapi import Myjdapi
log = logging.getLogger(__name__)
class JDClient:
    """
    My.JDownloader client with compatibility for both linkgrabberv2 and linkgrabber.
    """
    def __init__(self, email: str, password: str, device_name: str = "", app_key: str = "PyForumBot"):
        self.api = Myjdapi()
        self.email = (email or "").strip()
        self.password = (password or "").strip()
        self.device_name = (device_name or "").strip()
        self.app_key = (app_key or "PyForumBot").strip()
        self.device = None
        self.lg = None          # resolved linkgrabber proxy
        self.lg_mode = "none"   # "v2" | "v1" | "none"

    def connect(self) -> bool:
        try:
            if not self.email or not self.password:
                log.error("JD.connect: missing email/password")
                return False

            try:
                self.api.set_app_key(self.app_key)
            except Exception:
                pass

            log.debug("JD.connect: logging in to My.JDownloader (via connect)")
            self.api.connect(self.email, self.password)

            try:
                self.api.update_devices()
            except Exception:
                pass

            sel = None
            if self.device_name:
                try:
                    sel = self.api.get_device(self.device_name)
                except Exception:
                    sel = None
            if not sel:
                devices = getattr(self.api, "devices", {}) or {}
                if devices:
                    sel = next(iter(devices.values()))
            if not sel:
                log.error("JD.connect: no devices found on account")
                return False

            self.device = sel
            log.debug("JD.connect: selected device=%s", getattr(sel, "name", None) or "UNKNOWN")

            # حاول نجيب linkgrabberv2 ثم ارجع لـ linkgrabber
            self._resolve_linkgrabber()

            try:
                # معلومة الاتصال المباشر (اختياري)
                self.device.update_direct_connection_info()
            except Exception:
                pass

            if not self.lg:
                log.error("JD.connect: linkgrabber API not available on device")
                return False

            return True
        except Exception as e:
            log.exception("JD.connect: failed: %s", e)
            return False

    def _resolve_linkgrabber(self):
        # v2 أولاً
        lg = getattr(self.device, "linkgrabberv2", None)
        if lg:
            self.lg = lg
            self.lg_mode = "v2"
            log.debug("JD.connect: using linkgrabberv2")
            return
        # fallback: v1
        lg = getattr(self.device, "linkgrabber", None)
        if lg:
            self.lg = lg
            self.lg_mode = "v1"
            log.debug("JD.connect: using linkgrabber (v1)")
            return
        self.lg = None
        self.lg_mode = "none"

    def add_links_to_linkgrabber(
        self, urls: list[str], start_check: bool = True, package_name: str | None = None
    ) -> bool:
        """Send URLs to LinkGrabber.

        Parameters
        ----------
        urls:
            URLs or container links to push to JD.
        start_check:
            Whether to immediately trigger JD's ``startOnlineCheck`` after adding
            the links.  Some devices do not support this endpoint so failures are
            swallowed.
        package_name:
            Optional package name used to isolate links per session.  When
            provided, all added links are grouped under this package so that
            parallel sessions do not interfere with each other.
        """
        try:
            if not self.device:
                log.error("JD.add_links: device not ready")
                return False
            urls = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip()]
            if not urls:
                log.error("JD.add_links: empty url list")
                return False

            payload = {
                "autostart": False,
                "links": "\n".join(urls),
                "deepDecrypt": True,
                "checkAvailability": True,
            }
            if package_name:
                payload["packageName"] = package_name
            # NOTE: /linkgrabberv2/* expects a LIST of params
            self.device.action("/linkgrabberv2/addLinks", [payload])
            log.debug(
                "JD.add_links (raw): %d urls sent | package=%s",
                len(urls),
                package_name or "",
            )
            if start_check:
                try:
                    self.device.action("/linkgrabberv2/startOnlineCheck", [])
                except Exception:
                    pass
            return True
        except Exception as e:
            log.exception("JD.add_links: failed: %s", e)
            return False

    def query_links(self, package_uuid: str | None = None) -> list[dict]:
        """Query LinkGrabber links.

        When ``package_uuid`` is provided, only items belonging to that package
        are returned.  Each item returned will always contain a canonical
        ``uuid`` field regardless of how the underlying API names the
        identifier.
        """
        try:
            if not self.device:
                log.error("JD.query_links: device not ready")
                return []

            q = {
                "bytesTotal": True,
                "status": True,
                "host": True,
                "name": True,
                "availability": True,
                "size": True,
                "url": True,
                "contentURL": True,
                "pluginURL": True,
                # طلب الحقول المحتملة التي تعيد رابط الحاوية/المصدر
                "containerURL": True,
                "originURL": True,
                "originUrl": True,
                "sourceURL": True,
                "referrerURL": True,
                "packageUUID": True,
                "packageName": True,
                "startAt": 0,
                "maxResults": -1,
            }
            if package_uuid:
                q["packageUUIDs"] = [package_uuid]
            try:
                resp = self.device.action("/linkgrabberv2/queryLinks", [q]) or []
            except Exception:
                lg = (
                    self.lg
                    or getattr(self.device, "linkgrabberv2", None)
                    or getattr(self.device, "linkgrabber", None)
                )
                if lg and hasattr(lg, "query_links"):
                    resp = lg.query_links(q) or []
                else:
                    raise
            filtered: list[dict] = []

            for it in resp:
                # Normalise UUID field
                uid = it.get("uuid") or it.get("linkUUID") or it.get("id")
                if uid is not None:
                    it["uuid"] = str(uid)

                # Normalise availability
                av = (it.get("availability") or it.get("status") or "").upper()
                if av not in {"ONLINE", "OFFLINE"}:
                    av = "UNKNOWN"
                it["availability"] = av
                it["url"] = (
                    it.get("url")
                    or it.get("contentURL")
                    or it.get("pluginURL")
                    or ""
                )
                container = (
                    it.get("containerURL")
                    or it.get("originURL")
                    or it.get("originUrl")
                    or it.get("sourceURL")
                    or it.get("referrerURL")
                    or ""
                )
                it["containerURL"] = container
                filtered.append(it)

            log.debug(
                "JD.query_links (raw): %d items | package=%s",
                len(filtered),
                package_uuid or "",
            )
            return filtered
        except Exception as e:
            log.exception("JD.query_links: failed: %s", e)
            return []

    def start_online_check(self, link_ids) -> bool:
        """Trigger availability check for specific LinkGrabber entries."""
        try:
            if not self.device:
                log.error("JD.start_online_check: device not ready")
                return False
            ids = []
            for uid in link_ids or []:
                if uid is None:
                    continue
                try:
                    ids.append(int(uid))
                except Exception:
                    ids.append(uid)
            self.device.action("/linkgrabberv2/startOnlineCheck", [ids])
            return True
        except Exception as e:
            log.exception("JD.start_online_check: failed: %s", e)
            return False
    def remove_links(self, link_ids) -> bool:
        """Remove specific LinkGrabber entries by their UUIDs."""
        try:
            if not self.device:
                log.error("JD.remove_links: device not ready")
                return False
            ids = []
            for uid in link_ids or []:
                if uid is None:
                    continue
                try:
                    ids.append(int(uid))
                except Exception:
                    ids.append(uid)
            if not ids:
                return True

            try:
                self.device.action("/linkgrabberv2/removeLinks", [ids])
                log.debug("JD.remove_links: removed %d items via [ids]", len(ids))
                return True
            except Exception:
                pass

            try:
                self.device.action("/linkgrabberv2/removeLinks", [{"linkIds": ids}])
                log.debug("JD.remove_links: removed %d items via {'linkIds': [...]}" , len(ids))
                return True
            except Exception:
                pass

            lg = self.lg or getattr(self.device, "linkgrabberv2", None) or getattr(self.device, "linkgrabber", None)
            if lg and hasattr(lg, "remove_links"):
                try:
                    lg.remove_links(ids)
                    log.debug("JD.remove_links: removed %d items via wrapper.remove_links", len(ids))
                    return True
                except Exception:
                    pass
            log.error("JD.remove_links: all removal attempts failed")
            return False
        except Exception as e:
            log.exception("JD.remove_links: failed: %s", e)
            return False
    def remove_all_from_linkgrabber(self) -> bool:
        """
        Clear LinkGrabber entries. Be tolerant with parameter forms and ID types.
        """
        try:
            if not self.device:
                log.error("JD.clear: device not ready")
                return False

            items = self.query_links()
            if not items:
                log.debug("JD.clear: nothing to remove (no items)")
                return True

            link_ids = []
            for i in items:
                uid = i.get("uuid")
                if uid is None:
                    continue
                try:
                    link_ids.append(int(uid))
                except Exception:
                    link_ids.append(uid)

            if not link_ids:
                log.debug("JD.clear: nothing to remove (no ids)")
                return True

            # Try multiple shapes for compatibility
            try:
                self.device.action("/linkgrabberv2/removeLinks", [link_ids])
                log.debug("JD.clear: removed %d items via [linkIds]", len(link_ids))
                return True

            except Exception:
                pass

            try:
                self.device.action("/linkgrabberv2/removeLinks", [{"linkIds": link_ids}])
                log.debug("JD.clear: removed %d items via {'linkIds': [...]}" , len(link_ids))
                return True

            except Exception:
                pass

            try:
                lg = self.lg or getattr(self.device, "linkgrabberv2", None) or getattr(self.device, "linkgrabber", None)
                if lg and hasattr(lg, "remove_links"):
                    lg.remove_links(link_ids)
                    log.debug("JD.clear: removed %d items via wrapper.remove_links", len(link_ids))
                    return True

            except Exception:
                pass
            # As a last resort, try removing packages
            try:
                pkg_query = {
                    "bytesTotal": True,
                    "status": True,
                    "hosts": True,
                    "saveTo": True,
                    "packageUUIDs": True,
                    "childCount": True,
                    "startAt": 0,
                    "maxResults": -1
                }
                pkgs = self.device.action("/linkgrabberv2/queryPackages", [pkg_query]) or []
                pkg_ids = []
                for p in pkgs:
                    puid = p.get("packageUUID")
                    if puid is None:
                        continue
                    try:
                        pkg_ids.append(int(puid))
                    except Exception:
                        pkg_ids.append(puid)

                if pkg_ids:
                    try:
                        self.device.action("/linkgrabberv2/removePackages", [pkg_ids])
                        log.debug("JD.clear: removed %d packages via [pkgIds]", len(pkg_ids))
                        return True
                    except Exception:

                        self.device.action("/linkgrabberv2/removePackages", [{"packageIds": pkg_ids}])
                        log.debug("JD.clear: removed %d packages via {'packageIds': [...]}" , len(pkg_ids))
                        return True
            except Exception:
                pass

            log.error("JD.clear: all removal attempts failed")
            return False

        except Exception as e:
            log.exception("JD.clear: failed: %s", e)
            return False

