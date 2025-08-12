import logging
from myjdapi import Myjdapi

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
                logging.error("JD.connect: missing email/password")
                return False

            try:
                self.api.set_app_key(self.app_key)
            except Exception:
                pass

            logging.debug("JD.connect: logging in to My.JDownloader (via connect)")
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
                logging.error("JD.connect: no devices found on account")
                return False

            self.device = sel
            logging.debug("JD.connect: selected device=%s", getattr(sel, "name", None) or "UNKNOWN")

            # حاول نجيب linkgrabberv2 ثم ارجع لـ linkgrabber
            self._resolve_linkgrabber()

            try:
                # معلومة الاتصال المباشر (اختياري)
                self.device.update_direct_connection_info()
            except Exception:
                pass

            if not self.lg:
                logging.error("JD.connect: linkgrabber API not available on device")
                return False

            return True
        except Exception as e:
            logging.exception("JD.connect: failed: %s", e)
            return False

    def _resolve_linkgrabber(self):
        # v2 أولاً
        lg = getattr(self.device, "linkgrabberv2", None)
        if lg:
            self.lg = lg
            self.lg_mode = "v2"
            logging.debug("JD.connect: using linkgrabberv2")
            return
        # fallback: v1
        lg = getattr(self.device, "linkgrabber", None)
        if lg:
            self.lg = lg
            self.lg_mode = "v1"
            logging.debug("JD.connect: using linkgrabber (v1)")
            return
        self.lg = None
        self.lg_mode = "none"

    def add_links_to_linkgrabber(self, urls: list[str]) -> bool:
        """
        Send URLs (including keeplinks) to LinkGrabber with deepDecrypt=True.
        """
        try:
            if not self.device:
                logging.error("JD.add_links: device not ready")
                return False
            urls = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip()]
            if not urls:
                logging.error("JD.add_links: empty url list")
                return False

            payload = {
                "autostart": False,
                "links": "\n".join(urls),
                "deepDecrypt": True,
                "checkAvailability": True,
            }
            # NOTE: /linkgrabberv2/* expects a LIST of params
            self.device.action("/linkgrabberv2/addLinks", [payload])
            logging.debug("JD.add_links (raw): %d urls sent", len(urls))
            # Try to trigger online check (safe if unsupported)
            try:
                self.device.action("/linkgrabberv2/startOnlineCheck", [])
            except Exception:
                pass
            return True
        except Exception as e:
            logging.exception("JD.add_links: failed: %s", e)
            return False

    def query_links(self) -> list[dict]:
        """
        Query LinkGrabber links after JD expands containers (keeplinks etc.).
        """
        try:
            if not self.device:
                logging.error("JD.query_links: device not ready")
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
                "packageUUID": True,
                "packageName": True,
                "containerURL": True,
                "startAt": 0,
                "maxResults": -1,
            }
            try:
                resp = self.device.action("/linkgrabberv2/queryLinks", [q]) or []
            except Exception:
                lg = self.lg or getattr(self.device, "linkgrabberv2", None) or getattr(self.device, "linkgrabber", None)
                if lg and hasattr(lg, "query_links"):
                    resp = lg.query_links(q) or []
                else:
                    raise
            for it in resp:
                it["url"] = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
            logging.debug("JD.query_links (raw): %d items", len(resp))
            return resp
        except Exception as e:
            logging.exception("JD.query_links: failed: %s", e)
            return []

    def remove_all_from_linkgrabber(self) -> bool:
        """
        Clear LinkGrabber entries. Be tolerant with parameter forms and ID types.
        """
        try:
            if not self.device:
                logging.error("JD.clear: device not ready")
                return False

            items = self.query_links()
            if not items:
                logging.debug("JD.clear: nothing to remove (no items)")
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
                logging.debug("JD.clear: nothing to remove (no ids)")
                return True

            # Try multiple shapes for compatibility
            try:
                self.device.action("/linkgrabberv2/removeLinks", [link_ids])
                logging.debug("JD.clear: removed %d items via [linkIds]", len(link_ids))
                return True

            except Exception:
                pass

            try:
                self.device.action("/linkgrabberv2/removeLinks", [{"linkIds": link_ids}])
                logging.debug("JD.clear: removed %d items via {'linkIds': [...]}" , len(link_ids))
                return True

            except Exception:
                pass

            try:
                lg = self.lg or getattr(self.device, "linkgrabberv2", None) or getattr(self.device, "linkgrabber", None)
                if lg and hasattr(lg, "remove_links"):
                    lg.remove_links(link_ids)
                    logging.debug("JD.clear: removed %d items via wrapper.remove_links", len(link_ids))
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
                        logging.debug("JD.clear: removed %d packages via [pkgIds]", len(pkg_ids))
                        return True
                    except Exception:

                        self.device.action("/linkgrabberv2/removePackages", [{"packageIds": pkg_ids}])
                        logging.debug("JD.clear: removed %d packages via {'packageIds': [...]}" , len(pkg_ids))
                        return True
            except Exception:
                pass

            logging.error("JD.clear: all removal attempts failed")
            return False

        except Exception as e:
            logging.exception("JD.clear: failed: %s", e)
            return False

