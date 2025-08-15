# integrations/jd_client.py
# -*- coding: utf-8 -*-
import logging
from typing import List, Iterable, Optional

try:
    from myjdapi import Myjdapi
except Exception as e:
    raise ImportError("myjdapi is required. Install via: pip install myjdapi") from e

log = logging.getLogger(__name__)

class JDClient:
    """
    Drop-in client that matches the old GUI expectations:
      - __init__(email, password, device_name="", app_key="PyForumBot")
      - connect()
      - add_links_to_linkgrabber(urls: list[str], start_check: bool = True) -> bool
      - query_links() -> list[dict]
      - start_online_check(link_ids) -> bool
      - remove_links(link_ids) -> bool
      - remove_all_from_linkgrabber() -> bool
      - abort_linkgrabber() -> bool  <-- جديد لإيقاف الفحص ومسح كل شيء

    Internally uses `myjdapi`, so you don't deal with signatures/HMAC.
    """
    def __init__(self, email: str, password: str, device_name: str = "", app_key: str = "PyForumBot"):
        self.api = Myjdapi()
        self.email = (email or "").strip()
        self.password = (password or "").strip()
        self.device_name = (device_name or "").strip()
        self.app_key = (app_key or "PyForumBot").strip()
        self.device = None

    def connect(self) -> bool:
        try:
            if not self.email or not self.password:
                log.error("JD.connect: missing email/password")
                return False

            try:
                self.api.set_app_key(self.app_key)
            except Exception:
                pass

            log.debug("JD.connect: logging in to My.JDownloader (myjdapi)")
            self.api.connect(self.email, self.password)

            # pick device
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
                    sel = list(devices.values())[0]
            if not sel:
                log.error("JD.connect: no devices")
                return False

            self.device = sel
            log.debug("JD.connect: selected device=%s", getattr(self.device, "name", None))
            return True
        except Exception as e:
            log.exception("JD.connect failed: %s", e)
            return False

    def add_links_to_linkgrabber(self, urls: List[str], start_check: bool = True) -> bool:
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
            # /linkgrabberv2/* expects a LIST of params
            self.device.action("/linkgrabberv2/addLinks", [payload])
            log.debug("JD.add_links (raw): %d urls sent", len(urls))
            if start_check:
                try:
                    self.device.action("/linkgrabberv2/startOnlineCheck", [])
                except Exception:
                    try:
                        self.device.linkgrabberv2.start_online_check([])
                    except Exception:
                        pass
            return True
        except Exception as e:
            log.exception("JD.add_links failed: %s", e)
            return False

    def start_online_check(self, link_ids) -> bool:
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

    def query_links(self) -> list:
        try:
            if not self.device:
                return []
            query = {
                "bytesTotal": True,
                "status": True,
                "host": True,
                "name": True,
                "availability": True,
                "size": True,
                "url": True,
                "contentURL": True,
                "pluginURL": True,
                "containerURL": True,
                "origin": True,
                "variant": True,
                "packageUUID": True,
                "uuid": True,
            }
            res = self.device.action("/linkgrabberv2/queryLinks", [query]) or []
            if isinstance(res, dict):
                res = [res]
            log.debug("JD.query_links (raw): %d items", len(res))
            return res
        except Exception as e:
            log.exception("JD.query_links failed: %s", e)
            return []

    def remove_links(self, link_ids: Iterable) -> bool:
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
            # Try several variants to maximize compatibility
            try:
                self.device.action("/linkgrabberv2/removeLinks", [{"linkIds": ids}])
                log.debug("JD.remove_links: removed %d items via {'linkIds': [...]}",
                          len(ids))
                return True
            except Exception:
                pass
            try:
                self.device.linkgrabberv2.remove_links(ids)
                log.debug("JD.remove_links: removed %d items via wrapper.remove_links",
                          len(ids))
                return True
            except Exception:
                pass
            # Fallback: remove by packages
            pkg_query = {"packageUUIDs": True}
            pkgs = self.device.action("/linkgrabberv2/queryPackages", [pkg_query]) or []
            pkg_ids = [p.get("packageUUID") for p in pkgs if p.get("packageUUID")]
            if pkg_ids:
                self.device.action("/linkgrabberv2/removePackages", [{"packageIds": pkg_ids}])
                log.debug("JD.remove_links: removed by packages: %d", len(pkg_ids))
                return True
            return False
        except Exception as e:
            log.exception("JD.remove_links failed: %s", e)
            return False

    def remove_all_from_linkgrabber(self) -> bool:
        try:
            if not self.device:
                return False
            # Try new API first
            try:
                self.device.action("/linkgrabberv2/clearList", [])
                log.debug("JD.clear: cleared via /linkgrabberv2/clearList")
                return True
            except Exception:
                pass
            # Fallback: enumerate and remove
            items = self.query_links() or []
            ids = [it.get("uuid") for it in items if it.get("uuid")]
            if not ids:
                log.debug("JD.clear: nothing to remove (no items)")
                return True
            return self.remove_links(ids)
        except Exception as e:
            log.exception("JD.clear failed: %s", e)
            return False

    # ====== جديد: إيقاف أى فحص جارٍ ومسح القائمة فورًا ======
    def abort_linkgrabber(self) -> bool:
        """
        حاول إيقاف أي فحص/فك تشفير جارٍ في LinkGrabber، وبعدين امسح القائمة.
        بنجرّب كذا endpoint علشان التوافق بين نسخ JDownloader.
        """
        if not self.device:
            return False
        ok = False
        # جرّب شوية endpoints محتملة للإلغاء
        for ep, body in [
            ("/linkgrabberv2/cancel", []),
            ("/linkgrabberv2/abort", []),
            ("/linkgrabberv2/stopOnlineCheck", []),
            ("/linkgrabberv2/abortLinkGrabberTasks", []),
        ]:
            try:
                self.device.action(ep, body)
                log.debug("JD.abort: called %s", ep)
                ok = True
            except Exception:
                pass
        # في كل الأحوال امسح القائمة
        try:
            self.device.action("/linkgrabberv2/clearList", [])
            log.debug("JD.abort: cleared linkgrabber list")
            ok = True
        except Exception:
            # fallback قديم: إزالة بما هو متاح
            items = self.query_links() or []
            ids = [it.get("uuid") for it in items if it.get("uuid")]
            if ids:
                self.remove_links(ids)
                ok = True
        return ok
